'use strict';
let nonce = '';
let currentDoc = null;
let polling = false;
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
  } catch (error) { el('message').textContent = error.message; }
}
window.addEventListener('message', event => {
  let expected = location.origin;
  try { if (document.referrer) expected = new URL(document.referrer).origin; } catch (_) { return; }
  if (event.source !== parent || event.origin !== expected || event.data?.type !== 'control-deck-host.connected' || !event.ports[0]) return;
  nonce = event.data.session_nonce;
  const port = event.ports[0];
  port.onmessage = message => {
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
          const doc = await api('documents/' + row.doc_id);
          el('title').textContent = doc.title || '文献'; el('body').textContent = doc.body || ''; el('detail').hidden = false; currentDoc = row.doc_id; await loadAnalyses(currentDoc);
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
      const row = document.createElement('div'); row.className = 'job';
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
  } catch (error) { el('jobs').textContent = error.message; }
  finally { polling = false; }
}
setInterval(loadJobs, 2500);
