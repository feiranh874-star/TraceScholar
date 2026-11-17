(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  const MAX_BYTES = 50 * 1024 * 1024;
  const STORAGE_KEY = 'tracescholar-last-batch';
  let queue = [], current = null, timer = null, uploading = false, resolving = false, callbacks;
  const active = job => ['running', 'queued'].includes(job?.status);
  const size = bytes => (bytes / 1024 / 1024).toFixed(2) + ' MiB';

  function fileResult(entry, job) {
    if (!entry) return {label:'等待处理', tone:'pending'};
    if (entry.result?.cancelled) return {label:'已取消本篇', tone:'muted'};
    if (entry.status < 300) return {label:entry.result?.duplicate ? '已存在，未重复导入' : '导入成功', tone:'success'};
    if (entry.status === 409 && entry.result?.conflict) return {label:'关联版本待确认', tone:'conflict'};
    return {label:entry.status >= 500 && active(job) ? '暂时失败，待重试' : '导入失败', tone:'error'};
  }
  function readableError(value) {
    const message = typeof value === 'string' ? value : '文件无法导入，请检查 PDF 后重新选择。';
    if (/not a PDF|PDF signature/i.test(message)) return '这个文件不是有效的 PDF，请重新导出后上传。';
    if (/damaged|unreadable/i.test(message)) return 'PDF 已损坏或无法读取，请重新下载或导出。';
    if (/encrypt/i.test(message)) return 'PDF 已加密，请先导出未加密版本。';
    return message;
  }
  function setMode(batch) {
    el('singleImportTab').setAttribute('aria-selected', !batch); el('singleImportTab').classList.toggle('is-active', !batch);
    el('batchImportTab').setAttribute('aria-selected', batch); el('batchImportTab').classList.toggle('is-active', batch);
    el('singleImportArea').hidden = batch; el('batchImportPanel').hidden = !batch;
  }
  async function request(url, body) {
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 60000);
    try {
      const response = await fetch(url, {signal:controller.signal, cache:'no-store', ...(body !== undefined ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)} : {})});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) { const error = new Error(typeof data.detail === 'string' ? data.detail : '请求未完成，请刷新进度后重试。'); error.status = response.status; throw error; }
      return data;
    } catch (error) { if (error.name === 'AbortError') throw new Error('网络响应超时，请刷新进度。后台可能仍在处理。'); throw error; }
    finally { clearTimeout(timeout); }
  }
  function remember(id) { try { localStorage.setItem(STORAGE_KEY, id); } catch {} }
  function remembered() { try { return localStorage.getItem(STORAGE_KEY); } catch { return null; } }
  function drawQueue() {
    el('batchQueueSummary').textContent = queue.length ? '待上传 ' + queue.length + ' 篇 · 合计 ' + size(queue.reduce((sum, f) => sum + f.size, 0)) : '还没有选择文件';
    el('batchQueue').innerHTML = queue.map((file, i) => '<div class="batch-queue-row"><span class="batch-file-icon">PDF</span><span><strong>' + esc(file.name) + '</strong><small>' + size(file.size) + '</small></span><button type="button" class="text-button" data-remove-batch="' + i + '" aria-label="移除 ' + esc(file.name) + '"' + (uploading ? ' disabled' : '') + '>移除</button></div>').join('');
    el('startBatchImport').disabled = !queue.length || uploading || resolving || active(current);
    el('startBatchImport').textContent = uploading ? '正在上传…' : '开始批量导入';
    el('clearBatchQueue').disabled = !queue.length || uploading;
    el('batchNotes').disabled = uploading;
  }
  function addFiles(files) {
    setMode(true);
    if (uploading) { el('batchUploadStatus').textContent = '正在上传，请稍候再添加文件。'; return; }
    const candidates = [...queue], errors = [];
    for (const file of files) {
      if (!(file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf'))) errors.push(file.name + '：请选择 PDF。');
      else if (!file.size) errors.push(file.name + '：文件为空。');
      else candidates.push(file);
    }
    if (candidates.length > 20) errors.push('每批最多 20 篇，请减少文件后重试。');
    else if (candidates.reduce((sum, f) => sum + f.size, 0) > MAX_BYTES) errors.push('文件合计超过 50 MiB，请分批导入。');
    else queue = candidates;
    el('batchUploadStatus').textContent = errors.join(' '); drawQueue();
    el('batchFileInput').value = '';
  }
  function drawJob() {
    if (!current) return;
    el('batchCurrentJob').hidden = false;
    const entries = current.file_results || current.result?.files || [];
    const names = current.payload?.files || entries.map(f => f.filename), counts = {success:0, duplicate:0, conflict:0, error:0, cancelled:0};
    for (const entry of entries) {
      if (entry.result?.cancelled) counts.cancelled++;
      else if (entry.status < 300) counts[entry.result?.duplicate ? 'duplicate' : 'success']++;
      else if (entry.status === 409 && entry.result?.conflict) counts.conflict++;
      else counts.error++;
    }
    const status = ({queued:'等待开始', running:'正在处理', done:counts.conflict ? '等待确认关联版本' : '本批处理结束', failed:'部分文件未完成', interrupted:'任务已中断，可继续'})[current.status] || current.status;
    el('batchJobHeading').textContent = '批量导入 · ' + status;
    el('batchJobMessage').textContent = active(current) ? (current.message || '文件已上传，正在逐篇解析。可以离开本页，稍后回来查看。') : current.status === 'done' ? '已处理 ' + names.length + ' 篇。请核对下方每篇结果；待确认和失败的文件尚未入库。' : current.message;
    el('batchParseProgress').max = Math.max(1, names.length); el('batchParseProgress').value = current.progress || 0;
    el('batchJobSummary').textContent = '新入库 ' + counts.success + ' · 已存在 ' + counts.duplicate + ' · 待确认 ' + counts.conflict + ' · 失败 ' + counts.error + ' · 已取消 ' + counts.cancelled;
    el('resumeBatchJob').hidden = !['failed','interrupted'].includes(current.status);
    el('resumeBatchJob').disabled = resolving;
    el('batchJobFiles').innerHTML = names.map((name, index) => {
      const entry = entries.find(f => f.index === index), info = fileResult(entry, current), result = entry?.result;
      if (!entry && active(current) && current.current_index === index) info.label = '正在解析';
      const paper = result?.paper_id;
      const matches = result?.conflict ? (result.matches || []).map(m => '<p>库内：' + esc(m.paper.filename) + ' · ' + esc(m.paper.version_label || '版本未知') + '</p>').join('') : '';
      return '<article class="batch-file-result"><div class="batch-result-title"><strong>' + esc(name) + '</strong><span class="batch-result-badge ' + info.tone + '">' + info.label + '</span></div>' + (entry?.error ? '<p class="batch-file-error">' + esc(readableError(entry.error)) + '</p>' : '') + (result?.conflict ? '<div class="batch-conflict-copy">' + (result.recommendation === 'keep_existing_newer' ? '<p>库中已有新版，建议取消本篇导入。</p>' : '<p>发现相关论文，请选择保留两版或取消本篇导入。</p>') + matches + '</div><div class="batch-result-actions"><button type="button" class="secondary-button" data-batch-decision="keep_both" data-batch-index="' + index + '"' + (active(current) || resolving ? ' disabled' : '') + '>保留两个版本</button><button type="button" class="text-button" data-batch-decision="cancel" data-batch-index="' + index + '"' + (active(current) || resolving ? ' disabled' : '') + '>取消本篇导入</button></div>' : '') + (paper ? '<a href="/reader/' + encodeURIComponent(paper) + '?from=import" class="text-button">查看论文 ↗</a>' : '') + '</article>';
    }).join('');
    drawQueue();
  }
  async function refreshJob(id = current?.id, retry = false) {
    if (!id) return;
    clearTimeout(timer);
    try {
      const job = await request('/api/jobs/' + encodeURIComponent(id));
      if (current && current.id !== id) return;
      const wasActive = active(current); current = job; remember(id); drawJob();
      if (wasActive && !active(job)) { await callbacks.reload(); await history(); }
      if (active(job)) timer = setTimeout(() => refreshJob(id, true), 2000);
    } catch (error) {
      el('batchUploadStatus').textContent = error.message;
      if (retry && error.status !== 404 && error.status !== 401) timer = setTimeout(() => refreshJob(id, true), 5000);
    }
  }
  async function history() {
    try {
      const data = await request('/api/jobs');
      const jobs = data.items.filter(j => j.kind === 'batch');
      el('batchHistoryList').innerHTML = jobs.map(j => '<button type="button" class="batch-history-row" data-open-batch="' + esc(j.id) + '"><span>' + new Date(j.created_at * 1000).toLocaleString('zh-CN') + ' · ' + (j.payload?.files?.length || 0) + ' 篇</span><small>' + esc(({done:'查看处理结果', running:'正在处理', queued:'等待开始', failed:'处理未完成', interrupted:'可继续处理'})[j.status] || j.status) + '</small></button>').join('') || '<p>还没有批量导入记录。</p>';
      return jobs;
    } catch (error) { el('batchHistoryList').textContent = error.message; return []; }
  }
  function upload(body) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest(); xhr.open('POST', '/api/library/batch-upload'); xhr.timeout = 180000;
      xhr.upload.onprogress = event => {
        if (!event.lengthComputable) return;
        const percent = Math.round(event.loaded / event.total * 100); el('batchUploadProgress').value = percent;
        el('batchUploadStatus').textContent = percent < 100 ? '正在上传 ' + percent + '%，请保持本页打开…' : '文件已发送，正在等待服务器确认…';
      };
      xhr.onerror = xhr.ontimeout = () => reject(new Error('上传连接中断。先刷新“最近的批量导入记录”确认是否已收到，再决定是否重传。'));
      xhr.onload = () => {
        let data; try { data = JSON.parse(xhr.responseText); } catch { reject(new Error('服务器响应异常，请检查最近的批量导入记录。')); return; }
        if (xhr.status < 200 || xhr.status >= 300) reject(new Error(typeof data.detail === 'string' ? data.detail : '上传未完成，请稍后重试。'));
        else resolve(data);
      };
      xhr.send(body);
    });
  }
  async function start() {
    if (!queue.length || uploading || resolving || active(current)) return;
    const body = new FormData(); queue.forEach(file => body.append('files', file, file.name)); body.append('notes', el('batchNotes').value);
    const collection = callbacks.collection?.(); if (collection) body.append('collection_id', collection.id);
    uploading = true; drawQueue(); el('batchUploadProgress').hidden = false; el('batchUploadProgress').value = 0; el('batchUploadStatus').textContent = '正在准备上传…';
    try {
      current = await upload(body); remember(current.id); queue = []; el('batchNotes').value = '';
      el('batchUploadStatus').textContent = '文件已上传。逐篇处理状态和版本确认见下方；离开本页后也可以回来查看。';
      drawJob(); await refreshJob(current.id, true); await callbacks.reload(); await history();
    } catch (error) { el('batchUploadStatus').textContent = error.message; }
    finally { uploading = false; el('batchUploadProgress').hidden = true; drawQueue(); }
  }
  async function decide(button) {
    if (!current || active(current) || resolving) return;
    resolving = true; drawJob();
    try {
      await request('/api/jobs/' + current.id + '/files/' + button.dataset.batchIndex + '/resolve', {action:button.dataset.batchDecision});
      await refreshJob(); await callbacks.reload();
    } catch (error) { el('batchUploadStatus').textContent = error.message; }
    finally { resolving = false; drawJob(); }
  }
  function init(cbs) {
    callbacks = cbs;
    el('singleImportTab').onclick = () => setMode(false); el('batchImportTab').onclick = () => setMode(true);
    el('batchDropzone').onclick = () => { if (!uploading) el('batchFileInput').click(); };
    el('batchDropzone').onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); el('batchDropzone').click(); } };
    for (const type of ['dragenter','dragover','dragleave','drop']) el('batchDropzone').addEventListener(type, event => { event.preventDefault(); el('batchDropzone').classList.toggle('is-dragging', type === 'dragenter' || type === 'dragover'); if (type === 'drop') addFiles(Array.from(event.dataTransfer?.files || [])); });
    el('batchFileInput').onchange = () => addFiles(Array.from(el('batchFileInput').files));
    el('clearBatchQueue').onclick = () => { if (!uploading) { queue = []; drawQueue(); } };
    el('startBatchImport').onclick = start; el('refreshBatchJob').onclick = () => refreshJob(undefined, true);
    el('refreshBatchHistory').onclick = history;
    el('resumeBatchJob').onclick = async () => {
      if (!current || resolving) return;
      resolving = true; drawJob();
      try { current = await request('/api/jobs/' + current.id + '/resume', {}); await refreshJob(current.id, true); }
      catch (error) { el('batchUploadStatus').textContent = error.message; }
      finally { resolving = false; drawJob(); }
    };
    el('batchImportPanel').addEventListener('click', event => {
      const button = event.target.closest('button'); if (!button) return;
      if (button.dataset.removeBatch !== undefined && !uploading) { queue.splice(Number(button.dataset.removeBatch), 1); drawQueue(); }
      if (button.dataset.batchDecision) decide(button);
      if (button.dataset.openBatch && !uploading && !resolving) { current = {id:button.dataset.openBatch}; refreshJob(current.id, true); }
    });
    const id = remembered(); if (id && /^[a-f0-9-]{36}$/.test(id)) refreshJob(id, true);
    history(); drawQueue(); addEventListener('pagehide', () => clearTimeout(timer));
  }
  window.TraceBatch = {init, addFiles, setMode};
})();
