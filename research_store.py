"""人工事件的不可变版本、持仓与证据冻结研究；不抓取URL或调用模型。"""
import json
from datetime import datetime
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo
from private_common import LedgerError, canonical, decimal, label, now, stamp, symbol, text_number
from portfolio_ledger import ordered_active, replay

SCHEMA = '''
CREATE TABLE IF NOT EXISTS evidence(id TEXT NOT NULL, version INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY(id,version));
CREATE TABLE IF NOT EXISTS research_records(id TEXT PRIMARY KEY, account TEXT NOT NULL REFERENCES accounts(id), data TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS evidence_no_update BEFORE UPDATE ON evidence BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS evidence_no_delete BEFORE DELETE ON evidence BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS research_no_update BEFORE UPDATE ON research_records BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS research_no_delete BEFORE DELETE ON research_records BEGIN SELECT RAISE(ABORT,'immutable'); END;
'''


def event_url(value):
    """只保存合法HTTP(S)来源URL，不发网络请求，不接受内嵌凭证。"""
    original = value
    value = label(value, 2048)
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in original)
                or '\\' in value or any(c in parsed.netloc for c in '<>"')):
            raise ValueError
        _ = parsed.port
        return value
    except ValueError:
        raise LedgerError('证据URL只允许无凭证的HTTP或HTTPS地址。') from None


def normalize_evidence(data):
    """校验人工事件时间与独立数值字段，不能自称自动核实。"""
    if not isinstance(data, dict) or data.get('kind') not in {'news', 'earnings', 'macro', 'policy'}:
        raise LedgerError('事件类型必须为新闻、财报、宏观或政策。')
    scope = data.get('scope')
    if scope not in {'global', 'symbol'}:
        raise LedgerError('事件范围必须为global或symbol。')
    result = {'kind': data['kind'], 'scope': scope, 'symbol': symbol(data.get('symbol')) if scope == 'symbol' else None,
              'title': label(data.get('title')), 'source': label(data.get('source')), 'url': event_url(data.get('url')),
              'published_at': stamp(data.get('published_at'), True), 'available_at': stamp(data.get('available_at'), True),
              'verification': 'manual_unverified', 'quality': ['manual_unverified'],
              'notes': label(data.get('notes'), 10000, True), 'period': label(data.get('period'), 100, True) or None,
              'unit': label(data.get('unit'), 100, True) or None}
    for key in ('actual', 'expected', 'previous', 'revised'):
        result[key] = text_number(decimal(data.get(key), True))
    if result['published_at'] and result['available_at'] and result['available_at'] < result['published_at']:
        raise LedgerError('首次可知时间不能早于声称发布时间。')
    if not result['published_at'] or not result['available_at']:
        result['quality'].append('unknown_timing')
    return result


def evidence_gaps(event, as_of):
    """发布时间、可知声明及实际首次记录/当前版本记录都不得晚于截止。"""
    gaps = []
    for key in ('published_at', 'available_at', 'first_seen_at', 'captured_at'):
        if not event.get(key):
            gaps.append(key + ':unknown')
        elif event[key] > as_of:
            gaps.append(key + ':after_as_of')
    return gaps


def frozen_snapshot(events, revision, as_of):
    """按已知时刻截断，并排除日期不确定事实的后续标的依赖，显式保留缺口。"""
    local_day = datetime.fromisoformat(as_of).astimezone(ZoneInfo('America/New_York')).date().isoformat()
    active = ordered_active(events)
    selected, excluded, gaps = [], [], {}
    uncertain_cash = False
    for event in active:
        known = event['effective_at'] <= as_of if event.get('effective_at') else event['trade_date'] < local_day
        uncertain = not event.get('effective_at') and event['trade_date'] == local_day
        ticker = event.get('symbol')
        if uncertain:
            uncertain_cash = True
            if ticker:
                gap = gaps.setdefault(ticker, {'symbol': ticker, 'reason': 'date_only_at_cutoff',
                    'uncertain_event_ids': [], 'dependent_event_ids': []})
                gap['uncertain_event_ids'].append(event['id'])
        dependent = known and ticker in gaps
        if dependent:
            gaps[ticker]['dependent_event_ids'].append(event['id'])
        if known and event['trade_date'] <= local_day:
            if not dependent:
                selected.append(event)
                continue
        reason = 'depends_on_uncertain_event' if dependent else 'date_only_at_cutoff' if uncertain else 'after_cutoff'
        excluded.append({'id': event['id'], 'symbol': ticker, 'trade_date': event['trade_date'], 'reason': reason})
    result = replay(selected, revision)
    positions = {p['symbol']: p for p in result['positions']}
    for ticker, gap in sorted(gaps.items()):
        p = positions.setdefault(ticker, {'symbol': ticker, 'quantity': None, 'cost': None, 'group': 'ungrouped'})
        p.update(quantity_status='known_partial', known_partial_quantity=p['quantity'] or '0', known_partial_cost=p['cost'])
        p['cost'] = None
        gap['known_partial_quantity'] = p['known_partial_quantity']
    result['positions'] = [p for _, p in sorted(positions.items())]
    result.update(asOf=local_day, cutoff_at=as_of, recorded_revision_basis='current_corrected_ledger',
                  excluded_uncertain_or_future_events=[e['id'] for e in excluded], cutoff_exclusions=excluded,
                  position_gaps=list(gaps.values()), totals_status='known_partial' if uncertain_cash else 'complete')
    if uncertain_cash:
        keys = ('cash_balance', 'ledger_cash_delta', 'fees', 'dividend_income', 'net_funding', 'realized_pnl')
        result['known_partial_totals'] = {key: result[key] for key in keys}
        for key in keys:
            result[key] = None
        result['quality'].append('partial_ledger_totals')
    if gaps:
        result['quality'].append('position_timing_uncertain')
    if excluded:
        result['quality'].append('intraday_or_future_events_excluded')
    return result


class ResearchStore:
    """追加证据版本和研究记录，与账本使用同一SQLite事务快照。"""

    def __init__(self, store):
        """只读CLI不会创建研究表、数据库或任何记录。"""
        self.store = store
        if not store.readonly:
            with store.connection() as db:
                db.executescript(SCHEMA)

    def save_event(self, data, event_id=None, expected_version=None):
        """服务器生成实际首次记录/抓取时间，更新只追加新版本。"""
        event = normalize_evidence(data)
        with self.store.connection(True) as db:
            previous = None
            if event_id:
                previous = db.execute('SELECT data FROM evidence WHERE id=? ORDER BY version DESC LIMIT 1', (event_id,)).fetchone()
                if previous is None:
                    raise LedgerError('证据不存在。')
                previous = json.loads(previous[0])
                if expected_version != previous['version']:
                    raise LedgerError('证据版本已变化，请重新读取。')
            received = now()
            event.update(id=event_id or str(uuid4()), version=previous['version'] + 1 if previous else 1,
                         first_seen_at=previous['first_seen_at'] if previous else received, captured_at=received)
            db.execute('INSERT INTO evidence VALUES(?,?,?)', (event['id'], event['version'], canonical(event)))
        return event

    def events(self):
        """列出各事件的最新人工版本。"""
        with self.store.connection() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT e.data FROM evidence e WHERE version=(SELECT MAX(version) FROM evidence WHERE id=e.id) ORDER BY rowid DESC')]

    def save_research(self, data):
        """原子冻结持仓和支持/反面证据版本，未知或未来证据只列缺口。"""
        if not isinstance(data, dict):
            raise LedgerError('研究内容格式无效。')
        as_of = stamp(data.get('as_of'))
        if as_of > now():
            raise LedgerError('研究截止时间不能在未来。')
        record = {'id': str(uuid4()), 'account_id': label(data.get('account')), 'as_of': as_of, 'saved_at': now(),
                  'thesis': label(data.get('thesis'), 10000), 'trigger': label(data.get('trigger'), 10000, True),
                  'invalidation': label(data.get('invalidation'), 10000, True), 'group': data.get('group', 'ungrouped')}
        if record['group'] not in {'core', 'tactical', 'ungrouped'}:
            raise LedgerError('研究分组无效。')
        support, against = data.get('support', []), data.get('against', [])
        if any(not isinstance(ids, list) or len(ids) > 100 or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids) for ids in (support, against)):
            raise LedgerError('证据ID列表无效或重复。')
        if set(support) & set(against):
            raise LedgerError('同一证据不能同时标为支持与反面。')
        with self.store.connection(True) as db:
            account, events = self.store.state(db, record['account_id'])
            expected = data.get('revision')
            if type(expected) is not int or expected != account['revision']:
                raise LedgerError('账户版本已变化，请刷新后保存研究。')
            record['snapshot'] = {'account_id': account['id'], **frozen_snapshot(events, account['revision'], as_of)}
            record['evidence_gaps'] = []
            for side, ids in (('support', support), ('against', against)):
                record[side] = []
                for identity in ids:
                    versions = [json.loads(r[0]) for r in db.execute('SELECT data FROM evidence WHERE id=? ORDER BY version DESC', (identity,))]
                    if not versions:
                        raise LedgerError('引用证据不存在。')
                    # 只使用截止前实际记录的版本；无该版本时保留最新内容但列为不可知线索。
                    event = next((e for e in versions if e['captured_at'] <= as_of), versions[0])
                    gaps = evidence_gaps(event, as_of)
                    record[side].append({'event': event, 'eligible': not gaps, 'gaps': gaps})
                    record['evidence_gaps'].extend([{'id': identity, 'side': side, 'reason': g} for g in gaps])
            if not support:
                record['evidence_gaps'].append({'reason': 'no_support_evidence'})
            if not against:
                record['evidence_gaps'].append({'reason': 'no_counter_evidence'})
            record['evidence_gaps'].append({'reason': 'manual_sources_not_automatically_verified'})
            db.execute('INSERT INTO research_records VALUES(?,?,?)', (record['id'], record['account_id'], canonical(record)))
        return record

    def records(self, account):
        """读取已冻结的研究历史，不重新计算旧报告。"""
        with self.store.connection() as db:
            self.store.state(db, account)
            return [json.loads(r[0]) for r in db.execute('SELECT data FROM research_records WHERE account=? ORDER BY rowid DESC', (account,))]

    def report(self, identity):
        """按ID读取私有冻结记录，后续持仓或证据更新不影响内容。"""
        with self.store.connection() as db:
            row = db.execute('SELECT data FROM research_records WHERE id=?', (identity,)).fetchone()
            if row is None:
                raise LedgerError('研究记录不存在。')
            return json.loads(row[0])
