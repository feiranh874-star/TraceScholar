(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const paperId = location.pathname.split('/').filter(Boolean)[1];
  const page = () => Number(el('pageNumber').value) || 1;
  let generation = 0, loadedPage = null, pendingPage = null;
  const node = (tag, text, className) => {
    const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (className) e.className = className; return e;
  };
  function sourceLink(number, text, bbox) {
    const link = node('a', text); link.target = '_blank'; link.rel = 'noopener';
    link.href = '/reader/' + paperId + '?page=' + number + (bbox ? '&bbox=' + bbox.join(',') : '');
    return link;
  }
  function renderTable(rows) {
    const wrap = node('div', undefined, 'reader-table-scroll'), table = node('table');
    rows.forEach((row, index) => {
      const tr = node('tr'); for (const cell of row) tr.append(node(index ? 'td' : 'th', cell ?? ''));
      if (!index) { const head = node('thead'); head.append(tr); table.append(head); }
      else { let body = table.tBodies[0]; if (!body) { body = node('tbody'); table.append(body); } body.append(tr); }
    });
    wrap.append(table); return wrap;
  }
  function renderItem(item, data) {
    const card = node('article', undefined, 'reader-figure-card');
    card.append(node('h3', item.label || '原文图表'), node('p', item.caption || '', 'reader-hint'));
    const query = new URLSearchParams(Object.fromEntries(['x0','y0','x1','y1'].map((k, i) => [k, item.bbox[i]])));
    const image = node('img'); image.alt = (item.label || '图表') + ' 原版截图';
    image.src = '/api/papers/' + paperId + '/crop/' + data.page + '?' + query;
    const imageLink = node('a'); imageLink.href = image.src; imageLink.target = '_blank'; imageLink.rel = 'noopener'; imageLink.title = '在新页放大查看原版截图'; imageLink.append(image); card.append(imageLink);
    image.onerror = () => { imageLink.hidden = true; const error = node('p', '截图加载失败，请重新识别或点击“核对整页”查看原文。', 'reader-notice'); card.insertBefore(error, imageLink); };
    if (item.rows?.length) {
      card.append(node('h4', '提取的表格（请与上方原图核对）'), renderTable(item.rows));
      if (item.notice) card.append(node('p', item.notice, 'reader-hint'));
      if (item.merged_cells?.length) {
        const details = node('details'); details.append(node('summary', '合并单元格说明'));
        item.merged_cells.forEach(m => details.append(node('p', '数据行 ' + m.row + '，第 ' + m.columns.map(c => c + 1).join('、') + ' 列共用：' + m.text)));
        card.append(details);
      }
    }
    const links = node('div', undefined, 'reader-extra-links');
    links.append(sourceLink(data.page, '核对整页 · 原始第 ' + data.page + ' 页', item.bbox));
    if (item.rows?.length) { const csv = node('a', '下载 CSV（Excel 可打开）'); csv.href = '/api/papers/' + paperId + '/tables/' + data.page + '/' + encodeURIComponent(item.id) + '.csv'; links.append(csv); }
    card.append(links); return card;
  }
  async function analyze(force = false) {
    const number = page();
    if (pendingPage === number || (!force && loadedPage === number)) return;
    pendingPage = number;
    const ticket = ++generation;
    loadedPage = null;
    const target = el('pageFiguresResult'), visionHost = node('div'), output = node('div');
    target.replaceChildren(visionHost, output); window.TraceVision.mount(visionHost, paperId, number);
    output.textContent = '正在提取第 ' + number + ' 页图表…'; el('reloadPageFigures').disabled = true;
    el('figuresHeading').textContent = '本页表格与图片 · 第 ' + number + ' 页';
    el('figuresWorkspace').href = '/workspace?paper=' + paperId + '&page=' + number + '&tab=layout&analyze=1';
    try {
      const response = await fetch('/api/papers/' + paperId + '/analysis/' + number, {cache:'no-store'});
      const data = await response.json();
      if (!response.ok) {
        const error = new Error(data.detail || '图表提取失败'); error.status = response.status; throw error;
      }
      if (ticket !== generation || number !== page()) return;
      output.replaceChildren(); loadedPage = number;
      const items = [...data.tables, ...data.figures];
      if (!items.length) output.append(node('p', '本地解析没有自动定位到表格或图片。可以使用上方“视觉识别本页”，或翻到包含图表的一页再试。'), sourceLink(number, '查看完整原页'));
      else for (const item of items) output.append(renderItem(item, data));
    } catch (error) {
      if (ticket !== generation || number !== page()) return;
      loadedPage = null;
      if (error.status === 404) {
        output.replaceChildren(node('p', '无法读取这条论文的图表资料。这是资料访问失败，不是“表格未识别”。旧阅读页可能已失效，或服务重启后临时资料丢失；请返回论文库核对，再从当前记录打开。', 'reader-notice'));
        const back = node('a', '返回论文库核对'); back.href = '/?view=library'; output.append(back);
      } else if (error.status === 429) output.textContent = '另一个页面正在解析图表，请稍后点“重新识别本页图表”。';
      else output.textContent = error.message;
    }
    finally { if (ticket === generation) { pendingPage = null; el('reloadPageFigures').disabled = false; } }
  }
  el('showPageFigures').onclick = () => {
    el('pageFiguresPanel').hidden = false; analyze(); el('pageFiguresPanel').scrollIntoView({behavior:'smooth', block:'start'});
  };
  el('reloadPageFigures').onclick = () => analyze(true);
  const observer = new MutationObserver(() => { if (!el('pageFiguresPanel').hidden) analyze(); });
  observer.observe(el('readerPageLabel'), {childList:true, subtree:true, characterData:true});
  if (new URLSearchParams(location.search).get('figures') === '1') el('showPageFigures').click();
})();
