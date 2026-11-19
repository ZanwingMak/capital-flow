"""多方法研究的受限查询、来源审计、独立回测及逐笔归档读取。"""
import gzip
import hashlib
import json
import re
from datetime import datetime, timedelta

import alpaca_data
from indicator_backtest import costs, run_backtest, split_ranges
from indicator_engine import iso_date, validate_bars
from market_methods import METHODS, TRADE_METHODS, VERSION, calculate


def parse_request(query):
    """限定US日线、标的、截止日及成本，不接受任意公式或机器路径。"""
    if set(query)-{'symbol','asOf','market','timeframe','initial','feeBps','slippageBps'}:
        raise ValueError('未知多方法研究参数。')
    clean = {}
    for key, value in query.items():
        if isinstance(value,(list,tuple)):
            if len(value)!=1:
                raise ValueError('参数不能重复。')
            value = value[0]
        if not isinstance(value,str) or not value.strip():
            raise ValueError('参数不能为空。')
        clean[key] = value.strip()
    symbol = clean.get('symbol','').upper()
    if not re.fullmatch(r'[A-Z][A-Z0-9]{0,9}(?:[.-][A-Z0-9]{1,4})?',symbol):
        raise ValueError('请输入有效美股/ETF代码。')
    if clean.get('market','US')!='US' or clean.get('timeframe','1d')!='1d':
        raise ValueError('多方法研究当前只支持US已完成日线。')
    as_of = iso_date(clean.get('asOf'))
    try:
        initial, fee, slip = [float(clean.get(k,v)) for k,v in [('initial',10000),('feeBps',5),('slippageBps',5)]]
    except (ValueError,TypeError) as error:
        raise ValueError('资金与成本必须为有效数值。') from error
    costs(initial,fee,slip)
    return {'symbol':symbol,'as_of':as_of,'market':'US','initial':initial,'fee_bps':fee,'slippage_bps':slip}


def orderflow_sample(trades, quotes, start, close):
    """按同日有效报价估算20分钟主动量Delta；未知、特殊成交和竞价不计入CVD。"""
    if close-start != timedelta(minutes=20):
        raise ValueError('订单流归档必须是完整20分钟窗口。')
    begin, end = int(start.timestamp())*10**9, int(close.timestamp())*10**9
    tape = []
    for trade in trades:
        stamp = alpaca_data.timestamp_ns(trade['t'])
        price, size = alpaca_data.number(trade.get('p')), alpaca_data.number(trade.get('s'))
        if price is None or size is None or price<=0 or size<=0:
            continue
        if begin<=stamp<end:
            tape.append((stamp,price,size, bool(set(trade.get('c',[])) & alpaca_data.EXCLUDED) or '6' in trade.get('c',[])))
    tape.sort(key=lambda x:x[0])
    valid_quotes = sorted(quotes,key=lambda q:alpaca_data.timestamp_ns(q['t']))
    result = [{'minute':i+1,'buyVolume':0.,'sellVolume':0.,'unknownVolume':0.,'excludedVolume':0.,'delta':None,'cvd':None} for i in range(20)]
    pointer, latest, running = 0, None, 0.
    for stamp,price,size,excluded in tape:
        # 同时间戳报价先后顺序不可知，只接受严格早于成交的报价。
        while pointer<len(valid_quotes) and alpaca_data.timestamp_ns(valid_quotes[pointer]['t'])<stamp:
            q = valid_quotes[pointer]
            bid, ask = alpaca_data.number(q.get('bp')), alpaca_data.number(q.get('ap'))
            latest = (alpaca_data.timestamp_ns(q['t']),bid,ask) if bid and ask and 0<bid<ask and (alpaca_data.number(q.get('bs')) or 0)>0 and (alpaca_data.number(q.get('as')) or 0)>0 else None
            pointer += 1
        bucket = result[min(19,(stamp-begin)//(60*10**9))]
        side = 'unknownVolume'
        if excluded:
            side = 'excludedVolume'
        elif latest and 0<stamp-latest[0]<=5*10**9:
            side = 'buyVolume' if price>=latest[2] else 'sellVolume' if price<=latest[1] else 'unknownVolume'
        bucket[side] += size
    sums = {key:sum(row[key] for row in result) for key in ('buyVolume','sellVolume','unknownVolume','excludedVolume')}
    classified = sums['buyVolume']+sums['sellVolume']
    denominator = classified+sums['unknownVolume']
    for row in result:
        if row['buyVolume']+row['sellVolume']>0:
            row['delta'] = row['buyVolume']-row['sellVolume']
            running += row['delta']
            row['cvd'] = running
    coverage = classified/denominator if denominator>0 else None
    return {'status':'available' if classified>0 else 'unavailable','source':'Alpaca SIP trades + quotes / archived',
            'start':start.isoformat(),'end':close.isoformat(),'unit':'shares','fullDay':False,
            'classifiedRatio':coverage, 'buyVolume':sums['buyVolume'],'sellVolume':sums['sellVolume'],
            'netVolume':sums['buyVolume']-sums['sellVolume'] if classified>0 else None,
            'unknownVolume':sums['unknownVolume'], 'excludedVolume':sums['excludedVolume'], 'sampleTrades':len(tape),
            'quality':'coverage-gate-passed' if coverage is not None and coverage>=.8 else 'insufficient-classification',
            'directionReliable':bool(coverage is not None and coverage>=.8 and abs(sums['buyVolume']-sums['sellVolume'])>sums['unknownVolume']),
            'directionIdentified':False,'rows':result,
            'reason':'报价匹配估算；仅该20分钟，CVD不包含未知与排除成交；80%是覆盖门槛，不是准确率。'}


def archived_orderflow(root, symbol, as_of):
    """仅读取本机完整SIP归档，路径由已校验标的和日期生成，不自动下载或换日。"""
    if not re.fullmatch(r'[A-Z][A-Z0-9]{0,9}(?:[.-][A-Z0-9]{1,4})?',symbol):
        raise ValueError('逐笔标的无效。')
    iso_date(as_of)
    path = root/'alpaca'/symbol/(as_of+'-v1.json.gz')
    if not path.is_file():
        return {'status':'unavailable','reason':'该日尚无完整SIP尾盘20分钟逐笔与报价归档。先在“尾盘逐笔研究”采集同日数据，再刷新。','rows':[]}
    try:
        with gzip.open(path,'rt',encoding='utf-8') as file:
            text = file.read(64*1024*1024+1)
        if len(text)>64*1024*1024:
            raise ValueError('归档过大，未使用截断记录。')
        payload = json.loads(text)
        start, close = datetime.fromisoformat(payload['start']), datetime.fromisoformat(payload['close'])
        if payload.get('source')!='alpaca-sip' or start.tzinfo is None or close.tzinfo is None or start.date().isoformat()!=as_of or close.date().isoformat()!=as_of:
            raise ValueError('逐笔日期或来源不匹配。')
        return orderflow_sample(payload['trades'],payload['quotes'],start,close)
    except (OSError,ValueError,KeyError,TypeError,EOFError):
        return {'status':'unavailable','reason':'该日逐笔归档不完整或格式无效，未补零或用其他日期替代。','rows':[]}


def get_report(symbol, as_of, market, loader, initial=10000, fee_bps=5, slippage_bps=5, flow_loader=None):
    """一次授权日线读取后分别重放方法；各方法独立空仓、按时间切分并披露数据版本。"""
    params = parse_request({'symbol':symbol,'asOf':as_of,'market':market,'initial':str(initial),'feeBps':str(fee_bps),'slippageBps':str(slippage_bps)})
    symbol, as_of, market = params['symbol'],params['as_of'],params['market']
    initial, fee_bps, slippage_bps = params['initial'],params['fee_bps'],params['slippage_bps']
    payload = loader(symbol,as_of,market)
    if not isinstance(payload,dict) or payload.get('symbol')!=symbol or payload.get('market')!=market or payload.get('timezone')!='America/New_York':
        raise ValueError('授权日线元数据不匹配。')
    all_rows = validate_bars(payload.get('rows',[]))
    rows = [row for row in all_rows if row['date']<=as_of]
    expected = iso_date(payload.get('completedAsOf',as_of))
    if expected>as_of:
        raise ValueError('完成日期不能晚于请求截止日。')
    if any(row['date']>expected for row in rows):
        raise ValueError('日线包含未经完成日历核验的记录。')
    stale = bool(rows and rows[-1]['date']<expected)
    computed = calculate(rows)
    reports = {}
    for method, spec in METHODS.items():
        selected = [e for e in computed['events'] if e['method']==method]
        report = {**spec,'id':method,'events':selected,'latest':selected[-1] if selected else None,
                  'status':'stale' if stale else 'available' if len(rows)>60 else 'warming-up','backtest':None,'splits':{}}
        if method in TRADE_METHODS and len(rows)>=65:
            entry = [method.replace('MEAN_REVERSION','MEAN')+'_LONG']
            exit_names = [method.replace('MEAN_REVERSION','MEAN')+'_EXIT']
            if method=='MEAN_REVERSION': exit_names.append('MEAN_TARGET_EXIT')
            strategy = {'entry':entry,'exit':exit_names,'maxHoldBars':20}
            # 四个方法同一执行约定；不挑表现最好者、不修改固定阈值。
            kwargs = {'version':method,'initial':initial,'fee_bps':fee_bps,'slippage_bps':slippage_bps,'strategy':strategy}
            report['backtest'] = run_backtest(rows,selected,start=60,**kwargs)
            for name,(start,end) in split_ranges(rows,60).items():
                report['splits'][name] = run_backtest(rows,selected,start,end,**kwargs)
            report['backtest']['rules']['note'] = '本项目固定量化子集；收盘确认次开盘执行，最多持有20根，无杠杆、不做空；价位只作参考，未模拟止损止盈成交。'
        if method=='ELLIOTT': report['wave'] = computed['wave']
        if method=='ORDERFLOW':
            effective = rows[-1]['date'] if rows else None
            report['orderFlow'] = flow_loader(symbol,effective) if effective and flow_loader and not stale else {'status':'unavailable','reason':'没有与应完成日线一致的同日逐笔归档；没有切换成旧日数据。','rows':[]}
            report['status'] = report['orderFlow']['status']
        reports[method] = report
    f = computed['series']
    last = {key: values[-1] if values else None for key,values in f.items()}
    regimes = 'unknown' if len(rows)<60 else 'bullish' if rows[-1]['close']>last['MA20']>last['MA50'] else 'bearish' if rows[-1]['close']<last['MA20']<last['MA50'] else 'range-or-transition'
    result = {'source':'flowdesk-methods','schemaVersion':1,'engineVersion':VERSION,'symbol':symbol,'market':market,
        'asOf':as_of,'expectedCompletedAsOf':expected,'effectiveAsOf':rows[-1]['date'] if rows else None,'timeframe':'1d','currency':'USD',
        'sample':{'bars':len(rows),'start':rows[0]['date'] if rows else None,'end':rows[-1]['date'] if rows else None,'futureBarsExcluded':len(all_rows)-len(rows)},
        'data':{key:payload.get(key) for key in ('source','adjustment','collectedAt','timezone')},
        'sha256':hashlib.sha256(json.dumps(rows,sort_keys=True,allow_nan=False).encode()).hexdigest(),
        'quality':{'stale':stale,'missingVolumeBars':sum(r['volume'] is None for r in rows),'zeroVolumeBars':sum(r['volume']==0 for r in rows)},
        'context':{'regime':regimes,'latest':last,'signalTiming':'completed-close / next-open','pivotRightBars':2},
        'dates':[r['date'] for r in rows],'price':[r['close'] for r in rows],'series':f,'methods':reports,
        'activeGaps':computed['activeGaps'],'pivots':computed['pivots'],
        'warnings':['规则为本项目可检验子集，不是任何流派的完整复现或经过验证的交易优势。',
            'ICT、PA与威科夫共享价格结构证据，不是三份独立的胜率确认。',
            '波浪只显示几何候选；订单流只在同日SIP尾盘归档存在时显示，缺失不补零。',
            '20根持有与成本为固定研究约定；股票多头回测，不代表PUT期权或做空收益。',
            '当前复权快照不等于严格点时数据；有幸存者/选择偏差，留出段不代表真正未见的未来。',
            '统计不含原价位止损/止盈执行，胜率只包含已平仓；没有交易时胜率未知。']}
    json.dumps(result,allow_nan=False)
    return result
