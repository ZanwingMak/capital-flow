# 私有持仓与可追溯研究 V1 Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task. 本轮已获用户实施与发布授权；使用Codex实现，父代理逐节点核验、独立审查和真实验收，不再重复索要许可。

**Goal:** 在保留现有行情和研究口径的基础上，提供可用的私有股票台账、嘉信CSV预览导入、事件证据与持仓版本关联的研究记录及报告导出。

**Architecture:** Python标准库SQLite/Decimal提供仓库外私有存储；现有HTTP服务增加严格本机、同源、会话令牌保护的私有接口。原生JS新增私有工作台，GitHub Pages只提供页面外壳，不携带或读取私人数据。已有行情/研究API保持兼容，Hermes后续读取新台账作为持仓真值。

**Tech Stack:** 当前Python/stdlib sqlite3+Decimal、现有HTTP Handler、原生HTML/CSS/JS、unittest与Node内置测试；不新建LLM服务、支付数据源或第二套调度。

---

## 本轮边界

- 支持USD正股持仓、买卖、现金入出、费用、分红、拆股及带日期期初快照，底仓/短线/未分组。期权、卖空、转仓税批、wash sale和多币种精确收益不在V1能力内；导入遇到这些动作须明确待核实，不丢弃或假装已处理。
- 官方宏观/财报/新闻/政策事件先提供结构化录入、来源与时间、持仓关联和报告导出；不宣称自动抓取官方发布或自动核验事实。实际值/预期/前值/修订值分开，未知留空。
- 不生成AI买卖评分、校准胜率、真实实时账户总权益或完整税务收益。缺成本/价格/FX时保留未知，禁止0或1:1填补。
- 私人SQLite、输入原文、报告、令牌在仓库外；fixtures全部合成。默认私有目录使用平台用户应用数据目录，可由`FLOWDESK_PRIVATE_DIR`指定；拒绝私有目录落入仓库或dist。测试用临时根目录并明确隔离。

### Task 1: 私有账本基础（节点7）

**Files:** 新增`portfolio_store.py`（可按复杂度合理拆小模块）、`tests/test_portfolio_store.py`；新增`docs/changes/07-private-ledger.md`。

1. 先写红灯：新建独立账户、期初3股且成本未知，快照数量可用但成本/盈亏null。运行单测确认缺功能失败，再实现。
2. 每条成交/现金/公司行动有不可变ID、来源、收到时间、交易日期/可得时间和原始记录；使用Decimal与文本落库。更正保留审计记录，不能删除原始事实。
3. 分别增加红灯与实现：买入/卖出含费重放，部分卖出余量，未知成本继续未知，超卖拒绝，入出金不当投资收益，拆股保持总成本，分红和现金独立记录。期初日期之前的增量不能叠加导致双计。
4. 账户快照附revision/asOf/currency/quality；成本或价格未知不得输出完整盈亏。V1不引入实时估值，只给有依据的数量、账本现金及已知成本。
5. 每轮执行目标单测红绿灯；节点完成执行全部相关测试，记录并提交`feat: add private portfolio event ledger`。

### Task 2: 嘉信CSV解析和预览（节点8的一部分）

**Files:** 新增`portfolio_import.py`、`tests/test_portfolio_import.py`。

1. 合成Schwab列头：Date,Action,Symbol,Description,Quantity,Price,Fees & Comm,Amount（来自真实表头，但禁止读取真实成交行）。先红灯再实现：买卖、美元千分位、Decimal、日期；交易ID仅在确有列时使用，不把委托号当执行号。
2. 日期含as-of等歧义、数量/金额不一致、未知动作、期权/卖空等必须保留行号/原文并标待核实，不静默排除。现金动作只接受明确含义的映射。
3. 稳定去重不使用源行号。无执行ID时相同事实作为疑似重复，真实同价同量两笔不可直接合并；预览说明并要求用户明确选择/给独立参考号，不能自动吞记录。
4. 预览和提交共享完整业务校验，按有效时间排序；预览附账户revision与不可变payload标识。提交再次校验，账户变更/预览过期拒绝并要求重新预览；事务提交，不能悄悄部分成功。
5. 合成用例覆盖重复上传、重排序、同量分笔歧义、倒序买卖、超卖、unsupported及原始行保留；测试无私有数据。

### Task 3: 私有HTTP边界与工作台（节点8）

**Files:** 修改`server.py`、`dist/index.html`、静态白名单；新增`private_api.py`、`dist/private.js`/CSS、HTTP与JS测试、`docs/changes/08-private-workspace.md`。

1. 先红灯：外部Origin/恶意Host/非loopback peer/缺令牌的私有读写均拒绝，且拒绝前不初始化私有数据库。跨源公开网站永远不能获取私有数据或会话令牌。
2. 私有会话握手只允许直接本机同源；令牌服务启动时随机生成，前端仅内存持有，通过Header传递，不出现在URL、localStorage或日志。所有私有API请求检查Host/Origin/连接来源/令牌；私有响应不得沿用通用CORS向其他Origin开放。配置FLOW_TOKEN时不削弱既有认证。处理OPTIONS、请求体大小、JSON异常与异常脱敏。
3. 公共页面默认不触发私有请求；仅用户在本机页面主动打开私有工作台才握手。GitHub Pages给出本机打开提示，不能自动连接本机私有接口。
4. UI可创建账户、录入带日期期初/成交与分组、查看数量/现金/质量/版本，上传CSV预览逐行问题、选择明确可提交记录并确认。没有“挂单=成交”；不输出模拟行情/虚构账户。
5. 写合成HTTP边界测试（请求处理与真实loopback测试均适用），Node测试验证界面错误/未知值和导入状态。保留已有所有交互与README项目总览。
6. 完成后测试、节点文档、提交`feat: add protected local portfolio import workspace`。

### Task 4: 事件证据与研究记录（节点9）

**Files:** 新增`research_store.py`、`tests/test_research_store.py`，扩展private API/UI，新增`docs/changes/09-evidence-and-research.md`及用户指南。

1. 红灯先行：事件包括news/earnings/macro/policy、symbol或global、source/url、published_at、available_at/firstSeen、captured_at、质量与缺口；URL只支持http(s)，不在服务器自动获取用户URL；时间明确时区，未知时间只能作未核实线索。
2. 数值字段实际/预期/前值/修订值/期间/单位独立保留，缺失null。当前阶段人工录入不等于官方已验证。
3. 研究记录包含论点、支持与反面证据ID、触发/失效条件、底仓/短线、账户snapshot/revision，保存时冻结引用内容/版本，后改持仓或证据不重写旧报告。
4. `as_of`筛选同时约束发布时间与首次可得时间；未来或unknown时点证据不得作为严格截止日的已知事实。明确区分“现实首次记录时间”和历史发布声称时间。
5. 可从私有UI查看历史研究、生成并下载Markdown/JSON报告；报告先显示持仓日期/版本和证据缺口，再列事实、判断、支持/反面依据、触发和失效条件。不引入新付费模型，模板生成与数值计算可确定性验证。
6. 提供供Hermes读取的只读CLI导出，例如`private_cli.py portfolio/export-report`，默认不创建数据库/记录；私有报告导出不写dist或仓库。父代理后续接通旧持仓JSON与定时报告真值，不由Codex读写用户实际文件。
7. 验证冻结旧研究、修改当前持仓、缺/未来证据、事件URL、未知成本与Markdown转义；写文档、更新README对应当前功能/限制，不能覆盖项目介绍；提交`feat: add evidence-linked research records and reports`。

### Task 5: 独立验收与发布（Hermes）

1. 用原项目虚拟环境执行新工作区全套unittest、Node测试、JS语法与diff检查，审查新增私有HTTP边界；另派独立安全/口径审查。
2. 用合成临时数据库、额外loopback端口启动新服务，实际浏览器完成“期初→CSV预览→确认→快照→事件→研究→导出”，检验外部Origin无法读取。不得混入用户真实数据库或杀现有服务。
3. 通过后同步原工作区、在用户已授权范围内重启服务。先备份旧持仓记录，再由父代理明确导入带日期旧快照，成本未知保持null；不自动导入整年历史CSV以免期初双计。更新Hermes持仓读取桥接，使报告读最新账本并保留原JSON回退和旧快照日期。
4. 扫描提交路径与常见秘密模式；只提交代码、合成fixtures、技术文档。保留独立节点提交，推送PR、merge不squash，回读main精确SHA和对应部署状态。
