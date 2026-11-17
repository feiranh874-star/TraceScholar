const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/../assets/app.js', 'utf8');
function extract(start, end) { return source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start))); }
function cell(value = '') { return {value, hidden: true, textContent: '', innerHTML: '', focus(){this.focused=true;}, setAttribute(k,v){this[k]=v;}}; }
function harness() {
  const cells = Object.fromEntries(['arxivQuery','arxivError','outlineIdea','outlineError','researchQuestion','researchError','searchMentions'].map(id=>[id,cell()]));
  let calls=[];
  const elements = {researchQuestion:cells.researchQuestion,evidenceCount:cell(),evidenceResults:cell()};
  const context = {byId:id=>cells[id],elements,state:{retrieving:false},clearAnswer(){},renderResearchScope(){},escapeHtml:String,displaySectionTitle:String,friendlyError:e=>e.message,responseError:async()=>new Error('失败'),
    fetch: async(url,opts)=>{const body=JSON.parse(opts.body);calls.push(body);return {ok:true,json:async()=>({question:body.question,total_papers:13,scanned_papers:15,page:body.page,total_pages:2,notice:'正文匹配',items:[]})};},runTool:async()=>{calls.push('tool');}};
  const handlers = vm.runInNewContext(extract('  let mentionQuestion', '  async function retrieveEvidence') + '\n' + extract('  async function searchArxiv()', '  async function importArxiv') + '\n' + extract('  async function createResearchOutline(', '  async function searchArxiv()') + '\n({searchLibraryMentions,searchArxiv,createResearchOutline})', context);
  return {cells,calls,elements,handlers};
}
test('blank arXiv and outline submissions show inline Chinese errors without requests',async()=>{
  const h=harness();h.cells.arxivQuery.value='  ';
  await h.handlers.searchArxiv();await h.handlers.createResearchOutline(false);
  for(const id of ['arxivError','outlineError']){assert.equal(h.cells[id].textContent,'输入不能为空');assert.equal(h.cells[id].hidden,false);}
  assert.equal(h.calls.length,0);
});
test('global result pagination retains the submitted concept after input changes',async()=>{
  const h=harness();h.cells.researchQuestion.value='attention';
  await h.handlers.searchLibraryMentions();h.cells.researchQuestion.value='changed question';await h.handlers.searchLibraryMentions(2);
  assert.equal(h.calls.length,2);assert.equal(h.calls[1].question,'attention');assert.equal(h.calls[1].page,2);
  assert.match(h.elements.evidenceCount.textContent,/13 篇/);assert.match(h.elements.evidenceResults.innerHTML,/下一页/);
});
test('global empty search and duplicate in-flight click do not send requests',async()=>{
  const h=harness();await h.handlers.searchLibraryMentions();assert.equal(h.calls.length,0);assert.equal(h.cells.researchError.textContent,'输入不能为空');
});
test('validation arrays and objects never become object Object',()=>{
  const localize=vm.runInNewContext(extract('  function localizeApiError(', '  function friendlyError(')+'\nlocalizeApiError');
  assert.match(localize([{loc:['body','query'],msg:'too short'}],422),/输入内容/);
  assert.match(localize({unexpected:true},400),/请求参数/);
  assert.equal(localize('明确错误',400),'明确错误');
});
