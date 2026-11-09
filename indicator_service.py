"""注入已授权行情loader的指标研究服务；无密钥读取、外部请求或路径参数。"""
import copy
import hashlib
import json
import re
from datetime import date, datetime

from indicator_backtest import costs, run_backtest, split_ranges
from indicator_engine import COMPATIBILITY, calculate, iso_date, validate_bars
from indicator_specs import CATALOG

PARAMETERS = {'symbol', 'asOf', 'market', 'indicator', 'timeframe', 'initial', 'feeBps', 'slippageBps', 'validationStart', 'holdoutStart'}
WARNINGS = ['暂定兼容性契约，尚未完成富途逐根数值认证。',
            '只研究已完成US日线；20根HLC3加权均价不是逐笔VWAP，也不是持仓成本。',
            '固定40/20根与反向信号退出属于新增执行约定；未优化任何参数。',
            '当前复权快照可能含后来企业行动修订，不能视为严格点时历史。',
            '自选标的存在选择/幸存者偏差；六个指定标的不代表全市场。']


def parse_request(query):
    """解析HTTP查询参数，禁止未知字段、重复参数、任意公式和文件路径。"""
    if not isinstance(query, dict) or set(query) - PARAMETERS:
        raise ValueError('未知指标研究参数。')
    clean = {}
    for key, value in query.items():
        if isinstance(value, (list, tuple)):
            if len(value) != 1:
                raise ValueError('不允许重复参数。')
            value = value[0]
        if not isinstance(value, str) or not value.strip():
            raise ValueError('参数必须为非空字符串。')
        clean[key] = value.strip()
    symbol = clean.get('symbol', '').upper()
    if not re.fullmatch(r'[A-Z][A-Z0-9]{0,9}(?:[.-][A-Z0-9]{1,4})?', symbol):
        raise ValueError('仅支持有效US股票/ETF代码。')
    as_of = iso_date(clean.get('asOf'))
    indicator = clean.get('indicator', 'QUSHI-CHANG')
    if indicator not in CATALOG or not CATALOG[indicator]['supported']:
        raise ValueError(CATALOG.get(indicator, {}).get('reason', '未知指标。'))
    if clean.get('market', 'US') != 'US' or clean.get('timeframe', '1d') != '1d':
        raise ValueError('首发仅支持US日线。')
    try:
        initial, fee, slip = (float(clean.get(k, default)) for k, default in [('initial', 10000), ('feeBps', 5), ('slippageBps', 5)])
    except (TypeError, ValueError) as error:
        raise ValueError('资本/费用须为有效数值。') from error
    costs(initial, fee, slip)
    validation, holdout = clean.get('validationStart'), clean.get('holdoutStart')
    if (validation is None) != (holdout is None):
        raise ValueError('必须同时提供验证和留出开始日期。')
    if validation:
        iso_date(validation)
        iso_date(holdout)
        if not validation < holdout <= as_of:
            raise ValueError('切分日期次序无效。')
    return {'symbol': symbol, 'as_of': as_of, 'market': 'US', 'indicator': indicator,
            'initial': initial, 'fee_bps': fee, 'slippage_bps': slip,
            'validation_start': validation, 'holdout_start': holdout}


def get_report(symbol, as_of, market, loader, indicator='QUSHI-CHANG', initial=10000, fee_bps=5, slippage_bps=5,
               validation_start=None, holdout_start=None):
    """读取一次有界日线，先截断再计算；各切分共用历史暖机但从空仓独立执行。"""
    query = {'symbol': symbol, 'asOf': as_of, 'market': market, 'indicator': indicator,
             'initial': str(initial), 'feeBps': str(fee_bps), 'slippageBps': str(slippage_bps)}
    if validation_start is not None: query['validationStart'] = validation_start
    if holdout_start is not None: query['holdoutStart'] = holdout_start
    params = parse_request(query)
    # 后续所有身份、loader与截断都使用同一份已验证规范值。
    symbol, as_of, market, indicator = (params[k] for k in ('symbol', 'as_of', 'market', 'indicator'))
    validation_start, holdout_start = params['validation_start'], params['holdout_start']
    payload = loader(params['symbol'], as_of, market)
    metadata = payload if isinstance(payload, dict) else {}
    for key, expected in (('symbol', params['symbol']), ('market', market), ('timezone', 'America/New_York')):
        if key in metadata and metadata[key] != expected:
            raise ValueError('行情元数据与研究请求不一致：' + key)
    all_rows = validate_bars(metadata.get('rows', []) if isinstance(payload, dict) else payload)
    rows = [r for r in all_rows if r['date'] <= as_of]
    result = calculate(rows, indicator)
    quality = result['quality']
    first = quality['firstEligibleIndex']
    collected_at = metadata.get('collectedAt')
    if isinstance(collected_at, (date, datetime)):
        collected_at = collected_at.isoformat()
    if collected_at is not None and not isinstance(collected_at, str):
        raise ValueError('采集时间元数据须为ISO日期时间字符串。')
    report = {'source': 'flowdesk-indicators', 'schemaVersion': 1, 'engineVersion': COMPATIBILITY['id'],
              'symbol': params['symbol'], 'market': market, 'asOf': as_of, 'timeframe': '1d', 'currency': 'USD',
              'status': 'empty' if not rows else 'warming-up' if indicator.startswith('QUSHI') and first is None else 'available',
              'compatibility': copy.deepcopy(COMPATIBILITY), 'catalog': copy.deepcopy(list(CATALOG.values())),
              'indicator': copy.deepcopy(CATALOG[indicator]),
              'rules': {'nativeTradingSignals': CATALOG[indicator]['nativeTradingSignals'],
                        'primaryPriority': ['TOPSIG', 'BOTSIG', 'PUTSIG', 'CALLSIG'] if indicator.startswith('QUSHI') else [],
                        'signalTiming': 'completed-bar-close / no-pivot-backfill',
                        'cooldownBasis': 'previous-raw-candidates-including-suppressed' if indicator.startswith('QUSHI') else None,
                        'mbPivotRightConfirmationBars': 3 if indicator.startswith('QUSHI') else None,
                        'dailyAverage': '20-bar-HLC3-volume-weighted-mean',
                        'strategyParametersOptimized': False, 'allowedPerformance': indicator.startswith('QUSHI')},
              'data': {'source': str(metadata.get('source', 'injected-authorized-daily-loader')),
                       'adjustment': str(metadata.get('adjustment', 'unspecified')),
                       'timezone': 'America/New_York', 'collectedAt': collected_at,
                       'vintage': 'current-snapshot / not-point-in-time-certified',
                       'sha256': hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()},
              'sample': {'bars': len(rows), 'start': rows[0]['date'] if rows else None,
                         'end': rows[-1]['date'] if rows else None, 'futureBarsExcluded': len(all_rows) - len(rows),
                         'evaluationStart': rows[first]['date'] if first is not None else None},
              'dataQuality': quality, 'dates': [r['date'] for r in rows],
              'price': [r['close'] for r in rows], 'series': result['series'], 'events': result['events'],
              'backtest': None, 'splits': {}, 'warnings': WARNINGS.copy()}
    if indicator.startswith('QUSHI') and not quality['historicalBottomReady']:
        report['warnings'].append('历史大底1000根及其后续滚动/冷却依赖尚未全部暖机；不能把未出现解读为完整历史验证。')
    if quality['missingVolumeBars'] or quality['zeroVolumeBars']:
        report['warnings'].append('缺量传播null；零量及前20根含零量会使DATAOK无效。')
    if first is not None:
        kwargs = {'version': indicator, 'initial': params['initial'], 'fee_bps': params['fee_bps'], 'slippage_bps': params['slippage_bps']}
        report['backtest'] = run_backtest(rows, result['events'], start=first, **kwargs)
        if len(rows) - first < 3 and validation_start is None:
            ranges = {}
            report['warnings'].append('有效评价区间不足3根，不生成训练/验证/留出切分；全区间计价不代表样本充分。')
        else:
            ranges = split_ranges(rows, first, validation_start, holdout_start)
        for name, (start, end) in ranges.items():
            split = run_backtest(rows, result['events'], start=start, end=end, **kwargs)
            split['boundaryPolicy'] = 'start-flat; signals-before-start-excluded; open-end-marked-not-counted-as-closed; shared-earlier-history-warmup'
            report['splits'][name] = split
    elif validation_start or holdout_start:
        raise ValueError('样本尚未暖机，不能指定绩效切分。')
    report['splitPolicy'] = '默认有效区间按时间60/20/20；各段独立空仓，训练末跨界持仓仅计未实现盈亏、不进入已平仓计数；参数未优化。'
    # 最终序列化门禁防止意外NaN/Infinity进入HTTP或CLI。
    json.dumps(report, allow_nan=False)
    return report
