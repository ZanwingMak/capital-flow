# 节点2：量能缺失与期权质量

- 问题：量能全缺或部分缺失被显示为确定的0次放量下跌；局部OI聚合仍提供墙排名；自然日差不超过3天便将旧报价快照标为可用，同日未来时间也未拒绝。
- 技术指标：20日统计要求20个有效相邻成交量对（涉及21根日线）。缺失时`distributionDays20=null`，新增`distributionCoverage`包含完整/局部/未知状态、有效数、期望数和原因。真实零量保留零，完整窗口的零次仍显示`0 次`。不完整窗口不产生确定的多次放量下跌提示。
- 期权覆盖：所选范围任何OI缺失时清空墙排名及行权价排名图，新增`oiCoverage`说明停止原因；同一快照中完整到期子范围仍可单独计算。总量和P/C继续要求对应字段完整；不把缺失OI当零。异动候选仅筛选OI和量均已知的合约，通过`anomalyCoverage`标记局部样本；真实零OI继续单列。不计算GEX。
- 时间语义：可注入`now`，新增`snapshotQuality`。只将带明确时区、美东当日且滞后≤60分钟的报价快照标为`available`；旧日期或同日超时为`stale`，缺时间/无时区/畸形/未来时间为不可用。该规则是保守展示策略，不推断交易所休市安排。历史和未来日期请求均不冒用当前期权链。`oiAsOf=null`明确独立OI日期未知，报价新鲜不表示OI是盘中数据。
- UI：缺量显示未知和覆盖原因；过期链暂停墙/P/C/异动展示，显示原始时间及原因；OI不完整时显示停止排名；候选数量注明局部样本。更新脚本缓存版本。旧服务无覆盖字段时前端保守显示未知或停止排名。
- 红灯：`PYTHONDONTWRITEBYTECODE=1 /Users/maizhenying/Code/my_project/capital-flow/.venv/bin/python -m unittest discover -s tests -p 'test_intelligence.py' -v`，13个测试方法，8项失败、9项错误（含子测试）；包括旧快照误报available、0冒充缺失及局部墙输出。`node --test tests/test_intelligence_ui.js`，3个测试全部失败。
- 绿灯：以上两条相同命令，13个Python测试、3个Node测试全部通过；`node --check dist/intelligence.js`与`git diff --check`通过。
- 数据与限制：仅使用代码内明确标记的合成fixtures，固定美东2026-11-06，不联网、不读取凭据/券商记录/私有缓存。未核验上游无时区时间戳的实际含义，故保守拒绝，可能降低免费接口可用率；应在有官方时区证据后另批适配。未验证真实行情展示或启动服务。
