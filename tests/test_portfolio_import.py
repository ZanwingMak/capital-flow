"""Schwab合成表头与原文；不访问任何真实券商文件。"""
import tempfile
import unittest
from pathlib import Path
from portfolio_store import PortfolioStore, LedgerError
from portfolio_import import parse_schwab, ImportService

TEST_ROOT = Path.home() / '.hermes/cache/scratch/flowdesk-review/portfolio-tests'
TEST_ROOT.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TEST_ROOT)
HEADER = 'Date,Action,Symbol,Description,Quantity,Price,Fees & Comm,Amount'


def csv_text(*rows, header=HEADER):
    """拼接明确标记的合成 CSV。"""
    return header + '\n' + '\n'.join(rows)


class ImportTests(unittest.TestCase):
    """预览、完整校验与事务提交使用同一真实账本。"""

    def setUp(self):
        """创建隔离存储和无真实持仓的账户。"""
        self.tmp = tempfile.TemporaryDirectory(dir=TEST_ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.store = PortfolioStore(Path(self.tmp.name) / 'private')
        self.account = self.store.create_account('合成CSV')['id']
        self.service = ImportService(self.store)

    def test_decimal_thousands_and_date_only(self):
        """美元千分位不丢精度；只有日期时不伪造执行时间。"""
        row = parse_schwab(csv_text('01/02/2026,Buy,TEST,Synthetic,2,"$1,000.10",$0.20,"-$2,000.40"'))[0]
        self.assertEqual(row['issues'], [])
        self.assertEqual(row['event']['price'], '1000.1')
        self.assertEqual(row['event']['trade_date'], '2026-01-02')
        self.assertIsNone(row['event']['effective_at'])
        self.assertEqual(row['line'], 2)
        self.assertIn('Synthetic', row['raw'])

    def confirm(self, preview):
        """确认服务器保存的预览标识，不从客户端重传成交正文。"""
        return self.service.commit(self.account, preview['preview_id'], preview['payload_id'])

    def test_reverse_dated_trades_sorted_by_date(self):
        """逆序导出的跨日买卖按实际日期重放，费用口径不变。"""
        preview = self.service.preview(self.account, csv_text(
            '01/03/2026,Sell,TEST,Synthetic,1,12,1,11', '01/02/2026,Buy,TEST,Synthetic,2,10,1,-21'))
        self.assertTrue(preview['can_commit'])
        self.assertEqual(self.confirm(preview)['positions'][0]['cost'], '10.5')
        self.assertEqual(self.store.history(self.account)[0]['raw'], '01/03/2026,Sell,TEST,Synthetic,1,12,1,11\n')

    def test_same_day_mixed_needs_human_sequence(self):
        """只有日期且同日买卖时不自动买入优先，须明确人工顺序。"""
        content = csv_text('01/02/2026,Sell,TEST,Synthetic,1,12,0,12', '01/02/2026,Buy,TEST,Synthetic,2,10,0,-20')
        preview = self.service.preview(self.account, content)
        self.assertFalse(preview['can_commit'])
        self.assertIn('同日顺序', ' '.join(preview['errors']))
        preview = self.service.preview(self.account, content, [{'row': 0, 'sequence': 2}, {'row': 1, 'sequence': 1}])
        self.assertTrue(preview['can_commit'])
        self.assertEqual(self.confirm(preview)['positions'][0]['quantity'], '1')

    def test_oversell_matches_preview_and_commit_validation(self):
        """预览即拒绝超卖，不能先标可导入再在确认时失败。"""
        preview = self.service.preview(self.account, csv_text('01/02/2026,Sell,TEST,Synthetic,1,12,0,12'))
        self.assertFalse(preview['can_commit'])
        self.assertEqual(self.store.history(self.account), [])

    def test_identical_no_id_trades_are_not_collapsed(self):
        """真实同价同量分笔需要分别确认身份，最终保存两笔。"""
        row = '01/02/2026,Buy,TEST,Synthetic,1,10,0,-10'
        content = csv_text(row, row)
        preview = self.service.preview(self.account, content)
        self.assertFalse(preview['can_commit'])
        self.assertEqual(len(preview['rows']), 2)
        preview = self.service.preview(self.account, content, [
            {'row': 0, 'reference': 'synthetic-fill-a', 'distinct': True},
            {'row': 1, 'reference': 'synthetic-fill-b', 'distinct': True}])
        self.assertEqual(self.confirm(preview)['positions'][0]['quantity'], '2')
        self.assertEqual(len(self.store.history(self.account)), 2)

    def test_reupload_and_reordering_still_suspect(self):
        """重上传和重排行号不生成新去重身份。"""
        a, b = '01/02/2026,Buy,TEST,Synthetic,1,10,0,-10', '01/03/2026,Buy,TEST,Synthetic,2,11,0,-22'
        self.confirm(self.service.preview(self.account, csv_text(a, b)))
        preview = self.service.preview(self.account, csv_text(b, a))
        self.assertFalse(preview['can_commit'])
        self.assertTrue(all(row['needs_reference'] for row in preview['rows']))
        self.assertEqual(self.store.snapshot(self.account)['revision'], 1)

    def test_execution_id_is_explicit_and_order_id_not_execution(self):
        """明确执行号可用于拒绝重复，委托号不能吞掉分笔。"""
        row = '01/02/2026,Buy,TEST,Synthetic,1,10,0,-10'
        content = csv_text(row + ',exec-1', header=HEADER + ',Execution ID')
        self.confirm(self.service.preview(self.account, content))
        preview = self.service.preview(self.account, content)
        self.assertFalse(preview['can_commit'])
        self.assertIn('执行ID', str(preview['rows'][0]['issues']))
        parsed = parse_schwab(csv_text(row + ',order-1', header=HEADER + ',Order ID'))[0]
        self.assertNotIn('external_id', parsed['event'])

    def test_new_execution_id_matching_existing_unidentified_fact_requires_review(self):
        """后补执行号不能把已入账的无编号事实自动翻倍。"""
        row = '01/02/2026,Buy,TEST,Synthetic,1,10,0,-10'
        self.confirm(self.service.preview(self.account, csv_text(row)))
        content = csv_text(row + ',exec-1', header=HEADER + ',Execution ID')
        preview = self.service.preview(self.account, content)
        self.assertFalse(preview['can_commit'])
        self.assertTrue(preview['rows'][0]['needs_reference'])
        self.assertIsNone(preview['preview_id'])
        self.assertEqual(self.store.snapshot(self.account)['positions'][0]['quantity'], '1')
        self.assertEqual(self.store.snapshot(self.account)['revision'], 1)

    def test_distinct_confirmation_keeps_real_execution_id(self):
        """核实为独立分笔后只追加参考号，不捏造或覆盖真实执行号。"""
        row = '01/02/2026,Buy,TEST,Synthetic,1,10,0,-10'
        self.confirm(self.service.preview(self.account, csv_text(row)))
        content = csv_text(row + ',exec-1', header=HEADER + ',Execution ID')
        preview = self.service.preview(self.account, content, [
            {'row': 0, 'reference': 'synthetic-reviewed-separate-fill', 'distinct': True}])
        self.assertTrue(preview['rows'][0]['needs_reference'])
        self.assertTrue(preview['can_commit'])
        self.assertEqual(self.confirm(preview)['positions'][0]['quantity'], '2')
        self.assertEqual(self.store.history(self.account)[1]['external_id'], 'exec-1')
        self.assertEqual(self.store.history(self.account)[1]['reference'], 'synthetic-reviewed-separate-fill')
        self.assertFalse(self.service.preview(self.account, content)['can_commit'])

    def test_mixed_identified_and_unidentified_same_batch_requires_review(self):
        """同批缺编号的同事实也不能被新增执行号绕过歧义提示。"""
        row = '01/02/2026,Buy,TEST,Synthetic,1,10,0,-10'
        preview = self.service.preview(self.account, csv_text(row + ',', row + ',exec-1',
                                                          header=HEADER + ',Execution ID'))
        self.assertFalse(preview['can_commit'])
        self.assertTrue(all(r['needs_reference'] for r in preview['rows']))

    def test_bad_rows_preserve_raw_and_are_never_silently_imported(self):
        """as-of、金额不符、未知动作和期权原文均保留。"""
        content = csv_text('01/02/2026 as of 01/01/2026,Buy,TEST,Synthetic,1,10,0,-10',
            '01/02/2026,Buy,TEST,Synthetic,1,10,0,-9',
            '01/02/2026,Reinvest Shares,TEST,Synthetic,1,10,0,-10',
            '01/02/2026,Buy,TEST 260101C10,Synthetic,1,10,0,-10')
        rows = parse_schwab(content)
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(r['issues'] and r['raw'] and r['line'] >= 2 for r in rows))
        preview = self.service.preview(self.account, content, [{'row': 0}])
        self.assertFalse(preview['can_commit'])

    def test_cash_sign_and_unclear_transfer(self):
        """现金只接受明确映射与符号；拆股数量不猜比例。"""
        rows = parse_schwab(csv_text('01/02/2026,Deposit,,Synthetic,,,,100',
            '01/03/2026,Withdrawal,,Synthetic,,,,-20',
            '01/04/2026,Cash Dividend,TEST,Synthetic,,,,2',
            '01/05/2026,MoneyLink Transfer,,Synthetic,,,,100',
            '01/06/2026,Stock Split,TEST,Synthetic,2,,,0'))
        self.assertEqual([r['event']['kind'] for r in rows[:3]], ['deposit', 'withdrawal', 'dividend'])
        self.assertTrue(all(r['issues'] for r in rows[3:]))

    def test_payload_revision_expiry_and_single_use(self):
        """改包、旧版本、过期、重复确认均拒绝，整批不部分成功。"""
        content = csv_text('01/02/2026,Buy,TEST,Synthetic,1,10,0,-10')
        preview = self.service.preview(self.account, content)
        with self.assertRaisesRegex(LedgerError, '标识'):
            self.service.commit(self.account, preview['preview_id'], 'changed')
        self.store.append(self.account, [{'kind': 'deposit', 'amount': '1', 'source': 'synthetic', 'trade_date': '2026-01-01'}])
        with self.assertRaisesRegex(LedgerError, '版本'):
            self.confirm(preview)
        fresh = self.service.preview(self.account, content)
        self.confirm(fresh)
        with self.assertRaises(LedgerError):
            self.confirm(fresh)
        other = self.store.create_account('过期合成')['id']
        expired = self.service.preview(other, content)
        with self.store.connection(True) as db:
            db.execute("UPDATE previews SET expires_at='2000-01-01' WHERE id=?", (expired['preview_id'],))
        with self.assertRaisesRegex(LedgerError, '过期'):
            self.service.commit(other, expired['preview_id'], expired['payload_id'])
        self.assertEqual(self.store.snapshot(other)['revision'], 0)

    def test_selection_and_csv_structural_limits(self):
        """格式和重复选择不生成可提交预览。"""
        content = csv_text('01/02/2026,Buy,TEST,Synthetic,1,10,0,-10')
        for selections in ([{'row': 0}, {'row': 0}], [{'row': -1}], [{'row': 0, 'sequence': '1'}]):
            with self.assertRaises(LedgerError):
                self.service.preview(self.account, content, selections)
        for bad in ('bad header\nvalue', HEADER + '\n"unterminated'):
            with self.assertRaises(LedgerError):
                parse_schwab(bad)

    def test_buy_without_fee_value_requires_confirmation(self):
        """费用空白不当零，以待核实行展示。"""
        rows = parse_schwab(csv_text('01/02/2026,Buy,TEST,Synthetic,1,10,,-10'))
        self.assertTrue(rows[0]['issues'])

    def test_zero_quantity_cash_description_of_option_rejected(self):
        """明确期权描述不可因代码似正股而被错误接受。"""
        row = parse_schwab(csv_text('01/02/2026,Buy,TEST,OPTION CALL Synthetic,1,10,0,-10'))[0]
        self.assertTrue(row['issues'])

    def test_optional_currency_never_silently_overridden(self):
        """CSV明确非美元时不能由导入器伪装USD。"""
        row = parse_schwab(csv_text('01/02/2026,Buy,TEST,Synthetic,1,10,0,-10,EUR', header=HEADER+',Currency'))[0]
        self.assertTrue(row['issues'])

    def test_repreview_returns_frozen_reference_and_sequence(self):
        """再次预览必须展示用户确认的身份与顺序，不丢掉确认内容。"""
        row = '01/02/2026,Buy,TEST,Synthetic,1,10,0,-10'
        preview = self.service.preview(self.account, csv_text(row, row), [
            {'row': 0, 'reference': 'synthetic-a', 'distinct': True, 'sequence': 1},
            {'row': 1, 'reference': 'synthetic-b', 'distinct': True, 'sequence': 2}])
        self.assertTrue(preview['can_commit'])
        self.assertEqual(preview['rows'][0]['event']['reference'], 'synthetic-a')
        self.assertEqual(preview['rows'][0]['event']['sequence'], 1)

    def test_parallel_confirm_has_exactly_one_commit(self):
        """真实并发SQLite事务保证单次确认，不因双击增加两份持仓。"""
        from concurrent.futures import ThreadPoolExecutor
        preview = self.service.preview(self.account, csv_text('01/02/2026,Buy,TEST,Synthetic,1,10,0,-10'))

        def confirm_once():
            """把预期的第二次拒绝作为确定结果收集。"""
            try:
                self.confirm(preview)
                return 'committed'
            except LedgerError:
                return 'rejected'

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: confirm_once(), range(2)))
        self.assertCountEqual(results, ['committed', 'rejected'])
        self.assertEqual(self.store.snapshot(self.account)['positions'][0]['quantity'], '1')

    def test_parent_acceptance_fixture_from_unknown_opening(self):
        """直接验证父代理浏览器验收使用的合成文件及其预期数值。"""
        self.store.append(self.account, [
            {'kind': 'opening', 'symbol': 'TEST', 'quantity': '3', 'source': 'synthetic', 'trade_date': '2026-01-01'},
            {'kind': 'cash_opening', 'amount': '1000', 'source': 'synthetic', 'trade_date': '2026-01-01'}])
        content = (Path(__file__).parent / 'fixtures/portfolio/schwab-synthetic.csv').read_text()
        result = self.confirm(self.service.preview(self.account, content))
        self.assertEqual(result['positions'][0]['quantity'], '4')
        self.assertIsNone(result['positions'][0]['cost'])
        self.assertIsNone(result['realized_pnl'])
        self.assertEqual(result['cash_balance'], '992.2')
        self.assertEqual(result['ledger_cash_delta'], '-7.8')
        self.assertEqual(result['fees'], '0.3')
        self.assertEqual(result['dividend_income'], '0.5')

    def test_selected_subset_keeps_unresolved_original_in_private_preview(self):
        """确认明确记录后，取消选择的待核实原文仍随冻结预览私有存档。"""
        import json
        content = csv_text('01/02/2026,Buy,TEST,Synthetic,1,10,0,-10',
                           '01/03/2026,Unknown Action,TEST,Synthetic pending,1,10,0,-10')
        preview = self.service.preview(self.account, content, [{'row': 0}])
        self.assertTrue(preview['can_commit'])
        self.confirm(preview)
        with self.store.connection() as db:
            frozen = json.loads(db.execute('SELECT payload FROM previews WHERE id=?', (preview['preview_id'],)).fetchone()[0])
        self.assertEqual(frozen['original_csv'], content)
        self.assertTrue(frozen['rows'][1]['issues'])
        self.assertIn('Synthetic pending', frozen['rows'][1]['raw'])
