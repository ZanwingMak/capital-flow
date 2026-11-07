"""合成资金事件、价格和分钟档案；所有文件只写测试临时目录。"""
import copy
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import research


def synthetic_calendar(count=80):
    """生成明确为合成的工作日日历，不代表真实交易所节假日安排。"""
    days, current = [], date(2026, 7, 1)
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def synthetic_record(calendar):
    """生成合成资金与前复权占位价格；第10和15个窗口末日为大额事件。"""
    return {'prices': [{'time_key': day+' 00:00:00', 'close': 100+i, 'last_close': 99+i,
                        'name': '合成标的'} for i, day in enumerate(calendar)],
            'flow': [{'capital_flow_item_time': day, 'big_in_flow': (-800 if i == 10 else -1000 if i == 15 else -100)*10000,
                      'super_in_flow': 0} for i, day in enumerate(calendar)]}


def write_synthetic_tail(root, day, amount, missing=False):
    """把合成完整累计分钟窗口写入隔离目录，可删除中间分钟模拟缺失。"""
    end = datetime.fromisoformat(day+'T16:00')
    points = [{'time': (end-timedelta(minutes=20-i)).strftime('%Y-%m-%d %H:%M:%S'),
               'main': amount*i/20} for i in range(21)]
    if missing:
        points.pop(15)
    path = root / 'US/TEST' / (day+'.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'synthetic': True, 'source': 'futu-opend', 'date': day,
                                'closeTime': '16:00', 'points': points}), encoding='utf-8')


class ResearchTests(unittest.TestCase):
    """从真实研究构建入口验证时间边界和尾盘阈值。"""

    def setUp(self):
        """每个测试使用独立合成档案目录，绝不读取项目.data。"""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.patch = patch.object(research, 'DATA', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.calendar = synthetic_calendar()
        self.record = synthetic_record(self.calendar)

    def build(self, **kwargs):
        """以默认参数调用生产构建函数，允许逐项覆盖合成场景。"""
        params = dict(record=self.record, calendar=self.calendar, market='US', symbol='TEST',
                      as_of=self.calendar[15], lookback=20, span=1, percentile=90,
                      minimum=500, days=20, kind='daily', direction='out')
        params.update(kwargs)
        return research.build_research(**params)

    def test_default_is_explicit_retrospective(self):
        """默认旧调用保留事后路径，但必须明确声明可使用截至日之后价格。"""
        report = self.build()
        self.assertTrue(any(row['date'] > report['asOf'] for event in report['events'] for row in event['path']))
        self.assertEqual(report['mode'], 'retrospective')
        self.assertIn('事后复盘', report['timeSemantics'])

    def test_strict_paths_and_summary_never_exceed_as_of(self):
        """严格模式只用截至日内价格，未满期不进入统计分母。"""
        report = self.build(mode='strict-as-of')
        self.assertEqual(report['mode'], 'strict-as-of')
        self.assertEqual(report['outcomeThrough'], report['asOf'])
        self.assertFalse(report['pointInTimeVerified'])
        self.assertTrue(report['events'])
        for event in report['events'] + report['recentAlerts']:
            self.assertTrue(all(row['date'] <= report['asOf'] for row in event['path']))
            self.assertFalse(event['complete'])
        self.assertEqual(report['summary'][4]['samples'], 1)
        self.assertEqual(report['summary'][5]['samples'], 0)
        self.assertIsNone(report['summary'][5]['average'])

    def test_future_prices_cannot_change_strict_statistics(self):
        """合成未来价格再极端也不改变严格模式路径或统计。"""
        first = self.build(mode='strict-as-of')
        changed = copy.deepcopy(self.record)
        for row in changed['prices'][16:]:
            row['close'] = 999999
        second = self.build(record=changed, mode='strict-as-of')
        self.assertEqual(first['events'], second['events'])
        self.assertEqual(first['summary'], second['summary'])

    def test_strict_keeps_missing_price_gaps(self):
        """缺价交易日保留原偏移，不能压缩为下一根有效K线。"""
        changed = copy.deepcopy(self.record)
        changed['prices'].pop(12)
        report = self.build(record=changed, mode='strict-as-of')
        event = next(event for event in report['events'] if event['date'] == self.calendar[10])
        self.assertEqual(event['path'][2]['date'], self.calendar[12])
        self.assertIsNone(event['path'][2]['cumulative'])
        self.assertEqual(report['summary'][1]['samples'], 0)

    def test_minute_metadata_excludes_future_archives(self):
        """截至日之后的分钟文件不读取、不出现在覆盖日期和最新窗口。"""
        for i in (15, 16):
            write_synthetic_tail(self.root, self.calendar[i], -100)
        original = research.read_minutes
        with patch.object(research, 'read_minutes', wraps=original) as read:
            report = self.build()
        self.assertEqual(report['minuteDates'], [self.calendar[15]])
        self.assertEqual(report['tailLatest']['date'], self.calendar[15])
        self.assertTrue(all(call.args[0].stem <= report['asOf'] for call in read.call_args_list))

    def test_invalid_mode_is_rejected(self):
        """直接构建调用同样拒绝含混口径。"""
        with self.assertRaisesRegex(ValueError, 'mode|模式|口径'):
            self.build(mode='unknown')

    def test_tail_below_displayed_threshold_is_not_an_event(self):
        """复现尾盘-1却显示阈值500仍入选的真实筛选错误。"""
        for i in range(11):
            write_synthetic_tail(self.root, self.calendar[i], -500 if i < 10 else -1)
        report = self.build(as_of=self.calendar[10], kind='tail20', minimum=0)
        self.assertEqual(report['events'], [])

    def test_tail_insufficient_baseline_cannot_create_events(self):
        """只有9个此前同向完整窗口时，即使金额很大也不制造异常。"""
        for i in range(10):
            write_synthetic_tail(self.root, self.calendar[i], -100 if i < 9 else -10000)
        self.assertEqual(self.build(as_of=self.calendar[9], kind='tail20', minimum=0)['events'], [])

    def test_tail_quantile_minimum_and_direction(self):
        """双向基线分开计算，事件须达到金额与分位数两者中的较大值。"""
        for i in range(22):
            amount = -100 if i < 10 else 1000 if i < 20 else -150 if i == 20 else 150
            write_synthetic_tail(self.root, self.calendar[i], amount)
        report = self.build(as_of=self.calendar[21], kind='tail20', direction='both', minimum=120)
        self.assertEqual([event['date'] for event in report['events']], [self.calendar[20]])
        event = report['events'][0]
        self.assertEqual(event['threshold'], 120)
        self.assertEqual(event['baselineSamples'], 10)
        self.assertGreaterEqual(abs(event['main']), event['threshold'])

    def test_tail_missing_minutes_not_in_baseline(self):
        """缺中间分钟的窗口不能凑足10个基线样本。"""
        for i in range(11):
            write_synthetic_tail(self.root, self.calendar[i], -100 if i < 10 else -10000, missing=i == 5)
        self.assertEqual(self.build(as_of=self.calendar[10], kind='tail10', minimum=0)['events'], [])

    def test_tail_percentile_changes_selection(self):
        """实际分位数参数影响入选，不仅改变展示标签。"""
        for i in range(11):
            write_synthetic_tail(self.root, self.calendar[i], -(i+1)*100 if i < 10 else -600)
        lower = self.build(as_of=self.calendar[10], kind='tail20', minimum=0, percentile=50)
        upper = self.build(as_of=self.calendar[10], kind='tail20', minimum=0, percentile=90)
        self.assertEqual(len(lower['events']), 1)
        self.assertEqual(lower['events'][0]['threshold'], 550)
        self.assertEqual(upper['events'], [])

    def test_tail_baseline_is_limited_to_previous_60_windows(self):
        """很早的完整窗口不能让近期基线不足的日期产生异常。"""
        for i in list(range(10))+[70]:
            write_synthetic_tail(self.root, self.calendar[i], -100 if i < 10 else -10000)
        self.assertEqual(self.build(as_of=self.calendar[70], kind='tail20', minimum=0)['events'], [])
