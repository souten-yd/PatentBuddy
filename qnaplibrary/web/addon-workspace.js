'use strict';
let nonce = '';
let currentDoc = null;
let polling = false;
let bridgePort = null;
let imageURL = null;
let imageRequest = 0;
const bridgeCalls = new Map();
const knownJobs = new Map();
const root = location.pathname.startsWith('/addon-frame/') ? '/' + location.pathname.split('/').filter(Boolean).slice(0, 2).join('/') : '';
const el = id => document.getElementById(id);
async function api(path, body, method) {
  const response = await fetch(root + '/addon/v1/' + path, {method: method || (body ? 'POST' : 'GET'), credentials: 'include',
    headers: {'Content-Type': 'application/json', 'X-Control-Deck-Bridge-Session': nonce}, body: body ? JSON.stringify(body) : undefined});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '接続を確認してください');
  return data;
}
async function load() {
  try {
    const state = await api('status');
    const s = state.server;
    el('server').textContent = `${s.name}（${s.role}） — ${s.url} / ${s.version ? 'v' + s.version : '未接続'}`;
    el('version').textContent = `PatentBuddy v${state.addon.version} · ControlDeck管理`;
    const ready = s.reachable && !s.setup_required && s.token_configured;
    el('message').textContent = ready ? 'ResearchDataHubに接続しました。文献を検索できます。' :
      s.setup_required ? 'ResearchDataHubの管理Webで初期設定を完了してください。' : 'ResearchDataHubの接続トークン設定が必要です。';
    el('submit').disabled = !ready;
    el('import-pdf').disabled = !ready;
  } catch (error) { el('message').textContent = error.message; }
}
window.addEventListener('message', event => {
  let expected = location.origin;
  try { if (document.referrer) expected = new URL(document.referrer).origin; } catch (_) { return; }
  if (event.source !== parent || event.origin !== expected || event.data?.type !== 'control-deck-host.connected' || !event.ports[0]) return;
  nonce = event.data.session_nonce;
  const port = event.ports[0];
  bridgePort = port;
  port.onmessage = message => {
    const reply = message.data;
    if (reply?.type === 'response' && bridgeCalls.has(reply.id)) {
      const call = bridgeCalls.get(reply.id); bridgeCalls.delete(reply.id); clearTimeout(call.timer);
      if (reply.ok) call.resolve(reply.result); else call.reject(new Error(reply.error?.message || 'ファイル選択を中断しました'));
    }
    if (message.data?.type === 'event' && message.data.event === 'session.updated') nonce = message.data.data.session_nonce;
    if (message.data?.event === 'theme.changed') document.documentElement.style.colorScheme = message.data.data?.mode || 'light dark';
  };
  port.start();
  load();
});
if (parent !== window) parent.postMessage({type: 'control-deck-addon.connect', bridge_version: '1.0'}, '*');
else el('message').textContent = 'ControlDeckの「特許」から開いてください。';
el('search').addEventListener('submit', async event => {
  event.preventDefault(); el('submit').disabled = true; el('message').textContent = '検索中…';
  try {
    const data = await api('search', {q: el('query').value});
    el('results').replaceChildren();
    for (const row of data.results) {
      const button = document.createElement('button'); button.className = 'result';
      button.textContent = `${row.ext_id || ''} ${row.title || '無題'}\n${row.snippet || ''}`;
      button.onclick = async () => {
        try {
          await openDocument(row.doc_id);
        } catch (error) { el('message').textContent = error.message; }
      };
      el('results').append(button);
    }
    el('message').textContent = `${data.results.length}件の文献が見つかりました。`;
  } catch (error) { el('message').textContent = error.message; }
  finally { el('submit').disabled = false; }
});

async function loadAnalyses(id) {
  const data = await api('documents/' + id + '/analyses');
  if (currentDoc !== id) return;
  el('analyses').replaceChildren();
  for (const item of data.items) {
    const box = document.createElement('div'); box.className = 'analysis';
    const title = document.createElement('h3');
    title.textContent = (item.kind === 'claims' ? '請求項の確認' : '要約') + (item.stale ? ' — 原文が更新されています' : ' — 未確認');
    const text = document.createElement('pre'); text.textContent = item.content;
    box.append(title, text); el('analyses').append(box);
  }
}
el('analyze').onclick = async () => {
  if (!currentDoc) return;
  el('analyze').disabled = true;
  try {
    await api('jobs', {doc_id: currentDoc, kind: el('analysis-kind').value});
    el('message').textContent = 'ローカルAIの分析を開始しました。';
    await loadJobs();
  } catch (error) { el('message').textContent = error.message; }
  finally { el('analyze').disabled = false; }
};
async function loadJobs() {
  if (polling || !nonce || document.hidden) return;
  polling = true;
  try {
    const data = await api('jobs');
    el('jobs').replaceChildren();
    if (!data.items.length) el('jobs').textContent = '実行中の分析はありません。';
    for (const job of data.items) {
      const row = document.createElement('div'); row.className = 'job'; row.dataset.status = job.status;
      const label = document.createElement('p'); label.textContent = `${job.kind === 'claims' ? '請求項の確認' : '要約'} · 文献 ${job.doc_id} — ${job.message}`;
      row.append(label);
      if (['queued', 'running'].includes(job.status)) {
        const cancel = document.createElement('button'); cancel.textContent = 'キャンセル';
        cancel.onclick = async () => {
          cancel.disabled = true;
          try { await api('jobs/' + job.id + '/cancel', {}); }
          catch (error) { el('message').textContent = error.message; }
          finally { await loadJobs(); }
        };
        row.append(cancel);
      } else if (['failed', 'canceled', 'interrupted'].includes(job.status)) {
        const rerun = document.createElement('button'); rerun.textContent = '現在の原文で再実行';
        rerun.onclick = async () => {
          rerun.disabled = true;
          try { await api('jobs', {doc_id: job.doc_id, kind: job.kind, resume_id: job.id}); }
          catch (error) { el('message').textContent = error.message; }
          finally { await loadJobs(); }
        };
        row.append(rerun);
      }
      if (job.host_sync_pending) {
        const sync = document.createElement('button'); sync.textContent = 'Hostへ完了状態を再送';
        sync.onclick = async () => {
          sync.disabled = true;
          try { await api('jobs/' + job.id + '/reconcile', {}); }
          catch (error) { el('message').textContent = error.message; }
          finally { await loadJobs(); }
        };
        row.append(sync);
      }
      if (!['queued', 'running'].includes(job.status) && !job.host_sync_pending) {
        const menu = document.createElement('details');
        const heading = document.createElement('summary'); heading.textContent = 'その他';
        const forget = document.createElement('button'); forget.textContent = '処理履歴から除外（分析結果は保持）';
        forget.onclick = async () => {
          try { await api('jobs/' + job.id, undefined, 'DELETE'); }
          catch (error) { el('message').textContent = error.message; }
          finally { await loadJobs(); }
        };
        menu.append(heading, forget); row.append(menu);
      }
      el('jobs').append(row);
      if (job.status === 'succeeded' && knownJobs.get(job.id) !== 'succeeded' && currentDoc === job.doc_id) await loadAnalyses(currentDoc);
      knownJobs.set(job.id, job.status);
    }
    await loadPDFJobs();
  } catch (error) { el('jobs').textContent = error.message; }
  finally { polling = false; }
}
setInterval(loadJobs, 2500);


function hostCall(method, params) {
  return new Promise((resolve, reject) => {
    if (!bridgePort) { reject(new Error('ControlDeckへの接続を待ってください')); return; }
    const id = crypto.randomUUID();
    const timer = setTimeout(() => { bridgeCalls.delete(id); reject(new Error('ファイル選択の待ち時間を超えました')); }, 300000);
    bridgeCalls.set(id, {resolve, reject, timer});
    bridgePort.postMessage({type: 'request', id, method, params, session_nonce: nonce});
  });
}
async function startPDF(resumeId) {
  const text = el('ocr-pages').value.trim();
  if (text && !/^\d+(\s*,\s*\d+)*$/.test(text)) throw new Error('ページ番号をカンマで区切って指定してください');
  const pages = text ? text.split(',').map(x => Number(x.trim())) : [];
  if (pages.some(x => x < 1 || x > 200) || pages.length > 200) throw new Error('ページは1〜200で指定してください');
  const selected = await hostCall('host.file.pick', {mode: 'file', title: '取り込むPDFを選択'});
  await api('pdf-jobs', {grant_id: selected.grant_id, force_pages: pages, resume_id: resumeId || null});
  el('message').textContent = 'PDFの取り込みを開始しました。';
  await loadPDFJobs();
}
el('import-pdf').onclick = async () => {
  el('import-pdf').disabled = true;
  try { await startPDF(); } catch (error) { el('message').textContent = error.message; }
  finally { el('import-pdf').disabled = false; try { await loadPDFJobs(); } catch (_) {} }
};
async function openDocument(id) {
  const doc = await api('documents/' + id);
  currentDoc = id; imageRequest++;
  if (imageURL) { URL.revokeObjectURL(imageURL); imageURL = null; }
  el('title').textContent = doc.title || '文献'; el('body').textContent = doc.body || ''; el('detail').hidden = false;
  el('pdf-evidence').hidden = true; el('pdf-evidence').replaceChildren();
  await loadAnalyses(id);
  if (doc.meta?.source_type !== 'pdf' || currentDoc !== id) return;
  const evidence = await api('documents/' + id + '/pdf-extraction');
  if (currentDoc !== id) return;
  const box = el('pdf-evidence'); box.hidden = false;
  const heading = document.createElement('h3'); heading.textContent = 'PDFの原本とページ根拠';
  const download = document.createElement('button'); download.textContent = '原本PDFを保存';
  download.onclick = async () => {
    download.disabled = true;
    try {
      const response = await fetch(root + '/addon/v1/documents/' + id + '/original.pdf', {credentials: 'include', headers: {'X-Control-Deck-Bridge-Session': nonce}});
      if (!response.ok) throw new Error('原本PDFを取得できません');
      const url = URL.createObjectURL(await response.blob());
      const a = document.createElement('a'); a.href = url; a.download = 'original.pdf'; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (error) { el('message').textContent = error.message; }
    finally { download.disabled = false; }
  };
  const source = document.createElement('p'); source.className = 'hint';
  source.textContent = `原本 SHA-256: ${evidence.sha256} · ${evidence.page_count}ページ · OCR結果は未確認です`;
  box.append(heading, download, source);
  if (evidence.images?.length) {
    const gallery = document.createElement('div'); gallery.id = 'pdf-image-viewer';
    const label = document.createElement('label'); label.textContent = 'PDF内の画像';
    const select = document.createElement('select'); select.setAttribute('aria-label', 'PDF内の画像');
    const placeholder = document.createElement('option'); placeholder.value = ''; placeholder.textContent = `${evidence.images.length}点から選択`; select.append(placeholder);
    for (const item of evidence.images) {
      const option = document.createElement('option'); option.value = String(item.id);
      option.textContent = `ページ ${item.page} / 画像 ${item.id + 1} (${item.width}×${item.height})`; select.append(option);
    }
    const view = document.createElement('img'); view.hidden = true;
    const caption = document.createElement('p'); caption.className = 'hint';
    caption.textContent = '表紙や図面に含まれる画像です。図番号は原本と照合してください。';
    const save = document.createElement('a'); save.hidden = true; save.textContent = '表示中の画像を保存';
    select.onchange = async () => {
      const request = ++imageRequest; const item = evidence.images.find(x => String(x.id) === select.value);
      view.hidden = true; save.hidden = true;
      if (imageURL) { URL.revokeObjectURL(imageURL); imageURL = null; }
      if (!item) return;
      try {
        const response = await fetch(root + '/addon/v1/documents/' + id + '/images/' + item.id + '.png', {credentials: 'include', headers: {'X-Control-Deck-Bridge-Session': nonce}});
        if (!response.ok) throw new Error('画像を取得できません');
        const blob = await response.blob();
        if (request !== imageRequest || currentDoc !== id) return;
        imageURL = URL.createObjectURL(blob); view.src = imageURL; view.alt = `ページ${item.page}の埋め込み画像${item.id + 1}`; view.hidden = false;
        save.href = imageURL; save.download = `page-${item.page}-image-${item.id + 1}.png`; save.hidden = false;
      } catch (error) { el('message').textContent = error.message; }
    };
    label.append(select); gallery.append(label, caption, view, save); box.append(gallery);
  }
  for (const page of evidence.pages) {
    const details = document.createElement('details'); const label = document.createElement('summary');
    const method = page.method === 'pdf_text' ? '文字を直接抽出' : page.method === 'pdf_text_and_ocr' ? '直接抽出＋OCR' : 'OCR';
    label.textContent = `ページ ${page.page} — ${method}` + (page.low_confidence_words ? ` · 要確認 ${page.low_confidence_words}語` : '');
    const body = document.createElement('pre'); body.textContent = page.text || '読み取れる文字がありません。原本の図を確認してください。';
    details.append(label, body); box.append(details);
  }
}
async function loadPDFJobs() {
  const data = await api('pdf-jobs'); const box = el('pdf-jobs'); box.replaceChildren();
  el('import-pdf').disabled = data.items.some(job => ['queued', 'running'].includes(job.status));
  for (const job of data.items) {
    const row = document.createElement('div'); row.className = 'job'; row.dataset.status = job.status;
    const label = document.createElement('p'); label.textContent = job.message; row.append(label);
    function button(title, action) {
      const b = document.createElement('button'); b.textContent = title;
      b.onclick = async () => { b.disabled = true; try { await action(); } catch (error) { el('message').textContent = error.message; } finally { await loadPDFJobs(); } };
      row.append(b);
    }
    if (['queued', 'running'].includes(job.status)) button('PDF取り込みをキャンセル', () => api('pdf-jobs/' + job.id + '/cancel', {}));
    else {
      if (job.doc_id) button('取り込んだ文献を開く', () => openDocument(job.doc_id));
      if (job.host_sync_pending || job.status === 'interrupted') button('保存・Host状態を確認', () => api('pdf-jobs/' + job.id + '/reconcile', {}));
      else {
        if (['failed', 'canceled'].includes(job.status)) button('PDFを再選択して実行', () => startPDF(job.id));
        button('履歴から除外（資料は保持）', () => api('pdf-jobs/' + job.id, undefined, 'DELETE'));
      }
    }
    box.append(row);
  }
}
