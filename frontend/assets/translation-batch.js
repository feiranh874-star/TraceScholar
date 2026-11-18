(() => {
  'use strict';
  const el=id=>document.getElementById(id);
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let context,job=null,timer=null,submitting=false;
  function plan(papers,ids,mode,start,end) {
    if(!ids.length)throw new Error('请先在上方勾选论文。');
    if(ids.length>30)throw new Error('一次最多选择 30 篇论文，请分批翻译。');
    return ids.map(id=>{
      const p=papers.find(item=>item.paper_id===id);
      if(!p)throw new Error('所选论文已不在库中，请刷新资料。');
      const a=mode==='all'?1:Number(start),b=mode==='all'?p.page_count:Number(end);
      if(!Number.isInteger(a)||!Number.isInteger(b)||a<1||b<a||b>p.page_count)
        throw new Error('《'+(p.title||p.filename)+'》共 '+p.page_count+' 页，可填写 1–'+p.page_count+'，且起始页不大于结束页。');
      return {...p,start:a,end:b};
    });
  }
  function running(){return job&&['running','queued'].includes(job.status);}
  function refresh() {
    if(!context)return;
    const papers=context.papers(),ids=context.selected(),chosen=papers.filter(p=>ids.includes(p.paper_id)),mode=el('translationMode').value;
    el('translationRange').hidden=mode==='all';
    const min=chosen.length?Math.min(...chosen.map(p=>p.page_count)):null;
    for(const id of ['translateStart','translateEnd']){if(min!==null)el(id).max=min;else el(id).removeAttribute('max');el(id).setAttribute('aria-invalid','false');}
    el('translationRangeHint').textContent=chosen.length
      ?'已选择 '+chosen.length+' 篇。'+(mode==='all'?'每篇按各自总页数翻译。':'共同可填范围为 1–'+min+' 页；每篇的总页数见下方。')
      :'请勾选论文；选中后会显示每篇的总页数和可填写范围。';
    let ranges=[],error='';
    try{ranges=plan(papers,ids,mode,el('translateStart').value,el('translateEnd').value);}catch(e){if(ids.length)error=e.message;}
    el('translationRangeError').hidden=!error;el('translationRangeError').textContent=error;
    if(error&&mode==='range')for(const id of ['translateStart','translateEnd'])el(id).setAttribute('aria-invalid','true');
    el('translationSelection').innerHTML=chosen.map(p=>{
      const range=ranges.find(r=>r.paper_id===p.paper_id);
      return '<div class="translation-paper"><strong>'+esc(p.title||p.filename)+'</strong><p>共 '+p.page_count+' 页，可填写 1–'+p.page_count+' 页'+(range?' · 本次第 '+range.start+'–'+range.end+' 页':'')+'</p></div>';
    }).join('');
    const total=ranges.reduce((n,r)=>n+r.end-r.start+1,0);
    el('translateDocument').textContent=total?'开始批量翻译 · '+ranges.length+' 篇 / '+total+' 页':'开始批量翻译';
    el('translateDocument').disabled=submitting||Boolean(running())||!ranges.length||Boolean(error);
  }
  function renderJob() {
    if(!job)return;
    const results=job.paper_results||job.result?.papers||[],target=job.payload.target;
    const status={queued:'等待处理',running:'正在翻译',done:'翻译完成',failed:'部分步骤未完成',interrupted:'任务已中断'}[job.status]||job.status;
    const total=job.total||job.payload.ranges.reduce((n,r)=>n+r.end-r.start+1,0);
    el('translationJob').innerHTML='<section class="workspace-result"><div class="translation-job-heading"><strong>最近翻译任务 · '+esc(status)+'</strong>'+(['failed','interrupted'].includes(job.status)?'<button id="resumeBatchTranslation" class="secondary-button">继续未完成步骤</button>':'')+'</div><progress value="'+(job.progress||0)+'" max="'+total+'"></progress><p>已保存 '+(job.progress||0)+' / '+total+' 页。'+esc(job.message||'')+'</p>'+job.payload.ranges.map(item=>{
      const r=results.find(r=>r.paper_id===item.paper_id),count=(job.completed||[]).filter(key=>String(key).startsWith(item.paper_id+':')).length;
      const q=new URLSearchParams({page:String(item.start),from:'tools'});
      return '<article class="translation-paper"><strong>'+esc(item.title)+'</strong><p>共 '+item.page_count+' 页 · 本次第 '+item.start+'–'+item.end+' 页 · 已保存 '+count+' 页'+(r?.error?' · 第 '+r.failed_page+' 页：'+esc(r.error):'')+'</p><div class="workspace-links"><a target="_blank" rel="noopener" href="/reader/'+item.paper_id+'?'+q+'#bilingualPanel">打开论文与译文 ↗</a>'+(count?'<a href="/api/papers/'+item.paper_id+'/translations/'+target+'/export">下载已保存的双语文档</a>':'')+'</div></article>';
    }).join('')+'</section>';
    const resume=el('resumeBatchTranslation');if(resume)resume.onclick=()=>start(true);
    refresh();
  }
  async function poll() {
    clearTimeout(timer);if(!job)return;
    const id=job.id;
    try{const result=await context.request('/api/jobs/'+id);if(job?.id!==id)return;job=result;renderJob();if(running())timer=setTimeout(poll,2000);}
    catch(e){el('translationJob').textContent='暂时无法更新进度：'+e.message+'；正在重新连接。';timer=setTimeout(poll,5000);}
  }
  async function start(resume=false) {
    if(submitting)return;submitting=true;let failure='';refresh();
    try {
      let body={},url;
      if(resume)url='/api/jobs/'+job.id+'/resume';
      else {
        const ids=context.selected(),mode=el('translationMode').value;
        plan(context.papers(),ids,mode,el('translateStart').value,el('translateEnd').value);
        body={paper_ids:ids,target:el('documentTarget').value,mode};
        if(mode==='range'){body.start=Number(el('translateStart').value);body.end=Number(el('translateEnd').value);}
        url='/api/library/translate-batch';
      }
      job=await context.request(url,body);renderJob();await poll();
    } catch(e){failure=e.message;}
    finally{submitting=false;refresh();if(failure){el('translationRangeError').textContent=failure;el('translationRangeError').hidden=false;}}
  }
  function mount(options) {
    context=options;
    for(const id of ['translationMode','translateStart','translateEnd'])el(id).addEventListener('input',refresh);
    el('paperChoices').addEventListener('change',refresh);
    el('translateDocument').onclick=()=>start();
    if(new URLSearchParams(location.search).get('tool')==='translation'||new URLSearchParams(location.search).get('tab')==='translation')
      context.request('/api/jobs').then(r=>{if(job||submitting)return;job=r.items.find(j=>j.kind==='translate_batch');if(job){renderJob();if(running())poll();}}).catch(()=>{});
    addEventListener('pageshow',event=>{if(event.persisted&&running())poll();});
  }
  window.TraceTranslation={mount,refresh,plan,stop:()=>clearTimeout(timer)};
})();
