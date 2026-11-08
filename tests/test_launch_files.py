"""TMPDIR 内的合成文件与并发验收，不启动真实服务、App 或浏览器。"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import launch


class LauncherFileTests(unittest.TestCase):
    """实际文件锁和含空格路径均限制在调用方指定的临时目录。"""

    def setUp(self):
        """明确沿用 TMPDIR；不允许 tempfile 回退到其他系统目录。"""
        directory = os.getenv('TMPDIR')
        if not directory:
            self.skipTest('请先将 TMPDIR 指向获准可写的临时目录。')
        self.temporary = tempfile.TemporaryDirectory(prefix='Flow desk 中文 ', dir=directory)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_command_resolves_own_directory_and_preserves_arguments(self):
        """真实 shell 入口使用自身路径，且不拆分含空格参数。"""
        command = self.root / '启动Flowdesk.command'
        shutil.copy2(launch.ROOT / command.name, command)
        python = self.root / '.venv' / 'bin' / 'python'
        python.parent.mkdir(parents=True)
        python.symlink_to(sys.executable)
        (self.root / 'launch.py').write_text(
            'import json, sys\nfrom pathlib import Path\n'
            'print(json.dumps({"root": str(Path(__file__).resolve().parent), "args": sys.argv[1:]}))\n',
            encoding='utf-8')
        result = subprocess.run([str(command), '--no-browser', '合成 参数'], cwd=self.root.parent,
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, '合成入口失败，隐藏原始输出')
        self.assertEqual(json.loads(result.stdout), {'root': str(self.root.resolve()), 'args': ['--no-browser', '合成 参数']})
        self.assertTrue(os.access(command, os.X_OK))
        self.assertFalse((self.root / '__pycache__').exists())

    def test_simultaneous_clicks_start_exactly_one_synthetic_service(self):
        """两个真实线程竞争实际文件锁，只创建一个合成 Popen 服务。"""
        barrier, spawned = threading.Barrier(2), threading.Event()
        process = Mock(pid=43210)
        process.poll.return_value = None

        def state(*args):
            """合成端口只在首次创建进程后成为匹配的健康服务。"""
            return 'matching' if spawned.is_set() else 'absent'

        def spawn(*args, **kwargs):
            """仅记录合成服务已存在，绝不创建真实后台进程。"""
            spawned.set()
            return process

        def click():
            """使用真实启动锁包裹服务检查及创建。"""
            barrier.wait(timeout=5)
            with launch.startup_lock(self.root, timeout=3):
                return launch.ensure_service(self.root, Path('/synthetic/python'), '127.0.0.1', 8788)

        with patch.object(launch, 'service_state', side_effect=state), \
                patch.object(launch.subprocess, 'Popen', side_effect=spawn) as popen, \
                ThreadPoolExecutor(max_workers=2) as pool:
            clicks = [pool.submit(click), pool.submit(click)]
            self.assertEqual(sorted(item.result(timeout=6) for item in clicks), [False, True])
        popen.assert_called_once()
        self.assertEqual((self.root / '.data/server.pid').read_text(), '43210\n')
        self.assertTrue((self.root / '.data/startup.lock').exists())

    def test_kernel_lock_timeout_and_recovery(self):
        """实际内核锁不可重入，超时后原锁释放即可再次使用。"""
        with launch.startup_lock(self.root):
            with self.assertRaises(launch.LaunchError):
                with launch.startup_lock(self.root, timeout=0):
                    self.fail('两个文件描述符不应同时获得锁')
        with launch.startup_lock(self.root, timeout=0):
            self.assertTrue((self.root / '.data/startup.lock').exists())

    def test_status_leaves_empty_project_directory_untouched(self):
        """缺环境的真实文件目录在状态检查前后完全一致。"""
        with patch.dict(launch.os.environ, {}, clear=True), \
                patch.object(launch, 'port_open', return_value=False), \
                patch.object(launch, 'alpaca_configured', return_value=False), \
                patch.object(launch.subprocess, 'Popen') as popen, \
                patch.object(launch.subprocess, 'run') as run, \
                patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(launch.main(['--status'], root=self.root), 2)
        self.assertEqual(list(self.root.iterdir()), [])
        popen.assert_not_called()
        run.assert_not_called()
