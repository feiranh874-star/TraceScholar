const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../assets/library-ui.js'), 'utf8');
const start = source.indexOf('  function matches('), end = source.indexOf('  const date =', start);
const helpers = vm.runInNewContext(source.slice(start,end) + '\n({matches,recent,scopeSearch})');

test('paper lookup finds mixed language notes, title, filename and authors', () => {
  const p = {title:'Attention Is All You Need',filename:'1706.03762v7.pdf',authors:['Ashish Vaswani'],notes:'老师推荐：注意力机制入门'};
  for(const q of ['老师推荐','  ATTENTION  ','Vaswani','1706.03762']) assert.ok(helpers.matches(p,q),q);
  assert.equal(helpers.matches(p,'CLIP'),false);
  assert.equal(helpers.matches({},'missing'),false);
});
test('paper selection sorts by import time and does not mutate library data', () => {
  const original = [{paper_id:'first',created_at:'2026-11-14T10:00:00Z'}, {paper_id:'latest',created_at:'2026-11-16T10:00:00Z'}, {paper_id:'middle',created_at:'2026-11-15T10:00:00Z'}];
  assert.deepEqual(Array.from(helpers.recent(original),p=>p.paper_id),['latest','middle','first']);
  assert.deepEqual(original.map(p=>p.paper_id),['first','latest','middle']);
});

test('a numeric collection name finds all six member papers once in newest-first order', () => {
  const members=Array.from({length:6},(_,i)=>({paper_id:'p'+i,title:'Research '+i,created_at:'2026-11-'+String(i+1).padStart(2,'0'),collection_ids:['c12']}));
  const unrelated={paper_id:'outside',title:'Unrelated research',created_at:'2026-11-30'};
  const result=helpers.scopeSearch([...members,unrelated],[{id:'c12',name:'12',paper_ids:members.map(p=>p.paper_id)}],' 12 ');
  assert.equal(result.folders.length,1);
  assert.deepEqual(Array.from(result.papers,p=>p.paper_id),['p5','p4','p3','p2','p1','p0']);
  assert.equal(helpers.scopeSearch(members,[{id:'empty',name:'Empty',paper_ids:[]}],'empty').papers.length,0);
});
test('direct paper matching still works and a renamed folder uses its current name', () => {
  const papers=[{paper_id:'p1',title:'Attention paper',collection_ids:['c1']},{paper_id:'p2',notes:'read next'}];
  assert.deepEqual(Array.from(helpers.scopeSearch(papers,[{id:'c1',name:'新名字',paper_ids:['p1']}],'新名字').papers,p=>p.paper_id),['p1']);
  assert.equal(helpers.scopeSearch(papers,[{id:'c1',name:'新名字'}],'旧名字').papers.length,0);
  assert.deepEqual(Array.from(helpers.scopeSearch(papers,[],'read next').papers,p=>p.paper_id),['p2']);
});
