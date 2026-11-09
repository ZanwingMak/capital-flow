"""合成数值预言、实际公式覆盖和前缀因果性测试；不依赖富途运行时。"""
import hashlib
import math
import random
import re
import unittest
from datetime import date, timedelta

from indicator_engine import FormulaError, calculate, evaluate_formula, validate_bars
from indicator_specs import CATALOG, FORMULAS


def bars(count=320):
    """生成含反转、放量、跳空的明确合成日线，供长短版本独立计算。"""
    rows = []
    for i in range(count):
        close = 100 + i * .025 + 8 * math.sin(i / 11) + 2 * math.cos(i / 3)
        opening = close - math.sin(i * 1.7) * 1.1
        rows.append(dict(date=(date(2000, 1, 1) + timedelta(days=i)).isoformat(),
                         open=opening, high=max(opening, close) + .7,
                         low=min(opening, close) - .7, close=close,
                         volume=2400 if i % 7 == 0 else 1000 + i % 13 * 20))
    return rows


class FormulaTests(unittest.TestCase):
    """用手算结果约束解释器，而非复述实现。"""

    def test_numeric_oracles(self):
        """完整MA、首有效EMA、总体标准差及交叉有独立手算预言。"""
        result = evaluate_formula('A:=MA(C,3); E:=EMA(C,3); S:=STDP(C,3); X:=CROSS(C,2);', {'C': [1, 2, 3, 2]})
        self.assertEqual(result['A'], [None, None, 2, 7 / 3])
        self.assertEqual(result['E'], [1, 1.5, 2.25, 2.125])
        self.assertAlmostEqual(result['S'][2], math.sqrt(2 / 3))
        self.assertEqual(result['X'], [None, False, True, False])

    def test_dynamic_ref_sum_and_no_prior_event(self):
        """无事件BARSLAST保持未知，动态偏移不会变成负REF。"""
        result = evaluate_formula('B:=BARSLAST(E); R:=REF(C,B); S:=SUM(C,N);',
                                  {'C': [10, 20, 30, 40], 'E': [False, True, False, False], 'N': [1, 2, 1, 3]})
        self.assertEqual(result['B'], [None, 0, 1, 2])
        self.assertEqual(result['R'], [None, 20, 20, 20])
        self.assertEqual(result['S'], [10, 30, 30, 90])
        self.assertEqual(evaluate_formula('X:=REF(C,N);', {'C': [1, 2], 'N': [-1, None]})['X'], [None, None])

    def test_unknown_not_zero_and_boolean_contract(self):
        """安全除零、缺失、IF选择分支及三值逻辑均保留未知。"""
        out = evaluate_formula('A:=C/0; B:=MA(C,2); D:=0 AND C; E:=1 OR C; F:=NOT C; G:=IF(1,4,C/0);', {'C': [None, 2, 4]})
        self.assertEqual(out['A'], [None] * 3)
        self.assertEqual(out['B'], [None, None, 3])
        self.assertEqual(out['D'], [False] * 3)
        self.assertEqual(out['E'], [True] * 3)
        self.assertEqual(out['F'], [None, False, False])
        self.assertEqual(out['G'], [4] * 3)

    def test_count_extrema_and_equality(self):
        """COUNT含当根且要求完整已知窗口；极值并列保留等号语义。"""
        out = evaluate_formula('A:=COUNT(C<>0,2); B:=HHV(C,2); D:=LLV(C,2); E:=C=B; F:=BARSCOUNT(C);', {'C': [2, 2, None, 1]})
        self.assertEqual(out['A'], [None, 2, None, None])
        self.assertEqual(out['B'], [None, 2, None, None])
        self.assertEqual(out['E'], [None, True, None, None])
        self.assertEqual(out['F'], [1, 2, None, 4])

    def test_ema_gap_reseeds(self):
        """内部缺值输出未知，下一有效值重新播种，并明确区别填零。"""
        self.assertEqual(evaluate_formula('X:=EMA(C,3);', {'C': [2, None, 8, 10]})['X'], [2, None, 8, 9])

    def test_injection_and_resource_limits(self):
        """任意Python、属性、索引、未知函数和超大公式不能执行。"""
        for formula in ('X:=__import__("os");', 'X:=C.__class__;', 'X:=C[0];', 'X:=POW(C,2);',
                        'X:=REF(C,-1);', 'X:=MA(C,5001);', 'X:=' + '(' * 200 + 'C' + ')' * 200 + ';',
                        'X:=' + '+'.join(['C'] * 2000) + ';'):
            with self.subTest(formula=formula[:50]), self.assertRaises(FormulaError):
                evaluate_formula(formula, {'C': [1, 2]})

    def test_raw_cooldown_and_display_priority(self):
        """被更高优先级压制的raw仍阻挡下一根，不能用上次显示日期替代。"""
        formula = ('BUYRAW:=B OR C; BUYCOOL:=COUNT(REF(BUYRAW,1),2)=0; '
                   'TOPSIG:=T; BOTSIG:=B AND BUYCOOL AND TOPSIG=0; '
                   'PUTSIG:=P AND TOPSIG=0 AND BOTSIG=0; '
                   'CALLSIG:=C AND BUYCOOL AND TOPSIG=0 AND BOTSIG=0 AND PUTSIG=0;')
        out = evaluate_formula(formula, {'B': [0]*6, 'C': [0, 0, 1, 1, 0, 1], 'T': [0, 0, 1, 0, 0, 0], 'P': [0]*6})
        self.assertEqual(out['CALLSIG'][2:6], [False, False, False, False])


class IndicatorTests(unittest.TestCase):
    """锁定真实源码定义、版本差异和全部计算序列的历史稳定性。"""

    def test_catalog_is_eight_with_honest_unsupported(self):
        """四个展示指标不捏造事件，两个Python结构指标明确禁用。"""
        self.assertEqual(len(CATALOG), 8)
        for name in ('CL2', 'SRJ'):
            self.assertFalse(CATALOG[name]['supported'])
            self.assertTrue(CATALOG[name]['displayRepainting'])
            with self.assertRaises(ValueError):
                calculate(bars(10), name)
        for name in ('GZRX1', 'GZRX3', 'LDR', 'GZRZH'):
            self.assertEqual(calculate(bars(), name)['events'], [])

    def test_exact_reviewed_expression_coverage(self):
        """完整计算表达式有固定哈希，并核对易被错误简化的命名条件。"""
        pinned = {'GZRX1': ('5352cf9315870dfcdcfcda8d9e775e8a91a7ff0a0c3761eb12881c554ffd41ce', 6),
                  'GZRX3': ('6307c5f6ee2bcf2f05a3ca97159fcb89516198c485f6a54368586ff752d0a3b6', 5),
                  'GZRZH': ('17b06b2d832c64348655c2c29a719e6069de2ff3547f47a047f3860044528061', 17),
                  'LDR': ('df7ef31b4c37132847a5ffa2c1437eb4d93460dba8b43eaf5cbbb74829007a9b', 6),
                  'QUSHI-CHANG': ('ea0594afcd6491fd27fd9323b84bf4fcbb6fcb5b568cde00334742ae774eb68b', 249),
                  'QUSHI-DUAN': ('a86414057e327e9e287cd6692d548b1c6a5eacbadd2e6b1cb3652509d2af7c1e', 249)}
        for name in FORMULAS:
            entry = CATALOG[name]
            self.assertEqual(hashlib.sha256(FORMULAS[name].encode()).hexdigest(), entry['calculationSha256'])
            self.assertEqual((entry['calculationSha256'], entry['assignmentCount']), pinned[name])
            out = calculate(bars(30), name)
            self.assertEqual(len(out['series']), entry['assignmentCount'])
        long = FORMULAS['QUSHI-CHANG']
        for exact in ('REF(H,MBHN+3)', 'COUNT(REF(BUYRAW,1),18)=0', 'RVOL<=4',
                      'REF(H,3)=HHV(H,7)', 'REF(L,MBLN+3)', 'COUNT(V<=0,20)=0',
                      'CALLLEGACY', 'GSPRAW', 'DSHAPEBUY', 'DHIST', 'DIFX>DEAX'):
            self.assertIn(exact, long)
        self.assertNotIn('RVOL<=4', long.split('PUTF:=')[1].split(';')[0])
        self.assertEqual(CATALOG['QUSHI-CHANG']['sourceSha256'], '379ce5cb935f95fd1c8b6839d03b077c56921fac79e8800f866a797be8813546')

    def test_actual_mb_pivot_plus_three_and_dynamic_reference(self):
        """手工构造两个顶枢轴，实际源码只能在右侧第3根及交叉确认日发出事件。"""
        formula = '\n'.join(line for line in FORMULAS['QUSHI-CHANG'].splitlines()
                            if re.match(r'MB(?:PH|PL|HN|LN|TOP|BOT|BUY|SELL):=', line))
        n = 230
        highs = [100 + i * .01 for i in range(n)]
        highs[204], highs[214] = 120, 122
        dif, hist, dea = [5] * n, [3] * n, [3] * n
        dif[214], hist[214] = 4, 2
        dif[216], dif[217] = 4, 2
        inputs = {'BC': list(range(1, n+1)), 'H': highs, 'L': [90 + i*.01 for i in range(n)],
                  'DIFX': dif, 'HISTX': hist, 'DEAX': dea}
        out = evaluate_formula(formula, inputs)
        self.assertTrue(out['MBPH'][207])
        self.assertEqual(out['MBHN'][217], 10)
        self.assertFalse(out['MBTOP'][214])
        self.assertTrue(out['MBTOP'][217])
        self.assertTrue(out['MBSELL'][217])
        for cutoff in (205, 208, 215, 218):
            partial = evaluate_formula(formula, {k: v[:cutoff] for k, v in inputs.items()})
            self.assertEqual(partial, {k:v[:cutoff] for k,v in out.items()})

    def test_long_short_complete_pipeline_produces_all_primary_families(self):
        """固定随机种子的合成路径真实穿过raw→过滤→冷却→显示，而非注入买卖事件。"""
        rng, rows, previous = random.Random(0), [], 100
        for i in range(1800):
            opening = previous * (1 + rng.gauss(0, .002))
            close = opening * (1 + rng.gauss(.00015, .012))
            spread = rng.uniform(.001, .009) * close
            rows.append(dict(date=(date(2000,1,1)+timedelta(days=i)).isoformat(), open=opening,
                             high=max(opening,close)+spread, low=min(opening,close)-spread, close=close,
                             volume=rng.choice([600,800,1000,1000,1200,1600,2000,2600])))
            previous = close
        long, short = (calculate(rows, name) for name in ('QUSHI-CHANG','QUSHI-DUAN'))
        counts = {key: sum(v is True for v in short['series'][key]) for key in ('CALLSIG','PUTSIG','BOTSIG','TOPSIG')}
        self.assertEqual(counts, {'CALLSIG':3, 'PUTSIG':2, 'BOTSIG':1, 'TOPSIG':8})
        self.assertNotEqual(long['events'], short['events'])
        self.assertTrue(short['quality']['historicalBottomReady'])
        for key in ('CALLSIG','BOTSIG','PUTSIG','TOPSIG'):
            index = next(e['index'] for e in short['events'] if e['name']==key)
            prefix = calculate(rows[:index+1], 'QUSHI-DUAN')
            self.assertEqual(prefix['series'], {k:v[:index+1] for k,v in short['series'].items()})
            self.assertIn(next(e for e in short['events'] if e['name']==key), prefix['events'])

    def test_ma_and_ladder_source_oracles(self):
        """均线周期来自审计参数；综合版MA200与EMA200各自计算。"""
        rows = bars(260)
        for name, periods in [('GZRX1', [5, 10, 30, 60, 90, 180]), ('GZRX3', [55, 60, 65, 120, 250])]:
            out = calculate(rows, name)['series']
            for n in periods:
                self.assertIsNone(out[f'MA{n}'][n-2])
                self.assertAlmostEqual(out[f'MA{n}'][n-1], sum(r['close'] for r in rows[:n]) / n)
        combined = calculate(rows, 'GZRZH')['series']
        self.assertEqual(combined['UP1'][0], rows[0]['high'])
        self.assertNotEqual(combined['MA200'][-1], combined['TREND'][-1])

    def test_long_short_differ_and_events_are_confirmed(self):
        """长短原始条件不是同一套通用均线交叉。"""
        a, b = (calculate(bars(380), name) for name in ('QUSHI-CHANG', 'QUSHI-DUAN'))
        self.assertNotEqual(a['series']['DATAOK'], b['series']['DATAOK'])
        self.assertNotEqual(a['series']['GOLDRAW'], b['series']['GOLDRAW'])
        for out in (a, b):
            for event in out['events']:
                self.assertEqual(event['confirmIndex'], event['index'])
                self.assertEqual(event['firstExecutableIndex'], event['index'] + 1)
            for i in range(380):
                self.assertLessEqual(sum(out['series'][key][i] is True for key in ('TOPSIG', 'BOTSIG', 'PUTSIG', 'CALLSIG')), 1)

    def test_all_series_and_events_are_prefix_invariant(self):
        """完整运行和各前缀重算逐值一致，包括动态REF和确认事件。"""
        rows = bars(330)
        for name in FORMULAS:
            full = calculate(rows, name)
            for cutoff in (1, 21, 67, 121, 209, 329):
                prefix = calculate(rows[:cutoff], name)
                self.assertEqual(prefix['series'], {k: v[:cutoff] for k, v in full['series'].items()}, (name, cutoff))
                self.assertEqual(prefix['events'], [e for e in full['events'] if e['index'] < cutoff])

    def test_historical_bottom_is_not_warmed_at_827(self):
        """不把1000根依赖不足解读为已经完成历史底验证。"""
        out = calculate(bars(827), 'QUSHI-CHANG')
        self.assertFalse(out['quality']['historicalBottomReady'])
        self.assertTrue(all(v is None for v in out['series']['LOW1000']))
        self.assertFalse(any(e['name'] == 'DHIST' for e in out['events']))

    def test_volume_missing_zero_and_bad_ohlc(self):
        """缺量向下传播；零量使量价确认失效；非法OHLC拒绝。"""
        rows = bars(140)
        rows[125]['volume'] = None
        out = calculate(rows, 'QUSHI-CHANG')['series']
        self.assertIsNone(out['RVOL'][125])
        self.assertIsNone(out['VWM20'][125])
        self.assertIsNot(out['DATAOK'][125], True)
        rows[125]['volume'] = 0
        self.assertFalse(calculate(rows, 'QUSHI-CHANG')['series']['DATAOK'][125])
        for change in ({'high': 1}, {'close': None}, {'volume': -1}, {'open': float('nan')}):
            bad = bars(2)
            bad[0].update(change)
            with self.assertRaises(ValueError):
                validate_bars(bad)

    def test_dates_limits_and_daily_only(self):
        """重复、倒序、非ISO日期和超过5000根都拒绝。"""
        for rows in (bars(2)[::-1], [bars(1)[0]] * 2, bars(5001)):
            with self.assertRaises(ValueError):
                validate_bars(rows)
        with self.assertRaises(ValueError):
            calculate(bars(), 'QUSHI-CHANG', timeframe='5m')


if __name__ == '__main__':
    unittest.main()
