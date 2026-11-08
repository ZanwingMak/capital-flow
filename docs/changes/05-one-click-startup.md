# 节点5：macOS 一键启动

## 本次范围

新增 `启动Flowdesk.command` 和标准库启动器 `launch.py`，复用现有 `server.py` 同时提供页面与 API。健康响应保留原字段，增加 `app=flowdesk` 与项目目录 SHA-256 标识。启动器只监听本机，不改变行情计算、研究策略或交易逻辑。

## TDD 调整记录

以下命令均在项目根目录执行，使用现有 `.venv`，未安装依赖、连接真实服务或打开 App/浏览器。前两步执行时通过 `TMPDIR` 指向调用方提供的 scratch；后续用例只模拟文件边界，未创建临时文件。公开记录省略机器专属目录。

| 小步 | 实际命令主体 | 红灯 | 实现后结果 |
| --- | --- | --- | --- |
| 项目健康身份与服务识别 | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -p test_launch.py -v` | 导入失败：缺少 `launch` | 3 项通过 |
| 环境复用、首次创建与缺依赖安装 | 同上 | 8 项中 5 项错误：缺少环境引导函数 | 8 项通过 |
| Futu 已运行、缺 App、等待登录、远程目标与有界等待 | 同上 | 16 项中新增行为因缺函数失败（含子用例，共 14 个错误） | 16 项通过 |
| 后台脱离终端、端口冲突、提前退出与超时清理 | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -p test_launch.py` | 21 项，6 个错误、1 个失败：缺少服务启动函数 | 21 项通过 |
| 命令入口、部分就绪、可选 Alpaca 与只读状态 | 同上 | 28 项，9 个错误：缺少入口及状态报告函数 | 加 `-v` 运行，28 项通过 |
| 状态模式互斥、锁边界与真实 SDK 无写入导入 | 同上 | 32 项，2 个失败：状态模式可被内部启动参数覆盖；审计还将 `/dev/null` 误判为文件写入 | 参数模式互斥；审计仅允许空设备，32 项通过 |
| 健康标识导入的原平台兼容 | 同上 | 33 项，1 个错误：启动器顶层导入 Unix 专属 `fcntl` | 将锁模块改为按需导入，加 `-v` 运行，33 项通过 |

已完成的回归命令及结果：

- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -p test_intelligence.py -v`：13 项通过。
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -p test_research_api.py -v`：5 项通过。
- `node --test tests/*.js`：8 项通过。
- `/bin/bash -n 启动Flowdesk.command`、`git diff --check`、`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B launch.py --help`：退出码均为 0。

`tests/test_launch_files.py` 另有 4 项真实文件边界测试：含空格及中文目录下执行 shell、实际内核锁超时与恢复、双线程同时点击只创建一个合成服务、只读状态不创建文件。开发代理阶段因测试临时目录权限未执行，随后由独立验收者在可写临时目录补跑，4项全部通过。完整 Python 回归共72项通过，Node回归8项通过；没有将未执行用例计作成功。

## 实现约束

- 优先项目 `.venv`，首次才创建；缺少可导入且版本符合要求的 SDK 才运行项目环境的 pip，不升级全局 Python。安装失败隐藏第三方原始输出并非零退出。
- OpenD 只对明确的本机目标调用 macOS `open -g`。TCP 可连接不等于行情登录成功；独立进程只读核验 `get_global_state`，仅保留行情登录布尔值。核验进程有超时，SDK 默认文件及控制台日志被屏蔽，不读券商日志，不修改 `HOME`。
- 内核文件锁串行化同时双击，锁文件不删除，退出自动释放锁。健康身份不符则失败，不终止其他进程；失败清理仅针对本次创建的 `Popen` 子进程。
- 后台服务使用独立 session、关闭标准输入并将输出追加至 `.data/flowdesk.log`。PID 仅作记录，不用于终止服务；没有提供依赖不可靠 PID 的停止入口。
- `--status` 不获取启动锁、不创建环境、不启动服务/App、不打开浏览器；SDK 核验不写日志。Alpaca 只调用既有 `status()` 取得配置布尔值，始终说明权限未验证。Cboe 与 Alpaca 均不作为网页启动门槛。

## 验收边界

已由独立验收者完成真实本机验收：

- `./启动Flowdesk.command --no-browser` 首次运行退出0，启动本项目服务，网页健康响应包含正确项目身份；Futu行情登录为true。Alpaca显示配置齐全、权限未验证，没有暴露配置值。
- 第二次执行同一命令退出0，明确复用已有服务，监听PID未变。
- 启动命令已经退出后，服务仍可访问；其进程session ID等于自身PID，确认已与启动终端脱离。
- `./启动Flowdesk.command --status` 退出0，日志、PID和锁文件的大小及修改时间均未变化。
- 后台浏览器实际访问本机页面成功，品牌与两种研究模式正常，捕获的浏览器脚本异常为0。
- 完整回归命令为 `TMPDIR=<可写临时目录> PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -v`，72项通过；`node --test tests/test_intelligence_ui.js tests/test_research_ui.js`，8项通过；shell语法及差异检查通过。

此机已安装Python、项目依赖与OpenD，且行情已登录；首次联网安装、OpenD关闭后的App拉起及未登录流程仅做离线边界测试，未为测试主动退出用户已登录的OpenD。Finder图形界面的双击本身未操作，真实shell入口已执行且具备可执行权限，含空格目录行为由文件测试验证。没有声称全部行情订阅权限均已验证；本次不更新Windows分发包、不申请系统权限、不新增系统自启。
