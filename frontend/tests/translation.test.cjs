const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const batch=fs.readFileSync(__dirname+'/../assets/translation-batch.js','utf8');
const reader=fs.readFileSync(__dirname+'/../assets/reader.js','utf8');
function planner(){const window={};vm.runInNewContext(batch,{window});return window.TraceTranslation.plan;}
const papers=[{paper_id:'a',title:'短论文',page_count:2},{paper_id:'b',title:'长论文',page_count:15}];
test('batch all-pages mode uses each paper total, instead of reusing the first paper total',()=>{
 const plan=planner()(papers,['a','b'],'all','','');
 assert.deepEqual(Array.from(plan,p=>[p.paper_id,p.start,p.end]),[['a',1,2],['b',1,15]]);
});
test('batch range identifies the shorter paper and its actual maximum',()=>{
 const plan=planner();
 for(const [start,end] of [['1','20'],['','1'],['2','1'],['1',''],['1.5','2']])assert.throws(()=>plan(papers,['a','b'],'range',start,end),/共 2 页，可填写 1–2/);
 assert.deepEqual(Array.from(plan(papers,['b','a'],'range','2','2'),p=>[p.start,p.end]),[[2,2],[2,2]]);
 assert.throws(()=>plan(papers,[],'range',1,1),/勾选论文/);
 assert.throws(()=>plan(papers,['deleted'],'all'),/刷新资料/);
});
function readerHarness(){
 const cells={},state={page:3,text:'Original paragraph',translationVersion:0,translationMode:'page',translating:false};
 const el=id=>cells[id]||=( {value:id==='translationTarget'?'zh':id==='translationSource'?'Original paragraph':'',textContent:'',contains:()=>false} );
 let resolve,requestData;
 const context={state,el,paperId:'paper',getSelection:()=>null,request:(url,options)=>{requestData={url,options};return new Promise(r=>resolve=r);}};
 const slice=reader.slice(reader.indexOf('  async function refreshSavedTranslation()'),reader.indexOf('  function renderTranslationJob'));
 const api=vm.runInNewContext(slice+'\n({refreshSavedTranslation,translateParagraph})',context);
 return {api,cells,state,el,resolve:value=>resolve(value),requestData:()=>requestData};
}
test('paragraph translation keeps source page and language and never navigates away',async()=>{
 const h=readerHarness(),pending=h.api.translateParagraph();
 assert.deepEqual(JSON.parse(h.requestData().options.body),{page:3,text:'Original paragraph',target:'zh'});
 assert.equal(h.requestData().url,'/api/papers/paper/translate');
 h.resolve({translation:'译文'});await pending;
 assert.equal(h.el('translationResult').textContent,'译文');assert.equal(h.state.page,3);
});
test('a slow paragraph response cannot replace the next page or a changed language',async()=>{
 const h=readerHarness(),pending=h.api.translateParagraph();
 h.state.page=4;h.state.translationVersion++;h.el('translationResult').textContent='第4页译文';
 h.resolve({translation:'第3页过期译文'});await pending;
 assert.equal(h.el('translationResult').textContent,'第4页译文');
 const pending2=h.api.refreshSavedTranslation();h.state.translationVersion++;h.el('translationTarget').value='en';h.el('translationResult').textContent='英文译文';
 h.resolve({translation:'过期中文译文'});await pending2;
 assert.equal(h.el('translationResult').textContent,'英文译文');
});
test('whole page with more than 8000 characters uses the page action instead of paragraph API',async()=>{
 const h=readerHarness();h.el('translationSource').value='x'.repeat(8001);
 await h.api.translateParagraph();assert.equal(h.requestData(),undefined);assert.match(h.el('translationResult').textContent,/翻译当前整页/);
});
