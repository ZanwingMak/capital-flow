'use strict';
const intelligenceState={overview:null,stock:null,overviewController:null,stockController:null,autoKey:'',survey:null};

/** 安装市场风险与个股研究区域，沿用当前行情连接和所选市场。 */
function mountIntelligence(){
  const section=document.createElement('section');section.id='intelligence-hub';section.className='int-hub';
  section.innerHTML=`<div class="int-heading"><div><div class="eyebrow">MARKET REGIME / SENTIMENT / OPTIONS</div><h2>风险温度与期权结构<span class="int-tag">真实来源 · 分开观察</span></h2><p>先判断市场环境，再看个股位置。超卖、看空情绪和期权持仓集中，都不等于价格已经见底。</p></div><button class="button" id="int-overview-refresh" type="button">刷新市场观察 ↻</button></div>
  <div id="int-overview-status" class="int-status" role="status" aria-live="polite">连接行情服务后，读取市场基准与真实情绪数据。</div>
  <div class="int-market-layout"><div><div id="int-regime" class="int-regime"><span class="int-kicker">市场状态</span><strong>等待已完成日线</strong><p>依据基准趋势和成交量判断，不预设多头或空头获胜。</p></div><div id="int-benchmarks" class="int-benchmarks"></div></div><div class="int-context"><section id="int-vix"></section><section id="int-survey"></section><section id="int-breadth"></section></div></div>
  <div class="int-stock-heading"><div><div class="eyebrow">SINGLE STOCK / RISK FIRST</div><h3>个股位置、回撤与期权</h3></div><span>点击下方基准或任意标的详情，也可直接输入代码。</span></div>
  <form id="int-stock-form" class="int-stock-form"><label>股票 / ETF 代码<input id="int-stock-symbol" value="QQQ" list="path-symbols" required autocomplete="off" maxlength="18"></label><label>指标截至日<input id="int-stock-date" type="date" aria-label="个股指标截至日"></label><label>期权未来范围<select id="int-horizon"><option value="7">7个自然日</option><option value="30" selected>30个自然日</option><option value="60">60个自然日</option></select></label><button class="button primary" id="int-stock-query" type="submit">分析个股 ↗</button></form>
  <div id="int-stock-status" class="int-status" role="status" aria-live="polite">仅使用已结束日线；盘前、盘中展示最近已完成交易日的技术指标。</div><div id="int-stock-result"></div>
  <details class="int-method"><summary>数据口径与使用边界</summary><p>市场状态采用已完成日线；RSI为Wilder 14周期，布林带为20周期均线±2倍总体标准差，ATR为Wilder 14周期。放量下跌日指收盘跌幅至少0.2%且成交量高于上一交易日。历史回撤按同一复权口径的收盘价计算，只代表当前历史样本。</p><p>AAII是美国个人投资者的周度意见调查；小单资金是成交规模分类；P/C是期权Put/Call成交量或OI之比。三者均不是实际账户净多空比例，也不能用于计算“空头获胜率”。</p><p>期权墙指所选到期范围内、参考价上下20%内的持仓集中行权价，不保证形成支撑或阻力。OI不是盘中增仓；无做市商方向数据时不提供净GEX。异动是按量/OI筛选的候选，不识别买入、卖出或机构身份。</p><p>GitHub Pages只提供页面；完整行情需连接运行本项目新版代码的服务。数据源缺失、过期和历史不可查询时会明确标注，不补零或替换日期。</p></details>`;
  document.querySelector('.summary').insertAdjacentElement('afterend',section);
  $('int-stock-date').max=marketDate();$('int-stock-date').value=state.date||marketDate();
  $('int-overview-refresh').addEventListener('click',loadIntelligenceOverview);
  $('int-stock-form').addEventListener('submit',queryStockIntelligence);
  document.addEventListener('click',handleIntelligenceClick);
  window.addEventListener('flow-data',autoIntelligenceOverview);
  window.addEventListener('flow-market',resetIntelligence);
  window.addEventListener('flow-disconnect',resetIntelligence);
  renderIntelligenceEmpty();loadVerifiedSurvey();
  if(state.endpoint&&!state.busy)autoIntelligenceOverview();
}

/** 对每个模块明确展示不可用原因，不把缺失值显示为零。 */
function intelligenceEmpty(message){return '<div class="int-empty">'+escapeHtml(message)+'</div>';}

/** 只允许HTTPS来源链接，避免外部响应注入可执行链接。 */
function intelligenceSource(label,url){
  try{if(new URL(url).protocol==='https:')return '<a href="'+escapeHtml(url)+'" target="_blank" rel="noopener noreferrer">'+escapeHtml(label)+' ↗</a>';}catch{/* 缺失链接仍显示来源名。 */}
  return escapeHtml(label);
}

/** 格式化百分比并保留缺失状态。 */
function intelligencePercent(value,digits=1){return number(value,digits)+(Number.isFinite(value)?'%':'');}

/** 提示模块的数据是否过期，保留真实有效日期。 */
function intelligenceStale(report){return report?.status==='stale'?'<span class="int-stale">数据滞后</span>':'';}

/** 初始化缺失态，同时保留有日期的公开周度调查。 */
function renderIntelligenceEmpty(){
  $('int-benchmarks').innerHTML='';
  $('int-regime').innerHTML='<span class="int-kicker">市场状态</span><strong>等待已完成日线</strong><p>连接行情服务后判断，不预设空头或多头环境。</p>';
  $('int-regime').dataset.regime='pending';
  $('int-vix').innerHTML='<h3>VIX · 市场波动率</h3>'+intelligenceEmpty('待连接Cboe真实历史数据。');
  $('int-breadth').innerHTML='<h3>观察池涨跌广度</h3>'+intelligenceEmpty('待连接当前观察池行情。');
  renderRetailSurvey(state.market==='US'?intelligenceState.survey:null);
}

/** 读取经官方页面核验的周度事实样本，明确显示核验模式和过期状态。 */
async function loadVerifiedSurvey(){
  try{
    const response=await fetch('data/aaii-survey.json',{cache:'no-store'});if(!response.ok)return;
    const data=await response.json(),date=state.date||marketDate(),rows=(data.rows||[]).filter(row=>row.publishedDate<=date);
    const row=rows.sort((a,b)=>b.weekEnding.localeCompare(a.weekEnding))[0];if(!row)return;
    const age=(Date.parse(date)-Date.parse(row.publishedDate))/86400000;
    intelligenceState.survey={...row,source:data.source,url:data.url,verifiedAt:data.verifiedAt,mode:'verified-snapshot',status:age>10?'stale':'available',spread:row.bullish-row.bearish,bullBearRatio:row.bearish?row.bullish/row.bearish:null};
    if(!intelligenceState.overview&&state.market==='US')renderRetailSurvey(intelligenceState.survey);
  }catch{/* 不使用演示数据填充失败的调查。 */}
}

/** 渲染散户意见调查和多空比，避免解释为真实持仓。 */
function renderRetailSurvey(report){
  if(!report||!['available','stale'].includes(report.status)){$('int-survey').innerHTML='<h3>散户情绪 · AAII</h3>'+intelligenceEmpty(report?.reason||'AAII只调查美国个人投资者。');return;}
  const valid=[report.bullish,report.neutral,report.bearish].every(v=>Number.isFinite(v)&&v>=0&&v<=100);
  if(!valid){$('int-survey').innerHTML=intelligenceEmpty('调查字段缺失，未展示比例。');return;}
  $('int-survey').innerHTML='<h3>散户情绪 · AAII '+intelligenceStale(report)+'</h3><div class="int-survey-bars" role="img" aria-label="看多 '+number(report.bullish,1)+'%，中性 '+number(report.neutral,1)+'%，看空 '+number(report.bearish,1)+'%"><i class="int-bull" style="flex:'+report.bullish+'"></i><i class="int-neutral" style="flex:'+report.neutral+'"></i><i class="int-bear" style="flex:'+report.bearish+'"></i></div><div class="int-survey-values"><span>看多 <b>'+intelligencePercent(report.bullish)+'</b></span><span>中性 <b>'+intelligencePercent(report.neutral)+'</b></span><span>看空 <b>'+intelligencePercent(report.bearish)+'</b></span></div><div class="int-ratio"><span>看多 / 看空 <b>'+number(report.bullBearRatio,2)+'</b></span><span>多空差 <b class="'+tone(report.spread)+'">'+number(report.spread,1,true)+' pp</b></span></div><p class="int-caption">调查周截至 '+escapeHtml(report.weekEnding)+' · 发布 '+escapeHtml(report.publishedDate)+'<br>'+intelligenceSource('AAII官方调查',report.url)+' · '+(report.mode==='verified-snapshot'?'最近人工核验样本，非实时':'官方页面读取')+'<br>意见比例，不是持仓比例；对未来六个月的看法。</p>'+(report.warning?'<p class="int-caption int-warning">官网程序读取受限，已标明所用核验样本日期。</p>':'');
}

/** 构造同源研究端点，沿用连接令牌和历史日期。 */
function intelligenceEndpoint(path){
  if(!state.endpoint)throw new Error('请先连接新版行情服务。本机可打开 http://127.0.0.1:8788/，线上需配置HTTPS服务。');
  const url=new URL(state.endpoint);url.pathname=url.pathname.replace(/\/snapshot$/, '/'+path);url.search='';url.searchParams.set('market',state.market);return url;
}

/** 拒绝市场、标的或历史日期错配的响应。 */
function validateIntelligence(report,market,date,symbol=''){
  if(report.source!=='flowdesk-intelligence'||report.market!==market||!/^\d{4}-\d{2}-\d{2}$/.test(report.asOf||'')||(symbol&&report.symbol!==symbol))throw new Error('数据市场、标的或日期格式不匹配，未展示。');
  if(date&&date<marketDate()&&report.asOf!==date)throw new Error('返回日期与所选历史日期不同，已拒绝换日。');
}

/** 异步加载市场状态，每次查询取消旧请求并显示独立失败状态。 */
async function loadIntelligenceOverview(){
  intelligenceState.overviewController?.abort();const controller=new AbortController();intelligenceState.overviewController=controller;
  $('int-overview-refresh').disabled=true;$('int-overview-status').textContent='正在读取基准、市场情绪与观察池广度…';
  try{
    const market=state.market,date=state.date,url=intelligenceEndpoint('intelligence');
    if(date)url.searchParams.set('date',date);url.searchParams.set('symbols',state.rows.map(row=>row.symbol).join(','));
    const report=await requestJson(url,progress=>{$('int-overview-status').textContent=progress.message||'正在读取真实市场数据…';},controller.signal);
    validateIntelligence(report,market,date);if(controller.signal.aborted||market!==state.market)return;
    intelligenceState.overview=report;renderIntelligenceOverview(report);
  }catch(error){if(!controller.signal.aborted)$('int-overview-status').textContent=error.message;}
  finally{if(intelligenceState.overviewController===controller){intelligenceState.overviewController=null;$('int-overview-refresh').disabled=false;}}
}

/** 更新市场风险、基准强弱、VIX、调查及观察池广度。 */
function renderIntelligenceOverview(report){
  const regime=report.regime;
  $('int-overview-status').textContent='已完成日线截至 '+report.asOf+' · 各情绪与快照采用独立有效时间 · 无统一“空头获胜率”';
  $('int-regime').dataset.regime=regime.state||'pending';
  $('int-regime').innerHTML='<span class="int-kicker">市场状态 · 已完成日线</span><strong>'+escapeHtml(regime.label||'暂不可判断')+'</strong>'+(regime.status==='available'?'<p>'+number(regime.bearishBenchmarks)+' / '+number(regime.validBenchmarks)+' 个有效基准处于偏空排列</p><ul>'+regime.checks.map(item=>'<li>'+escapeHtml(item)+'</li>').join('')+'</ul><details><summary>判断规则</summary><p>'+escapeHtml(regime.rule)+'</p></details>':intelligenceEmpty(regime.reason));
  $('int-benchmarks').innerHTML=Object.entries(report.benchmarks).map(([symbol,row])=>'<button class="int-benchmark" data-intelligence="'+escapeHtml(symbol)+'"><span>'+escapeHtml(symbol)+'<small>'+escapeHtml(row.asOf||'暂无数据')+'</small></span>'+(row.close?'<strong>'+number(row.close,2)+' <b class="'+tone(row.change)+'">'+intelligencePercent(row.change,2)+'</b></strong><div><span class="int-state '+(row.trend==='bearish'?'int-down':row.trend==='bullish'?'int-up':'')+'">'+({bearish:'偏空趋势',bullish:'偏多趋势',transition:'过渡 / 分化'}[row.trend]||'待判断')+'</span><span>RSI '+number(row.rsi14,1)+' · '+escapeHtml(row.rsiState)+'</span></div><p>距MA20 '+intelligencePercent(row.distanceMA20Pct)+' · 当前回撤 '+intelligencePercent(row.drawdown?.currentPct)+'</p><small>'+escapeHtml(row.source)+' '+intelligenceStale(row)+'</small>':intelligenceEmpty(row.reason))+'</button>').join('');
  const vix=report.vix;
  $('int-vix').innerHTML='<h3>VIX · 市场波动率 '+intelligenceStale(vix)+'</h3>'+(Number.isFinite(vix.value)?'<div class="int-large-value">'+number(vix.value,2)+'<span class="int-state '+(vix.value>=20?'int-down':'')+'">'+escapeHtml(vix.label)+'</span></div><p>较前值 '+number(vix.change,2,true)+' / '+intelligencePercent(vix.changePct,1)+'</p><p class="int-caption">'+intelligenceSource('Cboe收盘数据',vix.url)+' · '+escapeHtml(vix.asOf)+'<br>VIX度量隐含波动率，并非下跌概率。</p>':intelligenceEmpty(vix.reason));
  renderRetailSurvey(report.retailSurvey);
  const b=report.breadth;
  $('int-breadth').innerHTML='<h3>观察池涨跌广度</h3>'+(b.status==='available'?'<div class="int-breadth-values"><span class="positive">'+number(b.up)+'<small>上涨</small></span><span class="negative">'+number(b.down)+'<small>下跌</small></span><span>'+number(b.flat)+'<small>持平</small></span></div><p>涨 / 跌家数比 '+number(b.advanceDeclineRatio,2)+' · 覆盖 '+number(b.valid)+' / '+number(b.requested)+'</p><p class="int-caption">'+escapeHtml(b.phase)+' · '+escapeHtml(b.time)+'<br>'+escapeHtml(b.scope)+'</p>':intelligenceEmpty(b.reason));
}

/** 同一市场日期在快照刷新后自动加载一次，避免反复拖慢资金接口。 */
function autoIntelligenceOverview(){
  if(!intelligenceState.stock&&!intelligenceState.stockController)$('int-stock-date').value=state.date||marketDate();
  const key=[state.market,state.date,state.endpoint,state.rows.map(row=>row.symbol).join(','),Math.floor(Date.now()/900000)].join('|');
  if(state.endpoint&&key!==intelligenceState.autoKey){intelligenceState.autoKey=key;loadIntelligenceOverview();}
}

/** 从列表入口打开个股分析，不改变总览的市场或日期。 */
function openStockIntelligence(symbol){
  if($('detail-dialog').open)$('detail-dialog').close();
  $('int-stock-symbol').value=symbol;$('int-stock-date').max=marketDate();$('int-stock-date').value=state.date||marketDate();
  $('int-stock-form').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});
  queryStockIntelligence();
}

/** 按所选代码与日期加载指标，过时响应和不同市场数据不进入页面。 */
async function queryStockIntelligence(event){
  event?.preventDefault();if(!$('int-stock-form').reportValidity())return;
  intelligenceState.stockController?.abort();const controller=new AbortController();intelligenceState.stockController=controller;
  intelligenceState.stock=null;$('int-stock-result').innerHTML='';
  $('int-stock-query').disabled=true;$('int-stock-result').classList.add('int-loading');$('int-stock-status').textContent='正在读取完整日线、回撤与期权链…';
  try{
    const market=state.market,symbol=marketSymbol($('int-stock-symbol').value),date=$('int-stock-date').value,url=intelligenceEndpoint('stock-intelligence');
    url.searchParams.set('symbol',symbol);url.searchParams.set('horizon',$('int-horizon').value);if(date)url.searchParams.set('date',date);
    const report=await requestJson(url,progress=>{$('int-stock-status').textContent=progress.message||'正在查询真实数据…';},controller.signal);
    validateIntelligence(report,market,date,symbol);if(controller.signal.aborted||market!==state.market)return;
    intelligenceState.stock=report;renderStockIntelligence(report);
    $('int-stock-status').textContent=symbol+' · 已完成日线截至 '+report.asOf+' · 期权报价与OI有效时间另列';
  }catch(error){if(!controller.signal.aborted)$('int-stock-status').textContent=error.message;}
  finally{if(intelligenceState.stockController===controller){intelligenceState.stockController=null;$('int-stock-query').disabled=false;$('int-stock-result').classList.remove('int-loading');}}
}

/** 生成有清晰单位和缺失状态的技术指标。 */
function intelligenceMetric(label,value,note='',css=''){return '<div class="int-metric"><span>'+escapeHtml(label)+'</span><strong class="'+css+'">'+value+'</strong><small>'+escapeHtml(note)+'</small></div>';}

/** 绘制真实日线收盘或回撤曲线，空数据不连线填补。 */
function intelligenceLineChart(rows,key,label){
  const data=rows.filter(row=>Number.isFinite(row[key]));if(data.length<2)return intelligenceEmpty('有效历史不足，暂无曲线。');
  const w=900,h=160,left=58,right=15,top=18,bottom=25,min=Math.min(...data.map(row=>row[key])),max=Math.max(...data.map(row=>row[key])),pad=Math.max((max-min)*.1,key==='close'?max*.005:.1),low=min-pad,high=max+pad;
  const x=i=>left+i/Math.max(1,rows.length-1)*(w-left-right),y=v=>top+(high-v)/(high-low)*(h-top-bottom);
  let path='',joined=false;rows.forEach((row,i)=>{if(!Number.isFinite(row[key])){joined=false;return;}path+=(joined?' L':' M')+x(i).toFixed(2)+','+y(row[key]).toFixed(2);joined=true;});
  return '<svg class="int-line-chart" viewBox="0 0 '+w+' '+h+'" role="img" aria-label="'+escapeHtml(label)+'">'+[high,(high+low)/2,low].map(v=>'<line x1="'+left+'" x2="'+(w-right)+'" y1="'+y(v)+'" y2="'+y(v)+'"/><text x="'+(left-7)+'" y="'+(y(v)+4)+'" text-anchor="end">'+number(v,1)+(key==='drawdown'?'%':'')+'</text>').join('')+'<path d="'+path+'" fill="none" stroke="'+(key==='close'?'#a8d9f0':'#e3b27b')+'" stroke-width="2"/><text x="'+left+'" y="'+(h-4)+'">'+escapeHtml(rows[0].date)+'</text><text x="'+(w-right)+'" y="'+(h-4)+'" text-anchor="end">'+escapeHtml(rows.at(-1).date)+'</text></svg>';
}

/** 展示个股趋势、反弹质量和最大回撤，保持各模块互不依赖。 */
function renderStockIntelligence(report){
  const t=report.technical;
  let technical=intelligenceEmpty(t.reason||'日线不可用。');
  if(t.close){
    const dd=t.drawdown;
    technical='<div class="int-result-heading"><h3>'+escapeHtml(report.symbol)+' · 日线风险位置</h3><span>'+escapeHtml(t.source)+' · '+escapeHtml(t.asOf)+' '+intelligenceStale(t)+'</span></div><div class="int-metrics">'+intelligenceMetric('已完成收盘',number(t.close,2),number(t.change,2,true)+'%')+intelligenceMetric('RSI14 · '+t.rsiState,number(t.rsi14,1),'≤30超卖 / ≥70超买',t.rsi14<=30||t.rsi14>=70?'int-warning':'')+intelligenceMetric('布林带 %B',intelligencePercent(t.bollinger.percentB),'0%下轨 / 100%上轨')+intelligenceMetric('当前历史回撤',intelligencePercent(dd.currentPct),'样本前高 '+dd.peakDate,tone(dd.currentPct))+intelligenceMetric('ATR14 / 收盘',intelligencePercent(t.atrPct),'波动尺度，不是跌幅预测')+intelligenceMetric('近20日放量下跌',number(t.distributionDays20)+' 次','跌幅≥0.2%且量增')+'</div><div class="int-risk-line"><span class="int-state '+(t.trend==='bearish'?'int-down':t.trend==='bullish'?'int-up':'')+'">'+({bearish:'偏空趋势',bullish:'偏多趋势',transition:'过渡 / 分化'}[t.trend])+'</span><strong>'+escapeHtml(t.rebound)+'</strong><span>相对前20日均量 '+number(t.relativeVolume20,2)+' 倍</span></div>'+(t.flags.length?'<ul class="int-flags">'+t.flags.map(flag=>'<li>'+escapeHtml(flag)+'</li>').join('')+'</ul>':'')+'<div class="int-ma-list">'+Object.entries(t.ma).map(([period,value])=>'<span>MA'+escapeHtml(period)+' <b>'+number(value,2)+'</b></span>').join('')+'</div><details class="int-history" open><summary>历史回撤与恢复 · '+escapeHtml(dd.start)+' 至 '+escapeHtml(dd.end)+'</summary><div class="int-drawdown-windows">'+dd.windows.map(item=>'<span>近'+number(item.days)+'个交易日最大回撤 <b class="negative">'+intelligencePercent(item.maxDrawdownPct)+'</b></span>').join('')+'<span>整个样本最大回撤 <b class="negative">'+intelligencePercent(dd.maxDrawdownPct)+'</b></span></div><h4>最近252个已完成收盘样本</h4>'+intelligenceLineChart(dd.path,'close','已完成日线收盘价')+'<h4>相对样本历史前高的回撤</h4>'+intelligenceLineChart(dd.path,'drawdown','历史回撤曲线')+'<div class="int-table-scroll"><table><thead><tr><th>区间前高</th><th>低点日期</th><th>最大回撤</th><th>收复前高</th><th>交易日数</th></tr></thead><tbody>'+dd.episodes.map(row=>'<tr><td>'+escapeHtml(row.peakDate)+'</td><td>'+escapeHtml(row.troughDate)+'</td><td class="negative">'+intelligencePercent(row.depthPct)+'</td><td>'+escapeHtml(row.recoveryDate||'尚未收复')+'</td><td>'+number(row.durationBars)+'</td></tr>').join('')+'</tbody></table></div><p class="int-caption">仅为样本内按收盘价计算的回撤，不是从上市至今的最大回撤；未恢复区间的交易日数统计到当前样本末尾。</p></details>';
  }
  $('int-stock-result').innerHTML=technical+'<div class="int-small-orders" id="int-small-orders"></div><section class="int-options"><div class="int-result-heading"><div><div class="eyebrow">DELAYED OPTIONS / OPEN INTEREST</div><h3>期权墙、多空比与异动候选</h3></div><label class="int-expiry-label">到期范围<select id="int-expiry" aria-label="期权到期范围"></select></label></div><div id="int-options-result"></div></section>';
  renderSmallOrderPressure(report.smallOrders);renderOptionsIntelligence(report.options);
}

/** 用真实小单成交分布呈现压力，不冒充散户心理或亏损卖出。 */
function renderSmallOrderPressure(report){
  const small=report.groups?.find(row=>row.key==='small');
  $('int-small-orders').innerHTML='<h4>小单成交压力 · 散户情绪的规模代理</h4>'+(report.status==='available'&&small?'<div class="int-inline-metrics"><span>流入 <b>'+number(small.in)+'</b></span><span>流出 <b>'+number(small.out)+'</b></span><span>净额 <b class="'+tone(small.net)+'">'+number(small.net,0,true)+'</b></span><span>卖出 / 双向总额 <b>'+intelligencePercent(report.smallSellShare)+'</b></span></div><p class="int-caption">原币金额 · '+escapeHtml(report.time)+' · '+escapeHtml(report.scope)+'</p>':report.status==='net-only'?'<div class="int-inline-metrics"><span>日级小单净额 <b class="'+tone(report.net)+'">'+number(report.net,0,true)+'</b></span></div><p class="int-caption">原币金额 · '+escapeHtml(report.asOf)+' · '+escapeHtml(report.source)+'<br>'+escapeHtml(report.reason)+'<br>'+escapeHtml(report.scope)+'</p>':intelligenceEmpty(report.reason||'暂无对应日期的小单分布。'));
}

/** 设置可选到期日，切换仅重算同一份快照范围，不再请求行情。 */
function renderOptionsIntelligence(report){
  const select=$('int-expiry');
  if(!report||!['available','stale'].includes(report.status)){select.disabled=true;select.innerHTML='<option>暂无期权链</option>';$('int-options-result').innerHTML=intelligenceEmpty(report?.reason||'期权数据不可用。');return;}
  select.disabled=false;select.innerHTML='<option value="all">全部 · 未来'+number(report.horizonDays)+'天</option>'+report.expiries.map(date=>'<option value="'+escapeHtml(date)+'">'+escapeHtml(date)+'</option>').join('');
  select.addEventListener('change',renderOptionScope);renderOptionScope();
}

/** 绘制同一到期范围内的持仓量分布，不推算有方向的Gamma墙。 */
function optionWallChart(rows,spot){
  if(!rows.length)return intelligenceEmpty('参考价上下20%内无有效持仓量。');
  const width=860,left=88,right=75,height=rows.length*27+38,mid=425,max=Math.max(1,...rows.flatMap(row=>[row.callOI,row.putOI].filter(Number.isFinite)));
  return '<div class="int-wall-legend"><span class="int-call-dot">Call OI</span><span class="int-put-dot">Put OI</span><span>参考价 '+number(spot,2)+' · 只绘制持仓量最大的18档</span></div><div class="int-wall-scroll"><svg class="int-wall-chart" viewBox="0 0 '+width+' '+height+'" role="img" aria-label="按行权价划分的Call和Put未平仓量">'+rows.map((row,i)=>{const y=20+i*27,call=Number.isFinite(row.callOI)?row.callOI/max*(mid-left-20):0,put=Number.isFinite(row.putOI)?row.putOI/max*(width-mid-right-20):0;return '<text x="'+(left-14)+'" y="'+(y+12)+'" text-anchor="end">'+number(row.strike,2)+'</text><rect x="'+(mid-call)+'" y="'+y+'" width="'+call+'" height="16" fill="#79b9da"/><rect x="'+mid+'" y="'+y+'" width="'+put+'" height="16" fill="#ddb07d"/><text x="'+(width-right+12)+'" y="'+(y+12)+'">'+number(row.callOI)+' / '+number(row.putOI)+'</text>';}).join('')+'<line x1="'+mid+'" x2="'+mid+'" y1="6" y2="'+(height-15)+'"/></svg></div>';
}

/** 展示期权P/C、集中价、异动候选和完整口径，不将Call成交视为买方看多。 */
function renderOptionScope(){
  const report=intelligenceState.stock?.options;if(!report?.scopes)return;
  const scope=report.scopes[$('int-expiry').value];if(!scope)return;
  const wall=(rows,key)=>rows.length?rows.map(row=>'<span class="int-wall-pill">'+number(row.strike,2)+' <small>OI '+number(row[key])+'</small></span>').join(''):'<span class="muted">所选范围未发现有效集中价</span>';
  $('int-options-result').innerHTML='<p class="int-caption">'+intelligenceSource(report.source,report.url)+' · 源时间 '+escapeHtml(report.providerTimestamp)+'（原样显示） '+intelligenceStale(report)+'<br>标的最后交易时间 '+escapeHtml(report.underlyingLastTradeTime||'未提供')+' · 标的延时参考价 '+number(report.spot,2)+'<br>OI独立有效日期未提供，使用最近公布存量；报价、成交量和OI并非同一更新时间。</p><div class="int-metrics int-option-metrics">'+intelligenceMetric('Put / Call · 成交量',number(scope.putCallVolume,2),'合约数量比，不是多空持仓比')+intelligenceMetric('Put / Call · OI',number(scope.putCallOI,2),'清算后的未平仓存量比')+intelligenceMetric('有效范围内合约',number(scope.contracts),'缺失OI '+number(scope.missingOI)+' · 缺失成交量 '+number(scope.missingVolume))+intelligenceMetric('异动候选',number(scope.anomalyCount),'按成交量显示前20条')+'</div><div class="int-wall-summary"><div><span>上方 Call OI 集中</span>'+wall(scope.upperCallWalls,'callOI')+'</div><div><span>下方 Put OI 集中</span>'+wall(scope.lowerPutWalls,'putOI')+'</div></div>'+optionWallChart(scope.strikes,report.spot)+'<h4>期权异动候选 <span class="int-tag">量 ≥ 500 · 量 / OI ≥ 2 · 零OI单列</span></h4>'+(scope.anomalies.length?'<div class="int-table-scroll"><table><thead><tr><th>到期</th><th>类型</th><th>行权价</th><th>成交量</th><th>OI</th><th>量 / OI</th><th>IV</th><th>最后成交时间</th></tr></thead><tbody>'+scope.anomalies.map(row=>'<tr><td>'+escapeHtml(row.expiry)+'</td><td>'+escapeHtml(row.type)+'</td><td>'+number(row.strike,2)+'</td><td>'+number(row.volume)+'</td><td>'+number(row.oi)+'</td><td>'+number(row.volumeOIRatio,2)+(row.oi===0?' · 零OI':'')+'</td><td>'+intelligencePercent(row.ivPct)+'</td><td>'+escapeHtml(row.lastTradeTime||'未提供')+'</td></tr>').join('')+'</tbody></table></div>':intelligenceEmpty('所选范围内没有满足阈值的候选；不表示没有机构活动。'))+'<ul class="int-option-limits">'+report.limits.map(item=>'<li>'+escapeHtml(item)+'</li>').join('')+'</ul>';
}

/** 处理跨模块代码入口。 */
function handleIntelligenceClick(event){const button=event.target.closest('[data-intelligence]');if(button)openStockIntelligence(button.dataset.intelligence);}

/** 切换市场或断开连接后取消请求，避免保留其他市场的结果。 */
function resetIntelligence(){
  intelligenceState.overviewController?.abort();intelligenceState.stockController?.abort();intelligenceState.overview=null;intelligenceState.stock=null;intelligenceState.autoKey='';
  $('int-stock-result').innerHTML='';$('int-stock-result').classList.remove('int-loading');$('int-stock-query').disabled=false;$('int-overview-refresh').disabled=false;
  $('int-stock-symbol').value=state.market==='US'?'QQQ':marketConfig().example;$('int-stock-date').max=marketDate();$('int-stock-date').value=state.date||marketDate();
  $('int-overview-status').textContent='市场已切换；等待对应市场真实数据。';$('int-stock-status').textContent='选择标的，查看对应市场的已完成日线与回撤。';renderIntelligenceEmpty();
}

mountIntelligence();
