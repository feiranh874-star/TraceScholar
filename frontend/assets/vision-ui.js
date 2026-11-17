(() => {
  'use strict';
  const node = (tag, text, cls) => {
    const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n;
  };
  async function request(url, body) {
    const response = await fetch(url, body === undefined ? {cache:'no-store'} : {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '视觉识别请求未完成。');
    return data;
  }
  function table(item) {
    const wrap = node('div', undefined, 'vision-table-scroll');
    wrap.tabIndex = 0; wrap.setAttribute('aria-label', '视觉识别表格，可左右滚动');
    const t = node('table'); const covered = new Set(); const anchors = new Map();
    for (const m of item.display_merges || item.merges || []) {
      anchors.set(m.row + ':' + m.column, m);
      for (let r = m.row; r < m.row + m.rowspan; r++) for (let c = m.column; c < m.column + m.colspan; c++) {
        if (r !== m.row || c !== m.column) covered.add(r + ':' + c);
      }
    }
    const head = node('thead'), body = node('tbody');
    item.rows.forEach((row, r) => {
      const tr = node('tr');
      row.forEach((value, c) => {
        const key = r + ':' + c; if (covered.has(key)) return;
        const cell = node(r ? 'td' : 'th', value ?? '');
        if (!r) cell.scope = 'col';
        const m = anchors.get(key); if (m) { cell.rowSpan = m.rowspan; cell.colSpan = m.colspan; }
        tr.append(cell);
      });
      (r ? body : head).append(tr);
    });
    t.append(head, body); wrap.append(t); return wrap;
  }
  function download(data) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type:'application/json'}));
    const a = node('a'); a.href = url; a.download = 'vision-page-' + data.page + '.json'; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function formula(latex) {
    const preview = node('div', undefined, 'vision-math');
    try {
      if (!window.katex) throw new Error('Formula renderer unavailable');
      // Insert only KaTeX-generated MathML, never model-provided HTML.
      preview.innerHTML = window.katex.renderToString(latex, {
        displayMode:true, output:'mathml', throwOnError:true, trust:false,
        strict:'error', maxExpand:500, maxSize:20
      });
    } catch (_) {
      preview.textContent = '此公式暂时无法排版，请查看原图或复制下方 LaTeX。';
      preview.className += ' vision-hint';
    }
    return preview;
  }
  function render(data) {
    const result = node('div', undefined, 'vision-result');
    const heading = node('div', undefined, 'vision-actions');
    heading.append(node('h3', '已保存的视觉识别 · 原始第 ' + data.page + ' 页'));
    const json = node('button', '下载识别 JSON', 'secondary-button'); json.type = 'button'; json.onclick = () => download(data); heading.append(json);
    result.append(heading, node('p', data.notice, 'vision-hint'));
    for (const warning of data.warnings || []) result.append(node('p', warning, 'vision-warning'));
    for (const [kind, items] of [['table', data.tables], ['formula', data.equations], ['figure', data.figures]]) {
      for (const item of items || []) {
        const card = node('article', undefined, 'vision-card vision-' + kind); card.append(node('h4', item.label || '原文区域'));
        const b = item.bbox, id = encodeURIComponent(data.paper_id);
        const q = new URLSearchParams({x0:b[0], y0:b[1], x1:b[2], y1:b[3]});
        const a = node('a'); a.href = '/api/papers/' + id + '/crop/' + data.page + '?' + q;
        a.target = '_blank'; a.rel = 'noopener'; a.className = 'vision-crop-preview'; a.title = '点击放大查看原版截图';
        const img = node('img'); img.loading = 'lazy'; img.src = a.href; img.alt = (item.label || '图表') + ' 原版区域（自动定位，需核对）'; a.append(img); card.append(a);
        if (item.layout_method) card.append(node('p', '截图：' + item.layout_method + ' · 点击图片可放大核对。', 'vision-hint'));
        if (kind === 'table') {
          card.append(table(item));
          if (item.display_note) card.append(node('p', item.display_note, 'vision-hint'));
          const csv = node('a', '下载视觉表格 CSV');
          csv.href = '/api/papers/' + id + '/vision/' + data.page + '/tables/' + encodeURIComponent(item.id) + '.csv'; card.append(csv);
        } else if (kind === 'formula') {
          card.append(node('p', '公式预览（按识别结果排版，请对照原图）', 'vision-hint'), formula(item.latex));
          const code = node('details', undefined, 'vision-latex-details');
          code.append(node('summary', '查看 LaTeX 源码'), node('pre', item.latex, 'vision-latex')); card.append(code);
          const copy = node('button', '复制 LaTeX', 'secondary-button'); copy.type = 'button';
          copy.onclick = async () => { try { await navigator.clipboard.writeText(item.latex); copy.textContent = '已复制'; } catch (_) { copy.textContent = '请选中上方代码复制'; } }; card.append(copy);
        } else card.append(node('p', item.description));
        if (item.notes) card.append(node('p', item.notes, 'vision-hint'));
        const original = node('a', '核对完整原页 ↗'); original.href = '/reader/' + id + '?page=' + data.page + '&bbox=' + b.join(',');
        original.target = '_blank'; original.rel = 'noopener'; const links = node('p'); links.append(original); card.append(links); result.append(card);
      }
    }
    if (!(data.tables.length + data.equations.length + data.figures.length)) result.append(node('p', '模型本次没有识别出图表或公式。这不代表原文一定没有，请核对完整原页。'));
    return result;
  }
  function mount(target, paperId, number) {
    const root = node('section', undefined, 'vision-panel');
    const actions = node('div', undefined, 'vision-actions'); const button = node('button', '视觉识别本页', 'secondary-button'); button.type = 'button';
    const status = node('p', '正在检查视觉接口配置…', 'vision-hint'); status.setAttribute('role', 'status');
    const output = node('div'); output.setAttribute('aria-live', 'polite');
    root.append(node('h3', '复杂表格、公式与图片'), node('p', '使用已配置的视觉接口识别当前页原图，按接口实际用量计费。首次点击才调用；已保存结果直接读取。原始空白保留为空。', 'vision-hint'), actions, status, output);
    actions.append(button); target.append(root); button.disabled = true;
    const base = '/api/papers/' + encodeURIComponent(paperId) + '/vision/' + number;
    let timer = null, hasResult = false;
    const active = () => root.isConnected;
    const show = data => { hasResult = true; output.replaceChildren(render(data)); button.textContent = '重新视觉识别（产生新用量）'; };
    async function poll(id) {
      if (!active()) return;
      try {
        const job = await request('/api/jobs/' + encodeURIComponent(id));
        if (!active()) return;
        if (['queued', 'running'].includes(job.status)) {
          status.textContent = '视觉识别进行中，可能需要 1–2 分钟。可离开页面，完成后结果自动保存。';
          timer = setTimeout(() => poll(id), 2000); return;
        }
        if (job.status === 'done') {
          const cache = await request(base);
          if (!active()) return;
          show(cache.result || job.result); status.textContent = '识别结果已保存；再次打开不重复调用。';
        }
        else status.textContent = job.message || '任务中断，可在研究工作区的后台任务中继续。';
        button.disabled = false;
      } catch (_) {
        if (!active()) return;
        status.textContent = '暂时无法读取进度，正在重新连接。不要重复启动；任务可能仍在后台执行。';
        timer = setTimeout(() => poll(id), 5000);
      }
    }
    button.onclick = async () => {
      if (hasResult && !confirm('重新识别会再次发送当前页，并产生新的 API 用量。是否继续？')) return;
      button.disabled = true; status.textContent = '正在提交本页识别任务…';
      try {
        const job = await request(base, {force:hasResult});
        if (!active()) return;
        if (job.cached) { show(job.result); status.textContent = '已读取缓存，没有再次调用模型。'; button.disabled = false; }
        else poll(job.id);
      } catch (error) { if (active()) { status.textContent = error.message; button.disabled = false; } }
    };
    Promise.all([request('/api/vision/status'), request(base), request('/api/jobs')]).then(([config, cache, jobs]) => {
      if (!active()) return;
      if (cache.result) show(cache.result);
      button.disabled = !config.configured;
      status.textContent = config.configured ? (hasResult ? '已读取保存结果，没有调用模型。' : '接口已配置。点击按钮开始识别当前一页。') : '尚未配置视觉接口；请在本机 .env 填写 VISION_API_KEY 后重启。';
      const running = jobs.items.find(j => j.kind === 'vision' && j.paper_ids.includes(paperId) && j.payload.page === number && ['running','queued'].includes(j.status));
      if (running) { button.disabled = true; poll(running.id); }
    }).catch(error => { if (active()) status.textContent = error.message + ' 请重新打开本页图表。'; });
    addEventListener('pagehide', () => clearTimeout(timer), {once:true});
  }
  window.TraceVision = {mount, table, formula, render};
})();
