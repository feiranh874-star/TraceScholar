(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  const title = p => (p.title || p.filename) + (p.version_label ? ' · ' + p.version_label : '');
  function matches(p, query) {
    const term = query.trim().toLocaleLowerCase();
    return !term || [p.title, p.filename, p.author, ...(p.authors || []), p.notes].some(v => String(v || '').toLocaleLowerCase().includes(term));
  }
  const recent = papers => [...papers].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
  function paginate(papers, requestedPage, pageSize = 10) {
    const total = papers.length;
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    const page = Math.max(1, Math.min(totalPages, Number(requestedPage) || 1));
    const offset = (page - 1) * pageSize;
    return {items: papers.slice(offset, offset + pageSize), page, total, totalPages,
      start: total ? offset + 1 : 0, end: Math.min(offset + pageSize, total)};
  }
  const date = p => p.created_at ? new Date(p.created_at).toLocaleString('zh-CN', {hour12:false}) : '入库时间未知';
  const pickers = new WeakMap();
  function mountPicker(select, papers, options = {}) {
    let picker = pickers.get(select);
    if (!picker) {
      if (options.searchFirst) {
        const root = document.createElement('div'); root.className = 'paper-picker paper-picker-search-first';
        root.innerHTML = '<input type="search" aria-label="搜索检索范围论文" aria-expanded="false" placeholder="搜索题名、作者、文件名或备注" autocomplete="off"><div class="picker-selection"><span></span><button type="button" hidden>清除选择</button></div><div class="paper-picker-popover" hidden><small>按入库时间：从新到旧</small><div class="paper-picker-options" role="group" aria-label="选择论文"></div></div>';
        select.hidden = true; select.after(root);
        const search = root.querySelector('input'), list = root.querySelector('.paper-picker-options'), panel = root.querySelector('.paper-picker-popover'), clear = root.querySelector('.picker-selection button');
        picker = {root, search, papers:[], options}; pickers.set(select, picker);
        const toggle = open => { panel.hidden = !open; search.setAttribute('aria-expanded', String(open)); };
        picker.draw = () => {
          const selected = picker.papers.find(p => p.paper_id === select.value);
          root.querySelector('.picker-selection span').textContent = selected ? '已选：' + title(selected) : '未限定论文，将检索整个论文库';
          clear.hidden = !selected;
          const rows = recent(picker.papers).filter(p => matches(p, search.value));
          list.innerHTML = rows.map(p => '<button type="button" data-pick="' + esc(p.paper_id) + '" aria-pressed="' + (select.value === p.paper_id) + '"><strong>' + esc(title(p)) + '</strong><small>' + esc(p.filename) + ' · ' + esc(date(p)) + '</small>' + (p.notes ? '<span class="picker-note">备注：' + esc(p.notes) + '</span>' : '') + '</button>').join('') || '<p class="picker-empty">没有匹配论文，请换个关键词。</p>';
        };
        search.onfocus = () => { picker.draw(); toggle(true); };
        search.oninput = () => { picker.draw(); toggle(true); };
        list.onclick = event => {
          const button = event.target.closest('[data-pick]'); if (!button) return;
          select.value = button.dataset.pick; search.value = ''; select.dispatchEvent(new Event('change', {bubbles:true}));
          search.focus(); toggle(false);
        };
        clear.onclick = () => { select.value = ''; search.value = ''; select.dispatchEvent(new Event('change', {bubbles:true})); search.focus(); };
        select.addEventListener('change', picker.draw);
        root.addEventListener('keydown', event => { if (event.key === 'Escape') { toggle(false); search.focus(); } });
        root.addEventListener('focusout', event => { if (!root.contains(event.relatedTarget)) toggle(false); });
        document.addEventListener('click', event => { if (!root.contains(event.target)) toggle(false); });
        picker.papers = papers; picker.draw(); return;
      }
      const root = document.createElement('details'); root.className = 'paper-picker';
      root.innerHTML = '<summary><span></span><b aria-hidden="true">⌄</b></summary><div class="paper-picker-popover"><input type="search" aria-label="搜索待选论文" placeholder="搜索题名、作者、文件名或备注"><small>按入库时间：从新到旧</small><div class="paper-picker-options" role="group" aria-label="选择论文"></div></div>';
      select.hidden = true; select.after(root);
      picker = {root, search: root.querySelector('input'), list: root.querySelector('.paper-picker-options'), summary: root.querySelector('summary span'), papers: [], options};
      pickers.set(select, picker);
      picker.draw = () => {
        const selected = picker.papers.find(p => p.paper_id === select.value);
        picker.summary.textContent = selected ? title(selected) : picker.options.all ? '全部已入库论文（' + picker.papers.length + '）' : '请选择论文';
        const rows = recent(picker.papers).filter(p => matches(p, picker.search.value));
        picker.list.innerHTML = (picker.options.all ? '<button type="button" data-pick="" aria-pressed="' + (!select.value) + '"><strong>全部已入库论文</strong><small>在整个论文库中查找证据</small></button>' : '') + rows.map(p => '<button type="button" data-pick="' + esc(p.paper_id) + '" aria-pressed="' + (select.value === p.paper_id) + '"><strong>' + esc(title(p)) + '</strong><small>' + esc(p.filename) + ' · ' + esc(date(p)) + '</small>' + (p.notes ? '<span class="picker-note">备注：' + esc(p.notes) + '</span>' : '') + '</button>').join('') + (!rows.length ? '<p class="picker-empty">没有匹配论文，请换个关键词。</p>' : '');
      };
      picker.search.oninput = picker.draw;
      picker.list.onclick = event => {
        const button = event.target.closest('[data-pick]'); if (!button) return;
        select.value = button.dataset.pick; select.dispatchEvent(new Event('change', {bubbles:true})); picker.draw(); root.open = false; root.querySelector('summary').focus();
      };
      root.addEventListener('toggle', () => { if (root.open) picker.search.focus(); });
      root.addEventListener('keydown', event => { if (event.key === 'Escape') { root.open = false; root.querySelector('summary').focus(); } });
      select.addEventListener('change', picker.draw);
      document.addEventListener('click', event => { if (!root.contains(event.target)) root.open = false; });
    }
    picker.papers = papers; picker.options = options; picker.draw();
  }
  window.TracePaperUI = {mountPicker, matches, recent, paginate};

  let collections = [], tab = 'all', folder = null, callbacks;
  const removing = new Set();
  async function removeFromCurrentFolder(paperId) {
    const collectionId = folder;
    if (!collectionId || removing.has(paperId)) return;
    removing.add(paperId);
    try {
      const saved = await request('/api/library/collections/' + encodeURIComponent(collectionId) + '/papers/' + encodeURIComponent(paperId), undefined, 'DELETE');
      const paper = callbacks.papers().find(p => p.paper_id === paperId);
      if (paper) Object.assign(paper, saved);
      await callbacks.reload();
      callbacks.toast('已移出当前收藏夹，论文仍保留在论文库及其他收藏夹中。', 'success');
    } catch (error) { callbacks.toast(error.message, 'error'); }
    finally { removing.delete(paperId); callbacks.render(); }
  }
  async function request(url, body, method = 'POST') {
    const response = await fetch(url, {method, headers:{'Content-Type':'application/json'}, ...(body !== undefined ? {body:JSON.stringify(body)} : {})});
    if (!response.ok) { const d = await response.json().catch(() => ({})); throw new Error(typeof d.detail === 'string' ? d.detail : '保存未完成，请检查输入或刷新后重试。'); }
    return response.status === 204 ? null : response.json();
  }
  async function load() {
    try { collections = (await request('/api/library/collections', undefined, 'GET')).items; }
    catch (error) { callbacks.toast(error.message, 'error'); }
    if (folder && !collections.some(c => c.id === folder)) folder = null;
  }
  function dialog(heading, body, save) {
    const d = document.createElement('dialog'); d.className = 'organize-dialog';
    d.innerHTML = '<form><header><h2>' + esc(heading) + '</h2><button type="button" class="text-button" data-close aria-label="关闭">✕</button></header>' + body + '<p class="organize-error" role="alert"></p><footer><button type="button" class="secondary-button" data-close>取消</button><button type="submit" class="primary-button">保存</button></footer></form>';
    document.body.append(d); d.querySelectorAll('[data-close]').forEach(b => b.onclick = () => d.close());
    d.addEventListener('close', () => d.remove());
    d.querySelector('form').onsubmit = async event => {
      event.preventDefault(); const button = d.querySelector('[type=submit]'); button.disabled = true;
      try { await save(d); d.close(); callbacks.toast('已保存。', 'success'); }
      catch (error) { d.querySelector('[role=alert]').textContent = error.message; }
      finally { button.disabled = false; }
    };
    d.showModal();
  }
  function collectionDialog(collection) {
    dialog(collection ? '重命名收藏夹' : '新建收藏夹', '<label>名称<input id="collectionName" required maxlength="80" value="' + esc(collection?.name || '') + '" placeholder="例如：注意力机制 / 待精读"></label><p class="organize-hint">收藏夹用于分类。同一篇论文可以加入多个收藏夹，原文件只保存一份。</p>', async d => {
      await request('/api/library/collections' + (collection ? '/' + collection.id : ''), {name:d.querySelector('input').value.trim()}, collection ? 'PATCH' : 'POST'); await load(); callbacks.render();
    });
  }
  function organize(paper) {
    dialog('整理论文', '<p class="organize-paper-title">' + esc(title(paper)) + '</p><label>备注<textarea id="paperNotes" rows="4" maxlength="4000" placeholder="写下主题、用途或阅读进度…">' + esc(paper.notes || '') + '</textarea></label><p class="organize-hint">可以用备注搜索论文；备注不会被当成原文证据。</p><fieldset><legend>收纳到收藏夹（可多选）</legend><div class="folder-checks">' + collections.map(c => '<label><input type="checkbox" value="' + esc(c.id) + '"' + ((paper.collection_ids || []).includes(c.id) ? ' checked' : '') + '><span>' + esc(c.name) + '</span></label>').join('') + '</div>' + (!collections.length ? '<p>还没有收藏夹。保存后，切换到“收藏夹”即可新建。</p>' : '') + '</fieldset>', async d => {
      await request('/api/papers/' + paper.paper_id + '/organization', {notes:d.querySelector('textarea').value, collection_ids:[...d.querySelectorAll('input[type=checkbox]:checked')].map(x => x.value)}, 'PATCH'); await callbacks.reload();
    });
  }
  function manageMembers(collection) {
    const current = new Set(collection.paper_ids);
    dialog('添加 / 移出论文', '<p class="organize-paper-title">' + esc(collection.name) + '</p><input class="member-search" type="search" aria-label="搜索要收纳的论文" placeholder="搜索论文或备注"><p class="organize-hint">勾选后保存。取消勾选只会移出此收藏夹。</p><div class="member-list">' + recent(callbacks.papers()).map(p => '<label data-member="' + esc(p.paper_id) + '"><input type="checkbox" value="' + esc(p.paper_id) + '"' + (current.has(p.paper_id) ? ' checked' : '') + '><span><strong>' + esc(title(p)) + '</strong><small>' + esc(p.notes || p.filename) + '</small></span></label>').join('') + '</div>', async d => {
      const checked = new Set([...d.querySelectorAll('input[type=checkbox]:checked')].map(x => x.value));
      for (const p of callbacks.papers()) {
        if (checked.has(p.paper_id) === current.has(p.paper_id)) continue;
        const ids = (p.collection_ids || []).filter(id => id !== collection.id && collections.some(c => c.id === id));
        if (checked.has(p.paper_id)) ids.push(collection.id);
        // Keep local state current if a later write fails; retrying the dialog is safe.
        const saved = await request('/api/papers/' + p.paper_id + '/organization', {notes:p.notes || '', collection_ids:ids}, 'PATCH');
        Object.assign(p, saved);
      }
      await callbacks.reload();
    });
    const d = document.querySelector('dialog.organize-dialog');
    d.querySelector('.member-search').oninput = event => {
      for (const label of d.querySelectorAll('[data-member]')) label.hidden = !matches(callbacks.papers().find(p => p.paper_id === label.dataset.member), event.target.value);
    };
  }
  function render(papers) {
    el('allPapersTab').classList.toggle('is-active', tab === 'all'); el('allPapersTab').setAttribute('aria-selected', tab === 'all');
    el('collectionsTab').classList.toggle('is-active', tab === 'folders'); el('collectionsTab').setAttribute('aria-selected', tab === 'folders');
    const browse = tab === 'folders' && !folder;
    el('collectionArea').hidden = !browse; el('collectionContext').hidden = !folder || tab === 'all'; el('libraryPanel').hidden = browse;
    if (browse) el('collectionArea').innerHTML = '<div class="collection-heading"><div><h3>我的收藏夹</h3><p>按主题收纳；同一篇论文可以出现在多个收藏夹。</p></div><button class="primary-button" data-new-folder>＋ 新建收藏夹</button></div><div class="collection-grid">' + collections.map(c => '<article class="collection-card"><button class="collection-open" data-folder="' + esc(c.id) + '"><span class="folder-symbol" aria-hidden="true">▰</span><strong>' + esc(c.name) + '</strong><small>' + papers.filter(p => (p.collection_ids || []).includes(c.id)).length + ' 篇论文</small></button><div class="collection-actions"><button data-manage-folder="' + esc(c.id) + '">添加 / 移出论文</button><button data-rename-folder="' + esc(c.id) + '">重命名</button><button data-delete-folder="' + esc(c.id) + '">删除</button></div></article>').join('') + (!collections.length ? '<div class="collection-empty">还没有收藏夹。先新建一个，例如“精读论文”。</div>' : '') + '</div>';
    if (folder) { const c = collections.find(c => c.id === folder); el('collectionContext').innerHTML = '<div><button class="text-button" data-folder-back>← 所有收藏夹</button><h3>' + esc(c?.name) + '</h3></div><div class="collection-context-actions"><button class="primary-button" data-upload-folder="' + esc(folder) + '">上传论文</button><button class="secondary-button" data-manage-folder="' + esc(folder) + '">添加 / 移出论文</button></div>'; }
    return browse;
  }
  function init(cbs) {
    callbacks = cbs;
    el('allPapersTab').onclick = () => { tab = 'all'; folder = null; callbacks.render(); };
    el('collectionsTab').onclick = () => { tab = 'folders'; folder = null; callbacks.render(); };
    document.addEventListener('click', async event => {
      const b = event.target.closest('button'); if (!b) return;
      if (b.dataset.uploadFolder) { const c = collections.find(c => c.id === b.dataset.uploadFolder); if (c) callbacks.upload(c); return; }
      if (b.dataset.removeCollectionPaper) { b.disabled = true; await removeFromCurrentFolder(b.dataset.removeCollectionPaper); return; }
      if (b.hasAttribute('data-new-folder')) collectionDialog();
      if (b.hasAttribute('data-folder-back')) { folder = null; callbacks.render(); }
      if (b.dataset.folder) { folder = b.dataset.folder; el('librarySearch').value = ''; el('searchInput').value = ''; callbacks.render(); }
      if (b.dataset.organizePaper) { const p = callbacks.papers().find(p => p.paper_id === b.dataset.organizePaper); if (p) organize(p); }
      const c = collections.find(c => c.id === (b.dataset.renameFolder || b.dataset.deleteFolder || b.dataset.manageFolder));
      if (c && b.dataset.renameFolder) collectionDialog(c);
      if (c && b.dataset.manageFolder) manageMembers(c);
      if (c && b.dataset.deleteFolder && confirm('删除收藏夹“' + c.name + '”？论文仍保留在“全部论文”中。')) {
        try { await request('/api/library/collections/' + c.id, undefined, 'DELETE'); await load(); callbacks.render(); }
        catch (error) { callbacks.toast(error.message, 'error'); }
      }
    });
  }
  window.TraceLibrary = {init, load, render, removeFromCurrentFolder, scopeKey:() => tab + ':' + (folder || ''), hasFolder:() => !!folder, filter: papers => folder ? papers.filter(p => (p.collection_ids || []).includes(folder)) : papers};
})();
