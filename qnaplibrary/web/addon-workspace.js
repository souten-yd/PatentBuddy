'use strict';
let nonce = '';
let currentDoc = null;
let currentDocBody = '';
let currentKnowledgeMap = null;
let selectedMapId = null;
let mapRequest = 0;
let reviewAllowed = false;
let linkAllowed = false;
let ideaWriteReady = false;
let linkSources = [];
let linkTarget = null;
let polling = false;
let bridgePort = null;
let imageURL = null;
let imageRequest = 0;
const bridgeCalls = new Map();
const knownJobs = new Map();
const root = location.pathname.startsWith('/addon-frame/') ? '/' + location.pathname.split('/').filter(Boolean).slice(0, 2).join('/') : '';
const el = id => document.getElementById(id);
// Local, in-workspace step selector. ControlDeck owns the global shell, route,
// history, theme, authentication and mobile navigation. These are content panels.
const WORKSPACE_STEPS = ['research', 'knowledge', 'ideas'];
let activeWorkspace = 'research';
let sourceReturnWorkspace = null;
let activeAnalysisJobs = 0;
let activePDFJobs = 0;
function switchWorkspace(next, {focusTab = false, scroll = true} = {}) {
  if (!WORKSPACE_STEPS.includes(next)) return;
  activeWorkspace = next;
  if (next === 'knowledge' && !atlasLoaded && !atlasLoading) void loadAtlas(0);
  for (const step of WORKSPACE_STEPS) {
    const tab = el('workspace-tab-' + step);
    const pane = el('workspace-panel-' + step);
    const active = step === next;
    tab.setAttribute('aria-selected', active ? 'true' : 'false');
    tab.tabIndex = active ? 0 : -1;
    pane.hidden = !active;
  }
  if (focusTab) el('workspace-tab-' + next).focus({preventScroll: true});
  if (scroll) el('workspace-tabs').scrollIntoView({block: 'start', behavior: 'auto'});
}
WORKSPACE_STEPS.forEach((step, index) => {
  const tab = el('workspace-tab-' + step);
  tab.onclick = () => switchWorkspace(step, {focusTab: true});
  tab.onkeydown = event => {
    const last = WORKSPACE_STEPS.length - 1;
    let target = index;
    if (event.key === 'ArrowRight') target = (index + 1) % WORKSPACE_STEPS.length;
    else if (event.key === 'ArrowLeft') target = (index + last) % WORKSPACE_STEPS.length;
    else if (event.key === 'Home') target = 0;
    else if (event.key === 'End') target = last;
    else return;
    event.preventDefault();
    switchWorkspace(WORKSPACE_STEPS[target], {focusTab: true});
  };
});
function updateActivitySummary() {
  const count = activeAnalysisJobs + activePDFJobs;
  const label = el('workspace-job-count');
  label.textContent = count > 0 ? count + '件を処理中' : '処理履歴を確認';
  label.dataset.active = count > 0 ? 'true' : 'false';
}
el('workspace-source-return').onclick = () => {
  const previous = sourceReturnWorkspace;
  if (!previous || !WORKSPACE_STEPS.includes(previous) || previous === 'research') return;
  sourceReturnWorkspace = null;
  el('workspace-source-return').hidden = true;
  switchWorkspace(previous, {focusTab: true, scroll: false});
  const destination = previous === 'ideas' ? el('idea-form') :
    (el('cross-compare-results').hasChildNodes() ? el('cross-compare-results') :
      el('knowledge-search-section'));
  destination.scrollIntoView({block: 'start', behavior: 'auto'});
};
el('document-compare-action').onclick = () => {
  switchWorkspace('knowledge', {focusTab: true});
  el('cross-query').focus({preventScroll: true});
};
el('research-pdf-quick').onclick = () => {
  switchWorkspace('research', {scroll: false});
  el('workspace-pdf-import').open = true;
  el('workspace-pdf-import').scrollIntoView({block: 'start', behavior: 'auto'});
  el('import-pdf').focus({preventScroll: true});
};

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
    const indicator = el('connection-state');
    indicator.dataset.state = ready ? 'ready' : 'attention';
    indicator.textContent = ready ? '接続済み' :
      (s.setup_required ? '初期設定が必要' : '再接続が必要');
    reviewAllowed = ready && s.knowledge_review_available === true;
    linkAllowed = ready && s.knowledge_link_available === true;
    ideaWriteReady = ready && s.idea_write_available === true;
    updateIdeaSaveState();
    updateLinkPreview();
    el('message').textContent = ready ? 'ResearchDataHubに接続しました。文献を検索できます。' :
      s.setup_required ? 'ResearchDataHubの管理Webで初期設定を完了してください。' : 'ResearchDataHubの接続トークン設定が必要です。';
    el('submit').disabled = !ready;
    el('cross-search-submit').disabled = !ready;
    el('import-pdf').disabled = !ready;
    if (ready) {
      await loadLibrary();
      await loadIdeas();
    }
  } catch (error) {
    reviewAllowed = false; linkAllowed = false; ideaWriteReady = false;
    el('connection-state').dataset.state = 'attention';
    el('connection-state').textContent = '接続を確認してください';
    el('cross-search-submit').disabled = true;
    el('submit').disabled = true;
    el('import-pdf').disabled = true;
    updateIdeaSaveState();
    el('message').textContent = '読み込みに失敗しました。接続を再確認できます。' +
      (error instanceof TypeError ? '' : ' ' + error.message);
  }
}
el('reconnect').onclick = () => load();

function sourceMiB(bytes) {
  return (Math.max(0, Number(bytes) || 0) / (1024 * 1024)).toLocaleString('ja-JP', {maximumFractionDigits: 1}) + ' MiB';
}

const ipcSectionLabels = {
  A: '生活', B: '処理・運輸', C: '化学・冶金', D: '繊維・紙',
  E: '固定構造物', F: '機械工学', G: '物理', H: '電気'
};
function sourcePickCode(code, label) {
  const list = el('source-ipc-select');
  if (![...list.options].some(item => item.value === code)) {
    const option = document.createElement('option');
    option.value = code;
    option.textContent = code + ' · ' + (label || '公式IPCに収録');
    list.append(option);
  }
  list.value = code;
  el('source-scope').open = true;
  el('source-scope-status').textContent =
    code + 'を仮選択しました。分類の定義と公開範囲を確認してください。';
}
async function sourceBrowseIPC(parent = '') {
  const result = await api('ipc-catalog/browse', {parent});
  const holder = el('source-catalog-tree');
  holder.replaceChildren();
  const status = el('source-catalog-browser-status');
  status.textContent = 'WIPO IPC ' + result.version + ' / ' +
    (parent || '大分類') + ' / ' + result.level + ' の記号（分類名は別資料）';
  if (parent) {
    const back = document.createElement('button');
    back.type = 'button'; back.className = 'secondary'; back.textContent = '上の階層へ';
    back.onclick = () => sourceBrowseIPC(parent.length === 4 ? parent.slice(0,3) :
      parent.length === 3 ? parent.slice(0,1) : '').catch(error => {
      status.textContent = error.message;
    });
    holder.append(back);
  }
  for (const item of result.items) {
    const btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'secondary';
    btn.textContent = item.code +
      (result.level === 'section' ? ' · ' + (ipcSectionLabels[item.code] || '') +
        (!item.imported ? '（未取込）' : '') : '');
    btn.onclick = () => {
      if (result.level === 'section' && !item.imported) {
        status.textContent = item.code + 'は未登録です。ResearchDataHub管理画面の「収集」から公式辞書を取り込んでください。';
      } else if (result.level === 'subclass') {
        sourcePickCode(item.code);
      } else if (result.level !== 'group') {
        sourceBrowseIPC(item.code).catch(error => {status.textContent = error.message;});
      }
    };
    holder.append(btn);
  }
}
el('source-catalog-open').onclick = () => sourceBrowseIPC().catch(error => {
  el('source-catalog-browser-status').textContent = '分類を取得できません: ' + error.message;
});
async function sourceLoadAdvisorModels() {
  const selection = el('source-ai-provider');
  const ask = el('source-ai-ask');
  const status = el('source-ai-status');
  selection.replaceChildren();
  ask.disabled = true;
  try {
    const data = await api('source-assistant/options');
    for (const model of data.models) {
      const option = document.createElement('option');
      option.value = model.id;
      option.textContent = model.label;
      selection.append(option);
    }
    ask.disabled = !data.models.length;
    status.textContent = data.models.length ?
      '検証済みローカルAIだけが表示されます。問い合わせはボタンを押した場合のみ実行します。' :
      'ローカルAI未接続です。代わりに公式IPC分類から選択してください。';
  } catch (error) {
    status.textContent = 'ローカルAIの情報を取得できません: ' + error.message;
  }
}
el('source-ai-ask').onclick = async () => {
  const button = el('source-ai-ask');
  const status = el('source-ai-status');
  const holder = el('source-ai-candidates');
  holder.replaceChildren();
  button.disabled = true;
  status.textContent = '検証済みローカルAIに問い合わせています…';
  try {
    const result = await api('source-assistant/ask', {
      question: el('source-topic').value.trim(),
      provider: el('source-ai-provider').value
    });
    const explanation = document.createElement('p');
    explanation.textContent = result.reason +
      (result.clarify ? ' / 確認事項: ' + result.clarify : '');
    holder.append(explanation);
    for (const item of result.codes) {
      const btn = document.createElement('button');
      btn.type = 'button'; btn.className = 'secondary';
      btn.textContent = item.code + (item.label ? ' · ' + item.label : '') +
        (item.official_catalog_verified ? '（辞書照合済）' : '（未登録）');
      btn.disabled = !item.official_catalog_verified;
      btn.onclick = () => sourcePickCode(item.code, item.label);
      holder.append(btn);
    }
    status.textContent = result.codes.length ?
      'AIの候補は未確認です。公式辞書と照合済みのコードだけ選択できます。' :
      '候補を確定できません。公式IPC分類から選択してください。';
  } catch (error) {
    status.textContent = '分類を提案できません: ' + error.message;
  } finally {button.disabled = !el('source-ai-provider').value;}
};

el('source-plan-form').onsubmit = async event => {
  event.preventDefault();
  const button = el('source-plan-go');
  button.disabled = true;
  el('source-plan-status').textContent = '分類候補を調べています…';
  el('source-plan-results').replaceChildren();
  try {
    const result = await api('source-plan', {topic: el('source-topic').value.trim()});
    const holder = el('source-plan-results');
    const selector = el('source-ipc-select');
    selector.replaceChildren();
    const empty = document.createElement('option');
    empty.value = '';
    empty.textContent = '分類を選択してください';
    selector.append(empty);
    for (const candidate of result.candidates.slice(0, 10)) {
      const option = document.createElement('option');
      option.value = candidate.code;
      option.textContent = candidate.code + ' · ' + candidate.label;
      selector.append(option);
      const card = document.createElement('p');
      card.className = 'hint';
      card.textContent = candidate.code + ' · ' + candidate.label + '（未確認の候補） / EPO式: ' + candidate.cql_preview;
      holder.append(card);
    }
    for (const match of (result.local_classification_matches || []).slice(0, 8)) {
      const line = document.createElement('p');
      line.textContent = '保存済み分類辞書: ' + match.code + ' · ' + match.title +
        '（未承認／外部検索対象ではありません）';
      holder.append(line);
    }
    el('source-plan-status').textContent = result.candidates.length
      ? result.candidates.length + '分類を提案しました。辞書と原典で照合し、公開情報だけを外部検索してください。'
      : '初期候補はありません。分類辞書からの追加候補も確認してください。';
  } catch (error) {
    el('source-plan-status').textContent = '分類候補を取得できません: ' + error.message;
  } finally { button.disabled = false; }
};
el('source-year-to').value = String(new Date().getFullYear());
el('source-scope-preview').onclick = async () => {
  const button = el('source-scope-preview');
  button.disabled = true;
  const status = el('source-scope-status');
  status.textContent = 'ローカルの検索式を確認しています…';
  try {
    const from = el('source-year-from').value;
    const to = el('source-year-to').value;
    const result = await api('source-scope/preview', {
      ipc: el('source-ipc-select').value, limit: Number(el('source-page-limit').value),
      publication_country: el('source-office').value,
      year_from: from === '' ? null : Number(from),
      year_to: to === '' ? null : Number(to),
      first: Number(el('source-page-first').value)
    });
    status.textContent = 'EPO公開書誌検索式: ' + result.cql +
      ' · ' + result.first_result + '〜' + result.last_result + '件目。' +
      ' この確認だけでは外部照会・保存を行いません。実行はResearchDataHub管理画面から行います。';
  } catch (error) {
    status.textContent = '確認できません: ' + error.message;
  } finally { button.disabled = false; }
};
el('source-storage-refresh').onclick = async () => {
  const button = el('source-storage-refresh');
  button.disabled = true;
  el('source-storage-status').textContent = '容量を計測しています…';
  try {
    const [result, receipts] = await Promise.all([
      api('source-storage'), api('source-acquisitions')
    ]);
    const u = result.usage, f = u.files, c = u.counts || {};
    el('source-storage-status').textContent =
      'DB ' + sourceMiB(f.sqlite_bytes) + ' / WAL ' + sourceMiB(f.wal_bytes) +
      ' / SHM ' + sourceMiB(f.shm_bytes) + ' · 空き ' + sourceMiB(u.disk_free_bytes) +
      ' · ソフト上限 ' + sourceMiB(u.soft_limit_bytes) +
      ' · 文献 ' + (c.documents ?? '未計測') + '件 / 原本PDF ' + (c.pdf_originals ?? '未計測') +
      '件 / PDF画像 ' + (c.pdf_images ?? '未計測') + '件' +
      (u.soft_limit_reached ? ' · 新規分類収集の上限超過' : '');
    const overview = el('source-breakdown');
    overview.replaceChildren();
    const sample = result.by_source_sample;
    if (sample?.items?.length) {
      const description = document.createElement('p');
      description.textContent = '新しい文献' + sample.documents_examined + '件のタイトル・メタデータ容量の参考値（本文・PDF・画像・索引は除外）' +
        (sample.has_older_documents ? '（過去の文献は標本外）' : '') + '。物理ディスク使用量ではありません。';
      overview.append(description);
      for (const source of sample.items.slice(0, 8)) {
        const row = document.createElement('p');
        row.textContent = source.source + ': ' + source.documents_in_sample + '件 / ' +
          sourceMiB(source.metadata_bytes_in_sample);
        overview.append(row);
      }
    }
    const recent = el('source-acquisition-receipts');
    recent.replaceChildren();
    const rows = receipts.items || [];
    const hint = document.createElement('p');
    hint.textContent = '分類別の手動取得履歴（最大' + rows.length + '件）。管理者はResearchDataHubの「収集」で操作できます。';
    recent.append(hint);
    for (const item of rows.slice(0, 6)) {
      const row = document.createElement('p');
      row.textContent = item.source + ' ' + item.classification +
        ' / ' + (item.publication_country || 'ALL') +
        ' / ' + (item.publication_year_from ?? '全年') + '〜' +
        (item.publication_year_to ?? '全年') + '年 / ' +
        (item.first_result || 1) + '件目から · ' +
        (item.status === 'succeeded' ? '成功' : item.status === 'failed' ? '失敗' : item.possibly_interrupted ? '中断の可能性' : '進行中') +
        ' · 取得' + item.received + '件 / 新規' + item.added + '件';
      recent.append(row);
    }
  } catch (error) {
    el('source-storage-status').textContent = '容量を確認できません: ' + error.message;
  } finally { button.disabled = false; }
};

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
  sourceLoadAdvisorModels();
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

// K4: read-only reviewed-essence discovery and literal side-by-side comparison.
// Search text is sent in a POST body, not embedded in a URL or local storage.
let crossRequest = 0;
let crossCompareRequest = 0;
let crossItems = [];
let crossFilters = null;
let crossNextCursor = null;
const CROSS_MAX_ON_SCREEN = 60;
const crossSelected = new Map();
const CROSS_LABELS = {
  problem: '課題', cause: '原因', constraint: '制約', principle: '解決原理',
  mechanism: '作用機構', implementation: '実装', effect: '効果',
  observation: '観測', application: '応用',
};
function crossKey(item) {
  return item.proposal_id + ':' + item.item_index;
}
function clearCrossSelection() {
  ++crossCompareRequest;
  lastComparedItems = [];
  crossSelected.clear();
  for (const input of el('cross-results').querySelectorAll('input[type="checkbox"]'))
    input.checked = false;
  el('cross-compare-results').replaceChildren();
  updateCrossSelection();
}
function updateCrossSelection() {
  const items = Array.from(crossSelected.values());
  const distinct = new Set(items.map(item => item.doc_id)).size;
  el('cross-selection').textContent = items.length + '件選択中（異なる文献 ' +
    distinct + '件）。別文献から2〜3件を選択してください。';
  el('cross-compare-button').disabled =
    !(items.length >= 2 && items.length <= 3 && distinct >= 2);
}
el('cross-clear-button').onclick = clearCrossSelection;
function crossParagraph(title, contents) {
  const p = document.createElement('p');
  const strong = document.createElement('strong');
  strong.textContent = title + '：';
  p.append(strong, document.createTextNode(contents || '未記載'));
  return p;
}
function crossOpenSource(item) {
  return async event => {
    const previous = activeWorkspace;
    const button = event?.currentTarget;
    if (button) button.disabled = true;
    el('message').textContent = '根拠の原文を開いています…';
    try {
      await openDocument(item.doc_id);
      if (currentDoc !== item.doc_id) return;
      sourceReturnWorkspace = previous === 'research' ? null : previous;
      const back = el('workspace-source-return');
      back.hidden = !sourceReturnWorkspace;
      back.textContent = previous === 'ideas' ? 'Idea Canvasへ戻る' : '比較画面へ戻る';
      focusKnowledgeEvidence(item.evidence);
    } catch (_) {
      switchWorkspace(previous, {scroll: false});
      const status = previous === 'ideas' ? el('idea-status') : el('cross-search-status');
      status.textContent = '元文献を開けませんでした。接続・権限・原文の版を確認してください。';
    } finally {
      if (button) button.disabled = false;
    }
  };
}
function crossRenderSearch(items, append = false) {
  const container = el('cross-results');
  if (!append) container.replaceChildren();
  if (!items.length && !append) {
    container.textContent = '現在の条件に一致する承認済みの知識はありません。検索語・種類を変更してください。';
    const back = document.createElement('button');
    back.type = 'button';
    back.className = 'secondary workspace-empty-action';
    back.textContent = '資料へ戻って知識を抽出・確認する';
    back.onclick = () => switchWorkspace('research', {focusTab: true});
    container.append(back);
    return;
  }
  for (const item of items) {
    const card = document.createElement('article');
    card.className = 'cross-hit';
    const title = document.createElement('h3');
    title.textContent = (CROSS_LABELS[item.kind] || '知識') + ' · ' +
      item.statement;
    const info = document.createElement('p');
    info.className = 'hint';
    info.textContent = (item.title || '文献') + '（文献 ' + item.doc_id +
      '） · 人間レビュー済みのAI推論（確定事実ではありません）';
    const quote = document.createElement('blockquote');
    quote.textContent = item.evidence.quote;
    const conditions = crossParagraph('成立条件', item.conditions.join('、'));
    const limitations = crossParagraph('限界・注意点', item.limitations.join('、'));
    const actions = document.createElement('div');
    actions.className = 'cross-hit-actions';
    const source = document.createElement('button');
    source.type = 'button';
    source.className = 'secondary';
    source.textContent = '根拠を原文で確認';
    source.onclick = crossOpenSource(item);
    const selection = document.createElement('label');
    selection.className = 'cross-select';
    const check = document.createElement('input');
    check.type = 'checkbox';
    check.setAttribute('aria-label', '比較対象に選択: ' + item.statement.slice(0, 90));
    check.onchange = () => {
      ++crossCompareRequest;
      lastComparedItems = [];
      const key = crossKey(item);
      if (check.checked) {
        if (crossSelected.size >= 3) {
          check.checked = false;
          el('cross-search-status').textContent = '比較は最大3件です。選択を減らしてください。';
          return;
        }
        crossSelected.set(key, item);
      } else crossSelected.delete(key);
      el('cross-compare-results').replaceChildren();
      updateCrossSelection();
    };
    selection.append(check, document.createTextNode('比較対象に選ぶ'));
    actions.append(source, selection);
    card.append(title, info, quote, conditions, limitations, actions);
    container.append(card);
  }
}
el('cross-search-form').addEventListener('submit', async event => {
  event.preventDefault();
  const request = ++crossRequest;
  ++crossCompareRequest;
  const button = el('cross-search-submit');
  button.disabled = true;
  lastComparedItems = [];
  crossSelected.clear();
  crossItems = [];
  crossFilters = {
    q: el('cross-query').value, kind: el('cross-kind').value, limit: 20,
  };
  crossNextCursor = null;
  el('cross-next-button').hidden = true;
  el('cross-next-button').disabled = false;
  el('cross-results').replaceChildren();
  el('cross-compare-results').replaceChildren();
  updateCrossSelection();
  el('cross-search-status').textContent = '確認済み技術知識を横断検索しています…';
  try {
    const result = await api('knowledge/search', {...crossFilters, cursor: 0});
    if (request !== crossRequest) return;
    if (!Array.isArray(result.items)) throw new Error('結果の形式が不正です');
    crossItems = result.items;
    crossRenderSearch(crossItems);
    crossNextCursor = Number.isInteger(result.next_cursor) && result.next_cursor > 0
      ? result.next_cursor : null;
    el('cross-next-button').hidden = !crossNextCursor;
    el('cross-search-status').textContent =
      result.items.length + '件表示 · 最近の承認記録から ' + result.scanned +
      '件を検査（1回上限 ' + result.scan_limit + '件）' +
      (crossNextCursor ? ' · 続きの候補を探せます。' :
        ' · AI推論の人間レビュー結果であり、事実認定ではありません。');
  } catch (_) {
    if (request === crossRequest) {
      el('cross-search-status').textContent =
        '横断検索ができませんでした。ResearchDataHubの接続・版・読取権限を確認して再検索してください。';
    }
  } finally { if (request === crossRequest) button.disabled = false; }
});
el('cross-next-button').onclick = async () => {
  const cursor = crossNextCursor, filters = crossFilters;
  if (!filters || !Number.isInteger(cursor) || cursor <= 0) return;
  const request = ++crossRequest;
  const button = el('cross-next-button');
  button.disabled = true;
  el('cross-search-status').textContent = '古い承認済み知識を確認しています…';
  try {
    const result = await api('knowledge/search', {...filters, cursor});
    if (request !== crossRequest) return;
    if (!Array.isArray(result.items) ||
        result.items.length > 20) throw new Error('不正な検索結果');
    const left = CROSS_MAX_ON_SCREEN - crossItems.length;
    const visible = result.items.slice(0, Math.max(left, 0));
    crossItems.push(...visible);
    crossRenderSearch(visible, true);
    crossNextCursor = Number.isInteger(result.next_cursor) &&
      result.next_cursor > 0 && result.next_cursor < cursor &&
      crossItems.length < CROSS_MAX_ON_SCREEN ? result.next_cursor : null;
    button.hidden = !crossNextCursor;
    el('cross-search-status').textContent =
      '現在' + crossItems.length + '件表示 · 今回' + result.scanned +
      '件を検査（1回上限 ' + result.scan_limit + '件）' +
      (crossItems.length >= CROSS_MAX_ON_SCREEN ?
        ' · 画面表示は60件までです。検索語を絞ってください。' :
        crossNextCursor ? ' · 続きの候補を探せます。' :
        ' · これより古い候補はありません。');
  } catch (_) {
    if (request === crossRequest)
      el('cross-search-status').textContent =
        '次の候補を取得できませんでした。接続を確認して同じボタンで再試行してください。';
  } finally { if (request === crossRequest) button.disabled = false; }
};
el('cross-compare-button').onclick = async () => {
  const selected = Array.from(crossSelected.values());
  if (selected.length < 2 || selected.length > 3 ||
      new Set(selected.map(x => x.doc_id)).size < 2) return;
  const button = el('cross-compare-button');
  const request = ++crossCompareRequest;
  button.disabled = true;
  const out = el('cross-compare-results');
  out.textContent = '選択した根拠と現在の承認状態を再確認しています…';
  try {
    const result = await api('knowledge/compare', {
      items: selected.map(item => ({
        proposal_id: item.proposal_id, item_index: item.item_index,
      })),
    });
    if (request !== crossCompareRequest) return;
    out.replaceChildren();
    if (result.comparison_type !== 'side_by_side_literal' ||
        !Array.isArray(result.items) || result.items.length !== selected.length)
      throw new Error('不正な比較結果');
    const intro = document.createElement('p');
    intro.className = 'hint';
    intro.textContent = 'これは人が確認したAI推論の並列比較です。意味が同じこと、特許の新規性、実現性を保証しません。';
    const grid = document.createElement('div');
    grid.className = 'cross-compare-grid';
    for (const item of result.items) {
      const card = document.createElement('article');
      card.className = 'cross-compare-card';
      const head = document.createElement('h3');
      head.textContent = (CROSS_LABELS[item.kind] || item.kind) + ' · ' + item.title;
      const statement = crossParagraph('技術的な主張', item.statement);
      const conditions = crossParagraph('成立条件', item.conditions.join('、'));
      const limitations = crossParagraph('限界・検証不足', item.limitations.join('、'));
      const quote = document.createElement('blockquote');
      quote.textContent = item.evidence.quote;
      const source = document.createElement('button');
      source.className = 'secondary';
      source.type = 'button';
      source.textContent = '元文献の引用へ移動';
      source.onclick = crossOpenSource(item);
      card.append(head, statement, conditions, limitations, quote, source);
      grid.append(card);
    }
    const common = document.createElement('div');
    common.className = 'cross-common';
    common.append(
      crossParagraph('文言が完全一致する成立条件', result.shared_conditions_exact.join('、')),
      crossParagraph('文言が完全一致する限界', result.shared_limitations_exact.join('、')),
    );
    const note = document.createElement('p');
    note.className = 'hint';
    note.textContent = '表現が異なる項目の意味的な一致・差異は判断していません。異分野応用は検証前の仮説として扱ってください。';
    const canvas = document.createElement('button');
    canvas.type = 'button';
    canvas.className = 'secondary';
    canvas.textContent = 'この比較を材料にIdea Canvasへ';
    canvas.onclick = () => beginIdeaFromComparison(result.items);
    out.append(intro, grid, common, note, canvas);
    out.scrollIntoView({block: 'nearest', behavior: 'auto'});
  } catch (_) {
    if (request === crossCompareRequest)
      out.textContent = '比較を表示できません。承認や原文が更新された可能性があります。再検索して選び直してください。';
  } finally { if (request === crossCompareRequest) updateCrossSelection(); }
};

// K5: nothing is saved by searching, comparing, navigating or typing.
// An Idea is created/edited only by a user-confirmed form submission.
const IDEA_FIELDS = ['title', 'problem', 'solution', 'effect', 'conditions', 'limitations'];
let lastComparedItems = [];
let ideaSources = [];
let currentIdea = null;
let ideaPending = null;
let ideaSaving = false;
let ideaReadRequest = 0;
let ideaDirty = false;
function ideaContent() {
  return Object.fromEntries(IDEA_FIELDS.map(field =>
    [field, el('idea-' + field).value.trim()]));
}
function ideaSourceSelectors() {
  return ideaSources.map(item => ({
    proposal_id: item.proposal_id, item_index: item.item_index,
    doc_id: item.doc_id, source_revision: item.source_revision,
    source_epoch: item.source_epoch, review_seq: item.review_seq,
  }));
}
function updateIdeaSaveState() {
  const content = ideaContent();
  const active = !currentIdea || !currentIdea.stale;
  const confirmed = el('idea-confirm').checked;
  el('idea-save').disabled = !(
    ideaWriteReady && !ideaSaving && active && confirmed &&
    ideaSources.length >= 2 && ideaSources.length <= 3 &&
    new Set(ideaSources.map(s => s.doc_id)).size >= 2 &&
    content.title && content.problem && content.solution
  );
  if (!ideaWriteReady) el('idea-save-status').textContent =
    'Idea専用保存権限がありません。ResearchDataHubで権限を設定してください。';
}
function showIdeaSources() {
  const box = el('idea-source-list');
  box.replaceChildren();
  for (const source of ideaSources) {
    const article = document.createElement('article');
    article.className = 'idea-source';
    const heading = document.createElement('h4');
    heading.textContent = source.title || '文献 ' + source.doc_id;
    const statement = document.createElement('p');
    statement.textContent = source.statement;
    const quote = document.createElement('blockquote');
    quote.textContent = source.evidence.quote;
    const note = document.createElement('p');
    note.className = 'hint';
    note.textContent = source.status === 'needs_revalidation'
      ? '旧版・承認変更：再比較が必要'
      : '人間承認済みAI推論（事実・特許性の認定ではありません）';
    const open = document.createElement('button');
    open.className = 'secondary';
    open.type = 'button';
    open.textContent = '元文献の引用へ';
    open.disabled = source.status === 'needs_revalidation';
    open.onclick = crossOpenSource(source);
    article.append(heading, statement, quote, note, open);
    box.append(article);
  }
}
function showIdeaHistory(detail) {
  const box = el('idea-history');
  box.replaceChildren();
  if (!detail?.history?.length) return;
  const disclosure = document.createElement('details');
  const summary = document.createElement('summary');
  summary.textContent = '編集履歴（直近20版・上書きされません）';
  disclosure.append(summary);
  for (const record of detail.history) {
    const row = document.createElement('div');
    row.className = 'idea-history-version';
    const show = document.createElement('button');
    show.type = 'button';
    show.className = 'secondary';
    const date = new Date(record.created * 1000);
    show.textContent = '第' + record.version + '版を読み取る · ' +
      (Number.isFinite(date.getTime()) ? date.toLocaleString() : '日時不明');
    const historical = document.createElement('div');
    show.onclick = async () => {
      show.disabled = true;
      historical.textContent = '過去の案を読み込んでいます…';
      try {
        const old = await api('ideas/' + detail.id + '/versions/' + record.version);
        if (currentIdea?.id !== detail.id) return;
        if (!old.read_only || old.version !== record.version || old.id !== detail.id)
          throw new Error('不正な履歴データ');
        const labels = {
          title: 'タイトル', problem: '課題', solution: '解決原理',
          effect: '期待効果', conditions: '成立条件', limitations: '限界',
        };
        const pre = document.createElement('pre');
        pre.textContent = IDEA_FIELDS.map(name =>
          labels[name] + '：' + (old.content[name] || '未記載')).join('\n\n');
        historical.replaceChildren(pre);
      } catch (_) {
        if (currentIdea?.id === detail.id)
          historical.textContent = '過去版を読み込めません。再試行してください。';
      } finally { show.disabled = false; }
    };
    row.append(show, historical);
    disclosure.append(row);
  }
  box.append(disclosure);
}
function beginIdeaFromComparison(items) {
  if (!Array.isArray(items) || items.length < 2 || items.length > 3 ||
      new Set(items.map(item => item.doc_id)).size < 2 ||
      !items.every(item => Number.isInteger(item.review_seq) &&
        Number.isInteger(item.source_epoch) && item.source_revision)) {
    el('idea-status').textContent = '承認済み出典を再取得してください。新たに2〜3件を比較する必要があります。';
    return;
  }
  if (ideaDirty && !window.confirm('入力中のIdea案を破棄して、新しい比較から作成しますか？')) return;
  lastComparedItems = items;
  currentIdea = null;
  ideaSources = items.map(item => ({...item}));
  ideaPending = null;
  ideaDirty = false;
  for (const field of IDEA_FIELDS) el('idea-' + field).value = '';
  el('idea-confirm').checked = false;
  el('idea-heading').textContent = '未保存の新しい発明仮説';
  el('idea-form').hidden = false;
  el('idea-history').replaceChildren();
  showIdeaSources();
  el('idea-status').textContent =
    '引用元' + ideaSources.length + '件を固定する準備ができました。自分の言葉で課題・仕組みを記述してください。';
  el('idea-save-status').textContent = '記入だけでは保存されません。確認チェックと保存ボタンが必要です。';
  updateIdeaSaveState();
  switchWorkspace('ideas', {scroll: false});
  el('idea-canvas').scrollIntoView({block: 'start', behavior: 'auto'});
  el('idea-title').focus({preventScroll: true});
}
el('idea-new').onclick = () => {
  if (lastComparedItems.length < 2) {
    el('idea-status').textContent =
      '上の横断検索で異なる文献の知識を2〜3件選び、比較結果からIdea Canvasへ進んでください。';
    return;
  }
  beginIdeaFromComparison(lastComparedItems);
};
for (const field of IDEA_FIELDS) {
  el('idea-' + field).addEventListener('input', () => {
    ideaPending = null;
    ideaDirty = true;
    updateIdeaSaveState();
  });
}
el('idea-confirm').onchange = () => {
  ideaPending = null;
  updateIdeaSaveState();
};
async function openIdea(id) {
  if (ideaDirty && !window.confirm('保存していない変更を破棄して、別のIdea案を開きますか？')) return;
  const request = ++ideaReadRequest;
  el('idea-status').textContent = '保存済みの発明仮説を読み込んでいます…';
  try {
    const detail = await api('ideas/' + encodeURIComponent(id));
    if (request !== ideaReadRequest) return;
    if (!detail || detail.id !== id || !Array.isArray(detail.sources)) throw new Error('不正なIdea応答');
    currentIdea = detail;
    ideaSources = detail.sources;
    ideaPending = null;
    ideaDirty = false;
    el('idea-form').hidden = false;
    for (const field of IDEA_FIELDS) el('idea-' + field).value = detail.content[field] || '';
    el('idea-confirm').checked = false;
    el('idea-heading').textContent = detail.content.title + ' — 第' +
      detail.version + '版';
    showIdeaSources();
    showIdeaHistory(detail);
    el('idea-status').textContent = detail.stale
      ? '根拠の版・レビューが変更されています。履歴は保持していますが、この案の編集保存はできません。最新知識を再比較して新しい案を作成してください。'
      : '保存済みの手動発明仮説・第' + detail.version + '版。編集は保存操作でのみ履歴に追加されます。';
    el('idea-save-status').textContent = detail.stale
      ? '根拠再確認が必要：元の案を自動的に再承認しません。'
      : '変更後、出典と本文を確認して新しい版として保存できます。';
    updateIdeaSaveState();
  } catch (_) {
    if (request === ideaReadRequest)
      el('idea-status').textContent = 'Ideaを読み込めません。接続と読取権限を確認してください。';
  }
}
async function loadIdeas() {
  const out = el('idea-recent');
  out.textContent = '保存済みの案を確認中…';
  try {
    const result = await api('ideas');
    out.replaceChildren();
    if (!Array.isArray(result.items) || !result.items.length) {
      out.textContent = '保存済みの発明仮説はまだありません。';
      const compare = document.createElement('button');
      compare.type = 'button';
      compare.className = 'secondary workspace-empty-action';
      compare.textContent = '知識を探して比べる';
      compare.onclick = () => switchWorkspace('knowledge', {focusTab: true});
      out.append(compare);
      return;
    }
    for (const item of result.items) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'secondary idea-recent-button';
      button.textContent = item.title + ' · 第' + item.version + '版' +
        (item.stale ? ' · 根拠再確認が必要' : '');
      button.onclick = () => openIdea(item.id);
      out.append(button);
    }
    if (result.truncated) {
      const note = document.createElement('p');
      note.className = 'hint';
      note.textContent = '最新20案を表示しています。古い案の閲覧機能は後続で拡張します。';
      out.append(note);
    }
  } catch (_) { out.textContent = 'Idea一覧を読み込めません。更新ボタンから再試行してください。'; }
}
el('idea-refresh').onclick = () => loadIdeas();
el('idea-form').addEventListener('submit', async event => {
  event.preventDefault();
  updateIdeaSaveState();
  if (el('idea-save').disabled || ideaSaving) return;
  const content = ideaContent();
  const existing = currentIdea;
  const sourceSelectors = ideaSourceSelectors();
  const signature = JSON.stringify({
    id: existing?.id || null, version: existing?.version || 0,
    content, sources: sourceSelectors,
  });
  if (!ideaPending || ideaPending.signature !== signature) {
    ideaPending = {signature, request_id: crypto.randomUUID().replaceAll('-', '')};
  }
  const requestId = ideaPending.request_id;
  ideaSaving = true;
  updateIdeaSaveState();
  el('idea-save-status').textContent = '根拠の版と人間の判断を再確認して保存しています…';
  try {
    const response = existing
      ? await api('ideas/' + existing.id, {
        request_id: requestId, expected_version: existing.version,
        content, confirm_manual: true,
      }, 'PUT')
      : await api('ideas', {
        request_id: requestId, sources: sourceSelectors,
        content, confirm_manual: true,
      });
    el('idea-save-status').textContent =
      '人の操作によって案を保存しました。出典・編集履歴は保持されます。';
    ideaPending = null;
    ideaDirty = false;
    await openIdea(response.id);
    await loadIdeas();
  } catch (_) {
    el('idea-save-status').textContent =
      '保存できませんでした。根拠の変更・版競合・専用権限を確認してください。同じ内容なら再試行できます。';
  } finally {
    ideaSaving = false;
    updateIdeaSaveState();
  }
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

const SVG_NS = 'http://www.w3.org/2000/svg';
const MAP_KIND_LABELS = {
  overview: '全体俯瞰', collection: '文献集合',
  document: '文献', concept: '技術概念', classification: '分類',
  party: '出願人', claim: '請求項', family: 'ファミリー',
  priority: '優先権', problem: '課題', cause: '原因',
  constraint: '制約', principle: '解決原理', mechanism: '作用機構',
  implementation: '実装', effect: '効果', observation: '観測',
  application: '応用',
};
function mapElement(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  return node;
}
function mapItemStatus(node) {
  if (node.stale) return '旧版・失効';
  if (node.basis === 'model_inference') {
    const names = {approved: '人間レビュー済みのAI推論',
      rejected: '却下されたAI推論',
      changes_requested: '差戻し中のAI推論',
      unreviewed: '未確認のAI推論'};
    return names[node.review_status] || names.unreviewed;
  }
  if (node.status === 'reviewed_graph_node') return '根拠で確認されたグラフの構成要素';
  if (node.basis === 'catalog_index') return '文献・保存先のインデックス（技術的関連性ではありません）';
  return '参照文献';
}
// Obsidian-style interactive force-directed view for a BOUNDED client slice.
// No CDN, no new graph truth or persistence. Max nodes are enforced server-side.
// The global Atlas and per-document map share exactly this renderer.
let localForceView = null;
let atlasForceView = null;
function makeForceGraph(svg, data, onSelect, initialFocus) {
  if (svg._forceDestroy) svg._forceDestroy();
  svg.replaceChildren();
  const WIDTH = 960, HEIGHT = 600;
  svg.setAttribute('viewBox', '0 0 ' + WIDTH + ' ' + HEIGHT);
  const nodes = (Array.isArray(data.nodes) ? data.nodes : []).filter(node =>
    node && typeof node.id === 'string' && typeof node.label === 'string').slice(0, 84);
  const lookup = new Map(nodes.map(node => [node.id, node]));
  const edges = (Array.isArray(data.edges) ? data.edges : []).filter(edge =>
    lookup.has(edge.source) && lookup.has(edge.target) &&
    edge.source !== edge.target).slice(0, 160);
  const degrees = new Map(nodes.map(n => [n.id, 0]));
  const neighbors = new Map(nodes.map(n => [n.id, new Set()]));
  for (const edge of edges) {
    degrees.set(edge.source, degrees.get(edge.source) + 1);
    degrees.set(edge.target, degrees.get(edge.target) + 1);
    neighbors.get(edge.source).add(edge.target);
    neighbors.get(edge.target).add(edge.source);
  }
  const distance = new Map([[data.root, 0]]);
  for (let i = 0; i < 3; i++) {
    for (const edge of edges) {
      if (distance.has(edge.source) && !distance.has(edge.target))
        distance.set(edge.target, distance.get(edge.source) + 1);
    }
  }
  const groups = new Map();
  for (const node of nodes) {
    const level = Math.min(distance.get(node.id) ?? 3, 3);
    if (!groups.has(level)) groups.set(level, []);
    groups.get(level).push(node);
  }
  const points = new Map();
  for (const [depth, group] of groups) {
    group.forEach((node, index) => {
      // Stable initial placement; force relaxation improves it visually.
      const angle = -Math.PI / 2 + 2 * Math.PI * index / Math.max(1, group.length);
      const radius = [0, 155, 280, 360][depth];
      points.set(node.id, {
        x: WIDTH / 2 + Math.cos(angle) * radius,
        y: HEIGHT / 2 + Math.sin(angle) * radius * .77,
        vx: 0, vy: 0, pinned: node.id === data.root,
      });
    });
  }
  const camera = {x: 0, y: 0, zoom: 1};
  const scene = mapElement('g', {class: 'graph-scene'});
  const edgeLayer = mapElement('g', {class: 'graph-edges'});
  const nodeLayer = mapElement('g', {class: 'graph-nodes'});
  scene.append(edgeLayer, nodeLayer);
  svg.append(scene);
  const lines = [], visualNodes = new Map();
  let focusId = lookup.has(initialFocus) ? initialFocus : data.root;
  let filterTerm = '';
  let hoverId = null, request = 0, destroyed = false, pointer = null;
  const media = window.matchMedia?.('(prefers-reduced-motion: reduce)');
  const reduced = media?.matches || document.documentElement.classList.contains('reduce-motion');
  const format = value => Number.isFinite(value) ? value.toFixed(2) : '0';
  function cameraDraw() {
    scene.setAttribute('transform',
      'translate(' + format(camera.x) + ',' + format(camera.y) + ') scale(' + format(camera.zoom) + ')');
  }
  function draw() {
    if (destroyed) return;
    cameraDraw();
    for (const entry of lines) {
      const a = points.get(entry.edge.source), b = points.get(entry.edge.target);
      entry.el.setAttribute('x1', format(a.x));
      entry.el.setAttribute('y1', format(a.y));
      entry.el.setAttribute('x2', format(b.x));
      entry.el.setAttribute('y2', format(b.y));
    }
    for (const [id, group] of visualNodes) {
      const p = points.get(id);
      group.setAttribute('transform',
        'translate(' + format(p.x) + ',' + format(p.y) + ')');
    }
  }
  function focus(id) {
    if (!lookup.has(id)) return;
    focusId = id;
    const center = hoverId || focusId;
    const adjacent = neighbors.get(center) || new Set();
    for (const [nodeId, group] of visualNodes) {
      const matched = !filterTerm || lookup.get(nodeId).label.toLocaleLowerCase().includes(filterTerm);
      group.classList.toggle('is-selected', nodeId === focusId);
      group.classList.toggle('is-neighbor', adjacent.has(nodeId));
      group.classList.toggle('is-filter-match', Boolean(filterTerm) && matched);
      group.classList.toggle('is-filtered', Boolean(filterTerm) && !matched &&
        nodeId !== focusId);
      group.classList.toggle('is-dimmed', (Boolean(filterTerm) && !matched &&
        nodeId !== focusId) ||
        (nodeId !== center && nodeId !== focusId && !adjacent.has(nodeId)));
    }
    for (const entry of lines) {
      entry.el.classList.toggle('is-active',
        entry.edge.source === center || entry.edge.target === center);
      entry.el.classList.toggle('is-dimmed',
        entry.edge.source !== center && entry.edge.target !== center);
    }
  }
  for (const edge of edges) {
    const line = mapElement('line', {
      class: 'map-line ' + (edge.basis === 'factual' ? 'map-line-factual' :
        edge.basis === 'inferred' ? 'map-line-hypothesis' :
        edge.basis === 'catalog_index' ? 'map-line-catalog' : 'map-line-source'),
    });
    const title = mapElement('title');
    title.textContent = edge.basis === 'inferred' ?
      '人が確認した技術仮説（技術的事実ではありません）' :
      edge.basis === 'catalog_index' ? '資料の保存先・所属関係' :
      edge.basis === 'provenance_only' ? '原文と知識候補の出典関係' :
      '根拠付きの関係';
    line.append(title);
    edgeLayer.append(line);
    lines.push({edge, el: line});
  }
  for (const node of nodes) {
    const id = node.id;
    const group = mapElement('g', {
      class: 'map-point map-node-' + String(node.kind || 'concept').replace(/[^a-z_-]/g, '') +
        (node.stale ? ' is-stale' : '') +
        (node.basis === 'model_inference' ? ' is-inference' : '') +
        (node.id === data.root ? ' is-root' : ''),
      'data-node-id': id, 'role': 'button', 'tabindex': '0',
      'aria-label': (MAP_KIND_LABELS[node.kind] || node.kind || '知識') +
        '：' + node.label + '。' + mapItemStatus(node) + '。Enterで詳細を表示',
    });
    const circle = mapElement('circle', {
      r: node.id === data.root ? 22 :
        node.kind === 'collection' ? 15 : Math.min(15, 8 + Math.sqrt(degrees.get(id) || 0) * 2),
    });
    const label = mapElement('text', {x: 0, y: node.id === data.root ? 37 : 27,
      'text-anchor': 'middle', class: 'map-node-label'});
    const limit = node.id === data.root ? 25 : node.kind === 'collection' ? 17 : 13;
    const summary = Array.from(String(node.label || '')).slice(0, limit).join('');
    label.textContent = summary + (Array.from(node.label || '').length > limit ? '…' : '');
    const title = mapElement('title');
    title.textContent = node.label + ' — ' + mapItemStatus(node);
    group.append(circle, label, title);
    group.addEventListener('pointerenter', () => {hoverId = id;focus(focusId);});
    group.addEventListener('pointerleave', () => {hoverId = null;focus(focusId);});
    group.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault(); onSelect(id); focus(id);
      }
    });
    nodeLayer.append(group);
    visualNodes.set(id, group);
  }
  function settle() {
    const items = [...points];
    const forces = new Map(items.map(([id]) => [id, [0, 0]]));
    // Small bounded client slice only: quadratic repulsion is capped at 84.
    for (let i = 0; i < items.length; i++) {
      const [aid, a] = items[i];
      for (let j = i + 1; j < items.length; j++) {
        const [bid, b] = items[j];
        let dx = a.x - b.x, dy = a.y - b.y;
        if (dx === 0 && dy === 0) {dx = (i + 1) * .015;dy = (j + 1) * .011;}
        const scale = 1450 / (dx * dx + dy * dy + 120);
        const fx = dx * scale, fy = dy * scale;
        forces.get(aid)[0] += fx;forces.get(aid)[1] += fy;
        forces.get(bid)[0] -= fx;forces.get(bid)[1] -= fy;
      }
    }
    for (const edge of edges) {
      const a = points.get(edge.source), b = points.get(edge.target);
      const dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.max(1, Math.hypot(dx, dy));
      const target = edge.basis === 'catalog_index' ? 105 : 145;
      const k = (d - target) * .012;
      const fx = dx / d * k, fy = dy / d * k;
      forces.get(edge.source)[0] += fx;forces.get(edge.source)[1] += fy;
      forces.get(edge.target)[0] -= fx;forces.get(edge.target)[1] -= fy;
    }
    for (const [id, p] of points) {
      if (p.pinned) {p.vx = 0;p.vy = 0;continue;}
      const [fx, fy] = forces.get(id);
      p.vx = Math.max(-10, Math.min(10, (p.vx + fx + (WIDTH/2-p.x)*.0015)*.74));
      p.vy = Math.max(-10, Math.min(10, (p.vy + fy + (HEIGHT/2-p.y)*.0015)*.74));
      p.x = Math.max(22, Math.min(WIDTH-22, p.x+p.vx));
      p.y = Math.max(20, Math.min(HEIGHT-20, p.y+p.vy));
    }
  }
  function reflow() {
    if (request) cancelAnimationFrame(request);
    if (reduced || document.hidden) {
      for (let i = 0; i < 80; i++) settle();
      draw();
      return;
    }
    let tick = 0;
    const animate = () => {
      if (destroyed) return;
      // Stops automatically: no continual GPU/CPU load on QNAP clients.
      for (let i = 0; i < 2; i++) settle();
      draw();
      if (++tick < 55) request = requestAnimationFrame(animate);
      else request = 0;
    };
    request = requestAnimationFrame(animate);
  }
  function zoom(factor, centerX=WIDTH/2, centerY=HEIGHT/2) {
    const next = Math.max(.4, Math.min(4, camera.zoom * factor));
    camera.x = centerX - (centerX-camera.x) * next/camera.zoom;
    camera.y = centerY - (centerY-camera.y) * next/camera.zoom;
    camera.zoom = next;
    cameraDraw();
  }
  function fit() {camera.x=0;camera.y=0;camera.zoom=1;cameraDraw();}
  function svgPoint(event) {
    const ctm = svg.getScreenCTM();
    if (!ctm) return null;
    const pt = svg.createSVGPoint();
    pt.x = event.clientX;pt.y = event.clientY;
    return pt.matrixTransform(ctm.inverse());
  }
  svg.onwheel = event => {
    const p = svgPoint(event);
    if (!p) return;
    event.preventDefault();
    zoom(event.deltaY < 0 ? 1.12 : 1/1.12, p.x, p.y);
  };
  svg.onpointerdown = event => {
    if (!event.isPrimary || event.button !== 0) return;
    const point = svgPoint(event);
    if (!point) return;
    const target = event.target.closest?.('[data-node-id]');
    const id = target?.getAttribute('data-node-id');
    pointer = {
      pointerId:event.pointerId, id:lookup.has(id) ? id : null,
      startX:point.x, startY:point.y, oldX:camera.x, oldY:camera.y,
      moved:false,
    };
    event.preventDefault();
    try {svg.setPointerCapture(event.pointerId);} catch (_) {}
  };
  svg.onpointermove = event => {
    if (!pointer || pointer.pointerId !== event.pointerId) return;
    const p = svgPoint(event);if (!p) return;
    const dx = p.x-pointer.startX,dy=p.y-pointer.startY;
    if (Math.hypot(dx,dy)>4) pointer.moved=true;
    if (pointer.id) {
      const item=points.get(pointer.id);
      item.pinned=true;
      item.x=Math.max(20,Math.min(WIDTH-20,item.x+dx/camera.zoom));
      item.y=Math.max(20,Math.min(HEIGHT-20,item.y+dy/camera.zoom));
      pointer.startX=p.x;pointer.startY=p.y;
      draw();
    } else {
      camera.x=pointer.oldX+dx;
      camera.y=pointer.oldY+dy;
      cameraDraw();
    }
  };
  const finish = event => {
    if (!pointer || pointer.pointerId !== event.pointerId) return;
    const chosen=pointer.id, moved=pointer.moved;
    pointer=null;
    try {svg.releasePointerCapture(event.pointerId);} catch (_) {}
    if (chosen && !moved) {focus(chosen);onSelect(chosen);}
  };
  svg.onpointerup=finish;
  svg.onpointercancel=event => {
    if (pointer?.pointerId===event.pointerId) pointer=null;
  };
  function destroy() {
    destroyed=true;
    if (request) cancelAnimationFrame(request);
    svg.onwheel=svg.onpointerdown=svg.onpointermove=svg.onpointerup=svg.onpointercancel=null;
  }
  svg._forceDestroy=destroy;
  function filter(query) {
    filterTerm = String(query || '').trim().toLocaleLowerCase();
    focus(focusId);
  }
  fit();focus(focusId);draw();reflow();
  return {focus,zoom,fit,reflow,destroy,filter};
}
function drawKnowledgeMap(data, select) {
  localForceView = makeForceGraph(el('map-svg'), data, select, selectedMapId);
  localForceView.filter(el('map-node-find').value);
}

function renderMapInspector(data, nodeId) {
  const box = el('map-inspector');
  box.replaceChildren();
  const node = data.nodes.find(n => n.id === nodeId) || data.nodes[0];
  if (!node) return;
  selectedMapId = node.id;
  const title = document.createElement('h4');
  title.textContent = node.label || '無題の知識';
  const kind = document.createElement('p');
  kind.className = 'hint';
  kind.textContent = (MAP_KIND_LABELS[node.kind] || '知識の構成要素') + ' · ' +
    mapItemStatus(node);
  box.append(title, kind);
  if (node.basis === 'model_inference') {
    const note = document.createElement('p');
    note.className = 'hint';
    note.textContent = '人が承認していても、AI推論が出典の確定した事実になったわけではありません。';
    box.append(note);
    for (const [field, label] of [
      ['conditions', '成立条件'], ['limitations', '限界'],
    ]) {
      if (Array.isArray(node[field]) && node[field].length) {
        const line = document.createElement('p');
        line.textContent = label + ': ' + node[field].join('、');
        box.append(line);
      }
    }
  }
  if (node.evidence) {
    const evidence = node.evidence;
    const quote = document.createElement('blockquote');
    quote.textContent = evidence.quote || '引用はありません';
    box.append(quote);
    const sourceButton = document.createElement('button');
    sourceButton.type = 'button';
    sourceButton.className = 'secondary';
    sourceButton.textContent = node.stale ? '旧版の根拠・再抽出が必要' : '根拠の原文を開く';
    sourceButton.disabled = Boolean(node.stale);
    sourceButton.onclick = async () => {
      if (!Number.isInteger(evidence.doc_id)) return;
      try {
        if (currentDoc !== evidence.doc_id) await openDocument(evidence.doc_id);
        focusKnowledgeEvidence(evidence);
      } catch (error) { el('map-status').textContent = '根拠を開けませんでした: ' + error.message; }
    };
    box.append(sourceButton);
  }
  if (Number.isInteger(node.document_id)) {
    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'secondary';
    open.textContent = '文献を表示';
    open.onclick = async () => {
      try { await openDocument(node.document_id); }
      catch (error) { el('map-status').textContent = '文献を開けませんでした: ' + error.message; }
    };
    box.append(open);
    if (node.kind === 'document') {
      const ai = document.createElement('button');
      ai.type = 'button';
      ai.className = 'secondary atlas-ai-action';
      ai.textContent = 'ローカルAIで知識を抽出';
      ai.onclick = () => void startLocalKnowledgeAI(node.document_id, ai, 'map-status');
      box.append(ai);
    }
  }
  const adjacent = data.edges.filter(e => e.source === node.id || e.target === node.id);
  if (adjacent.length) {
    const heading = document.createElement('h5');
    heading.textContent = '接続の理由と方向';
    box.append(heading);
    for (const edge of adjacent.slice(0, 12)) {
      const row = document.createElement('p');
      row.className = 'hint';
      row.textContent = edge.basis === 'provenance_only'
        ? '文献 → AI知識候補（出典リンクのみ・技術的関係の認定ではありません）'
        : edge.basis === 'inferred'
          ? ('人が確認した技術仮説（事実ではありません）: ' + edge.relation +
             '（' + edge.source + ' → ' + edge.target + '）')
          : ('承認済みの事実関係: ' + edge.relation +
             '（' + edge.source + ' → ' + edge.target + '）');
      box.append(row);
      if (edge.evidence?.quote) {
        const quote = document.createElement('blockquote');
        quote.textContent = edge.evidence.quote;
        box.append(quote);
        const evidenceOpen = document.createElement('button');
        evidenceOpen.type = 'button';
        evidenceOpen.className = 'secondary';
        evidenceOpen.textContent = 'この関係の出典へ移動';
        evidenceOpen.onclick = async () => {
          try {
            if (currentDoc !== edge.evidence.doc_id) await openDocument(edge.evidence.doc_id);
            focusKnowledgeEvidence(edge.evidence);
          } catch (error) {
            el('map-status').textContent = '関係の出典を開けませんでした: ' + error.message;
          }
        };
        box.append(evidenceOpen);
      }
    }
  }
}
function renderKnowledgeMap(data) {
  currentKnowledgeMap = data;
  const list = el('map-list');
  list.replaceChildren();
  if (!data.nodes || data.nodes.length <= 1) {
    list.textContent = 'この文献に表示可能な確認済み知識はまだありません。未確認候補の参考表示を選ぶか、知識候補を抽出・レビューしてください。';
  }
  if (!data.nodes.some(n => n.id === selectedMapId)) selectedMapId = data.root;
  const select = id => {
    selectedMapId = id;
    renderMapInspector(data, id);
    localForceView?.focus(id);
    for (const button of list.querySelectorAll('button')) {
      button.setAttribute('aria-pressed', String(button.dataset.nodeId === id));
    }
  };
  for (const node of data.nodes) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'map-list-item secondary';
    button.dataset.nodeId = node.id;
    button.textContent = (MAP_KIND_LABELS[node.kind] || '知識') + ' · ' +
      node.label + ' — ' + mapItemStatus(node);
    button.onclick = () => select(node.id);
    list.append(button);
  }
  drawKnowledgeMap(data, select);
  select(selectedMapId);
  el('map-status').textContent = '出典と知識 ' + data.nodes.length + '件、接続 ' +
    data.edges.length + '件、' + data.hops + '段階（' +
    (data.include_unreviewed ? '未確認も参考表示' : '確認済みだけ') +
    (data.include_links ? '・確認済み仮説も参考表示' : '') + '）。' +
    (data.truncated ? '表示上限に達したため、この文献の近傍の一部だけを表示しています。' :
     'ドラッグ・ズーム・ノード選択に対応しています。AI推論と出典関係は別です。');
}
async function loadKnowledgeMap(id) {
  if (currentDoc !== id) return;
  const request = ++mapRequest;
  el('map-status').textContent = '知識の関係を読み込んでいます…';
  const hops = el('map-hops').value === '2' ? '2' : '1';
  const visible = el('map-unreviewed').checked ? 'true' : 'false';
  const links = el('map-links').checked ? 'true' : 'false';
  try {
    const data = await api('documents/' + id + '/knowledge-map?hops=' + hops +
                           '&include_unreviewed=' + visible + '&include_links=' + links);
    if (request !== mapRequest || currentDoc !== id) return;
    if (!Array.isArray(data.nodes) || !Array.isArray(data.edges)) throw new Error('知識マップ形式が不正です');
    renderKnowledgeMap(data);
  } catch (error) {
    if (request !== mapRequest || currentDoc !== id) return;
    el('map-status').textContent = '知識マップを読み込めません。サーバー更新・権限・接続を確認してください。';
    el('map-list').replaceChildren();
    el('map-inspector').replaceChildren();
    if (localForceView) {localForceView.destroy();localForceView=null;}
    el('map-svg').replaceChildren();
    currentKnowledgeMap = null;
  }
}
el('map-refresh').onclick = () => { if (currentDoc) void loadKnowledgeMap(currentDoc); };
el('map-hops').onchange = () => { if (currentDoc) void loadKnowledgeMap(currentDoc); };
el('map-unreviewed').onchange = () => { if (currentDoc) void loadKnowledgeMap(currentDoc); };
el('map-links').onchange = () => { if (currentDoc) void loadKnowledgeMap(currentDoc); };
el('map-zoom-in').onclick = () => localForceView?.zoom(1.2);
el('map-zoom-out').onclick = () => localForceView?.zoom(1/1.2);
el('map-fit').onclick = () => localForceView?.fit();
el('map-reflow').onclick = () => localForceView?.reflow();
el('map-node-find').oninput = () => localForceView?.filter(el('map-node-find').value);
let atlasSelectedId = 'atlas:root';
let atlasLoading = false;
let atlasLoaded = false;
let atlasRequest = 0;
async function startLocalKnowledgeAI(docId, button, statusId) {
  if (!Number.isInteger(docId) || docId < 1) return;
  if (!window.confirm('この文献の知識をControlDeckのローカルAIで抽出しますか？ 結果は未確認のAI推論として保存され、人間のレビューが必要です。')) return;
  button.disabled = true;
  el(statusId).textContent = 'ローカルAIの知識抽出を明示的に開始しています…';
  try {
    // Reuse the existing Host-owned local-only model job with provenance.
    // Never send unpublished patent source through a new remote provider.
    await api('jobs', {doc_id: docId, kind: 'knowledge'});
    el(statusId).textContent = 'ローカルAIの抽出ジョブを登録しました。人間によるレビュー前には技術的事実になりません。';
    el('workspace-activity').open = true;
    await loadJobs();
  } catch (_) {
    el(statusId).textContent =
      'ローカルAIの抽出を開始できませんでした。ControlDeckのローカルモデル・権限・接続を確認してください。';
  } finally {button.disabled = false;}
}
function renderAtlasInspector(data, id) {
  const inspector = el('atlas-inspector');
  inspector.replaceChildren();
  const item = data.nodes.find(node => node.id === id) || data.nodes[0];
  if (!item) return;
  atlasSelectedId = item.id;
  const heading = document.createElement('h4');
  heading.textContent = item.label;
  const kind = document.createElement('p');
  kind.className = 'hint';
  kind.textContent = item.kind === 'overview' ? '資料の全体俯瞰（保存先と文献サンプル）' :
    item.kind === 'collection' ? '文献集合・保存先' : '文献（最新サンプル）';
  inspector.append(heading, kind);
  if (item.kind === 'collection') {
    const count = document.createElement('p');
    count.textContent = data.scope === 'catalog_page'
      ? 'このページには新しい文献を最大50件表示しています。'
      : ((item.count_is_lower_bound ? '少なくとも ' : '') +
         item.document_count.toLocaleString('ja-JP') + '件の文献が含まれます。');
    inspector.append(count);
    const note = document.createElement('p');
    note.className = 'hint';
    note.textContent = data.scope === 'catalog_page'
      ? '全件は一度に読み込みません。下の「続きの文献」でページ単位に探索できます。'
      : '全体図には新しい最大5件だけを表示しています。分野内を開くとさらに詳しく探索できます。';
    inspector.append(note);
    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'secondary';
    open.textContent = 'この保存先の文献を表示';
    open.onclick = async () => {
      try {
        const picker = el('library-collection');
        if (![...picker.options].some(opt => opt.value === String(item.collection_id)))
          await loadLibrary();
        picker.value = String(item.collection_id);
        switchWorkspace('research', {focusTab: true});
        await showLibrary();
        el('library-items').scrollIntoView({block: 'nearest', behavior: 'auto'});
      } catch (_) {
        el('atlas-status').textContent = '保存先を開けません。接続と読取権限を確認してください。';
      }
    };
    inspector.append(open);
    if (data.scope !== 'catalog_page') {
      const explore = document.createElement('button');
      explore.type = 'button';
      explore.className = 'atlas-drilldown';
      explore.textContent = 'この分野の文献マップを開く';
      explore.onclick = () => void loadAtlas(0, item.collection_id);
      inspector.append(explore);
    }
  }
  if (Number.isInteger(item.document_id)) {
    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'secondary';
    open.textContent = '原文と知識マップを開く';
    open.onclick = async () => {
      try {
        await openDocument(item.document_id);
        el('detail').scrollIntoView({block: 'start', behavior: 'auto'});
      } catch (_) {
        el('atlas-status').textContent = '文献を開けません。接続と読取権限を確認してください。';
      }
    };
    const ai = document.createElement('button');
    ai.type = 'button';
    ai.className = 'secondary atlas-ai-action';
    ai.textContent = 'ローカルAIで知識エッセンスを抽出';
    ai.onclick = () => void startLocalKnowledgeAI(item.document_id, ai, 'atlas-status');
    inspector.append(open, ai);
  }
  const advisory = document.createElement('p');
  advisory.className = 'hint';
  advisory.textContent = 'この線は資料の所属だけを示します。AIの類似性判定や特許性は意味しません。';
  inspector.append(advisory);
}
async function loadAtlas(cursor = 0, collectionId = 0) {
  if (atlasLoading) return;
  atlasLoading = true;
  const request = ++atlasRequest;
  const refresh = el('atlas-reload'), next = el('atlas-next');
  refresh.disabled = true;next.disabled = true;
  el('atlas-status').textContent = 'コレクションと文献のインデックスを取得しています…';
  try {
    const data = await api('knowledge/atlas?cursor=' + cursor +
      '&limit=' + (collectionId ? 50 : 10) + '&collection_id=' + collectionId);
    if (request !== atlasRequest) return;
    if (!Array.isArray(data.nodes) || !Array.isArray(data.edges) ||
        data.nodes.length > 61 || data.edges.length > 60 ||
        data.read_only !== true ||
        data.scope !== (collectionId ? 'catalog_page' : 'catalog_sample')) {
      throw new Error('Atlas data contract mismatch');
    }
    atlasLoaded = true;
    atlasSelectedId = data.root;
    atlasForceView = makeForceGraph(el('atlas-svg'), data, id => {
      atlasSelectedId=id;atlasForceView?.focus(id);renderAtlasInspector(data,id);
    }, data.root);
    atlasForceView.filter(el('atlas-node-find').value);
    renderAtlasInspector(data, data.root);
    next.hidden = !Number.isInteger(data.next_cursor);
    next.dataset.cursor = String(data.next_cursor || '');
    next.dataset.collectionId = String(collectionId);
    next.textContent = collectionId ? '続きの文献を表示' : '次の分野を表示';
    refresh.textContent = collectionId ? '全体アトラスへ戻る' : '全体を読み直す';
    el('atlas-status').textContent = (collectionId ? '保存先の文献を探索中：' :
      '全体の見取り図：') +
      '分野 ' + data.nodes.filter(n => n.kind === 'collection').length +
      '件、文献 ' + data.nodes.filter(n => n.kind === 'document').length +
      '件を表示。' +
      (data.next_cursor ? ' ボタンで次ページを調べられます。' :
        ' この範囲の続きはありません。') +
      (data.truncated ? ' 全資料の一部のみ表示しています。' : '');
  } catch (_) {
    if (request !== atlasRequest) return;
    atlasLoaded = false;
    el('atlas-status').textContent = 'アトラスを読み込めません。ResearchDataHub更新・読取権限・接続を確認して再読み込みしてください。';
    el('atlas-svg').replaceChildren();
    el('atlas-inspector').textContent = '現在表示できる文献集合はありません。';
    next.hidden = true;
  } finally {
    atlasLoading=false;refresh.disabled=false;next.disabled=false;
  }
}
el('atlas-reload').onclick = () => void loadAtlas(0);
el('atlas-next').onclick = () => {
  const cursor = Number(el('atlas-next').dataset.cursor);
  const collectionId = Number(el('atlas-next').dataset.collectionId || 0);
  if (Number.isInteger(cursor) && cursor > 0 &&
      Number.isInteger(collectionId) && collectionId >= 0)
    void loadAtlas(cursor, collectionId);
};
el('atlas-zoom-in').onclick = () => atlasForceView?.zoom(1.2);
el('atlas-zoom-out').onclick = () => atlasForceView?.zoom(1/1.2);
el('atlas-fit').onclick = () => atlasForceView?.fit();
el('atlas-reflow').onclick = () => atlasForceView?.reflow();
el('atlas-node-find').oninput = () => atlasForceView?.filter(el('atlas-node-find').value);


const LINK_RELATION_LABELS = {
  problem: '課題との関係', solution: '解決手段との関係',
  effect: '効果との関係', substitution: '置換可能性',
};
function chosenLinkSource() {
  const i = Number(el('link-source').value);
  return el('link-source').value !== '' && Number.isInteger(i)
    ? (linkSources[i] || null) : null;
}
function refreshLinkSourceOptions() {
  const select = el('link-source');
  select.replaceChildren();
  el('link-confirm').checked = false;
  const blank = document.createElement('option');
  blank.value = '';
  blank.textContent = linkSources.length
    ? '根拠となる知識を選択してください' : '現行版で承認済みの知識がありません';
  select.append(blank);
  linkSources.forEach((source, i) => {
    const option = document.createElement('option');
    option.value = String(i);
    option.textContent = source.label.slice(0, 90);
    select.append(option);
  });
  // Re-reviewing the source can change its version/approval state; never
  // silently carry a previously checked link target/source confirmation.
  select.value = '';
  updateLinkPreview();
}
function updateLinkPreview() {
  const source = chosenLinkSource();
  el('link-evidence').textContent = source
    ? '原文の引用: 「' + source.evidence.quote + '」'
    : 'K2で確認済みの知識と根拠を選択してください。';
  const ready = Boolean(
    linkAllowed && currentDoc && source && linkTarget &&
    linkTarget.id !== currentDoc && el('link-relation').value &&
    el('link-confirm').checked,
  );
  el('link-register').disabled = !ready;
  if (!linkAllowed) el('link-feedback').textContent =
    'リンク専用の書込権限が未設定です。ResearchDataHub管理画面で権限を設定してください。';
}
el('link-source').onchange = () => {
  el('link-confirm').checked = false;
  updateLinkPreview();
};
el('link-relation').onchange = () => {
  el('link-confirm').checked = false;
  updateLinkPreview();
};
el('link-confirm').onchange = updateLinkPreview;
el('link-target-form').addEventListener('submit', async event => {
  event.preventDefault();
  const text = el('link-target-query').value.trim();
  if (!text || !currentDoc) return;
  const hostDocument = currentDoc;
  linkTarget = null;
  el('link-confirm').checked = false;
  el('link-target-choice').textContent = '検索結果から関係先を選択してください。';
  updateLinkPreview();
  el('link-target-search').disabled = true;
  const targetResults = el('link-target-results');
  targetResults.textContent = '関係先の文献を検索しています…';
  try {
    const results = await api('search', {q: text});
    if (currentDoc !== hostDocument) return;
    targetResults.replaceChildren();
    let matched = 0;
    for (const row of results.results || []) {
      if (!Number.isInteger(row.doc_id) || row.doc_id === hostDocument) continue;
      matched++;
      const button = document.createElement('button');
      button.className = 'secondary map-list-item';
      button.type = 'button';
      button.textContent = '関係先に選択: ' + (row.title || row.ext_id || row.doc_id);
      button.onclick = async () => {
        button.disabled = true;
        try {
          // Only a minimal identity+revision response, never the target body.
          const target = await api('documents/' + row.doc_id + '/link-target');
          if (currentDoc !== hostDocument) return;
          linkTarget = target;
          el('link-target-choice').textContent =
            '関係先: ' + target.title + '（文献 ' + target.id + '）';
          el('link-confirm').checked = false;
          updateLinkPreview();
        } catch (error) {
          el('link-target-choice').textContent = '文献を選択できませんでした: ' + error.message;
        } finally { button.disabled = false; }
      };
      targetResults.append(button);
    }
    if (!matched) targetResults.textContent = '別の文献が見つかりませんでした。検索語を変更してください。';
  } catch (error) {
    if (currentDoc === hostDocument)
      targetResults.textContent = '関係先を検索できませんでした: ' + error.message;
  } finally { el('link-target-search').disabled = false; }
});
el('link-register').onclick = async () => {
  const source = chosenLinkSource(), target = linkTarget;
  const docId = currentDoc, relation = el('link-relation').value;
  if (!linkAllowed || !source || !target || !el('link-confirm').checked ||
      !LINK_RELATION_LABELS[relation] || target.id === docId) return;
  el('link-register').disabled = true;
  try {
    const saved = await api('documents/' + docId + '/knowledge-proposals/' +
      encodeURIComponent(source.proposalId) + '/links', {
        item_index: source.itemIndex,
        source_revision: source.sourceRevision,
        target_doc_id: target.id, target_revision: target.revision,
        relation, confirm_evidence: true,
      });
    if (currentDoc !== docId) return;
    el('link-confirm').checked = false;
    el('link-feedback').textContent = saved.review_status === 'unreviewed'
      ? '仮説リンクを未確認で登録しました。別の明示的なレビューが必要です。'
      : '以前登録した仮説リンクを確認しました。審査状態は変更していません。';
    await loadKnowledgeLinks(docId);
    await loadKnowledgeMap(docId);
  } catch (error) {
    if (currentDoc === docId) el('link-feedback').textContent =
      'リンクを登録できませんでした。原文・承認・関係先の版を再確認してください: ' + error.message;
  } finally { if (currentDoc === docId) updateLinkPreview(); }
};
async function loadKnowledgeLinks(docId) {
  const container = el('link-list');
  if (currentDoc !== docId) return;
  container.textContent = '保存済みの技術仮説リンクを確認しています…';
  try {
    const result = await api('documents/' + docId + '/knowledge-links');
    if (currentDoc !== docId) return;
    container.replaceChildren();
    if (!Array.isArray(result.items) || result.items.length === 0) {
      const empty = document.createElement('p');
      empty.className = 'hint';
      empty.textContent = '関係リンクはまだありません。確認済みの知識から、別文献への仮説を登録できます。';
      container.append(empty);
      return;
    }
    for (const item of result.items) {
      const card = document.createElement('details');
      card.className = 'knowledge-link-card';
      const summary = document.createElement('summary');
      const names = {approved: '人間が確認済みの仮説', rejected: '却下', unreviewed: '未確認'};
      summary.textContent = (LINK_RELATION_LABELS[item.relation] || '仮説') + ' — ' +
        (item.target_title || '文献 ' + item.target_doc_id) + ' · ' +
        (item.stale ? '原文更新・失効' :
          (names[item.review_status] || '未確認')) + '（事実ではありません）';
      const quote = document.createElement('blockquote');
      quote.textContent = item.quote;
      card.append(summary, quote);
      const showTarget = document.createElement('button');
      showTarget.className = 'secondary';
      showTarget.type = 'button';
      showTarget.textContent = '関係先の文献を表示';
      showTarget.onclick = async () => {
        try { await openDocument(item.target_doc_id); }
        catch (error) { el('link-feedback').textContent = '文献を開けません: ' + error.message; }
      };
      card.append(showTarget);
      if (item.review_status === 'unreviewed' && !item.stale && linkAllowed) {
        const choice = document.createElement('select');
        choice.setAttribute('aria-label', '仮説リンクの審査');
        for (const [value, title] of [
          ['', '確認する判断を選んでください'], ['approved', '仮説として承認'],
          ['rejected', 'この関係を却下'],
        ]) {
          const option = document.createElement('option');
          option.value = value;
          option.textContent = title;
          choice.append(option);
        }
        const label = document.createElement('label');
        label.className = 'map-toggle';
        const confirm = document.createElement('input');
        confirm.type = 'checkbox';
        label.append(confirm, document.createTextNode(
          '引用と関係先を再確認し、事実扱いせず記録する'));
        const save = document.createElement('button');
        save.className = 'secondary';
        save.type = 'button';
        save.disabled = true;
        save.textContent = 'リンクの審査結果を記録';
        const update = () => { save.disabled = !(choice.value && confirm.checked); };
        choice.onchange = update;
        confirm.onchange = update;
        save.onclick = async () => {
          if (!choice.value || !confirm.checked || currentDoc !== docId) return;
          save.disabled = true;
          try {
            await api('knowledge-links/' + encodeURIComponent(item.id) + '/review', {
              decision: choice.value, expected_graph_revision: item.graph_revision,
              confirm_evidence: true,
            });
            if (currentDoc !== docId) return;
            el('link-feedback').textContent =
              'リンクの判断を記録しました。承認しても技術的事実にはなりません。';
            await loadKnowledgeLinks(docId);
            await loadKnowledgeMap(docId);
          } catch (error) {
            if (currentDoc === docId) {
              el('link-feedback').textContent =
                '審査結果を保存できません。最新版を再取得してください: ' + error.message;
              await loadKnowledgeLinks(docId);
            }
          }
        };
        card.append(choice, label, save);
      } else if (!linkAllowed || item.stale) {
        const note = document.createElement('p');
        note.className = 'hint';
        note.textContent = item.stale
          ? '元文献が変更されたため、このリンクは再確認が必要です。'
          : 'リンクの審査には専用の権限が必要です。';
        card.append(note);
      }
      container.append(card);
    }
  } catch (error) {
    if (currentDoc !== docId) return;
    container.replaceChildren();
    const message = document.createElement('p');
    message.className = 'hint';
    message.textContent = 'リンクを読み込めませんでした。接続とサーバー版を確認してください。';
    const retry = document.createElement('button');
    retry.className = 'secondary';
    retry.type = 'button';
    retry.textContent = 'リンクを再読み込み';
    retry.onclick = () => loadKnowledgeLinks(docId);
    container.append(message, retry);
  }
}

async function loadKnowledge(id) {
  const holder = el('knowledge');
  if (currentDoc !== id) return;
  linkSources = [];
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
      refreshLinkSourceOptions();
      await loadKnowledgeLinks(id);
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
        if (!snapshot.stale && review?.status === 'approved' && review.stale !== true) {
          linkSources.push({
            proposalId: snapshot.id, itemIndex, sourceRevision: snapshot.source_revision,
            evidence: item.evidence, label: item.statement,
          });
        }
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
              await loadKnowledgeMap(id);
            } catch (error) {
              if (String(error.message).includes('409')) {
                el('message').textContent = '原文またはレビュー版が更新されています。最新の候補を確認してください。';
                await loadKnowledge(id);
              } else {
                el('message').textContent = 'レビューを記録できませんでした。' + error.message;
                submit.disabled = false;
              }
            }
          };
          reviewPanel.append(choice, submit);
        }
        card.append(title, status, statement, details, reviewPanel);
        if (!snapshot.stale && review?.status === 'approved' && review.stale !== true) {
          // Explicit discovery handoff only: prefill a visible input without
          // sending any source text, triggering a search, or creating an Idea.
          const compareAction = document.createElement('button');
          compareAction.type = 'button';
          compareAction.className = 'secondary knowledge-search-cross';
          compareAction.textContent = 'この条件から関連知識を探す';
          compareAction.onclick = () => {
            const condition = item.conditions.find(value => value.trim()) || item.statement;
            el('cross-query').value = Array.from(condition).slice(0, 120).join('');
            el('cross-kind').value = '';
            switchWorkspace('knowledge', {scroll: true});
            el('cross-search-status').textContent =
              '確認済みの知識から検索語を入力しました。必要なら修正し「知識を検索」を押してください。';
            el('cross-query').focus({preventScroll: true});
          };
          card.append(compareAction);
        }
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
    refreshLinkSourceOptions();
    await loadKnowledgeLinks(id);
  } catch (_) {
    if (currentDoc !== id) return;
    linkSources = [];
    refreshLinkSourceOptions();
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
    activeAnalysisJobs = data.items.filter(item =>
      ['queued', 'running'].includes(item.status)).length;
    updateActivitySummary();
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
        if (job.kind === 'knowledge') {
          await loadKnowledge(currentDoc);
          await loadKnowledgeMap(currentDoc);
        } else await loadAnalyses(currentDoc);
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
  switchWorkspace('research', {scroll: false});
  sourceReturnWorkspace = null;
  el('workspace-source-return').hidden = true;
  const doc = await api('documents/' + id);
  currentDoc = id; currentDocBody = doc.body || ''; imageRequest++;
  linkTarget = null;
  linkSources = [];
  el('link-source').replaceChildren();
  el('link-evidence').textContent = '確認済みの知識を読み込んでいます…';
  el('link-target-choice').textContent = '関係先は未選択です。';
  el('link-target-results').replaceChildren();
  el('link-confirm').checked = false;
  if (imageURL) { URL.revokeObjectURL(imageURL); imageURL = null; }
  el('title').textContent = doc.title || '文献'; el('body').textContent = doc.body || ''; el('detail').hidden = false;
  el('pdf-evidence').hidden = true; el('pdf-evidence').replaceChildren();
  await loadAnalyses(id);
  await loadKnowledge(id);
  await loadKnowledgeMap(id);
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
  activePDFJobs = data.items.filter(item => ['queued', 'running'].includes(item.status)).length;
  updateActivitySummary();
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
    button.onclick = async () => { try { await openDocument(row.id); el('detail').scrollIntoView({behavior:'auto'}); } catch(error) { el('message').textContent = error.message; } };
    el('library-items').append(button);
  }
  if (!data.items.length) el('library-items').textContent = 'この保存先には資料がありません。';
  el('library-note').textContent = '新しい資料を最大20件表示します。それ以前の資料はキーワードで検索できます。';
}
el('library-collection').onchange = () => showLibrary().catch(error => { el('message').textContent = error.message; });
