"""USD 正股事件校验与移动加权账面成本重放；不计算税务批次。"""
from collections import defaultdict
from decimal import Decimal, localcontext
from uuid import uuid4
from datetime import datetime
from zoneinfo import ZoneInfo
from private_common import LedgerError, canonical, day, decimal, label, now, stamp, symbol, text_number

KINDS = {'opening', 'cash_opening', 'buy', 'sell', 'deposit', 'withdrawal', 'fee', 'dividend', 'split', 'group', 'void'}
GROUPS = {'core', 'tactical', 'ungrouped'}


def normalize_event(data):
    """冻结来源、原文和日期精度，只规范已声明支持的业务字段。"""
    if not isinstance(data, dict) or data.get('kind') not in KINDS or data.get('currency', 'USD') != 'USD':
        raise LedgerError('仅支持 USD 正股账本动作。')
    result = {k: data[k] for k in ('kind', 'symbol', 'target', 'reason', 'external_id', 'reference', 'replaces', 'raw', 'line', 'sequence') if k in data}
    result.update(id=str(uuid4()), currency='USD', trade_date=day(data.get('trade_date')),
                  source=label(data.get('source')), received_at=now(),
                  available_at=stamp(data.get('available_at'), optional=True),
                  effective_at=stamp(data.get('effective_at'), optional=True),
                  group=data.get('group', 'ungrouped'))
    result['precision'] = 'instant' if result['effective_at'] else 'date'
    if result['effective_at'] and datetime.fromisoformat(result['effective_at']).astimezone(ZoneInfo('America/New_York')).date().isoformat() != result['trade_date']:
        raise LedgerError('实际执行时间与美东交易日期不一致。')
    if result['group'] not in GROUPS:
        raise LedgerError('分组必须为底仓、短线或未分组。')
    if 'sequence' in result and (type(result['sequence']) is not int or result['sequence'] < 0):
        raise LedgerError('人工确认顺序必须为非负整数。')
    kind = result['kind']
    if kind in {'opening', 'buy', 'sell', 'dividend', 'split', 'group'}:
        result['symbol'] = symbol(result.get('symbol'))
    for key in ('external_id', 'reference', 'replaces'):
        if key in result:
            result[key] = label(result[key], 200)
    if kind in {'opening', 'buy', 'sell', 'split'}:
        value = decimal(data.get('quantity'))
        if value <= 0:
            raise LedgerError('数量或拆股比例必须大于零。')
        result['quantity'] = text_number(value)
    if kind == 'opening':
        cost = decimal(data.get('total_cost'), optional=True)
        if cost is not None and cost < 0:
            raise LedgerError('期初总成本不能为负。')
        result['total_cost'] = text_number(cost)
    if kind in {'buy', 'sell'}:
        price, fees = decimal(data.get('price')), decimal(data.get('fees'))
        if price <= 0 or fees < 0 or (kind == 'sell' and fees > price * decimal(result['quantity'])):
            raise LedgerError('成交价格或费用无效。')
        result.update(price=text_number(price), fees=text_number(fees))
    if kind in {'cash_opening', 'deposit', 'withdrawal', 'fee', 'dividend'}:
        amount = decimal(data.get('amount'))
        if amount < 0 or (kind != 'cash_opening' and amount == 0):
            raise LedgerError('现金动作金额必须为正，期初现金可为零。')
        result['amount'] = text_number(amount)
    if kind == 'void':
        if 'replaces' in result:
            raise LedgerError('作废使用target；替代事实才使用replaces关联原事件。')
        result['target'] = label(result.get('target'))
        result['reason'] = label(result.get('reason'), 1000)
    canonical(result)
    return result


def ordered_active(events):
    """应用追加的更正，再检查期初边界与会改变成本的同日顺序。"""
    facts = {e['id']: e for e in events if e['kind'] != 'void'}
    voids = set()
    for e in events:
        if e['kind'] == 'void':
            if e['target'] not in facts or e['target'] in voids:
                raise LedgerError('更正目标不存在或已经更正。')
            voids.add(e['target'])
    active = [e for e in facts.values() if e['id'] not in voids]
    openings = [e for e in active if e['kind'] in {'opening', 'cash_opening'}]
    if len({e['trade_date'] for e in openings}) > 1:
        raise LedgerError('同一账户的期初快照必须使用同一截止日期。')
    if len({e.get('symbol', '$cash') for e in openings}) != len(openings):
        raise LedgerError('同一标的不能叠加期初快照，请追加更正记录。')
    anchor = openings[0]['trade_date'] if openings else None
    if anchor and any(e['kind'] not in {'opening', 'cash_opening', 'group'} and e['trade_date'] <= anchor for e in active):
        raise LedgerError('期初截止日及之前的增量不能叠加，避免重复计算。')
    buckets = defaultdict(list)
    for e in active:
        buckets[(e['trade_date'], e.get('symbol', ''))].append(e)
    order = {}
    for rows in buckets.values():
        trades = [e for e in rows if e['kind'] in {'buy', 'sell', 'split', 'group'}]
        kinds = {e['kind'] for e in trades}
        groups = {e['group'] for e in trades if e['group'] != 'ungrouped'}
        sensitive = len(trades) > 1 and (len(kinds) > 1 or 'group' in kinds or len(groups) > 1)
        if sensitive:
            times = [e.get('effective_at') for e in trades]
            sequences = [e.get('sequence') for e in trades]
            timed_sequences = sorted((e for e in trades if e.get('effective_at') and e.get('sequence') is not None), key=lambda e: e['sequence'])
            known_times = [e['effective_at'] for e in timed_sequences]
            if known_times != sorted(known_times):
                raise LedgerError('实际时间与人工确认顺序矛盾。')
            if all(times) and len(set(times)) == len(times):
                if all(s is not None for s in sequences) and sorted(trades, key=lambda e: e['effective_at']) != sorted(trades, key=lambda e: e['sequence']):
                    raise LedgerError('实际时间与人工确认顺序矛盾。')
                order.update({e['id']: i for i, e in enumerate(sorted(trades, key=lambda e: e['effective_at']))})
                continue
            if all(s is not None for s in sequences) and len(set(sequences)) == len(sequences):
                order.update({e['id']: i for i, e in enumerate(sorted(trades, key=lambda e: e['sequence']))})
                continue
            raise LedgerError('同日顺序待确认：请提供实际执行时间或逐笔人工顺序。')
    return sorted(active, key=lambda e: (e['trade_date'], order.get(e['id'], 0), e['id']))


def replay(events, revision, as_of=None):
    """重放数量、费用和现金流；未知成本持续传播，不输出虚构估值。"""
    with localcontext() as context:
        context.prec = 80
        return _replay(events, revision, as_of)


def _replay(events, revision, as_of):
    """在固定 Decimal 精度下计算移动加权账面成本。"""
    active = ordered_active(events)
    if as_of is not None:
        as_of = day(as_of)
        active = [e for e in active if e['trade_date'] <= as_of]
    positions = {}
    cash, balance, fees, income, funding = Decimal(0), None, Decimal(0), Decimal(0), Decimal(0)
    realized = Decimal(0)
    for e in active:
        kind = e['kind']
        p = positions.setdefault(e['symbol'], {'quantity': Decimal(0), 'cost': Decimal(0), 'group': 'ungrouped'}) if 'symbol' in e else None
        delta = Decimal(0)
        if kind == 'opening':
            p.update(quantity=decimal(e['quantity']), cost=decimal(e['total_cost'], True), group=e['group'])
        elif kind == 'cash_opening':
            balance = decimal(e['amount'])
        elif kind in {'buy', 'sell'}:
            qty, price, fee = (decimal(e[k]) for k in ('quantity', 'price', 'fees'))
            fees += fee
            if kind == 'buy':
                p['quantity'] += qty
                p['cost'] = p['cost'] + qty * price + fee if p['cost'] is not None else None
                if e['group'] != 'ungrouped':
                    p['group'] = e['group']
                delta = -qty * price - fee
            else:
                if qty > p['quantity']:
                    raise LedgerError('可用正股数量不足，不能超卖或卖空。')
                removed = p['cost'] * qty / p['quantity'] if p['cost'] is not None else None
                realized = realized + qty * price - fee - removed if realized is not None and removed is not None else None
                p['quantity'] -= qty
                p['cost'] = p['cost'] - removed if removed is not None else None
                if p['quantity'] == 0:
                    p['cost'] = Decimal(0)
                delta = qty * price - fee
        elif kind == 'split':
            if p['quantity'] == 0:
                raise LedgerError('拆股需要已有正股数量。')
            p['quantity'] *= decimal(e['quantity'])
        elif kind == 'group':
            p['group'] = e['group']
        elif kind in {'deposit', 'withdrawal', 'fee', 'dividend'}:
            amount = decimal(e['amount'])
            delta = -amount if kind in {'withdrawal', 'fee'} else amount
            if kind in {'deposit', 'withdrawal'}:
                funding += delta
            elif kind == 'fee':
                fees += amount
            else:
                income += amount
        cash += delta
        if balance is not None:
            balance += delta
    quality = ['date_only_execution'] if any(e['precision'] == 'date' and e['kind'] in {'buy', 'sell'} for e in active) else []
    if any(p['cost'] is None for p in positions.values()):
        quality.append('unknown_cost')
    if balance is None:
        quality.append('unknown_cash_baseline')
    quality.append('no_market_valuation')
    return {'revision': revision, 'asOf': as_of or max((e['trade_date'] for e in active), default=None),
            'currency': 'USD', 'cost_method': 'moving_weighted_average_not_tax',
            'positions': [{'symbol': s, **{k: text_number(v) if k != 'group' else v for k, v in p.items()}}
                          for s, p in sorted(positions.items()) if p['quantity'] != 0],
            'ledger_cash_delta': text_number(cash), 'cash_balance': text_number(balance),
            'fees': text_number(fees), 'dividend_income': text_number(income), 'net_funding': text_number(funding),
            'realized_pnl': text_number(realized), 'unrealized_pnl': None, 'total_return': None,
            'quality': quality, 'event_count': len(active)}
