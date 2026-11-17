const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../assets/app.js"), "utf8");
const start = source.indexOf("  async function generateAnswer()");
const end = source.indexOf("\n  function renderAll()", start);
assert.ok(start >= 0 && end > start);

function createHarness(failure, count = 2) {
  const cell = () => ({ textContent: "", innerHTML: "", disabled: false });
  const button = () => {
    const span = cell();
    return { disabled: false, querySelector: () => span };
  };
  const state = { papers: [{ paper_id: "clip" }, { paper_id: "gpt3" }], answering: false };
  const elements = {
    researchQuestion: { value: "比较 CLIP 和 GPT-3", focus() {} },
    researchSubmit: button(), researchAnswer: button(), researchCompare: button(),
    researchPaperScope: { value: "clip" },
    comparisonPaperList: { querySelectorAll: () => Array.from({length:count},(_,i)=>({value:"paper-"+i})) },
    answerPanel: { classList: { remove() {} } },
    answerModel: cell(), answerResult: cell(), answerCitations: cell(),
    agentTrace: {}, agentSteps: cell(), evidenceCount: cell(), evidenceResults: cell(),
  };
  const toasts = [];
  const requests = [];
  const context = {
    state, elements,
    clearAnswer() {},
    renderResearchScope() {
      elements.researchAnswer.disabled = state.answering;
      elements.researchCompare.disabled = state.answering;
    },
    showToast: (message) => toasts.push(message),
    friendlyError: (error) => error.message,
    escapeHtml: (value) => value.replaceAll("<", "&lt;").replaceAll(">", "&gt;"),
    responseError: async () => new Error("模型回答未完成 <retry>"),
    fetch: async (url, options) => {
      requests.push({url,body:JSON.parse(options.body)});
      if (failure === "network") throw new TypeError("Network request failed");
      return { ok: false, status: 502 };
    },
  };
  const handlers = vm.runInNewContext(`${source.slice(start, end)}\n({ generateAnswer, generateComparison })`, context);
  return { handlers, state, elements, toasts, requests };
}

for (const method of ["generateAnswer", "generateComparison"]) {
  for (const failure of ["http", "network"]) {
    test(`${method} clears the loading indicator and allows retry after ${failure} failure`, async () => {
      const { handlers, state, elements, toasts } = createHarness(failure);
      await handlers[method]();
      assert.equal(state.answering, false);
      assert.equal(elements.researchAnswer.disabled, false);
      assert.equal(elements.researchCompare.disabled, false);
      assert.doesNotMatch(elements.evidenceResults.innerHTML, /is-loading/);
      assert.match(elements.evidenceResults.innerHTML, /is-error/);
      assert.match(elements.evidenceCount.textContent, /未完成/);
      assert.match(elements.answerResult.innerHTML, /is-error/);
      assert.doesNotMatch(elements.answerResult.innerHTML, /<retry>/);
      assert.equal(toasts.length, 1);
    });
  }
}

test('six-paper comparison reaches the server with enough evidence for every paper',async()=>{
  const h=createHarness('http',6);await h.handlers.generateComparison();
  assert.equal(h.requests.length,1);assert.equal(h.requests[0].body.paper_ids.length,6);assert.equal(h.requests[0].body.limit,12);
  assert.doesNotMatch(h.toasts.join(' '),/最多比较/);
});
