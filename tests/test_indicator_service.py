"""注入行情采集器，验证参数边界、日期截断和JSON安全性。"""
import json
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from indicator_cli import main
from indicator_service import get_report, parse_request
from test_indicator_engine import bars


class ServiceTests(unittest.TestCase):
    """服务计算不读取密钥、原文件路径或任意公式。"""

    def test_strict_request_validation(self):
        """拒绝重复、未知、任意路径、非日线和不合法费用。"""
        for query in ({'symbol': ['A', 'B']}, {'symbol': '../A'}, {'formula': 'C'},
                      {'market': 'HK'}, {'timeframe': '5m'}, {'feeBps': 'nan'},
                      {'asOf': '2000-02-30'}, {'indicator': 'oops'}, {'maxHold': '3'}):
            with self.subTest(query=query), self.assertRaises(ValueError):
                parse_request({'symbol': 'AAPL', 'asOf': '2001-01-01', **query})

    def test_injected_loader_and_cutoff(self):
        """早于样本末尾的请求只使用截至日及之前数据，JSON严格无NaN。"""
        rows = bars(320)
        calls = []

        def loader(symbol, as_of, market):
            """记录已验证参数，返回合成行情元数据。"""
            calls.append((symbol, as_of, market))
            return {'rows': rows, 'source': 'synthetic', 'adjustment': 'QFQ', 'timezone': 'America/New_York'}

        report = get_report('TEST', rows[250]['date'], 'US', loader, indicator='QUSHI-DUAN')
        self.assertEqual(calls, [('TEST', rows[250]['date'], 'US')])
        self.assertEqual(report['sample']['bars'], 251)
        self.assertEqual(report['dates'][-1], rows[250]['date'])
        self.assertEqual(report['data']['source'], 'synthetic')
        self.assertFalse(report['compatibility']['futuCertified'])
        json.dumps(report, allow_nan=False)

    def test_no_fake_performance_for_display_family(self):
        """无原生买卖事件的均线目录只展示真实数值。"""
        report = get_report('TEST', bars(30)[-1]['date'], 'US', lambda *_: bars(30), indicator='GZRX1')
        self.assertIsNone(report['backtest'])
        self.assertEqual(report['events'], [])
        self.assertEqual(len(report['catalog']), 8)

    def test_empty_and_short_quality(self):
        """无数据与暖机不足有明确状态，不填充演示收益。"""
        empty = get_report('TEST', '2001-01-01', 'US', lambda *_: [])
        self.assertEqual(empty['status'], 'empty')
        short = get_report('TEST', '2001-01-01', 'US', lambda *_: bars(40))
        self.assertEqual(short['status'], 'warming-up')
        self.assertIsNone(short['backtest'])

    def test_explicit_splits_are_chronological(self):
        """可指定验证及留出开始日期，禁止逆序或样本外日期。"""
        rows = bars(320)
        report = get_report('TEST', rows[-1]['date'], 'US', lambda *_: rows,
                            validation_start=rows[220]['date'], holdout_start=rows[270]['date'])
        self.assertEqual(report['splits']['holdout']['range']['start'], rows[270]['date'])
        with self.assertRaises(ValueError):
            get_report('TEST', rows[-1]['date'], 'US', lambda *_: rows,
                       validation_start=rows[270]['date'], holdout_start=rows[220]['date'])

    def test_canonical_symbols_metadata_and_datetime(self):
        """规范化股票代码；错误市场或时区拒绝；采集时间可安全序列化。"""
        rows = bars(3)
        report = get_report('test', rows[-1]['date'], 'US', lambda *_: {'rows':rows, 'symbol':'TEST', 'collectedAt':datetime(2000,1,3,tzinfo=timezone.utc)}, indicator='LDR')
        self.assertEqual(report['symbol'], 'TEST')
        self.assertEqual(report['data']['collectedAt'], '2000-01-03T00:00:00+00:00')
        for key, value in (('symbol','OTHER'), ('market','HK'), ('timezone','Asia/Shanghai')):
            with self.subTest(key=key), self.assertRaises(ValueError):
                get_report('TEST', rows[-1]['date'], 'US', lambda *_: {'rows':rows,key:value})

    def test_canonical_dates_used_for_loader_and_cutoff(self):
        """接口已接受的空白规范化必须同时用于loader、截断和报告身份。"""
        rows, calls = bars(150), []
        cutoff = rows[130]['date']
        def loader(symbol, as_of, market):
            calls.append((symbol, as_of, market))
            return rows
        report = get_report(' test ', ' ' + cutoff + ' ', 'US', loader)
        self.assertEqual(calls, [('TEST', cutoff, 'US')])
        self.assertEqual(report['asOf'], cutoff)
        self.assertEqual(report['sample']['bars'], 131)

    def test_short_evaluation_does_not_claim_three_nonempty_splits(self):
        """刚完成暖机的一两根可计价，但不足以组成三个非空区间。"""
        rows = bars(150)
        complete = get_report('TEST', rows[-1]['date'], 'US', lambda *_: rows)
        first = complete['dataQuality']['firstEligibleIndex']
        self.assertIsNotNone(first)
        for count in (1, 2, 3):
            with self.subTest(count=count):
                subset = rows[:first + count]
                report = get_report('TEST', subset[-1]['date'], 'US', lambda *_: subset)
                self.assertEqual(report['backtest']['range']['bars'], count)
                self.assertEqual(len(report['splits']), 3 if count == 3 else 0)
                for split in report['splits'].values():
                    self.assertGreater(split['range']['bars'], 0)
                if count < 3:
                    self.assertTrue(any('不足3根' in w for w in report['warnings']))

    def test_cli_real_pipeline_and_input_preservation(self):
        """CLI真实经过引擎并产生严格JSON，拒绝覆盖行情输入。"""
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder)/'bars.json', Path(folder)/'report.json'
            original = json.dumps({'symbol':'TEST','rows':bars(140),'source':'synthetic'})
            source.write_text(original)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--input',str(source),'--output',str(target)]),0)
            report = json.loads(target.read_text())
            self.assertEqual(report['sample']['bars'],140)
            self.assertEqual(source.read_text(),original)
            with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
                main(['--input',str(source),'--output',str(source)])


if __name__ == '__main__':
    unittest.main()
