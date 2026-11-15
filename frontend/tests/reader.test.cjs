const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const reader = fs.readFileSync(path.join(__dirname, '../assets/reader.js'), 'utf8');
const app = fs.readFileSync(path.join(__dirname, '../assets/app.js'), 'utf8');
function pollHarness(job, error) {
  const cells = {}, calls = [], timers = [];
  const state = {page:1,ocrPage:null,poll:null};
  const context = {state,paperId:'sample',clearTimeout(){},setTimeout(fn,ms){timers.push(ms);return ms;},
    el:id=>cells[id]||=( {} ),request:async()=>{if(error)throw error;return job;},
    renderOcr:value=>calls.push(['render',value]),refreshText:async()=>calls.push(['text']),refreshPaper:async()=>calls.push(['metadata'])};
  const start=reader.indexOf('  async function pollOcr()');
  const end=reader.indexOf('  async function startOcr()',start);
  const poll=vm.runInNewContext(`${reader.slice(start,end)}\npollOcr`,context);
  return {poll,state,cells,calls,timers};
}
test('OCR refreshes completed current page while other pages still run',async()=>{
  const h=pollHarness({status:'running',remaining_pages:[2,3]});
  await h.poll();
  assert.deepEqual(h.calls.map(c=>c[0]),['render','text']);
  assert.equal(h.state.ocrPage,1);
  assert.deepEqual(h.timers,[2000]);
});
test('OCR completion refreshes metadata and text without scheduling more polls',async()=>{
  const h=pollHarness({status:'done',remaining_pages:[]});
  await h.poll();
  assert.ok(h.calls.some(c=>c[0]==='metadata'));
  assert.deepEqual(h.timers,[]);
});
test('OCR network interruption reconnects without enabling duplicate starts',async()=>{
  const h=pollHarness(null,new Error('offline'));
  await h.poll();
  assert.equal(h.cells.ocrButton.disabled,true);
  assert.deepEqual(h.timers,[5000]);
});
test('OCR stops polling deleted papers',async()=>{
  const error=new Error('不存在');error.status=404;
  const h=pollHarness(null,error);
  await h.poll();
  assert.match(h.cells.ocrDetail.textContent,/返回论文库/);
  assert.deepEqual(h.timers,[]);
});
test('evidence navigation preserves its page and return destination',()=>{
  const start=app.indexOf('  function openPaper('),end=app.indexOf('  function validateUpload(',start);
  let url;
  const open=vm.runInNewContext(`${app.slice(start,end)}\nopenPaper`,{state:{activeView:'research'},URLSearchParams,window:{location:{assign:value=>{url=value;}}}});
  open('paper-id',null,4);
  assert.equal(url,'/reader/paper-id?page=4&from=research');
});
