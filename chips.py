"""真实订单规模资金分布；券商持仓成本筹码缺失时明确标记不可用。"""
import json
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def finite(value):
    """读取有限非负金额，缺失不补零。"""
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
        payload.pop('volumeProfile', None)
        return payload
    payload = {'source': 'futu-opend', 'market': market, 'symbol': symbol, 'date': date,
               'timezone': zone, 'currency': {'US': 'USD', 'HK': 'HKD', 'CN': 'CNY'}[market],
               'capturedAt': now.isoformat(), 'archived': False,
               'costDistribution': {'status': 'unavailable', 'reason': '当前富途公开接口未提供投资者持仓成本筹码分布。'}}
    raw = {}
    ret, data = call(context.get_capital_distribution, code)
    raw['distribution'] = data.to_dict(orient='records') if ret == 0 else {'error': str(data)}
    payload['orderDistribution'] = distribution(raw['distribution'], date) if ret == 0 else {'status': 'missing', 'reason': str(data)}
    folder.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime('%H%M%S%f')
    (folder / (stamp + '-raw.json')).write_text(json.dumps(raw, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    (folder / (stamp + '.json')).write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    if payload['orderDistribution']['status'] == 'available':
        temporary = folder / 'latest.tmp'
        temporary.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        temporary.replace(path)
    return payload
