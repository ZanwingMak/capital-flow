"""市场风险、量价状态和公开延时期权结构；仅处理只读行情。"""
import csv
import html
import json
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import alpaca_data

ROOT = Path(__file__).resolve().parent
NY = ZoneInfo('America/New_York')
VIX_URL = 'https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv'
AAII_URL = 'https://www.aaii.com/sentimentsurvey'
CBOE_URL = 'https://cdn.cboe.com/api/global/delayed_quotes/options/'
CACHE = {}
CACHE_LOCK = threading.Lock()


def finite(value):
    """将非有限或缺失数据保留为空，不用零冒充缺失。"""
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def unavailable(reason, source=''):
    """统一描述单个数据模块的失败，其他模块仍可展示。"""
    return {'status': 'unavailable', 'reason': reason, 'source': source}


def cached(key, seconds, loader):
    """缓存已成功读取的数据；失败不会覆盖有效缓存或变成零值。"""
    with CACHE_LOCK:
        item = CACHE.get(key)
        if item and time.monotonic() - item[0] < seconds:
            return item[1]
    result = loader()
    with CACHE_LOCK:
        if len(CACHE) > 80:
            CACHE.pop(next(iter(CACHE)))
        CACHE[key] = (time.monotonic(), result)
    return result


def read_public(url, as_json=False):
    """读取固定官方公开端点，仅对瞬时失败有限重试，不绕过403限制。"""
    for attempt in range(2):
        try:
            request = Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json,text/csv,text/html'})
            with urlopen(request, timeout=18) as response:
                body = response.read(32 * 1024 * 1024 + 1)
            if len(body) > 32 * 1024 * 1024:
                raise RuntimeError('公开数据超过读取上限，未使用截断结果。')
            text = body.decode('utf-8-sig')
            return json.loads(text) if as_json else text
        except HTTPError as error:
            if attempt == 0 and (error.code == 429 or error.code >= 500):
                time.sleep(1)
                continue
            raise RuntimeError('官方数据源暂不可读（HTTP ' + str(error.code) + '）。') from None
        except (URLError, TimeoutError, OSError, ValueError):
            if attempt:
                raise RuntimeError('官方数据源连接失败或响应格式已变化。') from None
            time.sleep(1)


def vix_report(as_of):
    """按截至日选择Cboe已公布的VIX收盘值，标明滞后而不替换日期。"""
    try:
        text = cached('vix-csv', 900, lambda: read_public(VIX_URL))
        rows = []
        for row in csv.DictReader(text.splitlines()):
            date = datetime.strptime(row['DATE'], '%m/%d/%Y').date().isoformat()
            value = finite(row.get('CLOSE'))
            if date <= as_of and value is not None:
                rows.append((date, value))
        rows.sort()
        if not rows:
            raise RuntimeError('截至所选日期没有VIX数据。')
        date, value = rows[-1]
        previous = rows[-2][1] if len(rows) > 1 else None
        return {'status': 'available' if date == as_of else 'stale', 'source': 'Cboe', 'url': VIX_URL,
                'asOf': date, 'value': value, 'change': value - previous if previous is not None else None,
                'changePct': (value / previous - 1) * 100 if previous else None,
                'label': '高波动' if value >= 30 else '波动升温' if value >= 20 else '波动较低',
                'history': [{'date': d, 'value': v} for d, v in rows[-60:]]}
    except (RuntimeError, KeyError, ValueError) as error:
        return unavailable(str(error), VIX_URL)


def parse_survey(text):
    """只提取AAII带日期的看多/中性/看空百分比，并检查合计。"""
    text = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', '', text, flags=re.S | re.I)
    text = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', text)))
    rows = []
    pattern = r'(\d{1,2}/\d{1,2}/\d{4})\s+(\d+(?:\.\d+)?)%\s+(\d+(?:\.\d+)?)%\s+(\d+(?:\.\d+)?)%'
    for match in re.finditer(pattern, text):
        values = list(map(float, match.group(2, 3, 4)))
        if all(0 <= value <= 100 for value in values) and abs(sum(values) - 100) <= 1:
            date = datetime.strptime(match[1], '%m/%d/%Y').date()
            rows.append({'weekEnding': date.isoformat(), 'publishedDate': (date + timedelta(days=1)).isoformat(),
                         'bullish': values[0], 'neutral': values[1], 'bearish': values[2]})
    if not rows:
        raise RuntimeError('AAII页面未返回可核验的调查表格。')
    return {'source': 'AAII', 'url': AAII_URL, 'verifiedAt': datetime.now(timezone.utc).isoformat(), 'rows': rows}


def survey_report(as_of):
    """实时读取失败时使用注明核验时间的周度样本，禁止用于发布日前的历史视图。"""
    warning = ''
    try:
        payload = cached('aaii-survey', 3600, lambda: parse_survey(read_public(AAII_URL)))
        mode = 'online'
    except RuntimeError as error:
        warning = str(error)
        try:
            payload = json.loads((ROOT / 'dist/data/aaii-survey.json').read_text(encoding='utf-8'))
            mode = 'verified-snapshot'
        except (OSError, ValueError):
            return unavailable(warning, AAII_URL)
    rows = [row for row in payload.get('rows', []) if row.get('publishedDate', '') <= as_of]
    if not rows:
        return unavailable('所选日期前没有已核验且已发布的AAII调查，不会使用未来调查。', AAII_URL)
    row = max(rows, key=lambda item: item['weekEnding'])
    age = (datetime.fromisoformat(as_of).date() - datetime.fromisoformat(row['publishedDate']).date()).days
    return {'status': 'stale' if age > 10 else 'available', 'source': 'AAII', 'url': AAII_URL,
            **row, 'mode': mode, 'verifiedAt': payload.get('verifiedAt'), 'warning': warning,
            'spread': row['bullish'] - row['bearish'],
            'bullBearRatio': row['bullish'] / row['bearish'] if row['bearish'] else None,
            'scope': '美国个人投资者对未来六个月股市方向的周度调查；不代表实际多空持仓。'}


def rsi_series(closes, period=14):
    """用Wilder平滑计算RSI，平盘序列返回50，未满窗口保持为空。"""
    values = [None] * len(closes)
    if len(closes) <= period:
        return values
    changes = [b - a for a, b in zip(closes, closes[1:])]
    gain = sum(max(0, x) for x in changes[:period]) / period
    loss = sum(max(0, -x) for x in changes[:period]) / period
    for i in range(period, len(closes)):
        if i > period:
            gain = (gain * (period - 1) + max(0, changes[i - 1])) / period
            loss = (loss * (period - 1) + max(0, -changes[i - 1])) / period
        values[i] = 50 if gain == loss == 0 else 100 if loss == 0 else 100 - 100 / (1 + gain / loss)
    return values


def drawdown_summary(rows):
    """以同一复权口径的收盘价计算回撤、完整恢复周期及未恢复区间。"""
    peak = rows[0]
    episode = None
    episodes, path = [], []
    for i, row in enumerate(rows):
        if row['close'] >= peak['close']:
            if episode:
                episode.update(recoveryDate=row['date'], durationBars=i - episode.pop('peakIndex'))
                episodes.append(episode)
                episode = None
            peak = row
            peak_index = i
        else:
            depth = (row['close'] / peak['close'] - 1) * 100
            if episode is None:
                episode = {'peakDate': peak['date'], 'peakClose': peak['close'], 'peakIndex': peak_index,
                           'troughDate': row['date'], 'troughClose': row['close'], 'depthPct': depth, 'recoveryDate': None}
            if depth < episode['depthPct']:
                episode.update(troughDate=row['date'], troughClose=row['close'], depthPct=depth)
        path.append({'date': row['date'], 'close': row['close'], 'drawdown': (row['close'] / peak['close'] - 1) * 100})
    if episode:
        episode['durationBars'] = len(rows) - 1 - episode.pop('peakIndex')
        episodes.append(episode)
    windows = []
    for window in (20, 60, 252):
        if len(rows) < window + 1:
            windows.append({'days': window, 'maxDrawdownPct': None, 'coveredBars': len(rows)})
            continue
        rolling_peak, worst = 0.0, 0.0
        for row in rows[-window - 1:]:
            rolling_peak = max(rolling_peak, row['close'])
            worst = min(worst, (row['close'] / rolling_peak - 1) * 100)
        windows.append({'days': window, 'maxDrawdownPct': worst, 'coveredBars': window + 1})
    return {'currentPct': path[-1]['drawdown'], 'peakDate': peak['date'], 'peakClose': peak['close'],
            'maxDrawdownPct': min(item['drawdown'] for item in path), 'start': rows[0]['date'],
            'end': rows[-1]['date'], 'windows': windows,
            'episodes': sorted(episodes, key=lambda item: item['depthPct'])[:6], 'path': path[-252:]}


def technical_report(rows, source, as_of):
    """仅用已完成日线识别趋势和反弹质量，超卖状态不产生买入结论。"""
    rows = sorted((row for row in rows if row['date'] <= as_of), key=lambda row: row['date'])
    if len(rows) < 60 or len({row['date'] for row in rows}) != len(rows):
        return unavailable('有效且无重复的已完成日线不足60根。', source)
    for row in rows:
        if any(finite(row.get(key)) is None or row[key] <= 0 for key in ('open', 'high', 'low', 'close')):
            return unavailable('历史价格存在缺失或无效值，未补零计算。', source)
        if row['high'] < max(row['open'], row['close']) or row['low'] > min(row['open'], row['close']) or row['low'] > row['high']:
            return unavailable('历史OHLC范围不一致，未计算技术状态。', source)
    closes = [row['close'] for row in rows]
    close, previous = closes[-1], closes[-2]
    ma = {str(n): sum(closes[-n:]) / n if len(rows) >= n else None for n in (5, 20, 50, 200)}
    rsi = rsi_series(closes)[-1]
    sd = math.sqrt(sum((x - ma['20']) ** 2 for x in closes[-20:]) / 20)
    upper, lower = ma['20'] + 2 * sd, ma['20'] - 2 * sd
    volume = [finite(row.get('volume')) if finite(row.get('volume')) is not None and finite(row.get('volume')) >= 0 else None for row in rows]
    baseline = sum(volume[-21:-1]) / 20 if len(volume) >= 21 and all(v is not None and v >= 0 for v in volume[-21:-1]) else None
    relative = volume[-1] / baseline if volume[-1] is not None and baseline and baseline > 0 else None
    trs = [max(row['high'] - row['low'], abs(row['high'] - rows[i - 1]['close']), abs(row['low'] - rows[i - 1]['close']))
           for i, row in enumerate(rows) if i > 0]
    atr = sum(trs[:14]) / 14
    for value in trs[14:]:
        atr = (atr * 13 + value) / 14
    slope = (ma['20'] / (sum(closes[-25:-5]) / 20) - 1) * 100
    bear = close < ma['20'] < ma['50'] and slope < 0
    bull = close > ma['20'] > ma['50'] and slope > 0
    state = 'bearish' if bear else 'bullish' if bull else 'transition'
    change = (close / previous - 1) * 100
    distribution, covered_pairs = [], 0
    for i in range(max(1, len(rows) - 20), len(rows)):
        if volume[i] is not None and volume[i - 1] is not None:
            covered_pairs += 1
            if volume[i] > volume[i - 1] and (closes[i] / closes[i - 1] - 1) * 100 <= -.2:
                distribution.append(rows[i]['date'])
    volume_reason = '' if covered_pairs == 20 else '成交量缺失或无效，无法确定完整20日放量下跌次数。'
    rebound = '延续下跌' if change < 0 else '尚无明确反弹'
    if change > 0:
        rebound = '反弹获量价确认' if close > rows[-2]['high'] and close > ma['5'] and relative is not None and relative >= 1.2 else '反弹尚待量价确认'
    flags = []
    if bear:
        flags.append('收盘低于MA20及MA50，且MA20向下：趋势仍偏空。')
    if rsi <= 30:
        flags.append('RSI处于超卖区；超卖可能延续，不能单独视为见底。')
    if rsi >= 70:
        flags.append('RSI处于超买区；强趋势中也可能维持超买。')
    if covered_pairs == 20 and len(distribution) >= 4:
        flags.append('近20个交易日多次放量下跌，反弹需观察能否收回均线。')
    if change > 0 and close < ma['20']:
        flags.append('当前收涨仍处于MA20下方，尚未完成趋势修复。')
    return {'status': 'available' if rows[-1]['date'] == as_of else 'stale', 'source': source,
            'asOf': rows[-1]['date'], 'bars': len(rows), 'close': close, 'change': change, 'ma': ma,
            'rsi14': rsi, 'rsiState': '超卖' if rsi <= 30 else '超买' if rsi >= 70 else '中性',
            'bollinger': {'middle': ma['20'], 'upper': upper, 'lower': lower,
                          'percentB': (close - lower) / (upper - lower) * 100 if upper > lower else None},
            'relativeVolume20': relative, 'atr14': atr, 'atrPct': atr / close * 100,
            'ma20Slope5Pct': slope, 'distanceMA20Pct': (close / ma['20'] - 1) * 100,
            'trend': state, 'rebound': rebound, 'distributionDays20': len(distribution) if covered_pairs == 20 else None,
            'distributionCoverage': {'status': 'complete' if covered_pairs == 20 else 'partial' if covered_pairs else 'unknown',
                                     'available': covered_pairs, 'expected': 20, 'reason': volume_reason},
            'distributionDates': distribution, 'flags': flags, 'drawdown': drawdown_summary(rows)}


def alpaca_daily(symbols, as_of):
    """完整分页读取Alpaca SIP调整后日线，限定在选定市场交易日结束前。"""
    start = (datetime.fromisoformat(as_of).date() - timedelta(days=1200)).isoformat()
    end = datetime.fromisoformat(as_of).replace(hour=23, minute=59, second=59, tzinfo=NY).isoformat()
    params = {'symbols': ','.join(symbols), 'start': start, 'end': end, 'timeframe': '1Day',
              'feed': 'sip', 'adjustment': 'all', 'limit': 10000, 'sort': 'asc'}
    result = {symbol: [] for symbol in symbols}
    seen = set()
    for _ in range(12):
        payload = alpaca_data.request_json(alpaca_data.DATA_URL + 'bars', params)
        if not isinstance(payload.get('bars'), dict):
            raise RuntimeError('Alpaca日线格式错误。')
        for symbol, bars in payload['bars'].items():
            if symbol not in result:
                continue
            for bar in bars:
                date = datetime.fromisoformat(bar['t'].replace('Z', '+00:00')).astimezone(NY).date().isoformat()
                if date <= as_of:
                    result[symbol].append({'date': date, 'open': finite(bar.get('o')), 'high': finite(bar.get('h')),
                                          'low': finite(bar.get('l')), 'close': finite(bar.get('c')), 'volume': finite(bar.get('v'))})
        token = payload.get('next_page_token')
        if not token:
            return result
        if token in seen:
            raise RuntimeError('Alpaca分页重复，未使用截断历史。')
        seen.add(token)
        params['page_token'] = token
    raise RuntimeError('历史行情超过分页上限。')


def daily_reports(symbols, market, as_of, futu_loader):
    """美股优先复用已配置SIP，缺失时再读富途；标明每个标的实际来源。"""
    result, error = {}, ''
    if market == 'US' and alpaca_data.status()['configured']:
        try:
            records = cached(('alpaca-daily', tuple(symbols), as_of), 900, lambda: alpaca_daily(symbols, as_of))
            for symbol, rows in records.items():
                if rows:
                    result[symbol] = technical_report(rows, 'Alpaca SIP · adjustment=all', as_of)
        except (RuntimeError, ValueError) as failure:
            error = str(failure)
    for symbol in symbols:
        if result.get(symbol, {}).get('status') == 'available':
            continue
        try:
            rows = cached(('futu-daily', market, symbol, as_of), 900, lambda: futu_loader(symbol, as_of))
            result[symbol] = technical_report(rows, '富途 OpenD · 前复权日线', as_of)
        except (RuntimeError, ValueError) as failure:
            if symbol not in result:
                result[symbol] = unavailable((error + '；' if error else '') + str(failure))
    return result


def regime_report(benchmarks):
    """按已完成日线形成透明市场状态，不把空头情绪或超卖当成胜率。"""
    valid = [row for row in benchmarks.values() if row.get('status') == 'available']
    if len(valid) < 2:
        return unavailable('至少需要两个同期有效基准才能判断市场状态。')
    bearish = sum(row['trend'] == 'bearish' for row in valid)
    bullish = sum(row['trend'] == 'bullish' for row in valid)
    state = 'defensive' if bearish >= math.ceil(len(valid) / 2) else 'constructive' if bullish == len(valid) else 'mixed'
    labels = {'defensive': '防守环境', 'constructive': '趋势改善', 'mixed': '分化 / 过渡'}
    return {'status': 'available', 'state': state, 'label': labels[state], 'validBenchmarks': len(valid),
            'bearishBenchmarks': bearish, 'bullishBenchmarks': bullish,
            'rule': '偏空：收盘 < MA20 < MA50，且MA20近5日向下；至少半数基准偏空时标为防守环境。',
            'checks': ['观察能否收回MA20并守住前一日低点。', '反弹放量且收盘突破前一日高点，比单纯RSI超卖更有确认意义。',
                       '期权集中价位可能迁移或失效，不能当作必守支撑。']}


def parse_options(payload, symbol):
    """解析Cboe标准期权合约；排除调整合约，保留缺失OI及其覆盖信息。"""
    data = payload.get('data', {})
    spot = finite(data.get('current_price'))
    if not spot or not isinstance(data.get('options'), list):
        raise RuntimeError('Cboe未返回有效期权链与标的参考价。')
    rows, skipped = [], 0
    for row in data['options']:
        match = re.fullmatch(r'(.+?)(\d{6})([CP])(\d{8})', str(row.get('option', '')))
        if not match or match[1] != symbol:
            skipped += 1
            continue
        try:
            expiry = datetime.strptime(match[2], '%y%m%d').date().isoformat()
        except ValueError:
            skipped += 1
            continue
        oi, volume = finite(row.get('open_interest')), finite(row.get('volume'))
        iv = finite(row.get('iv'))
        rows.append({'code': row['option'], 'expiry': expiry, 'type': match[3], 'strike': int(match[4]) / 1000,
                     'oi': oi if oi is not None and oi >= 0 else None,
                     'volume': volume if volume is not None and volume >= 0 else None,
                     'ivPct': iv * 100 if iv is not None and iv > 0 else None,
                     'bid': finite(row.get('bid')), 'ask': finite(row.get('ask')),
                     'lastTradeTime': row.get('last_trade_time')})
    return {'rows': rows, 'spot': spot, 'providerTimestamp': payload.get('timestamp'),
            'underlyingLastTradeTime': data.get('last_trade_time'), 'skippedContracts': skipped}


def option_scope(rows, spot):
    """按同一期权范围计算P/C、持仓集中价与异动候选，不推断买卖方向或做市商净Gamma。"""
    calls = [row for row in rows if row['type'] == 'C']
    puts = [row for row in rows if row['type'] == 'P']
    totals = {}
    for side, group in [('call', calls), ('put', puts)]:
        for field in ('oi', 'volume'):
            values = [row[field] for row in group]
            totals[side + field.title()] = sum(values) if values and all(v is not None for v in values) else None
    strikes = {}
    anomalies = []
    for row in rows:
        strike = row['strike']
        if .8 * spot <= strike <= 1.2 * spot:
            bucket = strikes.setdefault(strike, {'strike': strike, 'callOI': None, 'putOI': None})
            if row['oi'] is not None:
                key = 'callOI' if row['type'] == 'C' else 'putOI'
                bucket[key] = (bucket[key] or 0) + row['oi']
        ratio = row['volume'] / row['oi'] if row['oi'] and row['volume'] is not None else None
        if row['volume'] is not None and row['volume'] >= 500 and (ratio is not None and ratio >= 2 or row['oi'] == 0):
            anomalies.append({**row, 'volumeOIRatio': ratio, 'reason': '成交量 / OI ≥ 2' if ratio is not None else '零OI高成交，不能计算比值'})
    missing_oi = sum(row['oi'] is None for row in rows)
    candidate_coverage = sum(row['oi'] is not None and row['volume'] is not None for row in rows)
    # 任一OI缺失都可能改变聚合和排序；不向调用方返回局部墙或局部行权价排名。
    walls = list(strikes.values()) if not missing_oi else []
    upper = sorted((row for row in walls if row['strike'] >= spot and row['callOI'] is not None and row['callOI'] > 0), key=lambda row: row['callOI'], reverse=True)[:3]
    lower = sorted((row for row in walls if row['strike'] <= spot and row['putOI'] is not None and row['putOI'] > 0), key=lambda row: row['putOI'], reverse=True)[:3]
    selected = sorted(walls, key=lambda row: (row['callOI'] or 0) + (row['putOI'] or 0), reverse=True)[:18]
    anomalies.sort(key=lambda row: (row['volume'], row['volumeOIRatio'] or 0), reverse=True)
    return {'contracts': len(rows), 'missingOI': missing_oi,
            'oiCoverage': {'status': 'partial' if missing_oi else 'complete',
                           'available': len(rows) - missing_oi, 'expected': len(rows),
                           'reason': 'OI不完整，停止排名及分布图。' if missing_oi else ''},
            'anomalyCoverage': {'status': 'complete' if candidate_coverage == len(rows) else 'partial',
                                'available': candidate_coverage, 'expected': len(rows),
                                'reason': '局部样本：仅筛选OI与成交量均已知的合约。' if candidate_coverage < len(rows) else ''},
            'missingVolume': sum(row['volume'] is None for row in rows), 'totals': totals,
            'putCallOI': totals['putOi'] / totals['callOi'] if totals['putOi'] is not None and totals['callOi'] else None,
            'putCallVolume': totals['putVolume'] / totals['callVolume'] if totals['putVolume'] is not None and totals['callVolume'] else None,
            'upperCallWalls': upper, 'lowerPutWalls': lower, 'strikes': sorted(selected, key=lambda row: row['strike']),
            'anomalyCount': len(anomalies), 'anomalies': anomalies[:20]}


def option_snapshot_quality(timestamp, now):
    """以带时区的报价时间判定质量；保守限制当日60分钟，不推断OI日期或休市日。"""
    policy = '仅美东当日且滞后不超过60分钟的带时区报价快照可用；不代表OI有效时间。'
    result = {'status': 'missing_timestamp', 'reason': '期权快照时间缺失，未展示。',
              'policy': policy, 'maxAgeSeconds': 3600, 'ageSeconds': None}
    if not timestamp:
        return result
    try:
        stamp = datetime.fromisoformat(str(timestamp).replace('Z', '+00:00'))
    except ValueError:
        return {**result, 'status': 'invalid_timestamp', 'reason': '期权快照时间格式无效，未展示。'}
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        return {**result, 'status': 'timezone_unknown', 'reason': '期权快照未提供明确时区，无法核验时效，未展示。'}
    age = (now - stamp).total_seconds()
    if age < 0:
        return {**result, 'status': 'future_timestamp', 'reason': '期权快照时间超前，未展示。', 'ageSeconds': age}
    stale = stamp.astimezone(NY).date() != now.astimezone(NY).date() or age > 3600
    return {**result, 'status': 'stale' if stale else 'available', 'ageSeconds': age,
            'reason': '报价快照滞后；不作为当前墙或异动信号。' if stale else ''}


def options_report(symbol, market, requested_date, horizon=30, now=None):
    """读取免费延时期权链，历史视图不冒用当前OI，所有范围均明确显示。"""
    now = now or datetime.now(NY)
    today = now.astimezone(NY).date().isoformat()
    if market != 'US':
        return unavailable('目前仅接入美股 / ETF 的Cboe公开延时期权链。')
    if requested_date and requested_date != today:
        reason = ('历史期权链未接入；不会用今天的OI替代所选历史日期。' if requested_date < today else
                  '所选期权日期超前，未使用当前链替代未来日期。')
        return {**unavailable(reason, CBOE_URL), 'oiAsOf': None,
                'snapshotQuality': {'status': 'historical_unavailable' if requested_date < today else 'future_request', 'reason': reason}}
    try:
        url = CBOE_URL + symbol + '.json'
        chain = cached(('cboe-options', symbol), 600, lambda: parse_options(read_public(url, True), symbol))
        quality = option_snapshot_quality(chain.get('providerTimestamp'), now)
        if quality['status'] not in {'available', 'stale'}:
            return {**unavailable(quality['reason'], url), 'snapshotQuality': quality,
                    'providerTimestamp': chain.get('providerTimestamp'), 'oiAsOf': None}
        end = (datetime.fromisoformat(today).date() + timedelta(days=horizon)).isoformat()
        rows = [row for row in chain['rows'] if today <= row['expiry'] <= end]
        if not rows:
            raise RuntimeError('该标的未来所选天数内没有可用标准期权合约。')
        expiries = sorted({row['expiry'] for row in rows})
        scopes = {'all': option_scope(rows, chain['spot'])}
        for expiry in expiries:
            scopes[expiry] = option_scope([row for row in rows if row['expiry'] == expiry], chain['spot'])
        return {'status': quality['status'], 'reason': quality['reason'], 'snapshotQuality': quality,
                'source': 'Cboe · 延时报价', 'url': url, 'oiAsOf': None,
                'providerTimestamp': chain['providerTimestamp'], 'capturedAt': now.astimezone(timezone.utc).isoformat(),
                'underlyingLastTradeTime': chain['underlyingLastTradeTime'], 'spot': chain['spot'],
                'horizonDays': horizon, 'start': today, 'end': end, 'expiries': expiries, 'scopes': scopes,
                'skippedContracts': chain['skippedContracts'],
                'limits': ['OI是最近公布的存量，接口未提供独立的OI有效日期，不能解释为盘中增仓。',
                           'P/C是合约成交或持仓比，不是实际多空资金、开仓方向或获胜比例。',
                           quality['policy'],
                           '所选范围OI完整时才给出上下20%集中价排名；Call/Put集中不保证形成阻力/支撑，未计算做市商净GEX。',
                           '异动仅按成交量≥500且成交量/OI≥2筛选，按成交量排序；零OI单列，极小OI会放大比值，不认定为机构买入、扫单或买Call看多。']}
    except (RuntimeError, ValueError, KeyError) as error:
        return unavailable(str(error), CBOE_URL)


def overview(market, as_of, symbols, daily_loader, breadth_loader):
    """组合市场状态与相互独立的情绪来源，保留各模块有效时间和覆盖。"""
    names = {'US': ['SPY', 'QQQ', 'IWM', 'SOXX'], 'HK': ['02800', '02828'],
             'CN': ['SH.510300', 'SZ.159915']}[market]
    benchmarks = daily_reports(names, market, as_of, daily_loader)
    with ThreadPoolExecutor(max_workers=2) as pool:
        vix_future = pool.submit(vix_report, as_of) if market == 'US' else None
        survey_future = pool.submit(survey_report, as_of) if market == 'US' else None
        try:
            breadth = breadth_loader(symbols)
        except RuntimeError as error:
            breadth = unavailable(str(error), '富途 OpenD')
        vix = vix_future.result() if vix_future else unavailable('VIX仅作为美国市场指标，本市场不混用。')
        survey = survey_future.result() if survey_future else unavailable('AAII仅调查美国个人投资者，本市场不混用。')
    return {'source': 'flowdesk-intelligence', 'schemaVersion': 1, 'market': market,
            'asOf': as_of, 'capturedAt': datetime.now(timezone.utc).isoformat(),
            'benchmarks': benchmarks, 'regime': regime_report(benchmarks),
            'vix': vix, 'retailSurvey': survey, 'breadth': breadth}


def stock_report(symbol, market, as_of, requested_date, horizon, daily_loader, distribution_loader):
    """返回个股技术、回撤、真实小单压力与期权信息；单一来源失败不清空其他结果。"""
    technical = daily_reports([symbol], market, as_of, daily_loader)[symbol]
    options = options_report(symbol, market, requested_date, horizon)
    try:
        distribution = distribution_loader(symbol, as_of)
    except RuntimeError as error:
        distribution = unavailable(str(error), '富途 OpenD')
    return {'source': 'flowdesk-intelligence', 'schemaVersion': 1, 'symbol': symbol, 'market': market,
            'asOf': as_of, 'requestedDate': requested_date, 'capturedAt': datetime.now(timezone.utc).isoformat(),
            'technical': technical, 'options': options, 'smallOrders': distribution}
