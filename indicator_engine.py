"""有界Mai表达式解释器；只对固定审阅公式求值，不运行原Python源码。"""
import math
import re
from datetime import date
from functools import lru_cache

from indicator_specs import CATALOG, FORMULAS

MAX_BARS = 5000
COMPATIBILITY = {
    'id': 'flowdesk-mai-daily-1', 'futuCertified': False,
    'notice': '源公式兼容性尚未通过富途逐根输出认证。',
    'contract': ['仅US已完成日线；DATE每日唯一，AVGX为20根HLC3成交量加权均价，不承诺日内等价。',
                 'MA/LLV/HHV/COUNT/SUM/STDP需要完整已知窗口；STDP总体标准差ddof=0。',
                 'EMA首个有效值播种；内部缺值输出null，随后重新播种。',
                 'CROSS为当根严格大于且前根小于等于；相等极值保留。',
                 'BARSLAST无已知事件为null；动态REF越界/负值为null；禁止负常量REF。',
                 '三值AND/OR保留可确定的真假；IF只选择已知条件的分支；未知不补零。',
                 'BARSCOUNT从首有效值起计根数，缺值当根为null；SUM的0窗口为全部已有历史。',
                 '原公式MAX(分母,0.000001)保留；未保护的除零输出null；ATR为TR的MA14。'],
}
EVENT_NAMES = ('TOPSIG', 'BOTSIG', 'PUTSIG', 'CALLSIG', 'WARNSIG', 'VUPSIG', 'VDNSIG',
               'DHIST', 'DSUPER', 'DBIG', 'DMID', 'DSMALL', 'DISLBUY', 'DISLSELL',
               'DENGBUY', 'DENGSELL', 'DSTARBUY', 'DSTARSELL', 'DBRKBUY', 'DBRKSELL',
               'DMBBUY', 'DMBSELL', 'DGOLD', 'DDEAD', 'DTXBUY', 'DTXSELL')
PRIMARY = EVENT_NAMES[:4]
FUNCTIONS = {'ABS': 1, 'NOT': 1, 'BARSCOUNT': 1, 'BARSLAST': 1,
             'MAX': 2, 'MIN': 2, 'IF': 3, 'REF': 2, 'MA': 2, 'EMA': 2,
             'LLV': 2, 'HHV': 2, 'COUNT': 2, 'SUM': 2, 'STDP': 2, 'CROSS': 2}
TOKEN = re.compile(r'\s*(?:(\d+(?:\.\d*)?|\.\d+)|([A-Z][A-Z0-9_]*)|(:=|<=|>=|<>|!=|[+*/()=<>;,\-]))', re.I)
PRECEDENCE = {'OR': 1, 'AND': 2, '=': 3, '<>': 3, '!=': 3, '<': 3, '>': 3,
              '<=': 3, '>=': 3, '+': 4, '-': 4, '*': 5, '/': 5}


class FormulaError(ValueError):
    """公式语法、白名单或资源界限错误。"""


def finite(value):
    """只接受有限数值，所有未知统一表示为None。"""
    return value if isinstance(value, (int, float)) and math.isfinite(value) else None


def iso_date(value):
    """校验不含时间的完整ISO交易日期。"""
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('日期须为YYYY-MM-DD。')
    date.fromisoformat(value)
    return value


def validate_bars(rows):
    """验证有界、升序、唯一日线；缺量允许传播未知，缺OHLC拒绝。"""
    if not isinstance(rows, (list, tuple)) or len(rows) > MAX_BARS:
        raise ValueError('日线必须为数组且最多5000根。')
    cleaned, previous = [], ''
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('每根日线必须为对象。')
        day = iso_date(row.get('date'))
        if day <= previous:
            raise ValueError('日线日期必须严格升序且不重复。')
        prices = {key: finite(row.get(key)) for key in ('open', 'high', 'low', 'close')}
        if any(v is None or isinstance(v, bool) or v <= 0 or v > 1e12 for v in prices.values()):
            raise ValueError('OHLC必须为有效正数且不超过1e12。')
        if not prices['low'] <= min(prices['open'], prices['close']) <= max(prices['open'], prices['close']) <= prices['high']:
            raise ValueError('OHLC高低区间无效。')
        volume = row.get('volume')
        if volume is not None and (finite(volume) is None or isinstance(volume, bool) or not 0 <= volume <= 1e18):
            raise ValueError('成交量必须缺失或为0至1e18的有限数值。')
        cleaned.append({'date': day, **prices, 'volume': volume})
        previous = day
    return cleaned


class Parser:
    """不使用Python AST/eval的有限Pratt语法分析器。"""

    def __init__(self, source):
        """分词并限制体积，拒绝引号、属性和数组等未批准语法。"""
        if not isinstance(source, str) or len(source) > 64000:
            raise FormulaError('公式体积超限。')
        self.tokens, self.pos, offset = [], 0, 0
        while offset < len(source):
            if not source[offset:].strip():
                break
            match = TOKEN.match(source, offset)
            if not match:
                raise FormulaError('公式包含未允许的字符。')
            self.tokens.append(next(g for g in match.groups() if g is not None).upper())
            offset = match.end()
            if len(self.tokens) > 20000:
                raise FormulaError('公式token超限。')

    def peek(self):
        """返回当前token，结束时使用空哨兵。"""
        return self.tokens[self.pos] if self.pos < len(self.tokens) else ''

    def take(self, expected=None):
        """消费一个token并校验必需的标点。"""
        token = self.peek()
        if not token or expected is not None and token != expected:
            raise FormulaError('公式语法错误。')
        self.pos += 1
        return token

    def expression(self, precedence=0, depth=0):
        """仅构造常量、变量、一元、二元和白名单函数节点。"""
        if depth > 80:
            raise FormulaError('公式嵌套超限。')
        token = self.take()
        if token in ('+', '-', 'NOT'):
            left = ('unary', token, self.expression(6, depth + 1))
        elif token == '(':
            left = self.expression(0, depth + 1)
            self.take(')')
        elif re.fullmatch(r'\d+(?:\.\d*)?|\.\d+', token):
            value = float(token)
            if not math.isfinite(value) or abs(value) > 1e18:
                raise FormulaError('常量超限。')
            left = ('number', value)
        elif re.fullmatch(r'[A-Z][A-Z0-9_]*', token):
            if self.peek() == '(':
                if token not in FUNCTIONS:
                    raise FormulaError('函数未在白名单中。')
                self.take('(')
                args = [self.expression(0, depth + 1)]
                while self.peek() == ',':
                    self.take(',')
                    args.append(self.expression(0, depth + 1))
                self.take(')')
                if len(args) != FUNCTIONS[token]:
                    raise FormulaError('函数参数数量错误。')
                if token in ('REF', 'MA', 'EMA', 'SUM', 'COUNT', 'LLV', 'HHV', 'STDP'):
                    period = args[1]
                    if period[0] == 'unary' and period[1] == '-':
                        raise FormulaError('禁止负常量偏移/窗口。')
                    if period[0] == 'number' and (not period[1].is_integer() or not 0 <= period[1] <= MAX_BARS):
                        raise FormulaError('窗口超限。')
                left = ('call', token, tuple(args))
            else:
                left = ('variable', token)
        else:
            raise FormulaError('无效表达式。')
        while self.peek() in PRECEDENCE and PRECEDENCE[self.peek()] > precedence:
            operator = self.take()
            right = self.expression(PRECEDENCE[operator], depth + 1)
            left = ('binary', operator, left, right)
        return left

    def parse(self):
        """解析有序赋值并拒绝重复命名或残留语句。"""
        assignments, seen = [], set()
        while self.peek():
            name = self.take()
            if not re.fullmatch(r'[A-Z][A-Z0-9_]*', name) or name in seen:
                raise FormulaError('重复或无效的赋值名称。')
            self.take(':=')
            expression = self.expression()
            pending, nodes = [(expression, 0)], 0
            # 迭代校验整棵AST，左结合长链也必须满足深度界限。
            while pending:
                node, depth = pending.pop()
                nodes += 1
                if depth > 80 or nodes > 10000:
                    raise FormulaError('表达式结构超限。')
                children = node[2] if node[0] == 'call' else node[2:] if node[0] in ('binary', 'unary') else ()
                pending.extend((child, depth + 1) for child in children)
            assignments.append((name, expression))
            self.take(';')
            seen.add(name)
            if len(assignments) > 400:
                raise FormulaError('赋值数量超限。')
        return tuple(assignments)


@lru_cache(maxsize=16)
def compile_formula(source):
    """缓存固定公式语法树，不加载外部路径或执行原始源码。"""
    return Parser(source).parse()


def binary(operator, a, b):
    """实现三值逻辑和安全算术；未知数不自动转换为False或零。"""
    if operator == 'AND':
        return False if a is not None and not a or b is not None and not b else None if a is None or b is None else True
    if operator == 'OR':
        return True if a is not None and a or b is not None and b else None if a is None or b is None else False
    if a is None or b is None:
        return None
    if operator == '+': return finite(a + b)
    if operator == '-': return finite(a - b)
    if operator == '*': return finite(a * b)
    if operator == '/': return finite(a / b) if b != 0 else None
    if operator == '=': return a == b
    if operator in ('<>', '!='): return a != b
    if operator == '<': return a < b
    if operator == '>': return a > b
    if operator == '<=': return a <= b
    if operator == '>=': return a >= b
    raise FormulaError('运算符未允许。')


def window_function(name, values, periods):
    """用已知窗口计算滚动值；动态SUM/COUNT允许逐根变化的历史长度。"""
    result, sums, missing = [], [0.0], [0]
    for value in values:
        sums.append(sums[-1] + (bool(value) if name == 'COUNT' else value or 0))
        missing.append(missing[-1] + (value is None))
    for i, period in enumerate(periods):
        if period is None or period != int(period) or not 0 <= period <= MAX_BARS:
            result.append(None)
            continue
        count = i + 1 if period == 0 and name == 'SUM' else int(period)
        first = i - count + 1
        if count < 1 or first < 0 or missing[i+1] != missing[first]:
            result.append(None)
            continue
        if name in ('SUM', 'MA', 'COUNT'):
            value = sums[i+1] - sums[first]
            result.append(finite(value / count if name == 'MA' else value))
        elif name in ('HHV', 'LLV'):
            result.append((max if name == 'HHV' else min)(values[first:i+1]))
        else:
            sample = values[first:i+1]
            mean = math.fsum(sample) / count
            result.append(finite(math.sqrt(math.fsum((v - mean)**2 for v in sample) / count)))
    return result


def call_function(name, args):
    """实现仅依赖当前及过去值的白名单Mai函数。"""
    values, n = args[0], len(args[0])
    if name in ('MA', 'SUM', 'COUNT', 'HHV', 'LLV', 'STDP'):
        return window_function(name, values, args[1])
    if name == 'REF':
        return [values[i-int(offset)] if offset is not None and offset == int(offset) and 0 <= offset <= min(i, MAX_BARS) else None
                for i, offset in enumerate(args[1])]
    if name == 'EMA':
        result, state = [], None
        for value, period in zip(values, args[1]):
            if value is None or period is None or period != int(period) or not 1 <= period <= MAX_BARS:
                state = None
            else:
                state = value if state is None else state + 2 / (period + 1) * (value - state)
            result.append(finite(state))
        return result
    if name in ('BARSLAST', 'BARSCOUNT'):
        result, anchor = [], None
        for i, value in enumerate(values):
            if name == 'BARSLAST':
                if value is None:
                    anchor = None
                elif value:
                    anchor = i
                result.append(i - anchor if anchor is not None else None)
            else:
                if value is not None and anchor is None:
                    anchor = i
                result.append(i - anchor + 1 if anchor is not None and value is not None else None)
        return result
    if name == 'CROSS':
        return [None] + [binary('AND', binary('>', values[i], args[1][i]), binary('<=', values[i-1], args[1][i-1]))
                         for i in range(1, n)] if n else []
    if name == 'IF':
        return [None if flag is None else a if flag else b for flag, a, b in zip(*args)]
    if name in ('ABS', 'NOT'):
        return [None if v is None else abs(v) if name == 'ABS' else not v for v in values]
    if name in ('MAX', 'MIN'):
        return [None if a is None or b is None else (max if name == 'MAX' else min)(a, b) for a, b in zip(*args)]
    raise FormulaError('函数未允许。')


def evaluate_formula(source, inputs):
    """计算固定公式全部赋值；环境数据有界，绝不使用eval/exec。"""
    lengths = {len(v) for v in inputs.values() if isinstance(v, (list, tuple))}
    if len(lengths) != 1 or next(iter(lengths)) > MAX_BARS:
        raise FormulaError('输入序列长度不一致或超限。')
    length = next(iter(lengths))
    environment = {k.upper(): [finite(x) for x in v] if isinstance(v, (list, tuple)) else [finite(v)] * length for k, v in inputs.items()}
    output, cache = {}, {}

    def compute(node):
        """逐节点解释并复用子表达式，每个节点只遍历当前输入一次。"""
        if node in cache:
            return cache[node]
        kind = node[0]
        if kind == 'number':
            result = [node[1]] * length
        elif kind == 'variable':
            if node[1] not in environment:
                raise FormulaError('公式引用未知变量：' + node[1])
            result = environment[node[1]]
        elif kind == 'unary':
            result = [None if v is None else not v if node[1] == 'NOT' else -v if node[1] == '-' else v for v in compute(node[2])]
        elif kind == 'binary':
            result = [binary(node[1], a, b) for a, b in zip(compute(node[2]), compute(node[3]))]
        else:
            result = call_function(node[1], [compute(arg) for arg in node[2]])
        cache[node] = result
        return result

    for name, expression in compile_formula(source):
        if name in environment:
            raise FormulaError('禁止覆盖输入变量。')
        output[name] = environment[name] = compute(expression)
    return output


def calculate(rows, indicator='QUSHI-CHANG', timeframe='1d'):
    """计算六个支持指标的真实数值和原始过滤后收盘确认事件。"""
    if timeframe != '1d':
        raise ValueError('首发仅支持日线，不承诺日内VWAP等价。')
    if indicator not in CATALOG or not CATALOG[indicator]['supported']:
        raise ValueError(CATALOG.get(indicator, {}).get('reason', '未知指标。'))
    rows = validate_bars(rows)
    inputs = {name: [r[key] for r in rows] for name, key in [('C', 'close'), ('CLOSE', 'close'), ('O', 'open'), ('H', 'high'), ('L', 'low'), ('V', 'volume')]}
    inputs['DATE'] = [int(r['date'].replace('-', '')) for r in rows]
    inputs.update(CATALOG[indicator]['parameters'])
    series = evaluate_formula(FORMULAS[indicator], inputs)
    events = []
    for i, row in enumerate(rows):
        for name in EVENT_NAMES:
            if name in series and series[name][i] is True:
                events.append({'name': name, 'index': i, 'date': row['date'], 'confirmIndex': i,
                               'confirmDate': row['date'], 'firstExecutableIndex': i + 1,
                               'layer': 'primary' if name in PRIMARY else 'auxiliary' if name in EVENT_NAMES[4:7] else 'observation',
                               'timing': 'completed-bar-close', 'mbPivotConfirmationBars': 3 if name.startswith('DMB') else None})
    readiness = {k: {'firstKnownIndex': next((i for i, x in enumerate(v) if x is not None), None),
                     'knownBars': sum(x is not None for x in v), 'lastKnown': bool(v) and v[-1] is not None}
                 for k, v in series.items()}
    eligible = [i for i in range(len(rows)) if series.get('DATAOK', [False] * len(rows))[i] is True and all(series[k][i] is not None for k in PRIMARY)] if indicator.startswith('QUSHI') else []
    historical_ready = bool(rows) and all(series[k][-1] is not None for k in ('LOW1000', 'DIV1000', 'HISTRAW', 'DHIST')) if indicator.startswith('QUSHI') else None
    quality = {'missingVolumeBars': sum(r['volume'] is None for r in rows), 'zeroVolumeBars': sum(r['volume'] == 0 for r in rows),
               'firstEligibleIndex': eligible[0] if eligible else None, 'eligibleBars': len(eligible),
               'historicalBottomReady': historical_ready, 'seriesReadiness': readiness,
               'calendarVerified': False, 'note': '验证顺序/OHLC/量，不自行推断交易所缺失交易日；只接受调用方提供的已完成日线。'}
    return {'indicator': indicator, 'series': series, 'events': events, 'quality': quality}
