"""成交、成本、净值和独立留出区间的合成预言。"""
import unittest

from indicator_backtest import run_backtest, split_ranges
from test_indicator_engine import bars


def event(index, name='CALLSIG'):
    """构造明确在收盘确认的合成主事件。"""
    return {'index': index, 'name': name}


class BacktestTests(unittest.TestCase):
    """只测真实账户记账语义，不给原公式补充交易信号。"""

    def flat(self, count=30):
        """创建统一价格以隔离费用与时点影响。"""
        rows = bars(count)
        for row in rows:
            row.update(open=100, high=101, low=99, close=100)
        return rows

    def test_next_open_gap_and_cost_oracle(self):
        """入场跳空按实际次开盘，买卖每边手续费和滑点均入账。"""
        rows = self.flat(5)
        rows[1].update(open=110, high=111, low=99)
        rows[3].update(open=120, high=121)
        out = run_backtest(rows, [event(0), event(2, 'PUTSIG')], fee_bps=5, slippage_bps=5)
        trade = out['trades'][0]
        shares = 10000 / (110 * 1.0005 * 1.0005)
        final = shares * 120 * .9995 * .9995
        self.assertAlmostEqual(out['metrics']['endingEquity'], final)
        self.assertEqual(trade['entrySignalDate'], rows[0]['date'])
        self.assertEqual(trade['entryDate'], rows[1]['date'])
        self.assertEqual(trade['exitDate'], rows[3]['date'])
        self.assertAlmostEqual(out['equity'][1]['equity'], shares * 100)

    def test_last_bar_signal_cannot_fill(self):
        """最后收盘的信号不能在不存在的未来开盘成交。"""
        out = run_backtest(self.flat(3), [event(2)], fee_bps=0, slippage_bps=0)
        self.assertEqual(out['metrics']['closedTrades'], 0)
        self.assertIsNone(out['openPosition'])
        self.assertEqual(out['unexecutedSignals'], 1)
        self.assertIsNone(out['metrics']['winRate'])

    def test_open_position_is_marked_not_closed_win(self):
        """期末持仓按收盘计价，保留未实现盈亏且不增加胜场。"""
        out = run_backtest(self.flat(4), [event(0), event(1)], fee_bps=0, slippage_bps=0)
        self.assertEqual(out['metrics']['closedTrades'], 0)
        self.assertIsNotNone(out['openPosition'])
        self.assertEqual(out['metrics']['endingEquity'], 10000)
        self.assertEqual(out['metrics']['exposure'], .75)

    def test_version_locks_hold_and_no_same_bar_reentry(self):
        """短版持有20根后次开盘退出，长版40；没有重叠或同根再进场。"""
        rows = self.flat(45)
        short = run_backtest(rows, [event(0)], version='QUSHI-DUAN', fee_bps=0, slippage_bps=0)
        long = run_backtest(rows, [event(0)], version='QUSHI-CHANG', fee_bps=0, slippage_bps=0)
        self.assertEqual(short['trades'][0]['exitDate'], rows[21]['date'])
        self.assertEqual(long['trades'][0]['exitDate'], rows[41]['date'])
        self.assertEqual(short['trades'][0]['exitReason'], 'max-hold')

    def test_benchmark_same_range_and_initial_costs(self):
        """同区间基准从首根开盘入场，同样收取入场费用，期末仍持有。"""
        rows = self.flat(6)
        out = run_backtest(rows, [], start=2, end=5)
        expected = 10000 / (1.0005 * 1.0005)
        self.assertEqual([p['date'] for p in out['equity']], [r['date'] for r in rows[2:5]])
        self.assertAlmostEqual(out['benchmark']['endingEquity'], expected)
        self.assertEqual(out['metrics']['endingEquity'], 10000)
        self.assertLess(out['benchmark']['totalReturn'], 0)

    def test_drawdown_includes_initial_capital(self):
        """净值回撤包含首次成本和持仓收盘损失。"""
        rows = self.flat(4)
        rows[2].update(open=80, high=101, low=79, close=80)
        out = run_backtest(rows, [event(0)], fee_bps=0, slippage_bps=0)
        self.assertAlmostEqual(out['metrics']['maxDrawdown'], -.2)
        self.assertIsNone(out['metrics']['sharpe'])

    def test_cutoff_excludes_future_exit(self):
        """截断前缀不使用区间结束之后的退出，并保留最后持仓。"""
        rows = self.flat(10)
        out = run_backtest(rows, [event(0), event(4, 'TOPSIG')], end=5)
        self.assertIsNotNone(out['openPosition'])
        self.assertEqual(out['metrics']['closedTrades'], 0)

    def test_independent_holdout_and_purged_boundary(self):
        """训练区间不能读取验证退出；留出从空仓开始且不消费前区间信号。"""
        rows = self.flat(100)
        ranges = split_ranges(rows, start=10)
        self.assertEqual(ranges, {'train': (10, 64), 'validation': (64, 82), 'holdout': (82, 100)})
        events = [event(62), event(65, 'TOPSIG'), event(81)]
        train = run_backtest(rows, events, *ranges['train'])
        holdout = run_backtest(rows, events, *ranges['holdout'])
        self.assertEqual(train['metrics']['closedTrades'], 0)
        self.assertIsNotNone(train['openPosition'])
        self.assertIsNone(holdout['openPosition'])

    def test_cost_and_event_validation(self):
        """费用、未知版本、越界事件和未来方向都不能悄悄接受。"""
        for kwargs in ({'fee_bps': -1}, {'fee_bps': 101}, {'slippage_bps': float('nan')}, {'initial': 0}, {'version': 'CL2'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                run_backtest(self.flat(), [], **kwargs)
        with self.assertRaises(ValueError):
            run_backtest(self.flat(), [event(-1)])


if __name__ == '__main__':
    unittest.main()
