(() => {
  'use strict';
  const tools = [
    {id:'online', name:'在线找论文', group:'查找与整理', kind:'home', control:'searchArxiv', selection:'none', description:'输入英文题名、arXiv 编号或链接，找到公开论文并确认导入。'},
    {id:'recommend', name:'本地论文推荐', group:'查找与整理', kind:'home', control:'recommendPapers', selection:'multi', description:'选一篇已入库论文，在你的资料库中发现相关工作。'},
    {id:'tracking', name:'主题追踪', group:'查找与整理', kind:'workspace', panel:'discovery', control:'addTracking', selection:'none', description:'填写主题关键词，定期检查 arXiv 上的新论文。'},
    {id:'code', name:'论文代码仓库线索', group:'查找与整理', kind:'workspace', panel:'discovery', control:'loadCodeLinks', selection:'single', description:'从目标论文的原文中寻找代码仓库链接，打开前仍需核对。'},
    {id:'layout', name:'图表与公式识别', group:'阅读与核对', kind:'workspace', panel:'layout', control:'analyzePage', selection:'page', description:'选择论文和原始页码，对照原图查看表格、图片和公式。'},
    {id:'references', name:'参考文献', group:'阅读与核对', kind:'workspace', panel:'layout', control:'loadReferences', selection:'single', description:'查看目标论文的真实参考文献条目与正文引用上下文。'},
    {id:'versions', name:'论文版本比较', group:'阅读与核对', kind:'workspace', panel:'versions', control:'compareVersions', selection:'none', description:'选择同一论文的两个版本，查看正文变化和来源页码。'},
    {id:'translation', name:'全文翻译', group:'阅读与核对', kind:'workspace', panel:'translation', control:'translateDocument', selection:'page', description:'选择论文和翻译页范围，查看或下载保存的双语内容。'},
    {id:'graph', name:'引用图谱', group:'研究与写作', kind:'home', control:'buildGraph', selection:'multi', description:'勾选论文，查看资料库中的真实引用关系。'},
    {id:'outline', name:'研究提纲与初稿', group:'研究与写作', kind:'home', control:'planOutline', selection:'multi', description:'选择最多 8 篇论文，填写研究想法，整理有来源的提纲和初稿。'},
    {id:'agent', name:'分步研究助手', group:'研究与写作', kind:'workspace', panel:'agent', control:'runAgent', extra:['loadRuns'], selection:'multi', description:'勾选论文并提出问题，让助手分步查资料，查看执行记录与来源。'},
    {id:'review', name:'文献综述与时间线', group:'研究与写作', kind:'workspace', panel:'review', control:'collectReview', selection:'multi', description:'选择论文和研究主题，整理图谱、Future Work 与带引用综述。'},
    {id:'claim', name:'研究方向核对', group:'研究与写作', kind:'workspace', panel:'review', control:'collectClaim', selection:'multi', description:'用所选论文的原文证据核对研究方向，查看已有成果和不足。'},
    {id:'diagram', name:'研究架构图', group:'图表与数据', kind:'workspace', panel:'review', control:'buildDiagram', selection:'none', description:'填写方法节点和连线，生成可编辑的研究架构图脚本。'},
    {id:'chart', name:'CSV 图表与图注', group:'图表与数据', kind:'home', control:'buildChart', selection:'none', description:'上传自己的实验 CSV，生成图表、图注与可复现绘图脚本。'},
    {id:'metadata', name:'论文信息与重新解析', group:'资料与任务', kind:'workspace', panel:'versions', control:'saveMetadata', selection:'single', description:'纠正题名、作者和摘要，或重新解析目标论文。'},
    {id:'archives', name:'版本归档恢复', group:'资料与任务', kind:'workspace', panel:'versions', control:'loadArchives', selection:'none', description:'查看被替换版本的归档记录，按需恢复到论文库。'},
    {id:'batch', name:'批量导入', group:'资料与任务', kind:'workspace', panel:'jobs', control:'uploadBatch', extra:['refreshJobs'], selection:'none', description:'一次上传多篇 PDF，并查看解析进度、版本冲突和失败记录。'},
    {id:'jobs', name:'后台任务', group:'资料与任务', kind:'workspace', panel:'jobs', control:'refreshJobs', selection:'none', description:'查看长任务进度，继续失败或中断的任务。'},
  ];
  const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const href = tool => tool.kind === 'home' ? '/?view=tools&tool='+tool.id : '/workspace?tab='+tool.panel+'&tool='+tool.id;
  function current() { return tools.find(t => t.id === new URLSearchParams(location.search).get('tool')); }
  function navigation() {
    const selected = current();
    const groups = [...new Set(tools.map(t => t.group))];
    return '<details class="tools-navigation" open><summary><span aria-hidden="true">◇</span>研究工具<span class="tools-nav-chevron" aria-hidden="true">⌄</span></summary><nav aria-label="研究工具"><a class="tools-catalog-link" href="/?view=tools" target="_blank" rel="noopener">全部工具 <span aria-hidden="true">↗</span></a>'+groups.map(group=>'<div class="tools-nav-group"><span>'+group+'</span>'+tools.filter(t=>t.group===group).map(t=>'<a href="'+href(t)+'" target="_blank" rel="noopener"'+(selected?.id===t.id?' aria-current="page"':'')+'>'+t.name+'<span aria-hidden="true">↗</span></a>').join('')+'</div>').join('')+'</nav></details>';
  }
  function mount() {
    document.querySelectorAll('[data-tools-navigation]').forEach(host => {
      host.innerHTML=navigation();
      if(document.body.classList.contains('has-tool-sidebar') && matchMedia('(max-width:960px)').matches) host.querySelector('details').open=false;
    });
    document.querySelectorAll('[data-tools-catalog]').forEach(host => {
      host.innerHTML=[...new Set(tools.map(t=>t.group))].map(group=>'<section class="tool-catalog-group"><h3>'+group+'</h3><div class="tool-catalog-grid">'+tools.filter(t=>t.group===group).map(t=>'<a class="tool-catalog-card" href="'+href(t)+'" target="_blank" rel="noopener"><strong>'+t.name+'<span aria-hidden="true">↗</span></strong><p>'+esc(t.description)+'</p></a>').join('')+'</div></section>').join('');
    });
  }
  function applyHome() {
    const tool=current(), focused=tool?.kind==='home';
    const host=document.getElementById('view-tools');
    if(!host)return;
    host.classList.toggle('is-focused-tool',focused);
    host.querySelector('[data-tools-catalog]').hidden=focused;
    host.querySelector('.tools-selection').hidden=!focused || tool.selection==='none';
    host.querySelector('.tool-grid').hidden=!focused;
    host.querySelectorAll('.tool-panel').forEach(card=>{card.hidden=!focused || !card.querySelector('#'+tool.control);});
    document.getElementById('toolPageTitle').textContent=focused?tool.name:'研究工具';
    document.getElementById('toolPageDescription').textContent=focused?tool.description:'从左侧展开工具，或在下方选择。每个工具会在新标签页独立打开。';
    if(focused){
      if(tool.id==='online' && !document.getElementById('arxivQuery').value) document.getElementById('arxivQuery').value=new URLSearchParams(location.search).get('query')||'';
      document.getElementById('pageTitle').textContent=tool.name;
      document.title=tool.name+' · TraceScholar';
      const hint=host.querySelector('.tools-selection .tool-hint');
      hint.textContent=tool.id==='recommend'?'请选择 1 篇论文作为推荐起点。':tool.id==='outline'?'最多选择 8 篇。整理提纲不调用模型，扩写初稿按模型实际用量计费。':'最多选择 30 篇，构建库内引用关系，不调用模型。';
    }
  }
  function applyWorkspace(tool=current()) {
    if(tool?.kind!=='workspace')return false;
    document.body.classList.add('is-focused-workspace');
    document.querySelector('.workspace-header h1').textContent=tool.name;
    document.querySelector('.workspace-header p').textContent=tool.description;
    document.title=tool.name+' · TraceScholar';
    document.querySelectorAll('[data-panel]').forEach(panel=>panel.classList.toggle('is-active',panel.dataset.panel===tool.panel));
    const cards=[tool.control,...(tool.extra||[])].map(id=>document.getElementById(id)?.closest('.workspace-card'));
    document.querySelectorAll('[data-panel] .workspace-card').forEach(card=>{card.hidden=!cards.includes(card);});
    document.querySelectorAll('.workspace-task-guide').forEach(guide=>{guide.hidden=true;});
    document.querySelector('.workspace-selection').hidden=tool.selection==='none';
    document.getElementById('paperChoices').hidden=tool.selection!=='multi';
    document.getElementById('workspacePaperSearch').hidden=tool.selection!=='multi';
    document.querySelector('.workspace-target-row').hidden=!['single','page'].includes(tool.selection);
    document.getElementById('activePage').closest('label').hidden=tool.selection!=='page';
    const intro=document.querySelector('.workspace-selection>div');
    intro.querySelector('h2').textContent=tool.selection==='multi'?'选择研究论文':'选择目标论文';
    intro.querySelector('p').textContent=tool.selection==='multi'?'勾选本次任务需要使用的已入库论文。':'从论文库选择需要处理的论文。';
    document.querySelector('.workspace-beginner').hidden=true;
    document.querySelector('.workspace-tabs').hidden=true;
    document.getElementById('reloadLibrary').hidden=tool.selection==='none';
    return true;
  }
  window.TraceTools={tools,href,current,mount,applyHome,applyWorkspace};
  mount();
})();
