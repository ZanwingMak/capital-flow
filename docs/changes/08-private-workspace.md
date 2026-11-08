# 节点8：CSV冻结预览与本机私有工作台

支持合成表头 `Date,Action,Symbol,Description,Quantity,Price,Fees & Comm,Amount`。只把明确的 Execution ID 当成交标识；Order ID及原始行号不作为稳定去重键。未知动作、as-of日期、金额不符、期权描述、拆股数量含义不清等逐行保留原文并标待核实。无ID的相同事实只作疑似重复，每笔独立确认及参考号后可保留全部分笔，重排行号不能绕过提示。

预览和确认共用完整账本校验；服务端私有库保存冻结payload、摘要、revision、15分钟有效期和单次状态。确认不接受重传业务正文，版本变化或过期必须重新预览，全批事务写入。

私有API只接受直接loopback连接、可信本机Host、精确匹配的Origin以及内存会话Header；FLOW_TOKEN配置时仍必须提供。握手无需会话令牌，但同源与FLOW_TOKEN不放松。所有私有读取也使用POST，以便浏览器提供Origin，不接受URL参数；拒绝OPTIONS跨源读取、重复关键头、chunked、超长或坏JSON。私有路径忽略行情CORS白名单，错误不回显路径和原文。前端主动开启，令牌只在内存；关闭清理私有DOM和输入。GitHub Pages只提示打开本机页面。

界面具备账户、期初/成交/现金/拆股/分组/追加作废、版本快照、原始审计、CSV逐行选择及再预览。没有交易执行功能。

验证（2026-11-08）：

- 红：CSV模块初始不存在；补充期权描述用例发现被接受，修复后13项通过。HTTP边界初始模块不存在。Node界面初始模块不存在，后续7项通过。
- Python全回归：104项通过；Node全回归：15项通过。`node --check dist/private.js`、`git diff --check`通过。
- Python使用原项目 `.venv/bin/python`，TMPDIR与tempfile.tempdir固定到授权portfolio-tests目录；审计钩子拒绝`.env`读取及所有socket.connect。启动器测试的“安装”文字来自被隔离的合成边界，未实际安装软件。
- HTTP使用真实Handler序列化与内存字节流隔离socket，账本和CSV核心均实际运算。未启动真实服务器或浏览器；实际loopback与浏览器验收由父代理Task5完成。

预期提交：`feat: add protected local portfolio import workspace`。Git元数据index.lock仍受环境保护，本轮无节点提交SHA，父代理负责提交；未push/merge。

## P1复审修复（2026-11-09）

新增执行ID不再跳过旧无ID事实指纹，也检查同批有ID/无ID的同事实组合。疑似同一笔时不生成可提交预览，账户数量和revision不变；用户只能取消选择、通过 `replaces` 更正原记录，或核实确为独立分笔后填写独立参考号并明确确认。确认会保留真实执行ID，参考号不替代或伪造执行号。

真实红→绿：新增3项后执行下列命令，21项中3项失败：旧无ID行后补exec-1可直接提交；人工确认的行缺少歧义标记；同批混合身份行可绕过检查。修复后相同命令21项通过。父代理的 `watchDialogClosure` MutationObserver清理与新增Node用例原样保留；用户指南的相对 `.venv/bin/python` 路径保留。

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
result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover('tests', pattern='test_portfolio_import.py'))
sys.exit(not result.wasSuccessful())
PY
```
