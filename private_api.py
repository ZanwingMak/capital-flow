"""仅直接本机同源可用的私有接口；不会继承行情API的开放CORS。"""
import hmac
import ipaddress
import json
import secrets
import threading
from urllib.parse import urlsplit
from private_common import LedgerError
from portfolio_store import PortfolioStore
from portfolio_import import ImportService
from research_store import ResearchStore
from research_report import export_report

MAX_BODY = 2 * 1024 * 1024


def reply(handler, status, payload):
    """固定JSON响应且不缓存；调用方Handler也必须关闭私有路径CORS。"""
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(body)))
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('Referrer-Policy', 'no-referrer')
    handler.send_header('X-Content-Type-Options', 'nosniff')
    handler.end_headers()
    handler.wfile.write(body)


def boundary(handler, token, flow_token, handshake):
    """先验证peer、Host、Origin和双令牌，拒绝过程不触碰私有目录。"""
    try:
        peer = ipaddress.ip_address(handler.client_address[0])
        if not peer.is_loopback:
            return 403
    except ValueError:
        return 403
    for key in ('Host', 'Origin', 'Authorization', 'X-Flowdesk-Session', 'Content-Length', 'Content-Type'):
        if len(handler.headers.get_all(key, [])) > 1:
            return 403
    port = handler.server.server_address[1]
    host = handler.headers.get('Host', '')
    if host not in {f'127.0.0.1:{port}', f'localhost:{port}', f'[::1]:{port}'}:
        return 403
    if handler.headers.get('Origin') != 'http://' + host or handler.headers.get('Sec-Fetch-Site', 'same-origin') != 'same-origin':
        return 403
    if flow_token and not hmac.compare_digest(handler.headers.get('Authorization', '').encode('utf-8'), ('Bearer ' + flow_token).encode('utf-8')):
        return 401
    if not handshake and not hmac.compare_digest(handler.headers.get('X-Flowdesk-Session', '').encode('utf-8'), token.encode('utf-8')):
        return 401
    return None


def body_json(handler):
    """限制报文长度与JSON结构，拒绝chunked及含重复字段的改包。"""
    length = handler.headers.get('Content-Length', '')
    if handler.headers.get('Transfer-Encoding') or not length.isdigit() or int(length) > MAX_BODY:
        raise LedgerError('请求体缺少有效长度或超过2MiB。')
    if handler.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
        raise LedgerError('请求必须使用application/json。')
    handler.connection.settimeout(5)
    raw = handler.rfile.read(int(length))
    if len(raw) != int(length):
        raise LedgerError('请求体不完整。')
    try:
        result = json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid_constant)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (ValueError, UnicodeError, RecursionError):
        raise LedgerError('JSON格式无效。') from None


def unique_object(pairs):
    """禁止JSON同名字段被后值悄悄覆盖。"""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def invalid_constant(value):
    """拒绝非标准NaN和Infinity JSON常量。"""
    raise ValueError


class PrivateAPI:
    """令牌仅服务进程内存持有，数据库延迟至通过边界验证后创建。"""

    def __init__(self, store_factory=PortfolioStore):
        """只生成随机会话令牌，构造时不打开任何私有文件。"""
        self.token = secrets.token_urlsafe(32)
        self.factory = store_factory
        self._store = None
        self.lock = threading.Lock()

    def store(self):
        """首次授权请求串行初始化存储，后续操作使用独立SQLite连接。"""
        with self.lock:
            if self._store is None:
                self._store = self.factory()
            return self._store

    def handle(self, handler, method, flow_token=''):
        """拦截所有私有前缀；统一鉴权、限长和异常脱敏。"""
        parsed = urlsplit(handler.path)
        if not parsed.path.startswith('/api/private'):
            return False
        handshake = parsed.path == '/api/private/session'
        status = boundary(handler, self.token, flow_token, handshake)
        if status:
            handler.close_connection = True
            reply(handler, status, {'error': '私有接口仅允许本机同源且通过令牌验证的请求。'})
            return True
        if method != 'POST' or parsed.query or parsed.fragment:
            handler.close_connection = True
            reply(handler, 405, {'error': '私有接口仅接受无查询参数的POST请求。'})
            return True
        try:
            data = body_json(handler)
            if handshake:
                if data:
                    raise LedgerError('握手不接受业务内容。')
                payload = {'session_token': self.token}
            else:
                payload = self.dispatch(parsed.path.removeprefix('/api/private/'), data)
            reply(handler, 200, payload)
        except LedgerError as error:
            handler.close_connection = True
            reply(handler, 400, {'error': str(error)})
        except Exception:
            handler.close_connection = True
            reply(handler, 500, {'error': '私有操作失败，请检查本机配置或重新预览。'})
        return True

    def dispatch(self, route, data):
        """保持HTTP层薄，只把经过字段约束的请求交给业务模块。"""
        fields = {'accounts': (set(), set()), 'accounts/create': ({'name'}, {'name'}),
                  'snapshot': ({'account'}, {'account', 'as_of'}), 'history': ({'account'}, {'account'}),
                  'events/append': ({'account', 'events', 'revision'}, {'account', 'events', 'revision'}),
                  'import/preview': ({'account', 'csv'}, {'account', 'csv', 'selections'}),
                  'import/commit': ({'account', 'preview_id', 'payload_id'}, {'account', 'preview_id', 'payload_id'}),
                  'evidence/list': (set(), set()), 'evidence/save': ({'event'}, {'event', 'event_id', 'version'}),
                  'research/list': ({'account'}, {'account'}), 'research/save': ({'record'}, {'record'}),
                  'research/export': ({'id', 'format'}, {'id', 'format'})}
        if route not in fields:
            raise LedgerError('私有接口不存在。')
        required, allowed = fields[route]
        if not required <= data.keys() or data.keys() - allowed:
            raise LedgerError('请求字段缺失或含未知字段。')
        store = self.store()
        if route == 'accounts':
            return {'accounts': store.accounts()}
        if route == 'accounts/create':
            return store.create_account(data['name'])
        if route == 'snapshot':
            return store.snapshot(data['account'], data.get('as_of'))
        if route == 'history':
            return {'events': store.history(data['account'])}
        if route == 'events/append':
            if type(data['revision']) is not int:
                raise LedgerError('账户版本必须为整数。')
            return store.append(data['account'], data['events'], data['revision'])
        if route.startswith(('evidence/', 'research/')):
            research = ResearchStore(store)
            if route == 'evidence/list':
                return {'events': research.events()}
            if route == 'evidence/save':
                return research.save_event(data['event'], data.get('event_id'), data.get('version'))
            if route == 'research/list':
                return {'records': research.records(data['account'])}
            if route == 'research/save':
                return research.save_research(data['record'])
            return {'format': data['format'], 'content': export_report(research.report(data['id']), data['format'])}
        importer = ImportService(store)
        if route == 'import/preview':
            return importer.preview(data['account'], data['csv'], data.get('selections'))
        return importer.commit(data['account'], data['preview_id'], data['payload_id'])
