'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ui = require('../dist/private.js');

test('更正表单保留执行身份并生成原子作废替代，已作废时仅追加替代',()=>{
  const original={id:'synthetic-original',kind:'buy',source:'schwab-csv',external_id:'exec-2'};
  const replacement=ui.eventFromValues({kind:'buy',symbol:'test',quantity:'1',price:'10',fees:'1',
    trade_date:'2026-01-02',sequence:'',replaces:original.id,external_id:''});
  const events=ui.correctionEvents(replacement,[original],'合成费用更正');
  assert.equal(events.length,2);
  assert.equal(events[0].kind,'void');
  assert.equal(events[0].target,original.id);
  assert.equal(events[1].replaces,original.id);
  assert.equal(events[1].external_id,'exec-2');
  assert.equal(events[1].source,'schwab-csv');
  const afterVoid=ui.correctionEvents(replacement,[original,{kind:'void',target:original.id}],'');
  assert.equal(afterVoid.length,1);
  assert.equal(afterVoid[0].external_id,'exec-2');
  assert.throws(()=>ui.correctionEvents({...replacement,external_id:'invented'},[original],'更正'),/执行/);
});

test('研究截止数量缺口明确标为已知部分，零部分不展示为确定零股',()=>{
  const html=ui.snapshotHTML({asOf:'2026-01-02',revision:1,quality:['position_timing_uncertain'],
    positions:[{symbol:'TEST',quantity:null,cost:null,group:'ungrouped',quantity_status:'known_partial',known_partial_quantity:'0'}],
    position_gaps:[{symbol:'TEST',uncertain_event_ids:['synthetic-buy'],dependent_event_ids:['synthetic-sell']}],
    totals_status:'known_partial',cash_balance:null,ledger_cash_delta:null,realized_pnl:null});
  assert.match(html,/截止总量未知/);
  assert.match(html,/仅已知部分/);
  assert.match(html,/synthetic-sell/);
  assert.match(html,/汇总.*未知/);
});

test('公开页面构造客户端不发请求，远程页面主动打开也不请求本机', async () => {
  let calls = 0;
  const client = ui.createClient({protocol:'https:',hostname:'example.github.io'}, async () => {calls++;});
  assert.equal(calls, 0);
  await assert.rejects(client.open(), /本机/);
  assert.equal(calls, 0);
});

test('未知成本与现金保留未知，用户内容安全转义', () => {
  const html = ui.snapshotHTML({asOf:'2026-01-02',revision:1,positions:[{symbol:'<TEST>',quantity:'3',cost:null,group:'core'}],cash_balance:null,ledger_cash_delta:'0',fees:'0',dividend_income:'0',realized_pnl:null,quality:['unknown_cost']});
  assert.match(html, /未知/);
  assert.match(html, /&lt;TEST&gt;/);
  assert.doesNotMatch(html, /<TEST>/);
});

test('令牌只在Header，关闭后不能继续读写私有API', async () => {
  const calls=[];
  const client=ui.createClient({protocol:'http:',hostname:'127.0.0.1'}, async (url,options)=>{
    calls.push({url,options});return {ok:true,json:async()=>url.endsWith('/session')?{session_token:'synthetic-session'}:{accounts:[]}};
  });
  await client.open('synthetic-flow');await client.call('accounts');
  assert.equal(calls[0].options.headers.Authorization,'Bearer synthetic-flow');
  assert.equal(calls[1].options.headers['X-Flowdesk-Session'],'synthetic-session');
  assert.equal(calls[1].options.mode,'same-origin');
  assert.doesNotMatch(calls.map(x=>x.url).join(''),/synthetic/);
  client.close();await assert.rejects(client.call('accounts'),/开启/);
});

test('接口错误可读，非JSON响应不会回显敏感原文', async () => {
  const client=ui.createClient({protocol:'http:',hostname:'localhost'},async()=>({ok:false,json:async()=>({error:'账户版本已变化，请重新预览。'})}));
  await assert.rejects(client.open(),/重新预览/);
  const bad=ui.createClient({protocol:'http:',hostname:'localhost'},async()=>({ok:false,json:async()=>{throw new Error('/Users/private');}}));
  await assert.rejects(bad.open(),error=>/格式异常/.test(error.message)&&!error.message.includes('/Users'));
});

test('未确认预览显示每一原文与问题，不把同价分笔压缩成一行', () => {
  const html=ui.previewHTML({revision:0,can_commit:false,errors:['需要确认'],rows:[0,1].map(i=>({line:i+2,raw:'<script>synthetic</script>',issues:[],warnings:['疑似重复'],selected:true,needs_reference:true,event:{kind:'buy',symbol:'TEST'}}))});
  assert.equal((html.match(/data-import-row=/g)||[]).length,2);
  assert.equal((html.match(/data-import-reference=/g)||[]).length,2);
  assert.doesNotMatch(html,/<script>/);
  assert.match(html,/待处理/);
});

test('期初空白成本保持null，现金与成交字段不混用', () => {
  const fields={kind:'opening',trade_date:'2026-01-01',symbol:'test',quantity:'3',total_cost:'',price:'',fees:'',amount:'',sequence:''};
  assert.equal(ui.eventFromValues(fields).total_cost,null);
  assert.equal(ui.eventFromValues(fields).symbol,'TEST');
  const cash=ui.eventFromValues({...fields,kind:'deposit',amount:'100'});
  assert.equal(cash.amount,'100');assert.equal(cash.price,undefined);assert.equal(cash.symbol,undefined);
});

test('私有模块无持久化、日志或导航写入，预览编辑后必须重新预览', () => {
  const js=fs.readFileSync('dist/private.js','utf8'),html=fs.readFileSync('dist/index.html','utf8');
  assert.doesNotMatch(js,/localStorage|sessionStorage|console\.|location\.(?:assign|href\s*=)|searchParams/);
  assert.match(js,/addEventListener\('input',invalidate\)/);
  assert.match(html,/id="private-confirm"[^>]*disabled/);
});

test('关闭会话时在途JSON解析结果不能重新建立会话',async()=>{
  let resolveBody;
  const ready=new Promise(resolve=>{resolveBody=resolve;});
  const client=ui.createClient({protocol:'http:',hostname:'localhost'},async()=>({ok:true,json:()=>ready}));
  const opening=client.open();
  await new Promise(resolve=>setImmediate(resolve));
  client.close();resolveBody({session_token:'late-synthetic-session'});
  await assert.rejects(opening,/关闭/);
  await assert.rejects(client.call('accounts'),/开启/);
});

test('实际表单提交在忙碌状态仍读到期初数量与未知成本',async()=>{
  const vm=require('node:vm'),elements=new Map(),requests=[];
  /** 只模拟DOM与HTTP边界，实际执行工作台事件和业务payload构造。 */
  function element(id) {
    if (!elements.has(id)) elements.set(id,{id,value:'',disabled:false,hidden:false,open:false,innerHTML:'',textContent:'',listeners:{},
      addEventListener(type,fn){this.listeners[type]=fn;},showModal(){this.open=true;},reset(){},querySelectorAll(){return [];},closest(){return {hidden:false};}});
    return elements.get(id);
  }
  const form=element('private-event');
  const names=['kind','symbol','quantity','total_cost','price','fees','amount','target','reason'];
  form.elements=Object.fromEntries(names.map(name=>[name,element('field-'+name)]));form.elements.kind.value='opening';
  const fields={kind:'opening',symbol:'test',quantity:'3',total_cost:'',trade_date:'2026-01-01',group:'core',sequence:''};
  class SyntheticFormData {
    /** 像浏览器一样拒绝从被disabled的fieldset取得可提交字段。 */
    constructor(){this.values=element('private-controls').disabled?{}:fields;}
    [Symbol.iterator](){return Object.entries(this.values)[Symbol.iterator]();}
  }
  const context=vm.createContext({AbortController,FormData:SyntheticFormData,document:{getElementById:element},
    window:{location:{protocol:'http:',hostname:'localhost'},FlowdeskPrivateResearch:{mount:()=>({refresh:async()=>{},clear(){}})},
      fetch:async(url,options)=>{requests.push({url,body:JSON.parse(options.body)});return {ok:true,json:async()=>
        url.endsWith('/session')?{session_token:'synthetic'}:url.endsWith('/accounts')?{accounts:[{id:'synthetic-account',name:'Synthetic',revision:0}]}:
        url.endsWith('/snapshot')?{revision:0,asOf:null,positions:[],quality:[]}:url.endsWith('/history')?{events:[]}:{} };}}});
  vm.runInContext(fs.readFileSync('dist/private.js','utf8'),context);
  element('private-session').listeners.submit({preventDefault(){}});
  await new Promise(resolve=>setImmediate(resolve));
  form.listeners.submit({preventDefault(){}});
  await new Promise(resolve=>setImmediate(resolve));
  const append=requests.find(r=>r.url.endsWith('/events/append'));
  assert.ok(append,'表单应真正发送追加事实');
  assert.equal(append.body.events[0].quantity,'3');
  assert.equal(append.body.events[0].total_cost,null);
});

test('后台页未派发原生close事件时，移除open属性也清空私有会话',()=>{
  const listeners={},dialog={open:true,addEventListener:(name,fn)=>{listeners[name]=fn;}};
  let observed,cleaned=0,callback;
  class SyntheticObserver {
    constructor(fn){callback=fn;}
    observe(target,options){observed={target,options};}
  }
  ui.watchDialogClosure(dialog,()=>{cleaned++;},SyntheticObserver);
  assert.equal(observed.target,dialog);
  assert.deepEqual(observed.options.attributeFilter,['open']);
  callback();assert.equal(cleaned,0,'仍然打开时不清除');
  dialog.open=false;callback();
  assert.equal(cleaned,1,'不依赖可能被后台页延迟的close事件');
  dialog.open=true;listeners.close();
  assert.equal(cleaned,1,'晚到的旧close事件不能清空已重新打开的会话');
});
