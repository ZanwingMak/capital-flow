"""用 Alpaca SIP 历史逐笔成交与报价估算尾盘大额买卖压力。"""
import gzip
import json
import math
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
NY = ZoneInfo('America/New_York')
DATA_URL = 'https://data.alpaca.markets/v2/stocks/'
EXCLUDED = {'B', 'C', 'G', 'H', 'I', 'M', 'N', 'O', 'P', 'Q', 'R', 'T', 'U', 'V', 'W', 'X', 'Z', '4', '5', '6', '7', '9'}


def credentials():
    """每次查询读取本机配置，只接受两个行情密钥字段且不输出其内容。"""
    values = {}
    try:
        for line in (ROOT / '.env').read_text(encoding='utf-8').splitlines():
            key, separator, value = line.strip().partition('=')
            if separator and key in {'APCA_API_KEY_ID', 'APCA_API_SECRET_KEY'}:
                values[key] = value.strip().strip('"\'')
    except OSError:
        pass
    return tuple(os.getenv(key) or values.get(key, '') for key in ('APCA_API_KEY_ID', 'APCA_API_SECRET_KEY'))


def status():
    """只报告密钥是否齐全，不将密钥或账户信息发送给网页。"""
    return {'source': 'alpaca-sip', 'configured': all(credentials()), 'feed': 'sip',
            'message': '密钥已配置，行情权限需通过实际查询验证。' if all(credentials()) else '请在本机 .env 填写 APCA_API_KEY_ID 和 APCA_API_SECRET_KEY。'}


def request_json(url, parameters):
    """仅调用 Alpaca 官方只读端点，对限流和瞬时失败最多重试两次。"""
    key, secret = credentials()
    if not key or not secret:
        raise ValueError('尚未配置 Alpaca 密钥；请在本机项目 .env 中填写两项密钥并保存，无需重启。')
    request = Request(url + '?' + urlencode(parameters), headers={
        'APCA-API-KEY-ID': key, 'APCA-API-SECRET-KEY': secret,
        'Accept': 'application/json', 'Accept-Encoding': 'gzip'})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=25) as response:
                stream = gzip.GzipFile(fileobj=response) if response.headers.get('Content-Encoding') == 'gzip' else response
                return json.load(stream)
        except HTTPError as error:
            if error.code in {401, 403}:
                raise RuntimeError('Alpaca 拒绝访问：请检查密钥有效性及 SIP 历史成交、报价权限；不会自动切换到 IEX。') from None
            if error.code == 429 or error.code >= 500:
                if attempt < 2:
                    delay = error.headers.get('Retry-After', '2')
                    time.sleep(min(15, max(1, int(delay) if delay.isdigit() else 2) * (attempt + 1)))
                    continue
                raise RuntimeError('Alpaca 限流或服务暂不可用，请稍后重试。') from None
            raise ValueError('Alpaca 不接受此次查询（HTTP ' + str(error.code) + '），请检查日期和标的。') from None
        except (URLError, TimeoutError, OSError, ValueError) as error:
            if attempt == 2:
                raise RuntimeError('无法取得 Alpaca 的有效响应，请检查网络后重试。') from None
            time.sleep(attempt + 1)


def pages(resource, symbol, start, end, progress):
    """完整遍历升序行情分页；超过上限或分页重复时拒绝返回残缺结果。"""
    parameters = {'symbols': symbol, 'start': start, 'end': end, 'feed': 'sip', 'limit': 10000, 'sort': 'asc'}
    if resource == 'bars':
        parameters.update(timeframe='1Day', adjustment='all')
    tokens = set()
    for index in range(200):
        label = {'trades': '历史成交', 'quotes': '历史报价', 'bars': '调整后日线'}[resource]
        progress(index, 200, '读取 ' + symbol + ' ' + label + ' · 第 ' + str(index + 1) + ' 页')
        payload = request_json(DATA_URL + resource, parameters)
        if not isinstance(payload.get(resource), dict):
            raise RuntimeError('Alpaca 行情响应缺少有效数据，未按零成交处理。')
        yield payload[resource].get(symbol, [])
        token = payload.get('next_page_token')
        if not token:
            return
        if token in tokens:
            raise RuntimeError('Alpaca 分页重复，无法确认窗口完整性，请重试。')
        tokens.add(token)
        parameters['page_token'] = token
        time.sleep(0.35)
    raise RuntimeError('该窗口行情超过分页上限，未使用截断数据计算资金方向。')


def timestamp_ns(stamp):
    """保留逐笔时间的纳秒精度，避免报价与成交因浮点舍入错序。"""
    match = re.fullmatch(r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?(Z|[+-]\d\d:\d\d)', stamp)
    if not match:
        raise RuntimeError('Alpaca 返回了无法识别的行情时间。')
    seconds = int(datetime.fromisoformat(match[1] + match[3].replace('Z', '+00:00')).timestamp())
    return seconds * 1000000000 + int((match[2] or '').ljust(9, '0'))


def number(value):
    """剔除非有限数值，避免无效价格或数量污染估算。"""
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def aggregate(trades, quote_pages, start, close, threshold):
    """用不晚于成交且最多五秒前的有效报价分类大额交易，无法判断的金额单列。"""
    buckets = [{'time': (start + timedelta(minutes=i)).strftime('%H:%M'), 'buy': 0.0, 'sell': 0.0,
                'unknown': 0.0, 'excluded': 0.0, 'trades': 0, 'largeTrades': 0, 'quoteUpdates': 0}
               for i in range(20)]
    begin, finish = int(start.timestamp()) * 1000000000, int(close.timestamp()) * 1000000000
    eligible, rejected, closing_auction = [], 0, 0.0
    for trade in trades:
        stamp, price, size = timestamp_ns(trade['t']), number(trade.get('p')), number(trade.get('s'))
        if price is None or size is None or price <= 0 or size <= 0:
            rejected += 1
            continue
        amount = price * size / 10000
        conditions = set(trade.get('c', []))
        if '6' in conditions and begin <= stamp <= finish + 60000000000:
            closing_auction += amount
        if not begin <= stamp < finish:
            continue
        bucket = buckets[(stamp - begin) // 60000000000]
        bucket['trades'] += 1
        if conditions & EXCLUDED:
            bucket['excluded'] += amount
        elif price * size >= threshold:
            bucket['largeTrades'] += 1
            eligible.append((stamp, price, amount, bucket))
    eligible.sort(key=lambda item: item[0])
    cursor, latest, last_stamp, quote_count = 0, None, -1, 0
    for page in quote_pages:
        for quote in page:
            stamp = timestamp_ns(quote['t'])
            if stamp < last_stamp:
                raise RuntimeError('Alpaca 报价顺序异常，不能可靠匹配成交方向。')
            last_stamp = stamp
            while cursor < len(eligible) and eligible[cursor][0] < stamp:
                trade_stamp, price, amount, bucket = eligible[cursor]
                side = 'unknown'
                if latest and 0 <= trade_stamp - latest[0] <= 5000000000:
                    if price >= latest[2]:
                        side = 'buy'
                    elif price <= latest[1]:
                        side = 'sell'
                bucket[side] += amount
                cursor += 1
            bid, ask = number(quote.get('bp')), number(quote.get('ap'))
            if bid is not None and ask is not None and 0 < bid < ask and (number(quote.get('bs')) or 0) > 0 and (number(quote.get('as')) or 0) > 0:
                latest = (stamp, bid, ask)
            else:
                latest = None
            quote_count += 1
            if begin <= stamp < finish:
                buckets[(stamp - begin) // 60000000000]['quoteUpdates'] += 1
    while cursor < len(eligible):
        trade_stamp, price, amount, bucket = eligible[cursor]
        side = 'unknown'
        if latest and 0 <= trade_stamp - latest[0] <= 5000000000:
            side = 'buy' if price >= latest[2] else 'sell' if price <= latest[1] else 'unknown'
        bucket[side] += amount
        cursor += 1
    windows = []
    for minutes in (10, 20):
        selected = buckets[-minutes:]
        sums = {field: sum(row[field] for row in selected) for field in ('buy', 'sell', 'unknown', 'excluded', 'trades', 'largeTrades', 'quoteUpdates')}
        total = sums['buy'] + sums['sell'] + sums['unknown']
        classified = sums['buy'] + sums['sell']
        windows.append({'minutes': minutes, **sums, 'netEstimate': sums['buy'] - sums['sell'] if total else None,
                        'classifiedRatio': classified / total if total else None,
                        'directionReliable': bool(total and classified / total >= 0.8 and abs(sums['buy'] - sums['sell']) > sums['unknown'])})
    for row in buckets:
        row['netEstimate'] = row['buy'] - row['sell'] if row['largeTrades'] else None
    return {'rows': buckets, 'windows': windows, 'tradeCount': sum(row['trades'] for row in buckets), 'quoteCount': quote_count,
            'invalidTrades': rejected, 'closingAuctionAmount': closing_auction, 'paginationComplete': True}


def future_prices(symbol, date, days, calendar, progress):
    """按官方交易日历对齐拆股和分红调整后的日线，缺失交易日保留断点。"""
    selected = [item['date'] for item in calendar][:days + 1]
    start = datetime.fromisoformat(date).replace(tzinfo=NY)
    end = (datetime.fromisoformat(selected[-1]) + timedelta(days=1)).replace(tzinfo=NY)
    end = min(end, datetime.now(timezone.utc) - timedelta(minutes=16))
    prices = {}
    for page in pages('bars', symbol, start.isoformat(), end.isoformat(), progress):
        for row in page:
            day = datetime.fromisoformat(row['t'].replace('Z', '+00:00')).astimezone(NY).date().isoformat()
            prices[day] = number(row.get('c'))
    anchor = prices.get(date)
    if not anchor or anchor <= 0:
        raise RuntimeError('事件日没有有效收盘价，无法计算后续收益。')
    rows = []
    previous = None
    for index, day in enumerate(selected):
        close = prices.get(day)
        rows.append({'day': index, 'date': day, 'close': close,
                     'change': (close / previous - 1) * 100 if close and previous else None,
                     'cumulative': (close / anchor - 1) * 100 if close else None})
        previous = close
    return rows


def fetch_tail(symbol, date, days, threshold, progress):
    """获取一个历史事件的完整尾盘成交和报价，独立缓存且不混入富途主力数据。"""
    today = datetime.now(NY).date()
    requested = datetime.strptime(date, '%Y-%m-%d').date()
    if not today - timedelta(days=365) <= requested < today:
        raise ValueError('请选择最近一年内已结束的美东日期。')
    if not all(credentials()):
        raise ValueError('请先在本机 .env 配置 Alpaca API Key 和 Secret Key。')
    progress(0, 1, '验证 Alpaca 交易日历和历史权限')
    key = credentials()[0]
    calendar_url = ('https://paper-api.alpaca.markets' if key.startswith('PK') else 'https://api.alpaca.markets') + '/v2/calendar'
    calendar_end = min(today - timedelta(days=1), requested + timedelta(days=days * 2 + 14)).isoformat()
    calendar = request_json(calendar_url, {'start': date, 'end': calendar_end})
    if not isinstance(calendar, list) or not calendar or calendar[0].get('date') != date:
        raise ValueError('所选日期不是 Alpaca 日历中的已结束交易日。')
    close = datetime.fromisoformat(date + 'T' + calendar[0]['close']).replace(tzinfo=NY)
    start = close - timedelta(minutes=20)
    path = ROOT / '.data' / 'alpaca' / symbol / (date + '-v1.json.gz')
    try:
        with gzip.open(path, 'rt', encoding='utf-8') as file:
            cached = json.load(file)
        if cached.get('start') != start.isoformat() or cached.get('close') != close.isoformat():
            raise ValueError
        trades, quotes = cached['trades'], cached['quotes']
        progress(1, 1, '复用已完整下载的 SIP 历史成交与报价')
    except (OSError, ValueError, KeyError, EOFError):
        trades = [row for page in pages('trades', symbol, start.isoformat(), close.isoformat(), progress) for row in page]
        quotes = [row for page in pages('quotes', symbol, (start - timedelta(seconds=5)).isoformat(), close.isoformat(), progress) for row in page]
        if not trades or not quotes:
            raise RuntimeError('该尾盘窗口缺少成交或报价，无法判断资金方向；未返回零资金。')
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        with gzip.open(temporary, 'wt', encoding='utf-8') as file:
            json.dump({'source': 'alpaca-sip', 'start': start.isoformat(), 'close': close.isoformat(), 'trades': trades, 'quotes': quotes}, file, allow_nan=False)
        temporary.replace(path)
    auction_path = path.with_name(date + '-auction-v1.json.gz')
    try:
        with gzip.open(auction_path, 'rt', encoding='utf-8') as file:
            auction_trades = json.load(file)
    except (OSError, ValueError, EOFError):
        progress(0, 1, '补取收盘后一分钟内报告的集合竞价成交，单独展示')
        auction_trades = [row for page in pages('trades', symbol, close.isoformat(),
                          (close + timedelta(minutes=1)).isoformat(), progress) for row in page]
        temporary = auction_path.with_suffix('.tmp')
        with gzip.open(temporary, 'wt', encoding='utf-8') as file:
            json.dump(auction_trades, file, allow_nan=False)
        temporary.replace(auction_path)
    close_ns = int(close.timestamp()) * 1000000000
    trades = trades + [row for row in auction_trades if timestamp_ns(row['t']) > close_ns]
    metrics = aggregate(trades, [quotes], start, close, threshold)
    rows = future_prices(symbol, date, days, calendar, progress)
    return {'source': 'alpaca-sip', 'market': 'US', 'feed': 'sip', 'unit': 'USD_10000', 'symbol': symbol,
            'date': date, 'start': start.isoformat(), 'closeTime': close.isoformat(), 'largeThresholdUSD': threshold,
            'auctionReportUntil': (close + timedelta(minutes=1)).isoformat(),
            'adjustment': 'split-and-dividend', 'requestedDays': days, 'availableDays': len(rows) - 1,
            'path': rows, **metrics,
            'method': '按单笔成交金额划分大额成交，不是按原始委托单划分；不晚于成交且最多5秒前的有效买卖报价用于估算主动方向。价在卖一及以上视为买入，买一及以下视为卖出，中间价、失效报价和缺失报价归为无法判断。尾盘压力排除收盘集合竞价、盘外、交叉及其他特殊成交条件，条件I的零股成交也排除；收盘后一分钟内报告的集合竞价成交额单独列出。覆盖率为可分类大额金额占比；80%仅是界面质量门槛，不代表算法准确率。指标不识别机构身份，与富途口径不同；后续价格采用拆股与分红调整，事件日收盘基准收益不是实际策略成交收益。'}
