const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../assets/app.js'), 'utf8');
const start = source.indexOf('  async function deletePaper(');
const end = source.indexOf('\n  function openPaper(', start);
assert.ok(start >= 0 && end > start);

function harness({ confirm = true, failure = false } = {}) {
  const state = { papers: [{ paper_id: 'v1', title: 'Attention', filename: 'old.pdf', version_label: 'v1' }, { paper_id: 'v7' }],
    total: 2, comparisonPaperIds: ['v1', 'v7'], currentPaper: { paper_id: 'v1' }, pendingUpload: {} };
  const cells = {};
  const byId = id => cells[id] ||= { textContent: '' };
  const elements = { researchPaperScope: { value: 'v1' }, evidenceResults: {}, evidenceCount: {} };
  const calls = [], prompts = [], toasts = [];
  let closed = false, refreshed = false;
  const context = { state, elements, byId, window: { confirm: text => { prompts.push(text); return confirm; } },
    paperTitle: paper => paper.title, renderLibrary() {}, renderAll() {}, renderToolPapers() {}, resetUploadPanel() {}, clearAnswer() {},
    closeDrawer() { closed = true; }, loadPapers: async () => { refreshed = true; },
    showToast: (message, type) => toasts.push({ message, type }), friendlyError: error => error.message,
    responseError: async () => new Error('该论文正在 OCR 识别'),
    fetch: async (...args) => { calls.push(args); return { ok: !failure, status: failure ? 409 : 204 }; } };
  return { state, elements, calls, prompts, toasts, get closed() { return closed; }, get refreshed() { return refreshed; },
    deletePaper: vm.runInNewContext(`${source.slice(start, end)}\ndeletePaper`, context) };
}

test('cancel deletion sends no request and keeps all selections', async () => {
  const h = harness({ confirm: false });
  await h.deletePaper('v1');
  assert.equal(h.calls.length, 0);
  assert.equal(h.state.papers.length, 2);
  assert.match(h.prompts[0], /Attention（v1）/);
  assert.match(h.prompts[0], /无法撤销/);
});

test('successful deletion clears only the selected record and updates dependent views', async () => {
  const h = harness();
  await h.deletePaper('v1');
  assert.equal(h.calls[0][0], '/api/papers/v1');
  assert.equal(h.calls[0][1].method, 'DELETE');
  assert.deepEqual(Array.from(h.state.papers, p => p.paper_id), ['v7']);
  assert.deepEqual(Array.from(h.state.comparisonPaperIds), ['v7']);
  assert.equal(h.elements.researchPaperScope.value, '');
  assert.equal(h.state.total, 1);
  assert.equal(h.closed, false);
  assert.equal(h.refreshed, true);
  assert.equal(h.state.deletingPaperId, null);
});

test('OCR conflict leaves record available and allows retry', async () => {
  const h = harness({ failure: true });
  await h.deletePaper('v1');
  assert.equal(h.state.papers.length, 2);
  assert.equal(h.state.total, 2);
  assert.equal(h.closed, false);
  assert.equal(h.state.deletingPaperId, null);
  assert.equal(h.toasts[0].type, 'error');
  assert.match(h.toasts[0].message, /OCR/);
});
