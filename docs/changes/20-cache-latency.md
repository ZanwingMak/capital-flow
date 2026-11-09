# 历史缓存命中不再逐只等待资金接口限频

## 问题与最小修复

`fetch_snapshot` 原先在 `cached_daily_flow` 之前执行 1.05 秒资金接口限频，并刷新 `LAST_FLOW_REQUEST`。因此即使所有资金流来自本地历史文件，仍逐只等待，也会让随后真正需要补取的请求继承一次并未发生的远程请求时间。

现在先读取所选历史日的资金缓存，仅在缓存缺失或查询实时资金流时等待并更新上次请求时间。实际 `get_capital_flow` 请求，包括失败的尝试，仍占用原来的 1.05 秒间隔。历史价格补取 `daily_record` 的远程请求继续使用同一个限频时钟；补取后读取其写入的资金缓存不会再次等待。锁、单线程工作队列和 SDK 请求方式均保持原样。

## 可重复验证

新增 `tests/test_snapshot_cache_latency.py`，使用临时 JSON 文件、真实 pandas、固定日期、可推进的假时钟和假行情提供者。测试不连接 OpenD，不读取密钥、券商账户或真实持仓。测试数据目录位于 `~/.hermes/cache/scratch/flowdesk-review/portfolio-tests`。

49 个标的的缓存全部命中，初始时刻与上次资金请求时刻相同：

| 项目 | 修复前（先运行失败回归） | 修复后 |
| --- | --- | --- |
| 实际资金接口调用 | 0 | 0 |
| 累计模拟 sleep | 51.45 秒 | 0 秒 |
| 单次函数墙钟耗时（假时钟、不实际 sleep） | 0.0197 秒 | 0.0190 秒 |
| 回归断言 | 失败：51.45 != 0 | 通过 |

这些数字衡量代码中的人为等待，不代表真实上游网络或桌面端到端耗时。由于 sleep 被假时钟替换，墙钟耗时本身不包含旧代码的 51.45 秒等待。

8 项回归覆盖：全命中、混合命中和缺失、实时请求、历史补取后缓存命中、失败请求继续限频、非交易日拒绝、历史整包缓存 3600 秒有效期、整池后查询单标的复用原始文件。混合请求的两个远程调用仍相隔 1.05 秒，只有两次模拟等待，共 2.10 秒。

在仓库根目录执行独立回归（Python 使用主仓库已安装依赖的虚拟环境）：

```sh
TMPDIR=/Users/maizhenying/.hermes/cache/scratch/flowdesk-review/portfolio-tests /Users/maizhenying/Code/my_project/capital-flow/.venv/bin/python -m unittest discover -s tests -p test_snapshot_cache_latency.py -v
```

全量 Python 测试：210 项通过，56.755 秒。当前已有 `test_analyze.py` 在导入时使用 `patch.dict(sys.modules)`，可能回滚首次导入的 pandas/numpy 模块；随后原生 numpy 再导入会报 `cannot load module more than once per process`。直接全量 discovery 已观察到该问题。以下命令先预载 pandas，再运行全量测试，已真实通过；没有修改现有其他测试或生产依赖：

```sh
TMPDIR=/Users/maizhenying/.hermes/cache/scratch/flowdesk-review/portfolio-tests /Users/maizhenying/Code/my_project/capital-flow/.venv/bin/python -c 'import pandas; import unittest; suite = unittest.defaultTestLoader.discover("tests", pattern="test_*.py"); result = unittest.TextTestRunner(verbosity=1).run(suite); raise SystemExit(not result.wasSuccessful())'
```

## 缓存与外部依赖边界

整包缓存键仍为 `(market, tuple(symbols), selected_date)`，历史有效期 3600 秒、实时有效期 60 秒。标的顺序决定返回行顺序，不能只排序键而不同时恢复请求顺序。

单标的历史查询已经可以复用 `cached_daily_flow`、`cached_daily_quote` 的磁盘原始记录，本次消除了这条路径上不必要的等待。没有新增跨观察池的整包结果复用，避免扩展缓存新鲜度、部分失败、行顺序和返回元数据的语义。

整包缓存未命中时，历史查询仍调用 `get_context`、真实交易日历和批量市场快照（快照可补充名称）。本次没有移除这些依赖，也没有以本地有数据推断某天必然是交易日。用户端残留等待还可能来自连接、市场快照、历史价格补取或队列占用，需要另行测量；此修复只保证历史资金缓存命中不再占用资金接口的限频间隔。
