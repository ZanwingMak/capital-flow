'use strict';
let alpacaBusy=false;
/** 获取当前已连接服务的 Alpaca 端点，本机页面可独立于富途快照使用。 */
function alpacaEndpoint(resource) {
  const base=state.endpoint||(['127.0.0.1','localhost'].includes(location.hostname)?location.origin+'/api/snapshot':'');
  if(!base)throw new Error('请先连接新版行情服务；GitHub Pages 本身不能运行行情后端或保管密钥。');
  const endpoint=new URL(base);endpoint.pathname=endpoint.pathname.replace(/\/snapshot$/, '/'+resource);endpoint.search='';return endpoint;
}
/** 打开独立的美股 SIP 尾盘窗口并检查服务端是否已配置密钥。 */
async function openAlpaca() {
  const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
  const part=name=>parts.find(item=>item.type===name).value;
  const yesterday=new Date(part('year')+'-'+part('month')+'-'+part('day')+'T12:00:00Z');yesterday.setUTCDate(yesterday.getUTCDate()-1);
  $('alpaca-date').max=yesterday.toISOString().slice(0,10);
  if(!$('alpaca-date').value)$('alpaca-date').value=state.market==='US'&&state.date?state.date:$('alpaca-date').max;
  $('alpaca-dialog').showModal();
  try{const report=await requestJson(alpacaEndpoint('alpaca-status'));$('alpaca-status').textContent=report.message;}
  catch(error){$('alpaca-status').textContent=error.message;}
}
/** 查询一个尾盘事件或依次验证三个示例标的，失败逐只保留且不显示旧结果。 */
async function queryAlpaca(event,batch=false) {
  event?.preventDefault();if(alpacaBusy||!$('alpaca-form').reportValidity())return;
  alpacaBusy=true;$('alpaca-content').replaceChildren();
  const date=$('alpaca-date').value,days=$('alpaca-days').value,threshold=Number($('alpaca-threshold').value)*10000;
  const symbols=batch?['MU','NVDA','SPY']:[$('alpaca-symbol').value.trim().toUpperCase()];
  document.querySelectorAll('#alpaca-form input,#alpaca-form select,#alpaca-form button').forEach(el=>{el.disabled=true;});
  try{
    for(const symbol of symbols){
      const section=document.createElement('section');section.className='alpaca-result';$('alpaca-content').append(section);
      section.textContent='正在查询 '+symbol+' · '+date+'…';
      try{
        const endpoint=alpacaEndpoint('alpaca-tail');for(const [key,value] of Object.entries({symbol,date,days,threshold}))endpoint.searchParams.set(key,value);
        const report=await requestJson(endpoint,progress=>{section.textContent=progress.message||'等待 SIP 历史数据…';});
        if(report.source!=='alpaca-sip'||report.feed!=='sip'||report.symbol!==symbol||report.date!==date||!report.paginationComplete||!Array.isArray(report.windows)||!Array.isArray(report.path))throw new Error('历史数据格式、日期或来源不匹配。');
        section.innerHTML=renderAlpaca(report);
      }catch(error){section.innerHTML='<h3>'+escapeHtml(symbol)+' · '+escapeHtml(date)+'</h3><p class="validation-error">'+escapeHtml(error.message)+'</p>';}
    }
  }finally{alpacaBusy=false;document.querySelectorAll('#alpaca-form input,#alpaca-form select,#alpaca-form button').forEach(el=>{el.disabled=false;});}
}
/** 显示独立口径的估算金额与分类覆盖率，不能判定方向时明确标注。 */
function renderAlpaca(report) {
  return '<div class="research-result-heading"><h3>'+escapeHtml(report.symbol)+' · '+escapeHtml(report.date)+'</h3><span>Alpaca SIP · 金额：万美元</span></div><div class="research-metrics">'+report.windows.map(item=>'<div><span>尾盘 '+item.minutes+' 分钟 · 估算大单净买入</span><strong class="'+tone(item.netEstimate)+'">'+number(item.netEstimate,2,true)+'</strong><small>'+(item.directionReliable?item.netEstimate>0?'估算买入占优':'估算卖出占优':'方向证据不足')+' · 金额分类覆盖 '+percent(item.classifiedRatio,1)+'</small><small>买入 '+number(item.buy,2)+' / 卖出 '+number(item.sell,2)+' / 无法判断 '+number(item.unknown,2)+'</small></div>').join('')+'</div><p class="method-caption">完整分页：'+report.tradeCount.toLocaleString()+' 笔成交、'+report.quoteCount.toLocaleString()+' 条报价 · 大额门槛：单笔 '+number(report.largeThresholdUSD/10000,2)+' 万美元 · 收盘集合竞价另列 '+number(report.closingAuctionAmount,2)+' 万美元</p><p class="research-explanation">'+escapeHtml(report.method)+'</p><h3 class="section-heading">尾盘逐分钟明细</h3><div class="path-table"><table><thead><tr><th>美东时间</th><th>估算买入</th><th>估算卖出</th><th>无法判断</th><th>估算净买入</th><th>排除成交金额</th><th>大额笔数 / 成交笔数</th><th>报价更新</th></tr></thead><tbody>'+report.rows.map(row=>'<tr><td>'+escapeHtml(row.time)+'</td><td class="positive">'+number(row.buy,2)+'</td><td class="negative">'+number(row.sell,2)+'</td><td>'+number(row.unknown,2)+'</td><td class="'+tone(row.netEstimate)+'">'+number(row.netEstimate,2,true)+'</td><td>'+number(row.excluded,2)+'</td><td>'+row.largeTrades+' / '+row.trades+'</td><td>'+row.quoteUpdates+'</td></tr>').join('')+'</tbody></table></div><h3 class="section-heading">此后每天的价格走向 · 已结束 '+report.availableDays+' / '+report.requestedDays+' 日</h3>'+pathChart(report.path)+'<div class="path-table"><table><thead><tr><th>交易日</th><th>日期</th><th>调整后收盘</th><th>单日涨跌</th><th>相对事件日累计</th></tr></thead><tbody>'+report.path.map(row=>'<tr><td>T+'+row.day+'</td><td>'+escapeHtml(row.date)+'</td><td>'+number(row.close,2)+'</td><td class="'+tone(row.change)+'">'+number(row.change,2,true)+(Number.isFinite(row.change)?'%':'')+'</td><td class="'+tone(row.cumulative)+'">'+number(row.cumulative,2,true)+(Number.isFinite(row.cumulative)?'%':'')+'</td></tr>').join('')+'</tbody></table></div><p class="research-muted">这是单个历史事件的观察，尚不能证明预测能力；未结束或缺失的交易日不补零。</p>';
}
/** 绑定尾盘验证入口，所有密钥只由本机服务读取。 */
function initializeAlpaca() {
  $('open-alpaca').addEventListener('click',openAlpaca);
  $('alpaca-form').addEventListener('submit',queryAlpaca);
  $('alpaca-batch').addEventListener('click',event=>queryAlpaca(event,true));
}
initializeAlpaca();
