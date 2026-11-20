'use strict';

/** 多方法日线研究：复用授权连接，保留原指标，按方法独立展示与检验。 */
(function installMethods(root) {
  const ids=['ICT','PA','WYCKOFF','MEAN_REVERSION','ELLIOTT','ORDERFLOW'];
  let dialog=null, controller=null, report=null, returnFocus=null;

  /** 对全部行情文本与证据字段转义。 */
  function esc(value) { return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

  /** 缺失数字始终显示破折号。 */
  function num(value,digits=2) { return typeof value==='number'&&Number.isFinite(value)?value.toLocaleString('zh-CN',{maximumFractionDigits:digits,minimumFractionDigits:digits}):'—'; }

  /** 将真实比例转为百分比，不把null转换成零。 */
  function pct(value) { return typeof value==='number'&&Number.isFinite(value)?num(value*100)+'%':'—'; }

  /** 读取父看板现有连接，令牌只留在内存与请求头中。 */
  function connection() { return typeof state!=='undefined'?{endpoint:state.endpoint,token:state.token,market:state.market,date:state.date}:{}; }

  /** 构造受限研究端点，禁止非HTTPS远程及URL凭据。 */
  function createURL(config,params) {
    const url=new URL(config.endpoint||'/api/methods',root.location.href);
    if(url.username||url.password||!(url.protocol==='https:'||url.protocol==='http:'&&['127.0.0.1','localhost','[::1]'].includes(url.hostname))) throw new Error('请连接HTTPS行情服务或本机服务。');
    url.pathname=/\/snapshot$/.test(url.pathname)?url.pathname.replace(/\/snapshot$/,'/methods'):'/api/methods';url.search='';url.hash='';
    for(const [key,value] of Object.entries(params))url.searchParams.set(key,value);
    url.searchParams.set('market','US');url.searchParams.set('timeframe','1d');return url;
  }

  /** 校验请求身份、确认时点、日期和有限数值，拒绝串日与错误结果。 */
  function validateReport(value,expected) {
    if(!value||value.source!=='flowdesk-methods'||value.schemaVersion!==1||value.symbol!==expected.symbol||value.asOf!==expected.asOf||value.market!=='US'||value.timeframe!=='1d')throw new Error('研究响应标的或日期不匹配。');
    if(!Array.isArray(value.dates)||value.dates.length>5000||!Array.isArray(value.price)||value.price.length!==value.dates.length)throw new Error('日线样本无效。');
    if(value.dates.some((d,i)=>!/^\d{4}-\d{2}-\d{2}$/.test(d)||d>value.asOf||i>0&&d<=value.dates[i-1]))throw new Error('日期乱序或包含未来数据。');
    if(value.effectiveAsOf!==(value.dates.at(-1)??null))throw new Error('日线有效日期不一致。');
    for(const id of ids){
      const method=value.methods?.[id];
      if(!method||method.id!==id||!Array.isArray(method.events)||method.events.some(e=>!Number.isInteger(e.index)||e.index<0||e.index>=value.dates.length||e.confirmIndex!==e.index||e.date!==value.dates[e.index]))throw new Error('方法事件确认时间无效。');
    }
    let count=0;
    /** 对有界报告树检查Infinity/NaN，避免图表与绩效呈现伪值。 */
    function walk(item,depth=0){
      if(++count>2000000||depth>25||typeof item==='number'&&!Number.isFinite(item))throw new Error('研究报告包含无效数值或超过上限。');
      if(item&&typeof item==='object')Object.values(item).forEach(v=>walk(v,depth+1));
    }
    walk(value);return value;
  }

  /** 表格始终带标题并由滚动容器承接窄屏内容。 */
  function table(headers,rows,title){
    return '<div class="ind-table"><table><caption>'+esc(title)+'</caption><thead><tr>'+headers.map(h=>'<th>'+esc(h)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(v=>'<td>'+esc(v)+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
  }

  /** 固定来源也校验HTTPS，文本不能变成可执行链接。 */
  function sourceLink(url){
    try{const link=new URL(url);if(link.protocol==='https:')return '<a href="'+esc(link.href)+'" target="_blank" rel="noopener noreferrer">方法来源 ↗</a>';}catch{/* 无效来源以缺失呈现。 */}
    return '来源不可用';
  }

  /** 保持操作确认与观察候选有明确视觉区分，不合成为胜率评分。 */
  function cards(value){
    return '<div class="methods-cards">'+ids.map(id=>{
      const m=value.methods[id], primaries=m.events.filter(e=>e.layer==='primary'), latest=primaries.at(-1);
      const latestToday=!value.quality.stale&&latest?.date===value.effectiveAsOf;
      let state=id==='ORDERFLOW'?(m.orderFlow.status==='available'?(m.orderFlow.directionReliable?'逐笔估算 / 仍需核验':'逐笔存在 / 方向不足确认'):'逐笔缺失'):id==='ELLIOTT'?(m.wave?'历史几何候选 / 仅观察':'没有合规几何候选'):value.quality.stale?'日线滞后 / 仅历史参考':latestToday?(latest.direction>0?'有效日线看涨确认':'有效日线转弱确认'):'有效日线无操作确认';
      return '<article class="methods-card"><div class="methods-card-head"><h3>'+esc(m.name)+'</h3><span class="methods-state">'+esc(state)+'</span></div><p>'+esc(id==='ORDERFLOW'?m.orderFlow.reason:latest?'历史最近：'+latest.date+' · '+latest.label:'当前样本没有操作确认；不代表市场安全。')+'</p><details><summary>规则、限制与来源</summary><p>'+esc(m.rules)+'</p><p class="ind-muted">'+esc(m.limit)+'</p>'+sourceLink(m.source)+'</details></article>';
    }).join('')+'</div>';
  }

  /** 画出固定规则的独立净值和切分结果，不把回测排名当作推荐。 */
  function renderBacktest(method){
    const b=method.backtest;if(!b)return '<p class="ind-note">该方法只提供观察或数据核验，没有定义可验证的独立交易策略，因此不显示胜率。</p>';
    let html='<h3>固定规则历史检验</h3><p class="ind-muted">收盘确认，下一交易日开盘成交；最多持有20根。每边手续费 '+num(b.rules.feeBpsPerLeg,1)+'bps、滑点 '+num(b.rules.slippageBpsPerLeg,1)+'bps。正股多头、无杠杆；止损/目标只作参考，未模拟价格触发成交。</p>';
    html+='<dl class="ind-metrics">'+[['净收益',pct(b.metrics.totalReturn)],['最大回撤',pct(b.metrics.maxDrawdown)],['同段买入持有',pct(b.benchmark.totalReturn)],['已平仓 / 胜率',b.metrics.closedTrades+' / '+pct(b.metrics.winRate)]].map(([a,v])=>'<div><dt>'+esc(a)+'</dt><dd>'+esc(v)+'</dd></div>').join('')+'</dl>';
    html+=root.FlowdeskIndicators.chartSVG(b.equity.map(x=>x.date),[{name:'研究策略 USD',values:b.equity.map(x=>x.equity)},{name:'同段买入持有 USD',values:b.equity.map(x=>x.benchmark)}],[],'固定规则净值与买入持有');
    html+=table(['分段','开始','结束','净收益','最大回撤','基准','已平仓','胜率'],Object.entries(method.splits).map(([k,s])=>[({train:'前60% · 训练',validation:'中20% · 验证',holdout:'后20% · 留出'})[k],s.range.start,s.range.end,pct(s.metrics.totalReturn),pct(s.metrics.maxDrawdown),pct(s.benchmark.totalReturn),s.metrics.closedTrades,pct(s.metrics.winRate)]),'按时间切分，独立空仓开始、共享早期暖机；固定参数未优化');
    html+='<p class="ind-muted">各段独立开始；跨界未平仓只计市值，不记作胜场。当前复权与选股样本有偏差，留出不代表未来已知胜率。</p>';
    if(b.openPosition)html+='<p class="ind-note">期末仍持有：'+esc(b.openPosition.entryDate)+'入场，未实现盈亏 '+num(b.openPosition.unrealizedPnl)+' USD；未强制平仓。</p>';
    if(b.trades.length)html+=table(['确认日','买入日','买入价','卖出日','卖出价','净收益'],b.trades.slice(-30).reverse().map(t=>[t.entrySignalDate,t.entryDate,num(t.entryPrice),t.exitDate,num(t.exitPrice),pct(t.netReturn)]),'最近30笔已平仓；含成本');
    return html;
  }

  /** 展示逐笔分类覆盖及有限窗口CVD，缺失保持不可用。 */
  function flowHTML(method){
    const flow=method.orderFlow;
    if(flow.status!=='available')return '<p class="ind-note">'+esc(flow.reason)+'</p><button type="button" class="ind-button" id="methods-open-tape">打开尾盘逐笔研究</button>';
    return '<p class="ind-note">SIP真实逐笔 + 报价匹配估算 · '+esc(flow.start)+' → '+esc(flow.end)+'。仅20分钟，不是全日CVD。</p>'+(!flow.directionReliable?'<p class="ind-note">分类覆盖不足，或未知量足以改变净方向；不能凭该CVD确认买卖压力。</p>':'')+'<dl class="ind-metrics">'+[['主动买量估算',num(flow.buyVolume,0)],['主动卖量估算',num(flow.sellVolume,0)],['净量估算（股）',num(flow.netVolume,0)],['可分类覆盖',pct(flow.classifiedRatio)]].map(([a,b])=>'<div><dt>'+esc(a)+'</dt><dd>'+esc(b)+'</dd></div>').join('')+'</dl><p class="ind-muted">未知 '+num(flow.unknownVolume,0)+'股，排除 '+num(flow.excludedVolume,0)+'股。覆盖门槛不是分类准确率；无盘口吸收、撤单或冰山识别。</p>'+root.FlowdeskIndicators.chartSVG(flow.rows.map(r=>String(r.minute)),[{name:'窗口CVD估算 / 股',values:flow.rows.map(r=>r.cvd)}],[],'仅尾盘20分钟的累计主动量差估算');
  }

  /** 根据所选方法切换图表，候选与确认在表中保留原始证据时点。 */
  function renderMethod(){
    if(!report)return;
    const id=dialog.querySelector('#methods-selection').value,m=report.methods[id];
    const start=Math.max(0,report.dates.length-240), dates=report.dates.slice(start);
    let html='<h3>'+esc(m.name)+'</h3><p class="ind-muted">'+esc(m.rules)+'</p>';
    if(id==='ORDERFLOW')html+=flowHTML(m);
    else{
      const extra=id==='MEAN_REVERSION'?['MA20','BOLL_UPPER','BOLL_LOWER']:['MA20','MA50'];
      const lines=[{name:'收盘 USD',values:report.price.slice(start)},...extra.map(k=>({name:k,values:report.series[k].slice(start)}))];
      html+=root.FlowdeskIndicators.chartSVG(dates,lines,m.events.filter(e=>e.index>=start&&(e.layer==='primary'||id==='ELLIOTT')).map(e=>({name:e.label,index:e.index-start})),'最近240根日线与当前方法确认事件');
      if(id==='ELLIOTT'){
        const wave=m.wave;
        html+=wave?'<p class="ind-note">最近几何候选确认于 '+esc(wave.confirmedDate)+'，距有效日线 '+num(wave.ageBars,0)+'根；不是当前确定浪数。'+(wave.truncatedFifth?'存在第五浪截短候选。':'')+'未验证子浪细分，不据此自动交易。</p>'+table(['点位','极值日','首次确认日','价格'],wave.points.map((p,i)=>[String(i),p.date,p.knownDate,num(p.price)]),'极值在右侧2根之后才可用，不回填交易信号')+table(['检查','结果'],Object.entries(wave.checks).map(([key,v])=>[({wave2InsideOrigin:'2浪不越起点',wave3BeyondWave1:'3浪越过1浪终点',wave4NoOverlap:'4浪不重叠1浪',wave3NotShortest:'3浪不是最短',positiveMotiveLegs:'推动段方向一致'})[key],v?'满足':'不满足']),'仅普通推动浪几何规则'):'<p class="ind-note">没有满足所列约束的六摆点推动浪候选，不强行数浪。</p>';
      }
      html+=renderBacktest(m);
      html+='<h3>确认事件与候选 · '+m.events.length+'条</h3>'+table(['首次可知日','类别','事件','边界 / 区间','失效参考'],m.events.slice(-80).reverse().map(e=>[e.date,e.layer==='primary'?'操作确认':e.layer==='exit-only'?'持仓退出参考':'观察候选',e.label,e.evidence.boundary??e.evidence.brokenLevel??(e.evidence.lower!==undefined?num(e.evidence.lower)+' — '+num(e.evidence.upper):'—'),num(e.evidence.stopReference)]),'最近80条；观察候选不自动入场，图中信号只标确认日');
    }
    dialog.querySelector('#methods-detail').innerHTML=html;
    dialog.querySelector('#methods-open-tape')?.addEventListener('click',openTape);
  }

  /** 报告总览显示有效日、环境与独立结果；不计算六流派合成胜率。 */
  function render(value){
    report=value;
    const l=value.context.latest;
    let html='<div class="ind-result-heading"><h3>'+esc(value.symbol)+' · 多方法研究</h3><span>请求截至 '+esc(value.asOf)+' / 应完成 '+esc(value.expectedCompletedAsOf??'—')+' / 日线实际截至 '+esc(value.effectiveAsOf??'—')+'</span></div>';
    if(value.quality.stale)html+='<p class="ind-note">日线未覆盖应完成的交易日，下方仅为历史参考，不作为当前操作确认；未替换成其他日期。</p>';
    html+='<p class="ind-note">'+esc(({bullish:'偏多排列',bearish:'偏空排列','range-or-transition':'震荡或过渡',unknown:'样本不足，环境未知'})[value.context.regime])+' · ADX14 '+num(l.ADX14)+' · RSI14 '+num(l.RSI14)+' · 量比 '+num(l.RVOL)+'。先看环境，再检查确认条件；相似价量证据不是多份独立胜率。</p>';
    html+='<p class="ind-muted">'+esc(value.data.source)+' · '+esc(value.data.adjustment)+' · US已完成日线 '+value.sample.bars+'根；缺量 '+value.quality.missingVolumeBars+'根、零量 '+value.quality.zeroVolumeBars+'根。所有图形为规则子集，阈值为本项目固定约定。</p>';
    html+=cards(value)+'<label class="methods-selector">查看方法细节<select id="methods-selection">'+ids.map(id=>'<option value="'+id+'">'+esc(value.methods[id].name)+'</option>').join('')+'</select></label><div id="methods-detail"></div>';
    html+='<details class="methods-limit"><summary>研究边界与数据来源</summary><ul>'+value.warnings.map(w=>'<li>'+esc(w)+'</li>').join('')+'</ul><p>输入指纹 <code>'+esc(value.sha256)+'</code> · '+esc(value.engineVersion)+'</p></details>';
    dialog.querySelector('#methods-result').innerHTML=html;
    dialog.querySelector('#methods-selection').addEventListener('change',renderMethod);renderMethod();
  }

  /** 在父页面中打开已有SIP研究入口，不自动下载或操作账户。 */
  function openTape(){ close();root.document.getElementById('open-alpaca')?.click(); }

  /** 取消在途任务展示，旧响应不能覆盖后续日期或标的。 */
  function cancel(){ controller?.abort();controller=null;if(dialog){dialog.querySelector('#methods-run').disabled=false;dialog.querySelector('#methods-result').removeAttribute('aria-busy');} }

  /** 关闭弹窗并恢复触发控件焦点。 */
  function close(){ cancel();if(dialog){if(!report){dialog.querySelector('#methods-result').innerHTML='';dialog.querySelector('#methods-status').textContent='查询已关闭。';}dialog.close();}returnFocus?.focus(); }

  /** 发起受限查询，复用标准异步作业、认证与错误处理。 */
  async function query(event){
    event?.preventDefault();const form=dialog.querySelector('form');if(!form.reportValidity())return;
    cancel();const current=new AbortController();controller=current;report=null;
    const status=dialog.querySelector('#methods-status'), result=dialog.querySelector('#methods-result');
    const params={symbol:form.elements.symbol.value.trim().toUpperCase(),asOf:form.elements.asOf.value,initial:form.elements.initial.value,feeBps:form.elements.feeBps.value,slippageBps:form.elements.slippageBps.value};
    result.innerHTML='<div class="ind-skeleton" aria-label="研究加载中"></div>';result.setAttribute('aria-busy','true');dialog.querySelector('#methods-run').disabled=true;status.textContent='正在核验完成日线并分别重放规则…';
    try{
      const config=connection();if(config.market&&config.market!=='US')throw new Error('请切换至美股市场；多方法研究当前支持US已完成日线。');
      const value=await root.FlowdeskIndicators.request(createURL(config,params),progress=>{if(controller===current)status.textContent=progress.message||'研究计算中…';},current.signal,config.token);
      if(current.signal.aborted||controller!==current)return;
      validateReport(value,params);render(value);status.textContent='研究已完成 · 日线截至 '+(value.effectiveAsOf??'无有效样本')+' · 各方法独立检验，未优化参数。';
    }catch(error){if(!current.signal.aborted&&controller===current){result.innerHTML='';status.textContent=error.message||'研究失败，请重试。';}}
    finally{if(controller===current){controller=null;dialog.querySelector('#methods-run').disabled=false;result.removeAttribute('aria-busy');}}
  }

  /** 懒创建弹窗，日期使用美东市场日期，所有输入均有可访问标签。 */
  function open(trigger){
    if(!dialog){
      dialog=root.document.createElement('dialog');dialog.id='methods-dialog';dialog.className='ind-dialog methods-dialog';dialog.setAttribute('aria-labelledby','methods-title');
      dialog.innerHTML='<div class="ind-header"><div><div class="ind-kicker">STRUCTURE / CONTEXT / INDEPENDENT RESEARCH</div><h2 id="methods-title">六种方法，同一份行情</h2></div><button class="ind-button" id="methods-close" type="button" aria-label="关闭多方法研究">关闭 ×</button></div><p class="ind-muted">ICT、PA、威科夫、均值回归分别检验；波浪只列候选，订单流只用真实逐笔归档。保留原有指标，不拼接“共振胜率”。</p><form class="ind-form"><label>美股 / ETF代码<input name="symbol" value="QQQ" pattern="[A-Za-z][A-Za-z0-9.\\-]{0,14}" required maxlength="15"></label><label>研究截至日<input name="asOf" type="date" required></label><label>初始研究资本 USD<input name="initial" type="number" min="1" max="1000000000" value="10000" required></label><label>每边手续费 bps<input name="feeBps" type="number" min="0" max="100" step="0.1" value="5" required></label><label>每边滑点 bps<input name="slippageBps" type="number" min="0" max="100" step="0.1" value="5" required></label><div class="ind-actions"><button id="methods-run" class="ind-button ind-primary">读取与检验</button><button id="methods-cancel" class="ind-button" type="button">取消</button></div></form><p id="methods-status" role="status" aria-live="polite">输入标的和截止日期，使用已授权日线。不会下单。</p><div id="methods-result"></div>';
      root.document.body.append(dialog);dialog.querySelector('form').addEventListener('submit',query);
      dialog.querySelector('#methods-close').addEventListener('click',close);
      dialog.querySelector('#methods-cancel').addEventListener('click',()=>{cancel();dialog.querySelector('#methods-result').innerHTML='';dialog.querySelector('#methods-result').removeAttribute('aria-busy');dialog.querySelector('#methods-status').textContent='已取消查询。';});
      dialog.addEventListener('cancel',event=>{event.preventDefault();close();});dialog.addEventListener('close',cancel);
    }
    returnFocus=trigger||root.document.activeElement;
    const config=connection(),today=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
    dialog.querySelector('[name=asOf]').max=today;dialog.querySelector('[name=asOf]').value=config.date||today;
    if(!dialog.open)dialog.showModal();dialog.querySelector('[name=symbol]').focus();
  }

  /** 只响应本模块入口；市场或连接变化时清除旧报告。 */
  root.document.addEventListener('click',event=>{const entry=event.target.closest?.('#open-methods');if(entry)open(entry);});
  /** 外部行情切换时取消旧查询，防止旧报告跨市场保留。 */
  function reset(){cancel();report=null;if(dialog){dialog.querySelector('#methods-result').innerHTML='';dialog.querySelector('#methods-status').textContent='行情连接或市场已变化，请重新计算。';}}
  root.addEventListener('flow-market',reset);root.addEventListener('flow-disconnect',reset);
  root.FlowdeskMethods={open,close,query,render,createURL,validateReport};
})(window);
