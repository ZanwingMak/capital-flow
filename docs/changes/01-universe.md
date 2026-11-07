# 节点1：观察池解析

- 问题：旧单引号行头正则在当前前端双引号JSON数组上提取0项，真实静态观察池为48项且包含SPY。
- 行为：限定唯一的`const usUniverse`声明，JSON解码器只消费其后一个完整值，要求分号终止；校验非空数组、三列结构、代码、名称和类型，保序去重并要求SPY。解析失败在采集之前明确报错，不覆盖旧`validation.json`。
- 兼容性：不改变报告格式、采集和统计流程；不改变既有时间切分与交易日区块bootstrap。只接受当前明确的JSON数组，不执行任意JS表达式。
- 测试数据：真实前端静态数组，加显式合成的相邻数组、重复、空数组、畸形输入和旧报告；不访问行情或私有缓存。
- 红灯命令：`PYTHONDONTWRITEBYTECODE=1 /Users/maizhenying/Code/my_project/capital-flow/.venv/bin/python -m unittest discover -s tests -p 'test_analyze.py' -v`。5个测试方法，2项失败、12项错误（含子测试）；真实入口断言`0 != 48`。首次导入被SDK默认日志写入权限阻止，测试随后用合成SDK占位隔离导入副作用；不修改SDK或环境。
- 绿灯：同一命令，5个测试全部通过（含10个无效输入子测试）；`git diff --check`通过。
- 限制：未连接行情进行年度验证或重建报告；观察池仍有原有选择偏差，不能由解析修复推导策略盈利。
