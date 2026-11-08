'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const ui=require('../dist/private-research.js');

test('服务端证据URL展示为安全可点击链接，恶意协议不生成链接',()=>{
  const event={title:'<script>',version:1,source:'Synthetic',url:'https://example.com/synthetic-release?x=1&y=2'};
  const html=ui.evidenceHTML([event]);
  assert.match(html,/href="https:\/\/example.com\/synthetic-release\?x=1&amp;y=2"/);
  assert.match(html,/rel="noopener noreferrer"/);
  assert.doesNotMatch(html,/<script>/);
  for (const url of ['javascript:alert(1)','https://example.com\\@evil.invalid','https://user:secret@example.com']) {
    assert.doesNotMatch(ui.evidenceHTML([{...event,url}]),/<a\b/);
  }
});

test('事件展示保留独立时间、未知值和人工未核实标记',()=>{
  const html=ui.evidenceHTML([{id:'synthetic',version:1,title:'<script>',source:'Synthetic',url:'https://example.invalid',published_at:null,available_at:null,first_seen_at:'2026-11-08T00:00:00Z',captured_at:'2026-11-08T00:00:00Z',actual:null,expected:'1',previous:null,revised:null}]);
  assert.match(html,/人工录入.*未自动核实/);
  assert.match(html,/实际首次记录/);
  assert.match(html,/未知/);
  assert.doesNotMatch(html,/<script>/);
});

test('证据支持与反面分别收集，空白数值维持null',()=>{
  const event=ui.eventValues({kind:'macro',scope:'global',symbol:'',title:'Synthetic',source:'Synthetic',url:'https://example.invalid',published_at:'',available_at:'',actual:'',expected:'3.1',previous:'',revised:'',period:'',unit:'',notes:''});
  assert.equal(event.actual,null);assert.equal(event.expected,'3.1');assert.equal(event.published_at,null);
});

test('真实研究事件绑定分别发送支持与反面ID，并显示冻结导出内容',async()=>{
  const vm=require('node:vm'),elements=new Map(),calls=[];
  /** 合成DOM仅隔离浏览器边界，运行真实研究表单回调。 */
  function el(id){if(!elements.has(id))elements.set(id,{value:'',textContent:'',innerHTML:'',selectedOptions:[],listeners:{},addEventListener(type,fn){this.listeners[type]=fn;},reset(){}});return elements.get(id);}
  const fields={thesis:'合成判断',trigger:'合成触发',invalidation:'合成失效',group:'core',as_of:''};
  class SyntheticFormData{/** 提供合成浏览器表单值。 */[Symbol.iterator](){return Object.entries(fields)[Symbol.iterator]();}}
  const context=vm.createContext({window:{},FormData:SyntheticFormData,Date,URL,Blob,document:{}});
  vm.runInContext(fs.readFileSync('dist/private-research.js','utf8'),context);
  const client={async call(route,data){calls.push({route,data});if(route==='research/save')return{id:'saved-synthetic'};if(route==='evidence/list')return{events:[]};if(route==='research/list')return{records:[]};if(route==='research/export')return{content:'合成冻结Markdown'};throw new Error('未知合成接口');}};
  let pending;
  context.window.FlowdeskPrivateResearch.mount({client,el,context:()=>({account:'account-synthetic',snapshot:{revision:7}}),run:fn=>{pending=fn();},status:()=>{}});
  el('private-support').selectedOptions=[{value:'support-synthetic'}];el('private-against').selectedOptions=[{value:'against-synthetic'}];
  el('private-study-form').listeners.submit({preventDefault(){}});await pending;
  const payload=calls.find(c=>c.route==='research/save').data.record;
  assert.deepEqual(Array.from(payload.support),['support-synthetic']);assert.deepEqual(Array.from(payload.against),['against-synthetic']);
  assert.equal(payload.revision,7);assert.equal(el('private-report').textContent,'合成冻结Markdown');
});

test('研究模块无持久化和自动抓取，下载使用内存Blob',()=>{
  const source=fs.readFileSync('dist/private-research.js','utf8');
  assert.doesNotMatch(source,/localStorage|sessionStorage|console\.|fetch\(/);
  assert.match(source,/createObjectURL\(new Blob/);
  assert.match(source,/textContent=report.content/);
});
