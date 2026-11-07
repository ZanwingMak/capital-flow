'use strict';
// 所有DOM与报告均为合成fixtures；只执行真实前端函数，不调用行情服务。
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {test}=require('node:test');

/** 在合成DOM中载入研究函数，跳过事件绑定和自动初始化。 */
function harness(){
  const values={'research-kind':'tail20','research-mode':'strict-as-of','research-direction':'out',
    'research-date':'2026-11-02','research-lookback':'120','research-span':'1','research-percentile':'90',
    'research-minimum':'0','research-days':'20'};
  const elements=new Map(Object.entries(values).map(([id,value])=>[id,{value,disabled:false}]));
  const context=vm.createContext({URL,Number,state:{market:'US',endpoint:'https://example.invalid/api/snapshot'},
    marketConfig:()=>({unit:'USD_10000',money:'万美元'}),escapeHtml:value=>String(value??''),
    number:value=>Number.isFinite(value)?String(value):'—',percent:value=>String(value),tone:()=>'',
    $:id=>{if(!elements.has(id))elements.set(id,{value:'',innerHTML:''});return elements.get(id);}});
  const source=fs.readFileSync('dist/research.js','utf8');
  vm.runInContext(source.slice(0,source.indexOf("$('open-tail-research').addEventListener")),context);
  return {context,elements};
}

/** 返回不含个人信息的合成空事件报告。 */
function syntheticReport(){return {source:'futu-opend',market:'US',unit:'USD_10000',symbol:'TEST',name:'合成标的',
  adjustment:'QFQ',asOf:'2026-11-02',start:'2026-10-01',events:[],summary:[],kind:'tail20',
  coverage:{available:0,requested:20},requestedDays:20};}

test('尾盘启用实际执行的分位数参数并解释同向基线',()=>{
  const {context,elements}=harness();
  vm.runInContext('updateResearchKind()',context);
  assert.equal(elements.get('research-percentile').disabled,false);
  assert.match(elements.get('research-explanation').textContent,/同向/);
  assert.match(elements.get('research-explanation').textContent,/分位/);
});

test('UI提供两种明确口径并将严格模式发送至API',()=>{
  const {context}=harness();
  assert.equal(vm.runInContext("researchEndpoint('TEST').searchParams.get('mode')",context),'strict-as-of');
  const html=fs.readFileSync('dist/index.html','utf8');
  assert.match(html,/id="research-mode"/);
  assert.match(html,/value="retrospective"/);
  assert.match(html,/value="strict-as-of"/);
});

test('旧尾盘服务不能冒充已执行分位阈值，旧日级响应保持兼容',()=>{
  const {context}=harness();context.synthetic=syntheticReport();
  assert.throws(()=>vm.runInContext("validateResearch(synthetic,'TEST')",context),/尾盘|新版/);
  context.synthetic.kind='daily';
  assert.doesNotThrow(()=>vm.runInContext("validateResearch(synthetic,'TEST')",context));
});

test('严格请求拒绝旧服务默认复盘和任何越界路径',()=>{
  const {context}=harness();
  context.synthetic=syntheticReport();
  assert.throws(()=>vm.runInContext("validateResearch(synthetic,'TEST','strict-as-of','2026-11-02')",context),/严格|口径|模式/);
  context.synthetic.mode='strict-as-of';
  context.synthetic.outcomeThrough='2026-11-02';
  context.synthetic.events=[{date:'2026-11-02',path:[{date:'2026-11-03'}]}];
  assert.throws(()=>vm.runInContext("validateResearch(synthetic,'TEST','strict-as-of','2026-11-02')",context),/截至|越界|日期/);
  context.synthetic.events=[{date:'2026-11-02',path:[{date:'2026-11-02'}]}];
  assert.doesNotThrow(()=>vm.runInContext("validateResearch(synthetic,'TEST','strict-as-of','2026-11-02')",context));
  context.synthetic.minuteDates=['2026-11-03'];
  assert.throws(()=>vm.runInContext("validateResearch(synthetic,'TEST','strict-as-of','2026-11-02')",context),/截至|越界|日期/);
});

test('旧报告按默认事后复盘标注，严格结果显示价格时间边界',()=>{
  const {context,elements}=harness();
  context.synthetic=syntheticReport();
  vm.runInContext('researchReport=synthetic;renderResearch()',context);
  assert.match(elements.get('research-content').innerHTML,/事后复盘/);
  context.synthetic.mode='strict-as-of';context.synthetic.outcomeThrough='2026-11-02';
  vm.runInContext('renderResearch()',context);
  assert.match(elements.get('research-content').innerHTML,/严格/);
  assert.match(elements.get('research-content').innerHTML,/2026-11-02/);
});
