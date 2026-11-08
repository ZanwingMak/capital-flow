# FLOWDESK

**资金流与市场研究工作台。** 将行情、成交规模分类、历史资金事件、技术风险和期权观察放在同一个界面，帮助复核市场变化和交易判断。

支持美股 / ETF、港股及沪深 A 股的行情与资金流查询；部分研究模块目前仅支持美股。项目只读取市场数据，不下单、不接管券商账户。

[在线页面](https://zanwingmak.github.io/capital-flow/) · [本机启动指南](docs/local-startup.md) · [数据接入教程](https://zanwingmak.github.io/capital-flow/guide.html) · [调整记录](docs/changes/)

> GitHub Pages 托管的是静态页面，不提供公共行情后端。日常本机使用请启动项目并访问 `http://127.0.0.1:8788/`；线上页面连接真实数据需要自行部署 HTTPS 行情接口。

## 主要功能

| 模块 | 当前能力 |
| --- | --- |
| 资金流看板 | 多市场切换、观察池和自选标的；查看价格、涨跌、大单 / 特大单 / 中单 / 小单分类与净额。 |
| 历史与区间查询 | 按真实市场交易日切换日期，查看最近 X 个交易日的资金净额与累计变化。 |
| 资金事件研究 | 按方向、金额与历史分位数筛选日级或尾盘事件，对照后续价格及样本统计。 |
| 尾盘留存 | 留存运行期间可取得的分钟资金，检查尾盘 10 / 20 分钟窗口覆盖；不以日级净额推算缺失分钟。 |
| 技术与风险位置 | 均线、RSI、布林带、ATR、量能、历史回撤及恢复情况。 |
| 市场环境 | 基准趋势、市场宽度、VIX 和情绪数据，分别保留来源与有效时间。 |
| 小单与筹码观察 | 展示真实订单规模分类；没有券商成本分布时明确不可用，不从成交分类推断真实持仓成本。 |
| 美股期权观察 | 延时期权链、P/C、OI 集中与异动候选；检查覆盖及快照质量，数据不足时降级或停止展示。 |
| Alpaca 尾盘验证 | 使用有权限的 SIP 历史成交与报价估算尾盘大额买卖压力，与富途资金流分开观察。 |
| 历史有效性验证 | 提供资金与后续收益的描述性检验、日期区块重采样和时间切分；不把历史统计包装成稳定预测胜率。 |

## 快速开始

### macOS 一键启动

1. 安装 Python 3.10+ 和富途 OpenD，并在 OpenD 中本人登录、确认需要的市场权限。
2. 下载或克隆本仓库，在项目根目录双击 **[启动Flowdesk.command](启动Flowdesk.command)**。
3. 启动器检查依赖、复用或启动 OpenD、启动网页与 API，并打开本机页面。

重复双击会复用匹配本项目的健康服务；后台服务独立运行，关闭启动窗口后仍可访问。

也可以从项目目录执行：

```bash
./启动Flowdesk.command --no-browser  # 启动但不打开浏览器
./启动Flowdesk.command --status      # 仅检查状态
```

首次依赖安装、登录提示、端口冲突、日志和配置说明，见[完整本机启动指南](docs/local-startup.md)。

### Windows 与手动启动

macOS 的 `.command` 入口不适用于 Windows。Windows 使用当前源码创建本机虚拟环境，再运行 `server.py`；完整步骤见[数据接入教程](https://zanwingmak.github.io/capital-flow/guide.html#windows)。现有 Windows 下载包尚未同步最新改动，不应与当前源码版本混用。

macOS / Linux 手动启动示例：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py
```

手动启动需要自行保持 OpenD 和服务进程运行；macOS 一键启动器会协调这些步骤。

## 数据来源与运行结构

```text
浏览器页面 dist/
        │ HTTP API
        ▼
本机 Python 服务 server.py
        ├── 富途 OpenD：行情、资金分类、交易日历
        ├── Alpaca SIP：可选历史成交与报价
        ├── Cboe 等公开来源：VIX、延时期权等
        └── .data/：本地缓存、分钟留存与研究结果
```

| 来源 | 使用条件与边界 |
| --- | --- |
| 富途 OpenD | 默认 `127.0.0.1:11111`；需要本人登录和相应市场权限。接口连接成功不代表全部实时行情订阅可用。 |
| Alpaca | 本机环境变量或 `.env` 配置 `APCA_API_KEY_ID`、`APCA_API_SECRET_KEY`；具体 SIP 权限需实际查询验证。缺少它不阻止基础页面。 |
| 公开行情 / 情绪来源 | 可能延迟或不可用。期权来源未给明确时区、独立 OI 日期或完整覆盖时，不补造信息，也不视作当前可靠信号。 |

默认网页和 API 共用 `127.0.0.1:8788`。公开仓库与 GitHub Pages 不包含个人持仓、券商成交、访问密钥或本地缓存。`.env`、`.venv/`、`.data/` 均被 Git 忽略。

## 如何理解研究结果

- **“主力”是供应商的大单加特大单成交分类**，不表示识别到了机构身份、真实剩余持仓或持仓成本；小单同样不能直接等同散户账户。
- **事后复盘 `retrospective`** 是默认模式：截至日限制资金事件，后续结果可以使用更晚的价格，并显示观察上限。
- **严格模式 `strict-as-of`** 将价格路径与统计截断到所选交易日期；历史发布、修订和复权版本仍未完整追踪，不能将它当作已经证明的历史时点可得数据。
- **日级与尾盘异常筛选** 使用此前同口径、同方向样本，至少需要 10 个有效基线样本，且达到分位阈值和金额下限。样本不足导致零事件，不等于没有资金流出。
- **缺失、真实零值和陈旧数据分开显示**。缺量不写成零次放量下跌；OI 不完整时停止完整排名；陈旧或无法核验的期权快照不作为当前信号。
- **历史事件统计是描述性观察**。重叠事件、交易成本、选择偏差和数据修订都会影响结论；期权集中价也不保证形成支撑或阻力。

个人持仓管理、新闻 / 官方数据 / 财报整合及定时研究服务属于后续扩展或仓库外集成，不应误认为当前网页已经内置全部能力。

## 项目结构

| 路径 | 用途 |
| --- | --- |
| `dist/` | 原生 HTML / CSS / JavaScript 页面、图表、交互与接入教程。 |
| `server.py` | 页面及数据 API、行情请求与后台任务。 |
| `launch.py`、`启动Flowdesk.command` | macOS 一键启动、依赖检查、服务复用与状态检查。 |
| `research.py` | 分钟资金留存、尾盘窗口、资金事件与后续路径。 |
| `analyze.py` | 观察池解析与历史有效性验证。 |
| `intelligence.py` | 技术、市场环境、情绪及期权观察。 |
| `alpaca_data.py` | Alpaca 历史成交 / 报价与尾盘压力估算。 |
| `chips.py` | 订单规模与小单观察。 |
| `tests/` | Python 和 Node 回归测试。 |
| `docs/` | 启动指南及分节点调整、验收记录。 |

## 开发与验证

先安装 `requirements.txt`；Python 测试中的历史分析模块还使用 SDK 的相关依赖。前端回归测试使用 Node.js 的内置测试运行器，建议 Node.js 18+。

```bash
.venv/bin/python -m unittest discover -s tests -v
node --test tests/test_intelligence_ui.js tests/test_research_ui.js
bash -n 启动Flowdesk.command
git diff --check
```

测试使用离线合成数据验证边界；不等于已验证全部真实行情权限、全天连续运行或所有平台。

## 文档与调整记录

- [本机启动与排查](docs/local-startup.md)
- [在线数据接入教程](https://zanwingmak.github.io/capital-flow/guide.html)
- [节点1：观察池解析](docs/changes/01-universe.md)
- [节点2：量能、期权覆盖与时效](docs/changes/02-intelligence-quality.md)
- [节点3：研究截止日与尾盘筛选](docs/changes/03-research-time-and-tail.md)
- [节点4：真实服务与网页验收](docs/changes/04-live-acceptance.md)
- [节点5：一键启动及验证](docs/changes/05-one-click-startup.md)
- [节点6：项目首页与启动指南整理](docs/changes/06-project-documentation.md)
