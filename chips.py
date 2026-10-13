"""真实订单规模分布与近期逐笔价量样本；不推算投资者持仓成本。"""
import json
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def finite(value):
    """读取有限非负数，保留碎股成交量，缺失不补零。"""
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (TypeError, ValueError):
        return None


def distribution(rows, date):
    """按资金有效日期校验四类真实流入和流出，金额保持原币。"""
    if not rows or str(rows[0].get('update_time', ''))[:10] != date:
        return {'status': 'missing', 'reason': '资金分布尚未更新到所选日期。'}
    row, groups = rows[0], []
    for key, label in [('super', '特大单'), ('big', '大单'), ('mid', '中单'), ('small', '小单')]:
        incoming, outgoing = finite(row.get('capital_in_' + key)), finite(row.get('capital_out_' + key))
        groups.append({'key': key, 'label': label, 'in': incoming, 'out': outgoing,
                       'net': incoming - outgoing if incoming is not None and outgoing is not None else None})
    small = groups[-1]
    total = small['in'] + small['out'] if small['in'] is not None and small['out'] is not None else None
    return {'status': 'available', 'time': str(row['update_time']), 'groups': groups,
            'smallSellShare': small['out'] / total * 100 if total else None,
            'mainNet': sum(item['net'] for item in groups[:2]) if all(item['net'] is not None for item in groups[:2]) else None}


def volume_profile(rows, date, close):
    """聚合实际逐笔价格及股数，排除跨日、盘外、无效和重复记录。"""
    ticks, seen = [], set()
    for row in rows:
        stamp = str(row.get('time', ''))
        price, volume = finite(row.get('price')), finite(row.get('volume'))
        identity = str(row.get('sequence', ''))
        if stamp[:10] != date or not '09:30:00' <= stamp[11:19] <= close or not price or not volume:
            continue
        if identity and identity in seen:
            continue
        seen.add(identity)
        ticks.append({**row, 'sequence': identity, 'price': price, 'volume': volume})
    if not ticks:
        return {'status': 'missing', 'reason': '没有所选日期常规交易时段的有效逐笔样本。'}
    ticks.sort(key=lambda item: str(item['time']))
    low, high = min(item['price'] for item in ticks), max(item['price'] for item in ticks)
    width = (high - low) / 24 if high > low else 0
    buckets = {}
    for item in ticks:
        index = min(23, int((item['price'] - low) / width)) if width else 0
        bucket = buckets.setdefault(index, {'low': low + index * width, 'high': low + (index + 1) * width,
                                             'buy': 0., 'sell': 0., 'neutral': 0., 'volume': 0.})
        direction = str(item.get('ticker_direction', '')).lower()
        bucket[direction if direction in {'buy', 'sell'} else 'neutral'] += item['volume']
        bucket['volume'] += item['volume']
    total = sum(item['volume'] for item in ticks)
    return {'status': 'available', 'count': len(ticks), 'from': str(ticks[0]['time']), 'to': str(ticks[-1]['time']),
            'volume': total, 'sampleVwap': sum(item['price'] * item['volume'] for item in ticks) / total,
            'bins': list(buckets.values())}


def fetch(context, call, root, symbol, code, market, zone, date=''):
    """读取最新真实分布并留存样本；历史日期只返回已归档的同日数据。"""
    now = datetime.now(ZoneInfo(zone))
    date = date or now.date().isoformat()
    if datetime.strptime(date, '%Y-%m-%d').date().isoformat() != date or date > now.date().isoformat():
        raise ValueError('请选择有效日期，不能查询未来日期。')
    folder = Path(root) / '.data' / 'chips' / market / symbol / date
    path = folder / 'latest.json'
    if date != now.date().isoformat():
        if not path.exists():
            raise ValueError('所选日期没有已留存的筹码观察样本；不会替换为今天数据。')
        payload = json.loads(path.read_text(encoding='utf-8'))
        payload['archived'] = True
        return payload
    payload = {'source': 'futu-opend', 'market': market, 'symbol': symbol, 'date': date,
               'timezone': zone, 'currency': {'US': 'USD', 'HK': 'HKD', 'CN': 'CNY'}[market],
               'capturedAt': now.isoformat(), 'archived': False,
               'costDistribution': {'status': 'unavailable', 'reason': '当前富途公开接口未提供投资者持仓成本筹码分布。'}}
    raw = {}
    ret, data = call(context.get_capital_distribution, code)
    raw['distribution'] = data.to_dict(orient='records') if ret == 0 else {'error': str(data)}
    payload['orderDistribution'] = distribution(raw['distribution'], date) if ret == 0 else {'status': 'missing', 'reason': str(data)}
    payload['volumeProfile'] = {'status': 'unavailable', 'reason': '逐笔价量观察目前仅接入已核验的美股常规时段。'}
    if market == 'US':
        ret, days = call(context.request_trading_days, market='US', start=date, end=date)
        session = next((item for item in days if item.get('time') == date), None) if ret == 0 else None
        if ret != 0:
            payload['volumeProfile'] = {'status': 'missing', 'reason': '无法核验交易日历：' + str(days)}
        elif session is None:
            payload['volumeProfile'] = {'status': 'missing', 'reason': '所选日期不是美股交易日。'}
        else:
            from futu import SubType
            close = '13:00:00' if session.get('trade_date_type') == 'HALF' else '16:00:00'
            ret, message = call(context.subscribe, [code], [SubType.TICKER], subscribe_push=False)
            if ret == 0:
                ret, data = call(context.get_rt_ticker, code, num=1000)
                raw['ticks'] = data.to_dict(orient='records') if ret == 0 else {'error': str(data)}
                if ret == 0:
                    for item in raw['ticks']:
                        item['sequence'] = str(item.get('sequence', ''))
                    payload['volumeProfile'] = volume_profile(raw['ticks'], date, close)
                else:
                    payload['volumeProfile'] = {'status': 'missing', 'reason': str(data)}
            else:
                payload['volumeProfile'] = {'status': 'missing', 'reason': str(message)}
    folder.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime('%H%M%S%f')
    (folder / (stamp + '-raw.json')).write_text(json.dumps(raw, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    (folder / (stamp + '.json')).write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    if payload['orderDistribution']['status'] == 'available' or payload['volumeProfile']['status'] == 'available':
        temporary = folder / 'latest.tmp'
        temporary.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        temporary.replace(path)
    return payload
