'use strict';
const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
function setup(){
  const dom=new JSDOM('<button id="open-methods">研究</button>',{url:'http://127.0.0.1:8788/',runScripts:'outside-only'});
  dom.window.eval(fs.readFileSync('dist/methods.js','utf8'));
  return {dom,api:dom.window.FlowdeskMethods};
}
test('methods endpoint removes stale query and rejects unsafe connections',()=>{
  const {dom,api}=setup();
  const url=api.createURL({endpoint:'http://localhost:8788/api/snapshot?token=old'}, {symbol:'TEST',asOf:'2026-11-13'});
  assert.equal(url.pathname,'/api/methods');assert.equal(url.searchParams.has('token'),false);
  assert.equal(url.searchParams.get('timeframe'),'1d');
  for(const endpoint of ['http://remote.example/api/snapshot','https://user:pass@example.com/api/snapshot','javascript:alert(1)'])assert.throws(()=>api.createURL({endpoint},{}));
  dom.window.close();
});
test('response rejects future bars and falsely backdated confirmations',()=>{
  const {dom,api}=setup();
  const value={source:'flowdesk-methods',schemaVersion:1,symbol:'TEST',asOf:'2026-11-13',market:'US',timeframe:'1d',dates:['2026-11-13'],price:[100],effectiveAsOf:'2026-11-13',methods:{}};
  for(const id of ['ICT','PA','WYCKOFF','MEAN_REVERSION','ELLIOTT','ORDERFLOW'])value.methods[id]={id,events:[]};
  api.validateReport(value,{symbol:'TEST',asOf:'2026-11-13'});
  value.methods.ICT.events=[{index:0,confirmIndex:1,date:'2026-11-13'}];
  assert.throws(()=>api.validateReport(value,{symbol:'TEST',asOf:'2026-11-13'}));
  value.methods.ICT.events=[];value.dates=['2026-11-14'];
  assert.throws(()=>api.validateReport(value,{symbol:'TEST',asOf:'2026-11-13'}));
  dom.window.close();
});
