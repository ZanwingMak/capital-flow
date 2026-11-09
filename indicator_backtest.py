"""无网络的US股票日线多头记账；原指标方向标签不代表期权收益。"""
import math
from statistics import mean, stdev

from indicator_engine import PRIMARY, finite, iso_date, validate_bars
from indicator_specs import CATALOG


def costs(initial=10000, fee_bps=5, slippage_bps=5):
    """限制每边费用，防止非有限输入、负费用或无法记账的资本。"""
    for value, lower, upper, name in ((initial, 1, 1e9, '初始资本'), (fee_bps, 0, 100, '每边手续费bps'), (slippage_bps, 0, 100, '每边滑点bps')):
        if isinstance(value, bool) or finite(value) is None or not lower <= value <= upper:
            raise ValueError(f'{name}须在{lower}至{upper}之间。')
    return float(initial), float(fee_bps) / 10000, float(slippage_bps) / 10000


def performance(points, initial, closed, exposed, turnover):
    """由逐日净值计算回撤和收益；胜率只含已平仓，短样本不报告夏普。"""
    peak, drawdown, previous, returns = initial, 0.0, initial, []
    for point in points:
        equity = point['equity']
        peak = max(peak, equity)
        drawdown = min(drawdown, equity / peak - 1)
        returns.append(equity / previous - 1)
        previous = equity
    deviation = stdev(returns) if len(returns) >= 30 else None
    return {'endingEquity': previous, 'totalReturn': previous / initial - 1,
            'maxDrawdown': drawdown, 'exposure': exposed / len(points) if points else None,
            'turnover': turnover / initial, 'closedTrades': len(closed),
            'winRate': sum(t['netPnl'] > 0 for t in closed) / len(closed) if closed else None,
            'sharpe': mean(returns) / deviation * math.sqrt(252) if deviation and deviation > 1e-12 else None,
            'sharpeConvention': '252日年化、零无风险利率；至少30根且日收益标准差>1e-12，否则null。'}


def run_backtest(rows, events, start=0, end=None, version='QUSHI-CHANG', initial=10000, fee_bps=5, slippage_bps=5):
    """收盘确认、次开盘执行，单仓全资金、无杠杆、不做空、不强制期末平仓。"""
    rows = validate_bars(rows)
    initial, fee, slip = costs(initial, fee_bps, slippage_bps)
    if version not in ('QUSHI-CHANG', 'QUSHI-DUAN'):
        raise ValueError('仅长短趋势定义回测策略。')
    end = len(rows) if end is None else end
    if any(isinstance(x, bool) or not isinstance(x, int) for x in (start, end)) or not 0 <= start <= end <= len(rows):
        raise ValueError('回测范围无效。')
    if not isinstance(events, (list, tuple)) or len(events) > len(rows) * 30:
        raise ValueError('事件数量超限。')
    by_index = {}
    for event in events:
        if not isinstance(event, dict):
            raise ValueError('每个事件必须为对象。')
        index, name = event.get('index'), event.get('name')
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(rows):
            raise ValueError('事件索引无效。')
        if name in PRIMARY:
            by_index.setdefault(index, set()).add(name)
    max_hold = CATALOG[version]['maxHold']
    cash, position, pending, trades, equity = initial, None, None, [], []
    exposed, turnover, unexecuted = 0, 0.0, 0
    for i in range(start, end):
        row = rows[i]
        if pending:
            if pending['action'] == 'buy':
                price = row['open'] * (1 + slip)
                shares = cash / (price * (1 + fee))
                notional = shares * price
                position = {'shares': shares, 'entryPrice': price, 'entryIndex': i,
                            'entryDate': row['date'], 'entrySignalDate': rows[pending['signalIndex']]['date'],
                            'entrySignal': pending['name'], 'entryFee': notional * fee, 'entryCapital': cash}
                cash = 0.0
            else:
                price = row['open'] * (1 - slip)
                notional = position['shares'] * price
                cash = notional * (1 - fee)
                pnl = cash - position['entryCapital']
                trades.append({**position, 'exitDate': row['date'], 'exitPrice': price,
                               'exitSignalDate': rows[pending['signalIndex']]['date'], 'exitReason': pending['name'],
                               'exitFee': notional * fee, 'netPnl': pnl, 'netReturn': pnl / position['entryCapital'],
                               'heldBars': i - position['entryIndex']})
                position = None
            turnover += notional
            pending = None
        marked = cash + (position['shares'] * row['close'] if position else 0)
        equity.append({'date': row['date'], 'equity': marked, 'cash': cash,
                       'positionValue': marked - cash})
        exposed += position is not None
        names = by_index.get(i, set())
        # 同根主方向遵循原显示优先级，且持仓时只处理退出，避免重叠资金。
        name = next((key for key in PRIMARY if key in names), None)
        if position:
            reason = name if name in ('PUTSIG', 'TOPSIG') else 'max-hold' if i - position['entryIndex'] + 1 >= max_hold else None
            if reason:
                pending = {'action': 'sell', 'signalIndex': i, 'name': reason}
        elif name in ('CALLSIG', 'BOTSIG'):
            pending = {'action': 'buy', 'signalIndex': i, 'name': name}
        if pending and i + 1 >= end:
            unexecuted += 1
    benchmark_points, benchmark_exposed, benchmark_turnover = [], 0, 0.0
    if start < end:
        benchmark_shares = initial / (rows[start]['open'] * (1 + slip) * (1 + fee))
        benchmark_turnover = benchmark_shares * rows[start]['open'] * (1 + slip)
        benchmark_points = [{'date': r['date'], 'equity': benchmark_shares * r['close']} for r in rows[start:end]]
        benchmark_exposed = len(benchmark_points)
        for point, benchmark in zip(equity, benchmark_points):
            point['benchmark'] = benchmark['equity']
    if position:
        position = {**position, 'markedDate': rows[end-1]['date'], 'markedValue': position['shares'] * rows[end-1]['close'],
                    'unrealizedPnl': position['shares'] * rows[end-1]['close'] - position['entryCapital'],
                    'pendingExitReason': pending['name'] if pending and pending['action'] == 'sell' else None}
    return {'range': {'start': rows[start]['date'] if start < end else None,
                      'end': rows[end-1]['date'] if start < end else None, 'bars': end - start},
            'rules': {'id': 'flowdesk-stock-long-next-open-1', 'version': version, 'maxHoldBars': max_hold,
                      'initialUSD': initial, 'feeBpsPerLeg': fee * 10000, 'slippageBpsPerLeg': slip * 10000,
                      'entry': ['CALLSIG', 'BOTSIG'], 'exit': ['PUTSIG', 'TOPSIG', 'max-hold'],
                      'execution': 'signal-close-known / next-bar-open', 'positionSizing': 'all-capital-fractional-shares',
                      'endPolicy': 'mark-open-position-at-close', 'stopTargetExecution': False,
                      'note': '固定持有/反向信号是新增执行约定；原公式价位仅作参考。未模拟最低佣金/点差之外的流动性与税费。'},
            'metrics': performance(equity, initial, trades, exposed, turnover),
            'benchmark': {**performance(benchmark_points, initial, [], benchmark_exposed, benchmark_turnover),
                          'policy': '同区间首开盘全仓买入、同入场成本、末收盘计价，未收取未发生的卖出费用。'},
            'equity': equity, 'trades': trades, 'openPosition': position, 'unexecutedSignals': unexecuted,
            'caution': 'CALL/PUT为股票方向标签；无期权/做空收益。胜率仅统计已平仓交易，小样本不代表稳定优势。'}


def split_ranges(rows, start=0, validation_start=None, holdout_start=None):
    """按时间60/20/20切分有效区间，或使用明确的后两段开始交易日。"""
    if isinstance(start, bool) or not isinstance(start, int) or not 0 <= start <= len(rows):
        raise ValueError('切分起点无效。')
    count = len(rows) - start
    if count < 3:
        raise ValueError('有效评价区间不足3根，不能生成三个非空切分。')
    if (validation_start is None) != (holdout_start is None):
        raise ValueError('必须同时提供验证和留出开始日期。')
    if validation_start is not None:
        dates = [r['date'] for r in rows]
        iso_date(validation_start)
        iso_date(holdout_start)
        if validation_start not in dates or holdout_start not in dates:
            raise ValueError('切分日期必须是样本内的实际交易日。')
        validation, holdout = dates.index(validation_start), dates.index(holdout_start)
        if not start < validation < holdout < len(rows):
            raise ValueError('训练、验证、留出必须严格按时间排列且各段非空。')
    else:
        validation = start + int(count * .6)
        holdout = start + int(count * .8)
    return {'train': (start, validation), 'validation': (validation, holdout), 'holdout': (holdout, len(rows))}
