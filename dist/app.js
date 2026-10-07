'use strict';
// 截图样例逐行抄录；截图未提供日期，绝不标记为实时行情。
const sampleRows = [
['SPY','标普 500', 'etf',779.53,.61,10470,31499,39557,79556,2.11,42.9,777.96,781.62,-3968],
['QQQ','纳斯达克 100','etf',760.32,.54,1726,20164,13580,48371,1.54,32.4,759.10,762.86,-402],
['XLB','原材料','etf',49.69,.38,10689,-1396,-812,-427,1.40,47.1,49.45,49.97,-284],
['XLU','公用事业','etf',41.03,2.66,3133,891,-760,-756,1.72,98.4,40.41,41.04,-186],
['XLK','科技','etf',202.15,.61,1382,2037,834,1090,.90,17.3,201.92,203.25,-82],
['IWM','罗素 2000','etf',280.83,-.90,753,2557,565,4203,.63,1.8,280.76,284.64,1215],
['SMH','半导体','etf',632.02,-.30,-978,2926,1720,-679,.26,6.6,631.49,639.47,-3488],
['XLE','能源','etf',63.81,.58,67,1488,216,-2104,1.20,78.2,62.93,64.06,-476],
['XLF','金融','etf',53.99,.20,1468,-239,-9,-937,1.33,26.2,53.88,54.30,-44],
['IBIT','比特币','etf',48.45,-.23,2630,-1452,298,1704,.81,14.5,48.34,49.10,-154],
['DIA','道琼斯工业','etf',514.62,.49,1292,-233,-1779,-6619,1.26,45.4,513.49,515.98,-114],
['XLI','工业','etf',171.37,.74,-1026,2052,916,-83,.81,53.4,170.26,172.34,102],
['XLP','必需消费','etf',81.75,.87,276,476,661,649,1.39,72.7,81.03,82.02,87],
['XLC','通信服务','etf',111.69,.07,0,411,1460,610,.66,64.9,111.07,112.03,0],
['USO','原油','etf',144.99,.69,470,-209,-86,-1247,2.34,97.6,141.79,145.07,183],
['XLRE','房地产','etf',41.06,.97,0,189,136,-282,1.38,60.4,40.74,41.27,0],
['XLV','医疗保健','etf',166.96,-.24,-902,386,-360,-411,.96,35.6,165.82,169.03,141],
['SLV','白银','etf',55.48,.63,-169,-361,165,207,1.63,62.3,54.86,55.86,119],
['XLY','可选消费','etf',111.71,1.17,-814,-464,-562,819,1.06,95.5,110.65,111.76,-117],
['GLD','黄金','etf',382.03,.65,-174,-4442,-21820,-16806,.96,59.2,379.82,383.55,-91],
['SOXX','半导体行业','etf',588.98,-.09,-4271,-1712,-2075,-2124,.26,3.6,588.70,596.39,-1726],
['MSFT','微软','stock',531.26,1.16,5379,2857,-584,-7267,.55,35.5,528.82,535.69,1165],
['NBIS','Nebius','stock',250.16,7.56,2220,3933,9348,6071,.67,72.8,237,255.08,157],
['MRVL','迈威尔科技','stock',286.56,5.64,2594,733,1612,1109,.32,56.7,267.26,301.27,796],
['BE','Bloom Energy','stock',298.90,4.28,807,2103,1253,-282,.68,87.5,285.64,300.80,-42],
['MRNA','莫德纳','stock',188,-7.48,2590,234,-1764,-2809,3.71,1.2,187.69,212.19,-1671],
['AMZN','亚马逊','stock',256.34,1.96,589,1435,-2936,3628,.80,94,251.08,256.68,-552],
['TSLA','特斯拉','stock',380.91,.58,4544,-2619,-4472,-7111,.47,49.7,378.52,383.33,-542],
['GOOGL','谷歌','stock',348.44,.57,40,1807,-176,1547,.31,85.3,344.68,349.09,281],
['GEV','GE Vernova','stock',1032.77,4.32,-212,2001,265,-2480,1.02,65.3,995.05,1052.78,-44],
['VST','Vistra','stock',160.38,10.69,555,1001,855,-312,1.55,79.5,151.44,162.69,-75],
['MU','美光科技','stock',1047.18,-1.58,182,1118,1789,-15167,2.44,5.8,1045.51,1074.31,911],
['CRWV','CoreWeave','stock',91.94,5.20,990,274,2331,1494,.88,72.5,88.60,93.20,-371],
['ORCL','甲骨文','stock',145.11,1.85,584,576,43,1398,.44,39.5,143.92,146.93,586],
['PANW','Palo Alto Networks','stock',420.19,3.30,578,394,393,20,1.53,40.3,412,432.32,-82],
['CRWD','CrowdStrike','stock',278.92,2.29,-35,734,56,1292,.95,26.6,276,286.99,0],
['ALAB','Astera Labs','stock',387.83,7.03,-635,588,537,353,1.63,53.5,371.82,401.74,-62],
['LITE','Lumentum','stock',1131.03,3.61,-1262,1140,1799,4806,.36,88.4,1084.04,1137.20,-3],
['CEG','Constellation Energy','stock',300.07,12.13,-564,212,1270,1170,1.02,47.9,291.11,309.80,562],
['PLTR','Palantir','stock',193.19,2,-702,136,514,-2929,1.09,68.2,190.25,194.56,-842],
['AAPL','苹果','stock',334.22,.40,2254,-3676,-3869,-11553,.81,95.7,330.62,334.38,164],
['SMCI','超微电脑','stock',43.41,.51,-824,-702,-1026,-1117,1.87,22.7,43.02,44.74,-150],
['APP','AppLovin','stock',279.68,-.81,-997,-699,-448,-2773,1.56,42.5,276.66,283.76,-284],
['META','Meta Platforms','stock',742.63,.10,-376,-1589,-2153,401,1.39,54.4,736.69,747.60,35],
['AMD','超威半导体','stock',649.42,2.80,-5782,3589,40,-2919,.60,70.2,628,658.52,-792],
['AVGO','博通','stock',377.35,4.09,-2892,-2948,2524,-84,1.04,79.3,364.01,380.84,110],
['INTC','英特尔','stock',113.28,-2.50,-3455,-7865,-13926,-17589,1.40,5.6,112.99,118.20,37],
['NVDA','英伟达','stock',239.32,.18,-14027,687,-4325,-9632,.85,6.7,239.03,243.37,-2254]
];
const keys = ['symbol','name','type','price','change','big','super','mid','small','ba','dp','low','high','delta'];
/** 将截图数据转换为统一结构，补充明确的样例标记。 */
function makeSample() { return sampleRows.map(values => { const row=Object.fromEntries(keys.map((key,i)=>[key,values[i]])); return {...row,main:row.big+row.super,flowTime:'日期未提供 · 15:40 ET',flowStatus:'sample'}; }); }
/** 从本地读取非敏感偏好；禁用存储时使用默认值。 */
function readPreference(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } }
/** 保存自选代码，不持久化接口令牌。 */
function savePreference(key,value) { try {localStorage.setItem(key,JSON.stringify(value));} catch { /* 存储受限时仍保留当前会话。 */ } }
const state={rows:makeSample(),tab:'all',sort:'main',descending:true,mode:'sample',endpoint:'',token:'',busy:false,favorites:new Set(readPreference('flow-favorites',['SPY','QQQ','NVDA'])),previous:new Map(),meta:null,date:''};
/** 获取页面元素。 */
function $(id) { return document.getElementById(id); }
const moneyFields=['main','big','super','mid','small','delta'];
/** 输出带符号数值，缺失值保持为破折号。 */
function number(value,digits=0,signed=false) { if(!Number.isFinite(value))return '—'; return (signed&&value>0?'+':'')+value.toLocaleString('en-US',{minimumFractionDigits:digits,maximumFractionDigits:digits}); }
/** 安全编码来自接口的文本，防止 HTML 注入。 */
function escapeHtml(value) {return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
/** 根据有效金额和价格方向计算同向、背离或持平。 */
function direction(row) {if(state.mode==='history'&&!Number.isFinite(row.change)){if(!Number.isFinite(row.main))return {label:'待数据',css:'flat'};return Math.abs(row.main)<100?{label:'持平',css:'flat'}:row.main>0?{label:'净流入',css:''}:{label:'净流出',css:'divergent'};} if(!Number.isFinite(row.main)||!Number.isFinite(row.change))return {label:'待数据',css:'flat'}; if(Math.abs(row.main)<100||row.change===0)return {label:'持平',css:'flat'}; return Math.sign(row.main)===Math.sign(row.change)?{label:'同向',css:''}:{label:'背离',css:'divergent'}; }
/** 为正负金额选择文本颜色。 */
function tone(value) {return Number.isFinite(value)&&value!==0?(value>0?'positive':'negative'):'';}
/** 根据分类、搜索与资金方向过滤列表并稳定排序。 */
function visibleRows() { const query=$('search').value.trim().toUpperCase(),filter=$('direction').value; return state.rows.filter(row=>(state.tab==='all'||row.type===state.tab||(state.tab==='favorite'&&state.favorites.has(row.symbol)))&&(!query||row.symbol.includes(query)||row.name.toUpperCase().includes(query))&&(filter==='all'||(filter==='in'&&row.main>0)||(filter==='out'&&row.main<0)||(filter==='divergent'&&direction(row).css==='divergent'))).sort((a,b)=>{const x=a[state.sort],y=b[state.sort];if(x==null)return y==null?0:1;if(y==null)return -1;return (typeof x==='string'?x.localeCompare(y):x-y)*(state.descending?-1:1);}); }
/** 渲染单个数值格，空数据不以零填充。 */
function cell(row,key,digits=0,signed=false) {const value=row[key],heat=moneyFields.includes(key)&&Number.isFinite(value)&&value!==0?'heat-'+(value>0?'positive':'negative'):key==='change'?tone(value):''; return '<td class="flow-cell '+heat+' '+(key==='main'?'main-column':'')+'">'+number(value,digits,signed)+(key==='change'&&Number.isFinite(value)?'%':'')+'</td>';}
/** 绘制当前列表、汇总指标与资金排行。 */
function render() {const rows=visibleRows(); $('rows').innerHTML=rows.map(row=>'<tr><td><button class="star '+(state.favorites.has(row.symbol)?'selected':'')+'" data-favorite="'+row.symbol+'" aria-label="'+(state.favorites.has(row.symbol)?'取消自选':'加入自选')+' '+row.symbol+'">'+(state.favorites.has(row.symbol)?'★':'☆')+'</button></td><td><button class="symbol-button" data-detail="'+row.symbol+'">'+row.symbol+'<span class="name">'+escapeHtml(row.name)+'</span></button></td>'+cell(row,'price',2)+cell(row,'change',2,true)+cell(row,'main',0,true)+cell(row,'big',0,true)+cell(row,'super',0,true)+cell(row,'mid',0,true)+cell(row,'small',0,true)+cell(row,'ba',2)+'<td class="dp-cell">'+number(row.dp,1)+'<span class="dp-line"><i style="width:'+(Number.isFinite(row.dp)?Math.max(0,Math.min(100,row.dp)):0)+'%"></i></span></td>'+cell(row,'low',2)+cell(row,'high',2)+cell(row,'delta',0,true)+'<td><span class="direction-badge '+direction(row).css+'">'+direction(row).label+'</span></td></tr>').join('');
$('empty').hidden=rows.length>0;$('row-count').textContent='显示 '+rows.length+' / '+state.rows.length+' 个标的'; const valid=rows.filter(r=>Number.isFinite(r.main)),sum=valid.reduce((total,r)=>total+r.main,0),inflows=valid.filter(r=>r.main>0),sorted=[...valid].sort((a,b)=>b.main-a.main),topIn=sorted.find(r=>r.main>0),topOut=[...sorted].reverse().find(r=>r.main<0);
$('total-flow').textContent=valid.length?number(sum,0,true):'—';$('total-flow').className='summary-value '+tone(sum);$('inflow-count').innerHTML=inflows.length+'<small>/ '+valid.length+'</small>';$('inflow-sub').textContent='有效资金标的中 '+(valid.length?Math.round(inflows.length/valid.length*100):0)+'% 为净流入';
$('top-in').textContent=topIn?.symbol??'—';$('top-in').className='summary-value positive';$('top-in-sub').textContent=topIn?number(topIn.main,0,true)+' 万美元':'暂无净流入标的';$('top-out').textContent=topOut?.symbol??'—';$('top-out').className='summary-value negative';$('top-out-sub').textContent=topOut?number(topOut.main,0,true)+' 万美元':'暂无净流出标的';
$('count-all').textContent=state.rows.length;$('count-etf').textContent=state.rows.filter(r=>r.type==='etf').length;$('count-stock').textContent=state.rows.filter(r=>r.type==='stock').length;
const ranking=sorted.filter(r=>r.main>0).slice(0,5);$('ranking').innerHTML=ranking.length?ranking.map((row,i)=>'<div class="rank-item"><div class="rank-top"><span class="rank-number">0'+(i+1)+'</span><button class="text-button rank-symbol" data-detail="'+row.symbol+'">'+row.symbol+'</button><span class="rank-value positive">'+number(row.main,0,true)+'</span></div><div class="rank-bar"><i style="width:'+Math.round(row.main/ranking[0].main*100)+'%"></i></div></div>').join(''):'<p class="muted">当前列表暂无净流入。</p>';
document.querySelectorAll('[data-sort]').forEach(button=>{const key=button.dataset.sort;button.textContent=button.textContent.replace(/ [↓↑]$/,'')+(key===state.sort?(state.descending?' ↓':' ↑'):'');}); }
/** 打开标的详情，仅展示已获得的资金分布。 */
function showDetail(symbol) {const row=state.rows.find(r=>r.symbol===symbol);if(!row)return; $('detail-title').textContent=row.symbol+' / '+row.name; $('detail-description').textContent=state.mode==='history'?'富途 OpenD · '+state.date+' · 交易日汇总':(state.mode==='sample'?'截图静态样例 · ':'富途 OpenD · ')+(row.flowTime?'资金流截至 '+row.flowTime+' ET':'资金流时间暂不可用')+(state.mode==='live'&&row.quoteTime?' · 报价更新 '+row.quoteTime+' ET':'');const fields=[['big','大单'],['super','特大单 / 机构代理'],['mid','中单'],['small','小单']],max=Math.max(1,...fields.map(([key])=>Math.abs(row[key]||0))); $('detail-content').innerHTML='<div class="detail-stat"><span>主力净流入</span><strong class="'+tone(row.main)+'">'+number(row.main,0,true)+' 万美元</strong></div><div class="detail-stat"><span>价格 / 涨跌幅</span><span>'+number(row.price,2)+' / <b class="'+tone(row.change)+'">'+number(row.change,2,true)+'%</b></span></div><div class="detail-flow">'+fields.map(([key,label])=>'<div><div class="flow-label"><span>'+label+'</span><span class="'+tone(row[key])+'">'+number(row[key],0,true)+'</span></div><div class="bar-track"><i class="'+(row[key]<0?'out':'')+'" style="width:'+(Number.isFinite(row[key])?Math.abs(row[key])/max*100:0)+'%"></i></div></div>').join('')+'</div><p>金额单位：万美元。大额成交分类不代表已确认的机构身份。'+(row.flowStatus==='unavailable'?'此标的资金流暂不可用，请检查行情权限。':'')+'</p>'; if(state.mode==='history')$('detail-content').innerHTML+=historyTrend(row);$('detail-content').innerHTML+='<button class="button primary" data-path="'+row.symbol+'">查看此后每天走向 ↗</button>';$('detail-dialog').showModal(); }
/** 显示短暂操作提示。 */
function notify(message) {$('toast').textContent=message;$('toast').hidden=false;clearTimeout(notify.timer);notify.timer=setTimeout(()=>{$('toast').hidden=true;},3500);}
/** 校验接入数据并规范化数值，拒绝非美股或重复代码。 */
function normalizePayload(payload) {if(payload.source!=='futu-opend'||payload.unit!=='USD_10000'||!Array.isArray(payload.rows)||!payload.rows.length)throw new Error('接口响应不符合资金流格式，请使用项目提供的行情服务。');const seen=new Set();return payload.rows.map(row=>{if(!/^[A-Z][A-Z0-9.-]{0,14}$/.test(row.symbol)||seen.has(row.symbol))throw new Error('接口包含无效或重复的股票代码。');seen.add(row.symbol);const clean={symbol:row.symbol,name:String(row.name||row.symbol),type:row.type==='etf'?'etf':'stock',flowTime:String(row.flowTime||''),quoteTime:String(row.quoteTime||''),flowStatus:row.flowStatus,history:Array.isArray(row.history)?row.history.filter(item=>/^\d{4}-\d{2}-\d{2}$/.test(item.date)).map(item=>({date:item.date,main:typeof item.main==='number'&&Number.isFinite(item.main)?item.main:null})):[]};for(const key of ['price','change','big','super','mid','small','ba','low','high'])clean[key]=typeof row[key]==='number'&&Number.isFinite(row[key])?row[key]:null;clean.main=clean.big!==null&&clean.super!==null?clean.big+clean.super:null;clean.dp=clean.price!==null&&clean.low!==null&&clean.high!==null&&clean.high>clean.low?(clean.price-clean.low)/(clean.high-clean.low)*100:null;clean.delta=null;return clean;});}
/** 将常规时段资金流与盘前、盘后和隔日数据明确区分。 */
function flowSessionHint(times) {const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23',weekday:'short'}).formatToParts(new Date()),part=type=>parts.find(item=>item.type===type)?.value;const today=part('year')+'-'+part('month')+'-'+part('day'),minute=Number(part('hour'))*60+Number(part('minute')),closed=['Sat','Sun'].includes(part('weekday'))||minute<570||minute>=960;return !times.length?'资金流暂不可用':times[0].slice(0,10)!==today||closed?'展示最近常规时段资金流 · 按需刷新':'常规时段资金流 · 延迟取决于权限';}
/** 更新日期控件与已加载数据口径，历史视图隐藏当前报价列。 */
function updateHistoryControls() {const historical=state.mode==='history',dates=state.meta?.tradingDates||[],current=state.date||state.rows.map(row=>row.flowTime.slice(0,10)).filter(date=>/^\d{4}-\d{2}-\d{2}$/.test(date)).sort().at(-1),index=dates.indexOf(current);document.querySelector('.table-panel').classList.toggle('history-view',historical);$('history-date').disabled=state.busy;$('view-history').disabled=state.busy||!state.endpoint;$('latest-flow').disabled=state.busy||!state.endpoint;$('previous-day').disabled=state.busy||index<=0;$('next-day').disabled=state.busy||index<0||index>=dates.length-1;const divergent=$('direction').querySelector('[value="divergent"]');divergent.disabled=historical&&!state.rows.some(row=>Number.isFinite(row.change));if(divergent.disabled&&$('direction').value==='divergent')$('direction').value='all';const priceHeader=document.querySelector('[data-sort="price"]');priceHeader.textContent=historical?'收盘价（前复权）':'现价';}
/** 拉取最新或历史资金流；请求失败时保留上一次成功数据和日期。 */
async function refresh(requestedDate=state.date) {
if(state.busy)return;if(!state.endpoint){notify('请先接入行情服务后查询资金流。');return;}
state.busy=true;updateHistoryControls();$('refresh').disabled=true;$('refresh').textContent='正在获取…';$('error').hidden=true;$('rows').classList.add('loading');
try{const endpoint=new URL(state.endpoint);endpoint.searchParams.set('symbols',state.rows.map(row=>row.symbol).join(','));if(requestedDate)endpoint.searchParams.set('date',requestedDate);else endpoint.searchParams.delete('date');const response=await fetch(endpoint,{headers:state.token?{Authorization:'Bearer '+state.token}:{},signal:AbortSignal.timeout(90000),cache:'no-store'});let payload;try{payload=await response.json();}catch{throw new Error('行情服务没有返回有效 JSON。');}if(!response.ok)throw new Error(payload.error||'行情服务暂不可用（'+response.status+'）。');if(requestedDate&&(payload.mode!=='history'||payload.date!==requestedDate))throw new Error('行情服务未返回所选交易日的历史资金流。');const rows=normalizePayload(payload),historical=payload.mode==='history';
if(!historical){for(const row of rows){const prior=state.previous.get(row.symbol);if(prior&&prior.flowTime.slice(0,10)===row.flowTime.slice(0,10)&&prior.flowTime!==row.flowTime&&row.main!==null)row.delta=row.main-prior.main;if(row.main!==null&&row.flowTime)state.previous.set(row.symbol,{main:row.main,flowTime:row.flowTime});}}
state.rows=rows;state.mode=historical?'history':'live';state.date=historical?payload.date:'';state.meta={...payload,tradingDates:Array.isArray(payload.tradingDates)?payload.tradingDates.filter(date=>/^\d{4}-\d{2}-\d{2}$/.test(date)):[]};if(new URL(state.endpoint).origin===location.origin){savePreference('flow-local-live',true);savePreference('flow-history-date',state.date);}
$('history-date').value=state.date;$('source-label').textContent=historical?'富途 OpenD · 历史日级':'富途 OpenD · 已连接';$('source-label').style.color='var(--green)';$('status-dot').classList.add('live');const times=rows.map(row=>row.flowTime).filter(Boolean).sort();$('snapshot-time').textContent=historical?'交易日 '+state.date+' · 美东日期':times.length?'资金有效时间 '+times.at(-1)+' ET':'资金有效时间暂不可用';const unavailable=rows.filter(row=>row.main===null).length;$('source-hint').textContent=(historical?'该交易日资金净流入 · 非分钟回放':flowSessionHint(times))+(unavailable?' · '+unavailable+' 个标的资金流不可用':'');if(unavailable){$('error').textContent=unavailable+' 个标的未返回'+(historical?'该交易日':'')+'资金流，表格显示 —。';$('error').hidden=false;}updateHistoryControls();render();notify(historical?'已加载 '+state.date+' 的资金流':'快照已获取');
}catch(error){$('error').textContent='获取失败：'+(error.name==='TimeoutError'?'请求超时，请稍后重试。':error.message)+' 当前保留上一次数据。';$('error').hidden=false;}
finally{state.busy=false;updateHistoryControls();$('refresh').disabled=false;$('refresh').innerHTML='刷新快照 <span>↻</span>';$('rows').classList.remove('loading');}}
/** 刷新当前数据，避免将点击事件误当作日期参数。 */
function refreshCurrent() {refresh();}
/** 提交历史日期查询，不将休市日自动替换为邻近交易日。 */
function viewHistory(event) {event.preventDefault();const date=$('history-date').value;if(!date||!$('history-date').checkValidity()){notify('请选择最近一年内的已结束交易日');return;}refresh(date);}
/** 按实际交易日历移动到相邻交易日。 */
function stepHistory(offset) {const dates=state.meta?.tradingDates||[],current=state.date||state.rows.map(row=>row.flowTime.slice(0,10)).filter(date=>/^\d{4}-\d{2}-\d{2}$/.test(date)).sort().at(-1),index=dates.indexOf(current);if(index>=0&&dates[index+offset])refresh(dates[index+offset]);}
/** 查询上一交易日。 */
function previousDay() {stepHistory(-1);}
/** 查询下一交易日。 */
function nextDay() {stepHistory(1);}
/** 从历史视图返回最新快照。 */
function latestFlow() {refresh('');}
/** 用真实日级数据展示截至所选日期最近最多20个交易日的主力资金趋势。 */
function historyTrend(row) {const days=row.history||[];if(!days.length)return '';const max=Math.max(1,...days.map(day=>Math.abs(day.main||0)));return '<div class="trend-title">近期主力资金动向<span>最多20个交易日 · 万美元</span></div><div class="trend-chart" role="img" aria-label="主力净流入日级趋势">'+days.map(day=>'<div class="trend-day" title="'+day.date+'：'+number(day.main,0,true)+' 万美元"><i class="'+(day.main<0?'out':'')+'" style="height:'+Math.abs(day.main||0)/max*48+'%"></i></div>').join('')+'</div><div class="trend-caption"><span>'+days[0].date+'</span><span>'+days.at(-1).date+'</span></div><div class="trend-list">'+days.slice(-5).map(day=>'<div><span>'+day.date+'</span><span class="'+tone(day.main)+'">'+number(day.main,0,true)+'</span></div>').join('')+'</div>';}
/** 导出当前筛选结果，带上来源与有效时间并防止表格公式注入。 */
function exportRows() {const rows=visibleRows();if(!rows.length){notify('当前没有可导出的标的');return;}const headers=['来源','有效时间','股票','名称','现价','涨跌幅%','主力净流入(万美元)','大单','特大单(机构代理)','中单','小单','B/A','DP%','日内低','日内高','快照变化','方向'];const csv=[headers,...rows.map(row=>[state.mode==='sample'?'截图静态样例（非实时）':state.mode==='history'?'富途OpenD·历史日级':'富途OpenD',row.flowTime,row.symbol,row.name,row.price,row.change,row.main,row.big,row.super,row.mid,row.small,row.ba,row.dp,row.low,row.high,row.delta,direction(row).label])].map(values=>values.map(value=>{let text=String(value??'');if(typeof value==='string'&&/^[=+\-@\t\r]/.test(text))text="'"+text;return '"'+text.replace(/"/g,'""')+'"';}).join(',')).join('\r\n');const url=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'})),link=document.createElement('a');link.href=url;link.download='资金流-'+(state.mode==='sample'?'截图样例':state.mode==='history'?'历史日级-'+state.date:'真实快照')+'.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);notify('已导出当前筛选结果');}
/** 恢复截图样例，同时清除实时凭据及快照基准。 */
function useSample() {if(state.busy)return;state.mode='sample';state.date='';$('history-date').value='';savePreference('flow-history-date','');state.endpoint='';state.token='';$('token').value='';state.rows=makeSample();savePreference('flow-local-live',false);state.previous.clear();$('source-label').textContent='截图静态样例';$('source-label').style.color='';$('status-dot').classList.remove('live');$('snapshot-time').textContent='日期未提供 · 15:40 ET';$('source-hint').textContent='仅用于体验页面 · 非实时行情';$('error').hidden=true;$('connect-dialog').close();updateHistoryControls();render();}
/** 更新纽约时钟；此时钟与资金数据时间相互独立。 */
function updateClock() {$('clock').textContent=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date())+' ET';}
/** 委托处理自选、详情、排序和分类切换。 */
function handleClick(event) {const favorite=event.target.closest('[data-favorite]'),detail=event.target.closest('[data-detail]'),sort=event.target.closest('[data-sort]'),tab=event.target.closest('[data-tab]'),close=event.target.closest('[data-close]');if(favorite){const symbol=favorite.dataset.favorite;state.favorites.has(symbol)?state.favorites.delete(symbol):state.favorites.add(symbol);savePreference('flow-favorites',[...state.favorites]);render();}if(detail)showDetail(detail.dataset.detail);if(sort){state.descending=state.sort===sort.dataset.sort?!state.descending:true;state.sort=sort.dataset.sort;render();}if(tab){state.tab=tab.dataset.tab;document.querySelectorAll('[data-tab]').forEach(button=>button.classList.toggle('active',button===tab));render();}if(close)close.closest('dialog').close();}
/** 保存当前会话接口配置并发起首次请求。 */
async function connectSource(event) {event.preventDefault();const endpoint=new URL($('endpoint').value.trim());if(endpoint.protocol!=='https:'&&!(endpoint.protocol==='http:'&&['localhost','127.0.0.1','[::1]'].includes(endpoint.hostname))){notify('在线接口请使用 HTTPS，本机接口可以使用 HTTP。');return;}state.endpoint=endpoint.href;state.token=$('token').value;state.previous.clear();$('connect-dialog').close();await refresh();}
/** 快捷键聚焦搜索框，不干扰表单输入。 */
function handleKeyboard(event) {if(event.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){event.preventDefault();$('search').focus();}}
document.addEventListener('click',handleClick);document.addEventListener('keydown',handleKeyboard);$('search').addEventListener('input',render);$('direction').addEventListener('change',render);$('refresh').addEventListener('click',refreshCurrent);$('history-form').addEventListener('submit',viewHistory);$('previous-day').addEventListener('click',previousDay);$('next-day').addEventListener('click',nextDay);$('latest-flow').addEventListener('click',latestFlow);$('export').addEventListener('click',exportRows);$('use-example').addEventListener('click',useSample);$('connect-form').addEventListener('submit',connectSource);
/** 展示接入表单，不预填远程令牌。 */
function openConnect() {if(state.busy)return;if(!$('endpoint').value)$('endpoint').value=location.hostname==='127.0.0.1'||location.hostname==='localhost'?location.origin+'/api/snapshot':'';$('connect-dialog').showModal();}
/** 展示字段来源和计算公式。 */
function openMethod() {$('method-dialog').showModal();}
/** 仅在本机恢复用户已成功连接的行情服务，不保存账户或访问令牌。 */
function initialize() {const today=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()),date=new Date(today+'T12:00:00Z'),minimum=new Date(date.getTime()-365*86400000).toISOString().slice(0,10),maximum=new Date(date.getTime()-86400000).toISOString().slice(0,10);$('history-date').min=minimum;$('history-date').max=maximum;updateHistoryControls();render();updateClock();setInterval(updateClock,30000);if(['127.0.0.1','localhost'].includes(location.hostname)&&readPreference('flow-local-live',false)){state.endpoint=location.origin+'/api/snapshot';const saved=readPreference('flow-history-date','');state.date=/^\d{4}-\d{2}-\d{2}$/.test(saved)&&saved>=minimum&&saved<=maximum?saved:'';refresh();}}
$('connect').addEventListener('click',openConnect);$('method').addEventListener('click',openMethod);$('help').addEventListener('click',openMethod);initialize();

/** 格式化收益或命中率的百分比。 */
function percent(value,digits=2) {return Number.isFinite(value)?number(value*100,digits)+'%':'—';}
/** 显示IC或收益差的95%区间，不把未跨零区间写成交易保证。 */
function confidence(interval,isReturn=false) {return Array.isArray(interval)&&interval.length===2?'['+(isReturn?percent(interval[0]):number(interval[0],3))+', '+(isReturn?percent(interval[1]):number(interval[1],3))+']':'样本不足';}
/** 展示本地真实历史数据的验证结果及可复核限制。 */
async function showValidation() {
$('validation-dialog').showModal();$('validation-content').innerHTML='<p>正在读取历史验证结果…</p>';
try{if(!state.endpoint)throw new Error('请先连接本地行情服务。');const endpoint=new URL(state.endpoint);endpoint.pathname=endpoint.pathname.replace(/\/snapshot$/, '/validation');endpoint.search='';const response=await fetch(endpoint,{headers:state.token?{Authorization:'Bearer '+state.token}:{},signal:AbortSignal.timeout(10000),cache:'no-store'}),report=await response.json();if(!response.ok)throw new Error(report.error||'验证结果暂不可用。');if(!Array.isArray(report.horizons)||!Array.isArray(report.coverage))throw new Error('验证结果格式错误。');const evidence=report.horizons.filter(item=>item.late?.ic_ci?.[0]>0&&item.late?.spread_ci?.[0]>0),verdict=evidence.length?'部分周期在时间后段出现正向证据，但这仍是一次探索性检验，需要更长样本和独立复核。':'时间后段复核中，尚未发现同时具备正IC与正分组收益差的稳健证据。资金流与当日价格同步不等于能够预测后续股价。';
$('validation-content').innerHTML='<p>'+escapeHtml(report.start)+' 至 '+escapeHtml(report.end)+' · '+report.available_symbols+' / '+report.requested_symbols+' 个标的 · '+report.trading_days+' 个交易日 · 基准 SPY</p><div class="validation-grid"><div><span>当日同步相关（平均IC）</span><strong>'+number(report.same_day_ic,3)+'</strong><small>95%区间 '+confidence(report.same_day_ic_ci)+'</small></div><div><span>验证的后续周期</span><strong>1 / 5 / 20</strong><small>交易日 · 前复权收盘价格变化</small></div><div><span>时间后段复核起点</span><strong style="font-size:19px">'+escapeHtml(report.split)+'</strong><small>最后30%时间 · 前段收益跨界样本剔除</small></div></div><div class="validation-note">'+verdict+'</div><h3 class="validation-heading">全样本：方向命中是否优于上涨基线</h3><div class="validation-scroll"><table><thead><tr><th>随后交易日</th><th>有效方向样本</th><th>整体上涨率</th><th>流入后上涨率</th><th>流出后上涨率</th><th>方向命中率</th><th>平均IC</th></tr></thead><tbody>'+report.horizons.map(item=>{const result=item.all;return '<tr><td>'+item.horizon+' 日</td><td>'+number(result.classification_n)+'</td><td>'+percent(result.baseline_up)+'</td><td>'+percent(result.inflow_up)+'</td><td>'+percent(result.outflow_up)+'</td><td>'+percent(result.direction_accuracy)+'</td><td>'+number(result.ic,3)+'</td></tr>';}).join('')+'</tbody></table></div><h3 class="validation-heading">时间后段：同一信号在后30%区间是否稳定</h3><div class="validation-scroll"><table><thead><tr><th>随后交易日</th><th>观察日数</th><th>平均IC</th><th>IC 95%区间</th><th>强流入组−弱流入组</th><th>收益差95%区间</th></tr></thead><tbody>'+report.horizons.map(item=>{const result=item.late;return '<tr><td>'+item.horizon+' 日</td><td>'+number(result.dates)+'</td><td>'+number(result.ic,3)+'</td><td>'+confidence(result.ic_ci)+'</td><td>'+percent(result.quartile_spread)+'</td><td>'+confidence(result.spread_ci,true)+'</td></tr>';}).join('')+'</tbody></table></div><p>IC是每天资金强度与随后收益的秩相关，再按交易日等权平均。资金强度 = 主力净流入 / 当日成交额。正IC表示资金越强，后续收益越高；接近0表示排序关系弱。强、弱两组分别为当天资金强度最高和最低的四分之一标的。</p><p>主力流入预测上涨、流出预测下跌。整体上涨率相当于同一非零样本上始终看涨的基线。样本数是“标的×日期”，不是独立事件数。95%区间通过连续交易日区块重采样计算，多日收益有重叠。收盘至未来收盘收益不等同可成交策略收益。</p><ul class="limits">'+report.method.limits.map(limit=>'<li>'+escapeHtml(limit)+'</li>').join('')+'</ul><p>单个标的覆盖：'+report.coverage.map(item=>escapeHtml(item.symbol)+' '+item.days+' 天').join(' · ')+'</p>'+(report.failures.length?'<p class="validation-error">有 '+report.failures.length+' 个数据获取失败项目，已从结果中排除。</p>':'');
}catch(error){$('validation-content').innerHTML='<p class="validation-error">'+escapeHtml(error.message)+'</p>';}}
$('validation').addEventListener('click',showValidation);

let pathReport=null, pathBusy=false;
const pathMetrics={main:'主力',total:'全部成交',big:'大单',super:'特大单',mid:'中单',small:'小单'};
/** 打开单股事件观察，沿用所选历史日期并允许输入其他美股代码。 */
function openPath(symbol='NVDA') {
if(pathBusy){if(!$('path-dialog').open)$('path-dialog').showModal();return;}
const dates=state.meta?.tradingDates||[];
$('path-symbol').value=symbol;$('path-symbols').innerHTML=state.rows.map(row=>'<option value="'+row.symbol+'">'+escapeHtml(row.name)+'</option>').join('');
$('path-date').min=$('history-date').min;$('path-date').max=$('history-date').max;
$('path-date').value=state.date||dates.at(-21)||'';
if($('detail-dialog').open)$('detail-dialog').close();
if(!$('path-dialog').open)$('path-dialog').showModal();
if(!pathBusy){pathReport=null;$('path-content').innerHTML='';if($('path-date').value&&state.endpoint)queryPath();}
}
/** 读取独立单股历史序列，不修改总览中的日期、排序或样例数据。 */
async function queryPath(event) {
if(event)event.preventDefault();if(pathBusy||!$('path-form').reportValidity())return;
pathBusy=true;pathReport=null;['path-symbol','path-date','path-days','path-query'].forEach(id=>{$(id).disabled=true;});$('path-query').textContent='正在查询…';$('path-content').innerHTML='<p>正在读取真实历史资金流与日K线…</p>';
try{if(!state.endpoint)throw new Error('请先接入本地行情服务，截图样例无法查询真实后续走势。');const endpoint=new URL(state.endpoint);endpoint.pathname=endpoint.pathname.replace(/\/snapshot$/, '/path');endpoint.search='';endpoint.searchParams.set('symbol',$('path-symbol').value.trim().toUpperCase());endpoint.searchParams.set('date',$('path-date').value);endpoint.searchParams.set('days',$('path-days').value);
const response=await fetch(endpoint,{headers:state.token?{Authorization:'Bearer '+state.token}:{},signal:AbortSignal.timeout(90000),cache:'no-store'});let report;try{report=await response.json();}catch{throw new Error('行情服务没有返回有效的走势数据。');}if(!response.ok)throw new Error(report.error||'走势查询暂不可用。');if(report.source!=='futu-opend'||report.adjustment!=='QFQ'||!Array.isArray(report.rows)||!report.rows.length||report.rows[0].date!==$('path-date').value)throw new Error('历史走势数据格式错误。');pathReport=report;renderPath();
}catch(error){$('path-content').innerHTML='<p class="validation-error" role="alert">'+escapeHtml(error.name==='TimeoutError'?'查询超时，请稍后重试。':error.message)+'</p>';}
finally{pathBusy=false;['path-symbol','path-date','path-days','path-query'].forEach(id=>{$(id).disabled=false;});$('path-query').textContent='查看每天走向';}
}
/** 绘制以事件日收盘为零点的累计涨跌曲线；缺失行情保留断点。 */
function pathChart(rows) {
const values=rows.map(row=>row.cumulative).filter(Number.isFinite);if(values.length<2)return '<p>后续有效行情不足，暂无法绘制走势。</p>';
const width=820,height=230,left=64,right=18,top=18,bottom=35,min=Math.min(0,...values),max=Math.max(0,...values),padding=Math.max((max-min)*.12,.2),low=min-padding,high=max+padding;
const x=i=>left+i/Math.max(1,rows.length-1)*(width-left-right),y=v=>top+(high-v)/(high-low)*(height-top-bottom);
let drawing='',connected=false;rows.forEach((row,i)=>{if(!Number.isFinite(row.cumulative)){connected=false;return;}drawing+=(connected?' L':' M')+x(i).toFixed(2)+','+y(row.cumulative).toFixed(2);connected=true;});
return '<div class="path-chart"><svg viewBox="0 0 '+width+' '+height+'" role="img" aria-label="从事件日收盘起的逐交易日累计涨跌曲线">'+[high,(high+low)/2,low].map(value=>'<line x1="'+left+'" x2="'+(width-right)+'" y1="'+y(value)+'" y2="'+y(value)+'" stroke="#263039"/><text x="'+(left-10)+'" y="'+(y(value)+4)+'" text-anchor="end">'+number(value,2)+'%</text>').join('')+'<line x1="'+left+'" x2="'+(width-right)+'" y1="'+y(0)+'" y2="'+y(0)+'" stroke="#83928d" stroke-dasharray="4 4"/><path d="'+drawing+'" fill="none" stroke="#b7eccd" stroke-width="2.5"/>'+rows.map((row,i)=>Number.isFinite(row.cumulative)?'<circle cx="'+x(i)+'" cy="'+y(row.cumulative)+'" r="3" fill="'+(row.cumulative<0?'#f47b7a':'#53d6a0')+'"><title>'+escapeHtml(row.date)+' · 收盘 '+number(row.close,2)+' · 累计 '+number(row.cumulative,2,true)+'%</title></circle>':'').join('')+'<text x="'+left+'" y="'+(height-9)+'">'+rows[0].date+' · 起点</text><text x="'+(width-right)+'" y="'+(height-9)+'" text-anchor="end">'+rows.at(-1).date+' · 第'+rows.at(-1).day+'日</text></svg></div>';
}
/** 展示事件日净资金与后续逐日价格，明确区分当日涨跌和累计涨跌。 */
function renderPath() {
if(!pathReport)return;const report=pathReport,rows=report.rows,metric=$('path-metric').value,label=pathMetrics[metric],anchor=rows[0],last=rows.at(-1),flow=anchor[metric],direction=Number.isFinite(flow)?flow>0?'净流入':flow<0?'净流出':'净额为零':'资金缺失';
const future=rows.slice(1).filter(row=>Number.isFinite(row.change)),up=future.filter(row=>row.change>0).length,down=future.filter(row=>row.change<0).length,flat=future.filter(row=>row.change===0).length;
$('path-content').innerHTML='<h3 class="validation-heading">'+escapeHtml(report.symbol)+' / '+escapeHtml(report.name)+' · '+escapeHtml(report.date)+'</h3><div class="validation-grid"><div><span>事件日 · '+label+direction+'（万美元）</span><strong class="'+tone(flow)+'">'+number(flow,0,true)+'</strong><small>当天完整交易日净额</small></div><div><span>第 '+last.day+' 日 · 相对起点累计涨跌</span><strong class="'+tone(last.cumulative)+'">'+number(last.cumulative,2,true)+(Number.isFinite(last.cumulative)?'%':'')+'</strong><small>'+escapeHtml(last.date)+' · 收盘 '+number(last.close,2)+'</small></div><div><span>后续每天的上涨 / 下跌 / 持平</span><strong>'+up+' / '+down+' / '+flat+'</strong><small>有效单日涨跌 '+future.length+' 天，共请求 '+report.requestedDays+' 个交易日</small></div></div>'+(report.availableDays<report.requestedDays?'<div class="validation-note">截至 '+escapeHtml(report.asOf)+'，此后仅有 '+report.availableDays+' 个已结束交易日，尚未满 '+report.requestedDays+' 日。</div>':'')+pathChart(rows)+'<p>虚线为事件日收盘基准（0%）。单日涨跌与上一交易日收盘比较；累计涨跌与 '+escapeHtml(report.date)+' 收盘比较。价格：美元／前复权；资金：万美元／净额。缺失项显示 —。</p><div class="path-table"><table><thead><tr><th>交易日</th><th>美东日期</th><th>收盘价</th><th>单日涨跌</th><th>相对起点累计</th><th>'+label+'净流入</th><th>当天价格方向</th></tr></thead><tbody>'+rows.map(row=>'<tr class="'+(row.day===0?'path-anchor':'')+'"><td>'+(row.day===0?'起点 T+0':'T+'+row.day)+'</td><td>'+escapeHtml(row.date)+'</td><td>'+number(row.close,2)+'</td><td class="'+tone(row.change)+'">'+number(row.change,2,true)+(Number.isFinite(row.change)?'%':'')+'</td><td class="'+tone(row.cumulative)+'">'+number(row.cumulative,2,true)+(Number.isFinite(row.cumulative)?'%':'')+'</td><td class="'+tone(row[metric])+'">'+number(row[metric],0,true)+'</td><td>'+(Number.isFinite(row.change)?row.change>0?'↑ 上涨':row.change<0?'↓ 下跌':'→ 持平':'行情缺失')+'</td></tr>').join('')+'</tbody></table></div><p>这是单个历史事件的实际走势，无法单独证明资金流具有预测能力。日级资金流在事件日结束后才完整，图中的累计涨跌不等同下一日可成交的策略收益。</p>';
}
/** 从标的详情直接进入该股票的后续走势。 */
function handlePathClick(event) {const target=event.target.closest('[data-path]');if(target)openPath(target.dataset.path);}
/** 从总览打开默认股票的逐日观察。 */
function openDefaultPath() {openPath();}
$('path-open').addEventListener('click',openDefaultPath);$('path-form').addEventListener('submit',queryPath);$('path-metric').addEventListener('change',renderPath);document.addEventListener('click',handlePathClick);
