'use strict';

/** 安装独立的日线指标研究弹窗，只访问授权行情接口。 */
(function installIndicators(root) {
  const families = [['trend','长短趋势 · 10-28原公式'],['GZRX1','GZRX1 · 6条均线'],['GZRX3','GZRX3 · 5条均线'],
    ['LDR','LDR · EMA梯子'],['GZRZH','GZRZH · 均线与梯子'],['CL2','CL2 · 图形回画，暂不支持'],['SRJ','SRJ · 水平回画，暂不支持']];
  const labels = {TOPSIG:'逃顶确认',BOTSIG:'抄底确认',PUTSIG:'PUT',CALLSIG:'CALL',WARNSIG:'注意',VUPSIG:'放量上涨',VDNSIG:'放量下跌',
    DHIST:'历史大底',DSUPER:'超大底',DBIG:'大底',DMID:'中底',DSMALL:'小底',DISLBUY:'岛形看涨',DISLSELL:'岛形看跌',
    DENGBUY:'看涨吞没',DENGSELL:'看跌吞没',DSTARBUY:'晨星',DSTARSELL:'暮星',DBRKBUY:'向上突破',DBRKSELL:'向下突破',
    DMBBUY:'底背离确认',DMBSELL:'顶背离确认',DGOLD:'金叉',DDEAD:'死叉',DTXBUY:'短买',DTXSELL:'短卖'};
  let options = {}, mounted = false, dialog = null, controller = null, returnFocus = null;

  /** 对文本和属性进行HTML转义，外部字段不作为可执行标记。 */
  function escape(value) { return String(value ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

  /** 缺失值显示破折号，只有真实有限数值才格式化。 */
  function number(value, digits=2) { return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('zh-CN',{minimumFractionDigits:digits,maximumFractionDigits:digits}) : '—'; }

  /** 比例按百分比呈现，null不伪装成0%。 */
  function percent(value) { return typeof value === 'number' && Number.isFinite(value) ? number(value*100)+'%' : '—'; }

  /** 读取现有行情连接的内存配置，不读账户、存储或私有持仓。 */
  function connection() {
    if (options.getConnection) return options.getConnection();
    return typeof state !== 'undefined' ? {endpoint:state.endpoint,token:state.token,market:state.market,date:state.date} : {};
  }

  /** 从行情连接创建受限指标端点；令牌仅放请求头，不进入URL。 */
  function createURL(config, params) {
    const url = new URL(config.endpoint || '/api/indicators', root.location.href);
    if (url.username || url.password || !(url.protocol === 'https:' || url.protocol === 'http:' && ['localhost','127.0.0.1','[::1]'].includes(url.hostname))) {
      throw new Error('指标服务须为HTTPS或本机HTTP行情服务。');
    }
    url.pathname = /\/snapshot$/.test(url.pathname) ? url.pathname.replace(/\/snapshot$/, '/indicators') : '/api/indicators';
    url.search = ''; url.hash = '';
    for (const [key,value] of Object.entries(params)) url.searchParams.set(key,String(value));
    url.searchParams.set('market','US'); url.searchParams.set('timeframe','1d');
    return url;
  }

  /** 等待后台进度，取消请求时立即释放定时器。 */
  function pause(signal) {
    return new Promise((resolve,reject)=>{
      if (signal.aborted) { reject(new DOMException('已取消','AbortError')); return; }
      /** 清理等待并正常继续。 */
      function done() { signal.removeEventListener('abort',cancel); resolve(); }
      /** 清理计时器并传播取消状态。 */
      function cancel() { clearTimeout(timer); signal.removeEventListener('abort',cancel); reject(new DOMException('已取消','AbortError')); }
      const timer = setTimeout(done,1000); signal.addEventListener('abort',cancel,{once:true});
    });
  }

  /** 沿用行情认证边界并支持标准202作业轮询，不依赖旧端点正则。 */
  async function request(url, progress, signal, token) {
    let target = new URL(url), attempts = 0;
    while (attempts++ < 480) {
      const timeout = AbortSignal.timeout ? AbortSignal.timeout(30000) : null;
      const response = await root.fetch(target,{cache:'no-store',headers:token?{Authorization:'Bearer '+token}:{},
        signal:timeout && AbortSignal.any ? AbortSignal.any([signal,timeout]) : signal});
      const payload = await response.json();
      if (response.status === 202) {
        if (!/^[a-f0-9]{24}$/.test(payload.jobId || '')) throw new Error('后台任务格式错误。');
        progress(payload.progress || {}); target = new URL(url); target.pathname=target.pathname.replace(/\/indicators$/, '/jobs');
        target.search=''; target.searchParams.set('id',payload.jobId); await pause(signal); continue;
      }
      if (!response.ok) throw new Error(response.status===404 ? '行情服务尚未接入自定义指标端点，请更新并重启服务。' : payload.error || '指标请求失败（'+response.status+'）。');
      return payload;
    }
    throw new Error('后台任务超时，请稍后重试。');
  }

  /** 校验完整数值树和请求身份，拒绝NaN、错版、错日或错标的。 */
  function validateReport(report, expected) {
    if (!report || report.source!=='flowdesk-indicators' || report.schemaVersion!==1 || report.market!=='US' || report.timeframe!=='1d' ||
        report.symbol!==expected.symbol || report.asOf!==expected.asOf || report.indicator?.id!==expected.indicator) throw new Error('指标响应标的、日期或版本错配。');
    const dates = report.dates;
    if (!Array.isArray(dates) || dates.length>5000 || !Array.isArray(report.price) || report.price.length!==dates.length) throw new Error('日线格式错误。');
    if (dates.some((date,i)=>!/^\d{4}-\d{2}-\d{2}$/.test(date) || date>report.asOf || i>0 && date<=dates[i-1])) throw new Error('日线日期无效或乱序。');
    for (const values of Object.values(report.series || {})) {
      if (!Array.isArray(values) || values.length!==dates.length || values.some(v=>v!==null && typeof v!=='boolean' && (typeof v!=='number' || !Number.isFinite(v)))) throw new Error('指标数值无效。');
    }
    if (!Array.isArray(report.events) || report.events.some(e=>!Number.isInteger(e.index) || e.index<0 || e.index>=dates.length || e.confirmIndex!==e.index || e.date!==dates[e.index])) throw new Error('确认事件时点无效。');
    let count = 0;
    /** 遍历有界JSON树，保证图表及成交中的数值均有限。 */
    function walk(value, depth=0) {
      if (++count>2000000 || depth>20 || typeof value==='number' && !Number.isFinite(value)) throw new Error('报告包含无效数值或体积超限。');
      if (value && typeof value==='object') for (const item of Object.values(value)) walk(item,depth+1);
    }
    walk(report); return report;
  }

  /** 将有限序列绘成有缺失断点的SVG，事件严格注释确认根。 */
  function chartSVG(dates, lines, events=[], title='日线图') {
    const values = lines.flatMap(line=>line.values.filter(v=>typeof v==='number' && Number.isFinite(v)));
    if (!dates.length || !values.length) return '<p class="ind-empty">没有有效数值可绘图。</p>';
    const width=960, height=280, pad=48, low=Math.min(...values), high=Math.max(...values), span=high-low || Math.max(1,Math.abs(high)*.02);
    // 颜色与线型组合覆盖当前最多17条曲线；图例复用完全相同的SVG样式。
    const colors=['#d4dfdf','#9dbd9f','#d4b788','#b3a2a2','#85aeb8'];
    const dashes=['none','6 3','2 3','8 3 2 3'];
    const styles=lines.map((line,i)=>({color:colors[i%colors.length],
      path:'stroke:'+colors[i%colors.length]+';stroke-dasharray:'+dashes[Math.floor(i/colors.length)%dashes.length]}));
    /** 将样本位置映射到画布横坐标。 */
    function x(index) { return pad + index / Math.max(1,dates.length-1)*(width-pad*2); }
    /** 将有限数值映射到画布纵坐标。 */
    function y(value) { return height-pad-(value-low)/span*(height-pad*2); }
    let svg='<svg viewBox="0 0 '+width+' '+height+'" role="img" aria-label="'+escape(title)+'"><title>'+escape(title)+'</title>';
    for (let tick=0;tick<4;tick++) {
      const value=low+span*tick/3, at=y(value);
      svg+='<line class="ind-grid" x1="'+pad+'" y1="'+at+'" x2="'+(width-pad)+'" y2="'+at+'"/><text x="4" y="'+at+'">'+number(value,1)+'</text>';
    }
    lines.forEach((line,lineIndex)=>{
      let path='';
      /** 输出一段连续已知值，未知值两侧不能连线。 */
      function flush() { if(path) svg+='<path class="ind-line ind-line-'+(lineIndex%5)+'" style="'+styles[lineIndex].path+'" d="'+path+'"><title>'+escape(line.name)+'</title></path>'; path=''; }
      line.values.forEach((value,index)=>{
        if (typeof value!=='number' || !Number.isFinite(value)) { flush(); return; }
        path+=(path?'L':'M')+x(index).toFixed(2)+','+y(value).toFixed(2)+' ';
      }); flush();
    });
    events.forEach((event,index)=>{
      const value=lines[0]?.values[event.index];
      if (!Number.isInteger(event.index) || event.index<0 || event.index>=dates.length || !Number.isFinite(value)) return;
      const cx=x(event.index), cy=y(value);
      svg+='<g><circle class="ind-event" cx="'+cx+'" cy="'+cy+'" r="4"/><text class="ind-event-label" x="'+cx+'" y="'+(cy+(index%2?24:-12))+'">'+escape(event.name)+'</text><title>'+escape(dates[event.index]+' 收盘确认 '+event.name+'；最早下一根开盘')+'</title></g>';
    });
    return svg+'<text x="'+pad+'" y="'+(height-8)+'">'+escape(dates[0])+'</text><text text-anchor="end" x="'+(width-pad)+'" y="'+(height-8)+'">'+escape(dates.at(-1))+'</text></svg>'+
      '<div class="ind-legend">'+lines.map((line,i)=>'<span class="ind-legend-'+(i%5)+'" style="color:'+styles[i].color+'"><svg aria-hidden="true" viewBox="0 0 28 12" style="display:inline-block;width:28px;height:12px;min-height:0;margin:0;vertical-align:middle"><path class="ind-line" style="'+styles[i].path+'" d="M0,6 L28,6"/></svg> '+escape(line.name)+'</span>').join('')+'</div>';
  }

  /** 在可横向滚动的语义化表格中呈现并行字段。 */
  function table(headers, rows, caption) {
    return '<div class="ind-table" tabindex="0" aria-label="'+escape(caption)+'"><table><caption>'+escape(caption)+'</caption><thead><tr>'+headers.map(h=>'<th scope="col">'+escape(h)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(row=>'<tr>'+row.map(v=>'<td>'+escape(v)+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
  }

  /** 呈现真实绩效与同区间基准，并区分已平仓与尚未实现收益。 */
  function backtestHTML(backtest, splits) {
    const m=backtest.metrics, rules=backtest.rules;
    let html='<section><h3>净值与同区间买入持有</h3><p class="ind-muted">'+escape(backtest.range.start)+' 至 '+escape(backtest.range.end)+' · 全资金多头 · 最多'+number(rules.maxHoldBars,0)+'根 · 次开盘执行 · 每边手续费'+number(rules.feeBpsPerLeg,1)+'bps + 滑点'+number(rules.slippageBpsPerLeg,1)+'bps</p>';
    html+='<dl class="ind-metrics">'+[['净收益',percent(m.totalReturn)],['最大回撤',percent(m.maxDrawdown)],['买入持有',percent(backtest.benchmark.totalReturn)],['持仓敞口',percent(m.exposure)],['换手 / 初始资本',number(m.turnover)+'×'],['已平仓',number(m.closedTrades,0)],['已平仓胜率',m.closedTrades?percent(m.winRate):'无已平仓交易'],['年化夏普',number(m.sharpe)]].map(([label,value])=>'<div><dt>'+escape(label)+'</dt><dd>'+escape(value)+'</dd></div>').join('')+'</dl>';
    html+=chartSVG(backtest.equity.map(r=>r.date),[{name:'策略净值 USD',values:backtest.equity.map(r=>r.equity)},{name:'买入持有 USD',values:backtest.equity.map(r=>r.benchmark)}],[],'净值与买入持有，均含实际发生成本');
    html+='<p class="ind-muted">仅持有/反向信号退出；原公式止损和2R为参考价位，未模拟止损止盈。CALL/PUT是股票方向标签。小样本不支持稳定优势判断；不足30根或波动不足时夏普为未知。</p>';
    if (Object.keys(splits || {}).length) html+=table(['区间','开始','结束','净收益','基准','已平仓'],Object.entries(splits).map(([name,s])=>[({train:'训练',validation:'验证',holdout:'最终留出'})[name]||name,s.range.start,s.range.end,percent(s.metrics.totalReturn),percent(s.benchmark.totalReturn),s.metrics.closedTrades]),'时间顺序切分 · 60/20/20，或调用方指定日期');
    html+='<p class="ind-muted">各段独立空仓开始，共用早期历史暖机；跨界持仓只计期末未实现盈亏，不进入已平仓计数。参数未优化。基准从每段首开盘入场、同入场费用、末收盘计价。</p>';
    html+='<h3>已平仓交易</h3>'+(backtest.trades.length?table(['信号日','入场日','信号','入价','退出日','原因','出价','净盈亏 USD','净收益'],backtest.trades.map(t=>[t.entrySignalDate,t.entryDate,t.entrySignal,number(t.entryPrice),t.exitDate,t.exitReason,number(t.exitPrice),number(t.netPnl),percent(t.netReturn)]),'按实际成交日记账'): '<p class="ind-empty">无已平仓交易；胜率为未知。</p>');
    if (backtest.openPosition) html+='<p class="ind-note">期末仍持有：'+escape(backtest.openPosition.entryDate)+' 入场，未实现盈亏 '+number(backtest.openPosition.unrealizedPnl)+' USD。未强制平仓，也未记作胜场。</p>';
    return html+'</section>';
  }

  /** 展示数值、确认事件、暖机、来源和独立留出结果，不插入演示数据。 */
  function renderReport(report) {
    if (!dialog) createDialog();
    const quality=report.dataQuality, sample=report.sample, source=report.indicator;
    let html='<div class="ind-result-heading"><h3>'+escape(report.symbol)+' / '+escape(source.id)+'</h3><span>'+escape(sample.start || '—')+' → '+escape(sample.end || '—')+' · '+number(sample.bars,0)+'根</span></div>';
    html+='<p class="ind-note">'+escape(report.compatibility.notice)+' · 历史价位以当前复权快照计算。</p>';
    html+='<p class="ind-muted">来源 '+escape(report.data.source)+' · '+escape(report.data.adjustment)+' · US日线 / America/New_York · 有效量价确认 '+number(quality.eligibleBars,0)+'根 · 缺量 '+number(quality.missingVolumeBars,0)+'根 · 零量 '+number(quality.zeroVolumeBars,0)+'根</p>';
    if (quality.historicalBottomReady===false) html+='<p class="ind-note">历史大底：1000根及后续滚动/冷却依赖尚未全部暖机，不把未出现解释为完整验证。</p>';
    if (report.status==='empty') html+='<p class="ind-empty">截至所选日期无有效日线，未生成曲线或绩效。</p>';
    else {
      if (report.status==='warming-up') html+='<p class="ind-empty">量价条件尚在暖机，暂不提供回测绩效。</p>';
      const start=Math.max(0,report.dates.length-240), dates=report.dates.slice(start);
      const keys=Object.keys(report.series).filter(key=>/^MA\d+$/.test(key)||['TREND','UP1','LOW1','UP2','LOW2','VAVG'].includes(key));
      const lines=[{name:'收盘 USD',values:report.price.slice(start)},...keys.map(key=>({name:key,values:report.series[key].slice(start)}))];
      html+='<section><h3>数值与原公式主确认事件</h3><p class="ind-muted">图示最近'+number(dates.length,0)+'根；主提示标在当根收盘确认位置，最早下一根开盘执行。观察层事件见下表。</p>'+chartSVG(dates,lines,report.events.filter(e=>e.layer==='primary'&&e.index>=start).map(e=>({...e,index:e.index-start})),'原公式收盘确认事件')+'</section>';
      html+='<details><summary>全部数值序列最新值与有效覆盖</summary>'+table(['序列','最新值','已知 / 总根数'],Object.entries(report.series).map(([key,values])=>[key,typeof values.at(-1)==='boolean'?String(values.at(-1)):number(values.at(-1),4),(quality.seriesReadiness?.[key]?.knownBars ?? values.filter(v=>v!==null).length)+' / '+sample.bars]),'计算值；未知保持null')+'</details>';
      if (report.backtest) html+=backtestHTML(report.backtest,report.splits);
      else if (report.status!=='warming-up') html+='<p class="ind-note">此指标没有原生买卖事件，仅展示真实均线/通道数值。</p>';
      html+='<section><h3>原公式确认事件 · '+number(report.events.length,0)+'条</h3>'+(report.events.length?table(['收盘确认日','原始名称','含义','层级','最早成交'],report.events.slice(-100).reverse().map(e=>[e.date,e.name,labels[e.name]||e.name,e.layer,'下一根开盘']),'最近100条原公式事件；MB枢轴右侧3根确认，未回填枢轴日'): '<p class="ind-empty">当前样本没有原公式确认事件。</p>')+'</section>';
    }
    html+='<details><summary>来源审计与研究边界</summary><p>公式 '+escape(source.sourceBasename)+' · '+escape(source.sourceVersion)+'<br>源文件 SHA256 <code>'+escape(source.sourceSha256)+'</code><br>公式 SHA256 <code>'+escape(source.formulaSha256 || '—')+'</code></p><ul>'+(report.warnings||[]).map(w=>'<li>'+escape(w)+'</li>').join('')+'</ul>';
    html+=table(['目录','状态','限制'],(report.catalog||[]).map(c=>[c.id,c.supported?'暂定数值兼容':'暂不支持',c.reason||'富途逐根认证待完成']),'8个原始指标审计目录')+'</details>';
    dialog.querySelector('#indicator-result').innerHTML=html;
  }

  /** 取消在途查询，旧响应即使返回也不进入页面。 */
  function cancel() { controller?.abort(); controller=null; if(dialog) { dialog.querySelector('#indicator-run').disabled=false; dialog.querySelector('#indicator-result').removeAttribute('aria-busy'); } }

  /** 关闭弹窗并恢复入口焦点。 */
  function close() {
    cancel(); if(!dialog) return;
    if(typeof dialog.close==='function') dialog.close(); else dialog.removeAttribute('open');
    returnFocus?.focus();
  }

  /** 按表单字段查询，显示加载、取消、空态和真实错误。 */
  async function query(event) {
    event?.preventDefault(); if(!dialog) createDialog();
    const form=dialog.querySelector('form'); if(!form.reportValidity()) return;
    cancel(); const current=new AbortController(); controller=current;
    const status=dialog.querySelector('#indicator-status'), result=dialog.querySelector('#indicator-result'), button=dialog.querySelector('#indicator-run');
    const family=dialog.querySelector('#indicator-family').value;
    const params={symbol:dialog.querySelector('#indicator-symbol').value.trim().toUpperCase(),asOf:dialog.querySelector('#indicator-asof').value,
      indicator:family==='trend'?dialog.querySelector('#indicator-version').value:family,initial:dialog.querySelector('#indicator-initial').value,
      feeBps:dialog.querySelector('#indicator-fee').value,slippageBps:dialog.querySelector('#indicator-slip').value};
    result.innerHTML='<div class="ind-skeleton" aria-label="加载中"></div>'; result.setAttribute('aria-busy','true'); button.disabled=true;
    status.textContent='正在读取授权日线并重放原公式…';
    try {
      const config=connection(); if(config.market && config.market!=='US') throw new Error('自定义指标首发仅支持US日线，请切换美国市场。');
      const url=createURL(config,params), fetcher=options.request || request;
      /** 在当前请求仍有效时显示后台进度。 */
      function progress(value) { if(controller===current&&!current.signal.aborted) status.textContent=value.message || '正在计算…'; }
      const report=await fetcher(url,progress,current.signal,config.token);
      if(current.signal.aborted || controller!==current) return;
      validateReport(report,params); renderReport(report); status.textContent='已完成 '+report.symbol+' · 截至 '+report.asOf+' · '+(report.status==='available'?'真实输入计算完成':'样本不足，见质量提示');
    } catch(error) {
      if(!current.signal.aborted && controller===current) { result.innerHTML=''; status.textContent=error.message || '指标研究失败。'; }
    } finally {
      if(controller===current) { controller=null; button.disabled=false; result.removeAttribute('aria-busy'); }
    }
  }

  /** 懒创建带原生可访问标签的弹窗，样式全部由独立CSS提供。 */
  function createDialog() {
    dialog=root.document.createElement('dialog'); dialog.id='indicator-dialog'; dialog.className='ind-dialog';
    dialog.setAttribute('aria-labelledby','indicator-title');
    dialog.innerHTML='<div class="ind-header"><div><span class="ind-kicker">CUSTOM INDICATOR RESEARCH</span><h2 id="indicator-title">自定义指标研究</h2></div><button type="button" class="ind-button" id="indicator-close" aria-label="关闭自定义指标研究">关闭</button></div>'+
      '<p class="ind-note">源公式兼容性尚未通过富途逐根输出认证。仅US已完成日线；CALL/PUT是股票方向标签，不代表期权收益。</p>'+
      '<form class="ind-form"><label for="indicator-symbol">股票 / ETF代码<input id="indicator-symbol" required maxlength="15" pattern="[A-Za-z][A-Za-z0-9.\\-]{0,14}" autocomplete="off" value="QQQ"></label>'+
      '<label for="indicator-asof">截至日<input id="indicator-asof" type="date" required></label>'+
      '<label for="indicator-family">源码指标族<select id="indicator-family">'+families.map(([value,label])=>'<option value="'+value+'"'+(['CL2','SRJ'].includes(value)?' disabled':'')+'>'+label+'</option>').join('')+'</select></label>'+
      '<label for="indicator-version">长短趋势版本<select id="indicator-version"><option value="QUSHI-CHANG">长趋势 · 持有上限40根</option><option value="QUSHI-DUAN">短趋势 · 持有上限20根</option></select></label>'+
      '<label for="indicator-initial">初始资本 USD<input id="indicator-initial" type="number" min="1" max="1000000000" value="10000" required></label>'+
      '<label for="indicator-fee">每边手续费 bps<input id="indicator-fee" type="number" min="0" max="100" step="0.1" value="5" required></label>'+
      '<label for="indicator-slip">每边滑点 bps<input id="indicator-slip" type="number" min="0" max="100" step="0.1" value="5" required></label>'+
      '<div class="ind-actions"><button class="ind-button ind-primary" id="indicator-run" type="submit">计算与回测</button><button class="ind-button" id="indicator-cancel" type="button">取消查询</button></div></form>'+
      '<p id="indicator-status" role="status" aria-live="polite">输入标的与日期，读取已授权市场日线。CL2/SRJ因显示回画及原生因果事件尚未移植而禁用。</p><div id="indicator-result"></div>';
    root.document.body.append(dialog);
    dialog.querySelector('form').addEventListener('submit',query);
    dialog.querySelector('#indicator-close').addEventListener('click',close);
    /** 用户取消时保留明确的取消状态。 */
    function cancelQuery() { cancel(); dialog.querySelector('#indicator-result').removeAttribute('aria-busy'); dialog.querySelector('#indicator-result').innerHTML=''; dialog.querySelector('#indicator-status').textContent='已取消查询。'; }
    dialog.querySelector('#indicator-cancel').addEventListener('click',cancelQuery);
    /** 非趋势指标不显示无关的持有版本选择。 */
    function familyChanged() { dialog.querySelector('#indicator-version').disabled=dialog.querySelector('#indicator-family').value!=='trend'; }
    dialog.querySelector('#indicator-family').addEventListener('change',familyChanged);
    /** 原生取消事件同样恢复焦点并释放请求。 */
    function onCancel(event) { event.preventDefault(); close(); }
    dialog.addEventListener('cancel',onCancel);
    /** 在原生dialog及测试DOM中处理Escape。 */
    function onKey(event) { if(event.key==='Escape') { event.preventDefault(); close(); } }
    dialog.addEventListener('keydown',onKey);
    dialog.addEventListener('close',cancel);
  }

  /** 打开弹窗并在原生dialog管理下保持键盘焦点。 */
  function open(trigger=null) {
    if(!dialog) createDialog();
    returnFocus=trigger || (root.document.activeElement===root.document.body ? root.document.getElementById('open-indicators') : root.document.activeElement);
    if(!dialog.hasAttribute('open')) {
      // 每次重开采用主页面当前日期；本次弹窗内手动修改仍用于查询。
      const config=connection(), today=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
      const asOf=dialog.querySelector('#indicator-asof'); asOf.max=today; asOf.value=config.date || today;
      if(typeof dialog.showModal==='function') dialog.showModal(); else dialog.setAttribute('open','');
    }
    dialog.querySelector('#indicator-symbol').focus();
  }

  /** 安装一次委托入口，支持父页面稍后添加open-indicators按钮。 */
  function mount(config={}) {
    options={...options,...config}; if(mounted) return; mounted=true;
    /** 只响应指标入口，避免捕获其他工作台按钮。 */
    function handleClick(event) { const entry=event.target.closest?.('#open-indicators'); if(entry) open(entry); }
    /** 连接变化时取消旧市场请求并清理可能过期的研究结果。 */
    function reset() { cancel(); if(dialog) { dialog.querySelector('#indicator-result').innerHTML=''; dialog.querySelector('#indicator-status').textContent='行情连接已变化，请重新计算。'; } }
    root.document.addEventListener('click',handleClick); root.addEventListener('flow-market',reset); root.addEventListener('flow-disconnect',reset);
  }

  root.FlowdeskIndicators={mount,open,close,query,createURL,validateReport,chartSVG,renderReport};
  mount();
})(window);
