"""合成量价及期权数据回归；不联网、不读取密钥或私有缓存。"""
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import intelligence as intel

NOW = datetime(2026, 11, 6, 16, 30, tzinfo=intel.NY)


def synthetic_bars(volume=100):
    """生成60根价格有效的合成日线，成交量可明确缺失或为零。"""
    return [{'date': (NOW.date() - timedelta(days=59-i)).isoformat(),
             'open': 100, 'high': 102, 'low': 98, 'close': 100, 'volume': volume}
            for i in range(60)]


def synthetic_chain(timestamp='2026-11-06T16:15:00-05:00', missing=False):
    """生成同范围多行权价的合成期权链，缺失OI保持None。"""
    return {'timestamp': timestamp, 'data': {'current_price': 100, 'options': [
        {'option': 'TEST261120C00105000', 'open_interest': 100, 'volume': 600},
        {'option': 'TEST261120C00110000', 'open_interest': None if missing else 200, 'volume': 100},
        {'option': 'TEST261120P00095000', 'open_interest': 150, 'volume': 500}]}}


class VolumeTests(unittest.TestCase):
    """20日计数需要20个有效的相邻成交量对。"""

    def test_all_missing_volume_is_unknown(self):
        """全缺失不能作为零次放量下跌。"""
        report = intel.technical_report(synthetic_bars(None), 'synthetic', '2026-11-06')
        self.assertIsNone(report['distributionDays20'])
        self.assertEqual(report['distributionCoverage']['available'], 0)
        self.assertEqual(report['distributionCoverage']['expected'], 20)
        self.assertTrue(report['distributionCoverage']['reason'])
        self.assertIsNone(report['relativeVolume20'])

    def test_partial_volume_is_unknown(self):
        """一个中间缺量点影响两个相邻比较，不输出完整窗口计数。"""
        rows = synthetic_bars()
        rows[-10]['volume'] = None
        report = intel.technical_report(rows, 'synthetic', '2026-11-06')
        self.assertIsNone(report['distributionDays20'])
        self.assertEqual(report['distributionCoverage']['available'], 18)

    def test_real_zero_is_not_missing(self):
        """真实零量且全覆盖可报告零次，但均量为零不计算相对量。"""
        report = intel.technical_report(synthetic_bars(0), 'synthetic', '2026-11-06')
        self.assertEqual(report['distributionDays20'], 0)
        self.assertEqual(report['distributionCoverage']['status'], 'complete')
        self.assertIsNone(report['relativeVolume20'])

    def test_complete_volume_detects_distribution(self):
        """合成末日放量下跌应保留一次有效事件。"""
        rows = synthetic_bars()
        rows[-1].update(close=99, volume=200)
        report = intel.technical_report(rows, 'synthetic', '2026-11-06')
        self.assertEqual(report['distributionDays20'], 1)
        self.assertEqual(report['distributionDates'], ['2026-11-06'])


class OptionCoverageTests(unittest.TestCase):
    """缺OI时停止集中价排名，已知合约异动注明局部覆盖。"""

    def test_partial_oi_suppresses_rankings(self):
        """缺失合约可能改变排名，不能由已知子集给出确定墙。"""
        chain = intel.parse_options(synthetic_chain(missing=True), 'TEST')
        scope = intel.option_scope(chain['rows'], chain['spot'])
        self.assertIsNone(scope['putCallOI'])
        self.assertIsNone(scope['totals']['callOi'])
        self.assertEqual(scope['upperCallWalls'], [])
        self.assertEqual(scope['lowerPutWalls'], [])
        self.assertEqual(scope['strikes'], [])
        self.assertEqual(scope['oiCoverage']['status'], 'partial')
        self.assertEqual(scope['oiCoverage']['available'], 2)
        self.assertEqual(scope['anomalyCoverage']['status'], 'partial')

    def test_complete_oi_preserves_rankings(self):
        """完整OI可计算确定范围内的排名与P/C。"""
        chain = intel.parse_options(synthetic_chain(), 'TEST')
        scope = intel.option_scope(chain['rows'], 100)
        self.assertEqual(scope['upperCallWalls'][0]['strike'], 110)
        self.assertEqual(scope['putCallOI'], .5)
        self.assertEqual(scope['oiCoverage']['status'], 'complete')

    def test_zero_oi_is_known(self):
        """已知零OI保留零值及零OI异动，不制造除零比值。"""
        chain = intel.parse_options(synthetic_chain(), 'TEST')
        chain['rows'][0]['oi'] = 0
        scope = intel.option_scope(chain['rows'], 100)
        self.assertEqual(scope['missingOI'], 0)
        self.assertEqual(scope['anomalies'][0]['oi'], 0)
        self.assertIsNone(scope['anomalies'][0]['volumeOIRatio'])

    def test_missing_volume_blocks_ratio_and_marks_candidates_partial(self):
        """成交量缺失不能当零并参与完整P/C或全链候选数。"""
        chain = intel.parse_options(synthetic_chain(), 'TEST')
        chain['rows'][0]['volume'] = None
        scope = intel.option_scope(chain['rows'], 100)
        self.assertIsNone(scope['putCallVolume'])
        self.assertEqual(scope['anomalyCoverage']['status'], 'partial')


class OptionTimeTests(unittest.TestCase):
    """固定美东2026-11-06，区分报价时间质量和未知的独立OI日期。"""

    def report_at(self, timestamp):
        """仅向报告注入合成已解析链和固定时钟，不触发网络。"""
        chain = intel.parse_options(synthetic_chain(timestamp), 'TEST')
        with patch.object(intel, 'cached', return_value=chain), \
                patch.object(intel, 'datetime', wraps=datetime) as clock:
            clock.now.return_value = NOW
            return intel.options_report('TEST', 'US', '2026-11-06')

    def test_two_day_old_snapshot_is_stale(self):
        """11月4日快照在11月6日不能因自然日差小于3而available。"""
        report = self.report_at('2026-11-04T16:15:00-05:00')
        self.assertEqual(report['status'], 'stale')
        self.assertEqual(report['snapshotQuality']['status'], 'stale')
        self.assertIsNone(report['oiAsOf'])

    def test_same_day_old_quote_is_stale(self):
        """同日数小时前的报价也不能视为当前快照。"""
        self.assertEqual(self.report_at('2026-11-06T10:00:00-05:00')['status'], 'stale')

    def test_recent_quote_is_available_without_claiming_oi_date(self):
        """15分钟延时仅确认报价快照，独立OI时间仍未知。"""
        report = self.report_at('2026-11-06T21:15:00Z')
        self.assertEqual(report['status'], 'available')
        self.assertIsNone(report['oiAsOf'])
        self.assertEqual(report['snapshotQuality']['ageSeconds'], 900)

    def test_invalid_missing_and_future_times(self):
        """缺失、畸形、无时区和同日未来时间均明确拒绝。"""
        for stamp, quality in [(None, 'missing_timestamp'), ('bad', 'invalid_timestamp'),
                               ('2026-11-06', 'timezone_unknown'),
                               ('2026-11-06T16:15:00', 'timezone_unknown'),
                               ('2026-11-06T16:45:00-05:00', 'future_timestamp'),
                               ('2026-11-07T16:15:00-05:00', 'future_timestamp')]:
            with self.subTest(stamp=stamp):
                report = self.report_at(stamp)
                self.assertEqual(report['status'], 'unavailable')
                self.assertEqual(report['snapshotQuality']['status'], quality)
                self.assertTrue(report['reason'])

    def test_injected_clock_and_historical_requests(self):
        """可注入时钟；历史或未来请求不使用当前链且不访问数据源。"""
        with patch.object(intel, 'cached') as cache:
            for date in ('2026-11-04', '2026-11-07'):
                with self.subTest(date=date):
                    report = intel.options_report('TEST', 'US', date, now=NOW)
                    self.assertEqual(report['status'], 'unavailable')
            cache.assert_not_called()
