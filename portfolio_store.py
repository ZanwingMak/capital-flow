"""仓库外 SQLite 私有台账；所有事实追加存储，业务变更使用事务。"""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
import json
from private_common import LedgerError, canonical, label, now
from portfolio_ledger import normalize_event, ordered_active, replay

PROJECT = Path(__file__).resolve().parent
SCHEMA = '''
CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY, name TEXT NOT NULL, revision INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, account TEXT NOT NULL REFERENCES accounts(id), data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_account ON events(account);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'immutable'); END;
PRAGMA user_version=1;
'''


def identity_keys(event):
    """执行号和人工参考号分别构成来源内身份，二者都参与重复校验。"""
    return [(event['source'], key, event[key]) for key in ('external_id', 'reference') if event.get(key)]


def private_directory(value=None):
    """选择仓库外的本机私有目录，并解析符号链接防止误放静态站点。"""
    directory = Path(value or os.getenv('FLOWDESK_PRIVATE_DIR') or Path.home() / 'Library/Application Support/Flowdesk/private').expanduser().resolve()
    if directory == PROJECT or PROJECT in directory.parents or any(p.name == 'dist' or (p / '.git').exists() for p in (directory, *directory.parents)):
        raise LedgerError('私有数据目录必须位于项目和静态资源目录之外。')
    return directory


class PortfolioStore:
    """每次操作独立连接；跨线程通过 SQLite 写事务和账户 revision 串行化。"""

    def __init__(self, directory=None, readonly=False):
        """写模式显式初始化私有库；只读模式不创建文件、目录或记录。"""
        self.directory = private_directory(directory)
        self.path = self.directory / 'portfolio.sqlite3'
        self.readonly = readonly
        if self.path.is_symlink():
            raise LedgerError('私有数据库路径不能是符号链接。')
        if readonly:
            if not self.path.is_file():
                raise LedgerError('私有数据库尚不存在。')
            return
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.directory, 0o700)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with self.connection() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connection(self, write=False):
        """关闭每个连接，并确保失败回滚；只读连接由 SQLite 强制限制。"""
        if write and self.readonly:
            raise LedgerError('只读模式禁止写入。')
        target = self.path.as_uri() + '?mode=ro' if self.readonly else str(self.path)
        db = sqlite3.connect(target, uri=self.readonly, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def create_account(self, name):
        """新建独立的 USD 合成或用户显式录入账户，不猜测现金和持仓。"""
        account = {'id': str(uuid4()), 'name': label(name, 100), 'revision': 0, 'created_at': now()}
        with self.connection(True) as db:
            db.execute('INSERT INTO accounts VALUES(:id,:name,:revision,:created_at)', account)
        return account

    def accounts(self):
        """列出账户摘要。"""
        with self.connection() as db:
            return [dict(r) for r in db.execute('SELECT * FROM accounts ORDER BY created_at,id')]

    def state(self, db, account):
        """在同一事务中取得账户版本与完整原始审计事件。"""
        row = db.execute('SELECT * FROM accounts WHERE id=?', (account,)).fetchone()
        if row is None:
            raise LedgerError('账户不存在。')
        events = [json.loads(r[0]) for r in db.execute('SELECT data FROM events WHERE account=? ORDER BY rowid', (account,))]
        return dict(row), events

    def history(self, account):
        """返回包括被更正原文在内的追加审计记录。"""
        with self.connection() as db:
            return self.state(db, account)[1]

    def snapshot(self, account, as_of=None):
        """在一致读事务中重放账本，日期截止不代表历史时点已知版本。"""
        with self.connection() as db:
            db.execute('BEGIN')
            row, events = self.state(db, account)
            return {'account_id': account, **replay(events, row['revision'], as_of)}

    def validate(self, existing, incoming, revision):
        """有效事实去重；审计身份仅能沿显式作废替代链继承，不能被普通导入复用。"""
        active = ordered_active(existing + incoming)
        facts = {e['id']: e for e in existing if e['kind'] != 'void'}
        voided = {e['target'] for e in existing + incoming if e['kind'] == 'void'}
        replaced = {e['replaces'] for e in existing if e.get('replaces')}
        owners = {}
        for e in facts.values():
            for key in identity_keys(e):
                owners.setdefault(key, set()).add(e['id'])
        for e in incoming:
            if e['kind'] == 'void':
                continue
            ancestors = set()
            target = e.get('replaces')
            if target:
                original = facts.get(target)
                if not original or target not in voided or target in replaced:
                    raise LedgerError('替代必须关联已作废且尚未被替代的原事件ID。')
                if e['source'] != original['source'] or (original.get('external_id') and e.get('external_id') != original['external_id']):
                    raise LedgerError('替代须保留原来源和真实执行ID，不能捏造执行身份。')
                replaced.add(target)
                while target:
                    ancestors.add(target)
                    target = facts[target].get('replaces')
            for key in identity_keys(e):
                if owners.get(key, set()) - ancestors:
                    raise LedgerError('执行ID或独立参考号已存在；更正须用replaces关联原事件。')
                owners.setdefault(key, set()).add(e['id'])
            facts[e['id']] = e
        keys = set()
        for e in active:
            for key in identity_keys(e):
                if key in keys:
                    raise LedgerError('执行ID或独立参考号被其他有效事实占用，不能重复记账。')
                keys.add(key)
        return replay(existing + incoming, revision + 1)

    def insert(self, db, account, events):
        """原子追加整批事件并只增加一次账户 revision。"""
        db.executemany('INSERT INTO events VALUES(?,?,?)', [(e['id'], account, canonical(e)) for e in events])
        db.execute('UPDATE accounts SET revision=revision+1 WHERE id=?', (account,))

    def append(self, account, events, expected_revision=None):
        """校验整批后事务写入，任何错误都不留下部分成交。"""
        if not isinstance(events, list) or not 1 <= len(events) <= 5000:
            raise LedgerError('请提供1至5000条事件。')
        incoming = [normalize_event(e) for e in events]
        with self.connection(True) as db:
            row, existing = self.state(db, account)
            if expected_revision is not None and row['revision'] != expected_revision:
                raise LedgerError('账户版本已变化，请重新预览。')
            result = self.validate(existing, incoming, row['revision'])
            self.insert(db, account, incoming)
            return {'account_id': account, **result}
