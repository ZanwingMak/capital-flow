"""合成账本回归；全部临时数据库位于显式授权目录。"""
import tempfile
import unittest
from pathlib import Path

from portfolio_store import PortfolioStore, LedgerError

TEST_ROOT = Path.home() / '.hermes/cache/scratch/flowdesk-review/portfolio-tests'
TEST_ROOT.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TEST_ROOT)


class PortfolioStoreTests(unittest.TestCase):
    """实际 SQLite 与 Decimal 重放，不替换核心计算。"""

    def setUp(self):
        """每例创建隔离的合成账户。"""
        self.tmp = tempfile.TemporaryDirectory(dir=TEST_ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.store = PortfolioStore(Path(self.tmp.name) / 'private')
        self.account = self.store.create_account('合成账户')['id']

    def add(self, **event):
        """附加一条有来源、日期的合成事实。"""
        return self.store.append(self.account, [{'trade_date': '2026-01-02', 'source': 'synthetic', 'fees': '0', **event}])

    def test_unknown_opening_is_not_zero_cost(self):
        """期初数量可用，成本与估值、收益继续未知。"""
        self.add(kind='opening', symbol='TEST', quantity='3', total_cost=None)
        snapshot = self.store.snapshot(self.account)
        self.assertEqual(snapshot['positions'][0]['quantity'], '3')
        self.assertIsNone(snapshot['positions'][0]['cost'])
        self.assertIsNone(snapshot['unrealized_pnl'])
        self.assertIsNone(snapshot['cash_balance'])
        self.assertEqual(snapshot['revision'], 1)
        self.assertEqual(snapshot['currency'], 'USD')
        self.assertIn('unknown_cost', snapshot['quality'])

    def test_fees_partial_sell_cash_and_split(self):
        """实际买卖费用进入账面成本和净所得，拆股不改变总成本。"""
        self.add(kind='cash_opening', amount='1000', trade_date='2026-01-01')
        self.add(kind='buy', symbol='TEST', quantity='10', price='10', fees='2')
        self.add(kind='sell', symbol='TEST', quantity='4', price='15', fees='1', trade_date='2026-01-03')
        self.add(kind='split', symbol='TEST', quantity='2', trade_date='2026-01-04')
        snap = self.store.snapshot(self.account)
        self.assertEqual(snap['positions'][0]['quantity'], '12')
        self.assertEqual(snap['positions'][0]['cost'], '61.2')
        self.assertEqual(snap['realized_pnl'], '18.2')
        self.assertEqual(snap['fees'], '3')
        self.assertEqual(snap['cash_balance'], '957')
        self.assertIsNone(snap['total_return'])

    def test_unknown_cost_propagates_and_flat_resets_position_cost(self):
        """未知底仓不能因后续买入变成已知，平仓后新买成本可知。"""
        self.add(kind='opening', symbol='TEST', quantity='3')
        self.add(kind='buy', symbol='TEST', quantity='2', price='10', trade_date='2026-01-03')
        self.add(kind='sell', symbol='TEST', quantity='5', price='11', trade_date='2026-01-04')
        self.add(kind='buy', symbol='TEST', quantity='1', price='12', trade_date='2026-01-05')
        snap = self.store.snapshot(self.account)
        self.assertEqual(snap['positions'][0]['cost'], '12')
        self.assertIsNone(snap['realized_pnl'])

    def test_funding_dividend_fee_are_separate(self):
        """入出金不当收益，分红和独立费用单独记录。"""
        for kind, amount in [('deposit', '100'), ('withdrawal', '20'), ('dividend', '5'), ('fee', '2')]:
            self.add(kind=kind, amount=amount, **({'symbol': 'TEST'} if kind == 'dividend' else {}))
        snap = self.store.snapshot(self.account)
        self.assertEqual(snap['net_funding'], '80')
        self.assertEqual(snap['dividend_income'], '5')
        self.assertEqual(snap['ledger_cash_delta'], '83')
        self.assertEqual(snap['realized_pnl'], '0')
        self.assertIsNone(snap['cash_balance'])

    def test_oversell_and_batch_failure_are_atomic(self):
        """末条超卖使整个事务回滚，不悄悄导入第一条。"""
        with self.assertRaises(LedgerError):
            self.store.append(self.account, [
                {'kind': 'buy', 'symbol': 'TEST', 'quantity': '1', 'price': '1', 'fees': '0', 'source': 'synthetic', 'trade_date': '2026-01-02'},
                {'kind': 'sell', 'symbol': 'TEST', 'quantity': '2', 'price': '1', 'fees': '0', 'source': 'synthetic', 'trade_date': '2026-01-03'}])
        self.assertEqual(self.store.history(self.account), [])
        self.assertEqual(self.store.snapshot(self.account)['revision'], 0)

    def test_opening_cutoff_cannot_double_count(self):
        """期初前和当日成交都不能叠加；另一日期期初也拒绝。"""
        self.add(kind='opening', symbol='TEST', quantity='3')
        for date in ('2026-01-01', '2026-01-02'):
            with self.assertRaisesRegex(LedgerError, '期初'):
                self.add(kind='buy', symbol='TEST', quantity='1', price='2', trade_date=date)
        with self.assertRaises(LedgerError):
            self.add(kind='opening', symbol='OTHER', quantity='1', trade_date='2026-01-04')

    def test_same_day_order_requires_explicit_confirmation(self):
        """不以CSV行号或随机ID推断同日买卖顺序。"""
        self.add(kind='buy', symbol='TEST', quantity='3', price='10')
        with self.assertRaisesRegex(LedgerError, '同日顺序'):
            self.add(kind='sell', symbol='TEST', quantity='1', price='20')

    def test_correction_retains_original_and_regroups(self):
        """追加作废和替代事实，原始来源、原文、不可变ID仍在。"""
        self.add(kind='buy', symbol='TEST', quantity='3', price='10', raw={'synthetic': True})
        original = self.store.history(self.account)[0]
        self.add(kind='void', target=original['id'], reason='合成更正', trade_date='2026-01-04')
        self.add(kind='buy', symbol='TEST', quantity='2', price='12', trade_date='2026-01-03')
        self.add(kind='group', symbol='TEST', group='core', trade_date='2026-01-05')
        self.assertEqual(self.store.history(self.account)[0], original)
        self.assertEqual(self.store.snapshot(self.account)['positions'][0]['group'], 'core')
        with self.store.connection(True) as db:
            with self.assertRaises(Exception):
                db.execute('DELETE FROM events')

    def test_execution_identity_correction_in_one_batch_retains_audit(self):
        """同批作废与替代保留真实执行号，费用更正只生效一次。"""
        self.add(kind='buy', symbol='TEST', quantity='1', price='10', external_id='exec-2')
        original = self.store.history(self.account)[0]
        result = self.store.append(self.account, [
            {'kind': 'void', 'target': original['id'], 'reason': '合成费用更正',
             'source': 'synthetic', 'trade_date': '2026-01-03'},
            {**original, 'fees': '1', 'replaces': original['id']}])
        self.assertEqual(result['positions'][0]['cost'], '11')
        self.assertEqual(result['positions'][0]['quantity'], '1')
        self.assertEqual(result['fees'], '1')
        history = self.store.history(self.account)
        self.assertEqual(history[0], original)
        self.assertEqual(history[2]['external_id'], 'exec-2')
        self.assertEqual(history[2]['replaces'], original['id'])
        self.assertNotEqual(history[2]['id'], original['id'])

    def test_execution_identity_replacement_after_previous_void(self):
        """先前已作废也可显式关联原事实替代，随后普通重导仍拒绝。"""
        self.add(kind='buy', symbol='TEST', quantity='1', price='10', external_id='exec-2')
        original = self.store.history(self.account)[0]
        self.add(kind='void', target=original['id'], reason='合成费用更正')
        result = self.add(kind='buy', symbol='TEST', quantity='1', price='10', fees='1',
                          external_id='exec-2', replaces=original['id'])
        self.assertEqual(result['positions'][0]['cost'], '11')
        self.assertEqual(self.store.history(self.account)[2]['replaces'], original['id'])
        with self.assertRaises(LedgerError):
            self.add(kind='buy', symbol='TEST', quantity='1', price='10', external_id='exec-2')

    def test_void_does_not_release_identity_for_unlinked_import(self):
        """作废不会让普通重导占用审计中的身份，必须显式replaces。"""
        self.add(kind='buy', symbol='TEST', quantity='1', price='10', external_id='exec-2')
        original = self.store.history(self.account)[0]
        self.add(kind='void', target=original['id'], reason='合成作废')
        before = self.store.history(self.account)
        with self.assertRaises(LedgerError):
            self.add(kind='buy', symbol='TEST', quantity='1', price='10', external_id='exec-2')
        self.assertEqual(self.store.history(self.account), before)

    def test_replacement_rejects_live_foreign_or_missing_identity(self):
        """替代须关联已作废原文，同源保留执行号，不能冒用其他有效身份。"""
        self.add(kind='buy', symbol='TEST', quantity='1', price='10', external_id='exec-2')
        self.add(kind='buy', symbol='OTHER', quantity='1', price='10', external_id='exec-other')
        original = self.store.history(self.account)[0]
        before = self.store.history(self.account)
        void = {'kind': 'void', 'target': original['id'], 'reason': '合成更正',
                'source': 'synthetic', 'trade_date': '2026-01-03'}
        base = {**original, 'fees': '1', 'replaces': original['id']}
        for changes in ({'external_id': 'exec-other'}, {'external_id': 'invented'},
                        {'source': 'other-source'}, {'replaces': 'missing'}):
            with self.subTest(changes=changes), self.assertRaises(LedgerError):
                self.store.append(self.account, [void, {**base, **changes}])
        with self.assertRaises(LedgerError):
            self.store.append(self.account, [{**base, 'external_id': 'fresh-unlinked'}])
        self.assertEqual(self.store.history(self.account), before)

    def test_replacement_chain_and_secondary_reference_cannot_branch(self):
        """连续更正沿最新事实关联；执行号存在时参考号也不能被其他事实冒用。"""
        self.add(kind='buy', symbol='TEST', quantity='1', price='10', external_id='exec-2', reference='review-2')
        original = self.store.history(self.account)[0]
        for fee in ('1', '2'):
            self.store.append(self.account, [
                {'kind': 'void', 'target': original['id'], 'reason': '合成连续更正',
                 'source': 'synthetic', 'trade_date': '2026-01-03'},
                {**original, 'fees': fee, 'replaces': original['id']}])
            original = self.store.history(self.account)[-1]
        self.assertEqual(self.store.snapshot(self.account)['positions'][0]['cost'], '12')
        with self.assertRaises(LedgerError):
            self.add(kind='buy', symbol='OTHER', quantity='1', price='10', external_id='exec-new', reference='review-2')
        first = self.store.history(self.account)[0]
        with self.assertRaises(LedgerError):
            self.store.append(self.account, [{**first, 'replaces': first['id']}])

    def test_decimal_exact_and_unsupported_values(self):
        """小数计算精确，非有限、负数、期权和非USD明确拒绝。"""
        self.add(kind='buy', symbol='TEST', quantity='0.1', price='0.2', fees='0.01')
        self.assertEqual(self.store.snapshot(self.account)['positions'][0]['cost'], '0.03')
        for fields in ({'price': 'NaN'}, {'quantity': '-1'}, {'currency': 'EUR'}, {'symbol': 'TEST 260101C1'}, {'kind': 'short'}):
            with self.assertRaises(LedgerError):
                self.add(**{'kind': 'buy', 'symbol': 'TEST', 'quantity': '1', 'price': '1', **fields})

    def test_account_isolation_revision_and_readonly(self):
        """账户隔离、乐观锁和只读连接均由实际数据库保证。"""
        other = self.store.create_account('另一个合成账户')['id']
        self.add(kind='buy', symbol='TEST', quantity='1', price='10')
        self.assertEqual(self.store.snapshot(other)['positions'], [])
        with self.assertRaisesRegex(LedgerError, '版本'):
            self.store.append(self.account, [{'kind': 'deposit', 'amount': '1', 'source': 'synthetic', 'trade_date': '2026-01-03'}], expected_revision=0)
        readonly = PortfolioStore(self.store.directory, readonly=True)
        self.assertEqual(readonly.snapshot(self.account)['revision'], 1)
        with self.assertRaises(LedgerError):
            readonly.create_account('不允许')

    def test_private_directory_and_date_precision(self):
        """仓库目录拒绝落库，日期字段没有虚构逐笔时刻。"""
        with self.assertRaises(LedgerError):
            PortfolioStore(Path(__file__).resolve().parents[1] / 'dist/private')
        self.add(kind='buy', symbol='TEST', quantity='1', price='10')
        event = self.store.history(self.account)[0]
        self.assertEqual(event['precision'], 'date')
        self.assertIsNone(event['effective_at'])
        self.assertIsNone(event['available_at'])
        self.assertIsNotNone(event['received_at'])

    def test_inconsistent_explicit_time_and_sequence_is_rejected(self):
        """实际时间与人工顺序矛盾时不能任意选择一个口径。"""
        self.add(kind='buy', symbol='TEST', quantity='1', price='10', sequence=1,
                 effective_at='2026-01-02T10:00:00-05:00')
        with self.assertRaisesRegex(LedgerError, '顺序'):
            self.add(kind='sell', symbol='TEST', quantity='1', price='11', sequence=0,
                     effective_at='2026-01-02T11:00:00-05:00')

    def test_execution_time_must_match_trade_date(self):
        """不能把另一交易日的执行时间塞进旧日期重排账本。"""
        with self.assertRaisesRegex(LedgerError, '日期'):
            self.add(kind='buy', symbol='TEST', quantity='1', price='10',
                     effective_at='2026-01-03T10:00:00-05:00')

    def test_same_day_conflicting_groups_require_order(self):
        """分组也可能受顺序影响，不使用随机ID选择最终分组。"""
        self.add(kind='buy', symbol='TEST', quantity='1', price='10', group='core')
        with self.assertRaisesRegex(LedgerError, '顺序'):
            self.add(kind='buy', symbol='TEST', quantity='1', price='10', group='tactical')

    def test_omitted_fee_is_not_assumed_zero(self):
        """手工API也要求显式费用，不能绕过CSV空白费用限制。"""
        with self.assertRaises(LedgerError):
            self.store.append(self.account, [{'kind': 'buy', 'symbol': 'TEST', 'quantity': '1', 'price': '10',
                'source': 'synthetic', 'trade_date': '2026-01-02'}])

    def test_sql_failure_rolls_back_already_inserted_rows(self):
        """实际SQLite第二笔写入失败时，第一笔及revision一并回滚。"""
        import sqlite3
        with self.store.connection(True) as db:
            db.execute('''CREATE TRIGGER synthetic_failure BEFORE INSERT ON events
                WHEN instr(NEW.data, '"symbol":"FAIL"')>0 BEGIN SELECT RAISE(ABORT,'synthetic failure'); END''')
        with self.assertRaises(sqlite3.Error):
            self.store.append(self.account, [
                {'kind': 'buy', 'symbol': name, 'quantity': '1', 'price': '10', 'fees': '0',
                 'source': 'synthetic', 'trade_date': '2026-01-02'} for name in ('TEST', 'FAIL')])
        self.assertEqual(self.store.history(self.account), [])
        self.assertEqual(self.store.snapshot(self.account)['revision'], 0)

    def test_partial_known_times_cannot_be_reversed_by_sequence(self):
        """部分逐笔时刻已知时，人工顺序也不能颠倒该已知先后关系。"""
        self.add(kind='opening', symbol='TEST', quantity='10', total_cost='100', trade_date='2026-01-01')
        with self.assertRaisesRegex(LedgerError, '顺序'):
            self.store.append(self.account, [
                {'kind': 'buy', 'symbol': 'TEST', 'quantity': '1', 'price': '12', 'fees': '0', 'source': 'synthetic',
                 'trade_date': '2026-01-02', 'effective_at': '2026-01-02T10:00:00-05:00', 'sequence': 2},
                {'kind': 'sell', 'symbol': 'TEST', 'quantity': '1', 'price': '13', 'fees': '0', 'source': 'synthetic',
                 'trade_date': '2026-01-02', 'effective_at': '2026-01-02T11:00:00-05:00', 'sequence': 0},
                {'kind': 'buy', 'symbol': 'TEST', 'quantity': '1', 'price': '14', 'fees': '0', 'source': 'synthetic',
                 'trade_date': '2026-01-02', 'sequence': 1}])
