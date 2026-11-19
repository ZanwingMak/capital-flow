"""六种市场方法的固定规则子集；纯量价计算、收盘确认、不回填历史事件。"""
from statistics import fmean, pstdev

from indicator_engine import validate_bars
from intelligence import rsi_series

VERSION = 'flowdesk-methods-2026-11-18.1'
METHODS = {
    'ICT': {'name': 'ICT · 扫价 / 结构 / FVG', 'source': 'https://www.youtube.com/innercircletrader',
        'rules': '左右各2根确认摆点；穿越摆点后收回记扫价候选；10根内出现结构突破与三根K线FVG，形成后20根内回测守住才确认。位移实体≥0.6ATR，缺口≥0.05ATR。',
        'limit': '日线结构子集，不包含日内Kill Zone；FVG只是价格结构，不证明机构订单、止损分布或必然回补。'},
    'PA': {'name': 'PA · 突破与回测', 'source': 'https://www.brookstradingcourse.com/how-to-trade-price-action-manual/',
        'rules': '收盘突破此前20根高低区间；随后1至5根回测边界并顺向收盘确认；吞没和长影线仅作观察。',
        'limit': '不是完整Brooks体系；单根K线形态与突破本身均不直接入场。'},
    'WYCKOFF': {'name': '威科夫 · Spring / Upthrust', 'source': 'https://www.wyckoffanalytics.com/wyckoff-method/',
        'rules': '此前20根形成宽2至8ATR且上下至少各2次接触的箱体；Spring/Upthrust收回箱体后，5根内缩量测试，10根内越过箱体中点确认SOS/SOW。',
        'limit': '只识别局部量价序列，不宣称已完成A至E阶段、吸筹派发或识别庄家。'},
    'MEAN_REVERSION': {'name': '均值回归 · 弱趋势过滤', 'source': 'https://www.bollingerbands.com/bollinger-band-rules',
        'rules': 'BOLL20±2倍总体标准差；ADX14<20且MA50五根斜率绝对值<0.5ATR；前根越轨、RSI越过30/70极值后，当根收回轨内并转向才确认。',
        'limit': '触轨和超卖不等于见底；强趋势时禁用回归入场，不假设价格服从正态分布。'},
    'ELLIOTT': {'name': '艾略特 · 推动浪候选', 'source': 'https://www.elliottwave.com/waveopedia/impulse/',
        'rules': '用左右2根确认的摆点构造交替路径；检查2浪不越起点、3浪越过1浪终点、4浪不重叠1浪、3浪不是1/3/5中最短。列出浪长与回撤比例。',
        'limit': '只是普通推动浪几何候选，未验证子浪5-3-5-3-5，不覆盖对角线、复杂调整和多重计数；不据此产生交易绩效。'},
    'ORDERFLOW': {'name': '订单流 · SIP尾盘逐笔', 'source': 'https://docs.alpaca.markets/docs/historical-stock-data-1',
        'rules': '只读取已完整归档的尾盘20分钟逐笔与同期报价；按不晚于成交、最多5秒前的有效买卖报价估算主动方向，未知与特殊成交单列。',
        'limit': 'CVD只覆盖该20分钟样本，并非全日；报价匹配仍是估算。没有完整盘口时不识别撤单、冰山、挂单墙或机构账户。'},
}
TRADE_METHODS = ('ICT', 'PA', 'WYCKOFF', 'MEAN_REVERSION')


def average(values, count):
    """完整且有效窗口才输出简单均值，不用零填补缺失。"""
    return [fmean(values[i-count+1:i+1]) if i+1 >= count and all(v is not None for v in values[i-count+1:i+1]) else None
            for i in range(len(values))]


def wilder(values, count=14):
    """以首个完整窗口播种Wilder平滑；缺值后重新暖机。"""
    result, seed, last = [], [], None
    for value in values:
        if value is None:
            seed, last = [], None
        elif last is None:
            seed.append(value)
            if len(seed) == count:
                last = fmean(seed)
        else:
            last = (last * (count-1) + value) / count
        result.append(last)
    return result


def features(rows):
    """计算ATR、ADX、RSI、BOLL和量比；所有窗口只使用截至当根的记录。"""
    close, volume = [r['close'] for r in rows], [r['volume'] for r in rows]
    tr, plus, minus = [], [], []
    for i, row in enumerate(rows):
        previous = rows[i-1] if i else row
        tr.append(max(row['high']-row['low'], abs(row['high']-previous['close']), abs(row['low']-previous['close'])))
        up, down = row['high']-previous['high'], previous['low']-row['low']
        plus.append(max(0, up) if up > down else 0)
        minus.append(max(0, down) if down > up else 0)
    atr, dm_plus, dm_minus = wilder(tr), wilder(plus), wilder(minus)
    dx = [100*abs(p-m)/(p+m) if p is not None and m is not None and p+m>0 else 0 if p==m==0 else None
          for p, m in zip(dm_plus, dm_minus)]
    ma20, ma50, vma = average(close, 20), average(close, 50), average(volume, 20)
    sd = [pstdev(close[i-19:i+1]) if i>=19 else None for i in range(len(rows))]
    return {'MA20': ma20, 'MA50': ma50, 'ATR14': atr, 'ADX14': wilder(dx), 'RSI14': rsi_series(close),
            'BOLL_UPPER': [m+2*s if m is not None else None for m, s in zip(ma20, sd)],
            'BOLL_LOWER': [m-2*s if m is not None else None for m, s in zip(ma20, sd)],
            'RVOL': [volume[i]/vma[i-1] if i and volume[i] is not None and volume[i]>0 and vma[i-1] and vma[i-1]>0 else None for i in range(len(rows))]}


def wave_candidate(turns):
    """核对最新六个交替摆点的普通推动浪几何约束，不验证未知的子浪结构。"""
    if len(turns) < 6:
        return None
    points = turns[-6:]
    if any(b['index']<=a['index'] for a,b in zip(points,points[1:])):
        return None
    sign = 1 if points[0]['side']=='low' else -1
    expected = ['low','high','low','high','low','high'] if sign==1 else ['high','low','high','low','high','low']
    if [p['side'] for p in points] != expected:
        return None
    p = [sign*x['price'] for x in points]
    legs = [p[1]-p[0], p[3]-p[2], p[5]-p[4]]
    checks = {'wave2InsideOrigin': p[0]<p[2]<p[1], 'wave3BeyondWave1': p[3]>p[1],
              'wave4NoOverlap': p[1]<p[4]<p[3], 'wave3NotShortest': legs[1]>=min(legs[0],legs[2]),
              'positiveMotiveLegs': min(legs)>0}
    if not all(checks.values()):
        return None
    return {'direction': 'bullish' if sign==1 else 'bearish', 'points': [dict(x) for x in points], 'checks': checks,
            'waveLengths': legs, 'wave2Retracement': (p[1]-p[2])/legs[0],
            'wave4Retracement': (p[3]-p[4])/legs[1], 'truncatedFifth': p[5]<=p[3],
            'subdivisionVerified': False, 'status': 'geometric-candidate'}


def calculate(rows):
    """因果重放四种固定交易子集和波浪观察；每个事件记录首次可知的确认根。"""
    rows = validate_bars(rows)
    f = features(rows)
    events, pivots, turns, gaps = [], [], [], []
    high_pivot = low_pivot = None
    sweeps, shifts, breakouts, tests = {}, {}, {}, {}
    last_signal = {}
    last_wave = None

    def emit(method, i, code, label, direction, layer='observation', **evidence):
        """冻结当根可知证据，操作确认按同方法同方向冷却5根，绝不改写旧事件。"""
        if layer=='primary':
            key = (method, direction)
            if i-last_signal.get(key, -100)>5:
                last_signal[key] = i
            else:
                return
        events.append({'method': method, 'index': i, 'confirmIndex': i, 'date': rows[i]['date'],
                       'name': code, 'label': label, 'direction': direction, 'layer': layer, 'evidence': evidence})

    for i, row in enumerate(rows):
        a = f['ATR14'][i]
        if i<60 or not a or a<=0:
            continue
        c, o, h, l = (row[k] for k in ('close','open','high','low'))
        previous = rows[i-1]
        rv = f['RVOL'][i]
        volume_ok = rv is not None and rv>=1
        pos = (c-l)/(h-l) if h>l else .5
        body = abs(c-o)
        ma = f['MA20'][i]
        # 确认在i发生；index仍指向极值根，knownIndex才是首次可用根。
        j = i-2
        for side, key in (('high','high'),('low','low')):
            value = rows[j][key]
            window = [r[key] for r in rows[j-2:j+3]]
            if value != (max(window) if side=='high' else min(window)) or window.count(value)!=1:
                continue
            point = {'index': j, 'date': rows[j]['date'], 'knownIndex': i, 'knownDate': row['date'], 'side': side, 'price': value}
            pivots.append(point)
            if side=='high': high_pivot = point
            else: low_pivot = point
            if turns and turns[-1]['side']==side:
                if (value-turns[-1]['price'])*(1 if side=='high' else -1)>0:
                    turns[-1] = point
            elif not turns or abs(value-turns[-1]['price'])>=a*.8:
                turns.append(point)
                turns = turns[-12:]
        wave = wave_candidate(turns)
        if wave and wave['points'][-1]['knownIndex']==i:
            last_wave = wave
            emit('ELLIOTT', i, 'WAVE5_CANDIDATE', '五浪几何候选', 0, wave=wave)
        for direction, pivot in ((1,low_pivot),(-1,high_pivot)):
            if not pivot or pivot['knownIndex']>=i:
                continue
            level = pivot['price']
            swept = l<level-a*.05 and c>level if direction==1 else h>level+a*.05 and c<level
            if swept:
                sweeps[direction] = {'index': i, 'level': level, 'extreme': l if direction==1 else h}
                emit('ICT', i, 'LIQUIDITY_SWEEP', '下方扫价收回' if direction==1 else '上方扫价收回', direction,
                     level=level, pivotKnownDate=pivot['knownDate'])
        for direction, pivot in ((1,high_pivot),(-1,low_pivot)):
            sweep = sweeps.get(direction)
            crossed = pivot and pivot['knownIndex']<i and (c>pivot['price']>=previous['close'] if direction==1 else c<pivot['price']<=previous['close'])
            if crossed and sweep and 0<i-sweep['index']<=10 and body>=a*.6 and (c-o)*direction>0:
                shifts[direction] = {'index': i, 'sweepIndex': sweep['index']}
                emit('ICT', i, 'STRUCTURE_SHIFT', '扫价后结构转换', direction, brokenLevel=pivot['price'], sweepDate=rows[sweep['index']]['date'])
        middle = rows[i-1]
        for direction in (1,-1):
            lower, upper = (rows[i-2]['high'],l) if direction==1 else (h,rows[i-2]['low'])
            if upper-lower>a*.05 and (middle['close']-middle['open'])*direction>=f['ATR14'][i-1]*.6:
                gap = {'index': i, 'lower': lower, 'upper': upper, 'direction': direction}
                gaps.append(gap)
                emit('ICT', i, 'FVG', '看涨FVG候选' if direction==1 else '看跌FVG候选', direction, lower=lower, upper=upper)
        for gap in gaps[:]:
            direction = gap['direction']
            invalid = c<gap['lower'] if direction==1 else c>gap['upper']
            if i-gap['index']>20 or invalid:
                gaps.remove(gap)
                continue
            shift = shifts.get(direction)
            touched = l<=gap['upper'] and h>=gap['lower']
            held = c>gap['upper'] and c>o and pos>=.6 if direction==1 else c<gap['lower'] and c<o and pos<=.4
            if i>gap['index'] and touched and held and volume_ok and shift and gap['index']-10<=shift['index']<=gap['index']+2 and i-shift['index']<=20:
                stop = min(l,gap['lower'])-a*.2 if direction==1 else max(h,gap['upper'])+a*.2
                emit('ICT', i, 'ICT_LONG' if direction==1 else 'ICT_EXIT', 'FVG回测确认', direction, 'primary',
                     lower=gap['lower'], upper=gap['upper'], formedDate=rows[gap['index']]['date'], stopReference=stop)
                gaps.remove(gap)
        gaps = gaps[-40:]
        ceiling = max(r['high'] for r in rows[i-20:i])
        floor = min(r['low'] for r in rows[i-20:i])
        for direction in (1,-1):
            pending = breakouts.get(direction)
            if pending and 0<i-pending['index']<=5:
                level = pending['level']
                held = l<=level+a*.3 and c>level and c>o and pos>=.6 if direction==1 else h>=level-a*.3 and c<level and c<o and pos<=.4
                if held and volume_ok and body>=a*.25:
                    emit('PA', i, 'PA_LONG' if direction==1 else 'PA_EXIT', '突破回测与跟随确认', direction, 'primary',
                         boundary=level, breakoutDate=rows[pending['index']]['date'], stopReference=(l-a*.2 if direction==1 else h+a*.2))
                    breakouts.pop(direction)
                elif (c-level)*direction < -a*.5:
                    emit('PA', i, 'FAILED_BREAKOUT', '突破失效', -direction, boundary=level)
                    breakouts.pop(direction)
            boundary = ceiling if direction==1 else floor
            if (c-boundary)*direction>0 and (previous['close']-boundary)*direction<=0 and body>=a*.5:
                breakouts[direction] = {'index': i, 'level': boundary}
                emit('PA', i, 'BREAKOUT', '区间向上突破候选' if direction==1 else '区间向下突破候选', direction, boundary=boundary)
        if c>o and previous['close']<previous['open'] and o<=previous['close'] and c>=previous['open']:
            emit('PA', i, 'ENGULFING', '看涨吞没观察', 1)
        elif c<o and previous['close']>previous['open'] and o>=previous['close'] and c<=previous['open']:
            emit('PA', i, 'ENGULFING', '看跌吞没观察', -1)
        if h-max(c,o)>max(body*2,a*.5) and pos<.35 and h>=ceiling-a*.3:
            emit('PA', i, 'REJECTION', '阻力长上影观察', -1, boundary=ceiling)
        if min(c,o)-l>max(body*2,a*.5) and pos>.65 and l<=floor+a*.3:
            emit('PA', i, 'REJECTION', '支撑长下影观察', 1, boundary=floor)
        in_range = (2*a<=ceiling-floor<=8*a and abs(ma-f['MA20'][i-5])<a*.5
                    and sum(r['low']<=floor+a*.4 for r in rows[i-20:i])>=2
                    and sum(r['high']>=ceiling-a*.4 for r in rows[i-20:i])>=2)
        for direction in (1,-1):
            pending = tests.get(direction)
            if pending:
                invalid = l<pending['extreme']-a*.1 if direction==1 else h>pending['extreme']+a*.1
                if invalid or i-pending['index']>10:
                    tests.pop(direction)
                else:
                    quiet = row['volume'] is not None and row['volume']>0 and row['volume']<pending['volume']
                    tested = l<=pending['boundary']+a*.5 if direction==1 else h>=pending['boundary']-a*.5
                    if i>pending['index'] and i-pending['index']<=5 and quiet and tested and not pending.get('testIndex'):
                        pending['testIndex'] = i
                        emit('WYCKOFF', i, 'LOW_VOLUME_TEST', '缩量测试候选', direction, boundary=pending['boundary'])
                    strength = c>pending['mid'] and c>previous['high'] and c>o if direction==1 else c<pending['mid'] and c<previous['low'] and c<o
                    if pending.get('testIndex') is not None and i>pending['testIndex'] and strength and volume_ok and body>=a*.5:
                        emit('WYCKOFF', i, 'WYCKOFF_LONG' if direction==1 else 'WYCKOFF_EXIT', 'Spring后SOS确认' if direction==1 else 'Upthrust后SOW确认', direction, 'primary',
                             boundary=pending['boundary'], setupDate=rows[pending['index']]['date'], testDate=rows[pending['testIndex']]['date'],
                             stopReference=pending['extreme']-direction*a*.2)
                        tests.pop(direction)
            swept = l<floor and c>floor and pos>=.65 if direction==1 else h>ceiling and c<ceiling and pos<=.35
            if in_range and swept and row['volume'] is not None and row['volume']>0:
                boundary = floor if direction==1 else ceiling
                tests[direction] = {'index': i, 'extreme': l if direction==1 else h, 'boundary': boundary,
                                    'mid': (floor+ceiling)/2, 'volume': row['volume']}
                emit('WYCKOFF', i, 'SPRING' if direction==1 else 'UPTHRUST', 'Spring候选' if direction==1 else 'Upthrust候选', direction, boundary=boundary)
        adx = f['ADX14'][i]
        weak_trend = adx is not None and adx<20 and abs(f['MA50'][i]-f['MA50'][i-5])<a*.5
        if weak_trend and f['RSI14'][i] is not None and f['RSI14'][i-1] is not None:
            for direction in (1,-1):
                reverted = (previous['close']<f['BOLL_LOWER'][i-1] and c>f['BOLL_LOWER'][i] and f['RSI14'][i-1]<30 and f['RSI14'][i]>30 and c>o and l>=previous['low']) if direction==1 else (
                    previous['close']>f['BOLL_UPPER'][i-1] and c<f['BOLL_UPPER'][i] and f['RSI14'][i-1]>70 and f['RSI14'][i]<70 and c<o and h<=previous['high'])
                if reverted:
                    stop = min(r['low'] for r in rows[i-4:i+1])-a*.25 if direction==1 else max(r['high'] for r in rows[i-4:i+1])+a*.25
                    emit('MEAN_REVERSION', i, 'MEAN_LONG' if direction==1 else 'MEAN_EXIT', '弱趋势收回布林轨确认', direction, 'primary',
                         targetReference=ma, stopReference=stop, adx=adx, rsi=f['RSI14'][i])
        # 均值回归只在持仓方向回到中轨时退出，不用未来均值或高低价假设成交。
        if c>=ma and previous['close']<f['MA20'][i-1]:
            emit('MEAN_REVERSION', i, 'MEAN_TARGET_EXIT', '收盘回到均值', -1, 'exit-only', targetReference=ma)
    wave = {**last_wave, 'confirmedDate': last_wave['points'][-1]['knownDate'],
            'ageBars':len(rows)-1-last_wave['points'][-1]['knownIndex']} if last_wave else None
    return {'series': f, 'events': events, 'pivots': pivots, 'wave': wave,
            'activeGaps': [dict(g, formedDate=rows[g['index']]['date']) for g in gaps]}
