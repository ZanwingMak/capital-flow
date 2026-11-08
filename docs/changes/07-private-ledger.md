# 节点7：仓库外 USD 正股台账

实现不可变事件、实际收到时间、来源与原文、交易日期与执行精度；更正通过追加 void 保留原事实。独立账户附 revision，整批业务校验后使用 SQLite 事务写入。Decimal 文本计算移动加权账面成本（非税务批次），买入费入成本，卖出费抵所得；资金出入、分红和费用分开。期初截止日及之前增量拒绝叠加。同日影响成本的顺序不明时拒绝，不以CSV行号排序。

未知成本、现金期初及实时价格不补零；只显示账本现金变化，只有明确现金期初才有现金余额。不支持期权、卖空、洗售、多币种税务或实时权益。

验证（2026-11-08）：

- 红：最初1项因 `portfolio_store` 未实现而失败。
- 红：扩充至12项后，时间与人工顺序矛盾用例误报超卖。
- 绿：修复后 `python -m unittest discover -s tests -p test_portfolio_store.py -v`，12项通过。解释器为原项目 `.venv/bin/python`；TMPDIR及 tempfile.tempdir 均显式指向 `~/.hermes/cache/scratch/flowdesk-review/portfolio-tests`。
- 所有数据合成，实际 SQLite/Decimal 运算，无核心计算 Mock。

预期提交：`feat: add private portfolio event ledger`。本轮 Git 尝试在元数据创建 index.lock 时返回 Operation not permitted；未创建替代仓库、未删除锁。源文件保留，由父代理提交。

## P1复审修复（2026-11-09）

修复带执行ID事实不能以原身份更正的问题：有效事实的身份唯一，历史审计的身份只允许沿明确 `replaces=原事件ID` 继承。原事件须已在同批或前次操作作废，保留原来源及真实执行ID；替代产生新审计ID。执行号与参考号分别检查，普通重复、冒用其他有效身份及旧关联分叉均拒绝。不可变SQLite审计触发器保持有效。UI填写完整替代事实及原事件ID后，自动继承身份并按需同批作废，无须删除或捏造执行号。

真实红→绿：新增5项后执行下列命令，22项中出现3个错误、2个失败（含subTest）：同批更正、前次void后替代及连续更正被旧去重拒绝，伪造新身份和遗漏关联却被接受。修复后原样运行，22项全部通过。Node更正表单用例先因缺少 `correctionEvents` 失败，修复后 `node --test tests/test_private_ui.js` 12项通过；既有后台close清理用例保留。

```bash
TMPDIR=~/.hermes/cache/scratch/flowdesk-review/portfolio-tests PYTHONDONTWRITEBYTECODE=1 ~/Code/my_project/capital-flow/.venv/bin/python - <<'PY'
import os, sys, tempfile, unittest
tempfile.tempdir = os.environ['TMPDIR']
def guard(event, args):
    """禁止测试读取环境秘密或连接网络。"""
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)) and os.path.basename(os.fsdecode(args[0])).startswith('.env'):
        raise AssertionError('禁止读取.env')
    if event in {'socket.connect', 'socket.bind'}:
        raise AssertionError('禁止网络或服务')
sys.addaudithook(guard)
result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover('tests', pattern='test_portfolio_store.py'))
sys.exit(not result.wasSuccessful())
PY
node --test tests/test_private_ui.js
```
