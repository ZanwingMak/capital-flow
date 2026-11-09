'use strict';
(() => {
  /** 绑定现有任务面板；仅管理可见性和焦点，不读取业务字段或执行I/O。 */
  function mount({dialog}) {
    const tabs=Array.from(dialog.querySelectorAll('[data-workspace-tab]'));
    const panels=Array.from(dialog.querySelectorAll('[data-workspace-panel]'));
    if (!tabs.length || tabs.length!==panels.length) return null;
    const linked=tabs.map(tab=>panels.find(panel=>panel.id===tab.getAttribute('aria-controls')));
    if (linked.some(panel=>!panel)) return null;
    const intro=dialog.querySelector('#private-intro'), session=dialog.querySelector('#private-session');
    const scroller=dialog.querySelector('.private-panels');

    /** 同步ARIA与漫游焦点，隐藏的面板连同其表单退出键盘遍历。 */
    function select(index, focus=false) {
      tabs.forEach((tab,i)=>{
        const active=i===index;
        tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;
        linked[i].hidden=!active;linked[i].inert=!active;
      });
      if (scroller) scroller.scrollTop=0;
      const strip=dialog.querySelector('.private-tabs'),tab=tabs[index];
      if (strip?.getBoundingClientRect && tab.getBoundingClientRect) {
        const bounds=strip.getBoundingClientRect(),selected=tab.getBoundingClientRect();
        if (selected.left<bounds.left) strip.scrollLeft-=Math.ceil(bounds.left-selected.left);
        else if (selected.right>bounds.right) strip.scrollLeft+=Math.ceil(selected.right-bounds.right);
      }
      if (focus) tabs[index].focus();
    }
    /** 会话开启后收起接入流程，账户和状态仍由原工作台管理。 */
    function setSession(active) {
      dialog.setAttribute('data-workspace-session',active?'active':'idle');
      if (intro) intro.hidden=active;
      if (session) session.hidden=active;
    }
    /** 关闭时回到账户概览，不移动焦点或接触由原清理流程负责的私有值。 */
    function reset() {select(0);setSession(false);}
    tabs.forEach((tab,index)=>{
      tab.addEventListener('click',()=>select(index));
      tab.addEventListener('keydown',event=>{
        let next;
        if (event.key==='ArrowRight') next=(index+1)%tabs.length;
        else if (event.key==='ArrowLeft') next=(index+tabs.length-1)%tabs.length;
        else if (event.key==='Home') next=0;
        else if (event.key==='End') next=tabs.length-1;
        else return;
        event.preventDefault();select(next,true);
      });
    });
    reset();
    return {setSession,reset};
  }
  if (typeof window!=='undefined') window.FlowdeskWorkspaceNav={mount};
})();
