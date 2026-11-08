# 节点9：人工事件证据、冻结研究与私有导出

实现新闻/财报/宏观/政策的global或正股关联、HTTP(S)来源URL存档、独立数值字段，以及不可变证据版本。URL不由服务器访问；所有事件固定标为manual_unverified。published_at、声称available_at、实际first_seen_at与本版本captured_at各自保留，实际记录时间不能被客户端回填。

研究保存使用单一SQLite事务冻结账户snapshot/revision及支持/反面证据全文与版本；账户旧版本拒绝保存。截止同时限制发布、声称可得、实际首次记录与该版本录入时间，未来和未知时间只列线索/缺口；可用截止前已实际存档的旧版本。日期精度的当日账本事实在完整美东日期结束前不当作确定持仓，精确时刻按实际时间截断。持仓重放明确是当前更正后的账本口径，不伪装历史当时系统已知的账户版本。

私有界面支持事件新增/版本更新、支持/反面选择、论点及条件、历史查看与内存Blob下载；JSON/Markdown均来自冻结内容。Markdown转义用户输入，先列持仓日期/版本与证据缺口，再区分事实、判断和条件式观察。不调用模型，不生成胜率或自动买卖，不宣称BLS/IR自动抓取核验。

新增private_cli.py的accounts、portfolio、research、export-report，只读SQLite URI，缺库不创建文件。实际子进程测试确认导出后DB字节不变。真实持仓迁移与Hermes旧JSON回退桥接留父代理Task5。

用户操作、接口保护、数据口径、CLI命令和父代理真实验收步骤见[私有工作台指南](../private-workspace.md)。README保留原项目总览，仅增加当前能力和链接。新增实现为独立原生模块，未复制第三方实现或引入其框架。

## 红→绿记录与验证

- 红：初始research_store缺失；CLI用例在private_cli.py不存在时失败，完成后11项研究测试通过。
- 红：前端研究模块不存在；完成后人工时间/空值展示及真实表单事件链路通过。
- 追加边界红灯：CSV可选Currency被忽略、确认参考号未回显、执行时间日期错配、同日分组顺序未拦截、手工API漏费被当0。对应修复均通过；最终还发现部分已知逐笔时刻可被人工顺序颠倒，新增红灯后修复，不能因其他记录时间缺失而忽略已知先后。
- 前端真实事件测试发现busy禁用fieldset导致FormData为空；改为inert及串行保护后转绿。关闭会话时在途JSON与文件读取也被隔离，防止晚到结果恢复私有内容。
- 实际SQLite触发器模拟第二条插入失败，验证前条及revision回滚；并发确认验证恰好一次提交。核心计算未Mock。另以红→绿验证取消选择的待核实行随完整CSV一起存入有效冻结预览，确认子集不会丢失这些原文。

Task1–4阶段测试（2026-11-08）：Python **127项**、Node **21项**通过，Python新增55项，Node新增13项。全部JS语法、shell语法、已跟踪与未跟踪文本差异检查通过。测试只用合成fixtures；TMPDIR和tempfile.tempdir固定授权portfolio-tests目录，审计钩子禁止.env读取和socket.connect。该实现阶段没有启动真实服务/浏览器、调用业务网络、安装软件或接触真实账户。

## P1及来源链接复审修复（2026-11-09）

研究截止不再逐行拼接可能超卖的子集：当日date-only事实及其后同标的依赖一起排除，其他独立持仓保留。`position_gaps` 列出不确定和依赖事件ID及已知数量；受影响行标为 `quantity_status=known_partial`，没有已知持仓时数量为null，不能误报确定0股。报告/UI显式显示“截止总量未知 / 仅已知部分”，总成本未知；账户相关汇总设null，已知子集另存 `known_partial_totals`。逐笔原因保存在 `cutoff_exclusions`。明确晚于截止的精确成交只截断，不扩大持仓不确定性；完整美东日期结束后新冻结可恢复完整日事实。旧冻结记录仍不可变。

来源URL在保存及Markdown输出时均校验HTTP(S)、凭证、控制字符、反斜杠和authority解析歧义。用受控尖括号链接保留正常URL的域名、连字符与查询参数，编码可突破链接边界的字符；标题和正文仍按不可信文本转义。证据UI输出安全a元素，带 `rel="noopener noreferrer"` 和无referrer策略，并额外检查协议。服务端和UI都不自动抓取来源。

真实红→绿（未删改既有断言）：

- 截止依赖新增3项，研究模块14项初跑出现1失败、2错误：卖出子集超卖、底仓被错误扣减，以及质量字段缺失；修复后14项通过。`node --test tests/test_private_ui.js` 的新增缺口展示用例先因未显示“截止总量未知”失败，修复后11项通过。随后身份更正用例加入后该文件12项通过。
- 来源链接再新增3项，研究模块17项初跑出现10个失败（含恶意URL subTest）：正常地址被正文转义，危险链接边界未经编码，导出未重新验证协议；修复后17项通过。`node --test tests/test_private_research_ui.js` 先因没有安全a元素失败，修复后5项通过。
- 前两项Python红绿均使用下面同一命令；首次在只加入截止3项后运行，后次在加入URL3项后运行。

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
result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover('tests', pattern='test_research_store.py'))
sys.exit(not result.wasSuccessful())
PY
node --test tests/test_private_ui.js
node --test tests/test_private_research_ui.js
```

本轮全套回归：Python **141项**、Node **25项**通过（在原127项及含父代理close回归的22项基础上，分别新增14项和3项）。全JS语法、Python源语法、shell语法及已跟踪/未跟踪文本diff检查通过。保留父代理MutationObserver补丁、原始未提交源文件及用户指南中的相对Python路径。没有读取真实.env、持仓或券商数据，没有启动服务、联网、修改Hermes配置或写Git元数据。

回归命令（工作区根目录；不是启动服务）：

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
result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover('tests'))
sys.exit(not result.wasSuccessful())
PY
node --test tests/test_*.js
for file in dist/*.js tests/*.js; do node --check "$file" || exit 1; done
bash -n 启动Flowdesk.command
git diff --check
```

Git当前无法为worktree创建index.lock（Operation not permitted）。因此计划、节点7/8/9均无本地commit SHA；未push、merge、改Git配置、删除锁或创建替代仓库。父代理应审查后按计划保留节点提交：

- `docs: record private portfolio research implementation plan`
- `feat: add private portfolio event ledger`
- `feat: add protected local portfolio import workspace`
- `feat: add evidence-linked research records and reports`

后续修复均保留在当前未提交源文件中，节点文档保留真实红绿结果和累计数量，不伪造节点SHA。本轮未尝试Git写入。父代理已反馈基本合成浏览器链路通过、独立安全审查无阻塞，并补入后台dialog关闭清理；本轮保留该修改。三项账本P1现已逐项修复，追加修复的真实浏览器复验及后续提交、真实导入和发布仍由父代理完成。
