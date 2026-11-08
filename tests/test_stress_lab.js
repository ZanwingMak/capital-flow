'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const lab = require('../dist/stress-lab.js');

/** 构造仅存在内存的合成持仓，不使用账户文件。 */
function positions() {
  return [{symbol:'SYN-A',quantity:'2',group:'core'}, {symbol:'SYN-B',quantity:'3',group:'tactical'},
    {symbol:'SYN-C',quantity:'1',group:'unexpected'}];
}

test('完整覆盖按数量乘人工价格计算，分组与逐股冲击汇总一致且不修改快照',()=>{
  const snapshot={positions:positions(),revision:0,asOf:'2026-01-02'}, before=JSON.stringify(snapshot);
  const rows=lab.copyRows(snapshot);
  const result=lab.calculate(rows,{prices:['100','20','40'],globalShock:'-10',overrides:['','0','-100']});
  assert.equal(result.covered,3);
  assert.deepEqual(result.totals,{baseline:300,scenarioValue:240,change:-60});
  assert.deepEqual(result.groups.core.totals,{baseline:200,scenarioValue:180,change:-20});
  assert.equal(result.groups.tactical.totals.change,0);
  assert.equal(result.groups.ungrouped.totals.change,-40);
  assert.equal(result.rows[2].scenarioPrice,0);
  assert.equal(JSON.stringify(snapshot),before);
  assert.equal(rows[2].group,'ungrouped');
});

test('部分与无覆盖保留缺口，空值不冒充零，无组合收益率',()=>{
  const rows=lab.copyRows({positions:positions()});
  const partial=lab.calculate(rows,{prices:['100','','bad'],globalShock:'-5'});
  assert.equal(partial.covered,1);
  assert.deepEqual(partial.missing,['SYN-B','SYN-C']);
  assert.equal(partial.totals.baseline,200);
  assert.equal(partial.totals.change,-10);
  assert.equal(partial.groups.tactical.totals,null);
  assert.equal(partial.rows[1].baseline,null);
  assert.equal(partial.portfolioReturn,undefined);
  for (const empty of [rows,[]]) {
    const result=lab.calculate(empty,{prices:[],globalShock:'0'});
    assert.equal(result.covered,0);
    assert.equal(result.totals,null);
  }
});

test('未知、部分和缺口数量均不可用，明确的零数量与零价格仍可计算',()=>{
  const rows=lab.copyRows({positions:[
    {symbol:'UNKNOWN',quantity:null}, {symbol:'PART',quantity:'7',quantity_status:'known_partial',known_partial_quantity:'7'},
    {symbol:'ZERO',quantity:'0'}, {symbol:'PRICE0',quantity:'1'}, {symbol:'GAP',quantity:'3'},
    {symbol:'STATUS',quantity:'4',quantity_status:'unknown'}],position_gaps:[{symbol:'GAP'},{symbol:'ONLY-GAP'}]});
  const result=lab.calculate(rows,{prices:rows.map(()=> '0'),globalShock:'-100'});
  assert.equal(result.covered,2);
  assert.equal(result.totals.baseline,0);
  assert.equal(result.rows[0].baseline,null);
  assert.match(result.rows[1].reasons.join(),/截止总量未知/);
  assert.match(result.rows[4].reasons.join(),/截止总量未知/);
  assert.equal(result.rows.at(-1).symbol,'ONLY-GAP');
  assert.equal(result.rows.at(-1).baseline,null);
});

test('严格数字解析拒绝非有限、负数、畸形和过大值，真正的0保留',()=>{
  for (const input of ['',null,undefined,' ',false,[],{},'1,000','1x','0x10','1e3','Infinity','NaN',Infinity,NaN,-1,'-1','9'.repeat(400),'1000000000001']) {
    assert.ok(lab.parseNumber(input).error,`应拒绝 ${String(input)}`);
  }
  for (const input of ['0',0,'0.0',' 0 ','.5','10.25']) assert.equal(lab.parseNumber(input).error,'');
  const rows=[{symbol:'SYN',quantity:Infinity,group:'core'}];
  assert.equal(lab.calculate(rows,{prices:['1'],globalShock:'0'}).covered,0);
  rows[0].quantity='-2';
  assert.equal(lab.calculate(rows,{prices:['1'],globalShock:'0'}).covered,0);
  for (const input of ['-1',Infinity,NaN,'1x']) {
    assert.equal(lab.calculate([{symbol:'SYN',quantity:'1',group:'core'}],{prices:[input],globalShock:'0'}).covered,0);
  }
});

test('冲击上下限和空值显式校验，独立覆盖0有效，-100%不产生负价格',()=>{
  const rows=lab.copyRows({positions:positions()});
  for (const shock of ['','bad','-100.01','1000.01',Infinity]) {
    const result=lab.calculate(rows,{prices:['100','20','40'],globalShock:shock});
    assert.equal(result.covered,0);
    assert.match(result.rows[0].reasons.join(),/全局冲击/);
  }
  const result=lab.calculate(rows,{prices:['100','20','40'],globalShock:'-100',overrides:['0','bad','']});
  assert.equal(result.rows[0].scenarioPrice,100);
  assert.equal(result.rows[1].scenarioPrice,null);
  assert.equal(result.rows[2].scenarioPrice,0);
  assert.equal(lab.calculate(rows,{prices:['100','20','40'],globalShock:'1000'}).rows[0].scenarioPrice,1100);
});

test('乘积与累计超出可表示金额边界时阻止汇总，不显示Infinity或静默丢弃',()=>{
  const over=lab.calculate([{symbol:'HUGE',quantity:'1000000000000',group:'core'}],{prices:['1000000000000'],globalShock:'0'});
  assert.equal(over.covered,0);
  assert.match(over.rows[0].reasons.join(),/金额/);
  const scenario=lab.calculate([{symbol:'HUGE',quantity:'1',group:'core'}],{prices:['1000000000000'],globalShock:'1000'});
  assert.equal(scenario.covered,0);
  const summed=lab.calculate([{symbol:'A',quantity:'1',group:'core'},{symbol:'B',quantity:'1',group:'tactical'}],
    {prices:['600000000000','600000000000'],globalShock:'0'});
  assert.equal(summed.totals,null);
  assert.match(summed.error,/汇总/);
  assert.equal(summed.groups.core.totals,null,'总体汇总失败时不展示可混淆的局部分组总额');
  const tiny='0.'+'0'.repeat(199)+'1';
  assert.equal(lab.calculate([{symbol:'TINY',quantity:tiny,group:'core'}],{prices:[tiny],globalShock:'0'}).covered,0,'正数乘积下溢不能伪装真实0');
});

test('参考时间必须手填有效带时区ISO时间，不能以空白或日期代替',()=>{
  for (const input of ['', '2026-01-02','2026-02-30T12:00:00Z','2026-01-02T25:00:00Z','2026-01-02T12:00:00']) {
    assert.ok(lab.referenceTimeError(input));
  }
  assert.equal(lab.referenceTimeError('2026-01-02T10:30:00-05:00'),'');
  assert.equal(lab.referenceTimeError('2026-01-02T15:30:00Z'),'');
  assert.ok(lab.referenceTimeError('9999-01-02T15:30:00Z'));
});

/** 最小DOM边界：真实模块创建节点并绑定事件，禁止任何innerHTML注入。 */
function dom() {
  class Element {
    /** 保存合成节点的属性、子节点及监听器。 */
    constructor(tag='div') {this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.attributes={};this.value='';this.hidden=false;this.open=true;this._text='';this.style={};}
    /** 逐一挂载真实创建的节点。 */
    append(...nodes) {this.children.push(...nodes);}
    /** 实现DOM常用的单节点追加。 */
    appendChild(node) {this.append(node);return node;}
    /** 清理时同时移除所有子节点。 */
    replaceChildren(...nodes) {this.children=[];this._text='';this.append(...nodes);}
    /** 设置纯文本不会解析标签。 */
    set textContent(value) {this._text=String(value);this.children=[];}
    /** 汇集当前可见节点文本供断言。 */
    get textContent() {return this._text+this.children.map(node=>node.textContent).join('');}
    /** 新模块必须通过安全节点API渲染。 */
    set innerHTML(value) {throw new Error('压力实验室不得注入HTML：'+value);}
    /** 保存可访问性与表单属性。 */
    setAttribute(key,value) {this.attributes[key]=String(value);}
    /** 记录真实事件处理器。 */
    addEventListener(type,fn) {(this.listeners[type] ||= []).push(fn);}
    /** 从输入或按钮派发真实绑定事件。 */
    fire(type) {for (const fn of this.listeners[type] || []) fn({target:this,preventDefault(){}});}
  }
  const root=new Element(), document={createElement:tag=>new Element(tag)};
  /** 按ID查找当前节点，确保已清除的节点不再可见。 */
  function find(id,node=root) {if (node.id===id) return node;for (const child of node.children) {const hit=find(id,child);if (hit) return hit;}return null;}
  /** 输入数据并发送input事件，覆盖结果失效处理。 */
  function input(id,value) {const node=find(id);assert.ok(node,id);node.value=value;node.fire('input');}
  return {root,document,find,input,Element};
}

/** 挂载实际实验室，初始持仓仍只存在授权上下文中。 */
function mounted() {
  const ui=dom();
  let current={account:'synthetic-account',snapshot:{asOf:'2026-01-02',revision:0,positions:positions()}};
  const instance=lab.mount({root:ui.root,document:ui.document,context:()=>current});
  instance.sync();
  return {...ui,instance,getContext:()=>current,setContext:value=>{current=value;}};
}

/** 用真实输入事件完成一次合成情景。 */
function simulate(ui) {
  ui.find('stress-load').fire('click');
  ui.input('stress-time','2026-01-02T15:30:00Z');
  ['100','20','40'].forEach((value,i)=>ui.input('stress-price-'+i,value));
  ui.find('stress-preset-10').fire('click');
  ui.find('stress-run').fire('click');
}

test('实际DOM载入按钮才复制持仓、手填价格时间、预设与覆盖及清除均生效',()=>{
  const ui=mounted(), snapshot=ui.getContext().snapshot;
  assert.doesNotMatch(ui.root.textContent,/SYN-A/);
  assert.equal(ui.find('stress-price-0'),null);
  simulate(ui);
  assert.match(ui.find('stress-source').textContent,/2026-01-02.*revision 0/);
  assert.match(ui.find('stress-results').textContent,/270\.00/);
  assert.match(ui.find('stress-results').textContent,/-30\.00/);
  ui.input('stress-shock-0','-100');
  assert.equal(ui.find('stress-results').textContent,'','编辑后立即移除旧结果');
  ui.find('stress-run').fire('click');
  assert.match(ui.find('stress-results').textContent,/-210\.00/);
  ui.find('stress-overrides').fire('click');
  assert.equal(ui.find('stress-shock-0').value,'');
  ui.find('stress-run').fire('click');
  assert.match(ui.find('stress-results').textContent,/-30\.00/);
  assert.equal(snapshot.positions[0].quantity,'2');
  ui.find('stress-clear').fire('click');
  assert.equal(ui.find('stress-price-0'),null);
  assert.doesNotMatch(ui.root.textContent,/SYN-A/);
});

test('实际DOM拒绝缺失时间与冲击、显示缺口原因，不从成本补价格',()=>{
  const ui=mounted();
  ui.getContext().snapshot.positions[0].cost='9999';
  ui.find('stress-load').fire('click');
  assert.equal(ui.find('stress-price-0').value,'');
  ui.find('stress-run').fire('click');
  assert.match(ui.find('stress-message').textContent,/参考.*时间/);
  ui.input('stress-time','2026-01-02T15:30:00Z');
  ui.find('stress-run').fire('click');
  assert.match(ui.find('stress-results').textContent,/全局冲击/);
  ui.find('stress-preset-5').fire('click');
  ui.input('stress-price-0','100');
  ui.find('stress-run').fire('click');
  assert.match(ui.find('stress-results').textContent,/1 \/ 3/);
  assert.match(ui.find('stress-results').textContent,/SYN-B.*参考价格/);
  assert.match(ui.find('stress-results').textContent,/SYN-C.*参考价格/);
});

test('账户、revision和日期变化清空输入，旧按钮不能跨账户采用快照',()=>{
  const ui=mounted(),staleLoad=ui.find('stress-load');simulate(ui);
  const staleRun=ui.find('stress-run');
  ui.setContext({...ui.getContext(),account:'another-synthetic'});
  staleRun.fire('click');
  assert.equal(ui.find('stress-price-0'),null);
  staleLoad.fire('click');
  assert.equal(ui.find('stress-price-0'),null,'旧generation载入按钮不能读取新账户');
  simulate(ui);
  ui.getContext().snapshot.revision++;
  ui.instance.sync();
  assert.equal(ui.find('stress-price-0'),null);
  simulate(ui);
  ui.getContext().snapshot.asOf='2026-01-03';ui.instance.sync();
  assert.equal(ui.find('stress-price-0'),null);
  simulate(ui);ui.instance.clear();
  assert.equal(ui.root.children.length,0);
  staleRun.fire('click');assert.equal(ui.root.children.length,0);
});

test('恶意标的只以textContent显示，模块在禁止网络、存储、日志、导航的上下文可工作',()=>{
  const ui=dom();
  const sandbox={window:{},document:ui.document};
  /** 任何额外I/O都是本测试的失败。 */
  function forbidden() {throw new Error('禁止I/O');}
  for (const key of ['fetch','XMLHttpRequest','WebSocket','localStorage','sessionStorage','indexedDB','location']) {
    Object.defineProperty(sandbox,key,{get:forbidden});Object.defineProperty(sandbox.window,key,{get:forbidden});
  }
  sandbox.console={log:forbidden,error:forbidden,warn:forbidden};
  vm.runInNewContext(fs.readFileSync('dist/stress-lab.js','utf8'),sandbox);
  const malicious='<img src=x onerror=alert(1)>';
  const instance=sandbox.window.FlowdeskStressLab.mount({root:ui.root,document:ui.document,
    context:()=>({account:'synthetic',snapshot:{revision:1,asOf:null,positions:[{symbol:malicious,quantity:'1',group:'__proto__'}]}})});
  instance.sync();ui.find('stress-load').fire('click');
  assert.match(ui.root.textContent,/<img src=x onerror=alert\(1\)>/);
  assert.equal(ui.find('stress-price-0').value,'');
  ui.input('stress-time','2026-01-02T15:30:00Z');ui.input('stress-price-0','100');
  ui.find('stress-preset-20').fire('click');ui.find('stress-run').fire('click');
  assert.match(ui.find('stress-results').textContent,/-20\.00/);
  instance.clear();assert.equal(ui.root.textContent,'');
});

test('生产入口真实绑定实验室，切换账户、刷新与后台关闭均即时清空且不增加API调用',async()=>{
  const ui=dom(),elements=new Map(),requests=[];
  let observerCallback,revision=0,holdSnapshot=false,releaseSnapshot;
  /** 原工作台的HTML边界使用单独节点，实验室仍禁止innerHTML。 */
  class WorkspaceElement extends ui.Element {
    /** 仅原工作台需要HTML赋值，本测试不解析这些非实验室片段。 */
    set innerHTML(value) {this._html=value;}
    /** 为既有表单提供无副作用的重置边界。 */
    reset() {this.value='';}
    /** 模拟主对话框的原生打开动作。 */
    showModal() {this.open=true;}
    /** 不涉及本轮CSV和其他表单的节点查询。 */
    querySelectorAll() {return [];}
    /** 支持既有按动作隐藏表单标签的逻辑。 */
    closest() {return {hidden:false};}
  }
  /** 查找主工作台节点，实验室由模块真正创建。 */
  function el(id) {
    if (id==='private-stress') return ui.root;
    if (!elements.has(id)) elements.set(id,new WorkspaceElement());
    return elements.get(id);
  }
  const form=el('private-event');
  form.elements=Object.fromEntries(['kind','symbol','quantity','total_cost','price','fees','amount','target'].map(name=>[name,el('field-'+name)]));
  form.elements.kind.value='opening';
  class SyntheticObserver {
    /** 保存真实关闭监听器提供的清理回调。 */
    constructor(callback) {observerCallback=callback;}
    /** 验证真实生产代码观察对话框的open属性。 */
    observe(target,options) {assert.equal(target,el('private-dialog'));assert.deepEqual(Array.from(options.attributeFilter),['open']);}
  }
  const sandbox={AbortController,MutationObserver:SyntheticObserver,document:{...ui.document,getElementById:el},window:{
    location:{protocol:'http:',hostname:'localhost'},FlowdeskPrivateResearch:{mount:()=>({refresh:async()=>{},clear(){}})},
    /** 仅模拟既有授权私有接口，不创建服务或数据库。 */
    fetch:async(url,options)=>{
      requests.push(url);const body=JSON.parse(options.body);
      return {ok:true,json:async()=>{
        if (url.endsWith('/snapshot') && holdSnapshot) await new Promise(resolve=>{releaseSnapshot=resolve;});
        return url.endsWith('/session')?{session_token:'synthetic'}:
        url.endsWith('/accounts')?{accounts:[{id:'synthetic-account',name:'Synthetic',revision}]}:
        url.endsWith('/snapshot')?{asOf:'2026-01-02',currency:'USD',revision,positions:positions().map(row=>({...row,symbol:body.account==='other'?'OTHER':row.symbol})),quality:[]}:
        {events:[]};}};
    }
  }};
  const context=vm.createContext(sandbox),html=fs.readFileSync('dist/index.html','utf8');
  const scripts=Array.from(html.matchAll(/<script src="(stress-lab\.js|private\.js)[^"]*" defer><\/script>/g),match=>match[1]);
  assert.deepEqual(scripts,['stress-lab.js','private.js'],'生产入口必须在工作台之前载入模块');
  for (const script of scripts) vm.runInContext(fs.readFileSync('dist/'+script,'utf8'),context);
  assert.equal(requests.length,0,'挂载不能开启会话或取快照');
  el('open-private').fire('click');el('private-session').fire('submit');
  await new Promise(resolve=>setImmediate(resolve));
  const before=requests.length;
  simulate(ui);
  assert.equal(requests.length,before,'载入、编辑和计算均只读取已有上下文');
  const oldPrice=ui.find('stress-price-0'),oldResult=ui.find('stress-results');
  el('private-refresh').fire('click');
  assert.equal(ui.find('stress-price-0'),null,'刷新请求完成之前就清空');
  assert.equal(oldPrice.value,'');assert.equal(oldResult.textContent,'');
  await new Promise(resolve=>setImmediate(resolve));
  simulate(ui);revision++;
  el('private-refresh').fire('click');await new Promise(resolve=>setImmediate(resolve));
  assert.equal(ui.find('stress-price-0'),null);
  simulate(ui);el('private-account').value='other';el('private-account').fire('change');
  assert.equal(ui.find('stress-price-0'),null);
  assert.doesNotMatch(ui.root.textContent,/SYN-A/);
  await new Promise(resolve=>setImmediate(resolve));
  assert.doesNotMatch(ui.root.textContent,/OTHER/,'新账户也必须显式载入');
  simulate(ui);holdSnapshot=true;el('private-refresh').fire('click');
  await new Promise(resolve=>setImmediate(resolve));
  el('private-account').value='third';el('private-account').fire('change');
  releaseSnapshot();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(ui.find('stress-load'),null,'账户已变更时，迟到的旧账户快照不能重新启用实验室');
  holdSnapshot=false;el('private-refresh').fire('click');await new Promise(resolve=>setImmediate(resolve));
  simulate(ui);
  const lastPrice=ui.find('stress-price-0');
  el('private-dialog').open=false;observerCallback();
  assert.equal(ui.root.children.length,0);assert.equal(lastPrice.value,'');
  assert.equal(el('private-workspace').hidden,true);
  el('private-dialog').fire('close');assert.equal(ui.root.children.length,0);
});
