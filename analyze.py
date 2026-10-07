"""用真实日级资金流与复权价格检验同期相关性和后续方向预测力。"""
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from futu import AuType, KLType, OpenQuoteContext, PeriodType, RET_OK

ROOT = Path(__file__).resolve().parent
DATA = ROOT / '.data'
RAW = DATA / 'raw'
HORIZONS = (1, 5, 20)


def save_json(path, data):
    """原子保存市场数据及结果，避免服务读取到尚未写完的文件。"""
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def collect(symbols, start, end):
    """缓存一年资金流与日K线，每类请求限频并逐标的保存进度。"""
    RAW.mkdir(parents=True, exist_ok=True)
    context = OpenQuoteContext(host='127.0.0.1', port=11111)
    failures, records = [], {}
    try:
        ret, quota = context.get_history_kl_quota(get_detail=False)
        if ret != RET_OK:
            raise RuntimeError('无法确认历史K线额度。')
        print('历史K线剩余额度:', quota[1], flush=True)
        for index, symbol in enumerate(symbols):
            path = RAW / (symbol + '.json')
            if path.exists():
                existing = json.loads(path.read_text())
                if existing.get('start') == start and existing.get('end') == end:
                    records[symbol] = existing
                    print(f'{index+1}/{len(symbols)} {symbol} 使用缓存', flush=True)
                    continue
            ret, flow = context.get_capital_flow('US.' + symbol, period_type=PeriodType.DAY, start=start, end=end)
            if ret != RET_OK:
                failures.append({'symbol': symbol, 'stage': 'capital_flow', 'message': str(flow)})
                continue
            time.sleep(1.1)
            ret, prices, page = context.request_history_kline('US.' + symbol, start=start, end=end,
                                                             ktype=KLType.K_DAY, autype=AuType.QFQ,
                                                             max_count=1000)
            if ret != RET_OK or page is not None:
                failures.append({'symbol': symbol, 'stage': 'prices', 'message': str(prices) if ret != RET_OK else '日K线未完整返回'})
                continue
            record = {'symbol': symbol, 'start': start, 'end': end, 'adjustment': 'QFQ',
                      'flow': json.loads(flow.to_json(orient='records')),
                      'prices': json.loads(prices.to_json(orient='records'))}
            save_json(path, record)
            records[symbol] = record
            print(f'{index+1}/{len(symbols)} {symbol} 资金流 {len(flow)} 天 / 价格 {len(prices)} 天', flush=True)
            time.sleep(1.1)
    finally:
        context.close()
    return records, failures


def build_panel(records):
    """在完整交易日历上计算后续收益，不把缺失日期压缩成下一个交易日。"""
    benchmark = pd.DataFrame(records['SPY']['prices'])
    benchmark['date'] = benchmark['time_key'].str[:10]
    benchmark = benchmark.set_index('date').sort_index()
    calendar = benchmark.index
    panels, coverage = [], []
    for symbol, record in records.items():
        prices, flows = pd.DataFrame(record['prices']), pd.DataFrame(record['flow'])
        prices['date'], flows['date'] = prices['time_key'].str[:10], flows['capital_flow_item_time'].str[:10]
        if prices['date'].duplicated().any() or flows['date'].duplicated().any():
            raise RuntimeError('存在重复交易日：' + symbol)
        prices = prices.set_index('date').reindex(calendar)
        flows = flows.set_index('date').reindex(calendar)
        main = pd.to_numeric(flows['big_in_flow'], errors='coerce') + pd.to_numeric(flows['super_in_flow'], errors='coerce')
        turnover = pd.to_numeric(prices['turnover'], errors='coerce')
        data = pd.DataFrame({'symbol': symbol, 'main': main, 'factor': main / turnover.where(turnover > 0),
                             'same_return': prices['close'] / prices['last_close'].where(prices['last_close'] > 0) - 1,
                             'close': prices['close'], 'date': calendar}, index=calendar)
        data.loc[data['factor'].abs() > 1, 'factor'] = np.nan
        for horizon in HORIZONS:
            data[f'return_{horizon}'] = prices['close'].shift(-horizon) / prices['close'] - 1
            data[f'excess_{horizon}'] = data[f'return_{horizon}'] - (benchmark['close'].shift(-horizon) / benchmark['close'] - 1)
            data[f'executable_{horizon}'] = prices['close'].shift(-horizon) / prices['open'].shift(-1) - 1
            data[f'end_{horizon}'] = pd.Series(calendar, index=calendar).shift(-horizon)
        coverage.append({'symbol': symbol, 'days': int(data[['factor', 'same_return']].dropna().shape[0]),
                         'first': data['factor'].first_valid_index(), 'last': data['factor'].last_valid_index()})
        panels.append(data.reset_index(drop=True))
    panel = pd.concat(panels, ignore_index=True).replace([np.inf, -np.inf], np.nan)
    return panel, coverage, list(calendar)


def rank_corr(a, b):
    """用平均秩的 Pearson 相关系数计算 Spearman，保留并列秩。"""
    values = pd.concat([a, b], axis=1).dropna()
    if len(values) < 8 or values.iloc[:, 0].nunique() < 2 or values.iloc[:, 1].nunique() < 2:
        return np.nan
    return values.iloc[:, 0].rank().corr(values.iloc[:, 1].rank())


def block_interval(values, block_size, seed=20261007):
    """按连续交易日区块重采样，保留同日共振及多日收益重叠。"""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < max(20, block_size * 2):
        return None
    random = np.random.default_rng(seed)
    blocks = int(np.ceil(len(values) / block_size))
    starts = random.integers(0, len(values), size=(3000, blocks))
    positions = (starts[:, :, None] + np.arange(block_size)) % len(values)
    means = values[positions.reshape(3000, -1)[:, :len(values)]].mean(axis=1)
    return [float(value) for value in np.quantile(means, [.025, .975])]


def daily_metrics(panel, target):
    """按日期等权计算横截面IC与前后四分位收益差。"""
    result = []
    for date, group in panel.groupby('date', sort=True):
        group = group.dropna(subset=['factor', target, 'same_return'])
        if len(group) < 16:
            continue
        ranked = group.sort_values(['factor', 'symbol'])
        size = max(1, len(ranked) // 4)
        result.append({'date': date, 'ic': rank_corr(group['factor'], group[target]),
                       'momentum_ic': rank_corr(group['same_return'], group[target]),
                       'spread': ranked.iloc[-size:][target].mean() - ranked.iloc[:size][target].mean()})
    return pd.DataFrame(result)


def summarize(panel, horizon):
    """报告同一可用样本上的上涨基线、方向命中率和超额收益。"""
    target = f'return_{horizon}'
    data = panel.dropna(subset=['factor', target, f'excess_{horizon}'])
    nonzero = data[(data['main'] != 0) & (data[target] != 0)]
    inflow, outflow = nonzero[nonzero['main'] > 0], nonzero[nonzero['main'] < 0]
    metrics = daily_metrics(data, f'excess_{horizon}')
    if metrics.empty:
        return {'horizon': horizon, 'observations': 0}
    return {'horizon': horizon, 'observations': len(data), 'classification_n': len(nonzero), 'dates': len(metrics),
            'baseline_up': float((nonzero[target] > 0).mean()),
            'direction_accuracy': float((np.sign(nonzero['main']) == np.sign(nonzero[target])).mean()),
            'inflow_n': len(inflow), 'outflow_n': len(outflow),
            'inflow_up': float((inflow[target] > 0).mean()), 'outflow_up': float((outflow[target] > 0).mean()),
            'inflow_excess': float(inflow[f'excess_{horizon}'].mean()),
            'outflow_excess': float(outflow[f'excess_{horizon}'].mean()),
            'ic': float(metrics['ic'].mean()), 'momentum_ic': float(metrics['momentum_ic'].mean()),
            'ic_ci': block_interval(metrics['ic'], max(5, horizon)),
            'quartile_spread': float(metrics['spread'].mean()),
            'spread_ci': block_interval(metrics['spread'], max(5, horizon)),
            'next_open_inflow_return': float(inflow[f'executable_{horizon}'].mean()),
            'next_open_outflow_return': float(outflow[f'executable_{horizon}'].mean())}


def analyze(records, failures, start, end, requested):
    """按事先固定的1/5/20日周期计算结果，并对时间后段单独复核。"""
    panel, coverage, dates = build_panel(records)
    split = dates[int(len(dates) * .7)]
    same = daily_metrics(panel, 'same_return')
    summaries = []
    for horizon in HORIZONS:
        early = panel[(panel['date'] < split) & (panel[f'end_{horizon}'] < split)]
        late = panel[panel['date'] >= split]
        summaries.append({'horizon': horizon, 'all': summarize(panel, horizon),
                          'early': summarize(early, horizon), 'late': summarize(late, horizon)})
    return {'source': 'futu-opend', 'start': start, 'end': end, 'split': split,
            'generatedAt': datetime.now(ZoneInfo('UTC')).isoformat(),
            'requested_symbols': requested, 'available_symbols': len(records), 'trading_days': len(dates),
            'coverage': coverage, 'failures': failures,
            'same_day_ic': float(same['ic'].mean()), 'same_day_ic_ci': block_interval(same['ic'], 5),
            'horizons': summaries,
            'daily': {str(h): daily_metrics(panel, f'excess_{h}').to_dict(orient='records') for h in HORIZONS},
            'method': {'factor': '(大单净流入+特大单净流入)/当日成交额',
                       'returns': '信号日收盘至随后第N个交易日收盘的前复权价格变化；不等同可成交策略收益',
                       'benchmark': 'SPY同期前复权价格变化', 'bootstrap': '按交易日区块重采样3000次，区块长度max(5,N)，95%区间',
                       'limits': ['当前48标的构成，有幸存者与选择偏差', 'ETF和持仓重叠，区块重采样不能消除全部依赖',
                                  '20日周期有效独立区块有限', '未计手续费、滑点、分红现金及借券成本',
                                  '未控制全部行业、动量、波动因子', '三个周期的探索性检验，未校正多重比较',
                                  '日级流入流出是提供方成交分类，没有确认机构身份']}}


def main():
    """采集并复核数据，输出可重复计算的本地结果。"""
    symbols = re.findall(r"^\['([A-Z][A-Z0-9.-]*)'", (ROOT / 'dist/app.js').read_text(), re.MULTILINE)
    today = datetime.now(ZoneInfo('America/New_York')).date()
    start, end = (today - timedelta(days=365)).isoformat(), (today - timedelta(days=1)).isoformat()
    records, failures = collect(symbols, start, end)
    if 'SPY' not in records:
        raise RuntimeError('缺少SPY基准，无法完成验证。')
    report = analyze(records, failures, start, end, len(symbols))
    save_json(DATA / 'validation.json', report)
    brief = {key: report[key] for key in ['start', 'end', 'split', 'available_symbols', 'trading_days', 'same_day_ic', 'horizons', 'failures']}
    print(json.dumps(brief, ensure_ascii=False, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
