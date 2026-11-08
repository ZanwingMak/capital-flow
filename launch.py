"""Flowdesk 的 macOS 本机启动入口；仅使用标准库协调环境、页面和行情连接。"""
import argparse
import hashlib
import http.client
import ipaddress
import json
import logging.handlers
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from io import StringIO
from unittest.mock import patch
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parent
APP_ID = 'flowdesk'


class LaunchError(Exception):
    """只携带可公开的中文错误，不拼接第三方异常或响应。"""


def load_quiet_sdk():
    """屏蔽 SDK 默认文件日志及控制台日志，避免状态检查写入用户目录。"""
    original_makedirs = os.makedirs

    def sdk_makedirs(path, *args, **kwargs):
        """仅跳过 SDK 默认日志目录；其他依赖仍保留原本的目录操作。"""
        if str(path).endswith('/.com.futunn.FutuOpenD/Log'):
            return None
        return original_makedirs(path, *args, **kwargs)

    # SDK 没有禁用导入时文件日志的公开开关，替换仅限导入阶段，不改 HOME。
    with redirect_stdout(StringIO()), redirect_stderr(StringIO()), \
            patch('os.makedirs', side_effect=sdk_makedirs), \
            patch('logging.handlers.TimedRotatingFileHandler', return_value=logging.NullHandler()):
        import futu
    futu.SysConfig.set_all_thread_daemon(True)
    futu.SysConfig.enable_console_log(False)
    return futu


def futu_state(host, port):
    """只调用行情全局状态，立即丢弃原始字典，仅保留连接和行情登录布尔值。"""
    context = None
    try:
        sdk = load_quiet_sdk()
        context = sdk.OpenQuoteContext(host=host, port=port)
        ret, state = context.get_global_state()
        reachable = ret == sdk.RET_OK and isinstance(state, dict)
        logged_in = reachable and state.get('qot_logined') in (True, 1, '1')
        return {'reachable': reachable, 'quoteLoggedIn': bool(logged_in)}
    except Exception:
        return {'reachable': False, 'quoteLoggedIn': False}
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass


def probe_futu(python, root, host, port):
    """在可超时终止的独立进程内核验行情登录，禁止原始 SDK 响应外泄。"""
    if python is None or not port_open(host, port):
        return 'unavailable'
    try:
        result = subprocess.run([str(python), '-B', str(root / 'launch.py'), '--probe-futu', host, str(port)],
            cwd=root, capture_output=True, text=True, timeout=6)
        state = json.loads(result.stdout) if result.returncode == 0 else {}
        if isinstance(state, dict) and state.get('reachable') is True:
            return 'ready' if state.get('quoteLoggedIn') is True else 'login'
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return 'unavailable'


def is_loopback(host):
    """只将明确的 loopback 地址及 localhost 视为可以启动本机 App 的目标。"""
    if host.lower() == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def ensure_futu(python, root, host, port):
    """复用现有 OpenD，仅为本机关闭的接口启动已安装 App 并有界等待。"""
    state = probe_futu(python, root, host, port)
    if state != 'unavailable':
        return state
    if not is_loopback(host):
        return 'remote-unavailable'
    if port_open(host, port):
        return 'unavailable'
    app = Path('/Applications/Futu_OpenD.app')
    if not app.is_dir():
        return 'missing-app'
    try:
        subprocess.run(['/usr/bin/open', '-g', str(app)], check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return 'app-failed'
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        state = probe_futu(python, root, host, port)
        if state != 'unavailable':
            return state
        time.sleep(0.5)
    return 'unavailable'


def dependencies_available(python, root):
    """在独立解释器内检查 SDK 可导入性，屏蔽第三方原始输出。"""
    try:
        result = subprocess.run([str(python), '-B', str(root / 'launch.py'), '--check-deps'],
            cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def ensure_python(root, install=True):
    """优先复用项目环境；仅在缺失时创建 venv 或安装 requirements。"""
    python = root / '.venv' / 'bin' / 'python'
    if not python.is_file():
        if not install:
            return None
        if (root / '.venv').exists():
            raise LaunchError('现有 .venv 不完整，请手动移走后重试；启动器不会覆盖它。')
        print('首次启动：正在创建项目 .venv …', flush=True)
        try:
            subprocess.run([sys.executable, '-B', '-m', 'venv', str(root / '.venv')],
                cwd=root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        except (OSError, subprocess.SubprocessError):
            raise LaunchError('创建 .venv 失败，请安装包含 venv/pip 的 Python 3.10 或更新版本；不修改全局 Python。') from None
    if dependencies_available(python, root):
        return python
    if not install:
        return None
    print('缺少可用依赖：正在向项目 .venv 安装 requirements.txt …', flush=True)
    try:
        subprocess.run([str(python), '-B', '-m', 'pip', '--require-virtualenv', '--disable-pip-version-check',
            'install', '-r', str(root / 'requirements.txt')], cwd=root, check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
    except (OSError, subprocess.SubprocessError):
        raise LaunchError('依赖联网安装失败，请检查网络及 Python 版本后重试；原始安装输出已隐藏。') from None
    if not dependencies_available(python, root):
        raise LaunchError('依赖安装后仍无法加载，请检查 Python 兼容性，或手动重建项目 .venv。')
    return python


def project_id(root):
    """用规范化项目目录生成稳定标识，健康接口不公开绝对路径。"""
    return hashlib.sha256(str(root.resolve()).encode('utf-8')).hexdigest()


def port_open(host, port):
    """有界检查 TCP 可连接性；此结果不代表行情已登录。"""
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def health_response(host, port):
    """绕过代理读取本机健康响应，认证令牌仅通过请求头传递。"""
    request = Request(f'http://{host}:{port}/api/health')
    token = os.getenv('FLOW_TOKEN', '')
    if token:
        request.add_header('Authorization', 'Bearer ' + token)
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=1) as response:
            return json.loads(response.read(65536))
    except (OSError, ValueError, http.client.HTTPException):
        return None


def service_state(root, host, port):
    """区分空闲、同项目服务与未知占用，绝不根据 PID 猜测归属。"""
    if not port_open(host, port):
        return 'absent'
    body = health_response(host, port)
    if isinstance(body, dict) and body.get('app') == APP_ID and body.get('projectId') == project_id(root) \
            and isinstance(body.get('serviceVersion'), int) and body['serviceVersion'] >= 4:
        return 'matching'
    return 'conflict'


@contextmanager
def startup_lock(root, timeout=30):
    """以内核文件锁串行化双击启动；始终保留锁文件以避免 inode 竞争。"""
    import fcntl
    data = root / '.data'
    data.mkdir(mode=0o700, exist_ok=True)
    with (data / 'startup.lock').open('a') as handle:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise LaunchError('另一个启动器仍在工作，请稍后再双击；没有启动重复服务。') from None
                time.sleep(0.2)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def cleanup_child(process):
    """失败时仅回收本次 Popen 创建的子进程，绝不读取 PID 文件实施终止。"""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def ensure_service(root, python, host, port):
    """复用身份匹配的服务，或脱离终端启动本项目并有界等待健康接口。"""
    state = service_state(root, host, port)
    if state == 'matching':
        return False
    if state == 'conflict':
        raise LaunchError(f'网页端口 {port} 已被其他服务、另一份项目或无法认证的旧服务占用；请核实后自行处理，启动器不会终止它。')
    logfile, pidfile = root / '.data' / 'flowdesk.log', root / '.data' / 'server.pid'
    try:
        with logfile.open('ab', buffering=0) as output:
            process = subprocess.Popen([str(python), '-B', str(root / 'launch.py'), '--serve'], cwd=root,
                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    except OSError:
        raise LaunchError(f'后台服务无法启动；请检查项目环境和日志位置：{logfile}') from None
    try:
        pidfile.write_text(str(process.pid) + '\n', encoding='ascii')
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise LaunchError(f'后台服务提前退出；请检查本地日志：{logfile}（不自动打印内容）。')
            if service_state(root, host, port) == 'matching':
                return True
            time.sleep(0.2)
        raise LaunchError(f'后台服务健康检查超时；请检查本地日志：{logfile}（不自动打印内容）。')
    except (LaunchError, OSError, KeyboardInterrupt):
        cleanup_child(process)
        pidfile.unlink(missing_ok=True)
        raise


def alpaca_configured():
    """仅调用既有状态函数取得配置布尔值，不读取或输出密钥。"""
    import alpaca_data
    try:
        return bool(alpaca_data.status()['configured'])
    except Exception:
        return None


def open_browser(url):
    """使用 macOS 默认浏览器打开已就绪的本机页面，不向 URL 附加令牌。"""
    try:
        subprocess.run(['/usr/bin/open', url], check=True, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=5)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def settings():
    """读取已配置环境，仅允许本机网页监听，并安全校验两个端口。"""
    host = os.getenv('FLOW_HOST', '127.0.0.1')
    if host not in {'127.0.0.1', 'localhost'}:
        raise LaunchError('此一键入口仅支持 FLOW_HOST=127.0.0.1 或 localhost；远程部署仍需使用原服务的安全配置。')
    try:
        port, futu_port = int(os.getenv('FLOW_PORT', '8788')), int(os.getenv('FUTU_PORT', '11111'))
        if not (1 <= port <= 65535 and 1 <= futu_port <= 65535):
            raise ValueError
    except ValueError:
        raise LaunchError('FLOW_PORT 和 FUTU_PORT 必须是 1 至 65535 之间的整数。') from None
    return host, port, os.getenv('FUTU_HOST', '127.0.0.1'), futu_port


def report(root, url, service, futu, configured):
    """展示本机 URL、有限就绪状态和日志位置，不将配置齐全说成鉴权成功。"""
    web = {'matching': '已就绪', 'absent': '未运行', 'conflict': '端口冲突'}[service]
    messages = {'ready': '就绪（行情登录=true；具体市场权限仍以查询为准）',
        'login': '未就绪（行情登录=false；请在 OpenD 中本人登录）',
        'unavailable': '未就绪（接口不可用或核验超时；请检查 OpenD、本人登录及 API 设置）',
        'missing-app': '未就绪（未找到 Futu_OpenD.app，请先自行安装并本人登录）',
        'remote-unavailable': '未就绪（配置的远程接口不可用；未启动本机 App）',
        'app-failed': '未就绪（无法打开 OpenD，请手动打开并本人登录）'}
    print(f'网页：{web}\nURL：{url}')
    print('Futu：' + messages[futu])
    label = '配置齐全' if configured is True else '配置不齐全' if configured is False else '配置状态未知'
    print(f'Alpaca：{label}；权限未验证（不影响网页基本功能）。')
    print(f'本地日志：{root / ".data" / "flowdesk.log"}')


def main(argv=None, root=ROOT):
    """协调本机只读启动；0 表示网页及 Futu 就绪，2 表示部分就绪，1 表示失败。"""
    parser = argparse.ArgumentParser(description='Flowdesk 本机启动器（只读行情，不交易）')
    parser.add_argument('--no-browser', action='store_true', help='启动但不打开浏览器')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--status', action='store_true', help='只检查状态，不安装、不启动、不写文件')
    mode.add_argument('--check-deps', action='store_true', help=argparse.SUPPRESS)
    mode.add_argument('--probe-futu', nargs=2, metavar=('HOST', 'PORT'), help=argparse.SUPPRESS)
    mode.add_argument('--serve', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.check_deps:
        try:
            from importlib.metadata import version
            if not 9 <= int(version('futu-api').split('.')[0]) < 11:
                return 1
            load_quiet_sdk()
            return 0
        except Exception:
            return 1
    if args.probe_futu:
        state = futu_state(args.probe_futu[0], int(args.probe_futu[1]))
        print(json.dumps(state))
        return 0
    if args.serve:
        try:
            load_quiet_sdk()
            import server
            server.main()
            return 0
        except Exception as error:
            print('后台服务启动或运行失败：' + type(error).__name__, flush=True)
            return 1
    try:
        host, port, futu_host, futu_port = settings()
        url = f'http://{host}:{port}/'
        if args.status:
            python = ensure_python(root, install=False)
            service = service_state(root, host, port)
            futu = probe_futu(python, root, futu_host, futu_port)
            report(root, url, service, futu, alpaca_configured())
            if python is None:
                print('项目环境：缺少可用 .venv 或依赖；本次只检查，未安装。')
            return 0 if service == 'matching' and futu == 'ready' else 2
        with startup_lock(root):
            if service_state(root, host, port) == 'conflict':
                raise LaunchError(f'网页端口 {port} 被其他服务、另一份项目或无法认证的旧服务占用；未终止任何服务。')
            python = ensure_python(root)
            started = ensure_service(root, python, host, port)
            print('已启动本项目后台服务。' if started else '已复用本项目健康服务。')
            futu = ensure_futu(python, root, futu_host, futu_port)
        report(root, url, 'matching', futu, alpaca_configured())
        if futu != 'ready':
            print('部分就绪：网页可访问；Futu 行情尚未就绪，处理提示后可再次双击。')
        if not args.no_browser and not open_browser(url):
            print('无法自动打开浏览器，请手动访问上面的 URL。')
            return 1
        return 0 if futu == 'ready' else 2
    except LaunchError as error:
        print('启动失败：' + str(error))
        return 1
    except (OSError, subprocess.SubprocessError):
        print('启动失败：无法完成本机文件或进程操作，请检查项目权限及 .data/flowdesk.log；未打印原始异常。')
        return 1
    except KeyboardInterrupt:
        print('已取消启动。')
        return 1


if __name__ == '__main__':
    sys.exit(main())
