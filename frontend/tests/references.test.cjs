const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(__dirname+'/../assets/workspace.js','utf8');
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const render=vm.runInNewContext(source.slice(source.indexOf('  function referenceLookup('),source.indexOf('  async function copyReferenceText('))+'\nreferenceLookup',{esc});
test('reference lookup renders title, evidence and multiple discovery platforms without navigation',()=>{
 const html=render({text:'A. Author. A scientific title.',lookup:{title:'A scientific title',source_clues:[{name:'IEEE',basis:'条目原文线索',evidence:'IEEE'}],identifiers:[{kind:'DOI',value:'10.1109/test'}],suggested_places:['IEEE Xplore','Google Scholar']}});
 assert.match(html,/可能的题名/);assert.match(html,/IEEE Xplore/);assert.match(html,/DOI：10.1109\/test/);
 assert.match(html,/未联网核验/);assert.match(html,/复制题名/);
 assert.doesNotMatch(html,/<a\b|href=|data-search-reference|用此条目开始检索/);
});
test('unknown references explain missing title and source and copy the original entry',()=>{
 const html=render({text:'Unknown reference'});
 assert.match(html,/未能可靠提取/);assert.match(html,/暂不能判断/);assert.match(html,/复制条目/);
 assert.match(html,/Google Scholar/);assert.doesNotMatch(html,/arXiv|IEEE/);
});
test('document-derived titles and source names remain text and cannot inject HTML',()=>{
 const html=render({text:'" onfocus="bad',lookup:{title:'<img src=x onerror=bad>',source_clues:[{name:'<script>bad</script>',basis:'unknown',evidence:'"bad'}],suggested_places:['<a href="https://bad">bad</a>']}});
 assert.doesNotMatch(html,/<img|<script|<a\b/);assert.match(html,/&lt;img/);assert.match(html,/&quot;bad/);
});
test('copying a reference does not navigate or search and reports a local success/failure',async()=>{
 const copy=source.slice(source.indexOf('  async function copyReferenceText('),source.indexOf("  el('loadReferences').onclick"))+'\ncopyReferenceText';
 for(const failed of [false,true]){
  let copied;const status={textContent:''};
  const run=vm.runInNewContext(copy,{navigator:{clipboard:{writeText:async text=>{if(failed)throw Error('blocked');copied=text;}}}});
  await run({dataset:{copyReference:'A scientific title'},closest:()=>({querySelector:()=>status})});
  assert.equal(copied,failed?undefined:'A scientific title');assert.match(status.textContent,failed?/手动/:/已复制/);
 }
});
