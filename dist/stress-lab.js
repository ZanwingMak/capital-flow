'use strict';
// 纯计算与内存DOM模块；只接受工作台已有上下文，不持有API客户端。
(() => {
  const GROUPS={core:'底仓',tactical:'短线',ungrouped:'未分组'};
  const MAX_NUMBER=1e12, MAX_AMOUNT=1e12;

  /** 严格解析普通十进制，空白、非有限和越界值均保留明确错误。 */
  function parseNumber(input, label='数值', min=0, max=MAX_NUMBER) {
    if (input === null || input === undefined || (typeof input==='string' && !input.trim())) return {value:null,error:label+'未填写'};
    if (!['number','string'].includes(typeof input) || (typeof input==='string' && !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(input.trim()))) return {value:null,error:label+'须为普通十进制数字'};
    const value=Number(input);
    if (!Number.isFinite(value) || value<min || value>max || (value===0 && typeof input==='string' && /[1-9]/.test(input))) return {value:null,error:label+`须在 ${min} 至 ${max} 之间且为有限数值`};
    return {value,error:''};
  }

  /** 只复制标的、数量状态与分组；缺口标的即使未在positions中也保留。 */
  function copyRows(snapshot) {
    const gaps=new Set((snapshot.position_gaps || []).map(g=>g.symbol));
    const rows=(snapshot.positions || []).map(p=>({symbol:String(p.symbol ?? '未知标的'),quantity:p.quantity,
      quantity_status:gaps.has(p.symbol)?'known_partial':p.quantity_status,
      group:Object.hasOwn(GROUPS,p.group)?p.group:'ungrouped'}));
    for (const symbol of gaps) if (!rows.some(p=>p.symbol===symbol)) rows.push({symbol:String(symbol),quantity:null,quantity_status:'known_partial',group:'ungrouped'});
    return rows;
  }

  /** 部分数量不能当作总量，其他未知状态也不得默认为完整数量。 */
  function quantityResult(row) {
    if (row.quantity_status==='known_partial') return {value:null,error:'截止总量未知（仅有已知部分，不参与情景）'};
    if (row.quantity_status!=null && !['known','complete'].includes(row.quantity_status)) return {value:null,error:'数量状态未知，不参与情景'};
    return parseNumber(row.quantity,'数量');
  }

  /** 检查每次乘积及累计金额，限制在仍能合理显示到分的数值范围。 */
  function validAmount(value) {return Number.isFinite(value) && Math.abs(value)<=MAX_AMOUNT;}

  /** 汇总同一覆盖集合；空集合保持未知，溢出则停止全部汇总。 */
  function totalsFor(rows) {
    if (!rows.length) return null;
    const totals={baseline:0,scenarioValue:0,change:0};
    for (const row of rows) for (const key of Object.keys(totals)) {
      totals[key]+=row[key];
      if (!validAmount(totals[key])) throw new Error('汇总金额超出计算范围；未展示总额或分组总额。');
    }
    return totals;
  }

  /** 计算已覆盖正股的假设情景，逐行保留缺口，不计算账户权益或收益率。 */
  function calculate(rows,{prices=[],globalShock,overrides=[]}={}) {
    const global=parseNumber(globalShock,'全局冲击（%）',-100,1000);
    const results=rows.map((row,i)=>{
      const quantity=quantityResult(row),price=parseNumber(prices[i],'参考价格 USD');
      const custom=overrides[i];
      const shock=custom===undefined || custom===null || (typeof custom==='string' && !custom.trim()) ? global : parseNumber(custom,'单股冲击（%）',-100,1000);
      const reasons=[quantity.error,price.error,global.error,shock===global?'':shock.error].filter(Boolean);
      const result={symbol:String(row.symbol),group:Object.hasOwn(GROUPS,row.group)?row.group:'ungrouped',
        baseline:null,scenarioPrice:null,scenarioValue:null,change:null,shock:shock.value,reasons};
      if (reasons.length) return result;
      const multiplier=1+shock.value/100,baseline=quantity.value*price.value,scenarioPrice=price.value*multiplier,scenarioValue=quantity.value*scenarioPrice,change=scenarioValue-baseline;
      const underflow=(quantity.value>0 && price.value>0 && baseline===0) || (price.value>0 && multiplier>0 && scenarioPrice===0) || (quantity.value>0 && scenarioPrice>0 && scenarioValue===0);
      if (underflow || ![baseline,scenarioPrice,scenarioValue,change].every(validAmount) || scenarioPrice<0 || scenarioValue<0) {
        reasons.push('情景价格或金额超出计算范围，不参与汇总');return result;
      }
      return {...result,baseline,scenarioPrice,scenarioValue,change};
    });
    const covered=results.filter(row=>!row.reasons.length);
    const groups=Object.fromEntries(Object.keys(GROUPS).map(key=>[key,{count:covered.filter(row=>row.group===key).length,total:results.filter(row=>row.group===key).length,totals:null}]));
    let totals=null,error='';
    try {
      totals=totalsFor(covered);
      for (const key of Object.keys(groups)) groups[key].totals=totalsFor(covered.filter(row=>row.group===key));
    } catch (failure) {error=failure.message;totals=null;for (const group of Object.values(groups)) group.totals=null;}
    return {rows:results,covered:covered.length,total:results.length,missing:results.filter(row=>row.reasons.length).map(row=>row.symbol),groups,totals,error};
  }

  /** 校验人工价格参考时刻，必须真实有效、含时区且不晚于当前时刻。 */
  function referenceTimeError(input) {
    const text=String(input || '').trim();
    const match=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(Z|[+-]\d{2}:\d{2})$/.exec(text);
    const error='请填写有效的人工参考价格时间（含时区ISO时间，不能在未来）。';
    if (!match) return error;
    const [,year,month,day,hour,minute,second,zone]=match;
    const calendar=new Date(Date.UTC(Number(year),Number(month)-1,Number(day)));
    if (calendar.getUTCFullYear()!==Number(year) || calendar.getUTCMonth()!==Number(month)-1 || calendar.getUTCDate()!==Number(day) || Number(hour)>23 || Number(minute)>59 || Number(second)>59) return error;
    if (zone!=='Z' && (Number(zone.slice(1,3))>14 || Number(zone.slice(4))>59 || (Number(zone.slice(1,3))===14 && Number(zone.slice(4))!==0))) return error;
    const timestamp=Date.parse(text);
    return !Number.isFinite(timestamp) || timestamp>Date.now() ? error : '';
  }

  /** 金额以美元显示到分；未知与真实0不同，近零负数不显示负零。 */
  function money(value) {return value===null ? '—' : (Math.abs(value)<0.005?0:value).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});}

  /** 账户、快照版本和日期共同标识一次上下文，缺少授权快照时不载入。 */
  function contextKey({account,snapshot}={}) {
    return account && snapshot && Number.isInteger(snapshot.revision) && snapshot.revision>=0 && (!snapshot.currency || snapshot.currency==='USD') ? JSON.stringify([account,snapshot.revision,snapshot.asOf ?? null]) : null;
  }

  /** 挂载原生DOM与事件；没有会话、存储、行情查询或导出能力。 */
  function mount({root,context,document:doc=globalThis.document}) {
    if (!root) return null;
    let generation=0,key=null,rows=[],refs=null;

    /** 所有动态内容按纯文本渲染，标的永不进入HTML、选择器或节点ID。 */
    function node(tag,text='',className='') {
      const element=doc.createElement(tag);element.textContent=text;
      if (className) element.className=className;
      return element;
    }
    /** 创建具有显式按钮类型的操作入口。 */
    function button(id,text,handler) {
      const element=node('button',text,'button');element.id=id;element.type='button';element.addEventListener('click',handler);return element;
    }
    /** 递归擦除被移除的节点，旧事件引用也不能保留手填值或结果文本。 */
    function wipe(element) {
      for (const child of Array.from(element.children)) wipe(child);
      if ('value' in element) element.value='';
      element.textContent='';
    }
    /** 立即清除全部输入、结果和上下文标识，同时使旧节点事件失效。 */
    function clear() {generation++;rows=[];refs=null;key=null;wipe(root);root.replaceChildren();}
    /** 先检查代际，再检查最新上下文，阻止旧按钮跨账户或版本采用输入。 */
    function current(epoch) {
      if (epoch!==generation) return false;
      if (contextKey(context())!==key) {sync();return false;}
      return true;
    }
    /** 任意输入变动立即删除旧结果，等待用户重新计算。 */
    function invalidate(epoch) {
      if (!current(epoch) || !refs) return;
      wipe(refs.results);refs.message.textContent='输入已变更，请重新计算。';
    }
    /** 创建可访问的文本数字输入，保留浏览器不会自动清零的原始文本。 */
    function field(id,label,epoch,placeholder='') {
      const wrapper=node('label',label),input=node('input');input.id=id;input.type='text';input.autocomplete='off';input.spellcheck=false;
      input.inputMode=id==='stress-time'?'text':'decimal';input.placeholder=placeholder;
      input.setAttribute('aria-describedby','stress-rules stress-message');
      input.addEventListener('input',()=>invalidate(epoch));wrapper.append(input);return {wrapper,input};
    }
    /** 输出带表头的原生表格，由外层容器提供窄屏键盘滚动。 */
    function table(headers,label) {
      const scroll=node('div','','private-table stress-scroll');scroll.tabIndex=0;scroll.setAttribute('role','region');scroll.setAttribute('aria-label',label);
      const table=node('table'),head=node('thead'),tr=node('tr'),body=node('tbody');
      for (const title of headers) {const th=node('th',title);th.setAttribute('scope','col');tr.append(th);}
      head.append(tr);table.append(head,body);scroll.append(table);return {scroll,body};
    }
    /** 展示覆盖范围、美元汇总、分组与每只正股的计算或缺口原因。 */
    function showResults(result) {
      wipe(refs.results);
      refs.results.append(node('p',`可计算情景覆盖 ${result.covered} / ${result.total} 个标的（按标的数，不是市值覆盖率）。`,'stress-coverage'));
      if (result.missing.length) refs.results.append(node('p','未覆盖标的：'+result.missing.join('、')));
      refs.results.append(node('p','人工参考价格时间：'+refs.time.value.trim()+'；假设情景、不是预测。'));
      const totals=result.totals;
      refs.results.append(node('p',totals ? `已覆盖正股参考市值 USD ${money(totals.baseline)} → 情景市值 USD ${money(totals.scenarioValue)}；已覆盖情景美元变化 USD ${money(totals.change)}` : (result.error || '没有可用覆盖，市值与变化未知。'),'stress-total'));
      refs.results.append(node('p','以上仅为可计算行的正股市值，不含缺口、现金或其他资产；不代表账户净值、收益率或券商精确核算。'));
      const detail=table(['正股 / 分组','参考市值 USD','冲击 %','情景每股价 USD','情景市值 USD','变化 USD / 缺口原因'],'逐股情景结果，可横向滚动');
      for (const row of result.rows) {
        const tr=node('tr');
        for (const text of [row.symbol+' / '+GROUPS[row.group],money(row.baseline),row.shock===null?'—':row.shock.toFixed(2)+'%',money(row.scenarioPrice),money(row.scenarioValue),row.reasons.length?row.reasons.join('；'):money(row.change)]) tr.append(node('td',text));
        detail.body.append(tr);
      }
      refs.results.append(detail.scroll,node('h4','分组汇总 · 同一已覆盖集合'));
      const grouped=table(['分组 / 覆盖标的数','参考市值 USD','情景市值 USD','变化 USD'],'分组情景结果，可横向滚动');
      for (const [name,group] of Object.entries(result.groups)) {
        const tr=node('tr');
        for (const text of [`${GROUPS[name]} · ${group.count} / ${group.total}`,money(group.totals?.baseline ?? null),money(group.totals?.scenarioValue ?? null),money(group.totals?.change ?? null)]) tr.append(node('td',text));
        grouped.body.append(tr);
      }
      refs.results.append(grouped.scroll);
      refs.message.textContent=result.error || (result.covered===result.total && result.total ? '情景已计算。' : '存在未覆盖标的，请检查逐行原因；缺口没有按0计入。');
    }
    /** 显式载入只复制当前快照投影，绝不从成本推导价格。 */
    function load(epoch) {
      if (!current(epoch) || !key) return;
      const snapshot=context().snapshot;rows=copyRows(snapshot);
      wipe(root);root.replaceChildren();
      const source=node('p',`来源持仓日期 ${snapshot.asOf ?? '未知'} · revision ${snapshot.revision} · USD`,'private-meta');source.id='stress-source';
      const rules=node('p','冲击范围 -100% 至 +1000%；单股空白继承全局，填写0表示单股不变。价格与数量须在0至1万亿之间，金额和累计金额不超过1万亿美元；只接受普通十进制。','stress-rules');rules.id='stress-rules';
      const time=field('stress-time','人工参考价格时间（含时区，必填）',epoch,'2026-01-02T15:30:00Z');
      const global=field('stress-global','全局假设冲击（%，必填）',epoch,'例如 -10；不预填');
      const controls=node('div','','private-grid');controls.append(time.wrapper,global.wrapper);
      const presets=node('div','','private-actions');
      for (const shock of [5,10,20]) presets.append(button('stress-preset-'+shock,`假设下跌 ${shock}%`,()=>{if (current(epoch)) {global.input.value=String(-shock);invalidate(epoch);}}));
      const inputs=table(['正股 / 分组','账本总数量（股）','人工参考每股价 USD','单股假设冲击 %'],'情景输入，可横向滚动');
      const prices=[],overrides=[];
      rows.forEach((row,i)=>{
        const tr=node('tr'),quantity=quantityResult(row),price=field('stress-price-'+i,row.symbol+' 参考价格 USD',epoch,'空白=缺失'),shock=field('stress-shock-'+i,row.symbol+' 单股冲击 %',epoch,'空白=继承全局');
        prices.push(price.input);overrides.push(shock.input);
        tr.append(node('td',row.symbol+' / '+GROUPS[row.group]),node('td',quantity.error || String(row.quantity)));
        const priceCell=node('td'),shockCell=node('td');priceCell.append(price.wrapper);shockCell.append(shock.wrapper);tr.append(priceCell,shockCell);inputs.body.append(tr);
      });
      const message=node('p',rows.length?'请手填参考时间、价格及假设冲击后计算。':'当前快照没有正股记录，不能计算。');message.id='stress-message';message.setAttribute('role','status');message.setAttribute('aria-live','polite');
      const results=node('div');results.id='stress-results';
      refs={time:time.input,global:global.input,prices,overrides,message,results};
      const actions=node('div','','private-actions');
      const run=button('stress-run','计算假设情景',()=>{
        if (!current(epoch) || !refs) return;
        wipe(results);
        const error=referenceTimeError(refs.time.value);
        if (error) {message.textContent=error;return;}
        showResults(calculate(rows,{prices:prices.map(input=>input.value),globalShock:global.input.value,overrides:overrides.map(input=>input.value)}));
      });
      run.disabled=!rows.length;
      actions.append(run,button('stress-overrides','清除单股覆盖',()=>{if (current(epoch)) {for (const input of overrides) input.value='';invalidate(epoch);}}),button('stress-clear','清空实验',()=>{if (current(epoch)) {clear();sync();}}));
      root.append(source,rules,controls,presets,inputs.scroll,actions,message,results);
    }
    /** 上下文变化时只显示空入口；此步骤不复制持仓或任何成本信息。 */
    function sync() {
      const next=contextKey(context());
      if (next===key && root.children.length) return;
      clear();key=next;
      const epoch=generation,loadButton=button('stress-load','载入当前账户持仓',()=>load(epoch));loadButton.disabled=!key;
      root.append(node('p','手动载入后填写USD参考价格和时间。只使用当前已授权快照；关闭工作台、切换账户或刷新版本会清空本次实验。'),loadButton);
    }
    return {sync,clear};
  }
  if (typeof module!=='undefined') module.exports={parseNumber,copyRows,calculate,referenceTimeError,mount};
  if (typeof window!=='undefined') window.FlowdeskStressLab={mount};
})();
