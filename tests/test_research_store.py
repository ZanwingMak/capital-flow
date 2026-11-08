"""合成事件证据与研究冻结测试，不联网、不读取个人持仓。"""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from portfolio_store import PortfolioStore, LedgerError
from research_store import ResearchStore

TEST_ROOT = Path.home() / '.hermes/cache/scratch/flowdesk-review/portfolio-tests'
TEST_ROOT.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TEST_ROOT)


class ResearchStoreTests(unittest.TestCase):
    """实际SQLite冻结版本，明确区分发布时间与实际首次记录时间。"""

    def setUp(self):
        """创建只有未知成本期初的合成账户。"""
        self.tmp = tempfile.TemporaryDirectory(dir=TEST_ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.store = PortfolioStore(Path(self.tmp.name) / 'private')
        self.account = self.store.create_account('合成研究')['id']
        self.store.append(self.account, [{'kind': 'opening', 'symbol': 'TEST', 'quantity': '3',
                                        'source': 'synthetic', 'trade_date': '2026-01-01'}])
        self.research = ResearchStore(self.store)

    def event(self, **fields):
        """录入明确人工未核实的合成官方发布声称。"""
        return self.research.save_event({'kind': 'macro', 'scope': 'global', 'title': '合成宏观事件',
            'source': 'Synthetic official claim', 'url': 'https://example.invalid/release',
            'published_at': '2026-01-02T10:00:00Z', 'available_at': '2026-01-02T10:01:00Z', **fields})

    def test_event_times_values_and_manual_status(self):
        """数值缺失留null，发布时间、首次可知、实际记录、抓取时间分开。"""
        event = self.event(actual='3.1', expected=None, previous='3.0', revised='2.9', period='2026-01', unit='%')
        self.assertEqual(event['actual'], '3.1')
        self.assertIsNone(event['expected'])
        self.assertEqual(event['verification'], 'manual_unverified')
        self.assertNotEqual(event['first_seen_at'], event['available_at'])
        self.assertIsNotNone(event['captured_at'])
        self.assertEqual(event['version'], 1)

    def save(self, **fields):
        """用当前真实UTC时刻和显式账户版本冻结一条人工研究。"""
        return self.research.save_research({'account': self.account, 'revision': self.store.snapshot(self.account)['revision'],
            'as_of': datetime.now(timezone.utc).isoformat(), 'thesis': '合成论点', 'support': [], 'against': [], **fields})

    def test_freezes_portfolio_and_evidence_versions(self):
        """持仓及证据后改不重写旧研究的JSON和Markdown。"""
        from research_report import export_report
        event = self.event()
        record = self.save(support=[event['id']])
        before = export_report(record, 'markdown')
        self.store.append(self.account, [{'kind': 'buy', 'symbol': 'TEST', 'quantity': '2', 'price': '10', 'fees': '0',
            'source': 'synthetic', 'trade_date': '2026-01-03'}])
        changed = self.research.save_event({**event, 'title': '更新合成标题'}, event['id'], event['version'])
        self.assertEqual(changed['version'], 2)
        self.assertEqual(changed['first_seen_at'], event['first_seen_at'])
        self.assertEqual(self.research.report(record['id']), record)
        self.assertEqual(export_report(self.research.report(record['id']), 'markdown'), before)
        self.assertEqual(record['snapshot']['positions'][0]['quantity'], '3')
        self.assertEqual(record['support'][0]['event']['version'], 1)
        self.assertEqual(self.store.snapshot(self.account)['positions'][0]['quantity'], '5')

    def test_historical_claim_does_not_backdate_first_seen(self):
        """声称一月已发布也不能伪装系统一月已知。"""
        event = self.event(first_seen_at='2026-01-02T10:01:00Z', captured_at='2026-01-02T10:01:00Z')
        record = self.save(as_of='2026-01-04T23:00:00Z', support=[event['id']])
        self.assertFalse(record['support'][0]['eligible'])
        self.assertTrue(any('first_seen_at:after_as_of' == g['reason'] for g in record['evidence_gaps']))

    def test_unknown_and_future_evidence_remain_leads(self):
        """未知或未来发布时间不作为截止日确定事实。"""
        unknown = self.event(published_at=None, available_at=None)
        future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
        later = self.event(published_at=future, available_at=future)
        record = self.save(support=[unknown['id']], against=[later['id']])
        self.assertFalse(record['support'][0]['eligible'])
        self.assertFalse(record['against'][0]['eligible'])
        self.assertIn('published_at:unknown', record['support'][0]['gaps'])
        self.assertIn('published_at:after_as_of', record['against'][0]['gaps'])

    def test_support_and_counter_separate_missing_evidence_explicit(self):
        """支持与反面分离；缺失证据不能默认为没有风险。"""
        support, against = self.event(title='合成支持'), self.event(title='合成反面')
        record = self.save(support=[support['id']], against=[against['id']], group='tactical')
        self.assertTrue(record['support'][0]['eligible'])
        self.assertEqual(record['against'][0]['event']['id'], against['id'])
        missing = self.save()
        self.assertIn({'reason': 'no_counter_evidence'}, missing['evidence_gaps'])
        with self.assertRaises(LedgerError):
            self.save(support=[support['id']], against=[support['id']])
        with self.assertRaises(LedgerError):
            self.save(support=['missing-synthetic-id'])

    def test_invalid_urls_and_times(self):
        """URL只存HTTP(S)，时间带时区且不能倒置。"""
        for url in ('file:///etc/passwd', 'javascript:alert(1)', 'https://user:secret@example.invalid', 'https://example.invalid/\nsecret'):
            with self.assertRaises(LedgerError):
                self.event(url=url)
        for fields in ({'published_at': '2026-01-02T10:00:00'}, {'available_at': '2026-01-01T10:00:00Z'}, {'actual': 'NaN'}):
            with self.assertRaises(LedgerError):
                self.event(**fields)

    def test_research_revision_and_future_cutoff_reject(self):
        """旧持仓版本和未来截止研究不能静默保存。"""
        with self.assertRaisesRegex(LedgerError, '版本'):
            self.save(revision=0)
        with self.assertRaisesRegex(LedgerError, '未来'):
            self.save(as_of=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())

    def test_markdown_escaping_and_unknown_cost(self):
        """恶意Markdown及HTML按文本导出，成本未知保留未知。"""
        from research_report import export_report
        event = self.event(title='[fake](javascript:alert(1)) <script>x</script>', notes='![img](https://example.invalid)\n# title')
        record = self.save(support=[event['id']], thesis='| <b>synthetic</b> [x](evil)')
        markdown = export_report(record, 'markdown')
        self.assertIn('未知', markdown)
        self.assertNotIn('<script>', markdown)
        self.assertNotIn('![img]', markdown)
        self.assertIn('\\[fake\\]', markdown)
        self.assertEqual(__import__('json').loads(export_report(record))['snapshot']['positions'][0]['cost'], None)
        self.assertLess(markdown.index('数据与证据缺口'), markdown.index('判断（人工论点）'))

    def test_markdown_source_url_remains_clickable_and_copyable(self):
        """来源URL保留域名、连字符和查询参数，不经通用正文反斜杠转义。"""
        from research_report import export_report
        url = 'https://example.com/synthetic-release?x=1&y=2#section-1'
        event = self.event(url=url)
        markdown = export_report(self.save(support=[event['id']]), 'markdown')
        self.assertIn('URL：<' + url + '>', markdown)
        self.assertNotIn('example\\.com', markdown)

    def test_markdown_url_delimiters_cannot_inject_html_or_links(self):
        """URL内尖括号与引号编码，标题和正文仍按不可信文本转义。"""
        from research_report import export_report
        url = 'https://example.com/synthetic-(a)?q="><script>x</script>#end'
        event = self.event(url=url, title='[evil](javascript:alert(1))', notes='<img src=x onerror=alert(1)>')
        markdown = export_report(self.save(support=[event['id']]), 'markdown')
        self.assertIn('<https://example.com/synthetic-(a)?q=%22%3E%3Cscript%3Ex%3C/script%3E#end>', markdown)
        self.assertNotIn('<script>', markdown)
        self.assertNotIn('<img', markdown)
        self.assertNotIn('[evil](', markdown)

    def test_unsafe_source_urls_rejected_on_save_and_export(self):
        """保存和导出都验证协议、凭证及解析歧义，旧内容也不能绕过。"""
        from research_report import export_report
        valid = self.event()
        record = self.save(support=[valid['id']])
        for url in ('javascript:alert(1)', 'data:text/html,evil', '//example.com/path',
                    'https://user:secret@example.com', 'https://example.com\\@evil.invalid',
                    'https://exa"mple.com/path', 'https://example.com/\tbad', ' https://example.com'):
            with self.subTest(url=url):
                with self.assertRaises(LedgerError):
                    self.event(url=url)
                record['support'][0]['event']['url'] = url
                with self.assertRaises(LedgerError):
                    export_report(record, 'markdown')

    def test_old_evidence_versions_remain_immutable(self):
        """更新冲突拒绝，已存证据与研究不允许SQL修改。"""
        event = self.event()
        self.research.save_event({**event, 'actual': '4'}, event['id'], 1)
        with self.assertRaises(LedgerError):
            self.research.save_event(event, event['id'], 1)
        self.assertEqual(self.research.events()[0]['actual'], '4')
        record = self.save()
        with self.store.connection(True) as db:
            with self.assertRaises(Exception):
                db.execute('UPDATE evidence SET version=3')
            with self.assertRaises(Exception):
                db.execute('DELETE FROM research_records WHERE id=?', (record['id'],))

    def test_cutoff_uses_known_version_and_current_day_uncertainty(self):
        """按截止选择当时已有证据版本，日期精度当日成交不虚构时刻。"""
        event = self.event()
        cutoff = datetime.now(timezone.utc).isoformat()
        self.research.save_event({**event, 'actual': '9'}, event['id'], 1)
        record = self.save(as_of=cutoff, support=[event['id']])
        self.assertEqual(record['support'][0]['event']['version'], 1)
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo('America/New_York')).date().isoformat()
        self.store.append(self.account, [{'kind': 'buy', 'symbol': 'TEST', 'quantity': '1', 'price': '10', 'fees': '0',
            'source': 'synthetic', 'trade_date': today}])
        current = self.save()
        self.assertEqual(current['snapshot']['positions'][0]['quantity'], '3')
        self.assertIn('intraday_or_future_events_excluded', current['snapshot']['quality'])

    def test_cutoff_dependency_gap_does_not_oversell_or_hide_independent_position(self):
        """日期买入与精确卖出有依赖时保留缺口，其他确定持仓仍可研究。"""
        self.account = self.store.create_account('合成依赖缺口')['id']
        self.store.append(self.account, [
            {'kind': 'buy', 'symbol': 'OTHER', 'quantity': '3', 'price': '3', 'fees': '0',
             'source': 'synthetic', 'trade_date': '2026-01-01'},
            {'kind': 'buy', 'symbol': 'TEST', 'quantity': '2', 'price': '10', 'fees': '0',
             'source': 'synthetic', 'trade_date': '2026-01-02', 'sequence': 0},
            {'kind': 'sell', 'symbol': 'TEST', 'quantity': '1', 'price': '12', 'fees': '0',
             'source': 'synthetic', 'trade_date': '2026-01-02', 'sequence': 1,
             'effective_at': '2026-01-02T11:00:00-05:00'}])
        full = {p['symbol']: p for p in self.store.snapshot(self.account)['positions']}
        self.assertEqual((full['TEST']['quantity'], full['TEST']['cost']), ('1', '10'))
        record = self.save(as_of='2026-01-02T17:00:00Z')
        snap = record['snapshot']
        positions = {p['symbol']: p for p in snap['positions']}
        self.assertEqual((positions['OTHER']['quantity'], positions['OTHER']['cost']), ('3', '9'))
        self.assertIsNone(positions['TEST']['quantity'])
        self.assertIsNone(positions['TEST']['cost'])
        self.assertEqual(positions['TEST']['quantity_status'], 'known_partial')
        self.assertEqual(positions['TEST']['known_partial_quantity'], '0')
        gap = snap['position_gaps'][0]
        history = self.store.history(self.account)
        self.assertEqual(gap['symbol'], 'TEST')
        self.assertEqual(gap['uncertain_event_ids'], [history[1]['id']])
        self.assertEqual(gap['dependent_event_ids'], [history[2]['id']])
        self.assertIsNone(snap['ledger_cash_delta'])
        self.assertIsNone(snap['realized_pnl'])
        self.assertEqual(snap['totals_status'], 'known_partial')
        from research_report import export_report
        markdown = export_report(record, 'markdown')
        self.assertIn('截止总量未知', markdown)
        self.assertIn(history[2]['id'], markdown)
        self.assertEqual(self.research.report(record['id']), record)

    def test_cutoff_known_partial_is_explicit_and_full_day_recovers(self):
        """既有数量只是已知部分，不能把依赖卖出扣掉冒充截止总量。"""
        self.store.append(self.account, [
            {'kind': 'buy', 'symbol': 'TEST', 'quantity': '2', 'price': '10', 'fees': '0',
             'source': 'synthetic', 'trade_date': '2026-01-02', 'sequence': 0},
            {'kind': 'sell', 'symbol': 'TEST', 'quantity': '1', 'price': '12', 'fees': '0',
             'source': 'synthetic', 'trade_date': '2026-01-02', 'sequence': 1,
             'effective_at': '2026-01-02T11:00:00-05:00'}])
        partial = self.save(as_of='2026-01-02T17:00:00Z')['snapshot']
        p = partial['positions'][0]
        self.assertEqual(p['quantity'], '3')
        self.assertEqual(p['quantity_status'], 'known_partial')
        self.assertEqual(p['known_partial_quantity'], '3')
        complete = self.save(as_of='2026-01-03T06:00:00Z')['snapshot']
        self.assertEqual(complete['positions'][0]['quantity'], '4')
        self.assertEqual(complete['position_gaps'], [])
        self.assertEqual(complete['totals_status'], 'complete')

    def test_known_future_instant_does_not_make_position_uncertain(self):
        """明确在截止后的事实只截断，不污染此前可确定的持仓。"""
        self.store.append(self.account, [{'kind': 'buy', 'symbol': 'TEST', 'quantity': '2',
            'price': '10', 'fees': '0', 'source': 'synthetic', 'trade_date': '2026-01-02',
            'effective_at': '2026-01-02T14:00:00-05:00'}])
        snap = self.save(as_of='2026-01-02T17:00:00Z')['snapshot']
        self.assertEqual(snap['positions'][0]['quantity'], '3')
        self.assertEqual(snap['position_gaps'], [])
        self.assertEqual(snap['totals_status'], 'complete')

    def test_readonly_cli_never_creates_or_changes_files(self):
        """实际子进程CLI读取冻结内容；缺库不建目录，读后文件字节不变。"""
        import json
        import os
        import subprocess
        import sys
        record = self.save()
        before = self.store.path.read_bytes()
        env = {**os.environ, 'TMPDIR': str(TEST_ROOT), 'PYTHONDONTWRITEBYTECODE': '1'}
        args = [sys.executable, 'private_cli.py', '--directory', str(self.store.directory)]
        output = subprocess.run(args + ['export-report', '--id', record['id']], capture_output=True, text=True, env=env, check=True)
        self.assertEqual(json.loads(output.stdout)['id'], record['id'])
        portfolio = subprocess.run(args + ['portfolio', '--account', self.account], capture_output=True, text=True, env=env, check=True)
        self.assertEqual(json.loads(portfolio.stdout)['positions'][0]['quantity'], '3')
        self.assertEqual(before, self.store.path.read_bytes())
        absent = Path(self.tmp.name) / 'absent'
        failed = subprocess.run([sys.executable, 'private_cli.py', '--directory', str(absent), 'accounts'], capture_output=True, text=True, env=env)
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse(absent.exists())
        self.assertNotIn(str(absent), failed.stderr)
