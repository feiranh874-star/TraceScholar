const assert=require('node:assert/strict');
const test=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../assets/app.js'),'utf8');
const start=source.indexOf('  function markdownTableCells('),end=source.indexOf('  function renderAnswer(payload)',start);
const escapeHtml=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const render=vm.runInNewContext(source.slice(start,end)+'\nrenderAnswerContent',{escapeHtml});
test('model table cells remain text and render a real accessible table',()=>{
 const html=render('| Model | BLEU |\n|---|---|\n| <img src=x onerror=alert(1)> | 27.3 |');
 assert.match(html,/<table/);assert.match(html,/<th>Model<\/th>/);assert.match(html,/27.3/);assert.ok(!html.includes('<img'));assert.match(html,/&lt;img/);
});
test('empty and missing cells do not invent numeric values',()=>{
 const html=render('| A | B |\n|---|---|\n| Base | |\n| Big | 28.4 |');
 assert.match(html,/<td>Base<\/td><td><\/td>/);assert.match(html,/28.4/);
});
