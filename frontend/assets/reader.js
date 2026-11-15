(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const paperId = location.pathname.split('/').filter(Boolean)[1];
  const params = new URLSearchParams(location.search);
  const state = {paper:null,page:1,request:0,poll:null,fit:true,zoom:100,text:'',translating:false,ocrPage:null};

  async function request(url, options) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), url.endsWith('/translate') ? 120000 : 20000);
    try {
      const response = await fetch(url, {cache:'no-store', ...options, signal:controller.signal});
      if (!response.ok) {
        let message = '请求未完成（' + response.status + '），请稍后重试。';
        try { const data = await response.json(); if (typeof data.detail === 'string') message = data.detail; } catch {}
        const error = new Error(message); error.status = response.status; throw error;
      }
      return await response.json();
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('请求超时，请检查网络后重试。');
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }
  function authors(paper) {
    const names = (paper.authors?.length ? paper.authors : String(paper.author || '').split(/[,;，；\n]+/)).filter(Boolean);
    return names.slice(0,5).join(', ') + (names.length > 5 ? ', etc' : '');
  }
  async function refreshPaper() {
    const paper = await request('/api/papers/' + paperId); state.paper = paper;
    el('readerTitle').textContent = paper.title || paper.filename;
    document.title = (paper.title || paper.filename) + ' · TraceScholar';
    el('readerSubtitle').textContent = [paper.version_label, paper.page_count + ' 页', authors(paper)].filter(Boolean).join(' · ');
    el('pageNumber').max = paper.page_count; el('pageTotal').textContent = '/ ' + paper.page_count;
    const fields = [['原始文件',paper.filename],['作者',authors(paper)||'未识别'],['版本',paper.version_label||'未知'],['文本块',String(paper.chunk_count||0)],['待 OCR',(paper.needs_ocr_pages?.length||0)+' 页'],['arXiv',paper.arxiv_id||'未识别']];
    el('readerMetadata').replaceChildren();
    for (const [label,value] of fields) { const item=document.createElement('div'), name=document.createElement('span'), content=document.createElement('strong'); name.textContent=label; content.textContent=value; item.append(name,content); el('readerMetadata').append(item); }
    el('readerWarnings').textContent = paper.needs_ocr_pages?.length ? '扫描页需完成 OCR 才能读取正文。版本关联可通过文件名中的论文标识判断；没有标识且正文尚未识别时，关联可能漏检。' : '可检索文字已建立索引。OCR 文字可能有误，请以原版为准。';
    const structure = await request('/api/papers/' + paperId + '/structure'), select = el('sectionSelect'), previous=select.value;
    select.replaceChildren(new Option('选择章节',''));
    for (const section of structure.sections||[]) {
      const heading = [section.number, section.title].filter(Boolean).join(' ');
      select.add(new Option(heading+' · 第 '+section.page_start+' 页',section.page_start));
    }
    select.value=previous;
  }
  function fitImage() {
    const image=el('originalPdfImage'), canvas=el('readerCanvas');
    if (!image.naturalWidth||!image.naturalHeight) return;
    const padding=innerWidth<=600?24:36, width=Math.max(1,canvas.clientWidth-padding), height=Math.max(1,canvas.clientHeight-padding);
    const base=state.fit?Math.min(width,height*image.naturalWidth/image.naturalHeight):width;
    image.style.width=Math.round(base*(state.fit?1:state.zoom/100))+'px'; image.style.height='auto';
    canvas.scrollTop=0; canvas.scrollLeft=0;
    el('readerZoomLabel').textContent=state.fit?'整页':state.zoom+'%'; el('fitPage').setAttribute('aria-pressed',String(state.fit));
  }
  async function refreshText(page=state.page) {
    const data=await request('/api/papers/'+paperId+'/pages/'+page); if(page!==state.page)return;
    state.text=data.text||'';
    el('pageText').textContent=state.text.trim()||'本页暂无可检索文字。请启动上方 OCR；处理到本页后，文字会自动更新。';
    el('pageText').classList.toggle('is-empty',!state.text.trim());
    el('textOrigin').textContent=data.text_origin==='ocr'?'OCR 识别':state.text.trim()?'PDF 文字':'待识别';
    el('translateButton').disabled=!state.text.trim()||state.translating;
  }
  async function loadPage(number) {
    if(!state.paper)return;
    const page=Math.min(state.paper.page_count,Math.max(1,Math.trunc(Number(number))||1)), requestId=++state.request;
    state.page=page;state.ocrPage=null;state.text='';
    el('pageNumber').value=page;el('prevPage').disabled=page===1;el('nextPage').disabled=page===state.paper.page_count;
    el('readerPageLabel').textContent='原版页面 · 第 '+page+' 页';
    el('translationSource').value='';el('translationResult').textContent='';el('pageText').textContent='正在读取本页文字…';el('translateButton').disabled=true;
    el('originalPdfImage').hidden=true;el('imageStatus').hidden=false;el('imageStatus').textContent='正在加载原版页面…';
    el('originalPdfImage').src='/api/papers/'+paperId+'/render/'+page;
    const url=new URL(location.href);url.searchParams.set('page',page);history.replaceState(null,'',url);
    try{await refreshText(page);}catch(error){if(requestId===state.request)el('pageText').textContent=error.message;}
  }
  function renderOcr(job) {
    const remaining=job.remaining_pages||[], active=job.status==='running';
    el('ocrPanel').hidden=!remaining.length&&job.status==='idle';el('ocrButton').disabled=active;el('ocrButton').hidden=!remaining.length&&!active;
    el('ocrButton').textContent=job.status==='idle'?'开始 OCR 识别':'继续 / 重试 OCR';
    el('ocrProgress').max=Math.max(1,job.total||remaining.length);el('ocrProgress').value=job.processed||0;
    const phase={preparing:'正在准备识别引擎',rendering:'正在准备第 '+job.current_page+' 页图片',recognizing:'正在识别第 '+job.current_page+' 页',indexing:'正在更新检索索引'}[job.phase]||'正在处理';
    const label={done:'OCR 已完成',partial:'部分页面未识别',failed:'OCR 未完成',interrupted:'任务已中断'}[job.status]||job.status;
    el('ocrStatus').textContent=active?phase+' · 已处理 '+(job.processed||0)+'/'+job.total+' 页，成功 '+(job.completed_pages?.length||0)+' 页':job.status==='idle'?remaining.length+' 页扫描文字待识别':label+' · 成功 '+(job.completed_pages?.length||0)+' 页，剩余 '+remaining.length+' 页';
    const details=[job.message,...(job.failed_pages||[]).slice(0,3).map(p=>'第 '+p.page+' 页：'+p.message)].filter(Boolean);
    if(active)details.push('服务端运行 '+Math.round(job.elapsed_seconds||0)+' 秒；可离开阅读页，返回后查看进度。');
    if(active&&job.stalled)details.push('本页耗时较长，正在等待引擎结果；若服务重启，会提示继续识别。');
    el('ocrDetail').textContent=details.join('\n')||'OCR 在服务端运行，不调用大模型；识别后的文字可能有误，请与原版核对。';
  }
  async function pollOcr() {
    clearTimeout(state.poll);
    try {
      const job=await request('/api/papers/'+paperId+'/ocr');renderOcr(job);
      if(!job.remaining_pages?.includes(state.page)&&state.ocrPage!==state.page){await refreshText();state.ocrPage=state.page;}
      if(job.status==='running')state.poll=setTimeout(pollOcr,2000);
      else if(job.status!=='idle'){await refreshPaper();await refreshText();}
    } catch(error) {
      el('ocrPanel').hidden=false;el('ocrStatus').textContent='无法更新识别状态：'+error.message;
      if (error.status===404 || error.status===401) {
        el('ocrDetail').textContent=error.status===404?'该论文已不存在，请返回论文库。':'登录状态已失效，请刷新页面重新登录。';
        el('ocrButton').disabled=true;return;
      }
      el('ocrDetail').textContent='识别可能仍在服务端进行，正在尝试重新连接；请勿重复启动任务。';el('ocrButton').disabled=true;
      state.poll=setTimeout(pollOcr,5000);
    }
  }
  async function startOcr() {
    el('ocrButton').disabled=true;el('ocrStatus').textContent='正在启动识别任务…';
    try{await request('/api/papers/'+paperId+'/ocr',{method:'POST'});await pollOcr();}
    catch(error){el('ocrStatus').textContent=error.message;el('ocrButton').disabled=false;}
  }
  async function translateParagraph() {
    if(state.translating)return;
    const selection=getSelection(), selected=selection&&el('pageText').contains(selection.anchorNode)?selection.toString().trim():'';
    const text=selected||el('translationSource').value.trim(),page=state.page;
    if(!text){el('translationResult').textContent='请先选中或粘贴本页连续原文。';return;}
    el('translationSource').value=text;el('translateButton').disabled=true;state.translating=true;el('translationResult').textContent='正在翻译…';
    try{const result=await request('/api/papers/'+paperId+'/translate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({page,text,target:el('translationTarget').value})});if(state.page===page)el('translationResult').textContent=result.translation;}
    catch(error){if(state.page===page)el('translationResult').textContent=error.message;}
    finally{state.translating=false;el('translateButton').disabled=!state.text.trim();}
  }
  async function initialize() {
    const labels={overview:'工作台',library:'论文库',research:'证据检索',tools:'研究工具',import:'导入页面'};
    const from=Object.hasOwn(labels,params.get('from'))?params.get('from'):'library';
    el('readerBack').href='/?view='+from;el('readerBack').textContent='← 返回'+labels[from];
    el('originalPdfLink').href='/api/papers/'+paperId+'/source.pdf';
    el('originalPdfImage').addEventListener('load',()=>{el('originalPdfImage').hidden=false;el('imageStatus').hidden=true;fitImage();});
    el('originalPdfImage').addEventListener('error',()=>{el('imageStatus').hidden=false;el('imageStatus').textContent='原版预览暂未加载，请重试翻页或打开原版 PDF。';});
    el('fitPage').addEventListener('click',()=>{state.fit=true;fitImage();});
    el('readerZoom').addEventListener('input',event=>{state.fit=false;state.zoom=Number(event.target.value);fitImage();});
    new ResizeObserver(fitImage).observe(el('readerCanvas'));
    el('prevPage').addEventListener('click',()=>loadPage(state.page-1));el('nextPage').addEventListener('click',()=>loadPage(state.page+1));
    el('pageNumber').addEventListener('change',event=>loadPage(event.target.value));
    el('pageNumber').addEventListener('keydown',event=>{if(event.key==='Enter')loadPage(event.target.value);});
    el('sectionSelect').addEventListener('change',event=>{if(event.target.value)loadPage(event.target.value);});
    el('ocrButton').addEventListener('click',startOcr);el('translateButton').addEventListener('click',translateParagraph);
    el('pageText').addEventListener('mouseup',()=>{const selection=getSelection();if(selection?.toString().trim())el('translationSource').value=selection.toString().trim();});
    addEventListener('pagehide',()=>clearTimeout(state.poll));
    addEventListener('pageshow',event=>{if(event.persisted)pollOcr();});
    try{await refreshPaper();await loadPage(params.get('page')||1);await pollOcr();}
    catch(error){el('readerError').textContent='论文读取未完成：'+error.message;el('readerError').classList.remove('is-hidden');el('readerTitle').textContent='暂时无法打开论文';}
  }
  initialize();
})();
