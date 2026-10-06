"""资金流看板的本地 HTTP 服务：仅使用富途行情接口，不访问交易接口。"""
import hmac
import json
import math
import os
import re
import socket
import threading
import time
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent / 'dist'
HOST = os.getenv('FLOW_HOST', '127.0.0.1')
PORT = int(os.getenv('FLOW_PORT', '8788'))
OPEND_HOST = os.getenv('FUTU_HOST', '127.0.0.1')
OPEND_PORT = int(os.getenv('FUTU_PORT', '11111'))
TOKEN = os.getenv('FLOW_TOKEN', '')
ALLOWED_ORIGINS = set(filter(None, os.getenv('FLOW_ALLOWED_ORIGINS', '').split(',')))
ETFS = set('SPY QQQ XLB XLU XLK IWM SMH XLE XLF IBIT DIA XLI XLP XLC USO XLRE XLV SLV XLY GLD SOXX'.split())
DEFAULT_SYMBOLS = list('SPY QQQ XLK XLF XLE SMH NVDA MSFT AAPL TSLA AMZN META'.split())
LOCK = threading.Lock()
CACHE = {}
QUOTE_CONTEXT = None
LAST_FLOW_REQUEST = 0.0


def finite(value):
    """把 SDK 数值转为 JSON 兼容浮点数，缺失值保持为空。"""
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def get_context():
    """延迟加载 SDK 并连接 OpenD，缺少依赖或服务时返回明确错误。"""
    global QUOTE_CONTEXT
    try:
        from futu import OpenQuoteContext
    except ImportError as error:
        raise RuntimeError('请先安装行情依赖：python3 -m pip install -r requirements.txt') from error
    try:
        with socket.create_connection((OPEND_HOST, OPEND_PORT), timeout=2):
            pass
    except OSError as error:
        raise RuntimeError('未连接到富途 OpenD，请启动并登录 OpenD，确认本地端口 11111。') from error
    if QUOTE_CONTEXT is None:
        QUOTE_CONTEXT = OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)
    return QUOTE_CONTEXT


def fetch_snapshot(symbols):
    """缓存并串行拉取快照，资金流调用间隔保证每 30 秒少于 30 次。"""
    global LAST_FLOW_REQUEST
    cache_key = tuple(symbols)
    with LOCK:
        cached = CACHE.get(cache_key)
        if cached and time.monotonic() - cached[0] < 60:
            return cached[1]
        from_context = get_context()
        from futu import RET_OK, PeriodType
        codes = ['US.' + symbol for symbol in symbols]
        ret, snapshots = from_context.get_market_snapshot(codes)
        if ret != RET_OK:
            raise RuntimeError('行情快照获取失败，请检查 OpenD 登录状态及美股行情权限。')
        quotes = {str(row['code']): row for _, row in snapshots.iterrows()}
        rows = []
        for symbol in symbols:
            quote = quotes.get('US.' + symbol)
            record = {'symbol': symbol, 'name': symbol, 'type': 'etf' if symbol in ETFS else 'stock',
                      'price': None, 'change': None, 'low': None, 'high': None,
                      'ba': None, 'big': None, 'super': None, 'mid': None, 'small': None,
                      'flowTime': '', 'quoteTime': '', 'flowStatus': 'unavailable'}
            if quote is not None:
                record.update(name=str(quote.get('name', symbol)), price=finite(quote.get('last_price')),
                              low=finite(quote.get('low_price')), high=finite(quote.get('high_price')),
                              quoteTime=str(quote.get('update_time', '')))
                previous_close = finite(quote.get('prev_close_price'))
                if record['price'] is not None and previous_close and previous_close > 0:
                    record['change'] = (record['price'] / previous_close - 1) * 100
                bid, ask = finite(quote.get('bid_vol')), finite(quote.get('ask_vol'))
                if bid is not None and ask is not None and ask > 0:
                    record['ba'] = bid / ask
                interval = 1.05 - (time.monotonic() - LAST_FLOW_REQUEST)
                if interval > 0:
                    time.sleep(interval)
                LAST_FLOW_REQUEST = time.monotonic()
                flow_ret, flow = from_context.get_capital_flow('US.' + symbol, period_type=PeriodType.INTRADAY)
                if flow_ret == RET_OK and not flow.empty:
                    flow = flow.sort_values('capital_flow_item_time')
                    latest = flow.iloc[-1]
                    for key, upstream in [('big', 'big_in_flow'), ('super', 'super_in_flow'),
                                          ('mid', 'mid_in_flow'), ('small', 'sml_in_flow')]:
                        value = finite(latest.get(upstream))
                        record[key] = value / 10000 if value is not None else None
                    valid_time = str(latest.get('last_valid_time', ''))
                    record['flowTime'] = valid_time if valid_time and valid_time != 'N/A' else str(latest.get('capital_flow_item_time', ''))
                    record['flowStatus'] = 'ok' if record['big'] is not None and record['super'] is not None else 'unavailable'
            rows.append(record)
        if not any(row['flowStatus'] == 'ok' for row in rows):
            raise RuntimeError('没有取得可用资金流，请检查美股行情权限及标的是否支持资金流。')
        result = {'source': 'futu-opend', 'unit': 'USD_10000', 'timezone': 'America/New_York',
                  'generatedAt': datetime.now(timezone.utc).isoformat(), 'rows': rows}
        CACHE.clear()
        CACHE[cache_key] = (time.monotonic(), result)
        return result


class Handler(SimpleHTTPRequestHandler):
    """在同一源提供页面与行情 API，远程使用时要求显式令牌和来源白名单。"""

    def __init__(self, *args, **kwargs):
        """设置静态文件目录，避免暴露源码和配置文件。"""
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        """为白名单来源添加跨域响应，同时关闭 API 和页面缓存。"""
        origin = self.headers.get('Origin', '')
        if origin in ALLOWED_ORIGINS:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        super().end_headers()

    def respond(self, status, data):
        """输出 UTF-8 JSON，禁止将 NaN 写入响应。"""
        body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        """仅允许已配置的网站来源进行 GET 预检。"""
        if self.headers.get('Origin') not in ALLOWED_ORIGINS:
            self.respond(403, {'error': '此网站来源未授权。'})
            return
        self.send_response(204)
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Authorization')
        self.end_headers()

    def do_GET(self):
        """校验请求后获取资金流；静态请求只允许访问已知页面资产。"""
        parsed = urlsplit(self.path)
        if parsed.path == '/api/snapshot':
            origin = self.headers.get('Origin', '')
            own_origins = {f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}'}
            if origin and origin not in ALLOWED_ORIGINS | own_origins:
                self.respond(403, {'error': '请在 FLOW_ALLOWED_ORIGINS 中配置网站域名。'})
                return
            if TOKEN and not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + TOKEN):
                self.respond(401, {'error': '访问令牌无效。'})
                return
            raw = parse_qs(parsed.query).get('symbols', [','.join(DEFAULT_SYMBOLS)])[0]
            symbols = list(dict.fromkeys(raw.upper().split(',')))
            if not 1 <= len(symbols) <= 60 or any(not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}', code) for code in symbols):
                self.respond(400, {'error': '请提供 1 至 60 个有效的美股代码。'})
                return
            try:
                self.respond(200, fetch_snapshot(symbols))
            except RuntimeError as error:
                self.respond(503, {'error': str(error)})
            except Exception:
                self.respond(502, {'error': '行情服务异常，请确认 OpenD 连接和行情权限。'})
            return
        if parsed.path not in {'/', '/index.html', '/styles.css', '/app.js', '/favicon.ico'}:
            self.respond(404, {'error': '页面不存在。'})
            return
        if parsed.path == '/favicon.ico':
            self.send_response(204)
            self.end_headers()
            return
        super().do_GET()

    def log_message(self, format_string, *args):
        """保持控制台简洁，不记录可能包含敏感信息的请求参数。"""
        pass


def main():
    """启动本地服务并在退出时释放行情连接。"""
    if HOST not in {'127.0.0.1', 'localhost', '::1'} and (not TOKEN or not ALLOWED_ORIGINS):
        raise SystemExit('远程部署必须设置 FLOW_TOKEN 和 FLOW_ALLOWED_ORIGINS，并通过 HTTPS 反向代理访问。')
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f'Local: http://127.0.0.1:{PORT}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if QUOTE_CONTEXT is not None:
            QUOTE_CONTEXT.close()


if __name__ == '__main__':
    main()
