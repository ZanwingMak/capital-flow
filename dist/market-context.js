'use strict';
/** Public macro observations and aggregate positioning; no account data. */
(function installMarketContext(root) {
  const sources = [
    {id:'squeezemetrics',name:'SqueezeMetrics',url:'https://squeezemetrics.com/monitor/dix#gex',label:'查看 DIX / GEX',description:'DIX / GEX 为标普 500 聚合背景，不映射个股仓位。自动采集仅限已取得 SqueezeMetrics 书面许可的部署；默认需手动查看或在下方导入官方 CSV。'},
    {id:'financialjuice',name:'FinancialJuice',url:'https://www.financialjuice.com/',label:'打开 FinancialJuice',docs:'https://stream.financialjuice.com/docs',description:'提供官方 API；需要许可与密钥。当前未接入实时新闻流。'},
    {id:'webull',name:'Webull',url:'https://app.webull.com/',label:'打开 Webull',docs:'https://developer.webull.com/apis/docs/market-data-api/overview/',description:'应用行情与 OpenAPI 权限分开；API 行情可能需独立 Non-display 订阅。未接入登录抓取。'},
    {id:'fred',name:'FRED',url:'https://fred.stlouisfed.org/',label:'查看官方序列',docs:'https://fred.stlouisfed.org/releases/calendar',description:'官方宏观时间序列；逐项保留观测日与频率，更新节奏各异。'}
  ];
  let options={}, mounted=false, dialog=null, controller=null, returnFocus=null;
  let importGeneration=0, importReader=null;
  const maxCSVBytes=2*1024*1024;
  /** Official CSV uses plain date/numeric fields. Reject unsupported quoting rather than misparse. */
  function parseDixCSV(text, asOf) {
    if(!date(asOf)) throw new Error('请先选择有效截至日。');
    if(typeof text!=='string' || text.length>maxCSVBytes || /["\u0000]/.test(text)) throw new Error('CSV 格式无效：仅支持官方无引号日期及数值字段，最大 2 MB。');
    const lines=text.replace(/^\uFEFF/,'').trim().split(/\r?\n/);
    const headers=lines.shift().split(',').map(value=>value.trim().toLowerCase());
    if(headers.length!==4 || new Set(headers).size!==4 || !['date','price','dix','gex'].every(key=>headers.includes(key))) throw new Error('CSV 表头须为 date,price,dix,gex。');
    const seen=new Set(); let latest=null;
    for(const line of lines) {
      const values=line.split(',').map(value=>value.trim());
      if(values.length!==4) throw new Error('CSV 行列数无效。');
      const row=Object.fromEntries(headers.map((key,index)=>[key,values[index]]));
      if(!date(row.date) || seen.has(row.date)) throw new Error('CSV 日期无效或重复。');
      seen.add(row.date);
      for(const key of ['price','dix','gex']) {
        const raw=row[key];
        if(raw==='') { row[key]=null; continue; }
        if(!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(raw) || !finite(Number(raw))) throw new Error('CSV 含无效数值。');
        row[key]=Number(raw);
      }
      if(row.price!==null && row.price<=0 || row.dix!==null && (row.dix<0 || row.dix>1)) throw new Error('CSV price 须大于 0；DIX 须为 0–1 的比率。');
      if(row.date<=asOf && (!latest || row.date>latest.date)) latest=row;
    }
    if(!lines.length) throw new Error('CSV 没有观测行。');
    return latest;
  }
  function clearImport() {
    importGeneration++; importReader?.abort(); importReader=null;
    if(!dialog) return;
    dialog.querySelector('#market-context-csv').value='';
    dialog.querySelector('#market-context-manual-result').replaceChildren();
    dialog.querySelector('#market-context-import-status').textContent='尚未导入；文件不会上传或持久保存。';
  }
  async function importCSV(event) {
    const file=event.target.files?.[0]; clearImport();
    if(!file) return;
    const generation=importGeneration;
    const message=dialog.querySelector('#market-context-import-status');
    const asOf=dialog.querySelector('#market-context-asof').value;
    try {
      if(!finite(file.size) || file.size>maxCSVBytes) throw new Error('CSV 文件不能超过 2 MB。');
      message.textContent='正在浏览器内读取 CSV…';
      const text=typeof file.text==='function' ? await file.text() : await new Promise((resolve,reject)=>{
        const reader=new root.FileReader(); importReader=reader;
        reader.onload=()=>resolve(reader.result); reader.onerror=()=>reject(new Error('无法读取 CSV，请重新选择文件。'));
        reader.onabort=()=>reject(new Error('已取消导入。')); reader.readAsText(file);
      });
      if(generation!==importGeneration || !dialog.hasAttribute('open')) return;
      const row=parseDixCSV(text,asOf);
      const result=dialog.querySelector('#market-context-manual-result');
      if(row) result.innerHTML='<p class="mc-meta">文件观测日 '+escape(row.date)+' · 所选截至日 '+escape(asOf)+'</p><dl class="mc-metrics">'+[['DIX 百分比',finite(row.dix)?number(row.dix*100)+'%':'不可用'],['GEX 估算美元',finite(row.gex)?number(row.gex)+' USD':'不可用'],['S&P 500',number(row.price)]].map(([label,value])=>'<div><dt>'+label+'</dt><dd>'+value+'</dd></div>').join('')+'</dl>';
      message.textContent=row?'已导入文件中截至所选日期的最新观测；文件来源与完整性需自行核对。':'文件中没有不晚于所选截至日的观测。';
    } catch(error) {
      if(generation===importGeneration) message.textContent='导入失败：'+(error.message || '无法读取 CSV。');
    } finally { if(generation===importGeneration) importReader=null; }
  }
  const escape = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const macroLabels={DGS10:'10年期美债收益率',DGS2:'2年期美债收益率',T10Y2Y:'10年－2年期限利差',DFII10:'10年期实际收益率',BAMLH0A0HYM2:'高收益债信用利差',FEDFUNDS:'有效联邦基金利率',CPIAUCSL:'CPI物价指数',PCEPILFE:'核心PCE物价指数'};
  const displayUnit=value=>({Percent:'%', 'Percentage Points':'百分点','Index 1982-1984=100':'指数 · 1982—1984=100','Index 2017=100':'指数 · 2017=100'})[value] || value;
  const displayFrequency=value=>({Daily:'日度',Monthly:'月度'})[value] || value;
  const finite = value => typeof value==='number' && Number.isFinite(value);
  const number = value => finite(value) ? value.toLocaleString('zh-CN',{maximumFractionDigits:2}) : '不可用';
  const date = value => /^\d{4}-\d{2}-\d{2}$/.test(value || '') && !Number.isNaN(Date.parse(value)) && new Date(value).toISOString().slice(0,10)===value ? value : null;
  const status = value => ({available:'已取得',partial:'部分可用',unavailable:'不可用',stale:'较早观测',not_connected:'未接入','not-connected':'未接入',licensed:'需授权','manual-or-licensed':'手动查看 / 需授权'})[value] || value || '未取得';
  function connection() { return options.getConnection ? options.getConnection() : typeof state!=='undefined' ? {endpoint:state.endpoint,token:state.token,market:state.market,date:state.date} : {}; }
  function today() { return new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()); }
  function createURL(config, asOf) {
    const url=new URL(config.endpoint || '/api/market-context',root.location.href);
    if(url.username || url.password || !(url.protocol==='https:' || url.protocol==='http:' && ['localhost','127.0.0.1','[::1]'].includes(url.hostname))) throw new Error('数据服务须使用 HTTPS 或本机 HTTP。');
    url.pathname=/\/snapshot$/.test(url.pathname) ? url.pathname.replace(/\/snapshot$/,'/market-context') : '/api/market-context';
    url.search=''; url.hash=''; url.searchParams.set('asOf',asOf); return url;
  }
  /** Only official public origins can become links, even with a compromised response. */
  function link(url, label) {
    try {
      const target=new URL(url);
      if(target.protocol!=='https:' || target.username || target.password || !['squeezemetrics.com','www.financialjuice.com','stream.financialjuice.com','app.webull.com','developer.webull.com','fred.stlouisfed.org','api.stlouisfed.org'].includes(target.hostname)) return escape(label);
      return '<a href="'+escape(target.href)+'" target="_blank" rel="noopener noreferrer">'+escape(label)+' <span aria-hidden="true">↗</span></a>';
    } catch (_) { return escape(label); }
  }
  function validateReport(report, expected) {
    if(!report || report.source!=='flowdesk-market-context' || report.schemaVersion!==1 || !date(report.asOf) || report.asOf!==expected || !Array.isArray(report.macro) || !Array.isArray(report.sources) || !Array.isArray(report.warnings) || !report.positioning || !/Z$/.test(report.collectedAt || '') || !Number.isFinite(Date.parse(report.collectedAt))) throw new Error('市场背景响应日期或版本错配。');
    for(const item of report.macro) {
      if(!item || item.value!==null && !finite(item.value) || item.observationDate!==null && (!date(item.observationDate) || item.observationDate>report.asOf)) throw new Error('宏观观测数值或日期无效。');
    }
    const p=report.positioning;
    if(['dix','gex','spx'].some(key=>p[key]!==null && !finite(p[key])) || p.dix!==null && (p.dix<0 || p.dix>1) || p.observationDate!==null && (!date(p.observationDate) || p.observationDate>report.asOf)) throw new Error('聚合持仓数值或日期无效。');
    return report;
  }
  function sourceCards(report) {
    return sources.map(source=>{
      const item=report?.sources.find(item=>String(item.id).toLowerCase()===source.id);
      return '<article class="mc-source"><div class="mc-source-heading"><h4>'+source.name+'</h4><span class="mc-badge">'+escape(item ? status(item.status) : ['financialjuice','webull'].includes(source.id)?'未接入':'待查询')+'</span></div><p>'+source.description+'</p>'+(item?.reason?'<details class="mc-detail"><summary>可展开技术说明</summary><p class="mc-reason">'+escape(item.reason)+'</p></details>':'')+'<div class="mc-source-links">'+link(source.url,source.label)+(source.docs?link(source.docs,source.id==='fred'?'经济数据发布日历':source.id==='financialjuice'?'官方 API 文档':'API 权限说明'):'')+'</div></article>';
    }).join('');
  }
  function retrievalNote(item) {
    return typeof item.retrievedAt==='string' && /Z$/.test(item.retrievedAt) && Number.isFinite(Date.parse(item.retrievedAt)) ? '<p class="mc-meta">实际取数 '+escape(item.retrievedAt.replace('T',' ').replace('Z',' UTC'))+' · 成功结果可缓存10分钟</p>' : '';
  }
  function renderReport(report) {
    const p=report.positioning;
    let html='<div class="mc-freshness"><span>截至 <strong>'+escape(report.asOf)+'</strong></span><span>报告生成时间 <time datetime="'+escape(report.collectedAt)+'">'+escape(report.collectedAt.replace('T',' ').replace('Z',' UTC'))+'</time></span></div>';
    const positioningHTML='<section aria-labelledby="mc-positioning-title"><div class="mc-section-heading"><h3 id="mc-positioning-title">标普 500 · 成交与对冲背景</h3><span class="mc-badge">'+escape(status(p.status))+'</span></div><dl class="mc-metrics">'+[['DIX 百分比',finite(p.dix)?number(p.dix*100)+'%':'不可用'],['GEX 估算美元',finite(p.gex)?number(p.gex)+' USD':'不可用'],['S&P 500',number(p.spx)]].map(([label,value])=>'<div><dt>'+label+'</dt><dd>'+value+'</dd></div>').join('')+'</dl><p class="mc-meta">观测日 '+escape(p.observationDate || '不可用')+' · '+link(p.sourceUrl,'原始来源')+(p.observationDate && p.observationDate<report.asOf?' · 早于截至日；非实时快照':'')+'</p>'+(p.reason?'<details class="mc-detail"><summary>可展开技术说明</summary><p class="mc-reason">'+escape(p.reason)+'</p>'+retrievalNote(p)+'</details>':'')+'<p class="mc-meta">DIX 为暗池卖空成交推导的聚合指标；GEX 为模型估算。两者用于理解市场结构，不是个股资金流或交易信号。</p></section>';
    html+='<section aria-labelledby="mc-macro-title"><h3 id="mc-macro-title">宏观观察</h3><div class="mc-table" tabindex="0" role="region" aria-label="宏观观察表，可横向滚动"><table><caption>保留每项最新可得观测；较早观测不等于数据源故障。</caption><thead><tr><th scope="col">指标</th><th scope="col">观测值</th><th scope="col">观测日 / 频率</th><th scope="col">可用性与原因</th></tr></thead><tbody>';
    html+=report.macro.length ? report.macro.map(item=>'<tr><th scope="row">'+link(item.sourceUrl,macroLabels[item.id] || item.name || item.id)+'</th><td class="mc-value">'+number(item.value)+(finite(item.value)?' <small>'+escape(displayUnit(item.units))+'</small>':'')+'</td><td>'+escape(item.observationDate || '不可用')+'<small>'+escape(displayFrequency(item.frequency) || '频率未知')+(item.retrievalMode==='latest-page'?' · 最新页面观测 / 历史截至日可能无覆盖':'')+(item.observationDate && item.observationDate<report.asOf?' · 早于截至日':'')+'</small></td><td>'+escape(status(item.status))+(item.reason?'<details class="mc-detail"><summary>可展开技术说明</summary><small>'+escape(item.reason)+'</small>'+retrievalNote(item)+'</details>':'')+'</td></tr>').join('') : '<tr><td colspan="4">没有可用宏观观测。</td></tr>';
    html+='</tbody></table></div><p class="mc-meta">FRED 日期是观测所属日期，不是发布时间。数据为最新修订值；选择历史截至日也不构成当时可得（PIT）数据，不能直接用于历史回测。</p></section>'+positioningHTML;
    if(report.warnings.length) html+='<aside class="mc-warnings" aria-label="数据边界"><h3>数据边界</h3><p class="mc-meta">部分来源可能需要授权、存在更新延迟或历史覆盖限制；缺失值保持不可用。</p><details class="mc-detail"><summary>可展开技术说明</summary><ul>'+[...new Set(report.warnings)].map(value=>'<li>'+escape(value)+'</li>').join('')+'</ul></details></aside>';
    dialog.querySelector('#market-context-result').innerHTML=html;
    dialog.querySelector('#market-context-sources').innerHTML=sourceCards(report);
  }
  function cancel() { controller?.abort(); controller=null; if(dialog) { dialog.querySelector('#market-context-refresh').disabled=false; dialog.querySelector('#market-context-result').removeAttribute('aria-busy'); } }
  function reset(message='行情连接已变化，请重新读取市场背景。', clearManual=true) { cancel(); if(clearManual) clearImport(); if(dialog) { dialog.querySelector('#market-context-result').replaceChildren(); dialog.querySelector('#market-context-sources').innerHTML=sourceCards(); dialog.querySelector('#market-context-status').textContent=message; } }
  function close() {
    cancel(); clearImport(); if(!dialog) return;
    if(typeof dialog.close==='function') dialog.close(); else dialog.removeAttribute('open');
    if(returnFocus?.isConnected) returnFocus.focus();
  }
  async function query(event) {
    event?.preventDefault(); if(!dialog) createDialog();
    if(!dialog.querySelector('form').reportValidity()) return;
    reset('正在读取宏观观测与市场结构…',false);
    const current=new root.AbortController(); controller=current;
    const result=dialog.querySelector('#market-context-result'), message=dialog.querySelector('#market-context-status');
    result.setAttribute('aria-busy','true'); dialog.querySelector('#market-context-refresh').disabled=true;
    try {
      const config={...connection()}, asOf=dialog.querySelector('#market-context-asof').value;
      const fetcher=options.request || root.FlowdeskIndicators?.request;
      if(!fetcher) throw new Error('市场背景请求组件尚未就绪，请刷新页面。');
      const report=await fetcher(createURL(config,asOf),value=>{if(controller===current && !current.signal.aborted) message.textContent=value.message || '后台正在采集公开来源…';},current.signal,config.token);
      if(controller!==current || current.signal.aborted) return;
      const latest=connection();
      if(['endpoint','token','market'].some(key=>latest[key]!==config[key])) { reset(); return; }
      validateReport(report,asOf); renderReport(report); message.textContent='已读取公开市场背景 · 截至 '+report.asOf+' · 缺失项保持不可用';
    } catch(error) {
      if(controller===current && !current.signal.aborted) { result.replaceChildren(); message.textContent=error.message || '市场背景读取失败，请重试。'; }
    } finally { if(controller===current) { controller=null; result.removeAttribute('aria-busy'); dialog.querySelector('#market-context-refresh').disabled=false; } }
  }
  function createDialog() {
    dialog=root.document.createElement('dialog'); dialog.id='market-context-dialog'; dialog.className='mc-dialog'; dialog.setAttribute('aria-labelledby','market-context-title'); dialog.setAttribute('aria-describedby','market-context-intro');
    dialog.innerHTML='<header class="mc-header"><div><span class="mc-kicker">MARKET CONTEXT</span><h2 id="market-context-title">宏观与市场结构</h2></div><button class="mc-button" id="market-context-close" type="button" aria-label="关闭市场背景">关闭</button></header><p id="market-context-intro" class="mc-intro">把宏观环境与市场结构放在同一视野，逐项核对日期与来源。</p><form class="mc-toolbar"><label for="market-context-asof">截至日<input id="market-context-asof" type="date" required></label><button class="mc-button mc-primary" id="market-context-refresh" type="submit">读取市场背景</button><button class="mc-button" id="market-context-cancel" type="button">取消查询</button></form><p id="market-context-status" role="status" aria-live="polite">等待查询。</p><div id="market-context-result"></div><section class="mc-manual" aria-labelledby="market-context-manual-title"><h3 id="market-context-manual-title">官方 DIX CSV · 本地预览</h3><p class="mc-meta">手动导入 · 浏览器内存 · 非实时 · 所选日期非 PIT。仅核对文件观测，不合并到服务端报告；关闭、更改日期或连接变化后需重新导入。</p><label for="market-context-csv">导入官方DIX CSV<input id="market-context-csv" type="file" accept=".csv,text/csv" aria-describedby="market-context-csv-help"></label><p id="market-context-csv-help" class="mc-meta">最大 2 MB；表头 date,price,dix,gex，仅支持无引号日期及数值字段。空数值显示不可用；选择不晚于截至日的最新行。文件不会上传或持久保存，来源与完整性需自行核对。</p><p id="market-context-import-status" class="mc-meta" role="status" aria-live="polite">尚未导入；文件不会上传或持久保存。</p><div id="market-context-manual-result"></div></section><section aria-labelledby="market-context-source-title"><div class="mc-section-heading"><h3 id="market-context-source-title">来源与接入</h3><span class="mc-meta">外部链接在新窗口打开</span></div><div class="mc-sources" id="market-context-sources">'+sourceCards()+'</div></section>';
    root.document.body.append(dialog);
    dialog.querySelector('form').addEventListener('submit',query);
    dialog.querySelector('#market-context-csv').addEventListener('change',importCSV);
    dialog.querySelector('#market-context-asof').addEventListener('change',()=>reset('截至日已变化，请重新读取市场背景。'));
    dialog.querySelector('#market-context-close').addEventListener('click',close);
    dialog.querySelector('#market-context-cancel').addEventListener('click',()=>reset('已取消查询。'));
    dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
    dialog.addEventListener('keydown',event=>{if(event.key==='Escape') { event.preventDefault(); close(); }});
    dialog.addEventListener('close',()=>{cancel(); clearImport(); if(returnFocus?.isConnected) returnFocus.focus();});
  }
  function open(trigger) {
    if(!dialog) createDialog();
    if(dialog.hasAttribute('open')) return;
    returnFocus=trigger || root.document.activeElement;
    const input=dialog.querySelector('#market-context-asof'); input.max=today(); input.value=date(connection().date) || today();
    if(typeof dialog.showModal==='function') dialog.showModal(); else dialog.setAttribute('open','');
    dialog.querySelector('#market-context-close').focus(); query();
  }
  function mount(config={}) {
    options={...options,...config}; if(mounted) return; mounted=true;
    root.document.addEventListener('click',event=>{const trigger=event.target.closest?.('#open-market-context'); if(trigger) {event.preventDefault();open(trigger);}});
    for(const name of ['flow-market','flow-disconnect','flow-connect']) root.addEventListener(name,()=>reset());
    root.addEventListener('flow-data',()=>{if(dialog) reset('行情快照已更新，请重新读取市场背景。');});
  }
  root.FlowdeskMarketContext={mount,open,close,query,createURL,validateReport,parseDixCSV}; mount();
})(window);
