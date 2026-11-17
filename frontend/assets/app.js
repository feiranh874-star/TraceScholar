(() => {
  "use strict";

  const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;
  const viewLabels = {
    tools: { eyebrow: "有来源的研究辅助", title: "研究工具" },
    overview: { eyebrow: "研究资料总览", title: "科研工作台" },
    library: { eyebrow: "可信科研知识库", title: "论文库" },
    import: { eyebrow: "PDF 解析入库", title: "导入论文" },
    research: { eyebrow: "本地可信检索", title: "证据检索" },
  };

  const state = {
    papers: [],
    total: 0,
    activeView: "overview",
    uploading: false,
    importCollection: null,
    collectionPickerTarget: null,
    pendingUpload: null,
    retrieving: false,
    answering: false,
    comparisonMode: false,
    comparisonPaperIds: [],
    deletingPaperId: null,
    libraryPage: 1,
    libraryContext: "",
  };

  const byId = (id) => document.getElementById(id);
  const all = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const elements = {
    sidebar: byId("sidebar"),
    mobileMenu: byId("mobileMenu"),
    pageEyebrow: byId("pageEyebrow"),
    pageTitle: byId("pageTitle"),
    searchInput: byId("searchInput"),
    librarySearch: byId("librarySearch"),
    apiState: byId("apiState"),
    sidebarPaperCount: byId("sidebarPaperCount"),
    statTotal: byId("statTotal"),
    statReady: byId("statReady"),
    statOcr: byId("statOcr"),
    statPages: byId("statPages"),
    recentPapers: byId("recentPapers"),
    libraryTable: byId("libraryTable"),
    libraryEmpty: byId("libraryEmpty"),
    libraryPagination: byId("libraryPagination"),
    refreshPapers: byId("refreshPapers"),
    fileInput: byId("fileInput"),
    largeDropzone: byId("largeDropzone"),
    uploadProgress: byId("uploadProgress"),
    uploadFilename: byId("uploadFilename"),
    uploadResult: byId("uploadResult"),
    researchForm: byId("researchForm"),
    researchQuestion: byId("researchQuestion"),
    researchPaperScope: byId("researchPaperScope"),
    comparisonModeToggle: byId("comparisonModeToggle"),
    singlePaperScopeLabel: byId("singlePaperScopeLabel"),
    comparisonPaperScope: byId("comparisonPaperScope"),
    comparisonPaperList: byId("comparisonPaperList"),
    researchSubmit: byId("researchSubmit"),
    researchAnswer: byId("researchAnswer"),
    researchCompare: byId("researchCompare"),
    answerPanel: byId("answerPanel"),
    answerResult: byId("answerResult"),
    answerModel: byId("answerModel"),
    answerCitations: byId("answerCitations"),
    agentTrace: byId("agentTrace"),
    agentSteps: byId("agentSteps"),
    evidenceCount: byId("evidenceCount"),
    evidenceResults: byId("evidenceResults"),
    toastRegion: byId("toastRegion"),

  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function paperTitle(paper) {
    return paper.title?.trim() || paper.filename || "未命名论文";
  }

  function paperAuthor(paper) {
    const authors = Array.isArray(paper.authors) && paper.authors.length
      ? paper.authors
      : String(paper.author || "").split(/[,;，；\n]+/);
    const names = authors.map(name => String(name).trim()).filter(Boolean);
    if (!names.length) return "未填写作者";
    return names.slice(0, 5).join(", ") + (names.length > 5 ? ", etc" : "");
  }

  function paperVersion(paper) {
    if (paper.version_label) return paper.version_label;
    return paper.arxiv_id ? "版本未知" : "";
  }

  function displaySectionTitle(value) {
    const title = String(value || "").trim();
    if (!title) return "";
    if (!/^[A-Z\u3400-\u9fff]/.test(title)) return "";
    if (/[.,;:!?\u2013\u2014-]$/.test(title) || title.split(/\s+/).length > 10) return "";
    const words = title.match(/[A-Za-z]+/g) || [];
    if (words.length >= 6 && words.filter((word) => /^[A-Z]/.test(word)).length / words.length < 0.45) return "";
    if (/[\u00b7\u2022%]/.test(title)) return "";
    return title;
  }

  function versionRelationNotice(paper) {
    const relation = paper.version_relation;
    if (!relation || relation.kind === "none") return "";
    if (relation.kind === "older_version") {
      return `已识别为同一论文的较早版本；论文库中已有更新的 ${relation.latest_version_label || "版本"}，建议保留新版用于阅读，同时保留本版用于差异比较。`;
    }
    if (relation.kind === "newer_version") {
      return "已识别为同一论文的更新版本，建议优先使用当前版本。";
    }
    if (relation.kind === "same_version") {
      return "论文库中已有同一版本的其他文件，可能是文本版与扫描版。";
    }
    return "已在论文库中发现同一研究工作的关联记录。";
  }

  function statusInfo(status) {
    if (status === "ready") {
      return { label: "解析完成", className: "status-ready" };
    }
    if (status === "needs_ocr") {
      return { label: "待 OCR", className: "status-ocr" };
    }
    return { label: "状态未知", className: "status-unknown" };
  }

  function formatDate(value, withTime = false) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "时间未知";
    return new Intl.DateTimeFormat("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      ...(withTime ? { hour: "2-digit", minute: "2-digit", hour12: false } : {}),
    }).format(date);
  }

  function localizeWarning(warning) {
    const value = String(warning || "");
    const pageMatch = value.match(/^(\d+) page\(s\).*OCR/i);
    if (pageMatch) return `${pageMatch[1]} 页文字较少或为空，可能需要 OCR 识别`;
    if (/metadata.*title/i.test(value)) return "PDF 元数据中未提供题名，当前以文件名展示";
    return value || "该论文包含需要留意的解析信息";
  }

  function localizeApiError(detail, status) {
    const value = Array.isArray(detail)
      ? (status === 422 ? "输入内容不符合要求，请检查必填项和字数。" : detail.map(item => typeof item === "string" ? item : item?.msg || "输入有误").join("；"))
      : typeof detail === "object" && detail !== null ? (typeof detail.message === "string" ? detail.message : "请求参数有误，请检查输入。") : String(detail || "");
    if (status === 401) return "登录已失效，请刷新页面并输入演示账号和密码。";
    if (status === 429) return "上传过于频繁或服务繁忙，请一分钟后重试。";
    if (status === 507) return "演示资料库已达到容量上限，请联系管理员清理或扩容。";
    if (/not a PDF/i.test(value)) return "所选文件不是有效的 PDF。";
    if (/damaged or unreadable/i.test(value)) return "PDF 已损坏或无法读取。";
    if (/Password-protected/i.test(value)) return "暂不支持加密或需要密码的 PDF。";
    if (/50 MiB/i.test(value)) return "文件超过 50 MiB 上传限制。";
    if (/page limit/i.test(value)) return "PDF 页数超过系统限制。";
    if (/too much extracted text/i.test(value)) return "PDF 提取出的文本量超过系统限制。";
    if (/Could not store/i.test(value)) return "文件保存失败，请联系管理员检查服务存储。";
    if (/模型服务尚未配置|LLM_API_KEY/i.test(value)) return "模型服务尚未配置，请联系管理员设置接口信息。";
    if (/模型服务|模型返回|模型响应|连接模型/i.test(value)) return value;
    if (status === 413) return "文件超过系统允许的处理范围。";
    if (status >= 500) return "服务处理失败，请稍后重试。";
    return value || "请求失败，请稍后重试。";
  }

  function friendlyError(error, fallback) {
    if (error instanceof TypeError || /failed to fetch|networkerror|network request failed/i.test(String(error?.message))) {
      return "无法连接服务，请检查网络或联系管理员。";
    }
    return error?.message || fallback;
  }

  async function responseError(response) {
    let detail = "";
    try {
      const payload = await response.json();
      detail = payload.detail || payload.message || "";
    } catch (_error) {
      detail = "";
    }
    return new Error(localizeApiError(detail, response.status));
  }

  function setApiState(kind, title, detail) {
    elements.apiState.innerHTML = `
      <span class="status-dot ${kind}"></span>
      <div><strong>${escapeHtml(title)}</strong><small>${escapeHtml(detail)}</small></div>
    `;
  }

  async function checkHealth() {
    setApiState("is-checking", "正在连接", "科研资料服务");
    try {
      const response = await fetch("/health", { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error("health check failed");
      setApiState("is-online", "服务已连接", "演示账号共享资料库");
    } catch (_error) {
      setApiState("is-offline", "服务未连接", "请启动后端服务");
    }
  }

  function showToast(message, type = "success") {
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.setAttribute("role", type === "error" ? "alert" : "status");
    toast.innerHTML = `
      <span class="toast-icon" aria-hidden="true">${type === "error" ? "!" : "✓"}</span>
      <span>${escapeHtml(message)}</span>
      <button type="button" aria-label="关闭提示">×</button>
    `;
    toast.querySelector("button").addEventListener("click", () => toast.remove());
    elements.toastRegion.appendChild(toast);
    window.setTimeout(() => {
      toast.classList.add("is-leaving");
      window.setTimeout(() => toast.remove(), 220);
    }, 4200);
  }

  function navigateTo(view) {
    if (!viewLabels[view]) return;
    state.activeView = view;
    byId("searchBox").hidden = view !== "overview";
    document.querySelector(".topbar").classList.toggle("is-compact", view !== "overview");
    all("[data-view-panel]").forEach((panel) => {
      panel.classList.toggle("is-active", panel.dataset.viewPanel === view);
    });
    all(".nav-item[data-view]").forEach((button) => {
      const active = button.dataset.view === view;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-current", active ? "page" : "false");
    });
    elements.pageEyebrow.textContent = viewLabels[view].eyebrow;
    elements.pageTitle.textContent = viewLabels[view].title;
    closeMobileNavigation();
    if (view === "library") renderLibrary();
    if (view === "tools") renderToolPapers();
    if (view === "research") renderResearchScope();
    window.scrollTo({ top: 0, behavior: "instant" });
    document.querySelector(".content")?.scrollTo({ top: 0, behavior: "smooth" });
  }

  function openMobileNavigation() {
    elements.sidebar.classList.add("is-open");
    document.body.classList.add("nav-open");
    elements.mobileMenu.setAttribute("aria-expanded", "true");
  }

  function closeMobileNavigation() {
    elements.sidebar.classList.remove("is-open");
    document.body.classList.remove("nav-open");
    elements.mobileMenu.setAttribute("aria-expanded", "false");
  }

  function searchQuery() {
    return (elements.librarySearch.value || elements.searchInput.value || "").trim().toLocaleLowerCase("zh-CN");
  }

  function filteredPapers() {
    const query = searchQuery();
    const scoped = window.TraceLibrary.filter(state.papers);
    if (!query) return scoped;
    return scoped.filter((paper) =>
      [paper.title, paper.author, paper.filename, paper.notes]
        .filter(Boolean)
        .some((value) => String(value).toLocaleLowerCase("zh-CN").includes(query)),
    );
  }

  function renderStats() {
    const ready = state.papers.filter((paper) => paper.parse_status === "ready").length;
    const needsOcr = state.papers.filter((paper) => paper.parse_status === "needs_ocr").length;
    const pages = state.papers.reduce((sum, paper) => sum + (Number(paper.page_count) || 0), 0);
    elements.statTotal.textContent = String(state.total);
    elements.statReady.textContent = String(ready);
    elements.statOcr.textContent = String(needsOcr);
    elements.statPages.textContent = String(pages);
    elements.sidebarPaperCount.textContent = String(state.total);
  }

  function paperTableCells(paper) {
    const status = statusInfo(paper.parse_status);
    return `
      <td><button class="table-paper" type="button" data-paper-id="${escapeHtml(paper.paper_id)}">
        <span class="table-paper-icon" aria-hidden="true">PDF</span>
        <span class="table-paper-copy"><strong class="table-paper-title" title="${escapeHtml(paperTitle(paper))}">${escapeHtml(paperTitle(paper))}</strong><small class="table-paper-file">${escapeHtml(paper.filename)}${paperVersion(paper) ? ' · ' + escapeHtml(paperVersion(paper)) : ''}</small>${paper.notes ? `<small class="paper-note-preview">备注：${escapeHtml(paper.notes)}</small>` : ''}</span>
      </button></td>
      <td><span class="table-paper-authors" title="${escapeHtml(paperAuthor(paper))}">${escapeHtml(paperAuthor(paper))}</span></td>
      <td class="table-nowrap">${paper.page_count} 页</td>
      <td><span class="status-badge ${status.className}">${status.label}</span></td>
      <td><span class="table-paper-date">${formatDate(paper.created_at)}</span></td>
    `;
  }

  function renderRecent() {
    if (!state.papers.length) {
      elements.recentPapers.innerHTML = `
        <div class="inline-empty">
          <strong>还没有导入论文</strong>
          <span>点击左侧“导入论文”，添加第一篇 PDF。</span>
        </div>
      `;
      return;
    }
    elements.recentPapers.innerHTML = `<table class="recent-paper-table"><thead><tr><th>论文</th><th>作者</th><th>页数</th><th>状态</th><th>导入时间</th></tr></thead><tbody>${window.TracePaperUI.recent(state.papers).slice(0, 4).map(paper => `<tr>${paperTableCells(paper)}</tr>`).join("")}</tbody></table>`;
  }

  function renderLibraryPagination(page) {
    const {total, totalPages, start, end} = page;
    elements.libraryPagination.hidden = !total;
    if (!total) { elements.libraryPagination.innerHTML = ""; return; }
    const pages = totalPages <= 7 ? Array.from({length: totalPages}, (_, i) => i + 1)
      : [...new Set([1, page.page - 1, page.page, page.page + 1, totalPages])].filter(n => n > 0 && n <= totalPages).sort((a, b) => a - b);
    const numbers = pages.map((n, i) => `${i && n - pages[i - 1] > 1 ? '<span class="page-gap" aria-hidden="true">…</span>' : ''}<button type="button" data-library-page="${n}" aria-label="第 ${n} 页"${n === page.page ? ' aria-current="page"' : ''}>${n}</button>`).join("");
    elements.libraryPagination.innerHTML = `<span class="library-page-summary" role="status">共 ${total} 篇 · 每页 10 篇 · 第 ${start}–${end} 篇</span><div class="library-page-buttons"><button type="button" data-library-page="${page.page - 1}"${page.page === 1 ? ' disabled' : ''}>上一页</button>${numbers}<button type="button" data-library-page="${page.page + 1}"${page.page === totalPages ? ' disabled' : ''}>下一页</button></div>`;
  }

  function renderLibrary() {
    const context = window.TraceLibrary.scopeKey() + "\n" + searchQuery();
    if (state.libraryContext !== context) { state.libraryPage = 1; state.libraryContext = context; }
    if (window.TraceLibrary.render(state.papers)) { elements.libraryPagination.hidden = true; return; }
    const papers = filteredPapers();
    const page = window.TracePaperUI.paginate(papers, state.libraryPage);
    state.libraryPage = page.page;
    renderLibraryPagination(page);
    const hasSearch = Boolean(searchQuery());
    elements.libraryEmpty.classList.toggle("is-hidden", papers.length > 0);
    elements.libraryTable.closest(".table-wrap").classList.toggle("is-hidden", papers.length === 0);

    if (!papers.length) {
      elements.libraryTable.innerHTML = "";
      const heading = elements.libraryEmpty.querySelector("h3");
      const description = elements.libraryEmpty.querySelector("p");
      const action = elements.libraryEmpty.querySelector("button");
      description.hidden = true;
      action.hidden = true;
      delete action.dataset.goImport;
      if (hasSearch || window.TraceLibrary.hasFolder()) {
        heading.textContent = hasSearch ? "没有找到匹配的论文" : "收藏夹中还没有论文";
        description.hidden = false;
        description.textContent = hasSearch ? "试试题名、作者、文件名或备注中的其他关键词。" : "点击“上传论文”从本机添加，或用“添加 / 移出论文”收纳库内论文。";
        action.hidden = !hasSearch;
        action.textContent = "清除搜索";
        action.dataset.clearSearch = "true";
        delete action.dataset.goImport;
        delete action.dataset.retryLoad;
      } else {
        heading.textContent = "论文库还是空的";
        description.textContent = "";
        action.textContent = "";
        delete action.dataset.clearSearch;
        delete action.dataset.retryLoad;
      }
      return;
    }

    elements.libraryTable.innerHTML = page.items
      .map((paper) => {
        return `
          <tr>
            ${paperTableCells(paper)}
            <td><div class="library-row-actions"><button class="open-paper-button" type="button" data-organize-paper="${escapeHtml(paper.paper_id)}">整理</button><button class="open-paper-button" type="button" data-paper-id="${escapeHtml(paper.paper_id)}" aria-label="查看 ${escapeHtml(paperTitle(paper))}">查看</button>${window.TraceLibrary?.hasFolder() ? `<button class="open-paper-button" type="button" data-remove-collection-paper="${escapeHtml(paper.paper_id)}" aria-label="移出当前收藏夹">移出</button>` : `<button class="delete-paper-button" type="button" data-delete-paper="${escapeHtml(paper.paper_id)}" aria-label="永久删除 ${escapeHtml(paperTitle(paper))}"${state.deletingPaperId ? " disabled" : ""}>${state.deletingPaperId === paper.paper_id ? "删除中…" : "删除"}</button>`}</div></td>
          </tr>
        `;
      })
      .join("");
  }

  function refreshComparisonSelection() {
    const inputs = Array.from(elements.comparisonPaperList.querySelectorAll("input[type=checkbox]"));
    const checkedInputs = inputs.filter((input) => input.checked);
    state.comparisonPaperIds = checkedInputs.map((input) => input.value);
    const selectedCount = checkedInputs.length;
    inputs.forEach((input) => {
      const unavailable = input.closest(".comparison-paper-option")?.classList.contains("is-unavailable");
      input.disabled = Boolean(unavailable || (!input.checked && selectedCount >= 5));
    });
    elements.researchCompare.disabled = state.answering || state.retrieving || selectedCount < 2;
    elements.researchCompare.querySelector("span").textContent = selectedCount >= 2
      ? `比较所选论文（${selectedCount}）`
      : "比较所选论文（至少选 2 篇）";
  }

  function renderResearchScope() {
    const currentValue = elements.researchPaperScope.value;
    elements.researchPaperScope.innerHTML = [
      `<option value="">全部已入库论文（${state.papers.length}）</option>`,
      ...state.papers.map(
        (paper) => `<option value="${escapeHtml(paper.paper_id)}">${escapeHtml(paperTitle(paper))}${paperVersion(paper) ? ` · ${escapeHtml(paperVersion(paper))}` : ""}</option>`,
      ),
    ].join("");
    if (state.papers.some((paper) => paper.paper_id === currentValue)) {
      elements.researchPaperScope.value = currentValue;
    }
    window.TracePaperUI.mountPicker(elements.researchPaperScope, state.papers, { all: true, searchFirst: true });
    const selectedIds = new Set(state.comparisonPaperIds);
    const selectedCount = selectedIds.size;
    elements.comparisonPaperList.innerHTML = state.papers.map((paper) => {
      const checked = selectedIds.has(paper.paper_id);
      const unavailable = paper.parse_status !== "ready" || !paper.chunk_count;
      const disabled = unavailable || (!checked && selectedCount >= 5);
      const version = paper.version_label ? ` · ${paper.version_label}` : "";
      const note = unavailable ? " · 暂无可检索文本" : "";
      return `
        <label class="comparison-paper-option${unavailable ? " is-unavailable" : ""}">
          <input type="checkbox" value="${escapeHtml(paper.paper_id)}"${checked ? " checked" : ""}${disabled ? " disabled" : ""} />
          <span><strong>${escapeHtml(paperTitle(paper))}</strong><small>${escapeHtml(paper.filename)}${escapeHtml(version)}${escapeHtml(note)}</small></span>
        </label>
      `;
    }).join("") || '<div class="comparison-paper-empty">论文库为空，请先导入论文。</div>';
    elements.singlePaperScopeLabel.classList.toggle("is-hidden", state.comparisonMode);
    elements.comparisonPaperScope.classList.toggle("is-hidden", !state.comparisonMode);
    elements.researchSubmit.classList.toggle("is-hidden", state.comparisonMode);
    elements.researchAnswer.classList.toggle("is-hidden", state.comparisonMode);
    elements.researchCompare.classList.toggle("is-hidden", !state.comparisonMode);
    elements.comparisonModeToggle.innerHTML = state.comparisonMode
      ? '返回证据检索 <span>→</span>'
      : '切换到多篇比较 <span>→</span>';
    elements.comparisonModeToggle.disabled = state.answering || state.retrieving;
    refreshComparisonSelection();
    elements.researchPaperScope.disabled = state.papers.length === 0;
    elements.researchSubmit.disabled = state.answering || state.retrieving || state.papers.length === 0;
    byId("searchMentions").disabled = state.answering || state.retrieving;
    elements.researchAnswer.disabled = state.answering || state.retrieving || state.papers.length === 0;
  }

  function clearAnswer() {
    elements.answerPanel.classList.add("is-hidden");
    elements.answerResult.innerHTML = "";
    elements.answerCitations.innerHTML = "";
    elements.answerModel.textContent = "";
    elements.agentTrace.hidden = true;
    elements.agentSteps.innerHTML = "";
  }

  function answerTextForDisplay(value) {
    const displayFormulaMarker = "\uE000DISPLAY_FORMULA\uE001";
    const inlineFormulaMarker = "\uE000INLINE_FORMULA\uE001";
    const inlineMathLabel = /[\u3400-\u9fff]/.test(String(value || "")) ? "相关量" : "the relevant quantity";
    return String(value || "")
      .replace(/```(?:latex|math|tex)\s*[\s\S]*?```/gi, displayFormulaMarker)
      .replace(/\\begin\{(?:equation\*?|align\*?|gather\*?|multline\*?|aligned|cases|split|array|[bpv]?matrix)\}[\s\S]*?\\end\{(?:equation\*?|align\*?|gather\*?|multline\*?|aligned|cases|split|array|[bpv]?matrix)\}/gi, displayFormulaMarker)
      .replace(/\\\[[\s\S]*?\\\]/g, displayFormulaMarker)
      .replace(/\$\$[\s\S]*?\$\$/g, displayFormulaMarker)
      .replace(/\\\([\s\S]*?\\\)/g, inlineFormulaMarker)
      .replace(/\$(?!\$)[^$\n]+\$/g, inlineFormulaMarker)
      .replace(new RegExp(`(?:公式|表达式)(?:如下|为|是)?\\s*[：:]?\\s*${displayFormulaMarker}`, "g"), " ")
      .replace(new RegExp(`(?:可)?(?:写作|表示为|记为)\\s*[：:]?\\s*${displayFormulaMarker}`, "g"), " ")
      .replace(new RegExp(`(?:the\\s+)?(?:formula|equation|expression)(?:\\s+(?:is|equals|can\\s+be\\s+written\\s+as))?\\s*[:=：]?\\s*${displayFormulaMarker}`, "gi"), " ")
      .replaceAll(displayFormulaMarker, " ")
      .replaceAll(inlineFormulaMarker, inlineMathLabel)
      .replace(/[ \t]+([，。；：,.!?])/g, "$1")
      .replace(/[ \t]{2,}/g, " ")
      .replace(/([\u3400-\u9fff])\s+(?=[\u3400-\u9fff])/g, "$1")
      .replace(/\n[ \t]+/g, "\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  function markdownTableCells(line) {
    const value = String(line || "").trim();
    if (!value.includes("|")) return null;
    const cells = [];
    let cell = "";
    for (let index = 0; index < value.length; index += 1) {
      const character = value[index];
      if (character === "|" && value[index - 1] !== "\\") {
        cells.push(cell.trim());
        cell = "";
      } else {
        cell += character;
      }
    }
    cells.push(cell.trim());
    if (value.startsWith("|") && cells[0] === "") cells.shift();
    if (value.endsWith("|") && cells.at(-1) === "") cells.pop();
    return cells.length > 1 ? cells : null;
  }

  function isMarkdownTableDivider(cells) {
    return Boolean(cells?.length > 1 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.replaceAll(" ", ""))));
  }

  function cleanAnswerLabel(value) {
    return String(value || "").trim().replace(/^\*\*(.+)\*\*$/, "$1").replace(/^__(.+)__$/, "$1");
  }

  function renderComparisonCards(headers, rows) {
    const paperHeaders = headers.slice(1);
    const cards = rows.map((row, index) => {
      const aspect = cleanAnswerLabel(row[0]) || `比较项 ${index + 1}`;
      const details = paperHeaders.map((paper, paperIndex) => {
        const detail = String(row[paperIndex + 1] || "").trim();
        if (!detail) return "";
        return `<div class="answer-comparison-point"><strong>${escapeHtml(cleanAnswerLabel(paper))}</strong><span>${escapeHtml(detail)}</span></div>`;
      }).filter(Boolean).join("");
      return `<article class="answer-comparison-item"><h4>${escapeHtml(aspect)}</h4><div class="answer-comparison-points">${details}</div></article>`;
    }).join("");
    return `<div class="answer-comparison" aria-label="论文比较结果">${cards}</div>`;
  }

  function renderAnswerContent(value) {
    const lines = String(value || "").split(/\r?\n/);
    const blocks = [];
    let paragraph = [];
    const flushParagraph = () => {
      const content = paragraph.join("\n").trim();
      if (content) blocks.push(`<p>${escapeHtml(content).replaceAll("\n", "<br>")}</p>`);
      paragraph = [];
    };

    for (let index = 0; index < lines.length;) {
      const headers = markdownTableCells(lines[index]);
      const divider = markdownTableCells(lines[index + 1]);
      if (headers && isMarkdownTableDivider(divider) && headers.length === divider.length) {
        flushParagraph();
        const rows = [];
        index += 2;
        while (index < lines.length) {
          const row = markdownTableCells(lines[index]);
          if (!row) break;
          rows.push(row);
          index += 1;
        }
        if (rows.length) blocks.push(`<div class="answer-table-wrap"><table class="answer-table"><thead><tr>${headers.map(h => `<th>${escapeHtml(cleanAnswerLabel(h))}</th>`).join("")}</tr></thead><tbody>${rows.map(row => `<tr>${headers.map((_, i) => `<td>${escapeHtml(row[i] || "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
        continue;
      }
      if (!lines[index].trim()) flushParagraph();
      else paragraph.push(lines[index]);
      index += 1;
    }
    flushParagraph();
    return blocks.join("");
  }

  function renderAnswer(payload) {
    elements.answerPanel.classList.remove("is-hidden");
    elements.answerModel.textContent = payload.model ? "基于原文生成" : "本地工具编排";
    const steps = Array.isArray(payload.steps) ? payload.steps : [];
    const toolLabels = {
      intent_router: "识别问题类型",
      tool_selector: "选择处理工具",
      retrieve_evidence: "搜索论文证据",
      evidence_gate: "检查证据来源",
      generate_grounded_answer: "生成证据回答",
      citation_validator: "核对引用",
    };
    elements.agentSteps.innerHTML = steps.map((step) => `
      <li class="agent-step is-${escapeHtml(step.status)}"><strong>${escapeHtml(toolLabels[step.tool] || step.tool)}</strong><span>${escapeHtml(step.detail)}</span></li>
    `).join("");
    elements.agentTrace.hidden = steps.length === 0;
    if (payload.insufficient) {
      const detail = payload.model
        ? "模型判断当前检索到的证据不足以支持结论。请展开下方原文片段，确认问题和证据对应后再调整问题。"
        : "至少一篇所选论文没有找到可用证据，因此未调用模型。请导入相关论文或调整问题。";
      elements.answerResult.innerHTML = `<div class="answer-insufficient"><strong>当前资料不足</strong><span>${detail}</span></div>`;
      elements.answerCitations.innerHTML = "";
      return;
    }
    if (payload.route === "retrieve_only") {
      elements.answerResult.innerHTML = '<div class="agent-retrieval-note"><strong>已完成证据检索</strong><span>按照你的请求，本次只检索原文，没有调用模型。请查看下方证据卡片。</span></div>';
      elements.answerCitations.innerHTML = "";
      return;
    }
    if (!payload.answer) {
      elements.answerResult.innerHTML = '<div class="answer-insufficient"><strong>暂时没有可展示的回答</strong><span>请调整问题后重试。</span></div>';
      elements.answerCitations.innerHTML = "";
      return;
    }
    const formattedAnswer = answerTextForDisplay(payload.answer);
    const hasReadableAnswer = formattedAnswer.replace(/\[E\d+\]/gi, "").replace(/[\s\p{P}\p{S}]/gu, "").length > 0;
    const displayAnswer = hasReadableAnswer ? formattedAnswer : "详细公式请查看下方引用的论文原文。";
    elements.answerResult.innerHTML = renderAnswerContent(displayAnswer);
    const citations = Array.isArray(payload.citations) ? payload.citations : [];
    const citationLinks = citations.map((item) => {
      const source = item.source || {};
      const pageLabel = source.page_start === source.page_end ? `第 ${source.page_start} 页` : `第 ${source.page_start}–${source.page_end} 页`;
      const sectionTitle = displaySectionTitle(item.section_title);
      return `<button type="button" data-evidence-paper="${escapeHtml(source.paper_id)}" data-evidence-page="${Number(source.page_start) || 1}" data-evidence-quote="${escapeHtml(item.text?.slice(0, 120) || "")}"><strong>[${escapeHtml(item.citation_id)}] ${escapeHtml(item.paper_title || item.filename)}</strong><span>${escapeHtml([sectionTitle, source.version_label, pageLabel].filter(Boolean).join(" · "))}</span></button>`;
    }).join("");
    elements.answerCitations.innerHTML = citationLinks
      ? `<details class="answer-citation-details"><summary>查看引用来源（${citations.length}）</summary><div class="answer-citation-list">${citationLinks}</div></details>`
      : "";
  }

  function renderEvidence(items, totalCandidates) {
    const results = Array.isArray(items) ? items : [];
    elements.evidenceCount.textContent = results.length
      ? `${results.length} 条证据 · 检索 ${totalCandidates} 个文本块`
      : `0 条证据 · 检索 ${totalCandidates} 个文本块`;
    if (!results.length) {
      elements.evidenceResults.innerHTML = `
        <div class="evidence-empty is-insufficient">
          <strong>当前资料不足</strong>
          <span>没有找到能直接支撑该问题的原文片段。请更换关键词、切换论文范围，或先导入相关资料。</span>
        </div>
      `;
      return;
    }

    elements.evidenceResults.innerHTML = results
      .map((item, index) => {
        const source = item.source || {};
        const pageLabel = source.page_start === source.page_end
          ? `第 ${source.page_start} 页`
          : `第 ${source.page_start}–${source.page_end} 页`;
        const location = [displaySectionTitle(item.section_title), source.version_label, pageLabel].filter(Boolean).join(" · ");
        return `
          <article class="evidence-result">
            <div class="evidence-result-head"><span>${escapeHtml(item.citation_id ? `[${item.citation_id}]` : `证据 ${index + 1}`)}</span><strong>${escapeHtml(item.paper_title || item.filename)}</strong></div>
            <div class="evidence-meta"><span>${escapeHtml(location || pageLabel)}</span><span>相关度 ${Number(item.score || 0).toFixed(2)}</span></div>
            <details class="evidence-source">
              <summary>查看原文片段 <span aria-hidden="true">＋</span></summary>
              <p>${escapeHtml(item.text)}</p>
              <a class="evidence-open" href="/reader/${encodeURIComponent(source.paper_id)}?${new URLSearchParams({page:String(source.page_start || 1),from:"research",highlight:(item.text || "").slice(0,120)})}" target="_blank" rel="noopener">打开论文 · ${escapeHtml(pageLabel)} ↗</a>
            </details>
          </article>
        `;
      })
      .join("");
  }

  let mentionQuestion = "";
  function validateText(id, errorId) {
    const input = byId(id), error = byId(errorId), value = input.value.trim();
    error.textContent = value ? "" : "输入不能为空";
    error.hidden = Boolean(value);
    input.setAttribute("aria-invalid", String(!value));
    if (!value) input.focus();
    return value;
  }

  async function searchLibraryMentions(page = 1) {
    if (state.retrieving || state.answering) return;
    const question = page === 1 ? validateText("researchQuestion", "researchError") : mentionQuestion;
    if (!question) return;
    if (page === 1) mentionQuestion = question;
    state.retrieving = true;
    byId("searchMentions").disabled = true;
    renderResearchScope();
    clearAnswer();
    elements.evidenceCount.textContent = "正在查找全库正文";
    elements.evidenceResults.innerHTML = '<div class="evidence-empty">正在查找所有已入库论文…</div>';
    try {
      const response = await fetch("/api/research/mentions", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({question, page, page_size:10})});
      if (!response.ok) throw await responseError(response);
      const data = await response.json();
      elements.evidenceCount.textContent = `命中 ${data.total_papers} 篇 · 已查找 ${data.scanned_papers} 篇`;
      elements.evidenceResults.innerHTML = `<p class="tool-hint">查找：${escapeHtml(data.question)}。${escapeHtml(data.notice)}</p>` + (data.items.map(p => `<article class="evidence-result"><div class="evidence-result-head"><strong>${escapeHtml(p.title)}</strong></div><p class="evidence-meta">${escapeHtml(p.version_label || "")} · ${p.matched_passages} 个相关片段 · 原始页码 ${p.pages.join("、")}</p>${p.items.map(e => `<details class="evidence-source"><summary>第 ${e.source.page_start} 页 · ${escapeHtml(displaySectionTitle(e.section_title) || "查看正文片段")}</summary><p>${escapeHtml(e.text)}</p><a class="evidence-open" href="/reader/${encodeURIComponent(p.paper_id)}?${new URLSearchParams({page:String(e.source.page_start),from:"research",highlight:e.text.slice(0,120)})}" target="_blank" rel="noopener">在新标签页核对原文 ↗</a></details>`).join("")}<small>每篇展示最多 3 个相关片段，页码列出全部命中位置。</small></article>`).join("") || '<div class="evidence-empty">未找到相关正文。可以缩短为关键术语，或尝试原文中的英文术语。</div>') + (data.total_pages > 1 ? `<nav class="mention-pagination" aria-label="全库查找结果翻页"><button type="button" class="secondary-button" data-mentions-page="${data.page-1}" ${data.page===1?'disabled':''}>上一页</button><span>第 ${data.page} / ${data.total_pages} 页 · 每页 10 篇</span><button type="button" class="secondary-button" data-mentions-page="${data.page+1}" ${data.page===data.total_pages?'disabled':''}>下一页</button></nav>` : "");
    } catch (error) {
      elements.evidenceCount.textContent = "查找失败";
      elements.evidenceResults.textContent = friendlyError(error, "查找失败，请稍后重试。");
    } finally {
      state.retrieving = false;
      byId("searchMentions").disabled = false;
      renderResearchScope();
    }
  }

  async function retrieveEvidence() {
    const question = elements.researchQuestion.value.trim();
    if (!question) { validateText("researchQuestion", "researchError"); return; }
    if (question.length < 2) {
      showToast("请输入至少 2 个字符的研究问题。", "error");
      elements.researchQuestion.focus();
      return;
    }
    if (!state.papers.length) {
      showToast("请先导入至少一篇论文。", "error");
      return;
    }

    state.retrieving = true;
    clearAnswer();
    elements.researchSubmit.disabled = true;
    elements.researchAnswer.disabled = true;
    elements.researchSubmit.querySelector("span").textContent = "正在检索…";
    elements.evidenceCount.textContent = "正在扫描论文文本块";
    elements.evidenceResults.innerHTML = '<div class="evidence-empty is-loading"><span>正在定位相关原文、章节和页码…</span></div>';

    try {
      const selectedPaperId = elements.researchPaperScope.value;
      const response = await fetch("/api/research/retrieve", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ question, paper_ids: selectedPaperId ? [selectedPaperId] : [], limit: 6 }),
      });
      if (!response.ok) throw await responseError(response);
      const payload = await response.json();
      renderEvidence(payload.items, Number(payload.total_candidates) || 0);
    } catch (error) {
      const message = friendlyError(error, "证据检索失败，请稍后重试。");
      elements.evidenceCount.textContent = "检索失败";
      elements.evidenceResults.innerHTML = `<div class="evidence-empty is-error"><strong>无法完成检索</strong><span>${escapeHtml(message)}</span></div>`;
      showToast(message, "error");
    } finally {
      state.retrieving = false;
      elements.researchSubmit.querySelector("span").textContent = "检索原文证据";
      renderResearchScope();
    }
  }

  async function generateAnswer() {
    const question = elements.researchQuestion.value.trim();
    if (!question) { validateText("researchQuestion", "researchError"); return; }
    if (question.length < 2) {
      showToast("请输入至少 2 个字符的研究问题。", "error");
      elements.researchQuestion.focus();
      return;
    }
    if (!state.papers.length) {
      showToast("请先导入至少一篇论文。", "error");
      return;
    }
    state.answering = true;
    elements.researchSubmit.disabled = true;
    elements.researchAnswer.disabled = true;
    elements.researchAnswer.querySelector("span").textContent = "正在生成…";
    elements.answerPanel.classList.remove("is-hidden");
    elements.answerModel.textContent = "正在规划检索步骤";
    elements.answerResult.innerHTML = '<div class="answer-loading"><span>先检索原文证据，再生成带引用的回答…</span></div>';
    elements.answerCitations.innerHTML = "";
    elements.agentTrace.hidden = true;
    elements.agentSteps.innerHTML = "";
    elements.evidenceCount.textContent = "正在检索证据并生成回答";
    elements.evidenceResults.innerHTML = '<div class="evidence-empty is-loading"><span>正在定位原文并生成回答…</span></div>';
    try {
      const selectedPaperId = elements.researchPaperScope.value;
      const response = await fetch("/api/research/agent", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ question, paper_ids: selectedPaperId ? [selectedPaperId] : [], limit: 6 }),
      });
      if (!response.ok) throw await responseError(response);
      const payload = await response.json();
      renderAnswer(payload);
      renderEvidence(payload.items, Number(payload.total_candidates) || 0);
    } catch (error) {
      const message = friendlyError(error, "证据回答生成失败，请稍后重试。");
      elements.answerModel.textContent = "生成失败";
      elements.answerResult.innerHTML = `<div class="answer-insufficient is-error"><strong>无法生成回答</strong><span>${escapeHtml(message)}</span></div>`;
      elements.evidenceCount.textContent = "本次问答未完成";
      elements.evidenceResults.innerHTML = '<div class="evidence-empty is-error"><strong>本次未取得完整结果</strong><span>回答生成已停止。你可以重试原问题，或选择“只检索原文”查看证据。</span></div>';
      showToast(message, "error");
    } finally {
      state.answering = false;
      elements.researchAnswer.querySelector("span").textContent = "智能体回答";
      renderResearchScope();
    }
  }

  async function generateComparison() {
    const question = elements.researchQuestion.value.trim();
    const selectedIds = Array.from(elements.comparisonPaperList.querySelectorAll("input:checked"))
      .map((input) => input.value);
    if (!question) { validateText("researchQuestion", "researchError"); return; }
    if (question.length < 2) {
      showToast("请输入至少 2 个字符的研究问题。", "error");
      elements.researchQuestion.focus();
      return;
    }
    if (selectedIds.length < 2) {
      showToast("至少选择 2 篇论文后再比较。", "error");
      return;
    }
    if (selectedIds.length > 5) {
      showToast("一次最多比较 5 篇论文。", "error");
      return;
    }

    state.answering = true;
    state.comparisonPaperIds = selectedIds;
    renderResearchScope();
    clearAnswer();
    elements.researchCompare.querySelector("span").textContent = "正在分别检索并比较…";
    elements.answerPanel.classList.remove("is-hidden");
    elements.answerModel.textContent = "正在检查每篇论文的证据";
    elements.answerResult.innerHTML = '<div class="answer-loading"><span>分别检索所选论文，确认每篇都有原文依据后再生成比较…</span></div>';
    elements.evidenceCount.textContent = "正在按论文检索证据";
    elements.evidenceResults.innerHTML = '<div class="evidence-empty is-loading"><span>正在为每篇论文分别定位原文和页码…</span></div>';
    try {
      const response = await fetch("/api/research/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ question, paper_ids: selectedIds, limit: 10 }),
      });
      if (!response.ok) throw await responseError(response);
      const payload = await response.json();
      renderAnswer(payload);
      renderEvidence(payload.items, Number(payload.total_candidates) || 0);
    } catch (error) {
      const message = friendlyError(error, "多论文比较失败，请稍后重试。");
      elements.answerModel.textContent = "比较失败";
      elements.answerResult.innerHTML = `<div class="answer-insufficient is-error"><strong>无法完成比较</strong><span>${escapeHtml(message)}</span></div>`;
      elements.evidenceCount.textContent = "本次比较未完成";
      elements.evidenceResults.innerHTML = '<div class="evidence-empty is-error"><strong>本次未取得完整结果</strong><span>比较生成已停止。你可以保留所选论文，直接重试原问题。</span></div>';
      showToast(message, "error");
    } finally {
      state.answering = false;
      renderResearchScope();
    }
  }

  function renderAll() {
    renderStats();
    renderRecent();
    renderLibrary();
    renderResearchScope();
  }

  function setLibraryLoading() {
    elements.libraryPagination.hidden = true;
    elements.libraryEmpty.classList.add("is-hidden");
    elements.libraryTable.closest(".table-wrap").classList.remove("is-hidden");
    elements.libraryTable.innerHTML = '<tr class="loading-row"><td colspan="6"><span></span>正在读取论文库…</td></tr>';
    elements.recentPapers.innerHTML = '<div class="inline-empty is-loading"><span>正在加载论文资料…</span></div>';
  }

  async function loadPapers({ quiet = false } = {}) {
    if (!quiet) setLibraryLoading();
    elements.refreshPapers.disabled = true;
    elements.refreshPapers.classList.add("is-spinning");
    try {
      const response = await fetch("/api/papers?limit=500", { headers: { Accept: "application/json" } });
      if (!response.ok) throw await responseError(response);
      const payload = await response.json();
      state.papers = Array.isArray(payload.items) ? payload.items : [];
      await window.TraceLibrary.load();
      state.total = Number(payload.total) || state.papers.length;
      renderToolPapers();
      renderAll();
      return state.papers;
    } catch (error) {
      state.papers = [];
      state.total = 0;
      renderAll();
      elements.recentPapers.innerHTML = '<div class="inline-empty is-error"><strong>论文库读取失败</strong><span>请检查网络和服务状态。</span></div>';
      elements.libraryTable.closest(".table-wrap").classList.add("is-hidden");
      elements.libraryEmpty.classList.remove("is-hidden");
      elements.libraryEmpty.querySelector("h3").textContent = "无法读取论文库";
      elements.libraryEmpty.querySelector("p").textContent = "请检查网络和服务状态，然后重新加载。";
      elements.libraryEmpty.querySelector("p").hidden = false;
      const retryButton = elements.libraryEmpty.querySelector("button");
      retryButton.hidden = false;
      retryButton.textContent = "重新加载";
      retryButton.dataset.retryLoad = "true";
      delete retryButton.dataset.goImport;
      delete retryButton.dataset.clearSearch;
      if (!quiet) showToast(friendlyError(error, "论文库读取失败。"), "error");
      return [];
    } finally {
      elements.refreshPapers.disabled = false;
      elements.refreshPapers.classList.remove("is-spinning");
    }
  }

  async function deletePaper(paperId) {
    if (window.TraceLibrary?.hasFolder()) return window.TraceLibrary.removeFromCurrentFolder(paperId);
    if (state.deletingPaperId) return;
    const paper = state.papers.find(item => item.paper_id === paperId);
    if (!paper) return;
    if (state.answering || state.retrieving) {
      showToast("请等待当前问答或检索结束后再删除论文。", "error");
      return;
    }
    const label = `${paperTitle(paper)}${paper.version_label ? `（${paper.version_label}）` : ""}\n文件：${paper.filename}`;
    if (!window.confirm(`确定永久删除这条论文记录吗？\n\n${label}\n\n将删除此记录的 PDF、识别文字和检索索引，无法撤销；其他版本不受影响。旧回答中指向该记录的引用将无法打开。`)) return;
    state.deletingPaperId = paperId;
    renderLibrary();
    try {
      const response = await fetch(`/api/papers/${encodeURIComponent(paperId)}`, { method: "DELETE" });
      if (!response.ok) throw await responseError(response);
      state.papers = state.papers.filter(item => item.paper_id !== paperId);
      state.total = Math.max(0, state.total - 1);
      state.comparisonPaperIds = state.comparisonPaperIds.filter(id => id !== paperId);
      if (elements.researchPaperScope.value === paperId) elements.researchPaperScope.value = "";
      state.pendingUpload = null;
      resetUploadPanel();
      clearAnswer();
      elements.evidenceResults.innerHTML = '<div class="evidence-empty">论文库已更新，请重新检索。</div>';
      elements.evidenceCount.textContent = "等待检索";
      ["graphResult", "recommendResult", "outlineResult"].forEach(id => { byId(id).textContent = "论文库已更新，请重新生成。"; });
      renderToolPapers();
      renderAll();
      await loadPapers({ quiet: true });
      showToast("已删除这条论文记录，其他版本不受影响。", "success");
    } catch (error) {
      showToast(friendlyError(error, "论文删除失败，请稍后重试。"), "error");
    } finally {
      state.deletingPaperId = null;
      renderLibrary();
    }
  }

  function openPaper(paperId, trigger = null, initialPage = 1) {
    const page = Math.max(1, Math.trunc(Number(initialPage)) || 1);
    const query = new URLSearchParams({ page: String(page), from: state.activeView });
    const quote = trigger?.dataset?.evidenceQuote;
    if (quote) query.set("highlight", quote.slice(0, 120));
    window.open(`/reader/${encodeURIComponent(paperId)}?${query}`, "_blank", "noopener");
  }

  function validateUpload(file) {
    if (!file) return "没有选择文件。";
    const looksLikePdf = file.type === "application/pdf" || file.name.toLocaleLowerCase().endsWith(".pdf");
    if (!looksLikePdf) return "请选择 PDF 文件。";
    if (file.size > MAX_UPLOAD_BYTES) return "文件超过 50 MiB 上传限制。";
    if (file.size === 0) return "不能上传空文件。";
    return "";
  }

  function showUploadProgress(file) {
    elements.largeDropzone.classList.add("is-hidden");
    elements.uploadResult.classList.add("is-hidden");
    elements.uploadProgress.classList.remove("is-hidden");
    elements.uploadFilename.textContent = `正在处理：${file.name}`;
  }

  function showUploadResult(paper, success = true, errorMessage = "") {
    elements.uploadProgress.classList.add("is-hidden");
    elements.uploadResult.classList.remove("is-hidden");
    if (!success) {
      elements.uploadResult.innerHTML = `
        <div class="result-card result-error">
          <span class="result-icon" aria-hidden="true">!</span>
          <div><strong>导入失败</strong><p>${escapeHtml(errorMessage)}</p><button class="secondary-button" type="button" data-upload-again>重新选择</button></div>
        </div>
      `;
      return;
    }

    const status = statusInfo(paper.parse_status);
    const relationNotice = versionRelationNotice(paper);
    const duplicateText = paper.duplicate
      ? "这篇论文已经在资料库中，本次未重复保存。"
      : paper.needs_ocr_pages?.length
        ? `文件已保存，${paper.needs_ocr_pages.length} 页扫描文字待识别。点击“查看原文”，在阅读页启动 OCR。`
        : relationNotice || "论文已保存，并完成逐页文本提取。";
    elements.uploadResult.innerHTML = `
      <div class="result-card result-success">
        <span class="result-icon" aria-hidden="true">✓</span>
        <div class="result-copy">
          <span class="section-kicker">${paper.duplicate ? "已识别重复文件" : "导入成功"}</span>
          <h3>${escapeHtml(paperTitle(paper))}</h3>
          <p>${duplicateText}</p>
          <div class="result-meta"><span>${paper.page_count} 页</span>${paperVersion(paper) ? `<span>${escapeHtml(paperVersion(paper))}</span>` : ""}<span class="status-badge ${status.className}">${status.label}</span></div>
          <div class="result-actions"><button class="primary-button" type="button" data-result-open="${escapeHtml(paper.paper_id)}">查看原文</button><button class="secondary-button" type="button" data-result-library>返回论文库</button><button class="text-button" type="button" data-upload-again>继续导入</button></div>
        </div>
      </div>
    `;
  }

  function resetUploadPanel({ choose = false } = {}) {
    state.pendingUpload = null;
    elements.uploadProgress.classList.add("is-hidden");
    elements.uploadResult.classList.add("is-hidden");
    elements.largeDropzone.classList.remove("is-hidden");
    elements.fileInput.value = "";
    if (choose) elements.fileInput.click();
  }

  function setImportCollection(collection) {
    state.importCollection = collection ? {id: collection.id, name: collection.name} : null;
    const notice = byId("importCollectionNotice");
    notice.hidden = !collection;
    notice.innerHTML = collection ? `<div><strong>上传到：${escapeHtml(collection.name)}</strong><span>同时保存到“全部论文”，按入库时间从新到旧显示。</span></div><button type="button" class="text-button" data-clear-import-collection>改为仅入库</button>` : "";
  }

  function chooseCollectionUpload(collection) {
    if (state.uploading) { showToast("请等待当前上传完成。", "error"); return; }
    state.collectionPickerTarget = {id: collection.id, name: collection.name};
    byId("collectionFileInput").value = "";
    byId("collectionFileInput").click();
  }

  async function uploadFile(file, decision = {}) {
    const validationError = validateUpload(file);
    if (validationError) {
      showToast(validationError, "error");
      return;
    }
    if (state.uploading) {
      showToast("当前已有文件正在处理，请稍候。", "error");
      return;
    }

    state.uploading = true;
    navigateTo("import");
    showUploadProgress(file);
    const savedNotes = state.pendingUpload?.notes;
    const collection = state.pendingUpload ? state.pendingUpload.collection : state.importCollection;
    state.pendingUpload = null;
    const formData = new FormData();
    formData.append("file", file, file.name);
    const notes = savedNotes ?? byId("importNotes").value;
    formData.append("notes", notes);
    if (collection) formData.append("collection_id", collection.id);
    formData.append("conflict_action", decision.action || "ask");
    if (decision.target) {
      formData.append("target_paper_id", decision.target.paper_id);
      formData.append("target_sha256", decision.target.sha256);
    }

    try {
      const response = await fetch("/api/papers", { method: "POST", body: formData });
      if (response.status === 409 && !decision.action) {
        const conflict = await response.json();
        if (conflict.conflict) {
          state.pendingUpload = { file, conflict, notes, collection };
          elements.uploadProgress.classList.add("is-hidden");
          elements.uploadResult.classList.remove("is-hidden");
          const newer = conflict.recommendation === "keep_existing_newer";
          elements.uploadResult.innerHTML = `<div class="result-card version-conflict"><div class="result-copy">
            <span class="section-kicker">发现关联论文 · 尚未入库</span>
            <h3>${newer ? "资料库中已有更新版本" : "请确认如何保存这份资料"}</h3>
            <p class="conflict-incoming">本次：${escapeHtml(conflict.incoming.filename)} · ${escapeHtml(conflict.incoming.version_label || "版本未知")}</p>
            <div class="conflict-matches">${conflict.matches.map(m => `<article class="conflict-match"><strong>${escapeHtml(paperTitle(m.paper))}</strong><span>${escapeHtml(m.paper.version_label || "版本未知")} · ${m.basis === "content_overlap" ? "正文相似" : m.basis === "identifier_and_content" ? "标识与正文匹配" : "论文标识匹配"} · 正文重合率 ${Math.round(m.score * 100)}%</span></article>`).join("")}</div>
            <p>${newer ? "建议保留库中新版。可取消本次导入，或保留两版用于对照。" : "相似内容可能属于不同工作，请先核对再选择。"}</p>
            <div class="result-actions"><button class="primary-button" type="button" data-version-action="cancel">取消本次导入</button>
            <button class="secondary-button" type="button" data-version-action="keep_both">保留两个版本</button></div>
            <details class="conflict-replace"><summary>替换指定记录</summary><p>目标将退出论文库，旧文件继续保留供历史引用查看。上传旧版会使当前库使用旧版，请谨慎确认。</p>
            <select id="replaceTarget">${conflict.matches.map(m => `<option value="${escapeHtml(m.paper.paper_id)}">${escapeHtml(m.paper.filename)} ${escapeHtml(m.paper.version_label || "")}</option>`).join("")}</select>
            <button class="secondary-button" type="button" data-version-action="replace">确认替换所选记录</button></details>
          </div></div>`;
          return;
        }
      }
      if (!response.ok) throw await responseError(response);
      const paper = await response.json();
      state.pendingUpload = null;
      if (!paper.duplicate) byId("importNotes").value = "";
      showUploadResult(paper, true);
      await loadPapers({ quiet: true });
      showToast(collection ? "已收纳到“" + collection.name + "”，论文也保留在全部论文中。" : paper.duplicate ? "论文已存在，已为你打开原有记录。" : "论文导入成功。", "success");
    } catch (error) {
      const message = friendlyError(error, "文件导入失败，请重试。");
      showUploadResult(null, false, message);
      showToast(message, "error");
    } finally {
      state.uploading = false;
      elements.fileInput.value = "";
    }
  }

  function renderToolPapers() {
    const root = byId("toolPaperList");
    const selected = new Set(Array.from(root.querySelectorAll("input:checked")).map(i => i.value));
    root.innerHTML = state.papers.map(p => `<label><input type="checkbox" value="${escapeHtml(p.paper_id)}"${selected.has(p.paper_id) ? " checked" : ""}><span>${escapeHtml(paperTitle(p))}<small>${escapeHtml(p.version_label || "版本未知")} · ${p.page_count} 页</small></span></label>`).join("") || '<p>请先导入研究论文。</p>';
  }

  function toolPaperIds() {
    const ids = Array.from(byId("toolPaperList").querySelectorAll("input:checked")).map(i => i.value);
    if (!ids.length || ids.length > 30) throw new Error("请选择 1–30 篇研究论文。");
    return ids;
  }

  async function toolRequest(url, body) {
    const response = await fetch(url, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!response.ok) throw await responseError(response);
    return response.json();
  }

  function downloadText(value, name, type = "text/plain") {
    const url = URL.createObjectURL(new Blob([value], { type }));
    const link = document.createElement("a"); link.href = url; link.download = name; link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function runTool(buttonId, outputId, action) {
    const button = byId(buttonId), output = byId(outputId);
    button.disabled = true;
    output.textContent = "正在处理…";
    try { await action(output); }
    catch (error) { output.textContent = friendlyError(error, "本次处理失败，请重试。"); }
    finally { button.disabled = false; }
  }

  async function buildCitationGraph() {
    return runTool("buildGraph", "graphResult", async output => {
      const graph = await toolRequest("/api/library/graph", { paper_ids: toolPaperIds() });
      const positions = new Map(graph.nodes.map((n, i) => {
        const angle = 2 * Math.PI * i / graph.nodes.length - Math.PI / 2;
        return [n.id, { x: 250 + 175 * Math.cos(angle), y: 210 + 155 * Math.sin(angle) }];
      }));
      const lines = graph.edges.map(e => {
        const a = positions.get(e.source), b = positions.get(e.target);
        return `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="#b7bfdc" stroke-width="2" marker-end="url(#arrow)" />`;
      }).join("");
      const nodes = graph.nodes.map((n, i) => {
        const { x, y } = positions.get(n.id);
        return `<g class="graph-node" role="button" tabindex="0" data-paper-id="${escapeHtml(n.id)}" aria-label="${escapeHtml(n.title)}"><title>${escapeHtml(n.title)}</title><circle cx="${x}" cy="${y}" r="23" fill="#5965d8" stroke="white" stroke-width="3"/><text x="${x}" y="${y + 5}" fill="white" text-anchor="middle">${i + 1}</text></g>`;
      }).join("");
      output.innerHTML = `<svg class="citation-graph" viewBox="0 0 500 420" aria-label="当前论文引用子图"><defs><marker id="arrow" markerWidth="10" markerHeight="8" refX="24" refY="4" orient="auto"><path d="M0,0 L10,4 L0,8" fill="#a5afce"/></marker></defs>${lines}${nodes}</svg><p class="tool-hint">${escapeHtml(graph.scope)}</p><div class="tool-result-list">${graph.nodes.map((n, i) => `<button class="tool-result-card" data-paper-id="${escapeHtml(n.id)}"><strong>${i + 1}. ${escapeHtml(n.title)}</strong><small>入边 ${n.incoming} · PageRank ${n.pagerank}</small></button>`).join("")}</div>${graph.edges.length ? `<details><summary>核对引用边及原文（${graph.edges.length}）</summary>${graph.edges.map(e => `<button class="tool-result-card" data-evidence-paper="${escapeHtml(e.source)}" data-evidence-page="${e.page}"><strong>第 ${e.page} 页参考文献 → ${escapeHtml(graph.nodes.find(n => n.id === e.target).title)}</strong><span>${escapeHtml(e.evidence)}</span></button>`).join("")}</details>` : '<p>当前没有核验到库内引用边。可选择存在引用关系的论文再试；系统不会补造连线。</p>'}<button class="text-button" id="downloadGraph">下载图谱 JSON</button>`;
      byId("downloadGraph").onclick = () => downloadText(JSON.stringify(graph, null, 2), "citation-graph.json", "application/json");
    });
  }

  async function recommendLocalPapers() {
    return runTool("recommendPapers", "recommendResult", async output => {
      const data = await toolRequest(`/api/library/recommendations/${toolPaperIds()[0]}`);
      output.innerHTML = data.items.map(item => `<button class="tool-result-card" data-paper-id="${escapeHtml(item.paper.paper_id)}"><strong>${escapeHtml(paperTitle(item.paper))}</strong><span>${escapeHtml(item.reason)}</span><small>相似度 ${item.score} · 点开核对论文</small></button>`).join("") || '<p>没有找到可推荐的其他研究工作。请补充论文题名与摘要，或导入相关论文。</p>';
      output.insertAdjacentHTML("beforeend", `<p class="tool-hint">${escapeHtml(data.method)}</p>`);
    });
  }

  async function createResearchOutline(generate) {
    if (!validateText("outlineIdea", "outlineError")) return;
    return runTool(generate ? "draftOutline" : "planOutline", "outlineResult", async output => {
      const data = await toolRequest("/api/library/outline", { paper_ids: toolPaperIds(), idea: byId("outlineIdea").value.trim(), generate });
      const evidence = data.draft?.citations || data.evidence;
      output.innerHTML = `<div class="outline-sections">${data.sections.map(s => `<article><h4>${escapeHtml(s.title)}</h4><p>${escapeHtml(s.guidance)}</p></article>`).join("")}</div>${data.draft?.answer ? `<div class="translation-result">${escapeHtml(data.draft.answer)}</div>` : ""}<details open><summary>真实参考文献（仅所选库内记录）</summary>${data.references.map(r => `<button class="tool-result-card" data-paper-id="${escapeHtml(r.paper_id)}"><strong>[${r.label}] ${escapeHtml(r.title)}</strong><span>${escapeHtml(r.authors.join(", "))}</span><small>${escapeHtml(r.arxiv_id || r.doi || "元数据未报告 DOI/arXiv，不补造")}</small></button>`).join("")}</details><details><summary>查看提纲依据</summary>${evidence.map((e, i) => `<button class="tool-result-card" data-evidence-paper="${escapeHtml(e.source.paper_id)}" data-evidence-page="${e.source.page_start}"><strong>[${escapeHtml(e.citation_id || `E${i + 1}`)}] ${escapeHtml(e.paper_title || e.filename)} · 第 ${e.source.page_start} 页</strong><span>${escapeHtml(e.text)}</span></button>`).join("")}</details><div class="tool-actions"><button class="text-button" id="downloadOutline">下载 Markdown</button><button class="text-button" id="downloadDiagram">下载 Mermaid 流程脚本</button></div>`;
      byId("downloadDiagram").onclick = () => downloadText(data.mermaid, "research-workflow.mmd");
      byId("downloadOutline").onclick = () => {
        const md = `# ${data.idea}\n\n${data.sections.map(s => `## ${s.title}\n\n${s.guidance}`).join("\n\n")}\n\n${data.draft?.answer || ""}\n\n## References\n\n${data.references.map(r => `[${r.label}] ${r.authors.join(", ")}. ${r.title}. ${r.arxiv_id || r.doi || ""}`).join("\n\n")}\n\n## Evidence\n\n${evidence.map((e, i) => `[${e.citation_id || `E${i + 1}`}] ${e.paper_title || e.filename}, page ${e.source.page_start}\n${e.text}`).join("\n\n")}`;
        downloadText(md, "research-outline.md", "text/markdown");
      };
    });
  }

  async function searchArxiv() {
    if (!validateText("arxivQuery", "arxivError")) return;
    return runTool("searchArxiv", "arxivResult", async output => {
      const data = await toolRequest("/api/library/search", { query: byId("arxivQuery").value.trim() });
      output.innerHTML = data.items.map(item => `<article class="tool-result-card"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.authors.join(", "))}</small><span>${escapeHtml(item.summary)}</span><div class="tool-actions"><a href="https://arxiv.org/abs/${encodeURIComponent(item.arxiv_id)}" target="_blank" rel="noopener">查看 arXiv</a><button class="secondary-button" data-import-arxiv="${escapeHtml(item.arxiv_id)}">确认导入 ${escapeHtml(item.arxiv_id)}</button></div></article>`).join("") || '<p>未找到完全匹配的结果，可用题名中的几个关键词重试。</p>';
    });
  }

  async function importArxiv(button) {
    const identifier = button.dataset.importArxiv;
    button.disabled = true; button.textContent = "正在导入…";
    try {
      const response = await fetch("/api/library/import", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ arxiv_id: identifier, conflict_action: "ask" }) });
      if (response.status === 409) {
        const result = await response.json();
        if (result.conflict) { button.textContent = "已有关联版本，请手动下载后选择保留／替换"; return; }
        throw new Error(result.detail || "关联论文状态已变化，请重试。");
      }
      if (!response.ok) throw await responseError(response);
      const paper = await response.json(); await loadPapers({ quiet: true });
      button.textContent = paper.duplicate ? "库中已有此文件" : "已导入，点击查看";
      button.onclick = () => openPaper(paper.paper_id, button);
      delete button.dataset.importArxiv;
    } catch (error) { button.textContent = "重试导入"; showToast(friendlyError(error, "导入失败。"), "error"); }
    finally { button.disabled = false; }
  }

  async function buildCsvChart(event) {
    event.preventDefault();
    return runTool("buildChart", "chartResult", async output => {
      const file = byId("chartFile").files[0];
      if (!file || file.size > 1024 * 1024) throw new Error("请选择不超过 1 MiB 的 UTF-8 CSV。");
      const body = new FormData(); body.append("file", file); body.append("x", byId("chartX").value); body.append("y", byId("chartY").value); body.append("kind", byId("chartKind").value); body.append("z", byId("chartZ").value);
      const response = await fetch("/api/library/chart", { method: "POST", body });
      if (!response.ok) throw await responseError(response);
      const data = await response.json();
      output.innerHTML = '<img class="csv-figure" alt="由上传数据生成的图表" id="chartImage"><p id="chartCaption"></p><div class="tool-actions"><a id="downloadChart" class="text-button" download="figure.png">下载 PNG</a><button id="downloadChartScript" class="text-button">下载 Python 脚本</button></div>';
      byId("chartImage").src = data.image; byId("downloadChart").href = data.image; byId("chartCaption").textContent = data.caption;
      byId("downloadChartScript").onclick = () => downloadText(data.script, "plot.py", "text/x-python");
    });
  }

  function bindDropzone(dropzone) {
    const openPicker = () => {
      if (!state.uploading) elements.fileInput.click();
    };
    dropzone.addEventListener("click", openPicker);
    dropzone.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openPicker();
      }
    });
    ["dragenter", "dragover"].forEach((eventName) => {
      dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        if (!state.uploading) dropzone.classList.add("is-dragging");
      });
    });
    ["dragleave", "drop"].forEach((eventName) => {
      dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        dropzone.classList.remove("is-dragging");
      });
    });
    dropzone.addEventListener("drop", (event) => {
      const files = Array.from(event.dataTransfer?.files || []);
      if (files.length > 1) { navigateTo("import"); window.TraceBatch.addFiles(files); }
      else uploadFile(files[0]);
    });
  }

  function bindEvents() {
    byId("buildGraph").addEventListener("click", buildCitationGraph);
    byId("recommendPapers").addEventListener("click", recommendLocalPapers);
    byId("planOutline").addEventListener("click", () => createResearchOutline(false));
    byId("draftOutline").addEventListener("click", () => createResearchOutline(true));
    byId("searchArxiv").addEventListener("click", searchArxiv);
    byId("chartForm").addEventListener("submit", buildCsvChart);
    elements.mobileMenu.setAttribute("aria-expanded", "false");
    elements.mobileMenu.addEventListener("click", () => {
      elements.sidebar.classList.contains("is-open") ? closeMobileNavigation() : openMobileNavigation();
    });

    all(".nav-item[data-view]").forEach((button) => button.addEventListener("click", () => navigateTo(button.dataset.view)));

    elements.searchInput.addEventListener("input", () => {
      elements.librarySearch.value = elements.searchInput.value;
      renderLibrary();
    });
    elements.searchInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") navigateTo("library");
    });
    elements.librarySearch.addEventListener("input", () => {
      elements.searchInput.value = elements.librarySearch.value;
      renderLibrary();
    });

    elements.refreshPapers.addEventListener("click", () => loadPapers());
    elements.researchForm.addEventListener("submit", (event) => {
      event.preventDefault();
      if (state.comparisonMode) {
        generateComparison();
      } else {
        retrieveEvidence();
      }
    });
    byId("searchMentions").addEventListener("click", () => searchLibraryMentions());
    [["arxivQuery","arxivError"],["outlineIdea","outlineError"],["researchQuestion","researchError"]].forEach(([id,error]) => byId(id).addEventListener("input", () => {byId(error).hidden=true;byId(id).removeAttribute("aria-invalid");}));
    elements.evidenceResults.addEventListener("click", event => {const button=event.target.closest("[data-mentions-page]");if(button&&!button.disabled)searchLibraryMentions(Number(button.dataset.mentionsPage));});
    elements.researchAnswer.addEventListener("click", generateAnswer);
    elements.comparisonModeToggle.addEventListener("click", () => {
      if (!state.comparisonMode && elements.researchPaperScope.value && !state.comparisonPaperIds.length) {
        state.comparisonPaperIds = [elements.researchPaperScope.value];
      }
      state.comparisonMode = !state.comparisonMode;
      renderResearchScope();
    });
    elements.comparisonPaperList.addEventListener("change", () => {
      refreshComparisonSelection();
    });
    elements.researchCompare.addEventListener("click", generateComparison);
    elements.fileInput.addEventListener("change", () => uploadFile(elements.fileInput.files?.[0]));
    byId("collectionFileInput").addEventListener("change", () => {
      const files = Array.from(byId("collectionFileInput").files || []);
      if (!files.length) return;
      setImportCollection(state.collectionPickerTarget);
      resetUploadPanel();
      navigateTo("import");
      if (files.length > 1) window.TraceBatch.addFiles(files);
      else { window.TraceBatch.setMode(false); uploadFile(files[0]); }
    });
    bindDropzone(elements.largeDropzone);

    document.addEventListener("click", (event) => {
      const pageButton = event.target.closest("[data-library-page]");
      if (pageButton && !pageButton.disabled) {
        state.libraryPage = Number(pageButton.dataset.libraryPage);
        renderLibrary();
        byId("libraryPanel").scrollIntoView({block: "start", behavior: "smooth"});
        elements.libraryPagination.querySelector('[aria-current="page"]')?.focus({preventScroll: true});
        return;
      }
      const deleteButton = event.target.closest("[data-delete-paper]");
      if (deleteButton) { deletePaper(deleteButton.dataset.deletePaper); return; }
      const importButton = event.target.closest("[data-import-arxiv]");
      if (importButton) importArxiv(importButton);
      const versionAction = event.target.closest("[data-version-action]");
      if (versionAction && state.pendingUpload && !state.uploading) {
        const { file, conflict } = state.pendingUpload;
        const action = versionAction.dataset.versionAction;
        if (action === "cancel") { state.pendingUpload = null; resetUploadPanel(); showToast("已保留原记录，本次未导入。", "success"); }
        else {
          const target = conflict.matches.find(m => m.paper.paper_id === byId("replaceTarget")?.value)?.paper;
          uploadFile(file, { action, target });
        }
      }
      if (event.target.closest("[data-go-import]")) {
        if (!state.uploading && !state.pendingUpload) setImportCollection(null);
        navigateTo("import");
      }
      if (event.target.closest("[data-clear-import-collection]") && !state.uploading && !state.pendingUpload) setImportCollection(null);
      if (event.target.closest("[data-go-library]")) navigateTo("library");

      const paperButton = event.target.closest("[data-paper-id]");
      if (paperButton) openPaper(paperButton.dataset.paperId, paperButton);

      const resultOpen = event.target.closest("[data-result-open]");
      if (resultOpen) openPaper(resultOpen.dataset.resultOpen, resultOpen);
      const evidenceOpen = event.target.closest("[data-evidence-paper]");
      if (evidenceOpen) openPaper(evidenceOpen.dataset.evidencePaper, evidenceOpen, evidenceOpen.dataset.evidencePage);
      if (event.target.closest("[data-result-library]")) navigateTo("library");
      if (event.target.closest("[data-upload-again]")) resetUploadPanel({ choose: true });
      if (event.target.closest("[data-clear-search]")) {
        elements.searchInput.value = "";
        elements.librarySearch.value = "";
        renderLibrary();
        elements.librarySearch.focus();
      }
      if (event.target.closest("[data-retry-load]")) loadPapers();
    });

    document.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLocaleLowerCase() === "k") {
        event.preventDefault();
        if (state.activeView !== "overview") navigateTo("library");
        const search = state.activeView === "overview" ? elements.searchInput : elements.librarySearch;
        search.focus();
        search.select();
      }
      if (event.key === "Escape") closeMobileNavigation();
    });

    document.querySelector(".workspace").addEventListener("click", (event) => {
      if (elements.sidebar.classList.contains("is-open") && !event.target.closest("#mobileMenu")) closeMobileNavigation();
    });
  }

  async function initialize() {
    window.TraceBatch.init({ reload: () => loadPapers({ quiet: true }), collection: () => state.importCollection });
    window.TraceLibrary.init({ render: renderLibrary, reload: () => loadPapers({ quiet: true }), papers: () => state.papers, toast: showToast, upload: chooseCollectionUpload });
    bindEvents();
    const initialView = new URLSearchParams(window.location.search).get("view");
    navigateTo(Object.hasOwn(viewLabels, initialView) ? initialView : "overview");
    await Promise.all([checkHealth(), loadPapers()]);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
