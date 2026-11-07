'use strict';
// 全部报告为合成fixtures；原生VM执行真实渲染函数，不启动浏览器或服务。
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {test}=require('node:test');

/** 在离线合成DOM中载入真实前端函数，跳过会触发自动联网的挂载入口。 */
function harness(){
  const elements=new Map();
  const context=vm.createContext({URL,Number,escapeHtml:value=>String(value??''),
    number:value=>Number.isFinite(value)?String(value):'—',tone:()=>'',
    $:id=>{if(!elements.has(id))elements.set(id,{innerHTML:'',value:'all',addEventListener(){}});return elements.get(id);}});
  vm.runInContext(fs.readFileSync('dist/intelligence.js','utf8').replace(/\nmountIntelligence\(\);\s*$/,''),context);
  return {context,elements};
}

test('合成过期期权不可作为正常墙和异动渲染',()=>{
  const {context,elements}=harness();
  vm.runInContext(`renderOptionsIntelligence({status:'stale',reason:'合成快照过期',providerTimestamp:'2026-11-04',expiries:[],horizonDays:30});`,context);
  assert.equal(elements.get('int-expiry').disabled,true);
  assert.match(elements.get('int-options-result').innerHTML,/过期|滞后/);
});

test('合成缺量与真实零次在UI上可区分',()=>{
  const {context,elements}=harness();
  const technical={close:100,change:0,source:'synthetic',asOf:'2026-11-06',status:'available',
    rsi14:50,rsiState:'中性',bollinger:{percentB:50},atrPct:1,trend:'transition',rebound:'合成',
    relativeVolume20:null,distributionDays20:null,distributionCoverage:{available:0,expected:20,reason:'成交量缺失'},
    flags:[],ma:{20:100},drawdown:{currentPct:0,peakDate:'2026-11-06',start:'2026-09-01',end:'2026-11-06',windows:[],path:[],episodes:[]}};
  context.syntheticReport={symbol:'TEST',technical,smallOrders:{status:'unavailable'},options:{status:'unavailable'}};
  vm.runInContext('renderStockIntelligence(syntheticReport)',context);
  assert.match(elements.get('int-stock-result').innerHTML,/未知/);
  assert.match(elements.get('int-stock-result').innerHTML,/覆盖 0 \/ 20/);
  technical.distributionDays20=0;technical.distributionCoverage={available:20,expected:20,reason:''};
  vm.runInContext('renderStockIntelligence(syntheticReport)',context);
  assert.match(elements.get('int-stock-result').innerHTML,/0 次/);
});

test('合成局部OI明确停止排名并标记候选覆盖',()=>{
  const {context,elements}=harness();
  context.syntheticOptions={status:'available',source:'synthetic',url:'https://example.invalid',spot:100,
    providerTimestamp:'2026-11-06T16:15:00-05:00',expiries:[],limits:[],horizonDays:30,
    scopes:{all:{contracts:3,missingOI:1,missingVolume:0,anomalyCount:0,anomalies:[],strikes:[],upperCallWalls:[],lowerPutWalls:[],
      oiCoverage:{status:'partial',available:2,expected:3,reason:'OI不完整，停止排名'},
      anomalyCoverage:{status:'partial',available:2,expected:3,reason:'局部样本'}}}};
  vm.runInContext('intelligenceState.stock={options:syntheticOptions};renderOptionsIntelligence(syntheticOptions)',context);
  assert.match(elements.get('int-options-result').innerHTML,/停止排名/);
  assert.match(elements.get('int-options-result').innerHTML,/局部样本/);
});
