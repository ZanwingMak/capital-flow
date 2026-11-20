# 四站研究与市场背景工作流

本次核对 SqueezeMetrics、FinancialJuice、Webull 和 FRED 的公开页面、官方文档及访问条件。Flowdesk 新增「事件研究 → 宏观与市场结构」，集中查看宏观观测、聚合市场结构、来源状态和官方入口。研究背景不自动生成交易建议。

## 各站值得借鉴的能力

| 网站 | 主要用途 | Flowdesk 的应用 | 访问边界 |
| --- | --- | --- | --- |
| [SqueezeMetrics DIX / GEX](https://squeezemetrics.com/monitor/dix#gex) | 用日级暗池成交和期权模型理解标普市场结构 | 独立展示 DIX、GEX、标普指数、观测日；支持浏览器内手动导入官方 CSV | 默认不自动下载；官方条款限制未经书面许可的系统性数据采集。 |
| [FinancialJuice](https://www.financialjuice.com/home) | 新闻、语音快讯、经济日历；发布值、预期、前值及修订值的时序 | 在背景窗口提供官网、官方接口说明；继续使用私有事件证据记录核实后的新闻与宏观事件 | 新闻和日历有官方 REST / WebSocket API，密钥与订阅决定频道、延迟、历史和连接限制；本次未接入付费新闻流。 |
| [Webull](https://app.webull.com/) | 自选、图表、筛选、可配置工作区和交易研究工具 | 借鉴从观察池进入研究的工作流，把宏观与结构研究放进现有事件研究入口，沿用连接、日期、取消和键盘交互 | 网页本次显示登录入口；以官方产品介绍及开发文档核实功能。OpenAPI 行情需独立权限，客户端订阅不自动覆盖 Non-display API。未登录券商或抓取账户。 |
| [FRED](https://fred.stlouisfed.org/) | 宏观序列、单位、频率、来源和发布时间；ALFRED 历史版本 | 固定序列列表、逐项观测日期与来源、缺失降级和历史版本警示 | 无密钥公开端点可变；不能把观测所属日期当作首次发布时间，或把今天修订后的值当作历史当时已知。 |

## 指标口径

### DIX / GEX

根据 [SqueezeMetrics 官方说明](https://squeezemetrics.com/monitor/docs)，DIX 是标普成分股暗池卖空成交比例的美元加权聚合指标。卖空标记涉及做市商提供流动性的机制，不能直接解释为机构账户的净买入、实际做空仓位或订单流。其经济含义依赖供应商模型假设。

GEX 是供应商模型下的美元 gamma 暴露估计。正负号反映不同的潜在对冲反馈，不能据此确定接下来涨跌，也不能把这个标普聚合值当作 QQQ、SOXX 或单只股票的 gamma 墙。缺少持仓方向、合约规格、有效日期和模型口径时，不拼接其他期权数据冒充同一指标。

[使用条款](https://squeezemetrics.com/monitor/terms)明确限制未经书面许可的系统性采集、汇编和数据库建立。公开 CSV 下载按钮不等于可无限自动采集和再分发。默认只提供手动导入与官方链接；已取得适用书面许可的部署方，才可设置 `FLOW_SQUEEZEMETRICS_AUTHORIZED=1` 开启本机自动请求。环境变量只声明部署方已确认许可，不会替部署方取得授权。实际数据不打包进源码、静态页面或安装包，不提供公共数据镜像。

手动 CSV 在浏览器内解析，不上传、不写入本机台账或浏览器持久存储；关闭窗口或切换连接后需重新导入。数据列为 `date,price,dix,gex`。原始 DIX 为 0—1 比率，显示时才换成百分数；GEX 保留美元估计和负号。缺失不填零。只选不晚于截至日的观测，但这仍不证明该观测当时已经公开。

### FinancialJuice 的事件时序

[官方接口文档](https://stream.financialjuice.com/docs)定义新闻的 created / updated / deleted，以及日历的 changed / deleted。消息序号与新闻 / 事件 ID 是不同概念；需要按 ID 更新、按各频道序号续传，避免把新闻修订重复当成新消息。日历保留 `timeUtc`、`actual`、`forecast`、`previous` 和 `revision`；未发布的 actual 为 null。

将来接入时，应同时保留计划发布时间、首次接收时间和修订时间；只有同口径、同单位且确实存在预期值，才能计算超预期。不能从标题自动推断利多利空，也不能把断流后的旧快讯标为实时。此次仅实现官方入口和权限状态，尚无自动新闻、语音或经济事件推送。

### Webull 的工作区与数据权限

[官方桌面产品介绍](https://www.webull.com/trading-platforms/desktop-app)强调可调整布局、自选、技术图表、筛选和表现分析。适合借鉴「先观察，再研究，再记录依据」的交互，不需要把券商执行功能引入 Flowdesk。

[官方市场数据 API 概览](https://developer.webull.com/apis/docs/market-data-api/overview.md)说明 API 权限和 Non-display 订阅应单独核实。因此，本次不声称已经接入 Webull 报价、深度或主动买卖数据。成交量、盘口、成交规模分类和可验证的主动订单流继续保持各自口径。

### FRED 的观测与版本

关注国债收益率、期限利差、实际利率、信用利差、联邦基金利率，以及 CPI / 核心 PCE 指数。各项保留序列 ID、单位、频率、观测日期和官方来源。收益率的 Percent、期限差的 Percentage Points 与物价指数不能混用；指数水平不是同比通胀率。

FRED 公开下载取得的是当前版本数据。即使只筛选 `observationDate <= asOf`，也不能证明这些数值在 asOf 当日已知；月度指标尤其可能在次月发布并继续修订。响应显式标记 `pointInTime: false`，不送入策略回测或生成胜率。正式历史研究应使用 [ALFRED](https://alfred.stlouisfed.org/) / [FRED 实时期间参数](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html)核对历史 vintage 与实际发布时点。

公开 CSV 不可用时，可以从官方序列页严格读取最新观测，明确标记 `retrievalMode: latest-page`。这种回退只覆盖该页最新观测，早于该观测的历史截至日仍返回缺失，不伪造历史覆盖。接口失败、格式变化和无法解析的值均逐项返回不可用，不用其他供应商冒充 FRED。

[FRED 发布日历](https://fred.stlouisfed.org/releases/calendar)可辅助准备盘前事件清单。发布日历、指标所属日期与当前请求采集时间分别记录；节假日和月度数据较早的观测不等于服务故障。

## 使用顺序

1. 长线复核先检查收益率、实际利率与信用环境，并核对观测日；这些是持仓环境背景，不能替代公司基本面和风险预算。
2. 短线之前打开官方日历与快讯，确认事件时区、是否已经发布、预期与前值是否可比。未获授权的自动新闻保持未接入。
3. DIX / GEX 作为市场结构背景，与价格和成交证据并列。不同代理指标不能相加为「三重机构确认」。
4. 若要形成操作计划，使用现有私有事件证据与研究记录保留依据、反面证据和失效条件；私人持仓不发送给以上网站。

## 服务与数据边界

`GET /api/market-context?asOf=YYYY-MM-DD` 使用现有 Origin / Bearer 校验、后台任务与轮询。仅支持美国市场的背景序列；输入参数不能指定任意 URL 或 API key。固定官方来源并限制超时、响应大小、并发和缓存；失败保持 null，不回显上游异常原文。

返回包含 `source`、`schemaVersion`、`asOf`、`collectedAt`、`macro`、`positioning`、`sources` 和 `warnings`。访问时间不代表观测发布时间。来源权限、序列日期与缺失原因均可在窗口展开查看。部署仍需自行核实来源条款和每项第三方序列的使用限制，特别是 ICE 数据的再分发限制；本模块面向本机阅读研究，不附带数据分发授权。

桌面资源清单包含新模块与页面资源；源码变更是否已经进入正式安装包，以对应 GitHub Release 为准。GitHub Pages 仅提供静态界面，不能自动拥有本机服务或订阅权限。
