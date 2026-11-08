"""启动器离线行为测试：合成响应与进程，不连接真实行情或服务端口。"""
import hashlib
import fcntl
import subprocess
import io
import sys
import runpy
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import Mock, patch, mock_open

import launch
import server


class HealthTests(unittest.TestCase):
    """同项目身份识别必须兼容原健康字段且不公开目录。"""

    def test_health_keeps_fields_and_identifies_project(self):
        """真实处理器返回固定应用名及目录哈希，保留既有字段。"""
        handler = server.Handler.__new__(server.Handler)
        handler.path, handler.headers, handler.respond = '/api/health', {}, Mock()
        with patch.object(server, 'TOKEN', ''):
            handler.do_GET()
        code, body = handler.respond.call_args.args
        self.assertEqual(code, 200)
        self.assertEqual(body['app'], 'flowdesk')
        self.assertEqual(body['projectId'], launch.project_id(Path(server.__file__).parent))
        self.assertEqual(body['serviceVersion'], 4)
        self.assertEqual(body['source'], 'futu-opend')
        self.assertIn('research', body['features'])
        self.assertNotIn(str(Path(server.__file__).parent), str(body))

    def test_identity_is_stable_and_directory_specific(self):
        """路径中空格和中文参与不可逆标识，不暴露明文。"""
        root = Path('/synthetic/Flow desk 项目')
        self.assertEqual(launch.project_id(root), hashlib.sha256(str(root.resolve()).encode()).hexdigest())
        self.assertNotEqual(launch.project_id(root), launch.project_id(root / 'other'))

    def test_reuse_matching_service_and_reject_other_owner(self):
        """健康标识匹配时直接复用，其他服务不能被当作本项目。"""
        root = Path('/synthetic/Flow desk')
        matching = {'app': 'flowdesk', 'projectId': launch.project_id(root), 'serviceVersion': 4}
        with patch.object(launch, 'port_open', return_value=True), \
                patch.object(launch, 'health_response', return_value=matching):
            self.assertEqual(launch.service_state(root, '127.0.0.1', 8788), 'matching')
        for body in ({}, {**matching, 'app': 'other'}, {**matching, 'projectId': 'other'}, None):
            with self.subTest(body=body), patch.object(launch, 'port_open', return_value=True), \
                    patch.object(launch, 'health_response', return_value=body):
                self.assertEqual(launch.service_state(root, '127.0.0.1', 8788), 'conflict')


class ServiceTests(unittest.TestCase):
    """服务启动使用合成进程，所有文件和网络边界均被隔离。"""

    def test_matching_service_is_reused_without_spawning(self):
        """复用健康服务时不新建日志或进程。"""
        with patch.object(launch, 'service_state', return_value='matching'), \
                patch.object(launch.subprocess, 'Popen') as spawn, patch.object(Path, 'open') as opened:
            self.assertFalse(launch.ensure_service(Path('/synthetic'), Path('/python'), '127.0.0.1', 8788))
        spawn.assert_not_called()
        opened.assert_not_called()

    def test_other_service_is_never_killed_or_replaced(self):
        """端口占用明确失败，不能靠 kill 抢端口。"""
        with patch.object(launch, 'service_state', return_value='conflict'), \
                patch.object(launch.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(launch.LaunchError, '端口.*占用'):
                launch.ensure_service(Path('/synthetic'), Path('/python'), '127.0.0.1', 8788)
        spawn.assert_not_called()

    def test_started_service_is_detached_and_records_only_own_pid(self):
        """后台服务关闭标准输入并创建独立 session，不依赖终端 job。"""
        root, process = Path('/synthetic/Flow desk'), Mock(pid=43210)
        process.poll.return_value = None
        with patch.object(launch, 'service_state', side_effect=['absent', 'matching']), \
                patch.object(Path, 'open', mock_open()), patch.object(Path, 'write_text') as write, \
                patch.object(launch.subprocess, 'Popen', return_value=process) as spawn:
            self.assertTrue(launch.ensure_service(root, Path('/python'), '127.0.0.1', 8788))
        self.assertTrue(spawn.call_args.kwargs['start_new_session'])
        self.assertEqual(spawn.call_args.kwargs['stdin'], subprocess.DEVNULL)
        self.assertEqual(spawn.call_args.kwargs['cwd'], root)
        self.assertEqual(spawn.call_args.args[0], ['/python', '-B', str(root / 'launch.py'), '--serve'])
        self.assertEqual(write.call_args.args[0], '43210\n')
        process.terminate.assert_not_called()

    def test_early_exit_and_timeout_are_bounded(self):
        """子进程退出或就绪超时都会失败，且只清理自己创建的进程。"""
        for poll in (7, None):
            process = Mock(pid=43210)
            process.poll.return_value = poll
            with self.subTest(poll=poll), patch.object(launch, 'service_state', return_value='absent'), \
                    patch.object(Path, 'open', mock_open()), patch.object(Path, 'write_text'), \
                    patch.object(Path, 'unlink') as unlink, \
                    patch.object(launch.subprocess, 'Popen', return_value=process), \
                    patch.object(launch.time, 'monotonic', side_effect=[0, 0, 16]), \
                    patch.object(launch.time, 'sleep'):
                with self.assertRaises(launch.LaunchError):
                    launch.ensure_service(Path('/synthetic'), Path('/python'), '127.0.0.1', 8788)
                unlink.assert_called_once()
            self.assertEqual(process.terminate.call_count, int(poll is None))

    def test_popen_failure_does_not_print_exception_or_log_contents(self):
        """启动错误只包含安全提示及日志位置，不回显原异常。"""
        with patch.object(launch, 'service_state', return_value='absent'), \
                patch.object(Path, 'open', mock_open()), \
                patch.object(launch.subprocess, 'Popen', side_effect=OSError('synthetic-secret')):
            with self.assertRaisesRegex(launch.LaunchError, '后台服务') as failure:
                launch.ensure_service(Path('/synthetic'), Path('/python'), '127.0.0.1', 8788)
        self.assertNotIn('synthetic-secret', str(failure.exception))


class EntryTests(unittest.TestCase):
    """实际命令入口以合成依赖完成纵向验证。"""

    def invoke(self, argv, futu='ready', service='matching', configured=False):
        """隔离所有系统边界，执行真正参数解析和结果输出。"""
        with patch.dict(launch.os.environ, {}, clear=True), \
                patch.object(launch, 'startup_lock', return_value=nullcontext()) as lock, \
                patch.object(launch, 'ensure_python', return_value=Path('/python')) as python, \
                patch.object(launch, 'service_state', return_value=service), \
                patch.object(launch, 'ensure_service', return_value=False) as start, \
                patch.object(launch, 'ensure_futu', return_value=futu) as app, \
                patch.object(launch, 'probe_futu', return_value=futu), \
                patch.object(launch, 'alpaca_configured', return_value=configured), \
                patch.object(launch, 'open_browser', return_value=True) as browser, \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            code = launch.main(argv, root=Path('/synthetic/Flow desk'))
        return code, output.getvalue(), (lock, python, start, app, browser)

    def test_no_alpaca_is_ready_and_no_browser_is_respected(self):
        """缺少可选 Alpaca 密钥不影响网页和 Futu 就绪。"""
        code, output, calls = self.invoke(['--no-browser'])
        self.assertEqual(code, 0)
        self.assertIn('http://127.0.0.1:8788/', output)
        self.assertIn('配置不齐全', output)
        self.assertIn('权限未验证', output)
        self.assertIn('flowdesk.log', output)
        calls[-1].assert_not_called()

    def test_partial_ready_still_opens_page_and_exits_nonzero(self):
        """等待本人登录时网页仍可打开，不能报告全部成功。"""
        code, output, calls = self.invoke([], futu='login')
        self.assertEqual(code, 2)
        self.assertIn('部分就绪', output)
        self.assertIn('本人登录', output)
        calls[-1].assert_called_once_with('http://127.0.0.1:8788/')

    def test_configured_alpaca_is_never_reported_authenticated(self):
        """密钥配置齐全仅是配置事实，权限仍需真实查询确认。"""
        code, output, _ = self.invoke(['--no-browser'], configured=True)
        self.assertEqual(code, 0)
        self.assertIn('配置齐全', output)
        self.assertIn('权限未验证', output)
        self.assertNotIn('鉴权通过', output)

    def test_status_has_no_start_install_browser_or_file_side_effects(self):
        """只读状态不拿锁、不创建文件、不打开 App 或浏览器。"""
        with patch.object(Path, 'mkdir', side_effect=AssertionError('write')), \
                patch.object(Path, 'open', side_effect=AssertionError('write')):
            code, _, calls = self.invoke(['--status'])
        self.assertEqual(code, 0)
        lock, python, start, app, browser = calls
        python.assert_called_once_with(Path('/synthetic/Flow desk'), install=False)
        for action in (lock, start, app, browser):
            action.assert_not_called()

    def test_status_reports_stopped_service_without_starting(self):
        """未启动的网页只报告状态，返回非零。"""
        code, output, calls = self.invoke(['--status'], service='absent')
        self.assertEqual(code, 2)
        self.assertIn('未运行', output)
        calls[2].assert_not_called()

    def test_foreign_port_fails_before_environment_or_app_start(self):
        """冲突时入口直接失败，不顺便安装环境或打开 OpenD。"""
        code, output, calls = self.invoke(['--no-browser'], service='conflict')
        self.assertEqual(code, 1)
        self.assertIn('占用', output)
        for action in calls[1:]:
            action.assert_not_called()

    def test_remote_web_host_and_invalid_ports_fail_without_actions(self):
        """本机入口拒绝通配监听和无效端口，不放宽远程安全策略。"""
        for env in ({'FLOW_HOST': '0.0.0.0'}, {'FLOW_PORT': 'bad'}, {'FUTU_PORT': '70000'}):
            with self.subTest(env=env), patch.dict(launch.os.environ, env, clear=True), \
                    patch.object(launch, 'startup_lock') as lock, \
                    patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(launch.main(['--no-browser']), 1)
            lock.assert_not_called()

    def test_status_rejects_internal_start_flags(self):
        """状态模式不能与内部后台入口组合而意外启动服务。"""
        with patch.object(launch, 'load_quiet_sdk'), patch.object(server, 'main') as start, \
                patch('sys.stderr', new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as result:
                launch.main(['--status', '--serve'])
        self.assertEqual(result.exception.code, 2)
        start.assert_not_called()


class LockTests(unittest.TestCase):
    """内核锁边界使用合成文件描述符，不触碰真实服务的锁。"""

    def test_busy_lock_times_out_without_entering_startup(self):
        """另一启动器占锁时有界退出，不进入临界区。"""
        with patch.object(Path, 'mkdir'), patch.object(Path, 'open', mock_open()), \
                patch.object(fcntl, 'flock', side_effect=BlockingIOError), \
                patch.object(launch.time, 'monotonic', side_effect=[0, 31]):
            with self.assertRaisesRegex(launch.LaunchError, '另一个启动器'):
                with launch.startup_lock(Path('/synthetic')):
                    self.fail('不应进入临界区')

    def test_lock_released_on_failure_without_unlinking_lock_file(self):
        """失败也释放内核锁，保留锁 inode，防止两次点击锁住不同文件。"""
        with patch.object(Path, 'mkdir'), patch.object(Path, 'open', mock_open()), \
                patch.object(Path, 'unlink') as unlink, patch.object(fcntl, 'flock') as flock:
            with self.assertRaisesRegex(RuntimeError, 'synthetic'):
                with launch.startup_lock(Path('/synthetic')):
                    raise RuntimeError('synthetic')
        self.assertEqual(flock.call_args_list[0].args[1], fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(flock.call_args_list[-1].args[1], fcntl.LOCK_UN)
        unlink.assert_not_called()

    def test_health_import_does_not_require_unix_only_modules(self):
        """server 导入健康标识时不能因新启动器破坏原有非 Unix 导入。"""
        original_import = __import__

        def without_fcntl(name, *args, **kwargs):
            """模拟没有 fcntl 的平台，只限制新启动器的导入阶段。"""
            if name == 'fcntl':
                raise ImportError('synthetic non-Unix platform')
            return original_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=without_fcntl):
            loaded = runpy.run_path(str(launch.ROOT / 'launch.py'), run_name='synthetic_launch')
        self.assertEqual(loaded['APP_ID'], 'flowdesk')


class EnvironmentTests(unittest.TestCase):
    """环境引导只在需要时安装，不触碰全局 Python。"""

    def test_existing_environment_never_runs_pip(self):
        """已有可用环境直接返回，路径空格保持单个参数。"""
        root = Path('/synthetic/Flow desk')
        with patch.object(Path, 'is_file', return_value=True), \
                patch.object(launch, 'dependencies_available', return_value=True), \
                patch.object(launch.subprocess, 'run') as run:
            self.assertEqual(launch.ensure_python(root), root / '.venv/bin/python')
        run.assert_not_called()

    def test_missing_dependencies_install_once_in_venv(self):
        """依赖缺失时安装 requirements，成功后重新核验，禁止每次升级。"""
        root = Path('/synthetic/Flow desk')
        with patch.object(Path, 'is_file', return_value=True), \
                patch.object(launch, 'dependencies_available', side_effect=[False, True]), \
                patch.object(launch.subprocess, 'run', return_value=Mock(returncode=0)) as run:
            launch.ensure_python(root)
        args = run.call_args.args[0]
        self.assertEqual(args[0], str(root / '.venv/bin/python'))
        self.assertIn('--require-virtualenv', args)
        self.assertEqual(args[-2:], ['-r', str(root / 'requirements.txt')])
        self.assertNotIn('--upgrade', args)

    def test_first_run_creates_venv_then_installs(self):
        """首次运行只在项目目录建立虚拟环境。"""
        root = Path('/synthetic/Flow desk')
        with patch.object(Path, 'is_file', return_value=False), \
                patch.object(Path, 'exists', return_value=False), \
                patch.object(launch, 'dependencies_available', side_effect=[False, True]), \
                patch.object(launch.subprocess, 'run', return_value=Mock(returncode=0)) as run:
            launch.ensure_python(root)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0][-3:], ['-m', 'venv', str(root / '.venv')])

    def test_install_failure_is_clear_and_redacts_raw_error(self):
        """安装失败只展示可操作提示，不泄露 pip 的原始响应。"""
        with patch.object(Path, 'is_file', return_value=True), \
                patch.object(launch, 'dependencies_available', return_value=False), \
                patch.object(launch.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'pip', stderr='synthetic-secret')):
            with self.assertRaisesRegex(launch.LaunchError, '联网安装失败') as failure:
                launch.ensure_python(Path('/synthetic'))
        self.assertNotIn('synthetic-secret', str(failure.exception))

    def test_status_environment_check_never_creates_or_installs(self):
        """状态检查发现环境缺失时返回未知，不创建任何目录或运行安装。"""
        with patch.object(Path, 'is_file', return_value=False), \
                patch.object(Path, 'mkdir') as mkdir, patch.object(launch.subprocess, 'run') as run:
            self.assertIsNone(launch.ensure_python(Path('/synthetic'), install=False))
        mkdir.assert_not_called()
        run.assert_not_called()


class FutuTests(unittest.TestCase):
    """行情就绪须核验 SDK 登录状态，不能由 TCP 开放推断。"""

    def test_running_opend_is_reused_without_opening_app(self):
        """已登录行情的 OpenD 直接复用。"""
        with patch.object(launch, 'probe_futu', return_value='ready'), \
                patch.object(launch.subprocess, 'run') as run:
            self.assertEqual(launch.ensure_futu(Path('/python'), Path('/project'), '127.0.0.1', 11111), 'ready')
        run.assert_not_called()

    def test_closed_local_port_and_missing_app_is_partial(self):
        """未安装 OpenD 应提示缺 App，不能启动其他程序。"""
        with patch.object(launch, 'probe_futu', return_value='unavailable'), \
                patch.object(launch, 'port_open', return_value=False), \
                patch.object(Path, 'is_dir', return_value=False), \
                patch.object(launch.subprocess, 'run') as run:
            self.assertEqual(launch.ensure_futu(Path('/python'), Path('/project'), 'localhost', 11111), 'missing-app')
        run.assert_not_called()

    def test_open_port_without_login_does_not_claim_ready(self):
        """行情未登录时报告等待本人登录，不重复打开 App。"""
        with patch.object(launch, 'probe_futu', return_value='login'), \
                patch.object(launch.subprocess, 'run') as run:
            self.assertEqual(launch.ensure_futu(Path('/python'), Path('/project'), '127.0.0.1', 11111), 'login')
        run.assert_not_called()

    def test_remote_host_never_opens_local_app(self):
        """配置远程 OpenD 时只读检查，不对其实施启动或登录。"""
        with patch.object(launch, 'probe_futu', return_value='unavailable'), \
                patch.object(launch.subprocess, 'run') as run:
            self.assertEqual(launch.ensure_futu(Path('/python'), Path('/project'), 'example.invalid', 11111), 'remote-unavailable')
        run.assert_not_called()

    def test_app_launch_wait_is_bounded(self):
        """已安装 App 通过 macOS open 启动，等待超时明确返回。"""
        with patch.object(launch, 'probe_futu', return_value='unavailable'), \
                patch.object(launch, 'port_open', return_value=False), \
                patch.object(Path, 'is_dir', return_value=True), \
                patch.object(launch.time, 'monotonic', side_effect=[0, 0, 21]), \
                patch.object(launch.time, 'sleep'), \
                patch.object(launch.subprocess, 'run', return_value=Mock(returncode=0)) as run:
            self.assertEqual(launch.ensure_futu(Path('/python'), Path('/project'), '127.0.0.1', 11111), 'unavailable')
        self.assertEqual(run.call_args.args[0], ['/usr/bin/open', '-g', '/Applications/Futu_OpenD.app'])

    def test_probe_timeout_and_bad_output_are_not_ready(self):
        """SDK 卡住或异常输出均保守返回不可用，不打印原始响应。"""
        for result in (subprocess.TimeoutExpired('probe', 6), Mock(returncode=0, stdout='synthetic-secret')):
            with self.subTest(result=result), patch.object(launch, 'port_open', return_value=True), \
                    patch.object(launch.subprocess, 'run', side_effect=[result]), \
                    patch('sys.stdout', new_callable=io.StringIO) as output:
                self.assertEqual(launch.probe_futu(Path('/python'), Path('/project'), '127.0.0.1', 11111), 'unavailable')
            self.assertNotIn('synthetic-secret', output.getvalue())

    def test_sdk_worker_only_emits_login_booleans(self):
        """只调用行情全局状态，将合成原始状态压缩成布尔值。"""
        for value, expected in ((1, True), ('1', True), (True, True), (0, False), ('0', False), ('unknown', False)):
            context = Mock()
            context.get_global_state.return_value = (0, {'qot_logined': value, 'account': 'synthetic-private'})
            sdk = SimpleNamespace(RET_OK=0, OpenQuoteContext=Mock(return_value=context))
            with self.subTest(value=value), patch.object(launch, 'load_quiet_sdk', return_value=sdk):
                state = launch.futu_state('127.0.0.1', 11111)
                self.assertEqual(state, {'reachable': True, 'quoteLoggedIn': expected})
                context.close.assert_called_once()
                self.assertNotIn('synthetic-private', str(state))

    def test_sdk_import_suppresses_file_and_console_logs(self):
        """SDK 导入期间日志处理器被替换，绝不修改 HOME。"""
        sdk = SimpleNamespace(SysConfig=Mock())
        with patch.dict(sys.modules, {'futu': sdk}), \
                patch.object(launch.logging.handlers, 'TimedRotatingFileHandler') as file_handler:
            self.assertIs(launch.load_quiet_sdk(), sdk)
        file_handler.assert_not_called()
        sdk.SysConfig.enable_console_log.assert_called_once_with(False)

    def test_real_sdk_import_has_no_write_or_network_side_effects(self):
        """真实导入 SDK，用 Python audit 禁止写文件及连接网络。"""
        script = '''
import os
import sys
sys.path.insert(0, sys.argv[1])
def readonly(event, args):
    """拒绝磁盘写操作和网络连接，SDK 仅允许本地导入。"""
    if event == 'open' and args[0] != os.devnull:
        mode, flags = args[1], args[2]
        if (mode and any(char in mode for char in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            raise RuntimeError('unexpected write')
    if event in {'os.mkdir', 'os.remove', 'os.rename', 'os.rmdir', 'socket.connect'}:
        raise RuntimeError('unexpected side effect')
sys.addaudithook(readonly)
import launch
raise SystemExit(launch.main(['--check-deps']))
'''
        result = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(launch.ROOT)],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, '真实 SDK 只读导入失败（隐藏第三方原始输出）')
        self.assertEqual(result.stdout, '')
