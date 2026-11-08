"""隔离HTTP/OS边界的私有接口测试，不启动真实服务器或行情网络。"""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from email.message import Message
from private_api import PrivateAPI
from portfolio_store import PortfolioStore

TEST_ROOT = Path.home() / '.hermes/cache/scratch/flowdesk-review/portfolio-tests'
TEST_ROOT.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TEST_ROOT)


class PrivateAPITests(unittest.TestCase):
    """拒绝请求必须早于私有存储工厂调用。"""

    def setUp(self):
        """延迟存储工厂记录所有触碰数据库的行为。"""
        self.tmp = tempfile.TemporaryDirectory(dir=TEST_ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.factory = Mock(side_effect=lambda: PortfolioStore(Path(self.tmp.name) / 'private'))
        self.api = PrivateAPI(self.factory)

    def request(self, path='/api/private/accounts', method='POST', data=None, peer='127.0.0.1', headers=None):
        """直接执行真实边界控制，只替换HTTP字节输送。"""
        handler = Mock()
        handler.path = path
        handler.client_address = (peer, 1234)
        handler.server.server_address = ('127.0.0.1', 8788)
        content = json.dumps(data or {}).encode()
        handler.headers = Message()
        default = {'Host': '127.0.0.1:8788', 'Origin': 'http://127.0.0.1:8788',
                   'Content-Type': 'application/json', 'Content-Length': str(len(content)), 'X-Flowdesk-Session': self.api.token}
        for key, value in {**default, **(headers or {})}.items():
            if value is not None:
                handler.headers[key] = value
        handler.rfile = io.BytesIO(content)
        handler.wfile = io.BytesIO()
        self.api.handle(handler, method, flow_token='')
        return handler.send_response.call_args.args[0], json.loads(handler.wfile.getvalue()), handler

    def test_denials_never_open_private_database(self):
        """恶意Host、跨源Origin、非loopback和缺令牌都不初始化数据库。"""
        for options in ({'headers': {'Origin': 'https://evil.invalid'}}, {'headers': {'Host': 'evil.invalid:8788'}},
                        {'peer': '192.0.2.1'}, {'headers': {'X-Flowdesk-Session': None}}):
            status, payload, handler = self.request(**options)
            self.assertIn(status, (401, 403))
            self.assertNotIn('sqlite', str(payload))
            self.assertFalse(any(c.args[0].lower().startswith('access-control') for c in handler.send_header.call_args_list))
        self.factory.assert_not_called()

    def test_session_same_origin_post_only_without_database(self):
        """握手不需要会话令牌，但同源、FLOW_TOKEN和HTTP方法不放松。"""
        status, body, handler = self.request('/api/private/session', headers={'X-Flowdesk-Session': None})
        self.assertEqual(status, 200)
        self.assertEqual(body['session_token'], self.api.token)
        self.factory.assert_not_called()
        for options in ({'headers': {'Origin': None}}, {'headers': {'Origin': 'https://example.invalid'}}, {'method': 'OPTIONS'}, {'method': 'GET'}):
            self.assertNotEqual(self.request('/api/private/session', **options)[0], 200)
        self.factory.assert_not_called()

    def test_flow_token_is_additional_not_replaced_by_session(self):
        """已有FLOW_TOKEN即使持有会话令牌也必须提供。"""
        _, _, handler = self.request()
        self.factory.reset_mock()
        handler.wfile = io.BytesIO()
        self.api.handle(handler, 'POST', flow_token='synthetic-flow-token')
        self.assertEqual(handler.send_response.call_args.args[0], 401)
        self.factory.assert_not_called()
        handler.headers['Authorization'] = 'Bearer synthetic-flow-token'
        handler.rfile.seek(0)
        handler.wfile = io.BytesIO()
        self.api.handle(handler, 'POST', flow_token='synthetic-flow-token')
        self.assertEqual(handler.send_response.call_args.args[0], 200)

    def test_length_json_and_duplicate_headers_fail_before_db(self):
        """限长、请求类型、歧义头部和坏JSON均不接触数据库。"""
        for headers in ({'Content-Length': '2097153'}, {'Content-Length': '-1'}, {'Content-Type': 'text/plain'},
                        {'Transfer-Encoding': 'chunked'}, {'Sec-Fetch-Site': 'cross-site'}):
            self.assertNotEqual(self.request(headers=headers)[0], 200)
        self.factory.assert_not_called()
        _, _, handler = self.request('/api/private/session')
        handler.headers['Host'] = 'evil.invalid'
        self.api.handle(handler, 'POST')
        self.assertEqual(handler.send_response.call_args.args[0], 403)
        self.factory.assert_not_called()
        for raw in (b'{bad', b'{"x":1,"x":2}', b'{"x":NaN}', b'[]'):
            _, _, handler = self.request('/api/private/session')
            handler.headers.replace_header('Content-Length', str(len(raw)))
            handler.rfile = io.BytesIO(raw)
            self.api.handle(handler, 'POST')
            self.assertEqual(handler.send_response.call_args.args[0], 400)
        self.factory.assert_not_called()

    def test_create_append_snapshot_and_frozen_import_via_http(self):
        """实际业务链路通过相同HTTP控制，确认接口拒绝重传改包正文。"""
        status, account, _ = self.request('/api/private/accounts/create', data={'name': '合成HTTP'})
        self.assertEqual(status, 200)
        identity = account['id']
        status, snapshot, _ = self.request('/api/private/events/append', data={'account': identity, 'revision': 0,
            'events': [{'kind': 'opening', 'quantity': '3', 'symbol': 'TEST', 'source': 'synthetic', 'trade_date': '2026-01-01'}]})
        self.assertEqual(status, 200)
        self.assertIsNone(snapshot['positions'][0]['cost'])
        status, preview, _ = self.request('/api/private/import/preview', data={'account': identity,
            'csv': 'Date,Action,Symbol,Description,Quantity,Price,Fees & Comm,Amount\n01/02/2026,Buy,TEST,Synthetic,1,10,0,-10'})
        self.assertTrue(preview['can_commit'])
        commit = {'account': identity, 'preview_id': preview['preview_id'], 'payload_id': preview['payload_id']}
        self.assertEqual(self.request('/api/private/import/commit', data={**commit, 'events': []})[0], 400)
        self.assertEqual(self.request('/api/private/import/commit', data=commit)[0], 200)
        status, snapshot, _ = self.request('/api/private/snapshot', data={'account': identity})
        self.assertEqual(snapshot['positions'][0]['quantity'], '4')
        self.assertEqual(snapshot['revision'], 2)

    def test_unexpected_error_never_leaks_sensitive_detail(self):
        """数据库/路径等异常文本不经过HTTP输出。"""
        self.factory.side_effect = RuntimeError('/Users/synthetic/private/sqlite account-secret')
        status, payload, _ = self.request()
        self.assertEqual(status, 500)
        self.assertNotIn('account-secret', str(payload))
        self.assertNotIn('/Users', str(payload))

    def test_real_handler_private_cors_ignores_market_allowlist(self):
        """调用实际Handler和真实header序列化，开放行情白名单仍无私有CORS。"""
        import server
        from unittest.mock import patch
        handler = server.Handler.__new__(server.Handler)
        handler.request_version = 'HTTP/1.1'
        handler.command = 'POST'
        handler.requestline = 'POST /api/private/session HTTP/1.1'
        handler.path = '/api/private/session'
        handler.client_address = ('127.0.0.1', 1234)
        handler.server = Mock(server_address=('127.0.0.1', 8788))
        handler.connection = Mock()
        handler.headers = Message()
        for k, v in {'Host': '127.0.0.1:8788', 'Origin': 'https://evil.invalid', 'Content-Length': '2', 'Content-Type': 'application/json'}.items():
            handler.headers[k] = v
        handler.rfile, handler.wfile = io.BytesIO(b'{}'), io.BytesIO()
        with patch.object(server, 'ALLOWED_ORIGINS', {'https://evil.invalid'}), patch.object(server, 'PRIVATE_API', self.api):
            handler.do_POST()
        output = handler.wfile.getvalue().decode()
        self.assertIn('403', output)
        self.assertNotIn('Access-Control-Allow-Origin', output)
        self.factory.assert_not_called()

    def test_evidence_research_and_export_use_protected_http(self):
        """人工证据、研究冻结与两种导出通过私有边界，不抓取来源URL。"""
        from datetime import datetime, timezone
        _, account, _ = self.request('/api/private/accounts/create', data={'name': '合成证据HTTP'})
        status, event, _ = self.request('/api/private/evidence/save', data={'event': {'kind': 'earnings', 'scope': 'symbol',
            'symbol': 'TEST', 'title': '合成财报', 'source': 'Synthetic IR', 'url': 'https://example.invalid/ir',
            'published_at': '2026-01-01T12:00:00Z', 'available_at': '2026-01-01T12:00:00Z'}})
        self.assertEqual(status, 200)
        status, record, _ = self.request('/api/private/research/save', data={'record': {'account': account['id'], 'revision': 0,
            'as_of': datetime.now(timezone.utc).isoformat(), 'thesis': '合成判断', 'support': [event['id']], 'against': []}})
        self.assertEqual(status, 200)
        for format in ('json', 'markdown'):
            status, result, _ = self.request('/api/private/research/export', data={'id': record['id'], 'format': format})
            self.assertEqual(status, 200)
            self.assertTrue(result['content'])
        self.assertEqual(len(self.request('/api/private/research/list', data={'account': account['id']})[1]['records']), 1)
        self.assertEqual(self.request('/api/private/evidence/list')[1]['events'][0]['verification'], 'manual_unverified')
        self.factory.reset_mock()
        for path in ('evidence/list', 'evidence/save', 'research/list', 'research/save', 'research/export', 'import/commit'):
            self.assertEqual(self.request('/api/private/'+path, headers={'Origin': 'https://evil.invalid'})[0], 403)
        self.factory.assert_not_called()

    def test_all_private_routes_reject_before_any_store_access(self):
        """所有读写及握手边界统一覆盖，拒绝不依赖已初始化的存储。"""
        routes = ['accounts', 'accounts/create', 'snapshot', 'history', 'events/append', 'import/preview', 'import/commit',
                  'evidence/list', 'evidence/save', 'research/list', 'research/save', 'research/export', 'session']
        for route in routes:
            for options in ({'peer': '192.0.2.10'}, {'headers': {'Host': 'evil.invalid:8788'}},
                            {'headers': {'Origin': 'https://example.github.io'}}, {'headers': {'Origin': None}}):
                with self.subTest(route=route, options=options):
                    self.assertEqual(self.request('/api/private/'+route, **options)[0], 403)
                    self.factory.assert_not_called()
            if route != 'session':
                with self.subTest(route=route, missing_token=True):
                    self.assertEqual(self.request('/api/private/'+route, headers={'X-Flowdesk-Session': None})[0], 401)
                    self.factory.assert_not_called()
