const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const library = fs.readFileSync(path.join(__dirname, '../assets/library-ui.js'), 'utf8');
const app = fs.readFileSync(path.join(__dirname, '../assets/app.js'), 'utf8');
const paginate = vm.runInNewContext(library.slice(library.indexOf('  function paginate('), library.indexOf('  const date =')) + '\npaginate');
const papers = n => Array.from({length:n}, (_, i) => ({paper_id:String(i + 1), title:'Paper ' + (i + 1)}));

test('ten-paper pages cover every record once, in the original order', () => {
  const rows = papers(23);
  const pages = [1, 2, 3].map(page => paginate(rows, page));
  assert.deepEqual(pages.map(page => page.items.length), [10, 10, 3]);
  assert.deepEqual(pages.flatMap(page => Array.from(page.items, p => p.paper_id)), rows.map(p => p.paper_id));
  assert.equal(pages[2].start, 21);
  assert.equal(pages[2].end, 23);
  for (const n of [0, 10, 11, 20, 21]) {
    const last = paginate(papers(n), 999);
    assert.equal(last.totalPages, Math.max(1, Math.ceil(n / 10)));
    assert.equal(last.end, n);
  }
});

function harness(n = 23) {
  const node = () => ({hidden:false, innerHTML:'', textContent:'', dataset:{}, classList:{toggle() {}}});
  const parts = {h3:node(), p:node(), button:node()}, wrap = node();
  const elements = {libraryPagination:node(), libraryEmpty:{...node(), querySelector:s => parts[s]},
    libraryTable:{...node(), closest:() => wrap}};
  const state = {papers:papers(n), libraryPage:1, libraryContext:'', deletingPaperId:null};
  const ctx = {state, elements, query:'', scope:'all:', browse:false, filtered:null,
    searchQuery:() => ctx.query, filteredPapers:() => ctx.filtered ?? state.papers,
    paperTableCells:p => '<td>' + p.paper_id + '</td>', escapeHtml:String, paperTitle:p => p.title};
  ctx.window = {TracePaperUI:{paginate}, TraceLibrary:{scopeKey:() => ctx.scope, render:() => ctx.browse, hasFolder:() => ctx.scope.startsWith('folders:')}};
  const start = app.indexOf('  function renderLibraryPagination('), end = app.indexOf('  function refreshComparisonSelection(', start);
  ctx.render = vm.runInNewContext(app.slice(start, end) + '\nrenderLibrary', ctx);
  return ctx;
}

test('list renders ten rows with correct active page and boundary controls', () => {
  const h = harness(); h.render();
  assert.equal((h.elements.libraryTable.innerHTML.match(/<tr>/g) || []).length, 10);
  assert.match(h.elements.libraryPagination.innerHTML, /data-library-page="0" disabled/);
  assert.match(h.elements.libraryPagination.innerHTML, /data-library-page="1" aria-label="第 1 页" aria-current="page"/);
  h.state.libraryPage = 3; h.render();
  assert.equal((h.elements.libraryTable.innerHTML.match(/<tr>/g) || []).length, 3);
  assert.match(h.elements.libraryPagination.innerHTML, /第 21–23 篇/);
  assert.match(h.elements.libraryPagination.innerHTML, /data-library-page="4" disabled/);
});

test('search and collection changes reset the list to its first page', () => {
  const h = harness(); h.render(); h.state.libraryPage = 3;
  h.query = 'Paper'; h.render(); assert.equal(h.state.libraryPage, 1);
  h.state.libraryPage = 2; h.scope = 'folders:a'; h.render(); assert.equal(h.state.libraryPage, 1);
  h.state.libraryPage = 2; h.scope = 'folders:b'; h.render(); assert.equal(h.state.libraryPage, 1);
  h.browse = true; h.scope = 'folders:'; h.render(); assert.equal(h.elements.libraryPagination.hidden, true);
});

test('removing the last paper on a page clamps to the previous page', () => {
  const h = harness(21); h.render(); h.state.libraryPage = 3;
  h.state.papers.pop(); h.render();
  assert.equal(h.state.libraryPage, 2);
  assert.match(h.elements.libraryPagination.innerHTML, /第 11–20 篇/);
  h.filtered = []; h.render();
  assert.equal(h.state.libraryPage, 1);
  assert.equal(h.elements.libraryPagination.hidden, true);
  assert.equal(h.elements.libraryTable.innerHTML, '');
});
