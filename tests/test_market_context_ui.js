'use strict';
// Synthetic observations exercise the real UI without external requests or private data.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {test}=require('node:test');
const {JSDOM}=require('jsdom');
const code=fs.readFileSync('dist/market-context.js','utf8');
const fixedDate='2026-11-06';
function report() {
  return {source:'flowdesk-market-context',schemaVersion:1,asOf:fixedDate,collectedAt:'2026-11-07T01:00:00Z',
    sources:[{id:'FRED',name:'FRED',url:'https://fred.stlouisfed.org/',status:'available',reason:'公开观测'}],
    macro:[{id:'DGS10',name:'10年期国债',value:4.25,observationDate:'2026-11-05',units:'Percent',frequency:'Daily',status:'available',sourceUrl:'https://fred.stlouisfed.org/series/DGS10',reason:''},
      {id:'MISSING',name:'缺失指标',value:null,observationDate:null,units:'Percent',frequency:'Monthly',status:'unavailable',sourceUrl:'https://fred.stlouisfed.org/',reason:'未返回观测'}],
    positioning:{status:'available',observationDate:fixedDate,dix:.4512,gex:123456789,spx:6000,sourceUrl:'https://squeezemetrics.com/monitor/dix#gex',reason:''},warnings:['合成测试；市场结构不代表交易信号']};
}
function deferred() { let resolve,reject; const promise=new Promise((yes,no)=>{resolve=yes;reject=no;}); return {promise,resolve,reject}; }
function setup(request=async()=>report(),getConnection=()=>({endpoint:'http://127.0.0.1:8788/api/snapshot',market:'US',token:'synthetic-token',date:fixedDate})) {
  const dom=new JSDOM('<button id="open-market-context"><span>市场背景</span></button>',{url:'http://127.0.0.1:8788/',runScripts:'outside-only'});
  dom.window.FlowdeskIndicators={request};
  dom.window.eval(code);
  const api=dom.window.FlowdeskMarketContext; api.mount({getConnection});
  return {dom,api,document:dom.window.document,open:()=>dom.window.document.querySelector('#open-market-context span').click()};
}
async function settle() { await new Promise(resolve=>setImmediate(resolve)); }

test('production lexical state and shared request poll the authenticated market-context job',async()=>{
  const dom=new JSDOM('<button id="open-market-context">市场背景</button>',{url:'http://127.0.0.1:8788/',runScripts:'outside-only'});
  dom.window.AbortSignal=AbortSignal;
  dom.window.AbortController=AbortController;
  const calls=[];
  dom.window.fetch=async(url,config)=>{
    calls.push({url:String(url),config});
    return calls.length===1 ? {status:202,ok:true,json:async()=>({jobId:'a'.repeat(24),progress:{message:'synthetic-job'}})} : {status:200,ok:true,json:async()=>report()};
  };
  require('node:vm').runInContext("const state={endpoint:'http://127.0.0.1:8788/api/snapshot',token:'synthetic-token',market:'US',date:'2026-11-06'};",dom.getInternalVMContext());
  dom.window.eval(fs.readFileSync('dist/indicators.js','utf8'));
  dom.window.eval(code);
  dom.window.document.querySelector('button').click();
  for(let i=0;i<40 && calls.length<2;i++) await new Promise(resolve=>setTimeout(resolve,50));
  await settle();
  assert.equal(calls.length,2);
  assert.equal(new URL(calls[0].url).pathname,'/api/market-context');
  assert.equal(new URL(calls[1].url).pathname,'/api/jobs');
  assert.equal(new URL(calls[1].url).searchParams.get('id'),'a'.repeat(24));
  for(const call of calls) { assert.equal(call.config.headers.Authorization,'Bearer synthetic-token'); assert.equal(call.config.cache,'no-store'); }
  assert.match(dom.window.document.querySelector('#market-context-result').textContent,/45\.12%/);
  dom.window.close();
});

test('changing selected date aborts pending output and clears stale source state',async()=>{
  const late=deferred();let signal;
  const {dom,document,open}=setup((url,progress,current)=>{signal=current;return late.promise;});
  open();const input=document.querySelector('input');input.value='2026-11-05';input.dispatchEvent(new dom.window.Event('change'));
  assert.equal(signal.aborted,true);late.resolve(report());await settle();
  assert.equal(document.querySelector('#market-context-result').textContent,'');
  assert.match(document.querySelector('#market-context-status').textContent,/截至日已变化/);
});

test('delegated entry mounts one labeled dialog, uses the shared pipeline and connection identity',async()=>{
  const calls=[];
  const {api,document,open}=setup(async(...args)=>{calls.push(args);return report();});
  open(); await settle(); api.mount(); api.open();
  assert.equal(document.querySelectorAll('dialog').length,1);
  const dialog=document.querySelector('dialog');
  assert.equal(dialog.getAttribute('aria-labelledby'),'market-context-title');
  assert.equal(document.activeElement.id,'market-context-close');
  assert.equal(calls.length,1);
  const [url,progress,signal,token]=calls[0];
  assert.equal(url.pathname,'/api/market-context');
  assert.equal(url.search,'?asOf='+fixedDate);
  assert.equal(url.href.includes('synthetic-token'),false);
  assert.equal(token,'synthetic-token'); assert.equal(typeof progress,'function');assert.equal(signal.aborted,false);
  assert.equal(document.querySelector('input').labels.length,1);
  assert.equal(document.querySelector('#market-context-result').hasAttribute('aria-busy'),false);
});

test('real macro and aggregate metrics display units, observation dates, collection time and missing values',async()=>{
  const {document,open}=setup();open();await settle();
  const content=document.querySelector('#market-context-result').textContent;
  assert.match(content,/45\.12%/);assert.match(content,/123,456,789 USD/);assert.match(content,/6,000/);
  assert.match(content,/4\.25/);assert.match(content,/2026-11-05/);assert.match(content,/早于截至日/);
  assert.match(content,/2026-11-07 01:00:00 UTC/);
  assert.match(content,/FRED 日期是观测所属日期，不是发布时间/);assert.match(content,/最新修订值/);assert.match(content,/PIT/);
  const missing=[...document.querySelectorAll('tbody tr')].find(row=>row.textContent.includes('缺失指标'));
  assert.match(missing.textContent,/不可用/);assert.doesNotMatch(missing.textContent,/0%|0\.00/);
  assert.equal(document.querySelectorAll('.mc-source').length,4);
  assert.match(document.querySelector('#market-context-sources').textContent,/需要许可与密钥/);
  assert.match(document.querySelector('#market-context-sources').textContent,/Non-display/);
});

test('report assembly time does not replace cached observation retrieval time',async()=>{
  const data=report();data.macro[0].retrievedAt='2026-11-07T00:55:00Z';data.macro[0].reason='cached observation';
  const {document,open}=setup(async()=>data);open();await settle();
  const result=document.querySelector('#market-context-result');
  assert.match(result.querySelector('.mc-freshness').textContent,/报告生成时间.*01:00:00/);
  assert.match(result.querySelector('tbody tr details').textContent,/实际取数.*00:55:00 UTC/);
  assert.match(result.textContent,/可缓存10分钟/);
});

test('null positioning stays unavailable while actual zero macro and GEX remain zero',async()=>{
  const data=report();data.positioning={...data.positioning,dix:null,gex:0,spx:null,status:'partial',reason:'DIX 暂缺'};data.macro[0].value=0;
  const {document,open}=setup(async()=>data);open();await settle();
  const values=[...document.querySelectorAll('.mc-metrics dd')].map(node=>node.textContent);
  assert.deepEqual(values,['不可用','0 USD','不可用']);
  assert.match(document.querySelector('tbody tr .mc-value').textContent,/^0/);
  assert.match(document.querySelector('#market-context-result').textContent,/DIX 暂缺/);
});

test('untrusted labels, reasons, warnings, status and URL attributes remain safe text',async()=>{
  const data=report(), attack='<img src=x onerror="alert(1)">';
  data.macro[0].name=attack;data.macro[0].sourceUrl='javascript:alert(1)';data.macro[0].reason=attack;
  data.macro[0].units=attack;data.positioning.sourceUrl='https://fred.stlouisfed.org.evil.test/';
  data.positioning.reason=attack;data.positioning.status=attack;data.warnings=[attack];data.sources[0].reason=attack;
  const {document,open}=setup(async()=>data);open();await settle();
  assert.equal(document.querySelectorAll('img,script,[onerror]').length,0);
  assert.match(document.querySelector('#market-context-result').textContent,/<img src=x/);
  for(const anchor of document.querySelectorAll('dialog a')) {
    assert.equal(new URL(anchor.href).protocol,'https:');
    assert.equal(anchor.target,'_blank');assert.match(anchor.rel,/noopener/);assert.match(anchor.rel,/noreferrer/);
    assert.doesNotMatch(anchor.href,/javascript|evil\.test/);
  }
  assert.ok(document.querySelector('a[href="https://stream.financialjuice.com/docs"]'));
  assert.ok(document.querySelector('a[href="https://developer.webull.com/apis/docs/market-data-api/overview/"]'));
});

test('URL security clears stale parameters, rejects credentials and public insecure HTTP',()=>{
  const {api}=setup();
  const target=api.createURL({endpoint:'https://example.test/custom/snapshot?token=old#hash'},fixedDate);
  assert.equal(target.pathname,'/custom/market-context');assert.equal(target.search,'?asOf='+fixedDate);assert.equal(target.hash,'');
  for(const endpoint of ['http://example.test/api/snapshot','https://user:secret@example.test/','javascript:alert(1)']) assert.throws(()=>api.createURL({endpoint},fixedDate));
});

test('wrong source, version, date, infinite values, future observations and invalid DIX are rejected',()=>{
  const {api}=setup();
  const variants=[{source:'other'},{schemaVersion:2},{asOf:'2026-11-05'},{collectedAt:'invalid'},
    {macro:[{...report().macro[0],value:Infinity}]},{macro:[{...report().macro[0],observationDate:'2026-11-09'}]},
    {positioning:{...report().positioning,dix:45}},{positioning:{...report().positioning,gex:'123'}}];
  for(const change of variants) assert.throws(()=>api.validateReport({...report(),...change},fixedDate));
});

test('new query cancels prior request and ignores late progress, response and cleanup',async()=>{
  const first=deferred(),second=deferred(),calls=[];
  const {api,document,open}=setup((...args)=>{calls.push(args);return calls.length===1?first.promise:second.promise;});
  open();const pending=api.query();
  assert.equal(calls[0][2].aborted,true);calls[0][1]({message:'stale-progress'});
  first.resolve(report());await settle();
  assert.equal(document.querySelector('#market-context-result').textContent,'');
  assert.equal(document.querySelector('#market-context-refresh').disabled,true);
  assert.doesNotMatch(document.querySelector('#market-context-status').textContent,/stale-progress/);
  second.resolve(report());await pending;
  assert.match(document.querySelector('#market-context-result').textContent,/45\.12%/);
  assert.equal(document.querySelector('#market-context-refresh').disabled,false);
});

for(const eventName of ['flow-market','flow-disconnect','flow-connect','flow-data']) {
  test(eventName+' clears displayed results and cancels pending output',async()=>{
    const late=deferred();let count=0,signal;
    const {dom,api,document,open}=setup((url,progress,current)=>{signal=current;return ++count===1?Promise.resolve(report()):late.promise;});
    open();await settle();assert.ok(document.querySelector('.mc-metrics'));
    const pending=api.query();dom.window.dispatchEvent(new dom.window.Event(eventName));
    assert.equal(signal.aborted,true);
    late.resolve(report());await pending;
    assert.equal(document.querySelector('#market-context-result').textContent,'');
    assert.equal(document.querySelector('#market-context-refresh').disabled,false);
    assert.doesNotMatch(document.querySelector('#market-context-sources').textContent,/公开观测/);
  });
}

test('connection changed without event cannot accept a prior connection response',async()=>{
  const late=deferred();let token='one';
  const {document,open}=setup(()=>late.promise,()=>({endpoint:'http://127.0.0.1:8788/api/snapshot',token,market:'US',date:fixedDate}));
  open();token='two';late.resolve(report());await settle();
  assert.equal(document.querySelector('#market-context-result').textContent,'');
  assert.match(document.querySelector('#market-context-status').textContent,/连接已变化/);
});

for(const action of ['Escape','cancel','close','button']) {
  test(action+' cancels request, restores focus and ignores late success',async()=>{
    const late=deferred();let signal;
    const {dom,api,document,open}=setup((url,progress,current)=>{signal=current;return late.promise;});
    open();const dialog=document.querySelector('dialog');
    if(action==='Escape') dialog.dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
    else if(action==='cancel') dialog.dispatchEvent(new dom.window.Event('cancel',{cancelable:true}));
    else if(action==='button') document.querySelector('#market-context-close').click();
    else api.close();
    assert.equal(signal.aborted,true);assert.equal(dialog.hasAttribute('open'),false);
    assert.equal(document.activeElement.id,'open-market-context');
    late.resolve(report());await settle();assert.equal(document.querySelector('#market-context-result').textContent,'');
  });
}

test('cancel button and request error produce actionable clean states',async()=>{
  const late=deferred();const {api,document,open}=setup(()=>late.promise);open();
  document.querySelector('#market-context-cancel').click();assert.match(document.querySelector('#market-context-status').textContent,/已取消/);
  late.reject(new Error('late-error'));await settle();assert.doesNotMatch(document.querySelector('#market-context-status').textContent,/late-error/);
  api.mount({request:async()=>{throw new Error('<b>来源超时</b>');}});await api.query();
  assert.equal(document.querySelector('#market-context-result').textContent,'');assert.equal(document.querySelector('#market-context-status b'),null);
  assert.match(document.querySelector('#market-context-status').textContent,/来源超时/);
});

test('reopening uses current parent date and an empty macro list is explicit',async()=>{
  let selected=fixedDate;
  const {api,document,open}=setup(async url=>({...report(),asOf:url.searchParams.get('asOf'),macro:[]}),()=>({date:selected}));
  open();await settle();api.close();selected='2026-11-08';open();await settle();
  assert.equal(document.querySelector('input').value,selected);
  assert.match(document.querySelector('#market-context-result').textContent,/没有可用宏观观测/);
});

// Deliberately synthetic CSV: tiny fictional prices and round ratios, never live observations.
const syntheticCSV='date,price,dix,gex\n2026-11-07,9,.9,999\n2026-11-04,2,.2,-2\n2026-11-06,3,.3,0\n2026-11-05,1,.1,1';
function selectCSV(dom, file) {
  const input=dom.window.document.querySelector('#market-context-csv');
  Object.defineProperty(input,'files',{configurable:true,value:file?[file]:[]});
  input.dispatchEvent(new dom.window.Event('change'));
}
const csvFile=text=>({size:Buffer.byteLength(text),text:async()=>text});

test('CSV parser uses latest eligible row from unsorted input and preserves missing versus zero',()=>{
  const {api}=setup();
  const row=api.parseDixCSV(syntheticCSV,fixedDate);
  assert.equal(row.date,fixedDate);assert.equal(row.price,3);assert.equal(row.gex,0);assert.equal(row.dix,.3);
  const missing=api.parseDixCSV('date,price,dix,gex\n2026-11-06,,,',fixedDate);
  for(const key of ['price','dix','gex']) assert.equal(missing[key],null);
  assert.equal(api.parseDixCSV('date,price,dix,gex\n2026-11-07,1,.1,1',fixedDate),null);
});

test('CSV rejects malformed headers, dates, ambiguous rows, invalid numbers and unsafe cells',()=>{
  const {api}=setup();
  for(const text of ['date,price,dix','date,price,dix,gex','date,price,dix,gex\n2026-02-30,1,.1,1',
    'date,price,dix,gex\n2026-11-06,0,.1,1','date,price,dix,gex\n2026-11-06,1,30,1',
    'date,price,dix,gex\n2026-11-06,1,.1,Infinity','date,price,dix,gex\n2026-11-06,1,.1,1e999',
    'date,price,dix,gex\n2026-11-06,1,.1,0x10','date,price,dix,gex\n2026-11-06,"1,000",.1,1',
    'date,price,dix,gex\n2026-11-06,1,.1,=1+1','date,price,dix,gex\n2026-11-06,1,.1,<img src=x onerror=alert(1)>',
    'date,price,dix,gex\n2026-11-06,1,.1,1\n2026-11-06,2,.2,2']) assert.throws(()=>api.parseDixCSV(text,fixedDate),text);
});

test('browser-only import works despite server failure and never persists or uploads content',async()=>{
  let requests=0;const {dom,document,open,api}=setup(async()=>{requests++;throw new Error('synthetic offline');});
  const forbidden=()=>{throw new Error('unexpected persistence or upload');};
  dom.window.fetch=forbidden;dom.window.Storage.prototype.setItem=forbidden;
  open();await settle();selectCSV(dom,csvFile(syntheticCSV));await settle();
  assert.equal(document.querySelector('#market-context-csv').labels[0].textContent,'导入官方DIX CSV');
  const preview=document.querySelector('#market-context-manual-result');
  assert.match(preview.textContent,/30%/);assert.match(preview.textContent,/0 USD/);assert.match(preview.textContent,/2026-11-06/);
  assert.equal(document.querySelector('#market-context-result').textContent,'');assert.equal(requests,1);
  assert.match(document.querySelector('.mc-manual').textContent,/手动导入 · 浏览器内存 · 非实时 · 所选日期非 PIT/);
  await api.query();assert.match(preview.textContent,/30%/);assert.equal(requests,2);
  selectCSV(dom,csvFile('date,price,dix,gex\n2026-11-06,,,'));await settle();
  assert.deepEqual([...preview.querySelectorAll('dd')].map(n=>n.textContent),['不可用','不可用','不可用']);
});

test('oversize file is rejected before reading; future-only and injection imports leave no preview',async()=>{
  const {dom,document,open}=setup();open();await settle();
  let read=false;selectCSV(dom,{size:2*1024*1024+1,text:async()=>{read=true;return syntheticCSV;}});await settle();
  assert.equal(read,false);assert.match(document.querySelector('#market-context-import-status').textContent,/2 MB/);
  selectCSV(dom,csvFile('date,price,dix,gex\n2026-11-07,1,.1,1'));await settle();
  assert.match(document.querySelector('#market-context-import-status').textContent,/没有不晚于/);
  selectCSV(dom,csvFile('date,price,dix,gex\n2026-11-06,1,.1,<img src=x onerror=alert(1)>'));await settle();
  assert.match(document.querySelector('#market-context-import-status').textContent,/导入失败/);
  assert.equal(document.querySelector('#market-context-manual-result').textContent,'');assert.equal(document.querySelector('img'),null);
});

for(const action of ['date','Escape','close','disconnect','cancel-query','native-close']) {
  test(action+' clears import and ignores late file text',async()=>{
    const late=deferred();const {dom,api,document,open}=setup();open();await settle();
    selectCSV(dom,csvFile(syntheticCSV));await settle();assert.match(document.querySelector('#market-context-manual-result').textContent,/30%/);
    selectCSV(dom,{size:10,text:()=>late.promise});
    if(action==='date') {const input=document.querySelector('#market-context-asof');input.value='2026-11-04';input.dispatchEvent(new dom.window.Event('change'));}
    else if(action==='Escape') document.querySelector('dialog').dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
    else if(action==='close') api.close();
    else if(action==='native-close') document.querySelector('dialog').dispatchEvent(new dom.window.Event('close'));
    else if(action==='cancel-query') document.querySelector('#market-context-cancel').click();
    else dom.window.dispatchEvent(new dom.window.Event('flow-disconnect'));
    late.resolve(syntheticCSV);await settle();
    assert.equal(document.querySelector('#market-context-manual-result').textContent,'');
    assert.match(document.querySelector('#market-context-import-status').textContent,/尚未导入/);
    if(['close','Escape','native-close'].includes(action)) assert.equal(document.activeElement.id,'open-market-context');
  });
}

test('new selection invalidates prior file read and FileReader fallback reads real browser File',async()=>{
  const {dom,document,open}=setup();open();await settle();const late=deferred();
  selectCSV(dom,{size:10,text:()=>late.promise});selectCSV(dom,csvFile('date,price,dix,gex\n2026-11-06,7,.7,7'));await settle();
  late.resolve(syntheticCSV);await settle();assert.match(document.querySelector('#market-context-manual-result').textContent,/70%/);
  selectCSV(dom,new dom.window.File([syntheticCSV],'synthetic.csv',{type:'text/csv'}));
  for(let i=0;i<20 && !document.querySelector('#market-context-manual-result').textContent;i++) await new Promise(resolve=>setTimeout(resolve,5));
  assert.match(document.querySelector('#market-context-manual-result').textContent,/30%/);
});

test('source links and licensing are explicit, latest-page caveat is visible and upstream warnings collapsed',async()=>{
  const data=report();data.macro[0].retrievalMode='latest-page';data.positioning.reason='raw positioning diagnostic';data.warnings=['raw diagnostic','raw diagnostic'];
  const {document,open}=setup(async()=>data);open();await settle();
  assert.match(document.querySelector('#market-context-sources').textContent,/自动采集仅限已取得 SqueezeMetrics 书面许可/);
  assert.ok(document.querySelector('a[href="https://www.financialjuice.com/"]'));
  assert.ok(document.querySelector('a[href="https://fred.stlouisfed.org/releases/calendar"]'));
  assert.match(document.querySelector('tbody tr').textContent,/最新页面观测 \/ 历史截至日可能无覆盖/);
  const details=document.querySelector('.mc-warnings details');assert.equal(details.open,false);assert.equal(details.querySelectorAll('li').length,1);
  assert.equal([...document.querySelectorAll('#market-context-result details')].find(n=>n.textContent.includes('raw positioning diagnostic')).open,false);
});
