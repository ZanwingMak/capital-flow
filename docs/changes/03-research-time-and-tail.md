# 节点3：研究时间口径与尾盘阈值

- 问题：旧`asOf`仅限制资金事件，后续价格和统计可超过该日期，却未注明复盘口径；分钟覆盖日期也可能暴露截至日后的档案。尾盘绕过分位数条件，存在合成复现的净额-1、展示阈值500仍入选，以及此前样本不足便产生异常的问题。
- 时间行为：新增`mode=retrospective|strict-as-of`。省略仍为事后复盘，允许后续价格超过事件截至日；严格模式在构建价格映射和收益路径前截断交易日历至截至日，全部汇总/近期提醒沿用已截断路径。两种模式均只读取截至日内的分钟文件，覆盖日期、最新窗口不越界，缺价保持交易日断点。
- 响应：保留旧字段，新增`mode`、`outcomeThrough`、`timeSemantics`、`pointInTimeVerified=false`及`dataRevisionNote`；研究响应`serviceVersion=3`。交易日期截断并非历史发布版本保证：现有前复权日线及分钟留存不含完整发布/修订历史，不能伪称数据版本在当时实际可得。UI持续显示该限制。
- API：旧路径与省略mode的调用保持默认复盘；未知、空白和重复mode返回400；两种模式进入不同作业键，模式贯穿fetch及构建入口。保留原有数值边界、市场与交易日验证。
- 尾盘：与日级一致，使用事件之前60个同口径窗口中的同向绝对值分位数，至少10个有效样本，缺分钟不凑数；入选必须同时达到金额下限和分位阈值（即展示threshold）。双向模式分别使用与当前事件同向的基线，不把净流入与净流出混合。
- UI：增加默认复盘/严格截至当时选择，显示事件与结果价格的不同边界；启用尾盘分位数输入并说明样本要求。严格请求拒绝旧服务默认复盘或越界路径、分钟日期。旧日级响应可按默认复盘读取；旧尾盘服务未执行分位阈值，新UI明确拒绝，提示连接新版服务，避免控件与实际行为不一致。更新脚本缓存版本。
- 初始红灯命令：`PYTHONDONTWRITEBYTECODE=1 /Users/maizhenying/Code/my_project/capital-flow/.venv/bin/python -m unittest discover -s tests -p 'test_research*.py' -v`，16个测试方法，11项失败、6项错误（含子测试）；复现尾盘绕过阈值及不足样本入选，并确认新时间模式/验证缺失。`node --test tests/test_research_ui.js`，初始4个测试全部失败。复查增加旧尾盘服务兼容测试后，5个Node测试中1个红灯，随后修复通过。
- 最终节点绿灯：同一Python命令17个测试全部通过，包含额外核对实际改变分位数会改变事件入选的合成测试；同一Node命令5个测试全部通过。覆盖未来价格极端变化不影响严格统计、未满期不入分母、缺价不压缩、60窗口限制、双向分离、缺分钟和API参数传递。所有行情和文件均为显式合成fixtures，HTTP测试直接调用处理器，不绑定端口、不启动服务、不读取凭据或私有缓存。
- 保留：`analyze.py`时间切分、前后段隔离、交易日区块bootstrap未变；不增加可成交策略或盈利结论。

## 本批验证与交付

- 全量命令：`PYTHONDONTWRITEBYTECODE=1 /Users/maizhenying/Code/my_project/capital-flow/.venv/bin/python -m unittest discover -s tests -v`（35个Python测试）；`node --test tests/test_intelligence_ui.js tests/test_research_ui.js`（8个Node测试）。
- 语法与差异：`node --check dist/intelligence.js`、`node --check dist/research.js`、`git diff --check`；另外对所有Python源码做内存编译，不生成pyc。
- 实际结果：全量35个Python测试和8个Node测试全部通过；上述两项JS语法检查、差异检查及10个Python文件内存编译均通过。
- Git实际限制：工作区`.git`指向原项目的`.git/worktrees/flowdesk-quality-worktree`，普通`git add`因无法创建该处`index.lock`失败。本批没有修改原项目Git元数据；在允许写入的`/private/tmp/flowdesk-quality-review.git`中建立独立提交历史，基于`efebe75`，同名分支`fix/research-data-quality`，逐节点明确暂存文件并提交。工作区文件保留全部实现，原worktree的分支引用未推进。提交包`/private/tmp/flowdesk-quality-commits.bundle`仅包含这三个提交相对基线的新对象，供Hermes独立审查、导入并推送，不自行push/merge。
- 后续：由Hermes在可写Git元数据的环境导入并审查；在另行允许的环境核验上游时间戳时区和无私有数据的页面集成。真正的历史发布时可得研究需要独立数据版本依据，属于后续批次；本批不扩成数据平台。现有Windows压缩包未重建，后续发布需同步打包流程，避免分发旧代码。
