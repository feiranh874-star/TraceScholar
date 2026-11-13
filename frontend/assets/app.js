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
    researchSubmit: byId("researchSubmit"),
    researchAnswer: byId("researchAnswer"),
    answerPanel: byId("answerPanel"),
    answerResult: byId("answerResult"),
    answerModel: byId("answerModel"),
    answerCitations: byId("answerCitations"),
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
    elements.researchPaperScope.disabled = state.papers.length === 0;
    elements.researchSubmit.disabled = state.retrieving || state.papers.length === 0;
    elements.researchAnswer.disabled = state.answering || state.retrieving || state.papers.length === 0;
  }

  function clearAnswer() {
    elements.answerPanel.classList.add("is-hidden");
    elements.answerResult.innerHTML = "";
    elements.answerCitations.innerHTML = "";
    elements.answerModel.textContent = "";
  }

  function renderAnswer(payload) {
    elements.answerPanel.classList.remove("is-hidden");
    elements.answerModel.textContent = payload.model ? `模型：${payload.model}` : "证据约束回答";
    if (payload.insufficient || !payload.answer) {
      elements.answerResult.innerHTML = '<div class="answer-insufficient"><strong>当前资料不足</strong><span>未调用模型补写缺失结论，请先导入更相关的论文或调整问题。</span></div>';
      elements.answerCitations.innerHTML = "";
      return;
    }
    elements.answerResult.innerHTML = `<p>${escapeHtml(payload.answer).replaceAll("\n", "<br>")}</p>`;
    const citations = Array.isArray(payload.citations) ? payload.citations : [];
    elements.answerCitations.innerHTML = citations.map((item) => {
      const source = item.source || {};
      const pageLabel = source.page_start === source.page_end ? `第 ${source.page_start} 页` : `第 ${source.page_start}–${source.page_end} 页`;
      return `<button type="button" data-evidence-paper="${escapeHtml(source.paper_id)}" data-evidence-page="${Number(source.page_start) || 1}"><strong>[${escapeHtml(item.citation_id)}] ${escapeHtml(item.paper_title || item.filename)}</strong><span>${escapeHtml([item.section_title, source.version_label, pageLabel].filter(Boolean).join(" · "))}</span></button>`;
    }).join("");
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
        const location = [item.section_title, source.version_label, pageLabel].filter(Boolean).join(" · ");
        return `
          <article class="evidence-result">
            <div class="evidence-result-head"><span>${escapeHtml(item.citation_id ? `[${item.citation_id}]` : `证据 ${index + 1}`)}</span><strong>${escapeHtml(item.paper_title || item.filename)}</strong></div>
            <div class="evidence-meta"><span>${escapeHtml(location || pageLabel)}</span><span>相关度 ${Number(item.score || 0).toFixed(2)}</span></div>
            <p>${escapeHtml(item.text)}</p>
            <button class="evidence-open" type="button" data-evidence-paper="${escapeHtml(source.paper_id)}" data-evidence-page="${Number(source.page_start) || 1}">打开原文 · ${escapeHtml(pageLabel)} <span>→</span></button>
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
    elements.answerModel.textContent = "正在调用 DeepSeek";
    elements.answerResult.innerHTML = '<div class="answer-loading"><span>先检索原文证据，再生成带引用的回答…</span></div>';
    elements.answerCitations.innerHTML = "";
    try {
      const selectedPaperId = elements.researchPaperScope.value;
      const response = await fetch("/api/research/answer", {
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
      showToast(message, "error");
    } finally {
      state.answering = false;
      elements.researchAnswer.querySelector("span").textContent = "生成证据回答";
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
      retrieveEvidence();
    });
    elements.researchAnswer.addEventListener("click", generateAnswer);
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
