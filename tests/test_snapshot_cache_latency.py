"""历史缓存延迟回归：只使用临时文件、真实 pandas 和确定性假上游，不连接 OpenD。"""
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import json
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import pandas as pd
import server


DAY = '2026-11-06'
SCRATCH = Path.home() / '.hermes/cache/scratch/flowdesk-review/portfolio-tests'


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime.fromisoformat('2026-11-09T12:00:00+00:00').astimezone(tz)


class FakeClock:
    def __init__(self):
        self.current = 100.0
        self.waits = []

    def monotonic(self):
        return self.current

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.current += seconds


def flow_row(day=DAY):
    return {'capital_flow_item_time': day, 'big_in_flow': 20000,
            'super_in_flow': 10000, 'mid_in_flow': -5000, 'sml_in_flow': -25000}


def price_row():
    return {'time_key': DAY + ' 00:00:00', 'name': '历史名称', 'close': 10,
            'change_rate': 2, 'low': 9, 'high': 11}


class FakeProvider:
    def __init__(self, clock):
        self.clock = clock
        self.requests = []

    def request_trading_days(self, **kwargs):
        return 0, [{'time': DAY}]

    def get_market_snapshot(self, codes):
        return 0, pd.DataFrame([{'code': code, 'name': '当前名称', 'last_price': 99,
                                'prev_close_price': 98} for code in codes])

    def get_capital_flow(self, code, **kwargs):
        self.requests.append((code, self.clock.monotonic(), kwargs))
        return 0, pd.DataFrame([flow_row()])

    def request_history_kline(self, code, **kwargs):
        return 0, pd.DataFrame([price_row()]), None


class SnapshotCacheLatencyTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.addCleanup(directory.cleanup)
        self.data = Path(directory.name)
        (self.data / 'raw').mkdir()
        self.clock = FakeClock()
        self.provider = FakeProvider(self.clock)
        fake_sdk = SimpleNamespace(RET_OK=0, PeriodType=SimpleNamespace(DAY='DAY', INTRADAY='INTRADAY'),
                                   AuType=SimpleNamespace(QFQ='QFQ'), KLType=SimpleNamespace(K_DAY='K_DAY'))
        patches = [
            patch.object(server, 'DATA', self.data),
            patch.object(server, 'datetime', FrozenDatetime),
            patch.object(server, 'time', self.clock),
            patch.object(server, 'LAST_FLOW_REQUEST', 100.0),
            patch.object(server, 'CACHE', {}),
            patch.object(server, 'TRADING_DATES_CACHE', {}),
            patch.object(server, 'RECORD_CACHE', {}),
            patch.object(server, 'WATCHLIST', {'US': set(), 'HK': set(), 'CN': set()}),
            patch.object(server, 'get_context', return_value=self.provider),
            patch.object(server, 'archive_flow'),
            patch.dict(sys.modules, {'futu': fake_sdk}),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def cache(self, symbol, flow=True, quote=True):
        record = {'adjustment': 'QFQ', 'start': '2025-11-09', 'end': '2026-11-08',
                  'flow': [flow_row()] if flow else [], 'prices': [price_row()] if quote else []}
        (self.data / 'raw' / (symbol + '.json')).write_text(json.dumps(record), encoding='utf-8')

    def test_fully_cached_history_has_no_per_symbol_wait(self):
        symbols = ['TEST' + str(index) for index in range(49)]
        for symbol in symbols:
            self.cache(symbol)
        started = time.perf_counter()
        result = server.fetch_snapshot(symbols, DAY)
        elapsed = time.perf_counter() - started
        print(f'\n49 cached symbols: wall={elapsed:.4f}s simulated_wait={sum(self.clock.waits):.2f}s '
              f'flow_requests={len(self.provider.requests)}')
        self.assertEqual(len(result['rows']), 49)
        self.assertTrue(all(row['flowStatus'] == 'ok' and row['big'] == 2 and row['super'] == 1
                            and row['price'] == 10 and row['name'] == '历史名称' for row in result['rows']))
        self.assertEqual(self.provider.requests, [])
        self.assertEqual(sum(self.clock.waits), 0)
        self.assertEqual(server.LAST_FLOW_REQUEST, 100.0)

    def test_mixed_history_only_waits_for_missing_flows(self):
        for symbol in ['HIT1', 'MISS1', 'HIT2', 'MISS2', 'HIT3']:
            self.cache(symbol, flow=not symbol.startswith('MISS'))
        result = server.fetch_snapshot(['HIT1', 'MISS1', 'HIT2', 'MISS2', 'HIT3'], DAY)
        self.assertEqual([item[0] for item in self.provider.requests], ['US.MISS1', 'US.MISS2'])
        self.assertEqual(len(self.clock.waits), 2)
        self.assertAlmostEqual(sum(self.clock.waits), 2.10)
        self.assertAlmostEqual(self.provider.requests[0][1], 101.05)
        self.assertAlmostEqual(self.provider.requests[1][1], 102.10)
        self.assertAlmostEqual(server.LAST_FLOW_REQUEST, 102.10)
        self.assertTrue(all(item[2]['period_type'] == 'DAY' for item in self.provider.requests))
        self.assertTrue(all(row['flowStatus'] == 'ok' for row in result['rows']))

    def test_live_requests_keep_upstream_spacing(self):
        result = server.fetch_snapshot(['LIVE1', 'LIVE2'])
        self.assertEqual(result['mode'], 'live')
        self.assertEqual(len(self.provider.requests), 2)
        self.assertAlmostEqual(self.provider.requests[1][1] - self.provider.requests[0][1], 1.05)
        self.assertAlmostEqual(sum(self.clock.waits), 2.10)
        self.assertTrue(all(item[2]['period_type'] == 'INTRADAY' for item in self.provider.requests))

    def test_history_backfill_does_not_wait_again_after_populating_cache(self):
        result = server.fetch_snapshot(['NEW'], DAY)
        self.assertEqual(result['rows'][0]['flowStatus'], 'ok')
        self.assertEqual(len(self.provider.requests), 1)
        self.assertEqual(len(self.clock.waits), 1)
        self.assertAlmostEqual(sum(self.clock.waits), 1.05)
        self.assertAlmostEqual(server.LAST_FLOW_REQUEST, self.provider.requests[0][1])
        self.assertTrue((self.data / 'raw' / 'NEW.json').is_file())

    def test_failed_remote_attempt_still_occupies_upstream_interval(self):
        for symbol in ['FAIL', 'GOOD']:
            self.cache(symbol, flow=False)
        original = self.provider.get_capital_flow

        def fail_first(code, **kwargs):
            response = original(code, **kwargs)
            return (-1, 'no flow permission') if code == 'US.FAIL' else response

        with patch.object(self.provider, 'get_capital_flow', side_effect=fail_first):
            result = server.fetch_snapshot(['FAIL', 'GOOD'], DAY)
        self.assertEqual(result['rows'][0]['flowStatus'], 'unavailable')
        self.assertEqual(result['rows'][1]['flowStatus'], 'ok')
        self.assertAlmostEqual(self.provider.requests[1][1] - self.provider.requests[0][1], 1.05)

    def test_invalid_trading_date_is_rejected_even_with_disk_cache(self):
        self.cache('CACHED')
        with self.assertRaisesRegex(ValueError, '交易日'):
            server.fetch_snapshot(['CACHED'], '2026-11-07')
        self.assertEqual(self.provider.requests, [])
        self.assertEqual(self.clock.waits, [])

    def test_exact_snapshot_cache_bypasses_provider_until_history_ttl(self):
        self.cache('CACHED')
        first = server.fetch_snapshot(['CACHED'], DAY)
        self.clock.current += 3599
        with patch.object(server, 'get_context', side_effect=AssertionError('unexpected upstream')):
            self.assertIs(server.fetch_snapshot(['CACHED'], DAY), first)
        self.clock.current += 2
        with patch.object(server, 'get_context', wraps=server.get_context) as context:
            refreshed = server.fetch_snapshot(['CACHED'], DAY)
        context.assert_called_once()
        self.assertEqual(refreshed['rows'], first['rows'])
        self.assertEqual(self.clock.waits, [])

    def test_single_symbol_history_reuses_raw_cache_after_pool_request(self):
        for symbol in ['ONE', 'TWO']:
            self.cache(symbol)
        pool = server.fetch_snapshot(['ONE', 'TWO'], DAY)
        single = server.fetch_snapshot(['TWO'], DAY)
        self.assertEqual(single['rows'], [pool['rows'][1]])
        self.assertEqual(self.provider.requests, [])
        self.assertEqual(self.clock.waits, [])


if __name__ == '__main__':
    unittest.main()
