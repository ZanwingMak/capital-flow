'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

/** 用真实入口HTML构造内存DOM边界，事件由Node EventTarget实际派发。 */
function fixture() {
  const document = {activeElement:null};
  class Element extends EventTarget {
    /** 保存结构与属性，不实现网络或浏览器存储。 */
    constructor(tag, attributes = {}) {super();this.tagName=tag;this.attributes={...attributes};this.children=[];this.parentElement=null;this.value='';this.checked=false;this.inert=false;this._text='';}
    /** 读取实际HTML中的属性。 */
    getAttribute(name) {return this.attributes[name] ?? null;}
    /** 保存模块写入的ARIA及焦点属性。 */
    setAttribute(name, value) {this.attributes[name]=String(value);}
    /** 判断布尔属性是否存在。 */
    hasAttribute(name) {return name in this.attributes;}
    /** 通过ID进行定位。 */
    get id() {return this.getAttribute('id');}
    /** hidden与HTML布尔属性保持一致。 */
    get hidden() {return this.hasAttribute('hidden');}
    /** 模拟浏览器隐藏整棵子树。 */
    set hidden(value) {if(value)this.setAttribute('hidden','');else delete this.attributes.hidden;}
    /** 读取原生对话框开关。 */
    get open() {return this.hasAttribute('open');}
    /** 模拟后台移除open，不自动派发close事件。 */
    set open(value) {if(value)this.setAttribute('open','');else delete this.attributes.open;}
    /** 读取顺序焦点索引。 */
    get tabIndex() {return Number(this.getAttribute('tabindex') ?? 0);}
    /** 记录漫游焦点索引。 */
    set tabIndex(value) {this.setAttribute('tabindex',value);}
    /** 读取纯文本，不解析动态业务HTML。 */
    get textContent() {return this._text+this.children.map(child=>child.textContent).join('');}
    /** 支持原工作台清空敏感内容的路径。 */
    set textContent(value) {this._text=String(value);this.children=[];}
    /** 只模拟既有业务渲染边界，导航不应调用此接口。 */
    set innerHTML(value) {this.textContent=value;}
    /** 按实际表单name暴露原工作台使用的字段。 */
    get elements() {return Object.fromEntries(this.querySelectorAll('input,select,textarea').filter(node=>node.getAttribute('name')).map(node=>[node.getAttribute('name'),node]));}
    /** 支持本轮导航用到的简单ID、标签和属性选择器。 */
    matches(selector) {return selector.startsWith('#') ? this.id===selector.slice(1) : selector.startsWith('.') ? (this.getAttribute('class') || '').split(' ').includes(selector.slice(1)) : selector.startsWith('[') ? this.hasAttribute(selector.slice(1,-1)) : this.tagName===selector;}
    /** 遍历实际生产HTML中的后代。 */
    querySelectorAll(selector) {return this.children.flatMap(child=>[...(selector.split(',').some(part=>child.matches(part))?[child]:[]),...child.querySelectorAll(selector)]);}
    /** 返回单个生产节点。 */
    querySelector(selector) {return this.querySelectorAll(selector)[0] || null;}
    /** 查找标签所属表单与任务面板。 */
    closest(selector) {return this.matches(selector)?this:this.parentElement?.closest(selector) || null;}
    /** 记录键盘导航实际移动的焦点。 */
    focus() {document.activeElement=this;}
    /** 模拟原生对话框显示。 */
    showModal() {this.open=true;}
    /** 恢复表单初始值，供原有关闭清理调用。 */
    reset() {for(const node of this.querySelectorAll('input,select,textarea')){node.value=node.defaultValue;node.checked=node.defaultChecked;}}
    /** 派发实际绑定的监听器，并返回可检查preventDefault的事件。 */
    fire(type, key) {const event=new Event(type,{cancelable:true});if(key)Object.defineProperty(event,'key',{value:key});this.dispatchEvent(event);return event;}
  }
  const root=new Element('document'), stack=[root], html=fs.readFileSync('dist/index.html','utf8');
  const voidTags=new Set(['meta','link','input','br','hr','img','source','wbr']);
  for(const match of html.matchAll(/<(\/?)([a-z][\w-]*)\b([^>]*?)>/gi)) {
    const [,closing,tag,raw]=match;
    if(closing){while(stack.length>1 && stack.pop().tagName!==tag){}continue;}
    const attributes={};
    for(const attribute of raw.matchAll(/([\w:-]+)(?:="([^"]*)")?/g))attributes[attribute[1]]=attribute[2] ?? '';
    const node=new Element(tag,attributes),parent=stack.at(-1);node.parentElement=parent;parent.children.push(node);
    if(!voidTags.has(tag))stack.push(node);
  }
  for(const node of root.querySelectorAll('input,select,textarea')) {
    node.value=node.getAttribute('value') ?? (node.tagName==='select'?node.querySelector('option')?.getAttribute('value') ?? '':'');
    node.defaultValue=node.value;node.checked=node.hasAttribute('checked');node.defaultChecked=node.checked;
  }
  document.getElementById=id=>root.querySelector('#'+id);
  return {document,root,html,el:document.getElementById,tabs:root.querySelectorAll('[data-workspace-tab]'),panels:root.querySelectorAll('[data-workspace-panel]')};
}

/** 在禁止额外I/O的上下文装载实际导航模块。 */
function mounted(attach = true) {
  const ui=fixture(),window={};
  /** 导航访问任何网络、存储或地址能力都会立即失败。 */
  function forbidden() {throw new Error('导航禁止I/O');}
  for(const key of ['fetch','XMLHttpRequest','WebSocket','localStorage','sessionStorage','indexedDB','location'])Object.defineProperty(window,key,{get:forbidden,configurable:true});
  const context=vm.createContext({window,document:ui.document});
  vm.runInContext(fs.readFileSync('dist/workspace-nav.js','utf8'),context);
  const navigation=attach?window.FlowdeskWorkspaceNav.mount({dialog:ui.el('private-dialog')}):null;
  return {...ui,navigation,context,window};
}

test('实际HTML包含六个关联页签，独立表单与账户选择仍在忙碌保护内',()=>{
  const ui=mounted();
  assert.equal(ui.tabs.length,6);assert.equal(ui.panels.length,6);
  assert.ok(ui.html.indexOf('workspace-nav.js')<ui.html.indexOf('src="private.js'));
  assert.equal(ui.el('private-workspace').hidden,true);
  for(const [index,tab] of ui.tabs.entries()) {
    const panel=ui.el(tab.getAttribute('aria-controls'));
    assert.equal(tab.getAttribute('role'),'tab');assert.equal(tab.getAttribute('type'),'button');
    assert.equal(panel.getAttribute('role'),'tabpanel');assert.equal(panel.getAttribute('aria-labelledby'),tab.id);
    assert.equal(panel.hidden,index!==0);assert.equal(panel.inert,index!==0);
    assert.equal(tab.getAttribute('aria-selected'),String(index===0));assert.equal(tab.tabIndex,index===0?0:-1);
    assert.equal(panel.closest('fieldset'),ui.el('private-controls'));
  }
  for(const id of ['private-create','private-event','private-evidence-form','private-study-form']) {
    const form=ui.el(id);assert.equal(form.tagName,'form');assert.equal(form.parentElement.closest('form'),null);
    assert.ok(form.closest('[data-workspace-panel]'));
    assert.ok(form.querySelectorAll('input,textarea').some(input=>input.hasAttribute('required')));
  }
  assert.equal(ui.el('private-account').closest('fieldset'),ui.el('private-controls'));
  assert.equal(ui.el('private-account').closest('[data-workspace-panel]'),null);
});

test('实际点击只显示目标面板，表单值、预览状态与账户选择保持原样',()=>{
  const ui=mounted(),fields=ui.el('private-dialog').querySelectorAll('input,select,textarea');
  fields.forEach((field,index)=>{field.value='synthetic-'+index;field.checked=index%2===0;});
  const before=fields.map(field=>[field.value,field.checked,field.disabled]);
  ui.el('private-confirm').disabled=true;
  for(const [index,tab] of ui.tabs.entries()) {
    const scroller=ui.el('private-dialog').querySelector('.private-panels');scroller.scrollTop=800;
    tab.fire('click');assert.equal(ui.panels.filter(panel=>!panel.hidden).length,1);
    assert.equal(scroller.scrollTop,0,'新任务从顶部开始，不能沿用上一任务的滚动位置');
    assert.equal(ui.panels[index].hidden,false);assert.equal(ui.panels[index].inert,false);
    assert.deepEqual(fields.map(field=>[field.value,field.checked,field.disabled]),before);
    assert.equal(ui.el('private-confirm').disabled,true);
  }
});

test('真实键盘绑定支持左右循环、Home、End，并只保留一个Tab入口',()=>{
  const ui=mounted();
  for(const [from,key,to] of [[0,'ArrowLeft',5],[5,'ArrowRight',0],[0,'End',5],[5,'Home',0],[0,'ArrowRight',1],[1,'ArrowLeft',0]]) {
    const event=ui.tabs[from].fire('keydown',key);
    assert.equal(event.defaultPrevented,true);assert.equal(ui.document.activeElement,ui.tabs[to]);
    assert.equal(ui.panels[to].hidden,false);assert.equal(ui.tabs.filter(tab=>tab.tabIndex===0).length,1);
  }
  assert.equal(ui.tabs[0].fire('keydown','Tab').defaultPrevented,false);
  assert.equal(ui.tabs[0].fire('keydown','ArrowDown').defaultPrevented,false);
});

test('窄屏键盘选择使活动页签可见，重置时回到左端且不滚动外层页面',()=>{
  const ui=mounted(),strip=ui.el('private-dialog').querySelector('.private-tabs');
  strip.scrollLeft=0;strip.getBoundingClientRect=()=>({left:100,right:400});
  ui.tabs.forEach((tab,i)=>{tab.getBoundingClientRect=()=>({left:100+i*90-strip.scrollLeft,right:190+i*90-strip.scrollLeft});});
  ui.tabs[0].fire('keydown','End');
  assert.equal(strip.scrollLeft,240);
  assert.equal(ui.tabs[5].getBoundingClientRect().right,400);
  ui.navigation.reset();assert.equal(strip.scrollLeft,0);
});

test('会话呈现与重置只修改导航，不清除任务输入或抢占关闭后的焦点',()=>{
  const ui=mounted();ui.el('private-name').value='synthetic';
  ui.navigation.setSession(true);
  assert.equal(ui.el('private-intro').hidden,true);assert.equal(ui.el('private-session').hidden,true);
  ui.tabs[3].fire('keydown','ArrowRight');const focused=ui.document.activeElement;
  ui.navigation.reset();
  assert.equal(ui.panels[0].hidden,false);assert.equal(ui.el('private-intro').hidden,false);
  assert.equal(ui.el('private-session').hidden,false);assert.equal(ui.el('private-name').value,'synthetic');
  assert.equal(ui.document.activeElement,focused);
});

test('缺少可选节点的旧DOM可以安全跳过挂载',()=>{
  const ui=mounted();
  assert.equal(ui.window.FlowdeskWorkspaceNav.mount({dialog:{querySelectorAll:()=>[]}}),null);
});

test('生产入口的原生关闭与后台open移除都重置导航并沿用敏感内容清理',async()=>{
  const ui=mounted(false),observers=[],requests=[];
  class Observer {
    /** 收集实际生产watchDialogClosure的回调。 */
    constructor(callback) {this.callback=callback;observers.push(this);}
    /** 只允许观察原对话框的open属性。 */
    observe(target,options) {assert.equal(target,ui.el('private-dialog'));assert.deepEqual(Array.from(options.attributeFilter),['open']);}
  }
  ui.context.AbortController=AbortController;ui.context.MutationObserver=Observer;
  Object.defineProperty(ui.window,'location',{configurable:true,value:{protocol:'http:',hostname:'localhost'}});
  Object.defineProperty(ui.window,'fetch',{configurable:true,value:async(url)=>{
    requests.push(url);return {ok:true,json:async()=>url.endsWith('/session')?{session_token:'synthetic'}:
      url.endsWith('/accounts')?{accounts:[]}:url.endsWith('/evidence/list')?{events:[]}:{records:[]}};
  }});
  vm.runInContext(fs.readFileSync('dist/private-research.js','utf8'),ui.context);
  vm.runInContext(fs.readFileSync('dist/private.js','utf8'),ui.context);
  assert.equal(requests.length,0,'挂载不能读取私有库');
  for(const background of [false,true]) {
    ui.el('open-private').fire('click');assert.equal(requests.length,background?3:0,'打开弹窗不能开启会话');
    ui.el('private-session').fire('submit');await new Promise(resolve=>setImmediate(resolve));
    assert.equal(ui.el('private-workspace').hidden,false);assert.equal(ui.el('private-session').hidden,true);
    const count=requests.length;
    ui.tabs[4].fire('click');ui.tabs[4].fire('keydown','ArrowRight');
    assert.equal(requests.length,count,'切页不得请求任何私有API');
    ui.el('private-name').value='sensitive-synthetic';ui.el('private-flow-token').value='synthetic-token';
    ui.el('private-dialog').open=false;
    if(background)observers.forEach(observer=>observer.callback());else ui.el('private-dialog').fire('close');
    assert.equal(ui.el('private-workspace').hidden,true);assert.equal(ui.el('private-name').value,'');
    assert.equal(ui.el('private-flow-token').value,'');assert.equal(ui.panels[0].hidden,false);
    assert.equal(ui.el('private-intro').hidden,false);assert.equal(ui.el('private-session').hidden,false);
  }
});

test('首页任务锚点均有唯一目标，既有行情与研究动作保留ID',()=>{
  const ui=fixture(),ids=ui.root.querySelectorAll('[id]').map(node=>node.id);
  assert.equal(new Set(ids).size,ids.length);
  const links=ui.root.querySelectorAll('a').filter(node=>(node.getAttribute('href') || '').startsWith('#'));
  assert.equal(links.length,3);for(const link of links)assert.ok(ui.el(link.getAttribute('href').slice(1)));
  for(const id of ['market-select','watch-form','history-form','rows','main-window-open','path-open','chips-open','validation','open-daily-research','open-tail-research','open-alpaca','open-private'])assert.ok(ui.el(id),id);
});

test('线上页面的实际打开与提交绑定不能发起本机请求或显示工作区',async()=>{
  const ui=mounted(false);let requests=0;
  ui.context.AbortController=AbortController;
  Object.defineProperty(ui.window,'location',{value:{protocol:'https:',hostname:'example.github.io'}});
  Object.defineProperty(ui.window,'fetch',{value:async()=>{requests++;throw new Error('线上页面禁止私有请求');}});
  vm.runInContext(fs.readFileSync('dist/private-research.js','utf8'),ui.context);
  vm.runInContext(fs.readFileSync('dist/private.js','utf8'),ui.context);
  ui.el('open-private').fire('click');
  assert.equal(ui.el('private-session-button').hidden,true);
  assert.match(ui.el('private-status').textContent,/GitHub Pages不能读取/);
  ui.el('private-session').fire('submit');await new Promise(resolve=>setImmediate(resolve));
  assert.equal(requests,0);assert.equal(ui.el('private-workspace').hidden,true);
  assert.equal(ui.el('private-intro').hidden,false);assert.equal(ui.panels[0].hidden,false);
});
