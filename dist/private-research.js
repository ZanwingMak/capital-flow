'use strict';
// 只提供纯展示函数与挂载入口，证据、账户和令牌只保存在实例闭包。
(() => {
  /** 转义人工证据所有文字。 */
  function escape(value) {return String(value ?? '未知').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  /** 收集独立数值与时间字段，空白保持null。 */
  function eventValues(fields) {
    const event={};
    for (const key of ['kind','scope','symbol','title','source','url','published_at','available_at','actual','expected','previous','revised','period','unit','notes']) event[key]=fields[key] || null;
    if (event.symbol) event.symbol=event.symbol.trim().toUpperCase();
    return event;
  }
  /** 只链接服务端已校验的HTTP(S)证据；再防御协议、凭证和浏览器解析歧义。 */
  function sourceLink(value) {
    try {
      if (!/^https?:\/\//i.test(value) || /[\\\s\x00-\x1f\x7f]/.test(value)) throw new Error();
      const url=new URL(value);
      if (!['http:','https:'].includes(url.protocol) || url.username || url.password) throw new Error();
      return `<a href="${escape(url.href)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">${escape(value)}</a>`;
    } catch {return escape(value);}
  }
  /** 人工录入不视为自动核实，四种时间各自展示。 */
  function evidenceHTML(events) {
    if (!events.length) return '<p>尚无事件证据；可手工录入来源及时间。</p>';
    return events.map(e=>`<details><summary>${escape(e.title)} · v${e.version} · 人工录入，未自动核实</summary><p>${escape(e.kind)} · ${escape(e.symbol || 'global')} · 来源 ${escape(e.source)}</p><p>URL ${sourceLink(e.url)}</p><p>发布时间 ${escape(e.published_at)}<br>声称首次可知 ${escape(e.available_at)}<br>实际首次记录 ${escape(e.first_seen_at)}<br>本版本抓取/录入 ${escape(e.captured_at)}</p><p>实际值 ${escape(e.actual)} · 预期 ${escape(e.expected)} · 前值 ${escape(e.previous)} · 修订值 ${escape(e.revised)} · 期间 ${escape(e.period)} · 单位 ${escape(e.unit)}</p><p>${escape(e.notes || '')}</p></details>`).join('');
  }
  /** 挂载支持/反面选择、版本化人工事件、冻结研究与本地下载。 */
  function mount({client,el,context,run,status}) {
    let events=[],records=[],editing=null,report=null;
    /** 下载只产生当前内存Blob，文件名不含账户、标的或论点。 */
    function download(content,format) {
      const url=URL.createObjectURL(new Blob([content],{type:format==='json'?'application/json;charset=utf-8':'text/markdown;charset=utf-8'}));
      const a=document.createElement('a');a.href=url;a.download='flowdesk-private-report.'+(format==='json'?'json':'md');a.click();URL.revokeObjectURL(url);
    }
    /** 显示已冻结的Markdown正文，始终按纯文本渲染。 */
    async function showReport() {
      report=null;
      const id=el('private-record-select').value;
      if (!id) {el('private-report').textContent='选择一条历史研究查看冻结报告。';return;}
      report=await client.call('research/export',{id,format:'markdown'});
      el('private-report').textContent=report.content;
    }
    /** 刷新事件及当前账户的冻结记录，不重算旧报告。 */
    async function refresh() {
      const {account}=context();
      events=(await client.call('evidence/list')).events;
      el('private-evidence-list').innerHTML=evidenceHTML(events);
      el('private-event-edit').innerHTML='<option value="">新增人工事件</option>'+events.map(e=>`<option value="${escape(e.id)}">${escape(e.title)} · v${e.version}</option>`).join('');
      editing=null;
      const options=events.map(e=>`<option value="${escape(e.id)}">${escape(e.title)} · v${e.version} · ${escape(e.symbol || 'global')}</option>`).join('');
      el('private-support').innerHTML=options;el('private-against').innerHTML=options;
      records=account?(await client.call('research/list',{account})).records:[];
      el('private-record-select').innerHTML='<option value="">选择冻结研究</option>'+records.map(r=>`<option value="${escape(r.id)}">${escape(r.saved_at)} · v${r.snapshot.revision} · ${escape(r.thesis.slice(0,60))}</option>`).join('');
      report=null;el('private-report').textContent=records.length?'选择历史研究查看或导出。':'尚无冻结研究。';
    }
    /** 关闭会话清空本实例的证据与报告，以及对应DOM。 */
    function clear() {
      events=[];records=[];editing=null;report=null;
      for (const id of ['private-evidence-list','private-event-edit','private-support','private-against','private-record-select','private-report','private-event-version']) el(id).textContent='';
    }
    el('private-event-edit').addEventListener('change',()=>{
      editing=events.find(e=>e.id===el('private-event-edit').value) || null;
      const form=el('private-evidence-form');form.reset();
      if (editing) for (const [key,val] of Object.entries(editing)) if (form.elements.namedItem(key)) form.elements.namedItem(key).value=val ?? '';
      el('private-event-version').textContent=editing?`更新将追加v${editing.version+1}，保留实际首次记录 ${editing.first_seen_at}；已有研究保持旧版本。`:'新增人工事件；服务器记录实际首次录入时间。';
    });
    el('private-evidence-form').addEventListener('submit',event=>{event.preventDefault();run(async()=>{
      const data=eventValues(Object.fromEntries(new FormData(el('private-evidence-form'))));
      await client.call('evidence/save',{event:data,...(editing?{event_id:editing.id,version:editing.version}:{})});
      el('private-evidence-form').reset();await refresh();status('人工事件已保存，未自动核实；旧证据版本保留。');
    });});
    el('private-study-form').addEventListener('submit',event=>{event.preventDefault();run(async()=>{
      const {account,snapshot}=context();if (!account || !snapshot) throw new Error('请先选择账户并刷新持仓。');
      const form=el('private-study-form'), fields=Object.fromEntries(new FormData(form));
      const record={account,revision:snapshot.revision,as_of:fields.as_of || new Date().toISOString(),thesis:fields.thesis,trigger:fields.trigger,invalidation:fields.invalidation,group:fields.group,
        support:Array.from(el('private-support').selectedOptions,o=>o.value),against:Array.from(el('private-against').selectedOptions,o=>o.value)};
      const saved=await client.call('research/save',{record});await refresh();el('private-record-select').value=saved.id;await showReport();status('已冻结账户快照和证据版本；未来或未知时间证据仅列线索。');
    });});
    el('private-record-select').addEventListener('change',()=>run(showReport));
    el('private-report-refresh').addEventListener('click',()=>run(refresh));
    for (const format of ['json','markdown']) el('private-download-'+format).addEventListener('click',()=>run(async()=>{
      const id=el('private-record-select').value;if (!id) throw new Error('请先选择冻结研究。');
      const result=await client.call('research/export',{id,format});download(result.content,format);status('私有报告已生成下载，请保存在仓库外。');
    }));
    return {refresh,clear};
  }
  if (typeof module!=='undefined') module.exports={eventValues,evidenceHTML};
  if (typeof window!=='undefined') window.FlowdeskPrivateResearch={mount};
})();
