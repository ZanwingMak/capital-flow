'use strict';
let chipsController=null;
/** 打开单股真实分布，历史看板沿用所选日期，不偷偷切换到今天。 */
function openChips(symbol=marketConfig().example) {
  $('detail-dialog').close();
  $('chips-symbol').value=symbol;
  $('chips-date').max=marketDate();
  $('chips-date').value=state.date||marketDate();
  $('chips-dialog').showModal();
  queryChips();
}
/** 展示原币资金净额及小单卖出占比，缺失值保留为空。 */
function renderChips(report) {
  const flow=report.orderDistribution,small=flow.groups?.find(item=>item.key==='small'),currency=escapeHtml(report.currency);
  $('chips-content').innerHTML='<div class="chips-heading"><strong>'+escapeHtml(report.symbol)+' · '+escapeHtml(report.date)+'</strong><span>'+escapeHtml(report.timezone)+(report.archived?' · 已留存样本':' · 最新读取')+'</span></div><div class="validation-note">持仓成本筹码：'+escapeHtml(report.costDistribution.reason)+' 以下仅展示真实订单规模资金，不推算持仓成本。</div><div class="chips-grid"><section><h3>订单规模资金分布</h3>'+(flow.status==='available'?'<p class="method-caption">截至 '+escapeHtml(flow.time)+' · 金额：'+currency+' · 常规交易时段累计</p><div class="chips-metrics"><div><span>小单累计净额</span><strong class="'+tone(small.net)+'">'+number(small.net,0,true)+'</strong></div><div><span>小单卖出 / 双向总额</span><strong>'+number(flow.smallSellShare,1)+'%</strong></div><div><span>大单 + 特大单净额</span><strong class="'+tone(flow.mainNet)+'">'+number(flow.mainNet,0,true)+'</strong></div></div><div class="chips-table"><table><thead><tr><th>规模</th><th>流入</th><th>流出</th><th>净额</th></tr></thead><tbody>'+flow.groups.map(item=>'<tr><td>'+item.label+'</td><td>'+number(item.in)+'</td><td>'+number(item.out)+'</td><td class="'+tone(item.net)+'">'+number(item.net,0,true)+'</td></tr>').join('')+'</tbody></table></div><p class="method-caption">卖出占比以流出 /（流入 + 流出）计算。超过50%表示小单净卖出，不表示亏损卖出；大额订单也无法直接确认机构身份。</p>':'<div class="research-empty">'+escapeHtml(flow.reason)+'</div>')+'</section></div><p class="method-caption">来源：富途 OpenD · 读取 '+escapeHtml(report.capturedAt)+'。历史资金分布仅支持本机已归档记录；未归档不会估算补齐。</p>';
}
/** 查询同市场同日期数据，支持失败重试，并取消过时请求。 */
async function queryChips(event) {
  event?.preventDefault();chipsController?.abort();
  const controller=new AbortController();chipsController=controller;
  $('chips-content').innerHTML='<div class="research-empty" role="status">正在核验日期并读取真实分布…</div>';
  $('chips-query').disabled=true;
  try {
    if(!state.endpoint)throw new Error('请先连接行情服务。可在本机 http://127.0.0.1:8788/ 使用已登录的 OpenD。');
    const symbol=marketSymbol($('chips-symbol').value.trim().toUpperCase()),date=$('chips-date').value,market=state.market;
    if(!symbol||!date)throw new Error('请填写有效股票代码和日期。');
    const endpoint=new URL(state.endpoint);endpoint.pathname=endpoint.pathname.replace(/\/snapshot$/, '/chips');endpoint.search='';
    endpoint.searchParams.set('market',market);endpoint.searchParams.set('symbol',symbol);endpoint.searchParams.set('date',date);
    const report=await requestJson(endpoint,()=>{},controller.signal);
    if(report.source!=='futu-opend'||report.market!==market||report.symbol!==symbol||report.date!==date||!report.orderDistribution||!report.costDistribution)throw new Error('数据日期或市场不匹配，已拒绝显示。');
    if(!controller.signal.aborted&&market===state.market)renderChips(report);
  } catch(error) {
    if(!controller.signal.aborted)$('chips-content').innerHTML='<div class="research-empty">'+escapeHtml(error.message)+'<br><button class="button" data-retry-chips>重试所选日期</button></div>';
  } finally {if(chipsController===controller){chipsController=null;$('chips-query').disabled=false;}}
}
/** 处理单股入口和重试按钮。 */
function handleChipsClick(event) {
  const button=event.target.closest('[data-chips]');
  if(button)openChips(button.dataset.chips);
  if(event.target.closest('[data-retry-chips]'))queryChips();
}
/** 离开行情连接或切换市场后取消旧查询并清空结果。 */
function resetChips() {chipsController?.abort();$('chips-content').innerHTML='';$('chips-dialog').close();}
$('chips-open').addEventListener('click',()=>openChips());
$('chips-form').addEventListener('submit',queryChips);
$('chips-dialog').addEventListener('close',()=>chipsController?.abort());
document.addEventListener('click',handleChipsClick);
window.addEventListener('flow-market',resetChips);
window.addEventListener('flow-disconnect',resetChips);
