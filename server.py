"""资金流看板的本地 HTTP 服务：仅使用富途行情接口，不访问交易接口。"""
import hmac
import json
import math
import os
import re
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

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
TRADING_DATES_CACHE = None


def history_bounds():
    """按美东日期限定最近一年内已结束的历史交易日。"""
    today = datetime.now(ZoneInfo('America/New_York')).date()
    return (today - timedelta(days=365)).isoformat(), (today - timedelta(days=1)).isoformat()


def trading_dates(context):
    """缓存真实美股交易日历，避免将周末或休市日替换为别的日期。"""
    global TRADING_DATES_CACHE
    bounds = history_bounds()
    if TRADING_DATES_CACHE and TRADING_DATES_CACHE[0] == bounds:
        return TRADING_DATES_CACHE[1]
    from futu import Market, RET_OK
    ret, days = context.request_trading_days(market=Market.US, start=bounds[0], end=bounds[1])
    if ret != RET_OK:
        raise RuntimeError('无法取得美股交易日历，请稍后重试。')
    dates = sorted(item['time'] for item in days)
    TRADING_DATES_CACHE = (bounds, dates)
    return dates


def finite(value):
    """把 SDK 数值转为 JSON 兼容浮点数，缺失值保持为空。"""
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def cached_daily_quote(symbol, selected_date):
    """使用已验证的复权历史日K线补充所选日期价格，缺失时不替用现价。"""
    path = ROOT.parent / '.data' / 'raw' / (symbol + '.json')
    try:
        record = json.loads(path.read_text())
        for quote in record['prices']:
            if str(quote['time_key'])[:10] == selected_date:
                return quote
    except (OSError, ValueError, KeyError):
        pass
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


def fetch_snapshot(symbols, selected_date=''):
    """按日期读取日级资金流或最新快照，保持缓存隔离及请求限频。"""
    global LAST_FLOW_REQUEST
    cache_key = (tuple(symbols), selected_date)
    with LOCK:
        cached = CACHE.get(cache_key)
        if cached and time.monotonic() - cached[0] < (3600 if selected_date else 60):
            return cached[1]
        from_context = get_context()
        from futu import RET_OK, PeriodType
        dates = trading_dates(from_context)
        if selected_date and selected_date not in dates:
            raise ValueError('所选日期不是可查询的已结束美股交易日，请选择其他日期。')
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
                      'flowTime': '', 'quoteTime': '', 'providerTime': '', 'flowStatus': 'unavailable',
                      'history': []}
            if quote is not None:
                record['name'] = str(quote.get('name', symbol))
            if quote is not None and not selected_date:
                record.update(price=finite(quote.get('last_price')),
                              low=finite(quote.get('low_price')), high=finite(quote.get('high_price')),
                              quoteTime=str(quote.get('update_time', '')))
                previous_close = finite(quote.get('prev_close_price'))
                if record['price'] is not None and previous_close and previous_close > 0:
                    record['change'] = (record['price'] / previous_close - 1) * 100
                bid, ask = finite(quote.get('bid_vol')), finite(quote.get('ask_vol'))
                if bid is not None and ask is not None and ask > 0:
                    record['ba'] = bid / ask
            if selected_date:
                historical_quote = cached_daily_quote(symbol, selected_date)
                if historical_quote:
                    record.update(price=finite(historical_quote.get('close')),
                                  change=finite(historical_quote.get('change_rate')),
                                  low=finite(historical_quote.get('low')), high=finite(historical_quote.get('high')),
                                  quoteTime=selected_date + ' · 前复权日K线')
            if quote is not None or selected_date:
                interval = 1.05 - (time.monotonic() - LAST_FLOW_REQUEST)
                if interval > 0:
                    time.sleep(interval)
                LAST_FLOW_REQUEST = time.monotonic()
                if selected_date:
                    start = max(history_bounds()[0], (datetime.fromisoformat(selected_date) - timedelta(days=35)).date().isoformat())
                    flow_ret, flow = from_context.get_capital_flow('US.' + symbol, period_type=PeriodType.DAY,
                                                                  start=start, end=selected_date)
                else:
                    flow_ret, flow = from_context.get_capital_flow('US.' + symbol, period_type=PeriodType.INTRADAY)
                if flow_ret == RET_OK and not flow.empty:
                    flow = flow.sort_values('capital_flow_item_time')
                    if selected_date:
                        for _, day in flow.tail(20).iterrows():
                            big, super_flow = finite(day.get('big_in_flow')), finite(day.get('super_in_flow'))
                            main = (big + super_flow) / 10000 if big is not None and super_flow is not None else None
                            record['history'].append({'date': str(day['capital_flow_item_time'])[:10], 'main': main})
                        flow = flow[flow['capital_flow_item_time'].astype(str).str[:10] == selected_date]
                    if flow.empty:
                        rows.append(record)
                        continue
                    latest = flow.iloc[-1]
                    for key, upstream in [('big', 'big_in_flow'), ('super', 'super_in_flow'),
                                          ('mid', 'mid_in_flow'), ('small', 'sml_in_flow')]:
                        value = finite(latest.get(upstream))
                        record[key] = value / 10000 if value is not None else None
                    valid_time = str(latest.get('last_valid_time', ''))
                    record['flowTime'] = str(latest.get('capital_flow_item_time', ''))
                    record['providerTime'] = valid_time if valid_time != 'N/A' else ''
                    record['flowStatus'] = 'ok' if record['big'] is not None and record['super'] is not None else 'unavailable'
            rows.append(record)
        if not any(row['flowStatus'] == 'ok' for row in rows):
            raise RuntimeError('没有取得可用资金流，请检查美股行情权限及标的是否支持资金流。')
        result = {'source': 'futu-opend', 'unit': 'USD_10000', 'timezone': 'America/New_York',
                  'mode': 'history' if selected_date else 'live', 'date': selected_date,
                  'tradingDates': dates,
                  'generatedAt': datetime.now(timezone.utc).isoformat(), 'rows': rows}
        if len(CACHE) >= 8:
            CACHE.pop(next(iter(CACHE)))
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
        if parsed.path in {'/api/snapshot', '/api/validation'}:
            origin = self.headers.get('Origin', '')
            own_origins = {f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}'}
            if origin and origin not in ALLOWED_ORIGINS | own_origins:
                self.respond(403, {'error': '请在 FLOW_ALLOWED_ORIGINS 中配置网站域名。'})
                return
            if TOKEN and not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + TOKEN):
                self.respond(401, {'error': '访问令牌无效。'})
                return
            if parsed.path == '/api/validation':
                path = ROOT.parent / '.data' / 'validation.json'
                try:
                    self.respond(200, json.loads(path.read_text()))
                except (OSError, ValueError):
                    self.respond(404, {'error': '历史验证尚未完成，请稍后查看。'})
                return
            raw = parse_qs(parsed.query).get('symbols', [','.join(DEFAULT_SYMBOLS)])[0]
            symbols = list(dict.fromkeys(raw.upper().split(',')))
            if not 1 <= len(symbols) <= 60 or any(not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}', code) for code in symbols):
                self.respond(400, {'error': '请提供 1 至 60 个有效的美股代码。'})
                return
            selected_date = parse_qs(parsed.query).get('date', [''])[0]
            if selected_date:
                try:
                    valid_date = datetime.strptime(selected_date, '%Y-%m-%d').date().isoformat()
                    minimum, maximum = history_bounds()
                    if valid_date != selected_date or not minimum <= selected_date <= maximum:
                        raise ValueError
                except ValueError:
                    self.respond(400, {'error': '历史日期需在最近一年内，且早于当前美东日期。'})
                    return
            try:
                self.respond(200, fetch_snapshot(symbols, selected_date))
            except ValueError as error:
                self.respond(400, {'error': str(error)})
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
