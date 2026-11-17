const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../assets/vision-ui.js'), 'utf8');

class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.isConnected = true; }
  append(...nodes) { this.children.push(...nodes); }
  setAttribute(key, value) { this.attrs[key] = value; }
  replaceChildren(...nodes) { this.children = nodes; }
}
function harness(replies = {}) {
  const calls = [];
  const context = {window:{}, document:{createElement:tag => new Element(tag)}, addEventListener(){},
    fetch:async (url, options) => { calls.push({url, options}); return {ok:true, json:async () => replies[url]}; },
    setTimeout(){}, clearTimeout(){}, URLSearchParams};
  vm.runInNewContext(source, context);
  return {api:context.window.TraceVision, calls};
}
test('vision table preserves blanks and merges without interpreting model HTML', () => {
  const {api} = harness();
  const wrap = api.table({rows:[['group', 'BLEU'], ['<img src=x>', '25.8'], [null, null]], merges:[{row:1, column:0, rowspan:2, colspan:1}]});
  const table = wrap.children[0], head = table.children[0], body = table.children[1];
  assert.equal(head.children[0].children[0].scope, 'col');
  assert.equal(body.children[0].children[0].textContent, '<img src=x>');
  assert.equal(body.children[0].children[0].children.length, 0);
  assert.equal(body.children[0].children[0].rowSpan, 2);
  assert.equal(body.children[1].children.length, 1);
  assert.equal(body.children[1].children[0].textContent, '');
  assert.equal(wrap.tabIndex, 0);
});
test('opening vision panel only reads status/cache/jobs and never starts a paid request', async () => {
  const {api, calls} = harness({'/api/vision/status':{configured:false}, '/api/papers/paper/vision/9':{result:null}, '/api/jobs':{items:[]}});
  const target = new Element('div'); api.mount(target, 'paper', 9);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.length, 3);
  assert.ok(calls.every(call => !call.options.method));
  const panel = target.children[0], button = panel.children[2].children[0];
  assert.equal(button.disabled, true);
  assert.match(panel.children[3].textContent, /VISION_API_KEY/);
});

test('local analysis failures keep the independent vision entry and coalesce concurrent page refreshes', async () => {
  const reader = fs.readFileSync(path.join(__dirname, '../assets/reader-figures.js'), 'utf8');
  const start = reader.indexOf('  async function analyze('), end = reader.indexOf("  el('showPageFigures').onclick", start);
  const cells = {}, mounts = [], calls = [];
  let release;
  const pending = new Promise(resolve => {release = resolve;});
  const context = {generation:0, loadedPage:null, pendingPage:null, paperId:'paper', page:()=>9,
    el:id=>cells[id] ||= new Element('div'), node:(tag,text)=>Object.assign(new Element(tag),{textContent:text}),
    window:{TraceVision:{mount:(host,id,p)=>mounts.push([host,id,p])}},
    fetch:async()=>{calls.push(1);await pending;return {ok:false,status:429,json:async()=>({detail:'busy'})};}};
  const analyze = vm.runInNewContext(reader.slice(start,end)+'\nanalyze',context);
  const first = analyze(); await analyze();
  assert.equal(calls.length,1); assert.equal(mounts.length,1);
  release(); await first;
  assert.equal(cells.pageFiguresResult.children[0],mounts[0][0]);
  assert.equal(cells.reloadPageFigures.disabled,false);
  assert.match(cells.pageFiguresResult.children[1].textContent,/另一个页面/);
});
