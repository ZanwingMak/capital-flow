# 自定义富途指标研究

引擎以用户提供且已做本地静态审计的公式为来源，在授权的 US 已完成日线 OHLCV 上计算。没有读取账户配置或持仓，不依赖网络。**这是暂定兼容性实现，尚未通过富途逐根输出认证**；源码表达式一致和前缀因果性通过，不等于富途边界语义认证。

## 指标与来源

`indicator_specs.py` 保存8项来源目录、原始 ftindex 文件 SHA256、提取公式 SHA256、wire字段、源版本、参数与确认延迟。只纳入计算赋值，不携带二进制导出、截图或机器路径。六项计算共532条赋值；长短趋势各249条，包括原本没有绘制文字但仍被依赖的蜘蛛、三K分型、legacy条件及显示层过滤。

| 指标 | 实际实现 | 原生买卖事件 | 首发限制 |
| --- | --- | --- | --- |
| GZRX1 | MA5/10/30/60/90/180 | 无 | 参数来自原文件编码，不制造交叉策略 |
| GZRX3 | MA55/60/65/120/250 | 无 | 完整窗口 |
| LDR | H/L的EMA25/90、C的EMA200、绘图间隙LGAP | 无 | EMA种子受加载起点影响 |
| GZRZH | 11条MA与LDR；MA200和EMA200分别计算 | 无 | 名称沿用来源；不推断资金或机构身份 |
| QUSHI-CHANG | 10-28实际长趋势计算链与原可见确认事件 | 有 | DATAOK最低120根；新增执行持有上限40根 |
| QUSHI-DUAN | 10-28实际短趋势计算链与原可见确认事件 | 有 | DATAOK最低60根；新增执行持有上限20根 |
| CL2 | 审计目录；数值图与回测禁用 | 原源码有，尚未移植 | 最终笔/中枢跨历史插值会回画；需移植逐根事件及失效日志，默认first_bar=confirm_bar+1 |
| SRJ | 审计目录；数值图与回测禁用 | 无完整交易策略 | 最新水平覆盖最后60根会回画；需移植持久化逐根区域；右侧3根枢轴确认后再一根参与区域 |

当前原始目录的长、短提取公式分别与10-28同名TXT全文相同。版本目录关联为`2026-10-28.2`，同时固定公式哈希；不能称10-28修复了这两个当前原文件的未来函数。LDR与10-27源码一致；GZRZH只差空行；其余四项没有10-28修订来源。CL2/SRJ的提取Python仅用于审阅，未执行、导入或以eval/exec加载。

## 数值与信号契约

- 只支持US、`1d`，最多5000根，日期必须唯一且严格升序。缺OHLC、非正价格、非法高低范围、负量及非有限数值报错；缺量保留null、零量保留0并使量价确认不成立。引擎不自行验证交易所缺根或当前K线是否收盘，调用方负责已完成日线及交易日历。
- 安全Pratt解析器只接受固定的赋值、数字、变量、算术/比较、AND/OR/NOT以及明确白名单函数。有公式体积、token、嵌套、赋值及窗口界限。HTTP不接受公式或文件路径。
- MA、LLV、HHV、COUNT、SUM和STDP要求完整已知窗口；STDP为总体标准差ddof=0。COUNT含当根。SUM窗口0指当前全部历史。窗口未知或越界返回null。
- EMA从首有效值播种，内部缺值当根为null，下一有效值重新播种。BARSCOUNT从首有效值起计根数，缺值当根为null。
- CROSS为当根严格大于且前根小于等于；首根未知。BARSLAST无事件为null；遇未知条件后，在新已知事件之前也保持未知。动态REF禁止未来引用，未知、负偏移和越界返回null；负常量REF在解析时拒绝。
- 使用三值逻辑：确定的False AND未知为False，True OR未知为True；其余未知传播。IF只选已知条件对应的分支。无保护除零为null；原公式的MAX(分母,0.000001)保留，不能把它当作数据质量通过。
- DATE每天唯一，保留原公式INTRAX启发式，日线AVGX为20根HLC3成交量加权均价。它不是逐笔VWAP，也不承诺日内等价。RVOL分母为前一根MA(V,20)，ATR为TR的简单MA14。
- 主显示优先级为TOPSIG > BOTSIG > PUTSIG > CALLSIG。冷却依据此前raw候选，包括被显示优先级抑制的候选。观察层保留原显示过滤；不会把raw候选冒充最终提示。
- MB枢轴在右侧第3根确认，动态REF比较实际前一枢轴；只在确认根输出事件，不回填枢轴日。收盘确认事件可能依赖当根全部OHLCV；盘中数据不属于此契约。
- 1000根仅是历史底的最低门槛；完整极值、回看和冷却链还需要更多历史。827根样本不能完成该链暖机。报告逐条给出firstKnownIndex、knownBars、lastKnown，历史底另设明确状态。

## 回测规则

纯函数`run_backtest(rows, events, start=0, end=None, ...)`的索引范围为`[start,end)`。默认10000 USD，手续费及滑点每边各5bps，各限定0至100bps。支持分数股、单仓、全资金、无杠杆、不做空；没有期权合约或期权收益。

CALLSIG/BOTSIG在收盘确认后，最早下一根开盘买入；PUTSIG/TOPSIG或持有上限到达后，最早下一根开盘退出。短趋势持有20根，长趋势40根，不能通过HTTP优化或覆盖。固定持有与反向信号是**新增执行约定**，原源码没有完整交易执行策略。首发不执行止损/目标；原CALLSL/CALLTP等仅为原公式参考序列。

每笔入价=实际开盘×(1+滑点)，出价=实际开盘×(1-滑点)，手续费按各边成交额计收；没有假设信号收盘成交。最后一根信号没有后续开盘时不成交。持仓期间新买信号不叠加资金。

每日净值=现金+持仓股数×当日收盘。期末持仓仅计价，不强制平仓、不算已平仓胜负；胜率分母只含已平仓交易，没有时为null。回撤从初始资本计入首笔费用；exposure为收盘持仓根数/区间根数，turnover为双边成交额合计/初始资本。夏普采用252日年化、零无风险利率；不足30根或日收益标准差≤1e-12返回null。未模拟最低佣金、税费、借券、容量或停牌报价。

买入持有使用与策略相同的评价区间、初始资本、入场费用与滑点，从区间首开盘买入，期末收盘计价；不收取尚未发生的卖出费用。

默认在主事件已知且DATAOK成立的首个评价根之后按时间60%/20%/20%切分；最后一段为最终留出。也可同时指定验证与留出开始日期，必须是样本内交易日且严格递增。各段从空仓独立执行，不消费段前信号；指标沿用此前历史暖机。训练末跨界持仓保留未实现盈亏，不进入已平仓计数，也不读取下一段的退出成交。参数没有优化。

有效评价区间不足3根时仍提供全区间计价，但不生成空的训练/验证/留出段，并明确提示样本不足。服务对标的、日期、指标版本及切分日期先规范化，行情loader、日期截断和响应身份使用同一份已验证参数。

## 服务和离线CLI

`indicator_service.get_report(symbol, as_of, market, loader, ...)`只注入一次行情loader，不读密钥。loader接受`(symbol, as_of, market)`，返回日线数组或包含`rows`的对象；对象可携带symbol、market、source、adjustment、timezone、collectedAt。身份和时区不匹配会报错。先按as_of截断再计算；请求上界是asOf，实际最后数据日另在sample.end展示。全部输出严格JSON，无NaN/Infinity。

报告包含`series`、`events`、`rules`、8项`catalog`、来源哈希、数据快照哈希、`dataQuality`、`sample`、`backtest`、`splits`及限制说明。数据sha256为归一化截断后rows的排序键紧凑JSON哈希；不等同原输入文件字节哈希。来源basename和哈希保留，报告没有本机源文件路径。

```sh
python indicator_cli.py --input "$INDICATOR_HISTORY_FILE" --output "$INDICATOR_RESULT_FILE" \
  --indicator QUSHI-DUAN --fee-bps 5 --slippage-bps 5
```

输入为含symbol/asOf/rows的JSON或显式配合`--symbol`、`--as-of`的数组；输出不能覆盖输入，输入上限10MB。`--validation-start`和`--holdout-start`必须同时传入。真实行情及日级曲线只存本地授权结果目录，不放公开文档或仓库。

## 父项目接入：精确改动

以下改动由HTML/server/desktop负责者实施；本次没有修改这些文件。

1. 在HTML引入独立静态资产，并在合适的研究入口增加按钮：

```html
<link rel="stylesheet" href="indicators.css?v=20261109">
<script src="indicators.js?v=20261109" defer></script>
<button id="open-indicators" class="button" type="button">自定义指标研究</button>
```

脚本以委托事件懒挂载dialog；不需要更改已有弹窗或app.js。可直接调用`window.FlowdeskIndicators.open()`；可用`mount({getConnection,request})`注入宿主适配器。默认读取现有内存state的行情endpoint/token/market/date，或请求同源`/api/indicators`，不访问私有API。它自带202轮询，向同目录`jobs?id=...`查询，Bearer仅放Header。

2. `server.py`增加`import indicator_service`，将`/api/indicators`加入已有行情API受鉴权路径集合，保留其Origin和Bearer检查。静态允许列表增加`/indicators.js`、`/indicators.css`；health.features增加`indicators`。不要将该接口放入private_api。

3. 在已有函数区域添加以下包装，所有provider调用继续通过现有工作线程及intelligence_daily：

```python
def fetch_indicators(params):
    """用真实交易日历过滤未完成日线，再调用无网络指标服务。"""
    completed = intelligence_date(params['as_of'], params['market'])
    job_progress(0, 2, '读取已完成授权日线')

    def loader(symbol, as_of, market):
        """复用原日线provider，携带明确复权与时区元数据。"""
        return {
            'rows': intelligence_daily(symbol, min(as_of, completed), market),
            'symbol': symbol, 'market': market, 'source': 'Futu OpenD',
            'adjustment': 'QFQ/current-vintage',
            'timezone': MARKETS[market]['timezone'],
            'collectedAt': datetime.now(timezone.utc).isoformat(),
        }

    report = indicator_service.get_report(loader=loader, **params)
    job_progress(2, 2, '指标研究完成')
    return report
```

该包装保留请求asOf作为上界，盘中查询今天时sample.end显示最近已完成日；历史非交易日仍按现有intelligence_date报错。原日线loader约827根，历史大底不可能完整暖机，UI会明确说明。

4. 在鉴权之后、已有其他业务分支之前加入：

```python
if parsed.path == '/api/indicators':
    try:
        params = indicator_service.parse_request(
            parse_qs(parsed.query, keep_blank_values=True))
        key = ('indicators', tuple(sorted(params.items())))
        identity = submit_job(key, fetch_indicators, (params,))
        status, payload = job_result(identity)
        self.respond(status, payload)
    except ValueError as error:
        self.respond(400, {'error': str(error)})
    except RuntimeError as error:
        self.respond(503, {'error': str(error)})
    return
```

必须保留`keep_blank_values=True`，避免空费用参数被默默丢弃。所有重复和未知参数都被拒绝。允许查询键为symbol、asOf、market、indicator、timeframe、initial、feeBps、slippageBps、validationStart、holdoutStart；market仅US，timeframe仅1d。示例：`/api/indicators?symbol=IWM&asOf=2026-11-06&market=US&indicator=QUSHI-DUAN&feeBps=5&slippageBps=5`。

5. 桌面打包负责者在`desktop/resources.json`的applicationModules加入indicator_engine、indicator_specs、indicator_backtest、indicator_service、indicator_cli；requiredStatic加入indicators.js、indicators.css，并完成其资源审计与原生打包验证。本次没有修改desktop或启动服务。

## 已执行验证

先写数值、因果与成交测试并确认缺实现失败，再实现。指标范围现有35项Python测试及12项jsdom真实DOM测试，全部实际通过，覆盖手算预言、完整计算表达式固定哈希、长短版本差异、四类主信号完整链、动态MB右侧3根确认、raw冷却、缺量/零量、截断、注入拒绝、成本/跳空/次开盘、持仓计价、独立切分、CLI及异步UI状态。接手复核新增的两个回归先复现了日期规范值未用于截断、极短评价区间产生空切分的问题，修复后通过。

早前项目验证记录为Python共189项：186通过，3项会启动HTTP服务的桌面协议测试按本任务“禁止服务”限制跳过；Node共58项全部通过。本轮接手独立验证范围为上述35项指标Python测试和12项DOM测试；共享模块持续由其他协作者修改，全项目最终验收由整合方记录。DOM测试使用环境已有jsdom，通过NODE_PATH提供；没有安装依赖或启动浏览器。Python使用项目现有解释器，临时目录使用任务指定portfolio-tests目录。

六个真实数据集共4962根；六项指标36次完整数值计算、252次前缀对照全部一致，长短趋势12份真实CLI报告。原始计算表达式532条与审计提取文本逐条匹配。完整表现及样本限制见变更记录；没有做富途逐根对齐、网络请求、服务启动、git提交/推送或发布。
