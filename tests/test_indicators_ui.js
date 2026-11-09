'use strict';
// 使用已安装的jsdom真实DOM；不启动浏览器、端口、网络或安装依赖。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {test} = require('node:test');
const {JSDOM} = require('jsdom');
const code = fs.readFileSync('dist/indicators.js', 'utf8');

/** 在真实DOM载入实际脚本，通过依赖注入避免网络。 */
function setup(request, getConnection=()=>({endpoint:'http://127.0.0.1:8788/api/snapshot', market:'US', token:'test-token'})) {
  const dom = new JSDOM('<button id="open-indicators">自定义指标</button>', {url:'http://127.0.0.1:8788/', runScripts:'outside-only'});
  dom.window.AbortController = AbortController;
  dom.window.AbortSignal = AbortSignal;
  dom.window.eval(code);
  const api = dom.window.FlowdeskIndicators;
  api.mount({request, getConnection});
  dom.window.document.getElementById('open-indicators').click();
  return {dom, api, document:dom.window.document};
}

/** 合成报告只用于DOM状态测试，不冒充真实行情。 */
function report() {
  return {source:'flowdesk-indicators', schemaVersion:1, market:'US', symbol:'TEST', asOf:'2026-11-06', timeframe:'1d', status:'available',
    compatibility:{futuCertified:false, notice:'尚未富途逐根认证'},
    indicator:{id:'QUSHI-CHANG', sourceBasename:'QUSHI-CHANG.ftindex', sourceVersion:'synthetic', sourceSha256:'a'.repeat(64)},
    catalog:[{id:'CL2', supported:false, displayRepainting:true, reason:'图形回画，未移植'},{id:'SRJ', supported:false, reason:'水平回画'}],
    sample:{bars:3,start:'2026-11-04',end:'2026-11-06'}, data:{source:'synthetic', adjustment:'QFQ'},
    dataQuality:{eligibleBars:2,missingVolumeBars:0,zeroVolumeBars:0,historicalBottomReady:false,seriesReadiness:{}},
    dates:['2026-11-04','2026-11-05','2026-11-06'], price:[100,102,101], series:{MA10:[null,101,101.5]},
    events:[{name:'CALLSIG',date:'2026-11-05',index:1,confirmIndex:1,layer:'primary'}], warnings:['合成数据'], splits:{},
    backtest:{range:{start:'2026-11-05',end:'2026-11-06',bars:2},rules:{maxHoldBars:40,feeBpsPerLeg:5,slippageBpsPerLeg:5},
      metrics:{totalReturn:0,maxDrawdown:0,exposure:0,turnover:0,closedTrades:0,winRate:null,sharpe:null},
      benchmark:{totalReturn:.01},equity:[{date:'2026-11-05',equity:10000,benchmark:9990},{date:'2026-11-06',equity:10000,benchmark:10100}],
      trades:[],openPosition:null}};
}

test('真实DOM懒挂载、可访问标签与CL2/SRJ禁用',()=>{
  const {document,api} = setup();
  api.mount();
  assert.equal(document.querySelectorAll('#indicator-dialog').length,1);
  assert.ok(document.querySelector('#indicator-dialog').hasAttribute('open'));
  assert.match(document.querySelector('#indicator-dialog').textContent,/尚未.*富途.*认证/);
  for (const input of document.querySelectorAll('input,select')) assert.ok(input.labels.length>0,input.id);
  for (const key of ['CL2','SRJ']) assert.equal(document.querySelector(`option[value="${key}"]`).disabled,true);
});

test('URL仅复用行情地址，保留成本且不包含凭据或任意路径',()=>{
  const {api} = setup();
  const url=api.createURL({endpoint:'http://127.0.0.1:8788/api/snapshot?stale=1'}, {symbol:'TEST',asOf:'2026-11-06',indicator:'QUSHI-DUAN',feeBps:5,slippageBps:6});
  assert.equal(url.pathname,'/api/indicators');
  assert.equal(url.searchParams.get('slippageBps'),'6');
  assert.equal(url.searchParams.has('stale'),false);
  assert.throws(()=>api.createURL({endpoint:'javascript:alert(1)'},{}));
});

test('纯SVG保留缺失断点、注释确认根，防止文本注入',()=>{
  const {api,document} = setup();
  const html=api.chartSVG(['a','b','c'], [{name:'<script>x</script>',values:[100,null,102]}], [{index:2,name:'CALLSIG'}], '合成');
  const section=document.createElement('section'); section.innerHTML=html;
  assert.equal(section.querySelectorAll('script').length,0);
  assert.equal(section.querySelectorAll('svg[role="img"] path').length,2);
  assert.match(section.textContent,/CALLSIG/);
  assert.equal(section.querySelector('svg').getAttribute('role'),'img');
});

test('响应错配日期、标的、版本及无限值被拒绝',()=>{
  const {api} = setup();
  const expected={symbol:'TEST',asOf:'2026-11-06',indicator:'QUSHI-CHANG'};
  for (const change of [{symbol:'OTHER'}, {asOf:'2026-11-05'}, {source:'other'}, {price:[NaN,2,3]}, {indicator:{id:'QUSHI-DUAN'}}]) {
    assert.throws(()=>api.validateReport({...report(),...change},expected));
  }
});

for (const [family, keys] of Object.entries({
  GZRX1:['MA5','MA10','MA30','MA60','MA90','MA180'],
  GZRX3:['MA55','MA60','MA65','MA120','MA250'],
  LDR:['UP1','LOW1','UP2','LOW2','TREND'],
  GZRZH:['MA5','MA10','MA30','MA55','MA60','MA65','MA90','MA120','MA180','MA200','MA250','UP1','LOW1','UP2','LOW2','TREND'],
})) {
  test(`${family}完整绘制全部价格序列，图例与曲线样式一一对应且不重复`,()=>{
    const {api,document}=setup(); const data=report();
    data.indicator.id=family; data.backtest=null;
    data.series=Object.fromEntries(keys.map((key,i)=>[key,[100+i,101+i,102+i]]));
    // 辅助间距不是价格曲线；布尔事件不进入价格图。
    data.series.LGAP=[.01,.02,.03]; data.series.CALLSIG=[false,true,false];
    api.renderReport(data);
    const paths=[...document.querySelectorAll('#indicator-result svg[role="img"] path.ind-line')];
    const legends=[...document.querySelectorAll('#indicator-result .ind-legend > span')];
    const names=['收盘 USD',...keys];
    assert.deepEqual(paths.map(path=>path.querySelector('title').textContent),names);
    assert.deepEqual(legends.map(legend=>legend.textContent.trim()),names);
    const styles=paths.map(path=>[path.style.stroke,path.style.strokeDasharray].join('|'));
    assert.equal(new Set(styles).size,names.length);
    legends.forEach((legend,i)=>{
      const swatch=legend.querySelector('[aria-hidden="true"]');
      assert.ok(swatch,'图例包含可见线型样本');
      const sample=swatch.querySelector('path');
      assert.equal(sample.style.stroke,paths[i].style.stroke);
      assert.equal(sample.style.strokeDasharray,paths[i].style.strokeDasharray);
      const normalized=document.createElement('span'); normalized.style.color=paths[i].style.stroke;
      assert.equal(legend.style.color,normalized.style.color);
    });
  });
}

test('重开同步主日期，请求使用新日期；本次弹窗内手改日期仍有效',async()=>{
  let date='2026-11-05'; const requested=[];
  const {api,document}=setup(async url=>{
    requested.push(url.searchParams.get('asOf'));
    return {...report(),asOf:url.searchParams.get('asOf')};
  },()=>({endpoint:'http://127.0.0.1:8788/api/snapshot',market:'US',date}));
  const input=document.querySelector('#indicator-asof');
  assert.equal(input.value,date);
  document.querySelector('#indicator-symbol').value='TEST';
  api.close(); date='2026-11-06';
  document.querySelector('#open-indicators').click();
  assert.equal(input.value,date);
  await api.query();
  input.value='2026-11-07'; api.open();
  assert.equal(input.value,'2026-11-07');
  await api.query();
  assert.deepEqual(requested,['2026-11-06','2026-11-07']);
  assert.match(document.querySelector('#indicator-status').textContent,/截至 2026-11-07/);
});

test('重开无主日期时回退纽约当日，并刷新跨日日期上限',()=>{
  const {api,document,dom}=setup(undefined,()=>({market:'US',date:'2026-11-05'}));
  api.close();
  const OriginalDate=dom.window.Date;
  dom.window.Date=class extends OriginalDate {
    constructor(...args) { super(...(args.length?args:['2026-11-10T05:30:00Z'])); }
  };
  api.mount({getConnection:()=>({market:'US'})});
  api.open();
  assert.equal(document.querySelector('#indicator-asof').value,'2026-11-10');
  assert.equal(document.querySelector('#indicator-asof').max,'2026-11-10');
});

test('真实DOM渲染确认事件、空成交胜率、基准及暖机质量',()=>{
  const {api,document} = setup();
  api.renderReport(report());
  const text=document.querySelector('#indicator-result').textContent;
  assert.match(text,/CALLSIG/); assert.match(text,/无已平仓交易/);
  assert.match(text,/1000/); assert.match(text,/买入持有/);
  assert.ok(document.querySelectorAll('svg').length>=2);
  assert.doesNotMatch(text,/胜率\s*0\.0/);
});

test('缺量、暖机与无数据状态不伪造曲线',()=>{
  const {api,document} = setup();
  const data=report(); data.status='empty'; data.dates=[]; data.price=[]; data.series={};data.events=[];data.backtest=null;data.sample.bars=0;
  api.renderReport(data);
  assert.match(document.querySelector('#indicator-result').textContent,/无.*日线/);
  assert.equal(document.querySelectorAll('svg').length,0);
  data.status='warming-up';data.sample.bars=3;data.dates=report().dates;data.price=report().price;
  api.renderReport(data);
  assert.match(document.querySelector('#indicator-result').textContent,/暖机/);
});

test('异步查询取消旧请求，旧响应不覆盖新结果',async()=>{
  const pending=[];
  const {api,document}=setup((url,progress,signal)=>new Promise(resolve=>pending.push({url,signal,resolve})));
  document.querySelector('#indicator-symbol').value='TEST'; document.querySelector('#indicator-asof').value='2026-11-06';
  const first=api.query(); const second=api.query();
  assert.equal(pending[0].signal.aborted,true);
  pending[1].resolve(report()); await second;
  pending[0].resolve({...report(),symbol:'WRONG'}); await first;
  assert.match(document.querySelector('#indicator-result').textContent,/TEST/);
  assert.doesNotMatch(document.querySelector('#indicator-status').textContent,/错配/);
});

test('错误、关闭与Escape释放请求并恢复入口焦点',async()=>{
  const {api,document,dom}=setup(async()=>{throw new Error('合成数据缺失');});
  document.querySelector('#indicator-symbol').value='TEST';document.querySelector('#indicator-asof').value='2026-11-06';
  await api.query(); assert.match(document.querySelector('#indicator-status').textContent,/合成数据缺失/);
  document.querySelector('#indicator-dialog').dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
  assert.equal(document.querySelector('#indicator-dialog').hasAttribute('open'),false);
  assert.equal(document.activeElement.id,'open-indicators');
});

test('恶意来源与成交字段作为文字渲染',()=>{
  const {api,document}=setup(); const data=report();data.data.source='<img src=x onerror=alert(1)>';
  data.backtest.trades=[{entryDate:'<script>x</script>',entrySignalDate:'x',entrySignal:'CALLSIG',exitDate:'x',exitReason:'x',entryPrice:100,exitPrice:101,netReturn:.01,netPnl:100}];
  api.renderReport(data);
  assert.equal(document.querySelectorAll('#indicator-result img,#indicator-result script').length,0);
});

test('真实请求管线复用Bearer并将202任务送往jobs端点',async()=>{
  const {api,document,dom}=setup(); const calls=[];
  dom.window.setTimeout=callback=>{queueMicrotask(callback);return 1;};
  dom.window.fetch=async(url,config)=>{
    calls.push({url:new URL(url),config});
    return calls.length===1?{status:202,ok:true,json:async()=>({jobId:'a'.repeat(24),progress:{message:'合成进度'}})}:
      {status:200,ok:true,json:async()=>report()};
  };
  document.querySelector('#indicator-symbol').value='TEST';document.querySelector('#indicator-asof').value='2026-11-06';
  await api.query();
  assert.equal(calls.length,2);assert.equal(calls[0].url.pathname,'/api/indicators');
  assert.equal(calls[1].url.pathname,'/api/jobs');assert.equal(calls[1].url.searchParams.get('id'),'a'.repeat(24));
  assert.equal(calls[1].config.headers.Authorization,'Bearer test-token');
  assert.equal(calls[0].url.href.includes('test-token'),false);
  assert.match(document.querySelector('#indicator-status').textContent,/计算完成/);
});

test('HTTP缺失端点和202格式错误明确显示，不产生假结果',async()=>{
  const {api,document,dom}=setup();
  document.querySelector('#indicator-symbol').value='TEST';document.querySelector('#indicator-asof').value='2026-11-06';
  dom.window.fetch=async()=>({status:404,ok:false,json:async()=>({})});await api.query();
  assert.match(document.querySelector('#indicator-status').textContent,/尚未接入/);
  dom.window.fetch=async()=>({status:202,ok:true,json:async()=>({jobId:'../private'})});await api.query();
  assert.match(document.querySelector('#indicator-status').textContent,/任务格式错误/);
  assert.equal(document.querySelectorAll('#indicator-result svg').length,0);
});

test('切换指标族与断开连接会禁用无关参数并释放在途请求',async()=>{
  let signal;
  const {api,document,dom}=setup((url,progress,current)=>{signal=current;return new Promise(()=>{});});
  const family=document.querySelector('#indicator-family');family.value='GZRX1';family.dispatchEvent(new dom.window.Event('change'));
  assert.equal(document.querySelector('#indicator-version').disabled,true);
  document.querySelector('#indicator-symbol').value='TEST';document.querySelector('#indicator-asof').value='2026-11-06';
  api.query();dom.window.dispatchEvent(new dom.window.Event('flow-disconnect'));
  assert.equal(signal.aborted,true);assert.match(document.querySelector('#indicator-status').textContent,/连接已变化/);
  assert.equal(document.querySelector('#indicator-result').hasAttribute('aria-busy'),false);
});
