const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../assets/library-ui.js'), 'utf8');
const start = source.indexOf('  function matches('), end = source.indexOf('  const date =', start);
const helpers = vm.runInNewContext(source.slice(start,end) + '\n({matches,recent})');

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
