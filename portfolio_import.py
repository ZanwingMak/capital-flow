"""合成/用户主动上传的 Schwab CSV 解析，以及冻结预览与原子确认。"""
import csv
import hashlib
import io
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from private_common import LedgerError, canonical, decimal, label, now, text_number
from portfolio_ledger import normalize_event

COLUMNS = ['Date', 'Action', 'Symbol', 'Description', 'Quantity', 'Price', 'Fees & Comm', 'Amount']
ACTIONS = {'Buy': 'buy', 'Sell': 'sell', 'Cash Dividend': 'dividend', 'Deposit': 'deposit',
           'Withdrawal': 'withdrawal', 'Fee': 'fee', 'Stock Split': 'split'}


def money(value, optional=False):
    """解析美元符号、合法千分位和括号负数，不接受含糊数字。"""
    value = value.strip()
    if not value and optional:
        return None
    if value.startswith('(') and value.endswith(')'):
        value = '-' + value[1:-1]
    value = value.replace('$', '')
    if not re.fullmatch(r'[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?', value):
        raise LedgerError('金额或数量格式待核实。')
    return decimal(value.replace(',', ''))


def fingerprint(event):
    """以业务事实生成候选指纹；行号、原文排版和委托号不参与稳定身份。"""
    keys = ('source', 'kind', 'trade_date', 'symbol', 'quantity', 'price', 'fees', 'amount', 'currency')
    return hashlib.sha256(canonical({k: event.get(k) for k in keys}).encode()).hexdigest()


def parse_schwab(content):
    """保留每一行的精确原文和行号，未支持或歧义记录明确待核实。"""
    if not isinstance(content, str) or len(content.encode('utf-8')) > 1024 * 1024:
        raise LedgerError('CSV必须为不超过1MiB的UTF-8文本。')
    lines = content.lstrip('\ufeff').splitlines(keepends=True)
    reader = csv.DictReader(io.StringIO(''.join(lines)), strict=True)
    try:
        if not reader.fieldnames or any(c not in reader.fieldnames for c in COLUMNS) or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise LedgerError('CSV表头不匹配 Schwab 已支持列。')
        rows, previous = [], 1
        for fields in reader:
            raw = ''.join(lines[previous:reader.line_num])
            line, previous = previous + 1, reader.line_num
            row = {'line': line, 'raw': raw, 'issues': [], 'event': None}
            rows.append(row)
            try:
                if None in fields or any(v is None for v in fields.values()):
                    raise LedgerError('CSV列数不匹配，原文保留待核实。')
                if fields.get('Currency', 'USD').strip().upper() != 'USD':
                    raise LedgerError('只接受USD账户导出，不转换其他货币。')
                date_text = fields['Date'].strip()
                if not re.fullmatch(r'\d{2}/\d{2}/\d{4}', date_text):
                    raise LedgerError('Date含歧义或as-of，需核实实际交易日期。')
                date = datetime.strptime(date_text, '%m/%d/%Y').date().isoformat()
                kind = ACTIONS.get(fields['Action'].strip())
                if kind is None:
                    raise LedgerError('未知或不支持动作（含期权、卖空、转仓、洗售），请核实。')
                if re.search(r'\b(OPTION|CALL|PUT|SHORT|WASH SALE)\b', fields['Description'], re.I):
                    raise LedgerError('描述涉及期权、卖空或洗售，超出首批支持范围。')
                event = {'kind': kind, 'source': 'schwab-csv', 'trade_date': date, 'currency': 'USD', 'raw': raw, 'line': line}
                if kind in {'buy', 'sell', 'dividend', 'split'}:
                    event['symbol'] = fields['Symbol'].strip().upper()
                # 只承认明确执行ID列；Order ID/委托号不是逐笔成交ID。
                if fields.get('Execution ID', '').strip():
                    event['external_id'] = fields['Execution ID'].strip()
                amount = money(fields['Amount'], optional=kind == 'split')
                if kind in {'buy', 'sell'}:
                    quantity, price, fees = money(fields['Quantity']), money(fields['Price']), money(fields['Fees & Comm'])
                    event.update(quantity=text_number(quantity), price=text_number(price), fees=text_number(fees))
                    expected = -quantity * price - fees if kind == 'buy' else quantity * price - fees
                    if amount != expected:
                        raise LedgerError('数量、价格、费用与Amount不一致，需核实。')
                elif kind == 'split':
                    raise LedgerError('Stock Split数量可能是新增股数而非比例，需手工核实并录入比例。')
                else:
                    if fields['Quantity'].strip() or fields['Price'].strip() or (fields['Fees & Comm'].strip() and money(fields['Fees & Comm']) != 0):
                        raise LedgerError('现金动作含数量、价格或额外费用，映射待核实。')
                    if amount is None or (kind in {'withdrawal', 'fee'} and amount >= 0) or (kind in {'deposit', 'dividend'} and amount <= 0):
                        raise LedgerError('现金动作Amount符号待核实。')
                    event['amount'] = text_number(abs(amount))
                row['event'] = normalize_event(event)
            except (LedgerError, ValueError) as error:
                row['issues'].append(str(error) if isinstance(error, LedgerError) else '日期或字段格式待核实。')
            if len(rows) > 5000:
                raise LedgerError('CSV超过5000条，请分批预览。')
        if not rows:
            raise LedgerError('CSV没有数据行。')
        return rows
    except csv.Error:
        raise LedgerError('CSV引号或记录结构错误，未导入。') from None


class ImportService:
    """预览正文由服务端私有库存储；提交只接受ID与摘要，拒绝过期版本。"""

    def __init__(self, store):
        """复用同一个账户存储和账本业务校验。"""
        self.store = store
        with store.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS previews(id TEXT PRIMARY KEY, account TEXT NOT NULL, digest TEXT NOT NULL, payload TEXT NOT NULL, expires_at TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0)')

    def preview(self, account, content, selections=None):
        """逐行展示问题和重复候选，选定事实完整重放后才允许确认。"""
        rows = parse_schwab(content)
        if selections is None:
            selections = [{'row': i} for i, r in enumerate(rows) if not r['issues']]
        if not isinstance(selections, list) or len(selections) > len(rows):
            raise LedgerError('导入选择格式无效。')
        chosen = {}
        for selection in selections:
            if not isinstance(selection, dict) or set(selection) - {'row', 'reference', 'distinct', 'sequence'}:
                raise LedgerError('导入选择包含未知字段。')
            index = selection.get('row')
            if type(index) is not int or index < 0 or index >= len(rows) or index in chosen:
                raise LedgerError('导入行选择无效或重复。')
            chosen[index] = selection
        with self.store.connection(True) as db:
            row, existing = self.store.state(db, account)
            counts = Counter(fingerprint(r['event']) for r in rows if r['event'])
            existing_facts = {fingerprint(e) for e in existing if e['kind'] != 'void'}
            unidentified_facts = {fingerprint(e) for e in existing if e['kind'] != 'void' and not e.get('external_id')}
            unidentified_facts.update(fingerprint(r['event']) for r in rows if r['event'] and not r['event'].get('external_id'))
            existing_ids = {(e['source'], e['external_id']) for e in existing if e.get('external_id') and e['kind'] != 'void'}
            incoming, errors = [], []
            for i, item in enumerate(rows):
                event, selection = item['event'], chosen.get(i)
                item['selected'] = selection is not None
                item['needs_reference'] = bool(event and (
                    fingerprint(event) in unidentified_facts if event.get('external_id') else
                    counts[fingerprint(event)] > 1 or fingerprint(event) in existing_facts))
                if event and event.get('external_id') and (event['source'], event['external_id']) in existing_ids:
                    item['issues'].append('执行ID已经导入，不能再次选择。')
                if item['needs_reference']:
                    item['warnings'] = ['疑似重复：新增执行ID也可能对应旧无ID事实；仅核实为独立分笔后填写参考号并确认，保留真实执行ID；同一笔请取消选择并通过更正关联原记录。']
                if selection is None:
                    continue
                if item['issues']:
                    errors.append('选中记录有待核实问题。')
                    continue
                event = dict(event)
                if item['needs_reference'] and not (selection.get('distinct') is True and selection.get('reference')):
                    errors.append('疑似重复记录需要独立参考号及明确确认。')
                    continue
                if selection.get('reference'):
                    event['reference'] = label(selection['reference'])
                if 'sequence' in selection:
                    if type(selection['sequence']) is not int or selection['sequence'] < 0:
                        raise LedgerError('人工顺序必须为非负整数。')
                    event['sequence'] = selection['sequence']
                item['event'] = event
                item['distinct_confirmed'] = selection.get('distinct') is True
                incoming.append(event)
            snapshot = None
            if not incoming:
                errors.append('没有选定可提交记录。')
            if not errors:
                try:
                    snapshot = self.store.validate(existing, incoming, row['revision'])
                except LedgerError as error:
                    errors.append(str(error))
            result = {'rows': rows, 'revision': row['revision'], 'errors': list(dict.fromkeys(errors)), 'can_commit': not errors,
                      'snapshot': snapshot, 'preview_id': None, 'payload_id': None}
            if not errors:
                payload = canonical({'account': account, 'revision': row['revision'], 'events': incoming,
                                     'original_csv': content, 'rows': rows})
                digest = hashlib.sha256(payload.encode()).hexdigest()
                identity = str(uuid4())
                expires = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
                db.execute('INSERT INTO previews(id,account,digest,payload,expires_at) VALUES(?,?,?,?,?)', (identity, account, digest, payload, expires))
                result.update(preview_id=identity, payload_id=digest, expires_at=expires)
            return result

    def commit(self, account, preview_id, payload_id):
        """事务内验证冻结内容、摘要、有效期和账户版本，再全有或全无追加。"""
        with self.store.connection(True) as db:
            preview = db.execute('SELECT * FROM previews WHERE id=? AND account=?', (preview_id, account)).fetchone()
            if preview is None or preview['used'] or preview['expires_at'] <= now():
                raise LedgerError('预览已过期或已确认，请重新预览。')
            if payload_id != preview['digest'] or hashlib.sha256(preview['payload'].encode()).hexdigest() != preview['digest']:
                raise LedgerError('预览内容标识不匹配，请重新预览。')
            payload = json.loads(preview['payload'])
            row, existing = self.store.state(db, account)
            if row['revision'] != payload['revision']:
                raise LedgerError('账户版本已变化，请重新预览。')
            snapshot = self.store.validate(existing, payload['events'], row['revision'])
            self.store.insert(db, account, payload['events'])
            db.execute('UPDATE previews SET used=1 WHERE id=?', (preview_id,))
            return {'account_id': account, **snapshot}
