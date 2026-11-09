"""对真实冻结sidecar验证协议、HTTP边界、错误挑战和EOF退出。"""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import build_opener, ProxyHandler, Request


def request(origin, path, data=None, headers=None):
    """仅访问当前实例loopback，禁用环境HTTP代理。"""
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(Request(origin + path, data=data, headers=headers or {}), timeout=4) as response:
            return response.status, response.read()
    except HTTPError as error:
        with error:
            return error.code, error.read()


def exercise(executable, root, mode):
    """启动完整原生可执行文件，任何测试失败均清理自己的子进程。"""
    challenge, instance = secrets.token_hex(32), secrets.token_hex(16)
    user_data = root / ('合成 Data ' + mode)
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith(('FLOW', 'PYTHON', 'PYINSTALLER'))}
    environment.update(PYTHONDONTWRITEBYTECODE='1', PYINSTALLER_RESET_ENVIRONMENT='1')
    with (root / (mode + '.log')).open('wb') as log:
        started = time.monotonic()
        child = subprocess.Popen([str(executable)], cwd=root, env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log)
        pool = concurrent.futures.ThreadPoolExecutor(1)
        try:
            if mode in ('init-eof', 'init-timeout'):
                if mode == 'init-eof':
                    child.stdin.close()
                # Include native bootloader/extraction in the host's budget.
                assert child.wait(timeout=30) == 2, '无效首报文退出码异常'
                assert child.stdout.read() == b'', '首报文前意外就绪'
                assert not user_data.exists(), '首报文前创建了用户目录'
                return
            message = {'type': 'init', 'version': 1, 'challenge': challenge,
                       'instanceId': instance, 'userData': str(user_data)}
            child.stdin.write((json.dumps(message) + '\n').encode())
            child.stdin.flush()
            remaining = max(0, 30 - (time.monotonic() - started))
            line = pool.submit(child.stdout.readline, 16385).result(timeout=remaining)
            assert line, f'sidecar在就绪前退出，日志: {root / (mode + ".log")}'
            ready = json.loads(line)
            assert len(line) <= 16384 and ready['type'] == 'ready' and ready['version'] == 1, '无效就绪协议'
            assert ready['challenge'] == challenge and ready['instanceId'] == instance, '挑战码不匹配'
            assert type(ready['port']) is int and 0 < ready['port'] <= 65535, '无效端口'
            origin = f"http://127.0.0.1:{ready['port']}"
            if mode == 'shutdown':
                assert request(origin, '/')[0] == 200, '静态首页不可用'
                assert request(origin, '/api/health')[0] == 200, '健康状态不可用'
                for path in ('/.env', '/server.py', '/unknown', '/data/portfolio.sqlite3', '/api/shutdown'):
                    assert request(origin, path)[0] == 404, '未知资源被公开'
                for path, request_origin, expected in (
                    ('/api/private/session', '', 403),
                    ('/api/private/session', 'https://evil.invalid', 403),
                    ('/api/private/accounts', origin, 401),
                    ('/api/private/session', origin, 200),
                ):
                    headers = {'Content-Type': 'application/json'}
                    if request_origin:
                        headers['Origin'] = request_origin
                    assert request(origin, path, b'{}', headers)[0] == expected, '私有API边界异常'
                assert not (user_data / 'private').exists(), '拒绝请求创建了私有存储'
                with socket.socket() as contender:
                    try:
                        contender.bind(('127.0.0.1', ready['port']))
                    except OSError:
                        pass
                    else:
                        raise AssertionError('sidecar没有独占已报告的端口')
            if mode == 'eof':
                child.stdin.close()
            else:
                command = {'type': 'shutdown', 'version': 1, 'instanceId': instance,
                           'challenge': challenge if mode == 'shutdown' else 'invalid'}
                child.stdin.write((json.dumps(command) + '\n').encode())
                child.stdin.flush()
            code = child.wait(timeout=8)
            assert code == (0 if mode != 'bad-challenge' else 2), 'sidecar退出码异常'
            assert child.stdout.read() == b'', 'stdout混入了普通日志'
            try:
                connection = socket.create_connection(('127.0.0.1', ready['port']), timeout=1)
            except OSError:
                pass
            else:
                connection.close()
                raise AssertionError('sidecar退出后端口仍在监听')
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
            for stream in (child.stdin, child.stdout):
                stream.close()
            pool.shutdown(wait=False, cancel_futures=True)


def main():
    """从命令行接受打包可执行文件，只生成临时合成目录。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sidecar', type=Path, required=True)
    args = parser.parse_args()
    executable = args.sidecar.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='flowdesk smoke 中文 ') as temporary:
        for mode in ('shutdown', 'eof', 'bad-challenge', 'init-eof', 'init-timeout'):
            exercise(executable, Path(temporary).resolve(), mode)
    print(json.dumps({'ok': True, 'checks': ['ready', 'http', 'private-origin', 'nonce', 'shutdown', 'eof', 'init-eof', 'init-timeout', 'port-release']}))


if __name__ == '__main__':
    main()
