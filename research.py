"""真实资金事件研究：分钟留存、尾盘累计差值与大额净流出后的逐日走势。"""
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parent / '.data' / 'minutes'


def finite(value):
    """只保留有限数值，缺失值不按零处理。"""
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def main_amount(row):
    """以大单加特大单定义主力净额，统一换算为原币万元。"""
    big, extra = finite(row.get('big_in_flow')), finite(row.get('super_in_flow'))
    return (big + extra) / 10000 if big is not None and extra is not None else None


def save_minutes(market, symbol, records, sessions):
    """合并真实累计分钟资金并原子留存；交易日类型不明时不推算收盘时间。"""
    grouped = {}
    for row in records:
        stamp = str(row.get('capital_flow_item_time', ''))
        try:
            datetime.strptime(stamp, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue
        valid_time = str(row.get('last_valid_time', ''))
        try:
            if datetime.strptime(stamp, '%Y-%m-%d %H:%M:%S') > datetime.strptime(valid_time, '%Y-%m-%d %H:%M:%S'):
                continue
        except ValueError:
            pass
        amount = main_amount(row)
        if amount is not None:
            grouped.setdefault(stamp[:10], {})[stamp] = amount
    paths = []
    for date, points in grouped.items():
        path = DATA / market / symbol / (date + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        old = read_minutes(path)
        merged = {row['time']: row['main'] for row in old.get('points', [])}
        merged.update(points)
        day_type = sessions.get(date)
        close = ({'US': '13:00', 'HK': '12:00'}.get(market) if day_type == 'HALF' else
                 {'US': '16:00', 'HK': '16:00', 'CN': '15:00'}.get(market) if day_type == 'WHOLE' else None)
        record = {'source': 'futu-opend', 'market': market, 'symbol': symbol, 'date': date,
                  'closeTime': close or old.get('closeTime'), 'dayType': day_type or old.get('dayType'),
                  'points': [{'time': time, 'main': value} for time, value in sorted(merged.items())]}
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        temporary.replace(path)
        paths.append(record)
    return paths


def read_minutes(path):
    """读取本机分钟留存，文件缺失或损坏时返回空记录。"""
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if data.get('source') == 'futu-opend' else {}
    except (OSError, ValueError, AttributeError):
        return {}


def tail_window(record, minutes):
    """尾盘净额等于收盘累计净额减窗口起点累计净额，要求每分钟完整覆盖。"""
    date, close = record.get('date'), record.get('closeTime')
    if not date or not close:
        return {'minutes': minutes, 'main': None, 'complete': False, 'reason': '收盘时刻未确认'}
    end = datetime.fromisoformat(date + 'T' + close)
    start = end - timedelta(minutes=minutes)
    points = {row['time']: finite(row.get('main')) for row in record.get('points', [])}
    expected = [(start + timedelta(minutes=i)).strftime('%Y-%m-%d %H:%M:%S') for i in range(minutes + 1)]
    valid = all(points.get(stamp) is not None for stamp in expected)
    return {'minutes': minutes, 'start': expected[0], 'end': expected[-1], 'complete': valid,
            'coveredPoints': sum(points.get(stamp) is not None for stamp in expected), 'expectedPoints': minutes + 1,
            'main': points[expected[-1]] - points[expected[0]] if valid else None,
            'reason': '' if valid else '窗口分钟记录不完整，尚不能判断尾盘净额'}


def future_rows(prices, calendar, date, days):
    """按市场交易日历对齐后续每日收益，缺失收盘保留断点且不压缩交易日。"""
    anchor = finite(prices.get(date, {}).get('close'))
    if not anchor or anchor <= 0 or date not in calendar:
        return []
    start = calendar.index(date)
    rows = []
    for offset, day in enumerate(calendar[start:start + days + 1]):
        price = prices.get(day, {})
        close, previous = finite(price.get('close')), finite(price.get('last_close'))
        rows.append({'day': offset, 'date': day, 'close': close,
                     'change': (close / previous - 1) * 100 if close and previous and previous > 0 else None,
                     'cumulative': (close / anchor - 1) * 100 if close and close > 0 else None})
    return rows


def quantile(values, percentile):
    """计算线性插值分位数，只接受已经发生的有效样本。"""
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * percentile / 100
    low = int(position)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (position - low)


def summarize_events(events, days):
    """按T+1至T+X统计真实可观察样本，未满期和缺失价格不进入分母。"""
    summary = []
    for horizon in range(1, days + 1):
        values = [event['path'][horizon]['cumulative'] for event in events
                  if len(event['path']) > horizon and event['path'][horizon]['cumulative'] is not None]
        summary.append({'day': horizon, 'samples': len(values), 'average': sum(values) / len(values) if values else None,
                        'upRate': sum(value > 0 for value in values) / len(values) if values else None})
    return summary


def build_research(record, calendar, market, symbol, as_of, lookback, span, percentile, minimum, days, kind, direction):
    """使用此前60个同跨度窗口设定异常阈值，构建资金事件和后续实际价格。"""
    prices = {str(row['time_key'])[:10]: row for row in record['prices']}
    flows = {str(row['capital_flow_item_time'])[:10]: main_amount(row) for row in record['flow']}
    eligible = [day for day in calendar if day <= as_of]
    selected = eligible[-lookback:]
    windows, events = [], []
    archives = [read_minutes(path) for path in sorted((DATA / market / symbol).glob('*.json'))]
    archived = {item.get('date'): item for item in archives if item}
    tail = {}
    for date, item in archived.items():
        tail[date] = {str(size): tail_window(item, size) for size in (10, 20)}
    for index, date in enumerate(eligible):
        start_index = index - span + 1
        interval = eligible[max(0, start_index):index + 1]
        amounts = [flows.get(day) for day in interval]
        daily = sum(amounts) if start_index >= 0 and all(value is not None for value in amounts) else None
        amount = daily if kind == 'daily' else tail.get(date, {}).get(kind[-2:], {}).get('main')
        prior = windows[-60:]
        candidates = [abs(value) for value in prior if value is not None and
                      (value < 0 if direction == 'out' or direction == 'both' and amount is not None and amount < 0 else value > 0)]
        threshold = quantile(candidates, percentile) if len(candidates) >= 10 else None
        flag = (amount is not None and (amount < 0 if direction == 'out' else amount > 0 if direction == 'in' else amount != 0))
        if date in selected and flag and abs(amount) >= minimum and (kind != 'daily' or threshold is not None and abs(amount) >= threshold):
            path = future_rows(prices, calendar, date, days)
            events.append({'date': date, 'start': interval[0] if kind == 'daily' else date,
                           'main': amount, 'threshold': max(minimum, threshold) if threshold is not None else minimum,
                           'baselineSamples': len(candidates), 'direction': 'out' if amount < 0 else 'in', 'path': path,
                           'availableDays': max(0, len(path) - 1), 'complete': len(path) == days + 1 and all(item['cumulative'] is not None for item in path),
                           'recent': date in eligible[-5:]})
        windows.append(amount)
    events.reverse()
    available = [date for date in selected if tail.get(date, {}).get(kind[-2:], {}).get('complete')] if kind != 'daily' else [date for date in selected if flows.get(date) is not None]
    historical_archives = [item for item in archives if item.get('date', '') <= as_of]
    latest_archive = historical_archives[-1] if historical_archives else {}
    return {'source': 'futu-opend', 'market': market, 'symbol': symbol,
            'name': next((str(row['name']) for row in record['prices'] if row.get('name')), symbol),
            'asOf': eligible[-1] if eligible else as_of, 'start': selected[0] if selected else as_of,
            'adjustment': 'QFQ', 'kind': kind, 'direction': direction, 'lookback': lookback, 'span': span,
            'percentile': percentile, 'minimum': minimum, 'requestedDays': days,
            'events': events, 'recentAlerts': [event for event in events if event['recent'] and event['direction'] == 'out'],
            'summary': summarize_events(events, days), 'coverage': {'requested': len(selected), 'available': len(available)},
            'tailLatest': {'date': latest_archive.get('date'), 'windows': [tail_window(latest_archive, size) for size in (10, 20)]},
            'minuteDates': [date for date in sorted(tail) if any(value['complete'] for value in tail[date].values())],
            'method': '主力=大单+特大单；尾盘=累计值之差。日级异常阈值使用事件前60个同跨度窗口中的同向样本，至少10个有效样本；最近提醒覆盖末5个已结束交易日。事件可能重叠，结果仅为描述性观察，不代表独立预测证据。'}
