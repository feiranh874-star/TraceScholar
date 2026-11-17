const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(__dirname+'/../assets/tools-nav.js','utf8');
const home=fs.readFileSync(__dirname+'/../index.html','utf8');
const workspace=fs.readFileSync(__dirname+'/../workspace.html','utf8');
function cell(){return {hidden:false,textContent:'',value:'',closest:()=>null,classList:{add(){},toggle(){}}};}
function load(query=''){
 const cells={},cards={},selectionIntro={querySelector:()=>cell()};
 const document={body:cell(),title:'',getElementById:id=>cells[id]||=(cell()),querySelectorAll:()=>[],querySelector:selector=>selector==='[data-sidebar-collapse]'?null:cell()};
 document.body.classList.contains=()=>false;
 const window={};vm.runInNewContext(source,{window,document,location:{search:query},URLSearchParams,matchMedia:()=>({matches:false})});
 return {api:window.TraceTools,document,cells,cards,selectionIntro};
}
test('all tools have unique independently addressable pages and real controls',()=>{
 const {api}=load();const ids=api.tools.map(t=>t.id);
 assert.equal(new Set(ids).size,19);
 for(const tool of api.tools){
  const html=tool.kind==='home'?home:workspace;
  assert.ok(html.includes('id="'+tool.control+'"'),tool.id+' control exists');
  const url=new URL(api.href(tool),'https://example.test');
  assert.equal(url.searchParams.get('tool'),tool.id);
  if(tool.kind==='workspace')assert.ok(html.includes('data-panel="'+tool.panel+'"'));
 }
});
test('every sidebar tool opens a separate tab with its own link',()=>{
 const h=load('?tool=online');const host=cell();
 h.document.querySelectorAll=selector=>selector==='[data-tools-navigation]'?[host]:[];
 h.api.mount();
 assert.equal((host.innerHTML.match(/target="_blank"/g)||[]).length,20);
 assert.ok(host.innerHTML.includes('rel="noopener"'));
 assert.ok(host.innerHTML.includes('<details'));
 assert.ok(host.innerHTML.includes('aria-current="page"'));
});
test('tool groups are independently collapsible and only the current group opens initially',()=>{
 for(const query of ['', '?tool=online', '?tool=references']){
  const h=load(query),host=cell();
  h.document.querySelectorAll=selector=>selector==='[data-tools-navigation]'?[host]:[];
  h.api.mount();
  const groups=[...host.innerHTML.matchAll(/<details class="tools-nav-group"( open)?><summary>([^<]+)/g)];
  assert.equal(groups.length,5);
  assert.equal(groups.filter(group=>group[1]).length,query?1:0);
  if(query)assert.equal(groups.find(group=>group[1])[2],query.includes('online')?'查找与整理':'阅读与核对');
 }
});
test('workspace pages show only their own cards and the required paper controls',()=>{
 const base=load();
 const tools=base.api.tools.filter(t=>t.kind==='workspace');
 for(const tool of tools){
  const h=load('?tool='+tool.id);
  const cards=tools.map(t=>({id:t.control,hidden:false}));
  h.document.querySelectorAll=selector=>selector==='[data-panel] .workspace-card'?cards:[];
  h.document.querySelector=selector=>selector==='.workspace-selection>div'?h.selectionIntro:(h.cells[selector]||=cell());
  for(const item of tools)h.document.getElementById(item.control).closest=()=>cards.find(c=>c.id===item.control);
  h.document.getElementById('activePage').closest=()=>h.cells.pageLabel||=cell();
  assert.equal(h.api.applyWorkspace(),true);
  assert.equal(cards.find(c=>c.id===tool.control).hidden,false,tool.id);
  assert.ok(cards.filter(c=>!c.hidden).every(c=>[tool.control,...(tool.extra||[])].includes(c.id)),tool.id);
  assert.equal(h.cells['.workspace-selection'].hidden,tool.selection==='none',tool.id);
  assert.equal(h.cells['paperChoices'].hidden,tool.selection!=='multi',tool.id);
  assert.equal(h.cells['.workspace-tabs'].hidden,true);
 }
});
test('legacy URLs remain unfocused instead of hiding their original controls',()=>{
 const h=load('?tab=discovery');assert.equal(h.api.applyWorkspace(),false);
});

test('sidebar can collapse and expand, restores the preference, and works when storage is unavailable',()=>{
 const code=source.slice(source.indexOf('  function initSidebar()'),source.indexOf('  function navigation()'))+'\ninitSidebar';
 for(const blocked of [false,true]){
  const classes=new Set(),attributes={},saved={};
  const button={setAttribute:(key,value)=>{attributes[key]=value;}};
  const storage={getItem(){if(blocked)throw Error('blocked');return 'true';},setItem(key,value){if(blocked)throw Error('blocked');saved[key]=value;}};
  const init=vm.runInNewContext(code,{document:{querySelector:()=>button,body:{classList:{toggle:(name,on)=>on?classes.add(name):classes.delete(name),contains:name=>classes.has(name)}}},localStorage:storage});
  init();
  assert.equal(classes.has('sidebar-is-collapsed'),!blocked);
  button.onclick();assert.equal(attributes['aria-expanded'],blocked?'false':'true');
  button.onclick();assert.equal(attributes['aria-label'],blocked?'收起侧边栏':'展开侧边栏');
  if(!blocked)assert.equal(saved['tracescholar-sidebar-collapsed'],'true');
 }
});
