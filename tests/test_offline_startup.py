"""在禁止DNS和系统主目录发现时，本机显式路径与HTTP仍可启动。"""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import app_paths
import server


class OfflineStartupTests(unittest.TestCase):
    def test_bind_does_not_query_reverse_dns(self):
        with patch('socket.getfqdn', side_effect=AssertionError('DNS must not be queried')):
            with server.FlowdeskHTTPServer(('127.0.0.1', 0), server.Handler) as httpd:
                self.assertEqual(httpd.server_name, '127.0.0.1')
                self.assertGreater(httpd.server_port, 0)

    def test_explicit_user_directory_does_not_discover_home(self):
        directory = str(Path.cwd().resolve() / 'synthetic-not-created')
        with patch.dict(os.environ, {'FLOWDESK_USER_DATA_DIR': directory}, clear=True), \
                patch.object(Path, 'home', side_effect=AssertionError('home must not be queried')):
            self.assertEqual(app_paths.user_data_dir(), Path(directory))


if __name__ == '__main__':
    unittest.main()
