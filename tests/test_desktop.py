"""桌面子进程协议与目录隔离测试，仅使用合成临时数据。"""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import unittest
import io
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
TEST_ROOT = Path.home() / '.hermes/cache/scratch/flowdesk-review/portfolio-tests'


class DesktopPathsTests(unittest.TestCase):
    """环境覆盖不依赖当前工作目录，也不在导入时创建目录。"""

    def test_source_defaults_and_explicit_paths(self):
        """旧网页默认目录不变，带空格中文的绝对路径可显式覆盖。"""
        import app_paths
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(app_paths.data_dir(), PROJECT / '.data')
            self.assertEqual(app_paths.static_dir(), PROJECT / 'dist')
            self.assertEqual(app_paths.config_dir(), PROJECT)
        with patch.dict(os.environ, {'FLOWDESK_DATA_DIR': '/tmp/合成 测试/cache'}):
            self.assertEqual(app_paths.data_dir(), Path('/tmp/合成 测试/cache').resolve())
        with patch.dict(os.environ, {'FLOWDESK_DATA_DIR': 'relative/unknown'}):
            with self.assertRaises(ValueError):
                app_paths.data_dir()

    def test_frozen_defaults_use_user_data_and_readonly_resources(self):
        """冻结运行时从资源读页面，将缓存写入用户目录。"""
        import app_paths
        with patch.dict(os.environ, {'FLOWDESK_USER_DATA_DIR': '/tmp/桌面 用户'}, clear=True), \
                patch.object(sys, 'frozen', True, create=True), \
                patch.object(sys, '_MEIPASS', '/tmp/只读 资源', create=True):
            self.assertEqual(app_paths.static_dir(), Path('/tmp/只读 资源/dist').resolve())
            self.assertEqual(app_paths.data_dir(), Path('/tmp/桌面 用户/data').resolve())
            self.assertEqual(app_paths.config_dir(), Path('/tmp/桌面 用户/config').resolve())

    def test_managed_cache_modules_use_isolated_unicode_directory(self):
        """新进程按环境导入全部缓存模块，只读写合成目录中的JSON与配置。"""
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='cache 中文 ', dir=TEST_ROOT) as temporary:
            root = Path(temporary)
            env = {key: value for key, value in os.environ.items() if not key.startswith(('FLOW', 'APCA_'))}
            env.update(FLOWDESK_DATA_DIR=str(root / 'Data cache'), FLOWDESK_CONFIG_DIR=str(root / 'Config'),
                       FLOWDESK_STATIC_DIR=str(root / 'Unknown assets'), PYTHONDONTWRITEBYTECODE='1')
            script = '''
import json
from pathlib import Path
import app_paths, server, research, alpaca_data, chips
data = app_paths.data_dir()
config = app_paths.config_dir()
assert server.DATA == data and research.DATA == data / 'minutes'
assert not app_paths.static_dir().exists()
path = data / 'raw/TEST.json'
path.parent.mkdir(parents=True)
path.write_text(json.dumps({'prices': [{'time_key': '2026-01-05', 'close': 12}]}))
assert server.cached_daily_quote('TEST', '2026-01-05')['close'] == 12
research.save_minutes('US', 'TEST', [{'capital_flow_item_time': '2026-01-05 15:59:00', 'big_in_flow': 1, 'super_in_flow': 2}], {'2026-01-05': 'WHOLE'})
assert (data / 'minutes/US/TEST/2026-01-05.json').is_file()
path = data / 'chips/US/TEST/2026-01-05/latest.json'
path.parent.mkdir(parents=True)
path.write_text(json.dumps({'synthetic': True}))
assert chips.fetch(None, None, '/unwritable/source', 'TEST', 'US.TEST', 'US', 'America/New_York', '2026-01-05')['archived']
config.mkdir()
(config / '.env').write_text('APCA_API_KEY_ID=synthetic-key\\nAPCA_API_SECRET_KEY=synthetic-secret\\n')
assert alpaca_data.status()['configured']
assert not app_paths.static_dir().exists()
print('managed-caches-ok')
'''
            result = subprocess.run([sys.executable, '-B', '-c', script], cwd=PROJECT, env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'managed-caches-ok')


class DesktopResourcesTests(unittest.TestCase):
    """资源输入只允许明确列举的公开资产。"""

    def test_asset_stage_excludes_hidden_secrets_and_unknown_files(self):
        """合成隐藏配置、数据库和未知文件不会被复制或读取。"""
        from desktop import build
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            (source / 'index.html').write_text('<html>synthetic</html>')
            for name in ('.env', 'portfolio.sqlite3', 'unknown.js'):
                (source / name).write_text('synthetic fixture')
            manifest = {'requiredStatic': ['index.html'], 'optionalStatic': []}
            with patch.object(build, 'MANIFEST', manifest):
                output = build.stage_assets(source, root / 'output')
            self.assertEqual([path.name for path in output.iterdir()], ['index.html'])

    def test_resource_traversal_and_missing_files_fail_build(self):
        """非法清单或丢失资源直接阻止构建。"""
        from desktop import build
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('../escape', '.env', 'missing.js'):
                with patch.object(build, 'MANIFEST', {'requiredStatic': [name], 'optionalStatic': []}):
                    with self.assertRaises(ValueError):
                        build.stage_assets(root, root / 'output')

    def test_resource_audit_rejects_sensitive_packaged_files(self):
        """审计依赖资源时也拒绝数据库和隐藏配置，不检查内容。"""
        from desktop import build
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            forbidden = root / '.env'
            forbidden.write_text('synthetic fixture')
            with self.assertRaises(ValueError):
                build.audit_resources(root)


class DesktopProtocolTests(unittest.TestCase):
    """真实短生命周期HTTP子进程，始终不调用OpenD或打开私有数据库。"""

    def setUp(self):
        """只在指定的合成根目录下创建用户数据。"""
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='desktop 中文 ', dir=TEST_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.user_data = str(Path(self.temp.name) / '用户 Data')
        self.challenge = secrets.token_hex(32)
        self.instance = secrets.token_hex(16)

    def start(self, init=None):
        """启动真实入口，将SDK打印和协议输出分开捕获。"""
        env = {k: v for k, v in os.environ.items() if not k.startswith(('FLOW', 'APCA_', 'FUTU_'))}
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        child = subprocess.Popen([sys.executable, '-B', str(PROJECT / 'desktop_sidecar.py')],
                                 cwd=self.temp.name, env=env, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.close, child)
        message = init or {'type': 'init', 'version': 1, 'challenge': self.challenge,
                           'instanceId': self.instance, 'userData': self.user_data}
        child.stdin.write(json.dumps(message) + '\n')
        child.stdin.flush()
        return child

    def close(self, child):
        """测试失败时也回收自己的进程和全部管道。"""
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
        for stream in (child.stdin, child.stdout, child.stderr):
            stream.close()

    def ready(self, child):
        """读取一条就绪消息，测试总体超时由独立进程等待保证。"""
        import concurrent.futures
        try:
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
        except PermissionError:
            self.skipTest('当前沙箱禁止loopback绑定；原生打包冒烟须在父进程或CI执行。')
        pool = concurrent.futures.ThreadPoolExecutor(1)
        try:
            line = pool.submit(child.stdout.readline).result(timeout=10)
            return json.loads(line)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def request(self, origin, path, data=None, headers=None):
        """发送合成请求并返回拒绝状态，避免打印任何响应私有信息。"""
        request = Request(origin + path, data=data, headers=headers or {})
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, response.read()
        except HTTPError as error:
            with error:
                return error.code, error.read()

    def test_real_handshake_assets_private_boundary_and_shutdown(self):
        """随机端口可提供页面，跨源与缺令牌拒绝，关闭只释放本进程端口。"""
        child = self.start()
        ready = self.ready(child)
        self.assertEqual(ready['type'], 'ready')
        self.assertEqual(ready['version'], 1)
        self.assertEqual(ready['challenge'], self.challenge)
        self.assertEqual(ready['instanceId'], self.instance)
        port = ready['port']
        origin = f'http://127.0.0.1:{port}'
        self.assertEqual(self.request(origin, '/')[0], 200)
        self.assertEqual(self.request(origin, '/api/health')[0], 200)
        for path in ('/.env', '/server.py', '/unknown', '/data/portfolio.sqlite3'):
            self.assertEqual(self.request(origin, path)[0], 404)
        status, body = self.request(origin, '/api/private/session', b'{}',
                                    {'Origin': origin, 'Content-Type': 'application/json'})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)['session_token'])
        for headers, expected in (({'Origin': 'https://evil.invalid'}, 403), ({'Origin': origin}, 401), ({}, 403)):
            self.assertEqual(self.request(origin, '/api/private/accounts', b'{}',
                {'Content-Type': 'application/json', **headers})[0], expected)
        self.assertFalse((Path(self.user_data) / 'private').exists())
        with socket.socket() as contender:
            with self.assertRaises(OSError):
                contender.bind(('127.0.0.1', port))
        child.stdin.write(json.dumps({'type': 'shutdown', 'version': 1,
                                     'instanceId': self.instance, 'challenge': self.challenge}) + '\n')
        child.stdin.flush()
        self.assertEqual(child.wait(timeout=5), 0)
        self.assertEqual(child.stdout.read(), '')
        with self.assertRaises(OSError):
            socket.create_connection(('127.0.0.1', port), timeout=1)

    def test_stdin_eof_stops_child(self):
        """宿主异常退出关闭stdin后，子进程自行结束。"""
        child = self.start()
        self.ready(child)
        child.stdin.close()
        self.assertEqual(child.wait(timeout=5), 0)

    def test_bad_shutdown_challenge_fails_closed(self):
        """不匹配挑战码不能被当成有效控制消息继续服务。"""
        child = self.start()
        self.ready(child)
        child.stdin.write(json.dumps({'type': 'shutdown', 'version': 1,
            'instanceId': self.instance, 'challenge': 'wrong'}) + '\n')
        child.stdin.flush()
        self.assertNotEqual(child.wait(timeout=5), 0)

    def test_invalid_and_oversized_init_never_start_server(self):
        """相对目录、非法挑战和超长协议报文均在导入服务前退出。"""
        for update in ({'userData': 'relative'}, {'challenge': 'wrong'}, {'challenge': 'x' * 20000}):
            with self.subTest(update=list(update)):
                message = {'type': 'init', 'version': 1, 'challenge': self.challenge,
                           'instanceId': self.instance, 'userData': self.user_data, **update}
                child = self.start(message)
                self.assertNotEqual(child.wait(timeout=5), 0)
                self.assertEqual(child.stdout.read(), '')

    def test_init_timeout_exits_without_listening(self):
        """没有宿主首报文时，在固定握手期限内回收真实子进程。"""
        child = subprocess.Popen([sys.executable, '-B', str(PROJECT / 'desktop_sidecar.py')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(self.close, child)
        self.assertEqual(child.wait(timeout=13), 2)
        self.assertEqual(child.stdout.read(), b'')

    def test_duplicate_fields_rejected_before_environment_configuration(self):
        """重复字段及未知控制类型不能进入受管目录初始化。"""
        import desktop_sidecar
        for line in (b'{"type":"init","type":"init"}\n', b'{"value":NaN}\n', b'[]\n', b'{}'):
            with self.subTest(line=line):
                with self.assertRaises(ValueError):
                    desktop_sidecar.read_message(io.BytesIO(line))


if __name__ == '__main__':
    unittest.main()
