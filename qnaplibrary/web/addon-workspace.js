'use strict';
let nonce = '';
let currentDoc = null;
let currentDocBody = '';
let reviewAllowed = false;
let polling = false;
let bridgePort = null;
let imageURL = null;
let imageRequest = 0;
const bridgeCalls = new Map();
const knownJobs = new Map();
const root = location.pathname.startsWith('/addon-frame/') ? '/' + location.pathname.split('/').filter(Boolean).slice(0, 2).join('/') : '';
const el = id => document.getElementById(id);
async function api(path, body, method) {
  if (!nonce) throw new Error('ControlDeckとの接続を待っています。画面を開き直してください。');
  let response;
  try { response = await fetch(root + '/addon/v1/' + path, {method: method || (body ? 'POST' : 'GET'), credentials: 'omit',
    headers: {'Content-Type': 'application/json', 'X-Control-Deck-Bridge-Session': nonce}, body: body ? JSON.stringify(body) : undefined}); }
  catch (_) { throw new Error('通信失敗: ' + path.split('/')[0] + ' / ' + location.protocol + '。ControlDeckの画面を開き直してください。'); }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '接続を確認してください');
  return data;
}
function applyHostTheme(theme) {
  if (!theme || theme.token_version !== '1.0') return;
  const rootEl = document.documentElement;
  rootEl.style.colorScheme = theme.color_scheme === 'dark' ? 'dark' : 'light';
  rootEl.dataset.hostTheme = theme.color_scheme === 'dark' ? 'dark' : 'light';
  for (const name of ['accent', 'bg', 'surface', 'text', 'border', 'muted']) {
    const value = theme[name];
    if (typeof value === 'string' && /^#[0-9a-fA-F]{6}$/.test(value))
      rootEl.style.setProperty('--pb-' + name, value);
  }
  rootEl.classList.toggle('reduce-motion', theme.motion_reduced === true);
}
async function load() {
  try {
    const state = await api('status');
    const s = state.server;
    el('server').textContent = `${s.name}（${s.role}） — ${s.url} / ${s.version ? 'v' + s.version : '未接続'}`;
    el('version').textContent = `PatentBuddy v${state.addon.version} · ControlDeck管理`;
    const ready = s.reachable && !s.setup_required && s.token_configured;
    reviewAllowed = ready && s.knowledge_review_available === true;
    el('message').textContent = ready ? 'ResearchDataHubに接続しました。文献を検索できます。' :
      s.setup_required ? 'ResearchDataHubの管理Webで初期設定を完了してください。' : 'ResearchDataHubの接続トークン設定が必要です。';
    el('submit').disabled = !ready;
    el('import-pdf').disabled = !ready;
    if (ready) await loadLibrary();
  } catch (error) { reviewAllowed = false; el('message').textContent = '読み込みに失敗しました。接続を再確認できます。' + (error instanceof TypeError ? '' : ' ' + error.message); }
}
el('reconnect').onclick = () => load();
window.addEventListener('message', event => {
  let expected = location.origin;
  try { if (document.referrer) expected = new URL(document.referrer).origin; } catch (_) { return; }
  if (event.source !== parent || event.origin !== expected || event.data?.type !== 'control-deck-host.connected' || !event.ports[0]) return;
  nonce = event.data.session_nonce;
  const port = event.ports[0];
  bridgePort = port;
  applyHostTheme(event.data.theme);
  port.onmessage = message => {
    const reply = message.data;
    if (reply?.type === 'response' && bridgeCalls.has(reply.id)) {
      const call = bridgeCalls.get(reply.id); bridgeCalls.delete(reply.id); clearTimeout(call.timer);
      if (reply.ok) call.resolve(reply.result); else call.reject(new Error(reply.error?.message || 'ファイル選択を中断しました'));
    }
    if (message.data?.type === 'event' && message.data.event === 'session.updated') nonce = message.data.data.session_nonce;
    if (message.data?.event === 'theme.changed') applyHostTheme(message.data.data);
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

const KNOWLEDGE_KINDS = {
  problem: '課題', cause: '原因', constraint: '制約', principle: '解決原理',
  mechanism: '作用機構', implementation: '実装', effect: '効果',
  observation: '観測', application: '応用可能性',
};

function focusKnowledgeEvidence(evidence) {
  if (!evidence || !Number.isInteger(evidence.start) || !Number.isInteger(evidence.end)) return;
  // Python stores Unicode code-point offsets; JS slice uses UTF-16 offsets.
  const codepoints = Array.from(currentDocBody);
  if (evidence.start < 0 || evidence.end > codepoints.length || evidence.start >= evidence.end
      || codepoints.slice(evidence.start, evidence.end).join('') !== evidence.quote) {
    el('message').textContent = '原文が更新されています。知識を再抽出して引用を確認してください。';
    return;
  }
  const original = el('body');
  const mark = document.createElement('mark');
  mark.textContent = evidence.quote;
  mark.tabIndex = -1;
  original.replaceChildren(
    document.createTextNode(codepoints.slice(0, evidence.start).join('')),
    mark,
    document.createTextNode(codepoints.slice(evidence.end).join(''))
  );
  el('source-details').open = true;
  mark.scrollIntoView({block: 'center', behavior: 'auto'});
  mark.focus({preventScroll: true});
}

async function loadKnowledge(id) {
  const holder = el('knowledge');
  if (currentDoc !== id) return;
  holder.replaceChildren();
  const loading = document.createElement('p');
  loading.className = 'hint';
  loading.textContent = '保存済みの知識候補を確認しています…';
  holder.append(loading);
  try {
    const data = await api('documents/' + id + '/knowledge-proposals');
    if (currentDoc !== id) return;
    holder.replaceChildren();
    if (!Array.isArray(data.items) || data.items.length === 0) {
      const empty = document.createElement('p');
      empty.className = 'hint';
      empty.textContent = '知識候補はまだありません。分析内容から「知識エッセンスを抽出」を選択してください。';
      holder.append(empty);
      return;
    }
    for (const snapshot of data.items) {
      const parsed = JSON.parse(snapshot.content);
      if (!Array.isArray(parsed.items)) throw new Error('保存済みの知識候補を表示できません');
      const group = document.createElement('details');
      group.className = 'knowledge-group';
      group.open = snapshot === data.items[0];
      const summary = document.createElement('summary');
      summary.textContent = (snapshot.stale ? '原文更新・再抽出が必要' : '未確認の知識候補') +
        ' · ' + parsed.items.length + '件';
      group.append(summary);
      if (!parsed.items.length) {
        const empty = document.createElement('p');
        empty.className = 'hint';
        empty.textContent = '根拠に合致する知識候補はありませんでした。';
        group.append(empty);
      }
      for (const [itemIndex, item] of parsed.items.entries()) {
        const review = snapshot.reviews?.[String(itemIndex)];
        const card = document.createElement('article');
        card.className = 'knowledge-card';
        const title = document.createElement('h3');
        title.textContent = KNOWLEDGE_KINDS[item.kind] || '知識候補';
        const status = document.createElement('p');
        status.className = 'hint';
        const currentDecision = snapshot.stale ? 'unreviewed' : (review?.status || 'unreviewed');
        const reviewNames = {
          approved: '人間が確認済み', rejected: '人間が却下', changes_requested: '差戻し',
          unreviewed: '未確認',
        };
        status.textContent = (snapshot.stale ? '原文変更・以前のレビューは失効 · ' : '') +
          'AI推論 · ' + (reviewNames[currentDecision] || '未確認') +
          '（技術的事実の確定ではありません）';
        const statement = document.createElement('p');
        statement.className = 'knowledge-statement';
        statement.textContent = item.statement;
        const details = document.createElement('details');
        const heading = document.createElement('summary');
        heading.textContent = '引用・条件・限界を確認';
        const quote = document.createElement('blockquote');
        quote.textContent = item.evidence.quote;
        const context = document.createElement('p');
        context.className = 'hint';
        context.textContent = '条件: ' + (item.conditions.join('、') || '未提示') +
          ' / 限界: ' + (item.limitations.join('、') || '未提示');
        const source = document.createElement('button');
        source.type = 'button';
        source.className = 'secondary';
        source.textContent = snapshot.stale ? '原文が更新されています' : '原文の該当箇所を表示';
        source.disabled = Boolean(snapshot.stale);
        source.onclick = () => focusKnowledgeEvidence(item.evidence);
        details.append(heading, quote, context, source);
        const reviewPanel = document.createElement('details');
        reviewPanel.className = 'knowledge-review';
        const reviewHeading = document.createElement('summary');
        reviewHeading.textContent = 'レビューする（承認・却下・差戻し）';
        reviewPanel.append(reviewHeading);
        if (!reviewAllowed || snapshot.stale) {
          const note = document.createElement('p');
          note.className = 'hint';
          note.textContent = snapshot.stale
            ? '原文の版が更新されています。再抽出した候補を確認してください。'
            : 'レビュー専用の権限が未設定です。ResearchDataHubの管理者に設定を依頼してください。';
          reviewPanel.append(note);
        } else {
          const choice = document.createElement('select');
          choice.setAttribute('aria-label', '知識候補の判断');
          for (const [code, label] of [
            ['', '判断を選択してください'], ['approved', '根拠を確認して承認'],
            ['rejected', '却下'], ['changes_requested', '差戻し'],
          ]) {
            const option = document.createElement('option');
            option.value = code;
            option.textContent = label;
            choice.append(option);
          }
          const submit = document.createElement('button');
          submit.type = 'button';
          submit.textContent = 'レビュー判断を記録';
          submit.disabled = true;
          let pending = null;
          choice.onchange = () => { pending = null; submit.disabled = !choice.value; };
          submit.onclick = async () => {
            if (!choice.value || currentDoc !== id) return;
            submit.disabled = true;
            try {
              // Keep a request ID across transient retries of the same decision.
              if (!pending || pending.decision !== choice.value) {
                pending = {id: crypto.randomUUID().replaceAll('-', ''), decision: choice.value};
              }
              await api('documents/' + id + '/knowledge-proposals/' +
                encodeURIComponent(snapshot.id) + '/reviews', {
                  request_id: pending.id, item_index: itemIndex,
                  source_revision: snapshot.source_revision, decision: pending.decision,
                });
              el('message').textContent = 'レビュー判断を記録しました。AIによる推論は事実と確定していません。';
              await loadKnowledge(id);
            } catch (error) {
              el('message').textContent = 'レビューを記録できませんでした。' + error.message;
              submit.disabled = false;
            }
          };
          reviewPanel.append(choice, submit);
        }
        card.append(title, status, statement, details, reviewPanel);
        group.append(card);
      }
      const historyDetails = document.createElement('details');
      historyDetails.className = 'knowledge-review';
      const historySummary = document.createElement('summary');
      historySummary.textContent = 'レビュー履歴（最大30件）';
      const historyList = document.createElement('div');
      const loadHistory = async () => {
        historyList.textContent = '履歴を読み込んでいます…';
        try {
          const data = await api('documents/' + id + '/knowledge-proposals/' +
            encodeURIComponent(snapshot.id) + '/reviews');
          if (currentDoc !== id) return;
          historyList.replaceChildren();
          const labels = {
            approved: '承認', rejected: '却下', changes_requested: '差戻し',
          };
          if (!data.items.length) historyList.textContent = 'レビュー履歴はまだありません。';
          for (const event of data.items) {
            const row = document.createElement('p');
            row.className = 'hint';
            const date = new Date(event.created * 1000);
            row.textContent = '候補 ' + (event.item_index + 1) + ' · ' +
              (labels[event.decision] || '未確認') +
              (event.stale ? '（旧版・失効）' : '') + ' · ' +
              (Number.isFinite(date.getTime()) ? date.toLocaleString() : '日時不明');
            historyList.append(row);
          }
        } catch (_) {
          historyList.textContent = '履歴を読み込めませんでした。閉じて再度開いてください。';
        }
      };
      historyDetails.addEventListener('toggle', () => {
        if (historyDetails.open) void loadHistory();
      });
      historyDetails.append(historySummary, historyList);
      group.append(historyDetails);
      holder.append(group);
    }
  } catch (_) {
    if (currentDoc !== id) return;
    holder.replaceChildren();
    const message = document.createElement('p');
    message.className = 'hint';
    message.textContent = '知識候補を読み込めませんでした。接続とサーバーの更新状態を確認してください。';
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.className = 'secondary';
    retry.textContent = '知識候補を再読み込み';
    retry.onclick = () => loadKnowledge(id);
    holder.append(message, retry);
  }
}

async function loadAnalyses(id) {
  const data = await api('documents/' + id + '/analyses');
  if (currentDoc !== id) return;
  el('analyses').replaceChildren();
  for (const item of data.items) {
    if (item.kind === 'knowledge') continue;
    const box = document.createElement('div'); box.className = 'analysis';
    const title = document.createElement('h3');
    const analysisNames = {summary: '要約', claims: '請求項の確認', chart: 'クレームチャート', relations: '関係の提案'};
    title.textContent = (analysisNames[item.kind] || '分析結果') + (item.stale ? ' — 原文が更新されています' : ' — 未確認');
    const text = document.createElement('pre'); text.textContent = item.content;
    box.append(title, text); el('analyses').append(box);
  }
}
el('analysis-kind').onchange = () => {
  el('analyze').textContent = el('analysis-kind').value === 'knowledge' ? '知識を抽出' : 'ローカルAIで分析';
};
el('analyze').onclick = async () => {
  if (!currentDoc) return;
  el('analyze').disabled = true;
  try {
    await api('jobs', {doc_id: currentDoc, kind: el('analysis-kind').value});
    el('message').textContent = el('analysis-kind').value === 'knowledge' ? '知識候補の抽出を開始しました。結果は未確認のまま保存されます。' : 'ローカルAIの分析を開始しました。';
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
      const label = document.createElement('p'); label.textContent = `${job.kind === 'knowledge' ? '知識エッセンス' : job.kind === 'claims' ? '請求項の確認' : '要約'} · 文献 ${job.doc_id} — ${job.message}`;
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
      if (job.status === 'succeeded' && knownJobs.get(job.id) !== 'succeeded' && currentDoc === job.doc_id) {
        if (job.kind === 'knowledge') await loadKnowledge(currentDoc);
        else await loadAnalyses(currentDoc);
      }
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
  currentDoc = id; currentDocBody = doc.body || ''; imageRequest++;
  if (imageURL) { URL.revokeObjectURL(imageURL); imageURL = null; }
  el('title').textContent = doc.title || '文献'; el('body').textContent = doc.body || ''; el('detail').hidden = false;
  el('pdf-evidence').hidden = true; el('pdf-evidence').replaceChildren();
  await loadAnalyses(id);
  await loadKnowledge(id);
  if (doc.meta?.source_type !== 'pdf' || currentDoc !== id) return;
  const evidence = await api('documents/' + id + '/pdf-extraction');
  if (currentDoc !== id) return;
  const box = el('pdf-evidence'); box.hidden = false;
  const heading = document.createElement('h3'); heading.textContent = 'PDFの原本とページ根拠';
  const download = document.createElement('button'); download.textContent = '原本PDFを保存';
  download.onclick = async () => {
    download.disabled = true;
    try {
      const response = await fetch(root + '/addon/v1/documents/' + id + '/original.pdf', {credentials: 'omit', headers: {'X-Control-Deck-Bridge-Session': nonce}});
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
        const response = await fetch(root + '/addon/v1/documents/' + id + '/images/' + item.id + '.png', {credentials: 'omit', headers: {'X-Control-Deck-Bridge-Session': nonce}});
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


async function loadLibrary() {
  const data = await api('collections');
  const picker = el('library-collection');
  const previous = picker.value;
  picker.replaceChildren();
  for (const collection of data.collections) {
    const option = document.createElement('option'); option.value = collection.id;
    option.textContent = collection.name; picker.append(option);
  }
  if ([...picker.options].some(option => option.value === previous)) picker.value = previous;
  await showLibrary();
}
async function showLibrary() {
  el('library-items').replaceChildren();
  const cid = Number(el('library-collection').value);
  if (!cid) { el('library-items').textContent = '保存済みの資料はありません。PDFを取り込むとここに表示されます。'; return; }
  const data = await api('library', {collection_id: cid});
  for (const row of data.items) {
    const button = document.createElement('button'); button.className = 'result';
    button.textContent = `${row.ext_id || ''} ${row.title || '無題'} — 原文・保存済み分析を開く`;
    button.onclick = async () => { try { await openDocument(row.id); el('detail').scrollIntoView({behavior:'smooth'}); } catch(error) { el('message').textContent = error.message; } };
    el('library-items').append(button);
  }
  if (!data.items.length) el('library-items').textContent = 'この保存先には資料がありません。';
  el('library-note').textContent = '新しい資料を最大20件表示します。それ以前の資料はキーワードで検索できます。';
}
el('library-collection').onchange = () => showLibrary().catch(error => { el('message').textContent = error.message; });
