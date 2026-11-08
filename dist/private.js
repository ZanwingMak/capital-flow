'use strict';
// 私有数据只保留在此模块闭包与当前DOM中，不写URL、日志或浏览器持久存储。
(() => {
  const groups = {core:'底仓',tactical:'短线',ungrouped:'未分组'};
  const qualities = {unknown_cost:'成本未知',unknown_cash_baseline:'现金期初未知',no_market_valuation:'未接入估值',date_only_execution:'成交仅精确到日期',position_timing_uncertain:'截止持仓存在日期精度缺口',partial_ledger_totals:'汇总未知，仅有已知部分',intraday_or_future_events_excluded:'已排除当日不确定或截止后的事实'};

  /** 转义所有用户文字，避免原始CSV或研究内容作为HTML执行。 */
  function escape(value) {return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  /** 未知与真实零明确区分，Decimal文本不经浮点转换。 */
  function value(value) {return value === null || value === undefined || value === '' ? '未知' : escape(value);}
  /** 判断当前页面本身是否由直接本机HTTP服务提供。 */
  function isLocal(location) {return location.protocol === 'http:' && ['127.0.0.1','localhost','[::1]'].includes(location.hostname);}

  /** 构造只使用相对路径和内存令牌的客户端，构造时不发请求。 */
  function createClient(location, fetcher) {
    let token = '', authorization = '', generation = 0, controller = new AbortController();
    /** 只访问同源POST接口，关闭会话后丢弃在途结果。 */
    async function request(route, data = {}) {
      if (!isLocal(location)) throw new Error('请在本机看板主动开启私有工作台。');
      const epoch = generation;
      let response;
      try {
        response = await fetcher('/api/private/' + route, {method:'POST',mode:'same-origin',credentials:'omit',cache:'no-store',referrerPolicy:'no-referrer',
          signal:controller.signal,headers:{'Content-Type':'application/json',...(token ? {'X-Flowdesk-Session':token} : {}),...(authorization ? {Authorization:'Bearer ' + authorization} : {})},body:JSON.stringify(data)});
      } catch {throw new Error('本机私有请求未完成，请重试。');}
      if (epoch !== generation) throw new Error('私有会话已关闭。');
      let body;
      try {body = await response.json();} catch {throw new Error('本机返回格式异常。');}
      if (epoch !== generation) throw new Error('私有会话已关闭。');
      if (!response.ok) throw new Error(body.error || '私有请求失败。');
      return body;
    }
    return {
      /** 主动握手，现有FLOW_TOKEN仅由本次输入提供。 */
      async open(flowToken = '') {authorization = flowToken; const body = await request('session'); token = body.session_token;},
      /** 已开启会话才可访问业务API。 */
      async call(route, data = {}) {if (!token) throw new Error('请先开启本机会话。'); return request(route, data);},
      /** 清空令牌并取消在途请求。 */
      close() {generation++;token='';authorization='';controller.abort();controller=new AbortController();}
    };
  }

  /** 展示有依据的账本数量和成本，不显示模拟实时权益。 */
  function snapshotHTML(snapshot) {
    return `<p class="private-meta">持仓日期 ${value(snapshot.asOf)} · revision ${value(snapshot.revision)} · USD · 移动加权账面成本（非税务）</p>
      <p>${(snapshot.quality || []).map(q => escape(qualities[q] || q)).join(' / ')}</p>
      <div class="private-table"><table><thead><tr><th>正股</th><th>数量</th><th>已知总成本 USD</th><th>分组</th></tr></thead><tbody>${snapshot.positions.length ? snapshot.positions.map(p => `<tr><td>${escape(p.symbol)}</td><td>${p.quantity_status==='known_partial' ? `截止总量未知（仅已知部分 ${value(p.known_partial_quantity)} 股）` : value(p.quantity)}</td><td>${value(p.cost)}</td><td>${escape(groups[p.group])}</td></tr>`).join('') : '<tr><td colspan="4">尚无正股记录</td></tr>'}</tbody></table></div>
      ${(snapshot.position_gaps || []).map(g=>`<p>${escape(g.symbol)}：日期不确定事件 ${escape(g.uncertain_event_ids.join(', '))}；连同排除的依赖 ${escape(g.dependent_event_ids.join(', '))}。</p>`).join('')}
      ${snapshot.totals_status==='known_partial' ? '<p>现金与损益等汇总未知，已知部分不能当作账户总额。</p>' : ''}
      <dl class="private-totals"><dt>现金余额</dt><dd>${value(snapshot.cash_balance)}</dd><dt>账本现金变化</dt><dd>${value(snapshot.ledger_cash_delta)}</dd><dt>费用合计</dt><dd>${value(snapshot.fees)}</dd><dt>分红</dt><dd>${value(snapshot.dividend_income)}</dd><dt>已实现账面损益</dt><dd>${value(snapshot.realized_pnl)}</dd><dt>浮动损益 / 总回报</dt><dd>未知（未估值）</dd></dl>`;
  }

  /** 每一CSV原文均可检查，重复候选需逐笔独立参考号确认。 */
  function previewHTML(preview) {
    return `<p>账户 revision ${value(preview.revision)} · ${preview.can_commit ? '已校验，可确认当前冻结预览' : '待处理：' + escape(preview.errors.join('；'))}</p>
      <div class="private-table"><table><thead><tr><th>选择</th><th>原始行 / 内容</th><th>问题与确认</th></tr></thead><tbody>${preview.rows.map((r,i) => `<tr><td><input type="checkbox" data-import-row="${i}" aria-label="选择第${r.line}行" ${r.selected ? 'checked' : ''} ${r.issues.length ? 'disabled' : ''}></td><td><details><summary>行 ${r.line} · ${escape(r.event?.kind || '待核实')} ${escape(r.event?.symbol || '')}</summary><pre>${escape(r.raw)}</pre></details></td><td>${escape([...r.issues,...(r.warnings || [])].join('；'))}${r.needs_reference ? `<label>独立参考号<input data-import-reference="${i}" value="${escape(r.event?.reference || '')}" autocomplete="off"></label><label><input type="checkbox" data-import-distinct="${i}" ${r.distinct_confirmed ? 'checked' : ''}>确认此笔独立事实</label>` : ''}<label>人工顺序（同日混合买卖时必填）<input type="number" min="0" step="1" data-import-sequence="${i}" value="${escape(r.event?.sequence ?? '')}"></label></td></tr>`).join('')}</tbody></table></div>${preview.snapshot ? snapshotHTML(preview.snapshot) : ''}`;
  }

  /** 只传与动作有关的字段，空白成本保留null。 */
  function eventFromValues(fields) {
    const kind = fields.kind, event = {kind,trade_date:fields.trade_date,source:'manual-local',group:fields.group || 'ungrouped'};
    if (['opening','buy','sell','split','group','dividend'].includes(kind)) event.symbol = fields.symbol.trim().toUpperCase();
    if (['opening','buy','sell','split'].includes(kind)) event.quantity = fields.quantity;
    if (kind === 'opening') event.total_cost = fields.total_cost || null;
    if (['buy','sell'].includes(kind)) {event.price=fields.price;event.fees=fields.fees;}
    if (['cash_opening','deposit','withdrawal','fee','dividend'].includes(kind)) event.amount=fields.amount;
    if (kind === 'void') {event.target=fields.target;event.reason=fields.reason;}
    if (kind !== 'void' && fields.replaces) event.replaces=fields.replaces.trim();
    if (kind !== 'void' && fields.external_id) event.external_id=fields.external_id.trim();
    if (fields.sequence !== '') event.sequence=Number(fields.sequence);
    if (fields.effective_at) event.effective_at=fields.effective_at;
    event.raw = {...event};
    return event;
  }

  /** 从原审计记录继承真实身份，按需同批作废；服务端仍执行全部关联与去重校验。 */
  function correctionEvents(event, history, reason) {
    if (!event.replaces) return [event];
    const original=history.find(e=>e.id===event.replaces && e.kind!=='void');
    if (!original) throw new Error('被替代原事件不存在，请核对审计ID。');
    if (original.external_id && event.external_id && event.external_id!==original.external_id) throw new Error('更正必须保留真实执行ID。');
    const replacement={...event,source:original.source};
    for (const key of ['external_id','reference']) if (original[key]) replacement[key]=original[key];
    replacement.raw={...event.raw,correction_source:original.source,replaces:original.id};
    if (history.some(e=>e.kind==='void' && e.target===original.id)) return [replacement];
    if (!reason?.trim()) throw new Error('同批作废替代须填写更正原因。');
    return [{kind:'void',target:original.id,reason:reason.trim(),source:'manual-local',trade_date:event.trade_date},replacement];
  }

  /** 后台页可能延迟原生close事件，以open属性移除同步到微任务清理。 */
  function watchDialogClosure(dialog, cleanup, Observer = globalThis.MutationObserver) {
    const clearIfClosed=()=>{if (!dialog.open) cleanup();};
    dialog.addEventListener('close',clearIfClosed);
    if (typeof Observer === 'function') {
      const observer=new Observer(clearIfClosed);
      observer.observe(dialog,{attributes:true,attributeFilter:['open']});
    }
  }

  /** 绑定本机私有工作台；关闭即清理表单、原文和令牌。 */
  function bind() {
    const el = id => document.getElementById(id), dialog=el('private-dialog');
    if (!dialog) return;
    const client=createClient(window.location,window.fetch.bind(window));
    let account='', snapshot=null, csv='', preview=null, busy=false, workspaceGeneration=0;
    const commit=el('private-confirm');
    /** 任何编辑都使确认按钮失效，必须重新生成冻结预览。 */
    function invalidate() {preview=null;commit.disabled=true;}
    /** 在状态区显示固定流程消息，不向控制台写入私有内容。 */
    function status(message) {el('private-status').textContent=message;}
    /** 串行处理工作台操作并显示可读错误。 */
    async function run(action) {
      if (busy) return;
      busy=true;
      el('private-busy').hidden=false;
      el('private-controls').inert=true;
      el('private-session-button').disabled=true;
      try {await action();} catch(error) {status(error.message);} finally {
        busy=false;el('private-busy').hidden=true;el('private-controls').inert=false;el('private-session-button').disabled=false;
      }
    }
    /** 读取当前账户最新版本并使旧预览失效。 */
    async function refresh() {
      invalidate();
      snapshot=null;stressUI.clear();
      if (!account) {stressUI.sync();el('private-snapshot').textContent='先创建或选择账户。';await researchUI.refresh();return;}
      const generation=workspaceGeneration,requestedAccount=account;
      const refreshed=await client.call('snapshot',{account:requestedAccount});
      if (generation!==workspaceGeneration || requestedAccount!==account) return;
      snapshot=refreshed;
      stressUI.sync();
      el('private-snapshot').innerHTML=snapshotHTML(snapshot);
      const history=await client.call('history',{account});
      el('private-history').textContent=JSON.stringify(history.events,null,2);
      await researchUI.refresh();
    }
    /** 列出账户，只有本次DOM选择持有账户ID。 */
    async function accounts(selected='') {
      const generation=workspaceGeneration;
      const result=await client.call('accounts');
      if (generation!==workspaceGeneration) return;
      el('private-account').innerHTML='<option value="">选择账户</option>' + result.accounts.map(a=>`<option value="${escape(a.id)}">${escape(a.name)} · v${a.revision}</option>`).join('');
      account=selected || (result.accounts.length === 1 ? result.accounts[0].id : '');
      el('private-account').value=account;
      await refresh();
    }
    /** 仅保留明确相关的输入项，减少现金/数量口径误用。 */
    function fieldsForAction() {
      const kind=el('private-event').elements.kind.value;
      const allowed={symbol:['opening','buy','sell','split','group','dividend'],quantity:['opening','buy','sell','split'],total_cost:['opening'],price:['buy','sell'],fees:['buy','sell'],amount:['cash_opening','deposit','withdrawal','fee','dividend'],target:['void']};
      for (const [name,kinds] of Object.entries(allowed)) el('private-event').elements[name].closest('label').hidden=!kinds.includes(kind);
    }
    const researchUI=window.FlowdeskPrivateResearch.mount({client,el,context:()=>({account,snapshot}),run,status});
    // 旧测试DOM或旧缓存没有模块时仍可使用原工作台；生产页面按顺序载入模块。
    const stressUI=window.FlowdeskStressLab?.mount({root:el('private-stress'),context:()=>({account,snapshot})}) || {
      /** 未加载实验模块时保留既有工作台关闭流程。 */
      clear(){},
      /** 未加载实验模块时保留既有工作台刷新流程。 */
      sync(){}
    };
    el('open-private').addEventListener('click',()=>{dialog.showModal();stressUI.sync();status(isLocal(window.location)?'主动开启本机会话后访问私有台账。':'GitHub Pages不能读取本机私有数据，请打开本机看板。');el('private-session-button').hidden=!isLocal(window.location);});
    el('private-session').addEventListener('submit',event=>{event.preventDefault();run(async()=>{
      await client.open(el('private-flow-token').value);el('private-flow-token').value='';el('private-workspace').hidden=false;
      await accounts();status('本机会话已开启，仅在当前窗口保留令牌。');
    });});
    el('private-create').addEventListener('submit',event=>{event.preventDefault();run(async()=>{
      const result=await client.call('accounts/create',{name:el('private-name').value});el('private-name').value='';await accounts(result.id);status('账户已创建。');
    });});
    el('private-account').addEventListener('change',()=>{
      workspaceGeneration++;account=el('private-account').value;snapshot=null;stressUI.clear();
      csv='';el('private-file').value='';el('private-preview').textContent='';
      run(refresh);
    });
    el('private-refresh').addEventListener('click',()=>run(refresh));
    el('private-event').elements.kind.addEventListener('change',fieldsForAction);
    el('private-event').addEventListener('submit',event=>{event.preventDefault();run(async()=>{
      if (!account || !snapshot) throw new Error('请先选择账户。');
      const fields=Object.fromEntries(new FormData(el('private-event')));
      const fact=eventFromValues(fields);
      const history=fact.replaces ? (await client.call('history',{account})).events : [];
      await client.call('events/append',{account,revision:snapshot.revision,events:correctionEvents(fact,history,fields.reason)});
      el('private-event').reset();fieldsForAction();
      invalidate();await refresh();status('事实已追加，原始记录保留。');
    });});
    el('private-file').addEventListener('change',()=>run(async()=>{
      invalidate();csv='';el('private-preview').textContent='';
      const file=el('private-file').files[0];
      if (!file) {csv='';return;}
      if (file.size > 1024*1024) throw new Error('CSV不能超过1MiB。');
      const generation=workspaceGeneration,content=await file.text();
      if (generation !== workspaceGeneration) return;
      csv=content;status('文件仅在内存中，点击解析预览。');
    }));
    el('private-preview-button').addEventListener('click',()=>run(async()=>{
      if (!account || !csv) throw new Error('请先选择账户及CSV文件。');
      invalidate();preview=await client.call('import/preview',{account,csv});
      el('private-preview').innerHTML=previewHTML(preview);commit.disabled=!preview.can_commit;status('请核对逐行原文和预览数量。');
    }));
    el('private-preview').addEventListener('input',invalidate);
    el('private-repreview').addEventListener('click',()=>run(async()=>{
      const selections=Array.from(el('private-preview').querySelectorAll('[data-import-row]:checked')).map(input=>{
        const row=Number(input.dataset.importRow), ref=el('private-preview').querySelector(`[data-import-reference="${row}"]`), distinct=el('private-preview').querySelector(`[data-import-distinct="${row}"]`), sequence=el('private-preview').querySelector(`[data-import-sequence="${row}"]`);
        return {row,...(ref?.value?{reference:ref.value,distinct:distinct.checked}:{}),...(sequence?.value!==''?{sequence:Number(sequence.value)}:{})};
      });
      invalidate();preview=await client.call('import/preview',{account,csv,selections});
      el('private-preview').innerHTML=previewHTML(preview);commit.disabled=!preview.can_commit;
      status(preview.can_commit?'已冻结所选事实，请确认导入。':'请处理问题后重新预览。');
    }));
    commit.addEventListener('click',()=>run(async()=>{
      if (!preview?.can_commit) throw new Error('请先重新预览。');
      const frozen=preview;invalidate();await client.call('import/commit',{account,preview_id:frozen.preview_id,payload_id:frozen.payload_id});
      csv='';el('private-file').value='';el('private-preview').textContent='';await refresh();status('整批导入完成。');
    }));
    watchDialogClosure(dialog,()=>{
      workspaceGeneration++;client.close();account='';snapshot=null;csv='';invalidate();
      researchUI.clear();
      stressUI.clear();
      dialog.querySelectorAll('form').forEach(form=>form.reset());
      for (const id of ['private-snapshot','private-preview','private-history','private-account']) el(id).textContent='';
      el('private-workspace').hidden=true;status('私有会话已关闭。');
    });
    fieldsForAction();
  }
  if (typeof module !== 'undefined') module.exports={escape,value,isLocal,createClient,snapshotHTML,previewHTML,eventFromValues,correctionEvents,watchDialogClosure};
  if (typeof document !== 'undefined') bind();
})();
