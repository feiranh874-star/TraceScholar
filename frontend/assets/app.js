(() => {
  "use strict";

  const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;
  const viewLabels = {
    overview: { eyebrow: "研究资料总览", title: "科研工作台" },
    library: { eyebrow: "可信科研知识库", title: "论文库" },
    import: { eyebrow: "PDF 解析入库", title: "导入资料" },
    research: { eyebrow: "本地可信检索", title: "证据检索" },
  };

  const state = {
    papers: [],
    total: 0,
    currentPaper: null,
    currentPage: 1,
    activeView: "overview",
    uploading: false,
    retrieving: false,
    answering: false,
    comparisonMode: false,
    comparisonPaperIds: [],
    drawerReturnFocus: null,
    detailRequestId: 0,
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
    refreshPapers: byId("refreshPapers"),
    fileInput: byId("fileInput"),
    miniDropzone: byId("miniDropzone"),
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
    drawer: byId("paperDrawer"),
    drawerBackdrop: byId("drawerBackdrop"),
    closeDrawer: byId("closeDrawer"),
    drawerTitle: byId("drawerTitle"),
    drawerMetadata: byId("drawerMetadata"),
    drawerWarning: byId("drawerWarning"),
    readerPageLabel: byId("readerPageLabel"),
    pageNumber: byId("pageNumber"),
    pageTotal: byId("pageTotal"),
    prevPage: byId("prevPage"),
    nextPage: byId("nextPage"),
    pageText: byId("pageText"),
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
    return paper.author?.trim() || "未填写作者";
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
    const value = String(detail || "");
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
    if (/模型服务尚未配置|LLM_API_KEY/i.test(value)) return "DeepSeek 尚未配置，请在本地 .env 或 Render Environment 中设置模型信息。";
    if (/DeepSeek/i.test(value)) return value;
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
    if (view === "research") renderResearchScope();
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
    if (!query) return state.papers;
    return state.papers.filter((paper) =>
      [paper.title, paper.author, paper.filename]
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

  function paperListItem(paper) {
    const status = statusInfo(paper.parse_status);
    const version = paperVersion(paper);
    return `
      <button class="paper-list-item" type="button" data-paper-id="${escapeHtml(paper.paper_id)}">
        <span class="paper-type-icon" aria-hidden="true">PDF</span>
        <span class="paper-list-copy">
          <strong class="paper-list-title">${escapeHtml(paperTitle(paper))}</strong>
          <span class="paper-list-meta">${escapeHtml(paperAuthor(paper))}${version ? ` · ${escapeHtml(version)}` : ""} · ${paper.page_count} 页 · ${formatDate(paper.created_at)}</span>
        </span>
        <span class="status-badge ${status.className}">${status.label}</span>
        <span class="paper-list-arrow" aria-hidden="true">→</span>
      </button>
    `;
  }

  function renderRecent() {
    if (!state.papers.length) {
      elements.recentPapers.innerHTML = `
        <div class="inline-empty">
          <strong>还没有导入论文</strong>
          <span>从右侧快速导入一篇 PDF 开始。</span>
        </div>
      `;
      return;
    }
    elements.recentPapers.innerHTML = state.papers.slice(0, 4).map(paperListItem).join("");
  }

  function renderLibrary() {
    const papers = filteredPapers();
    const hasAnyPapers = state.papers.length > 0;
    const hasSearch = Boolean(searchQuery());
    elements.libraryEmpty.classList.toggle("is-hidden", papers.length > 0);
    elements.libraryTable.closest(".table-wrap").classList.toggle("is-hidden", papers.length === 0);

    if (!papers.length) {
      elements.libraryTable.innerHTML = "";
      const heading = elements.libraryEmpty.querySelector("h3");
      const description = elements.libraryEmpty.querySelector("p");
      const action = elements.libraryEmpty.querySelector("button");
      if (hasAnyPapers && hasSearch) {
        heading.textContent = "没有找到匹配的论文";
        description.textContent = "试试题名、作者或文件名中的其他关键词。";
        action.textContent = "清除搜索";
        action.dataset.clearSearch = "true";
        delete action.dataset.goImport;
        delete action.dataset.retryLoad;
      } else {
        heading.textContent = "论文库还是空的";
        description.textContent = "导入第一篇 PDF，开始建立可信科研知识库。";
        action.textContent = "导入第一篇论文";
        action.dataset.goImport = "true";
        delete action.dataset.clearSearch;
        delete action.dataset.retryLoad;
      }
      return;
    }

    elements.libraryTable.innerHTML = papers
      .map((paper) => {
        const status = statusInfo(paper.parse_status);
        return `
          <tr>
            <td>
              <button class="table-paper" type="button" data-paper-id="${escapeHtml(paper.paper_id)}">
                <span class="table-paper-icon" aria-hidden="true">PDF</span>
                <span><strong class="table-paper-title">${escapeHtml(paperTitle(paper))}</strong><small class="table-paper-file">${escapeHtml(paper.filename)}${paperVersion(paper) ? ` · ${escapeHtml(paperVersion(paper))}` : ""}</small></span>
              </button>
            </td>
            <td>${escapeHtml(paperAuthor(paper))}</td>
            <td>${paper.page_count} 页</td>
            <td><span class="status-badge ${status.className}">${status.label}</span></td>
            <td>${formatDate(paper.created_at, true)}</td>
            <td><button class="open-paper-button" type="button" data-paper-id="${escapeHtml(paper.paper_id)}" aria-label="查看 ${escapeHtml(paperTitle(paper))}">查看</button></td>
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
      ? '返回单篇检索 <span>→</span>'
      : '切换到多篇比较 <span>→</span>';
    elements.comparisonModeToggle.disabled = state.answering || state.retrieving;
    refreshComparisonSelection();
    elements.researchPaperScope.disabled = state.papers.length === 0;
    elements.researchSubmit.disabled = state.retrieving || state.papers.length === 0;
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
        if (rows.length) blocks.push(renderComparisonCards(headers, rows));
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
    elements.answerModel.textContent = payload.model ? `模型：${payload.model}` : "本地工具编排";
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
      return `<button type="button" data-evidence-paper="${escapeHtml(source.paper_id)}" data-evidence-page="${Number(source.page_start) || 1}"><strong>[${escapeHtml(item.citation_id)}] ${escapeHtml(item.paper_title || item.filename)}</strong><span>${escapeHtml([sectionTitle, source.version_label, pageLabel].filter(Boolean).join(" · "))}</span></button>`;
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
              <button class="evidence-open" type="button" data-evidence-paper="${escapeHtml(source.paper_id)}" data-evidence-page="${Number(source.page_start) || 1}">打开论文 · ${escapeHtml(pageLabel)} <span>→</span></button>
            </details>
          </article>
        `;
      })
      .join("");
  }

  async function retrieveEvidence() {
    const question = elements.researchQuestion.value.trim();
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
      state.total = Number(payload.total) || state.papers.length;
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
      const retryButton = elements.libraryEmpty.querySelector("button");
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

  function renderMetadata(paper) {
    const status = statusInfo(paper.parse_status);
    const items = [
      ["作者", paperAuthor(paper)],
      ["原始文件", paper.filename],
      ["页数", `${paper.page_count} 页`],
      ["arXiv", paper.arxiv_id || "未识别"],
      ["版本", paperVersion(paper) || "未识别"],
      ["章节 / 文本块", `${paper.section_count || 0} / ${paper.chunk_count || 0}`],
      ["解析状态", status.label],
      ["导入时间", formatDate(paper.created_at, true)],
      ["文件指纹", paper.sha256 ? paper.sha256.slice(0, 12) + "…" : "未生成"],
    ];
    elements.drawerMetadata.innerHTML = items
      .map(([label, value]) => `<div class="metadata-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`)
      .join("");

    const warnings = Array.isArray(paper.warnings) ? paper.warnings.map(localizeWarning) : [];
    const relationNotice = versionRelationNotice(paper);
    if (relationNotice) warnings.unshift(relationNotice);
    if (warnings.length) {
      elements.drawerWarning.classList.remove("is-hidden");
      elements.drawerWarning.innerHTML = `<strong>解析与版本提示</strong><ul>${warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("")}</ul>`;
    } else {
      elements.drawerWarning.classList.add("is-hidden");
      elements.drawerWarning.innerHTML = "";
    }
  }

  async function openPaper(paperId, trigger = document.activeElement, initialPage = 1) {
    const requestId = ++state.detailRequestId;
    state.currentPaper = null;
    state.drawerReturnFocus = trigger instanceof HTMLElement ? trigger : null;
    const listedPaper = state.papers.find((paper) => paper.paper_id === paperId);
    elements.drawerTitle.textContent = listedPaper ? paperTitle(listedPaper) : "正在读取论文…";
    elements.drawer.classList.add("is-open");
    elements.drawerBackdrop.classList.add("is-visible");
    elements.drawer.setAttribute("aria-hidden", "false");
    elements.drawer.setAttribute("role", "dialog");
    elements.drawer.setAttribute("aria-modal", "true");
    document.body.classList.add("drawer-open");
    elements.drawerMetadata.innerHTML = "";
    elements.drawerWarning.classList.add("is-hidden");
    elements.drawerWarning.innerHTML = "";
    elements.prevPage.disabled = true;
    elements.nextPage.disabled = true;
    elements.pageNumber.disabled = true;
    elements.pageText.innerHTML = '<div class="reader-placeholder is-loading">正在读取论文详情…</div>';
    window.setTimeout(() => elements.closeDrawer.focus(), 80);

    try {
      const response = await fetch(`/api/papers/${encodeURIComponent(paperId)}`, { headers: { Accept: "application/json" } });
      if (!response.ok) throw await responseError(response);
      const paper = await response.json();
      if (requestId !== state.detailRequestId) return;
      state.currentPaper = paper;
      state.currentPage = Math.min(paper.page_count, Math.max(1, Number(initialPage) || 1));
      elements.pageNumber.disabled = false;
      elements.drawerTitle.textContent = paperTitle(paper);
      elements.pageNumber.max = String(paper.page_count);
      elements.pageTotal.textContent = `/ ${paper.page_count}`;
      renderMetadata(paper);
      await loadPage(state.currentPage);
    } catch (error) {
      if (requestId !== state.detailRequestId) return;
      const message = friendlyError(error, "论文详情读取失败。");
      elements.pageText.innerHTML = `<div class="reader-placeholder is-error">${escapeHtml(message)}</div>`;
      showToast(message, "error");
    }
  }

  function closeDrawer() {
    state.detailRequestId += 1;
    elements.drawer.classList.remove("is-open");
    elements.drawerBackdrop.classList.remove("is-visible");
    elements.drawer.setAttribute("aria-hidden", "true");
    document.body.classList.remove("drawer-open");
    const focusTarget = state.drawerReturnFocus;
    state.drawerReturnFocus = null;
    if (focusTarget?.isConnected) focusTarget.focus();
  }

  function updatePageControls(page) {
    const total = Number(state.currentPaper?.page_count) || 1;
    elements.pageNumber.value = String(page);
    elements.readerPageLabel.textContent = `第 ${page} 页`;
    elements.prevPage.disabled = page <= 1;
    elements.nextPage.disabled = page >= total;
  }

  async function loadPage(pageNumber) {
    if (!state.currentPaper) return;
    const total = Number(state.currentPaper.page_count) || 1;
    const page = Math.min(total, Math.max(1, Number(pageNumber) || 1));
    const requestedPaperId = state.currentPaper.paper_id;
    state.currentPage = page;
    updatePageControls(page);
    elements.pageText.classList.remove("needs-ocr");
    elements.pageText.innerHTML = '<div class="reader-placeholder is-loading">正在读取本页原文…</div>';

    try {
      const response = await fetch(`/api/papers/${encodeURIComponent(requestedPaperId)}/pages/${page}`, { headers: { Accept: "application/json" } });
      if (!response.ok) throw await responseError(response);
      const payload = await response.json();
      if (state.currentPaper?.paper_id !== requestedPaperId || state.currentPage !== page) return;
      if (payload.text?.trim()) {
        elements.pageText.textContent = payload.text;
        elements.pageText.classList.toggle("needs-ocr", Boolean(payload.needs_ocr));
      } else {
        elements.pageText.classList.add("needs-ocr");
        elements.pageText.innerHTML = `
          <div class="page-empty page-ocr">
            <strong>本页没有可读取的文字</strong>
            <span>这可能是扫描页，后续接入 OCR 后可继续识别。</span>
          </div>
        `;
      }
    } catch (error) {
      elements.pageText.innerHTML = `<div class="reader-placeholder is-error">${escapeHtml(friendlyError(error, "本页读取失败。"))}</div>`;
    }
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
    elements.uploadProgress.classList.add("is-hidden");
    elements.uploadResult.classList.add("is-hidden");
    elements.largeDropzone.classList.remove("is-hidden");
    elements.fileInput.value = "";
    if (choose) elements.fileInput.click();
  }

  async function uploadFile(file) {
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
    const formData = new FormData();
    formData.append("file", file, file.name);

    try {
      const response = await fetch("/api/papers", { method: "POST", body: formData });
      if (!response.ok) throw await responseError(response);
      const paper = await response.json();
      showUploadResult(paper, true);
      await loadPapers({ quiet: true });
      showToast(paper.duplicate ? "论文已存在，已为你打开原有记录。" : "论文导入成功。", "success");
    } catch (error) {
      const message = friendlyError(error, "文件导入失败，请重试。");
      showUploadResult(null, false, message);
      showToast(message, "error");
    } finally {
      state.uploading = false;
      elements.fileInput.value = "";
    }
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
    dropzone.addEventListener("drop", (event) => uploadFile(event.dataTransfer?.files?.[0]));
  }

  function bindEvents() {
    elements.mobileMenu.setAttribute("aria-expanded", "false");
    elements.mobileMenu.addEventListener("click", () => {
      elements.sidebar.classList.contains("is-open") ? closeMobileNavigation() : openMobileNavigation();
    });

    all(".nav-item[data-view]").forEach((button) => button.addEventListener("click", () => navigateTo(button.dataset.view)));
    byId("topUploadButton").addEventListener("click", () => navigateTo("import"));

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
    bindDropzone(elements.miniDropzone);
    bindDropzone(elements.largeDropzone);

    document.addEventListener("click", (event) => {
      if (event.target.closest("[data-go-import]")) navigateTo("import");
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

    elements.closeDrawer.addEventListener("click", closeDrawer);
    elements.drawerBackdrop.addEventListener("click", closeDrawer);
    elements.prevPage.addEventListener("click", () => loadPage(state.currentPage - 1));
    elements.nextPage.addEventListener("click", () => loadPage(state.currentPage + 1));
    elements.pageNumber.addEventListener("change", () => loadPage(elements.pageNumber.value));
    elements.pageNumber.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        loadPage(elements.pageNumber.value);
      }
    });

    document.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLocaleLowerCase() === "k") {
        event.preventDefault();
        elements.searchInput.focus();
        elements.searchInput.select();
      }
      if (event.key === "Escape") {
        if (elements.drawer.classList.contains("is-open")) closeDrawer();
        else closeMobileNavigation();
      }
      if (event.key === "Tab" && elements.drawer.classList.contains("is-open")) {
        const focusable = all('button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])', elements.drawer);
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    });

    document.querySelector(".workspace").addEventListener("click", (event) => {
      if (elements.sidebar.classList.contains("is-open") && !event.target.closest("#mobileMenu")) closeMobileNavigation();
    });
  }

  async function initialize() {
    bindEvents();
    navigateTo("overview");
    await Promise.all([checkHealth(), loadPapers()]);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
