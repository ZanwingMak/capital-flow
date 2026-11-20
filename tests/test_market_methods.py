"""Synthetic market-method fixtures exercise real confirmation and execution paths."""
import copy
import json
import unittest
from datetime import datetime, timedelta, timezone

from indicator_backtest import run_backtest
from market_methods import TRADE_METHODS, calculate, wave_candidate
from methods_service import get_report, orderflow_sample, parse_request
from test_indicator_engine import bars


def flat_rows(count=100):
    """Keep prices and volume stable until an explicit synthetic setup occurs."""
    rows = bars(count)
    for row in rows:
        row.update(open=100, close=100, high=100.5, low=99.5, volume=1000)
    return rows


def candle(rows, index, opening, high, low, close, volume=2000):
    """Replace a candle without changing its date or neighboring records."""
    rows[index].update(open=opening, high=high, low=low, close=close, volume=volume)


def setup_rows(method):
    """Construct each documented sequence without mocks or relaxed thresholds."""
    rows = flat_rows()
    if method == 'PA':
        candle(rows, 65, 100, 103.2, 99.8, 103)
        candle(rows, 66, 102, 104, 100.4, 103.8)
    elif method == 'ICT':
        candle(rows, 60, 100, 101.5, 99.5, 100.5, 1000)
        candle(rows, 63, 100, 100.5, 98, 99.5, 1000)
        candle(rows, 66, 99.5, 100.6, 97.5, 100.3)
        candle(rows, 67, 100.3, 104, 100, 103.8)
        candle(rows, 68, 104, 105, 103, 104.8)
        candle(rows, 69, 103.2, 105, 102.8, 104.7)
    elif method == 'WYCKOFF':
        for i in range(40, 60, 5):
            candle(rows, i, 100, 103, 97, 100, 1000)
        candle(rows, 60, 98, 99.3, 96.5, 99)
        candle(rows, 61, 98.5, 99.4, 97.2, 99, 500)
        candle(rows, 62, 99, 102.2, 98.8, 102)
    elif method == 'MEAN_REVERSION':
        for i in range(len(rows)):
            candle(rows, i, 100, 102, 98, 100 + (.1 if i % 2 else -.1), 1000)
        for i in range(60, 70):
            close = 100 - (i - 59) * .15
            candle(rows, i, close + .1, 102, 98, close, 1000)
        candle(rows, 70, 98.7, 102, 98.2, 99.5)
    else:
        raise ValueError(method)
    return rows


def payload(rows, **changes):
    """Supply only synthetic public-market metadata to the injectable service."""
    return dict(rows=rows, symbol='TEST', market='US', timezone='America/New_York',
                source='synthetic', adjustment='synthetic', **changes)


def report(rows, **kwargs):
    """Run the entire service with no network, credentials or account state."""
    return get_report('TEST', rows[-1]['date'], 'US', lambda *_: payload(rows), **kwargs)


class MethodConfirmationTests(unittest.TestCase):
    def test_all_four_real_setups_generate_entries_and_execute(self):
        expected = {'ICT': 69, 'PA': 66, 'WYCKOFF': 62, 'MEAN_REVERSION': 70}
        for method, index in expected.items():
            with self.subTest(method=method):
                rows = setup_rows(method)
                result = report(rows, fee_bps=0, slippage_bps=0)['methods'][method]
                entry_name = ('MEAN' if method == 'MEAN_REVERSION' else method) + '_LONG'
                entries = [e for e in result['events'] if e['name'] == entry_name]
                self.assertEqual([e['index'] for e in entries], [index])
                self.assertEqual(entries[0]['layer'], 'primary')
                self.assertEqual(entries[0]['confirmIndex'], index)
                backtest = result['backtest']
                self.assertEqual(backtest['metrics']['closedTrades'], 1)
                trade = backtest['trades'][0]
                self.assertEqual(trade['entrySignal'], entry_name)
                self.assertEqual(trade['entrySignalDate'], rows[index]['date'])
                self.assertEqual(trade['entryDate'], rows[index + 1]['date'])
                self.assertEqual(trade['entryPrice'], rows[index + 1]['open'])
                self.assertEqual(backtest['rules']['maxHoldBars'], 20)
                if method == 'MEAN_REVERSION':
                    self.assertEqual(trade['exitReason'], 'MEAN_TARGET_EXIT')
                    self.assertEqual(trade['exitDate'], rows[72]['date'])
                else:
                    self.assertEqual(trade['exitReason'], 'max-hold')
                    self.assertEqual(trade['heldBars'], 20)

    def test_incomplete_sequences_never_enter(self):
        ends = {'ICT': 69, 'PA': 66, 'WYCKOFF': 62, 'MEAN_REVERSION': 70}
        for method, end in ends.items():
            with self.subTest(method=method):
                selected = [e for e in calculate(setup_rows(method)[:end])['events'] if e['method'] == method]
                self.assertFalse(any(e['layer'] == 'primary' and e['direction'] == 1 for e in selected))

    def test_missing_confirmation_volume_does_not_become_zero_or_pass(self):
        for method, index in (('ICT', 69), ('PA', 66), ('WYCKOFF', 62)):
            for volume in (None, 0):
                with self.subTest(method=method, volume=volume):
                    rows = setup_rows(method)[:index + 1]
                    rows[index]['volume'] = volume
                    events = calculate(rows)['events']
                    self.assertFalse(any(e['method'] == method and e['layer'] == 'primary' and e['direction'] == 1 for e in events))

    def test_future_data_cannot_change_series_events_or_confirmed_pivots(self):
        for method in TRADE_METHODS:
            rows = setup_rows(method)
            original = copy.deepcopy(rows)
            full = calculate(rows)
            for end in (60, 61, 63, 66, 68, 69, 70, 71, 72, 80, 99):
                with self.subTest(method=method, end=end):
                    prefix = calculate(rows[:end])
                    self.assertEqual(prefix['events'], [e for e in full['events'] if e['confirmIndex'] < end])
                    self.assertEqual(prefix['pivots'], [p for p in full['pivots'] if p['knownIndex'] < end])
                    for name, series in prefix['series'].items():
                        self.assertEqual(series, full['series'][name][:end])
                    self.assertTrue(all(p['knownIndex'] == p['index'] + 2 for p in prefix['pivots']))
            self.assertEqual(rows, original)

    def test_bearish_confirmations_only_exit_never_short(self):
        for method in TRADE_METHODS:
            with self.subTest(method=method):
                rows = setup_rows(method)
                for row in rows:
                    row.update(open=200-row['open'], close=200-row['close'],
                               high=200-row['low'], low=200-row['high'])
                result = report(rows)['methods'][method]
                exits = [e for e in result['events'] if e['layer'] == 'primary' and e['direction'] == -1]
                self.assertTrue(exits)
                self.assertEqual(result['backtest']['metrics']['closedTrades'], 0)
                self.assertEqual(result['backtest']['metrics']['exposure'], 0)
                self.assertIsNone(result['backtest']['openPosition'])
                self.assertIsNone(result['backtest']['metrics']['winRate'])

    def test_observation_methods_never_receive_backtests(self):
        result = report(bars(500))
        self.assertTrue(result['methods']['ELLIOTT']['events'])
        for method in ('ELLIOTT', 'ORDERFLOW'):
            self.assertIsNone(result['methods'][method]['backtest'])
            self.assertEqual(result['methods'][method]['splits'], {})

    def test_wave_geometry_checks_both_directions_and_invalid_overlap(self):
        points = [dict(index=i*3, knownIndex=i*3+2, side=side, price=price)
                  for i, (side, price) in enumerate(zip(
                      ('low', 'high', 'low', 'high', 'low', 'high'), (100, 110, 105, 125, 115, 130)))]
        wave = wave_candidate(points)
        assert wave is not None
        self.assertEqual(wave['direction'], 'bullish')
        self.assertEqual(wave['waveLengths'], [10, 20, 15])
        self.assertFalse(wave['subdivisionVerified'])
        inverse = [{**p, 'price': 250-float(p['price']), 'side': 'high' if p['side'] == 'low' else 'low'} for p in points]
        inverse_wave = wave_candidate(inverse)
        assert inverse_wave is not None
        self.assertEqual(inverse_wave['direction'], 'bearish')
        points[4]['price'] = 109
        self.assertIsNone(wave_candidate(points))


class MethodRequestTests(unittest.TestCase):
    def test_rejects_invalid_requests_before_any_loader_call(self):
        invalid = ({'symbol': ['TEST', 'OTHER']}, {'symbol': '../TEST'}, {'symbol': ''},
                   {'symbol': True}, {'market': 'HK'}, {'timeframe': '1m'}, {'asOf': '2000-02-30'},
                   {'feeBps': 'nan'}, {'feeBps': '-1'}, {'feeBps': '101'},
                   {'slippageBps': 'inf'}, {'initial': '0'}, {'initial': '1000000001'},
                   {'maxHoldBars': '1'}, {'formula': 'C'}, {'path': '/private'}, {'asOf': []})
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                parse_request({'symbol': 'TEST', 'asOf': '2000-01-01', **changes})
        calls = []
        with self.assertRaises(ValueError):
            get_report('../TEST', '2000-01-01', 'US', lambda *args: calls.append(args))
        self.assertEqual(calls, [])

    def test_canonical_request_values_reach_loader_and_report(self):
        rows, calls = flat_rows(), []
        def loader(*args):
            calls.append(args)
            return payload(rows)
        result = get_report(' test ', ' '+rows[-1]['date']+' ', ' US ', loader)
        self.assertEqual(calls, [('TEST', rows[-1]['date'], 'US')])
        self.assertEqual(result['market'], 'US')
        json.dumps(result, allow_nan=False)

    def test_cutoff_excludes_future_signals_prices_and_flow_dates(self):
        rows = setup_rows('PA')
        cutoff = rows[65]['date']
        calls = []
        result = get_report('TEST', cutoff, 'US', lambda *_: payload(rows),
                            flow_loader=lambda *args: calls.append(args) or {'status': 'unavailable', 'rows': []})
        prefix = report(rows[:66])
        self.assertEqual(result['methods']['PA']['events'], prefix['methods']['PA']['events'])
        self.assertEqual(result['sha256'], prefix['sha256'])
        self.assertEqual(result['sample']['futureBarsExcluded'], 34)
        self.assertEqual(result['dates'], [r['date'] for r in rows[:66]])
        self.assertEqual(calls, [('TEST', cutoff)])
        self.assertIsNone(result['methods']['PA']['backtest']['openPosition'])

    def test_rejects_mismatched_metadata_and_uncompleted_bars(self):
        rows = flat_rows()
        for changes in ({'symbol': 'OTHER'}, {'market': 'HK'}, {'timezone': 'UTC'},
                        {'completedAsOf': rows[90]['date']}, {'completedAsOf': '2001-01-01'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                get_report('TEST', rows[-1]['date'], 'US', lambda *_: {**payload(rows), **changes})

    def test_stale_bars_do_not_read_old_orderflow(self):
        rows, calls = flat_rows(), []
        result = get_report('TEST', '2000-05-01', 'US', lambda *_: payload(rows),
                            flow_loader=lambda *args: calls.append(args))
        self.assertTrue(result['quality']['stale'])
        self.assertEqual(calls, [])
        self.assertEqual(result['methods']['ORDERFLOW']['status'], 'unavailable')

    def test_empty_warmup_and_minimum_backtest_boundaries(self):
        for count in (0, 1, 59, 60, 61, 64, 65):
            with self.subTest(count=count):
                rows = flat_rows(count)
                result = get_report('TEST', '2000-05-01', 'US', lambda *_: payload(rows))
                for method in TRADE_METHODS:
                    backtest = result['methods'][method]['backtest']
                    self.assertEqual(backtest is not None, count >= 65)
                    if backtest:
                        self.assertEqual(backtest['range']['bars'], count-60)
                        self.assertEqual(len(result['methods'][method]['splits']), 3)
                json.dumps(result, allow_nan=False)


class FixedExecutionTests(unittest.TestCase):
    strategy = {'entry': ['PA_LONG'], 'exit': ['PA_EXIT'], 'maxHoldBars': 20}

    def test_next_open_costs_use_only_configured_events(self):
        rows = flat_rows(6)
        candle(rows, 1, 110, 111, 99, 100)
        candle(rows, 4, 120, 121, 99, 100)
        events = [dict(index=0, name='PA_LONG'), dict(index=1, name='BREAKOUT'),
                  dict(index=2, name='PUTSIG'), dict(index=3, name='PA_EXIT')]
        out = run_backtest(rows, events, version='PA', strategy=self.strategy)
        shares = 10000/(110*1.0005*1.0005)
        self.assertAlmostEqual(out['metrics']['endingEquity'], shares*120*.9995*.9995)
        self.assertEqual(out['metrics']['closedTrades'], 1)
        self.assertEqual(out['trades'][0]['exitDate'], rows[4]['date'])
        self.assertEqual(out['trades'][0]['exitReason'], 'PA_EXIT')

    def test_exit_has_priority_over_simultaneous_entry(self):
        rows = flat_rows(6)
        events = [dict(index=0, name='PA_LONG'), dict(index=0, name='PA_EXIT'),
                  dict(index=1, name='PA_LONG'), dict(index=3, name='PA_LONG'), dict(index=3, name='PA_EXIT')]
        out = run_backtest(rows, events, version='PA', strategy=self.strategy)
        self.assertEqual(len(out['trades']), 1)
        self.assertEqual(out['trades'][0]['entryDate'], rows[2]['date'])
        self.assertEqual(out['trades'][0]['exitDate'], rows[4]['date'])
        self.assertIsNone(out['openPosition'])

    def test_split_starts_flat_and_final_confirmation_cannot_fill(self):
        rows = flat_rows(10)
        out = run_backtest(rows, [dict(index=2, name='PA_LONG'), dict(index=6, name='PA_LONG')],
                           start=3, end=7, version='PA', strategy=self.strategy)
        self.assertEqual(out['metrics']['exposure'], 0)
        self.assertEqual(out['unexecutedSignals'], 1)
        self.assertIsNone(out['openPosition'])

    def test_fixed_strategy_rejects_ambiguous_events_and_hold_bounds(self):
        for strategy in ({'entry': [], 'exit': ['X'], 'maxHoldBars': 20},
                         {'entry': ['X'], 'exit': ['X'], 'maxHoldBars': 20},
                         {'entry': ['X'], 'exit': ['Y'], 'maxHoldBars': True},
                         {'entry': ['X'], 'exit': ['Y'], 'maxHoldBars': 0},
                         {'entry': ['X'], 'exit': ['Y'], 'maxHoldBars': 253}):
            with self.subTest(strategy=strategy), self.assertRaises(ValueError):
                run_backtest(flat_rows(), [], strategy=strategy)


class OrderFlowTests(unittest.TestCase):
    def test_quote_timing_unknown_excluded_and_sample_boundaries(self):
        start = datetime(2000, 1, 3, 20, 40, tzinfo=timezone.utc)
        close = start+timedelta(minutes=20)
        def stamp(seconds):
            return (start+timedelta(seconds=seconds)).isoformat()
        quotes = [dict(t=stamp(0), bp=99, ap=101, bs=1, **{'as': 1}),
                  dict(t=stamp(4), bp=98, ap=100, bs=1, **{'as': 1})]
        trades = [dict(t=stamp(t), p=p, s=s, c=c) for t, p, s, c in (
            (-1, 101, 1000, []), (0, 101, 2, []), (1, 101, 10, []),
            (2, 99, 3, []), (3, 100, 4, []), (4, 100, 5, []),
            (5, 100, 8, ['6']), (10, 100, 6, []), (1200, 101, 1000, []))]
        out = orderflow_sample(trades, quotes, start, close)
        self.assertEqual(out['sampleTrades'], 7)
        self.assertEqual(out['buyVolume'], 10)
        self.assertEqual(out['sellVolume'], 3)
        self.assertEqual(out['unknownVolume'], 17)
        self.assertEqual(out['excludedVolume'], 8)
        self.assertEqual(out['netVolume'], 7)
        self.assertAlmostEqual(out['classifiedRatio'], 13/30)
        self.assertFalse(out['directionReliable'])
        self.assertFalse(out['fullDay'])
        self.assertEqual(len(out['rows']), 20)
        self.assertEqual(out['rows'][0]['cvd'], 7)
        self.assertIsNone(out['rows'][1]['cvd'])

    def test_incomplete_window_is_rejected_and_no_quotes_is_unknown(self):
        start = datetime(2000, 1, 3, tzinfo=timezone.utc)
        with self.assertRaises(ValueError):
            orderflow_sample([], [], start, start+timedelta(minutes=19))
        out = orderflow_sample([dict(t=(start+timedelta(seconds=1)).isoformat(), p=100, s=10)],
                               [], start, start+timedelta(minutes=20))
        self.assertEqual(out['status'], 'unavailable')
        self.assertIsNone(out['netVolume'])
        self.assertIsNone(out['rows'][0]['delta'])
        self.assertEqual(out['unknownVolume'], 10)


if __name__ == '__main__':
    unittest.main()
