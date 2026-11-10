/* QnapLibrary management web — dependency-free, CSP-safe (no inline handlers, no innerHTML with data). */
"use strict";
(() => {
const S = { me: null, csrf: null, view: "home", health: null, collections: [], meta: null };
const $app = document.getElementById("app");

// ---------- helpers ----------
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "value") el.value = v;
    else if (k === "checked") el.checked = !!v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
function toast(msg) { const t = document.getElementById("toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(t._t); t._t = setTimeout(() => t.classList.remove("show"), 2800); }
async function api(method, path, body, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  if (S.csrf && method !== "GET") headers["X-CSRF-Token"] = S.csrf;
  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: "same-origin" });
  if (opts.raw) return res;
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  if (!res.ok) {
    if (res.status === 401 && !opts.quiet) { S.me = null; render(); }
    throw new Error((data && data.error) || ("HTTP " + res.status));
  }
  return data;
}
function guard(fn) { return async (...a) => { try { await fn(...a); } catch (e) { toast(e.message); } }; }
function fmtDate(ts) { if (!ts) return "-"; const d = new Date(ts * 1000); return d.toLocaleString("ja-JP", { dateStyle: "short", timeStyle: "short" }); }
function field(label, input) { return h("label", { class: "f" }, h("span", {}, label), input); }
function sel(options, value, attrs = {}) { return h("select", attrs, options.map(o => { const [v, l] = Array.isArray(o) ? o : [o, o]; return h("option", { value: v, selected: String(v) === String(value) ? true : null }, l); })); }
function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
function b64u(buf) { let s = ""; new Uint8Array(buf).forEach(b => s += String.fromCharCode(b)); return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""); }
function unb64u(s) { s = s.replace(/-/g, "+").replace(/_/g, "/"); while (s.length % 4) s += "="; return Uint8Array.from(atob(s), c => c.charCodeAt(0)); }
function download(name, text, type = "application/json") { const a = h("a", { href: URL.createObjectURL(new Blob([text], { type })), download: name }); document.body.append(a); a.click(); a.remove(); }

// minimal safe markdown (escapes first; supports headings, bold, code, lists, tables)
function md(text) {
  const root = h("div", { class: "md" });
  const lines = String(text || "").split("\n");
  let i = 0;
  const inline = (s) => { const frag = document.createDocumentFragment(); const re = /(\*\*[^*]+\*\*|`[^`]+`|\[(\d+)\])/g; let last = 0, m;
    while ((m = re.exec(s))) { if (m.index > last) frag.append(s.slice(last, m.index)); const t = m[0];
      if (t.startsWith("**")) frag.append(h("strong", {}, t.slice(2, -2))); else if (t.startsWith("`")) frag.append(h("code", {}, t.slice(1, -1))); else frag.append(h("sup", { class: "tag" }, t));
      last = m.index + t.length; } if (last < s.length) frag.append(s.slice(last)); return frag; };
  while (i < lines.length) {
    const l = lines[i];
    if (l.startsWith("```")) { const buf = []; i++; while (i < lines.length && !lines[i].startsWith("```")) buf.push(lines[i++]); i++; root.append(h("pre", {}, buf.join("\n"))); continue; }
    if (/^\s*\|.*\|\s*$/.test(l)) { const rows = []; while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(lines[i++]);
      const cells = r => r.trim().slice(1, -1).split("|").map(c => c.trim()); const t = h("table");
      rows.forEach((r, idx) => { if (/^\s*\|[\s:\-|]+\|\s*$/.test(r)) return; t.append(h("tr", {}, cells(r).map(c => h(idx === 0 ? "th" : "td", {}, inline(c))))); }); root.append(t); continue; }
    const hm = l.match(/^(#{1,4})\s+(.*)/); if (hm) { root.append(h("h" + Math.min(3, hm[1].length), {}, inline(hm[2]))); i++; continue; }
    if (/^\s*([-*]|\d+\.)\s+/.test(l)) { const ul = h(/^\s*\d+\./.test(l) ? "ol" : "ul"); while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) ul.append(h("li", {}, inline(lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, "")))); root.append(ul); continue; }
    if (!l.trim()) { i++; continue; }
    const buf = []; while (i < lines.length && lines[i].trim() && !/^(#|```|\s*\||\s*([-*]|\d+\.)\s)/.test(lines[i])) buf.push(lines[i++]);
    if (!buf.length) { buf.push(l); i++; }
    root.append(h("p", {}, inline(buf.join("\n"))));
  }
  return root;
}

// ---------- boot / auth ----------
async function boot() {
  S.health = await api("GET", "/api/health");
  const me = await api("GET", "/api/auth/me", undefined, { quiet: true });
  S.me = me.authenticated ? me : null; S.csrf = me.csrf; S.meInfo = me;
  render();
}
function render() {
  clear($app); $app.className = "";
  if (!S.me) return $app.append(loginView());
  const views = [["home", "ホーム"], ["search", "検索"], ["patents", "特許"], ["data", "データ"], ["analytics", "分析"], ["chat", "AIチャット"], ["collect", "収集"], ["settings", "設定"]];
  const main = h("main", {});
  const nav = h("nav", { class: "side" }, h("div", { class: "brand" }, h("img", { src: "icon.svg", alt: "" }), "QnapLibrary"),
    views.map(([id, label]) => h("button", { class: S.view === id ? "active" : "", onclick: () => { S.view = id; render(); } }, label)),
    h("div", { class: "ver" }, "v" + S.health.version));
  $app.append(h("div", { class: "layout" }, nav, main));
  const fn = { home: homeView, search: searchView, patents: patentsView, data: dataView, analytics: analyticsView, chat: chatView, collect: collectView, settings: settingsView }[S.view];
  Promise.resolve(fn(main)).catch(e => main.append(h("div", { class: "card" }, "エラー: " + e.message)));
}
function loginView() {
  const setup = S.health.setup_required;
  const pw = h("input", { type: "password", class: "wide", autocomplete: setup ? "new-password" : "current-password", placeholder: setup ? "10文字以上" : "" });
  const go = guard(async () => {
    const r = await api("POST", setup ? "/api/auth/setup" : "/api/auth/login", { password: pw.value });
    S.csrf = r.csrf; await boot();
  });
  pw.addEventListener("keydown", e => { if (e.key === "Enter") go(); });
  const box = h("div", { class: "login" }, h("div", { class: "card" },
    h("h1", {}, setup ? "QnapLibrary 初期設定" : "QnapLibrary ログイン"),
    setup ? h("p", { class: "muted small" }, "管理者パスワードを設定します（LANからのみ）。後で設定からパスキー（Face ID 等）を登録できます。") : null,
    field(setup ? "新しい管理者パスワード" : "パスワード", pw),
    h("div", { class: "row" }, h("button", { class: "btn primary", onclick: go }, setup ? "設定して開始" : "ログイン"),
      !setup && window.PublicKeyCredential && window.isSecureContext && location.protocol === "https:" ? h("button", { class: "btn", onclick: guard(passkeyLogin) }, "顔認証 / パスキーでログイン") : null),
    location.protocol !== "https:" ? h("p", { class: "muted small" }, "※ 顔認証（パスキー）は https://<NAS名>.<tailnet>.ts.net:8443/ などの HTTPS で開いたときに使えます。",
      S.health.https_url ? [" ", h("a", { href: S.health.https_url }, "HTTPS で開く")] : null) : null));
  setTimeout(() => pw.focus(), 50);
  return box;
}
async function passkeyLogin() {
  const opt = await api("POST", "/api/auth/passkey/login/options", {});
  const pk = opt.publicKey;
  pk.challenge = unb64u(pk.challenge);
  pk.allowCredentials = pk.allowCredentials.map(c => ({ ...c, id: unb64u(c.id) }));
  const cred = await navigator.credentials.get({ publicKey: pk });
  const r = await api("POST", "/api/auth/passkey/login/verify", { bind: opt.bind, id: b64u(cred.rawId),
    clientDataJSON: b64u(cred.response.clientDataJSON), authenticatorData: b64u(cred.response.authenticatorData), signature: b64u(cred.response.signature) });
  S.csrf = r.csrf; await boot();
}
async function loadCollections() { const r = await api("GET", "/api/v1/collections"); S.collections = r.collections; S.kinds = r.kinds; return r.collections; }
function collectionPicker(selected = []) {
  const box = h("div", { class: "row small" });
  const all = S.collections;
  if (!all.length) box.append(h("span", { class: "muted" }, "コレクションがありません（データ画面で作成）"));
  all.forEach(c => box.append(h("label", {}, h("input", { type: "checkbox", value: c.name, checked: selected.includes(c.name) }), " ", c.name, " ", h("span", { class: "tag" }, c.kind))));
  box.values = () => [...box.querySelectorAll("input:checked")].map(i => i.value);
  return box;
}

// ---------- home ----------
async function homeView(main) {
  main.append(h("h1", {}, "ホーム"));
  const activity = h("section", { class: "card home-activity", "aria-live": "polite" },
    h("h2", {}, "処理状況"), h("p", { class: "small muted" }, "状態を確認しています…"));
  main.append(activity);

  const [st, pats] = await Promise.all([
    api("GET", "/api/v1/stats"), api("GET", "/api/v1/patents")
  ]);
  if (!main.isConnected || S.view !== "home") return;
  const s = st.store;
  const cards = [["文書", s.documents], ["コレクション", s.collections], ["特許案件", s.patents]];
  const kpis = h("div", { class: "home-kpis" });
  cards.forEach(([label, val]) => kpis.append(h("div", { class: "card home-kpi" },
    h("div", { class: "muted small" }, label),
    h("div", { class: "home-stat-value" }, Number(val || 0).toLocaleString("ja-JP")))));
  main.append(kpis);

  const deadlines = pats.projects.filter(p => p.next_deadline)
    .sort((a, b) => a.next_deadline.due.localeCompare(b.next_deadline.due));
  if (deadlines.length) {
    const table = h("table", {}, h("tr", {},
      h("th", {}, "案件"), h("th", {}, "期限"), h("th", {}, "内容")));
    deadlines.slice(0, 5).forEach(p => {
      const left = p.next_deadline.days_left;
      const badge = h("span", { class: "tag " + (left < 14 ? "bad" : left < 60 ? "warn" : "") },
        left < 0 ? "期限経過" : "あと" + left + "日");
      table.append(h("tr", { class: "click", onclick: () => {
        S.view = "patents"; S.patentId = p.id; render();
      } }, h("td", {}, p.title), h("td", {}, p.next_deadline.due, " ", badge),
      h("td", { class: "small" }, p.next_deadline.label)));
    });
    main.append(h("section", { class: "card" },
      h("h2", {}, "特許の期限（目安）"), h("div", { class: "scrollx" }, table)));
  }

  const info = h("dl", { class: "dl" },
    h("dt", {}, "チャンク"), h("dd", {}, String(s.chunks)),
    h("dt", {}, "ベクトル"), h("dd", {}, String(s.vectors)),
    h("dt", {}, "DB 容量"), h("dd", {}, (s.db_bytes / 1048576).toFixed(1) + " MB"),
    h("dt", {}, "全文検索"), h("dd", {}, s.fts5 ? "FTS5（日本語2-gram）" : "LIKE（FTS5なし）"),
    h("dt", {}, "検索用ベクトル索引"), h("dd", {}, st.vectors.vectors + " 件 / RAM " + st.vectors.ram_mb + " MB"));
  main.append(h("details", { class: "card home-technical" },
    h("summary", {}, "技術情報を表示"), info));
  main.append(h("p", { class: "small muted home-version" }, "QnapLibrary v" + S.health.version));

  const live = () => main.isConnected && S.view === "home";
  let lastActivity = null;
  async function refreshActivity() {
    if (!live()) return;
    try {
      const [emb, research, upd, backend] = await Promise.all([
        api("GET", "/api/llm/embedding"), api("GET", "/api/v1/research"),
        api("GET", "/api/update/status"), api("GET", "/api/vectors/backend")
      ]);
      if (!live()) return;
      const tasks = [];
      const e = emb.status || {};
      if (e.running) {
        tasks.push(["ベクトル化中", e.pending == null ? "検索用データを作成しています" :
          "残り " + Number(e.pending).toLocaleString("ja-JP") + " 件", "running"]);
      } else if (e.last_error && e.enabled) {
        tasks.push(["ベクトル化でエラー", e.last_error, "error"]);
      } else if (e.enabled && e.pending > 0) {
        tasks.push(["ベクトル化待ち", "未処理 " + Number(e.pending).toLocaleString("ja-JP") +
          " 件" + (e.auto === false ? "・自動実行オフ" : ""), "waiting"]);
      }
      const activeResearch = (research.jobs || []).filter(j => j.status === "running").slice(0, 3);
      if (activeResearch.length) {
        const jobs = await Promise.all(activeResearch.map(j => api("GET", "/api/v1/research/" + j.id)));
        if (!live()) return;
        jobs.forEach(j => tasks.push(["調査中: " + j.params.question,
          j.result && j.result.step || "処理中", "running"]));
      }
      const sync = backend.sync || {};
      if (sync.running) tasks.push(["検索索引を同期中", "Qdrantへ同期しています", "running"]);
      else if (sync.error) tasks.push(["検索索引の同期エラー", String(sync.error), "error"]);
      if (upd.phase && !["idle", "ready"].includes(upd.phase)) {
        tasks.push(["アップデート", upd.message || upd.phase, upd.error ? "error" : "running"]);
      } else if (upd.error) {
        tasks.push(["アップデートでエラー", String(upd.error), "error"]);
      }
      const key = JSON.stringify(tasks);
      if (key !== lastActivity) {
        lastActivity = key;
        const children = [h("h2", {}, "処理状況")];
        if (!tasks.length) {
          children.push(h("p", { class: "small muted home-idle" }, "現在、実行中の処理はありません。"));
        } else {
          tasks.forEach(([title, detail, status]) => children.push(
            h("div", { class: "home-activity-item" },
              h("span", { class: "home-activity-dot " + status, "aria-hidden": "true" }),
              h("div", {}, h("strong", {}, title), h("div", { class: "small muted" }, detail)))));
        }
        clear(activity).append(...children);
      }
    } catch (error) {
      if (live()) clear(activity).append(h("h2", {}, "処理状況"),
        h("p", { class: "small muted" }, "状態を取得できませんでした: " + error.message));
    } finally {
      if (live()) setTimeout(() => { if (live()) refreshActivity(); }, 20000);
    }
  }
  refreshActivity();
}

// ---------- search ----------
async function searchView(main) {
  await loadCollections();
  main.append(h("h1", {}, "検索"));
  const q = h("input", { class: "wide", placeholder: "例: 固体電解質 電池 -液体　（スペース=AND、OR、-除外、\"フレーズ\"）", value: S.lastQuery || "" });
  const picker = collectionPicker(S.lastColls || []);
  const mode = sel([["hybrid", "ハイブリッド"], ["keyword", "キーワード"], ["vector", "ベクトル"]], S.lastMode || "hybrid");
  const dFrom = h("input", { type: "date", value: S.dFrom || "" }), dTo = h("input", { type: "date", value: S.dTo || "" });
  const out = h("div", {});
  const run = guard(async () => {
    S.lastQuery = q.value; S.lastColls = picker.values(); S.lastMode = mode.value; S.dFrom = dFrom.value; S.dTo = dTo.value;
    const r = await api("POST", "/api/v1/search", { q: q.value, collections: S.lastColls, mode: mode.value, limit: 30, date_from: dFrom.value || null, date_to: dTo.value || null });
    clear(out).append(h("div", { class: "muted small" }, r.results.length + " 件 / " + r.trace.ms + " ms ・ " + r.trace.stages.map(s => s.stage + (s.hits !== undefined ? ":" + s.hits : "") + (s.error ? "(×)" : "")).join(" → ")));
    r.results.forEach(x => out.append(h("div", { class: "result" },
      h("div", { class: "row" }, h("a", { href: "#", class: "t", onclick: e => { e.preventDefault(); openDoc(x.doc_id); } }, x.title || "(無題)"),
        h("span", { class: "tag" }, x.collection), x.ext_id ? h("span", { class: "small muted" }, x.ext_id) : null, h("span", { class: "small muted" }, x.section),
        x.more_chunks ? h("span", { class: "small muted" }, "他" + x.more_chunks + "箇所") : null),
      h("div", { class: "s" }, x.snippet))));
  });
  q.addEventListener("keydown", e => { if (e.key === "Enter") run(); });
  main.append(h("div", { class: "card" }, h("div", { class: "row" }, q, mode, h("button", { class: "btn primary", onclick: run }, "検索")), picker,
    h("div", { class: "row small" }, "日付", dFrom, "〜", dTo)), h("div", { class: "card" }, out));
  if (S.lastQuery) run();
}
async function openDoc(id) {
  const d = await api("GET", "/api/v1/documents/" + id + "?chunks=1");
  S.view = "doc"; S.doc = d;
  const main = $app.querySelector("main"); clear(main);
  main.append(h("div", { class: "row" }, h("button", { class: "btn", onclick: () => { S.view = "search"; render(); } }, "← 戻る")),
    h("h1", {}, d.title || "(無題)"),
    h("div", { class: "card" }, h("dl", { class: "dl" }, h("dt", {}, "ID"), h("dd", {}, d.ext_id || "-"), h("dt", {}, "日付"), h("dd", {}, d.date || "-"),
      h("dt", {}, "出典"), h("dd", {}, d.source || "-"), h("dt", {}, "URL"), h("dd", {}, d.url ? h("a", { href: d.url, target: "_blank", rel: "noopener noreferrer" }, d.url) : "-")),
      h("details", {}, h("summary", {}, "メタデータ"), h("div", { class: "pre" }, JSON.stringify(d.meta, null, 2)))),
    h("div", { class: "card" }, h("div", { class: "row" }, h("h2", {}, "本文"), h("span", { class: "spacer" }),
      h("button", { class: "btn", onclick: guard(() => addRefDialog(d)) }, "特許案件の先行文献に追加")), h("div", { class: "pre" }, d.body || "(本文なし)")),
    h("div", { class: "card" }, h("h2", {}, "チャンク（索引単位） " + d.chunks.length), d.chunks.map(c => h("details", {}, h("summary", {}, "#" + c.ord + " " + c.section), h("div", { class: "pre" }, c.text)))));
}
async function addRefDialog(d) {
  const pats = (await api("GET", "/api/v1/patents")).projects;
  if (!pats.length) return toast("特許案件がありません");
  const main = $app.querySelector("main");
  const p = sel(pats.map(x => [x.id, x.title]), pats[0].id), cat = sel(Object.entries(S.meta?.ref_categories || { X: "X", Y: "Y", A: "A" }).map(([k, v]) => [k, k + ": " + v]), "A"), rel = h("textarea", { placeholder: "関連箇所・一致する構成要件など" });
  const box = h("div", { class: "card" }, h("h2", {}, "先行文献に追加"), field("案件", p), field("分類", cat), field("メモ", rel),
    h("button", { class: "btn primary", onclick: guard(async () => { await api("POST", "/api/v1/patents/" + p.value + "/refs", { doc_id: d.id, ref: (d.ext_id || "") + " " + d.title, category: cat.value, relevance: rel.value }); toast("追加しました"); box.remove(); }) }, "追加"));
  main.prepend(box);
}

// ---------- patents ----------
async function patentsView(main) {
  if (!S.meta) S.meta = await api("GET", "/api/v1/patents/meta");
  await loadCollections();
  if (S.patentId) return patentDetail(main, S.patentId);
  main.append(h("h1", {}, "特許案件"));
  const title = h("input", { class: "wide", placeholder: "発明の名称（仮）" });
  main.append(h("div", { class: "card" }, h("div", { class: "row" }, title, h("button", { class: "btn primary", onclick: guard(async () => {
    const p = await api("POST", "/api/v1/patents", { title: title.value }); S.patentId = p.id; render(); }) }, "新規案件"))));
  const list = (await api("GET", "/api/v1/patents")).projects;
  const stageLabel = Object.fromEntries(S.meta.stages.map(s => [s.id, s.label]));
  main.append(h("div", { class: "card" }, list.length ? h("table", {}, h("tr", {}, h("th", {}, "案件"), h("th", {}, "段階"), h("th", {}, "次の期限"), h("th", {}, "更新")),
    list.map(p => h("tr", { class: "click", onclick: () => { S.patentId = p.id; render(); } }, h("td", {}, p.title), h("td", {}, h("span", { class: "tag" }, stageLabel[p.stage])),
      h("td", { class: "small" }, p.next_deadline ? p.next_deadline.due + " " + p.next_deadline.label : "-"), h("td", { class: "small muted" }, fmtDate(p.updated))))) :
    h("p", { class: "muted" }, "まだ案件がありません。発明の名称を入れて「新規案件」から始めてください。")));
  main.append(h("div", { class: "card small muted" }, "流れ: 発明記録 → 先行技術調査 → 特許性評価 → 方針 → 明細書・請求項 → 出願 → 公開 → 審査請求 → 拒絶理由対応 → 特許査定 → 登録。各段階で AI 支援を使えます。期限は目安で、正式な期限は特許庁の通知・弁理士に確認してください。"));
}
async function patentDetail(main, id) {
  const p = await api("GET", "/api/v1/patents/" + id);
  const tab = S.patentTab || "summary";
  const idx = S.meta.stages.findIndex(s => s.id === p.stage);
  main.append(h("div", { class: "row" }, h("button", { class: "btn", onclick: () => { S.patentId = null; render(); } }, "← 一覧"), h("span", { class: "spacer" }),
    h("button", { class: "btn danger", onclick: guard(async () => { if (!confirm("この案件を削除しますか？")) return; await api("DELETE", "/api/v1/patents/" + id); S.patentId = null; render(); }) }, "削除")));
  main.append(h("h1", {}, p.title));
  main.append(h("div", { class: "stages" }, S.meta.stages.map((s, i) => h("button", { class: "st " + (i < idx ? "done" : i === idx ? "cur" : ""), title: s.goal,
    onclick: guard(async () => { await api("PATCH", "/api/v1/patents/" + id, { stage: s.id }); render(); }) }, (i + 1) + ". " + s.label))));
  main.append(h("div", { class: "card small" }, h("strong", {}, "この段階の目的: "), p.stage_info.goal,
    p.stage_info.ai.length ? h("span", {}, "　AI: ", p.stage_info.ai.map(t => h("button", { class: "btn", onclick: () => { S.patentTab = "ai"; S.aiTask = t; render(); } }, S.meta.tasks[t]))) : null));
  const tabs = [["summary", "発明内容"], ["claims", "請求項"], ["refs", "先行文献 " + p.refs.length], ["chart", "クレームチャート"], ["timeline", "期限・経過"], ["watch", "ウォッチ"], ["ai", "AI 支援"]];
  main.append(h("div", { class: "tabs" }, tabs.map(([t, l]) => h("button", { class: tab === t ? "active" : "", onclick: () => { S.patentTab = t; render(); } }, l))));
  const body = h("div", {}); main.append(body);
  const save = (patch) => api("PATCH", "/api/v1/patents/" + id, patch).then(() => toast("保存しました"));
  if (tab === "summary") {
    const d = p.data, fields = [["field", "技術分野"], ["problem", "課題（従来技術の問題点）"], ["solution", "解決手段（発明の構成）"], ["effect", "効果"], ["embodiment", "実施例・変形例・数値範囲"], ["inventors", "発明者"], ["applicant", "出願人"], ["notes", "メモ"]];
    const inputs = {};
    const t = h("input", { class: "wide", value: p.title });
    body.append(h("div", { class: "card" }, field("発明の名称", t), fields.map(([k, l]) => field(l, inputs[k] = h("textarea", { value: d[k] || "" }))),
      h("label", {}, h("input", { type: "checkbox", checked: d.foreign_resident }), " 在外者（応答期間3か月）"),
      h("div", { class: "row end" }, h("button", { class: "btn primary", onclick: guard(() => {
        const data = {}; for (const k in inputs) data[k] = inputs[k].value; data.foreign_resident = body.querySelector("input[type=checkbox]").checked;
        return save({ title: t.value, data }); }) }, "保存"))));
  } else if (tab === "claims") {
    const ta = h("textarea", { value: p.claims[0] ? p.claims[0].text : "", placeholder: "【請求項１】…" }); ta.style.minHeight = "260px";
    const note = h("input", { class: "wide", placeholder: "版のメモ（例: 拒絶理由対応で補正）" });
    const parsed = h("div", {});
    body.append(h("div", { class: "card" }, ta, field("メモ", note), h("div", { class: "row end" },
      h("button", { class: "btn", onclick: guard(async () => { const r = await api("POST", "/api/v1/patents/parse-claims", { text: ta.value });
        clear(parsed).append(...r.claims.map(c => h("div", { class: "card" }, h("strong", {}, "請求項" + c.no), h("table", {}, c.elements.map(e => h("tr", {}, h("td", {}, e.label), h("td", {}, e.text))))))); }) }, "構成要件に分解"),
      h("button", { class: "btn primary", onclick: guard(async () => { await api("POST", "/api/v1/patents/" + id + "/claims", { text: ta.value, note: note.value }); toast("新しい版として保存"); render(); }) }, "版として保存"))), parsed,
      p.claims.length ? h("div", { class: "card" }, h("h2", {}, "版の履歴"), p.claims.map(c => h("details", {}, h("summary", {}, "v" + c.version + " " + fmtDate(c.created) + " " + (c.note || "")), h("div", { class: "pre" }, c.text)))) : null);
  } else if (tab === "refs") {
    const ref = h("input", { class: "wide", placeholder: "文献番号・名称（例: JP2020-123456A）" }), cat = sel(Object.entries(S.meta.ref_categories).map(([k, v]) => [k, k + ": " + v]), "A"), rel = h("textarea", { placeholder: "関連箇所、対応する構成要件" });
    body.append(h("div", { class: "card" }, h("table", {}, h("tr", {}, h("th", {}, "分類"), h("th", {}, "文献"), h("th", {}, "関連"), h("th", {})),
      p.refs.map(r => h("tr", {}, h("td", {}, h("span", { class: "tag" + (r.category === "X" ? " bad" : r.category === "Y" ? " warn" : "") }, r.category)),
        h("td", {}, r.doc_id ? h("a", { href: "#", onclick: e => { e.preventDefault(); openDoc(r.doc_id); } }, r.ref) : r.ref), h("td", { class: "small" }, r.relevance),
        h("td", {}, h("button", { class: "btn danger", onclick: guard(async () => { await api("DELETE", "/api/v1/patents/" + id + "/refs/" + r.id); render(); }) }, "削除")))))),
      h("div", { class: "card" }, h("h2", {}, "手動で追加"), field("文献", ref), field("分類", cat), field("関連", rel),
        h("button", { class: "btn primary", onclick: guard(async () => { await api("POST", "/api/v1/patents/" + id + "/refs", { ref: ref.value, category: cat.value, relevance: rel.value }); render(); }) }, "追加"),
        h("p", { class: "small muted" }, "検索画面で文献を開き「特許案件の先行文献に追加」でも登録できます。")));
  } else if (tab === "chart") {
    const picker = collectionPicker(S.collections.filter(c => c.kind === "patent").map(c => c.name));
    const no = h("input", { type: "number", value: 1, min: 1, max: 999 });
    const cfg = await api("GET", "/api/llm/providers");
    const prov = sel(cfg.providers.filter(p => p.type !== "openrouter" && p.local_only_verified === true).map(p => [p.id, p.label || p.id]), cfg.default_provider);
    const progress = h("div", { class: "small muted", role: "status", "aria-live": "polite" });
    const out = h("div", {});
    function showChart(chart) {
      const content = h("div", {});
      if (chart.note) content.append(h("p", { class: "small muted" }, chart.note));
      if (chart.model) content.append(h("p", { class: "small muted" }, "利用モデル: " + chart.model));
      if (!chart.rows.length) content.append(h("p", { class: "muted" }, "構成要件が見つかりません。"));
      for (const row of chart.rows) {
        const a = row.assessment, sources = h("div", {});
        for (const e of row.evidence) sources.append(h("div", { class: "result" },
          h("a", { href: "#", onclick: ev => { ev.preventDefault(); openDoc(e.doc_id); } },
            (e.ext_id || "") + " " + e.title),
          h("span", { class: "small muted" }, " " + (e.section || "")),
          h("div", { class: "small muted" }, e.snippet || "")));
        const assessment = a ? h("div", { class: "claim-assessment" },
          h("div", { class: "row" },
            h("strong", { class: "claim-mark" }, a.judgment),
            h("span", {}, "AIの暫定判定")),
          h("p", {}, a.reason),
          (a.citations || []).length ? h("div", { class: "small" }, "根拠: ",
            a.citations.map(c => h("a", { href: "#", onclick: ev => { ev.preventDefault(); openDoc(c.doc_id); } },
              "[" + c.ref + "] " + c.title + " "))) : h("p", { class: "small muted" }, "有効な引用なし")) : null;
        content.append(h("section", { class: "card" },
          h("h3", {}, row.element.label + "　" + row.element.text),
          assessment, h("details", { open: !a }, h("summary", {}, "検索された根拠候補（" + row.evidence.length + " 件）"), sources)));
      }
      clear(out).append(content);
    }
    async function run(ai, btn) {
      btn.disabled = true;
      clear(out);
      progress.textContent = ai ? "AI が根拠を照合しています。結果は保存されません…" : "候補文献を検索しています…";
      try {
        const url = "/api/v1/patents/" + id + (ai ? "/chart/assess" : "/chart");
        const result = await api("POST", url, {
          claim_no: +no.value, collections: picker.values(), provider: ai ? prov.value : undefined
        });
        if (S.view === "patents" && S.patentId === id && S.patentTab === "chart") showChart(result);
        progress.textContent = "";
      } finally { btn.disabled = false; }
    }
    const search = h("button", { class: "btn", onclick: guard(async () => run(false, search)) }, "候補を検索");
    const judge = h("button", { class: "btn primary", onclick: guard(async () => run(true, judge)) }, "AIで仮判定");
    body.append(h("div", { class: "card" }, h("h2", {}, "構成要件と根拠の照合"),
      h("p", { class: "small muted" }, "未公開発明を保護するため、ローカル専用と確認済みのAIだけを利用します。根拠断片から○（対応）/△（一部・不確か）/×（今回の断片に記載なし）/?（未判定）を提案します。自動保存や法的確定判断はしません。"),
      h("div", { class: "row" }, field("請求項", no), field("AIプロバイダ", prov)),
      field("調査対象のコレクション", picker),
      h("div", { class: "row end" }, search, judge), progress), out);
  } else if (tab === "timeline") {
    const kind = sel(Object.entries(S.meta.events), "filing"), date = h("input", { type: "date" }), note = h("input", { placeholder: "メモ" });
    body.append(h("div", { class: "card" }, h("h2", {}, "期限（目安）"), p.deadlines.length ? h("table", {}, p.deadlines.map(d => h("tr", {}, h("td", {}, d.due), h("td", {}, h("span", { class: "tag " + (d.days_left < 0 ? "" : d.days_left < 14 ? "bad" : d.days_left < 60 ? "warn" : "ok") }, d.days_left < 0 ? "経過" : "あと" + d.days_left + "日")), h("td", {}, d.label), h("td", { class: "small muted" }, d.basis)))) : h("p", { class: "muted" }, "出願日などの経過を登録すると期限を計算します。"),
      h("p", { class: "small muted" }, "期限は特許法の一般的な規定に基づく目安です。正式な期限は特許庁の通知と弁理士で確認してください。")),
      h("div", { class: "card" }, h("h2", {}, "経過"), h("table", {}, p.events.map(e => h("tr", {}, h("td", {}, e.date), h("td", {}, S.meta.events[e.kind]), h("td", { class: "small" }, e.note),
        h("td", {}, h("button", { class: "btn danger", onclick: guard(async () => { await api("DELETE", "/api/v1/patents/" + id + "/events/" + e.id); render(); }) }, "削除"))))),
        h("div", { class: "row" }, kind, date, note, h("button", { class: "btn primary", onclick: guard(async () => { await api("POST", "/api/v1/patents/" + id + "/events", { kind: kind.value, date: date.value, note: note.value }); render(); }) }, "追加"))));
  } else if (tab === "watch") {
    await watchTab(body, id);
  } else if (tab === "ai") {
    const providers = await api("GET", "/api/llm/providers");
    const task = sel(Object.entries(S.meta.tasks), S.aiTask || "novelty");
    const prov = sel(providers.providers.map(x => [x.id, x.label || x.id]), providers.default_provider);
    const picker = collectionPicker(S.collections.map(c => c.name));
    const extra = h("textarea", { placeholder: "追加指示（拒絶理由通知の本文、対象製品の説明など）" });
    const out = h("div", {});
    const btn = h("button", { class: "btn primary", onclick: guard(async () => {
      btn.disabled = true; clear(out).append(h("p", { class: "muted" }, "AI が回答を作成中…（数十秒かかることがあります）"));
      try { const r = await api("POST", "/api/v1/patents/" + id + "/assist", { task: task.value, provider: prov.value, collections: picker.values(), extra: extra.value });
        clear(out).append(h("div", { class: "card" }, h("div", { class: "row small muted" }, r.model || "", h("span", { class: "spacer" }), h("button", { class: "btn", onclick: () => navigator.clipboard.writeText(r.answer) }, "コピー")), md(r.answer),
          r.evidence.length ? h("div", { class: "small muted" }, "参照: ", r.evidence.map((e, i) => h("a", { href: "#", onclick: ev => { ev.preventDefault(); openDoc(e.doc_id); } }, "[" + (i + 1) + "] " + (e.ext_id || e.title) + " "))) : null));
      } finally { btn.disabled = false; } }) }, "実行");
    body.append(h("div", { class: "card" }, field("タスク", task), field("AI プロバイダ", prov), field("根拠を探すコレクション", picker), field("追加指示", extra), h("div", { class: "row end" }, btn)), out);
  }
}

async function watchTab(body, pid) {
  const [ws, hits, cs] = await Promise.all([api("GET", "/api/v1/watches?patent_id=" + pid), api("GET", "/api/v1/watch-hits?patent_id=" + pid), api("GET", "/api/v1/connectors")]);
  body.append(h("div", { class: "card" }, h("h2", {}, "ウォッチ（定期収集）"),
    h("p", { class: "small muted" }, "外部データ源を定期的に取得し、新しい文献をこの案件の請求項と照合して候補に出します。新しい候補は通知（設定 > 通知）で知らせます。"),
    ws.watches.length ? h("table", {}, h("tr", {}, h("th", {}, "名前"), h("th", {}, "収集元"), h("th", {}, "間隔"), h("th", {}, "前回"), h("th", {})),
      ws.watches.map(w => h("tr", {}, h("td", {}, w.name, w.new_hits ? h("span", { class: "tag bad" }, "新" + w.new_hits) : null), h("td", { class: "small" }, w.connector, " ", h("code", {}, JSON.stringify(w.params))),
        h("td", {}, Math.round(w.interval_hours / 24 * 10) / 10 + "日"), h("td", { class: "small muted" }, fmtDate(w.last_run), " ", w.last_status),
        h("td", {}, h("button", { class: "btn", onclick: guard(async (e) => { e.target.disabled = true; try { const r = await api("POST", "/api/v1/watches/" + w.id + "/run", {}); toast(r.last_status); render(); } finally { e.target.disabled = false; } }) }, "今すぐ実行"),
          h("button", { class: "btn danger", onclick: guard(async () => { await api("DELETE", "/api/v1/watches/" + w.id); render(); }) }, "削除"))))) : h("p", { class: "muted" }, "ウォッチはまだありません。")));
  const conn = sel(cs.connectors.map(c => [c.id, c.label + (c.key && !c.configured ? "（未登録）" : "")]), "epo_ops");
  const q = h("input", { class: "wide", placeholder: "EPO: CQL（例: ta=\"solid electrolyte\" and pd>=2024）／GDELT: 検索語／RSS: URL" });
  const name = h("input", { placeholder: "名前" }), coll = h("input", { placeholder: "保存先（空なら自動）" }), days = h("input", { type: "number", value: 7, min: 1 });
  body.append(h("div", { class: "card" }, h("h2", {}, "ウォッチを追加"), h("div", { class: "row" }, name, conn, days, h("span", { class: "small" }, "日ごと")), field("条件", q), field("保存先コレクション", coll),
    h("button", { class: "btn primary", onclick: guard(async () => { const c = conn.value; const key = c === "rss" ? "url" : c === "jpo" ? "application_number" : "query";
      await api("POST", "/api/v1/watches", { name: name.value || q.value.slice(0, 40), connector: c, params: { [key]: q.value }, collection: coll.value, patent_id: pid, interval_hours: Math.max(6, +days.value * 24) }); render(); }) }, "追加")));
  body.append(h("div", { class: "card" }, h("h2", {}, "候補（新しい順・スコア順）"), hits.hits.length ? h("table", {}, hits.hits.map(x => h("tr", {},
    h("td", {}, h("span", { class: "tag " + (x.status === "new" ? "bad" : x.status === "relevant" ? "ok" : "") }, { new: "新規", relevant: "関連", dismissed: "対象外" }[x.status])),
    h("td", {}, h("a", { href: "#", onclick: e => { e.preventDefault(); openDoc(x.doc_id); } }, (x.ext_id || "") + " " + x.title), h("div", { class: "small muted" }, x.watch_name + " / " + (x.doc_date || "") + " / スコア " + x.score)),
    h("td", {}, h("button", { class: "btn", onclick: guard(async () => { await api("POST", "/api/v1/watch-hits/" + x.id, { status: "relevant", category: "Y" }); toast("先行文献(Y)に追加"); render(); }) }, "関連→Y"),
      h("button", { class: "btn", onclick: guard(async () => { await api("POST", "/api/v1/watch-hits/" + x.id, { status: "relevant", category: "X" }); toast("先行文献(X)に追加"); render(); }) }, "X"),
      h("button", { class: "btn", onclick: guard(async () => { await api("POST", "/api/v1/watch-hits/" + x.id, { status: "dismissed" }); render(); }) }, "対象外"))))) : h("p", { class: "muted" }, "候補はまだありません。")));
}

// ---------- data ----------
async function dataView(main) {
  await loadCollections();
  main.append(h("h1", {}, "データ（コレクション）"));
  const name = h("input", { placeholder: "名前（例: patents-jp）" }), kind = sel(S.kinds, "generic"), desc = h("input", { placeholder: "説明", class: "wide" });
  main.append(h("div", { class: "card" }, h("div", { class: "row" }, name, kind, desc, h("button", { class: "btn primary", onclick: guard(async () => { await api("POST", "/api/v1/collections", { name: name.value, kind: kind.value, description: desc.value }); render(); }) }, "作成"))));
  main.append(h("div", { class: "card" }, h("table", {}, h("tr", {}, h("th", {}, "名前"), h("th", {}, "種別"), h("th", {}, "文書"), h("th", {}, "チャンク"), h("th", {}, "ベクトル"), h("th", {}, "更新")),
    S.collections.map(c => h("tr", { class: "click", onclick: () => { S.collId = c.id; S.docOffset = 0; render(); } }, h("td", {}, c.name), h("td", {}, h("span", { class: "tag" }, c.kind)), h("td", {}, c.documents), h("td", {}, c.chunks), h("td", {}, c.vectors), h("td", { class: "small muted" }, fmtDate(c.updated)))))));
  const c = S.collections.find(x => x.id === S.collId);
  if (!c) return;
  const card = h("div", { class: "card" }); main.append(card);
  card.append(h("div", { class: "row" }, h("h2", {}, c.name), h("span", { class: "muted small" }, c.description), h("span", { class: "spacer" }),
    h("a", { class: "btn", href: "/api/v1/collections/" + c.id + "/export", download: c.name + ".ndjson" }, "エクスポート"),
    h("button", { class: "btn", onclick: guard(async () => { const r = await api("POST", "/api/v1/collections/" + c.id + "/embed", { limit: 256 }); toast(r.embedded + " 件をベクトル化" + (r.more ? "（続きあり）" : "")); render(); }) }, "ベクトル化"),
    h("button", { class: "btn", onclick: guard(async () => { if (!confirm(c.name + " のベクトルを削除します（埋め込みモデル変更時の作り直し用）")) return; const r = await api("DELETE", "/api/v1/collections/" + c.id + "/vectors"); toast(r.deleted + " 件削除。自動で再作成されます"); await api("POST", "/api/llm/embedding/run", {}).catch(() => {}); render(); }) }, "ベクトル再作成"),
    h("button", { class: "btn danger", onclick: guard(async () => { if (!confirm(c.name + " を削除しますか？（元に戻せません）")) return; await api("DELETE", "/api/v1/collections/" + c.id); S.collId = null; render(); }) }, "削除")));
  const fmt = sel([["ndjson", "NDJSON"], ["json", "JSON 配列"], ["csv", "CSV (id,title,body,url,date…)"], ["text", "テキスト1件"], ["codes", "分類コード表（コード<TAB>説明）"]], "ndjson");
  const data = h("textarea", { placeholder: '{"id":"JP2020-123456A","title":"…","abstract":"…","sections":{"claims":"【請求項１】…","description":"…"},"date":"2020-01-01"}' });
  const file = h("input", { type: "file", accept: ".ndjson,.json,.jsonl,.csv,.txt,.md" });
  file.addEventListener("change", async () => { const f = file.files[0]; if (!f) return; if (f.size > 90e6) return toast("90MB 以下のファイルにしてください"); data.value = await f.text();
    if (/\.csv$/i.test(f.name)) fmt.value = "csv"; else if (/\.json$/i.test(f.name)) fmt.value = "json"; else if (/\.(txt|md)$/i.test(f.name)) fmt.value = "text"; else fmt.value = "ndjson"; });
  card.append(h("details", {}, h("summary", {}, "取り込み（貼り付け / ファイル）"), h("div", { class: "row" }, fmt, file,
      c.kind === "standard" ? h("a", { class: "btn", href: "/api/v1/templates/standards.csv" }, "規格CSVテンプレート") : null), data,
    h("div", { class: "row end" }, h("button", { class: "btn primary", onclick: guard(async () => { const r = await api("POST", "/api/v1/collections/" + c.id + "/import", { format: fmt.value, data: data.value }); toast("追加 " + r.added + " / 更新 " + r.updated + " / 変更なし " + r.unchanged); data.value = ""; render(); }) }, "取り込む"))));
  const q = h("input", { placeholder: "タイトル/ID で絞り込み", value: S.docQ || "" });
  const list = await api("GET", "/api/v1/collections/" + c.id + "/documents?limit=50&offset=" + (S.docOffset || 0) + "&q=" + encodeURIComponent(S.docQ || ""));
  card.append(h("div", { class: "row" }, q, h("button", { class: "btn", onclick: () => { S.docQ = q.value; S.docOffset = 0; render(); } }, "絞り込み"), h("span", { class: "spacer" }),
    h("span", { class: "small muted" }, (S.docOffset || 0) + 1 + "–" + ((S.docOffset || 0) + list.items.length) + " / " + list.total),
    h("button", { class: "btn", disabled: !S.docOffset, onclick: () => { S.docOffset = Math.max(0, (S.docOffset || 0) - 50); render(); } }, "前"),
    h("button", { class: "btn", disabled: (S.docOffset || 0) + 50 >= list.total, onclick: () => { S.docOffset = (S.docOffset || 0) + 50; render(); } }, "次")));
  card.append(h("table", {}, list.items.map(d => h("tr", { class: "click", onclick: () => openDoc(d.id) }, h("td", { class: "small" }, d.ext_id || d.id), h("td", {}, d.title), h("td", { class: "small muted" }, d.date), h("td", { class: "small muted" }, (d.body_chars / 1000).toFixed(1) + "k字")))));
}

// ---------- analytics ----------
function bars(rows, max) {
  max = max || Math.max(1, ...rows.map(r => r.n));
  return h("table", {}, rows.map(r => { const bar = h("div", { class: "bar" }); bar.style.width = Math.max(2, Math.round(r.n / max * 100)) + "%";
    return h("tr", {}, h("td", { class: "small" }, r.k || "(空)"), h("td", { class: "barcell" }, bar), h("td", { class: "small" }, r.n)); }));
}
async function analyticsView(main) {
  await loadCollections();
  main.append(h("h1", {}, "分析"));
  if (!S.collections.length) return main.append(h("p", { class: "muted" }, "コレクションがありません"));
  const coll = sel(S.collections.map(c => [c.name, c.name + "（" + c.documents + "）"]), S.anColl || S.collections[0].name);
  const out = h("div", {});
  const load = guard(async (field) => {
    S.anColl = coll.value;
    const r = await api("GET", "/api/v1/analytics?collection=" + encodeURIComponent(coll.value) + (field ? "&field=" + encodeURIComponent(field) : ""));
    const fsel = sel([["", "（メタデータ項目を選択）"]].concat(r.fields.map(f => [f, f])), field || "");
    fsel.addEventListener("change", () => load(fsel.value));
    clear(out).append(h("div", { class: "grid" }, h("div", { class: "card" }, h("h2", {}, "年別件数"), r.by_year.length ? bars(r.by_year) : h("p", { class: "muted" }, "日付なし")),
      h("div", { class: "card" }, h("h2", {}, "出典"), r.by_source.length ? bars(r.by_source) : h("p", { class: "muted" }, "出典なし"))),
      h("div", { class: "card" }, h("div", { class: "row" }, h("h2", {}, "項目別（出願人・IPC など）"), fsel), r.by_field ? bars(r.by_field) : h("p", { class: "small muted" }, "文書の meta にある項目（applicants, ipc など）を選ぶと上位 25 件と年別の推移を表示します。"),
        r.matrix && r.matrix.length ? heat(r.matrix) : null));
  });
  coll.addEventListener("change", () => load(""));
  main.append(h("div", { class: "card row" }, "コレクション", coll), out);
  load(S.anField || "");
}
function heat(matrix) {
  const ys = [...new Set(matrix.map(m => m.y))].sort(), ks = [...new Set(matrix.map(m => m.k))];
  const max = Math.max(...matrix.map(m => m.n)); const get = (k, y) => (matrix.find(m => m.k === k && m.y === y) || {}).n || 0;
  return h("div", {}, h("h3", {}, "年別の推移（濃いほど多い・空白領域の把握に）"), h("div", { class: "scrollx" }, h("table", { class: "heat" }, h("tr", {}, h("th", {}), ys.map(y => h("th", {}, y))),
    ks.map(k => h("tr", {}, h("td", { class: "small" }, k), ys.map(y => { const n = get(k, y); const td = h("td", { title: k + " " + y + ": " + n }, n || ""); td.style.background = n ? "rgba(31,95,191," + (0.15 + 0.85 * n / max).toFixed(2) + ")" : "transparent"; if (n / max > 0.5) td.style.color = "#fff"; return td; }))))));
}

// ---------- chat ----------
async function chatView(main) {
  await loadCollections();
  const [threads, providers] = await Promise.all([api("GET", "/api/chat/threads"), api("GET", "/api/llm/providers")]);
  main.append(h("h1", {}, "AI チャット"));
  const wrap = h("div", { class: "chat" }); main.append(wrap);
  const list = h("div", { class: "threads card" }, h("button", { class: "btn primary", onclick: guard(async () => { const r = await api("POST", "/api/chat/threads", {}); S.threadId = r.id; render(); }) }, "＋ 新しいチャット"),
    threads.threads.map(t => h("button", { class: S.threadId === t.id ? "active" : "", onclick: () => { S.threadId = t.id; render(); } }, t.title)));
  const pane = h("div", { class: "pane" }); wrap.append(list, pane);
  if (!S.threadId && threads.threads[0]) S.threadId = threads.threads[0].id;
  if (!S.threadId) { pane.append(h("div", { class: "card muted" }, "「新しいチャット」を作成してください。ライブラリの文書を根拠に回答します。")); return; }
  const th = await api("GET", "/api/chat/threads/" + S.threadId);
  const msgs = h("div", { class: "msgs" });
  const addMsg = (m) => { const b = h("div", { class: "b" }, m.role === "assistant" ? md(m.content) : m.content); const el = h("div", { class: "msg " + m.role }, b);
    const src = (m.meta && m.meta.sources) || []; if (src.length) el.append(h("div", { class: "src" }, "参照: ", src.map(s => h("a", { href: "#", onclick: e => { e.preventDefault(); openDoc(s.doc_id); } }, "[" + s.n + "] " + (s.ext_id || s.title) + " "))));
    if (m.meta && (m.meta.model || m.meta.error)) el.append(h("div", { class: "src" }, (m.meta.model || "") + (m.meta.error ? " エラー: " + m.meta.error : "")));
    msgs.append(el); msgs.scrollTop = msgs.scrollHeight; return el; };
  th.messages.forEach(addMsg);
  const prov = sel(providers.providers.map(x => [x.id, x.label || x.id]), S.chatProvider || providers.default_provider);
  const rag = h("input", { type: "checkbox", checked: S.chatRag !== false });
  const picker = collectionPicker(S.chatColls || []);
  const ta = h("textarea", { placeholder: "質問（Ctrl/⌘+Enter で送信）" });
  const send = guard(async () => {
    const content = ta.value.trim(); if (!content) return; ta.value = ""; S.chatProvider = prov.value; S.chatRag = rag.checked; S.chatColls = picker.values();
    addMsg({ role: "user", content });
    const el = addMsg({ role: "assistant", content: "…" }); const b = el.querySelector(".b"); let text = "", sources = [];
    const res = await api("POST", "/api/chat/threads/" + S.threadId + "/messages", { content, provider: prov.value, rag: { enabled: rag.checked, collections: S.chatColls } }, { raw: true });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.error || "HTTP " + res.status); }
    const reader = res.body.getReader(), dec = new TextDecoder(); let buf = "";
    for (;;) { const { value, done } = await reader.read(); if (done) break; buf += dec.decode(value, { stream: true });
      let i; while ((i = buf.indexOf("\n\n")) >= 0) { const line = buf.slice(0, i); buf = buf.slice(i + 2); if (!line.startsWith("data:")) continue;
        const ev = JSON.parse(line.slice(5)); if (ev.sources) sources = ev.sources; if (ev.delta) { text += ev.delta; clear(b).append(md(text)); msgs.scrollTop = msgs.scrollHeight; }
        if (ev.error) b.append(h("p", { class: "tag bad" }, ev.error)); } }
    if (sources.length) el.append(h("div", { class: "src" }, "参照: ", sources.map(s => h("a", { href: "#", onclick: e => { e.preventDefault(); openDoc(s.doc_id); } }, "[" + s.n + "] " + (s.ext_id || s.title) + " "))));
  });
  ta.addEventListener("keydown", e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) send(); });
  pane.append(h("div", { class: "row small" }, prov, h("label", {}, rag, " ライブラリを根拠にする"), h("span", { class: "spacer" }),
    h("button", { class: "btn danger", onclick: guard(async () => { await api("DELETE", "/api/chat/threads/" + S.threadId); S.threadId = null; render(); }) }, "削除")), picker, msgs,
    h("div", { class: "composer" }, ta, h("button", { class: "btn primary", onclick: send }, "送信")));
}

// ---------- collect ----------
async function collectView(main) {
  await loadCollections();
  const cs = (await api("GET", "/api/v1/connectors")).connectors;
  await researchCard(main);
  main.append(h("h1", {}, "収集（外部データ源）"),
    h("p", { class: "muted small" }, "公式 API・フィードのみ利用します。キーが必要なものは 設定 > 外部キー で登録してください。別PCからは REST API / MCP で直接投入できます。"));
  cs.forEach(c => {
    const inputs = {};
    const coll = h("input", { placeholder: "保存先コレクション（空なら " + c.kind + "-" + c.id + "）", list: "colls" });
    const out = h("div", { class: "small muted" });
    main.append(h("div", { class: "card" }, h("div", { class: "row" }, h("h2", {}, c.label), h("span", { class: "tag" }, c.kind),
      c.key ? h("span", { class: "tag " + (c.configured ? "ok" : "warn") }, c.configured ? "キー設定済" : "キー未設定") : null), h("p", { class: "small muted" }, c.note),
      c.params.map(p => field(p.label, inputs[p.name] = h("input", { class: "wide", value: p.default ?? "" }))), field("保存先", coll),
      c.key && !c.configured ? h("p", { class: "small" }, h("span", { class: "tag warn" }, "未登録のため使いません"), " 設定 > 外部キー で登録すると利用できます。") : null,
      h("div", { class: "row end" }, out, h("button", { class: "btn primary", disabled: !!(c.key && !c.configured), onclick: guard(async (e) => { e.target.disabled = true;
        try { const params = {}; for (const k in inputs) params[k] = inputs[k].value; const r = await api("POST", "/api/v1/connectors/" + c.id + "/run", { params, collection: coll.value });
          out.textContent = r.collection + ": 取得 " + r.fetched + " / 追加 " + r.added + " / 更新 " + r.updated + "（" + r.ms + "ms）"; } finally { e.target.disabled = false; } }) }, "実行"))));
  });
  main.append(h("datalist", { id: "colls" }, S.collections.map(c => h("option", { value: c.name }))));
}

async function researchCard(main) {
  const [jobs, providers] = await Promise.all([api("GET", "/api/v1/research"), api("GET", "/api/llm/providers")]);
  const q = h("textarea", { placeholder: "調査したいこと（例: 全固体電池の硫化物系電解質について、主要出願人と最近の技術課題・規格動向を整理して）" });
  const prov = sel(providers.providers.map(x => [x.id, x.label || x.id]), providers.default_provider), news = h("input", { type: "checkbox" }), picker = collectionPicker([]);
  const out = h("div", {});
  const show = guard(async (id) => { const j = await api("GET", "/api/v1/research/" + id); const r = j.result;
    clear(out).append(h("div", { class: "card" }, h("div", { class: "row" }, h("strong", {}, j.params.question), h("span", { class: "tag " + (j.status === "done" ? "ok" : j.status === "failed" ? "bad" : "warn") }, r.step || j.status)),
      r.sub_questions ? h("details", {}, h("summary", {}, "サブ質問 " + r.sub_questions.length), h("ul", {}, r.sub_questions.map(x => h("li", {}, x)))) : null,
      r.error ? h("p", { class: "tag bad" }, r.error) : null, r.report ? md(r.report) : null,
      r.sources ? h("div", { class: "small muted" }, "根拠: ", r.sources.map(x => h("a", { href: "#", onclick: e => { e.preventDefault(); openDoc(x.doc_id); } }, "[" + x.n + "] " + (x.ext_id || x.title) + " "))) : null));
    if (j.status === "running") setTimeout(() => S.view === "collect" && show(id), 4000); });
  main.append(h("h1", {}, "調査ジョブ"), h("div", { class: "card" }, h("p", { class: "small muted" }, "質問をサブ質問に分け、ライブラリ（と任意で世界ニュース）を検索して根拠付きレポートを作り、reports コレクションに保存します。1 件ずつ実行します。"),
    q, h("div", { class: "row" }, prov, h("label", {}, news, " 世界ニュース（GDELT）も調べる"), h("span", { class: "spacer" }),
      h("button", { class: "btn primary", onclick: guard(async () => { const j = await api("POST", "/api/v1/research", { question: q.value, provider: prov.value, use_news: news.checked, collections: picker.values() }); show(j.id); }) }, "調査開始")), picker,
    jobs.jobs.length ? h("table", {}, jobs.jobs.slice(0, 10).map(j => h("tr", { class: "click", onclick: () => show(j.id) }, h("td", {}, j.question), h("td", {}, h("span", { class: "tag" }, j.status)), h("td", { class: "small muted" }, fmtDate(j.created))))) : null), out);
}

// ---------- settings ----------
async function settingsView(main) {
  main.append(h("h1", {}, "設定"));
  const tab = S.setTab || "account";
  const tabs = [["account", "アカウント"], ["devices", "デバイス接続"], ["ai", "AI"], ["keys", "外部キー"], ["notify", "通知"], ["backend", "検索基盤"], ["backups", "バックアップ"], ["update", "更新"], ["debug", "デバッグ"]];
  main.append(h("div", { class: "tabs" }, tabs.map(([t, l]) => h("button", { class: tab === t ? "active" : "", onclick: () => { S.setTab = t; render(); } }, l))));
  const body = h("div", {}); main.append(body);
  if (tab === "account") {
    const pks = await api("GET", "/api/auth/passkeys");
    const cur = h("input", { type: "password" }), nw = h("input", { type: "password" }), pkName = h("input", { placeholder: "例: iPhone Face ID" });
    body.append(h("div", { class: "card" }, h("h2", {}, "パスキー（顔認証 / 指紋）"),
      h("p", { class: "small muted" }, "Face ID・Windows Hello などで管理Webにログインできます。ブラウザの仕様上、名前付きの HTTPS アドレス（Tailscale の *.ts.net）で開いている必要があります。"),
      h("table", {}, pks.map(k => h("tr", {}, h("td", {}, k.name), h("td", { class: "small muted" }, "登録 " + fmtDate(k.created) + " / 最終 " + fmtDate(k.last_used)),
        h("td", {}, h("button", { class: "btn danger", onclick: guard(async () => { await api("DELETE", "/api/auth/passkeys/" + k.id); render(); }) }, "削除"))))),
      h("div", { class: "row" }, pkName, h("button", { class: "btn primary", disabled: !S.meInfo.passkey_ready || !window.PublicKeyCredential, onclick: guard(async () => {
        const o = (await api("POST", "/api/auth/passkey/register/options", {})).publicKey;
        o.challenge = unb64u(o.challenge); o.user.id = unb64u(o.user.id); o.excludeCredentials = o.excludeCredentials.map(c => ({ ...c, id: unb64u(c.id) }));
        const cred = await navigator.credentials.create({ publicKey: o });
        await api("POST", "/api/auth/passkey/register/verify", { id: b64u(cred.rawId), clientDataJSON: b64u(cred.response.clientDataJSON), attestationObject: b64u(cred.response.attestationObject), name: pkName.value });
        toast("登録しました"); render(); }) }, "この端末を登録")),
      !S.meInfo.passkey_ready ? h("p", { class: "tag warn" }, "現在の接続（" + location.origin + "）では登録できません。下の HTTPS 設定を行い https の名前で開いてください") : null),
      httpsCard(),
      h("div", { class: "card" }, h("h2", {}, "パスワード変更"), field("現在のパスワード", cur), field("新しいパスワード（10文字以上）", nw),
        h("button", { class: "btn", onclick: guard(async () => { await api("POST", "/api/auth/password", { current: cur.value, password: nw.value }); toast("変更しました"); }) }, "変更"),
        h("button", { class: "btn", onclick: guard(async () => { await api("POST", "/api/auth/logout", {}); S.me = null; render(); }) }, "ログアウト")));
  } else if (tab === "devices") {
    const d = await api("GET", "/api/devices");
    const pc = h("input", { type: "password", placeholder: "8文字以上" }), dn = h("input", { placeholder: "デバイス名" }), out = h("div", {});
    body.append(h("div", { class: "card" }, h("h2", {}, "LAN ペアリング用パスコード"), h("p", { class: "small muted" }, "別PC・AI アシスタント・ControlDeck が POST /api/v1/pair {\"passcode\":\"…\",\"name\":\"…\"} で長期トークンを取得します（LAN / Tailscale からのみ、取得後は無制限に利用可）。"),
      h("p", {}, "状態: ", h("span", { class: "tag " + (d.pairing_enabled ? "ok" : "warn") }, d.pairing_enabled ? "有効" : "未設定")),
      h("div", { class: "row" }, pc, h("button", { class: "btn primary", onclick: guard(async () => { await api("PUT", "/api/devices/pairing", { passcode: pc.value }); toast("設定しました"); render(); }) }, "設定"),
        h("button", { class: "btn", onclick: guard(async () => { await api("PUT", "/api/devices/pairing", { passcode: "" }); render(); }) }, "無効化")),
      h("details", {}, h("summary", {}, "接続例"), h("div", { class: "pre" }, 'curl -X POST http://<NAS>:' + location.port + '/api/v1/pair -H "Content-Type: application/json" -d \'{"passcode":"…","name":"my-pc"}\'\n\n# 以降\ncurl -H "Authorization: Bearer qlt_…" http://<NAS>:' + location.port + '/api/v1/collections\n# MCP: POST http://<NAS>:' + location.port + '/mcp （同じトークン）'))),
      h("div", { class: "card" }, h("h2", {}, "接続済みデバイス"), h("table", {}, d.devices.map(x => h("tr", {}, h("td", {}, x.name), h("td", {}, h("span", { class: "tag" }, x.scopes)), h("td", { class: "small muted" }, "最終 " + fmtDate(x.last_seen) + " " + (x.last_ip || "")),
        h("td", {}, h("button", { class: "btn danger", onclick: guard(async () => { await api("DELETE", "/api/devices/" + x.id); render(); }) }, "失効"))))),
        h("div", { class: "row" }, dn, h("button", { class: "btn", onclick: guard(async () => { const r = await api("POST", "/api/devices", { name: dn.value }); clear(out).append(h("p", {}, "トークン（一度だけ表示）: ", h("code", {}, r.token))); }) }, "トークンを直接発行")), out));
  } else if (tab === "ai") {
    await aiSettings(body);
  } else if (tab === "keys") {
    const s = await api("GET", "/api/settings");
    const labels = { openrouter_api_key: "OpenRouter API キー", epo_ops_key: "EPO OPS Consumer Key", epo_ops_secret: "EPO OPS Consumer Secret", jpo_username: "JPO 特許情報取得API ID", jpo_password: "JPO 特許情報取得API パスワード", uspto_api_key: "USPTO ODP API キー", openai_api_key: "OpenAI 互換 API キー（任意）", smtp_password: "SMTP パスワード（通知メール）", qdrant_api_key: "Qdrant API キー（任意）", estat_app_id: "e-Stat アプリケーションID", edinet_api_key: "EDINET API キー" };
    const ua = h("input", { class: "wide", value: (s.settings.connectors || {}).sec_user_agent || "", placeholder: "例: Taro Yamada taro@example.com" });
    body.append(h("div", { class: "card" }, h("h2", {}, "SEC EDGAR の User-Agent（キーではありません）"), field("名前とメールアドレス", ua),
      h("button", { class: "btn", onclick: guard(async () => { await api("PUT", "/api/settings", { connectors: { sec_user_agent: ua.value } }); toast("保存しました"); }) }, "保存")));
    body.append(h("div", { class: "card" }, h("p", { class: "small muted" }, "キーは secrets.json（権限 0600）に保存され、画面・API・デバッグ出力には表示されません。"),
      h("table", {}, Object.entries(labels).map(([k, l]) => { const inp = h("input", { type: "password", placeholder: s.secrets[k].configured ? "設定済み（" + s.secrets[k].fingerprint + "）" : "未設定" });
        return h("tr", {}, h("td", {}, l), h("td", {}, inp), h("td", {}, h("button", { class: "btn", onclick: guard(async () => { await api("PUT", "/api/secrets/" + k, { value: inp.value }); toast("保存しました"); render(); }) }, "保存"),
          h("button", { class: "btn danger", onclick: guard(async () => { await api("PUT", "/api/secrets/" + k, { value: "" }); render(); }) }, "削除"))); }))));
  } else if (tab === "notify") {
    const st = await api("GET", "/api/settings"); const n = st.settings.notify || {}; const em = n.email || {};
    const hooks = h("textarea", { value: (n.webhooks || []).map(w => [w.kind || "json", w.url, w.label || ""].join(" ")).join("\n"), placeholder: "1行に1件: 種類(json/discord/slack) URL 表示名\n例: discord https://discord.com/api/webhooks/... 研究用\n例: json http://192.168.1.20:8765/api/v1/webhooks/xxx ControlDeck" });
    const days = h("input", { value: (n.deadline_days || [60, 30, 7]).join(","), placeholder: "60,30,7" });
    const e = { enabled: h("input", { type: "checkbox", checked: em.enabled }), host: h("input", { value: em.host || "" }), port: h("input", { type: "number", value: em.port || 587 }), user: h("input", { value: em.user || "" }), from: h("input", { value: em.from || "" }), to: h("input", { value: em.to || "" }), starttls: h("input", { type: "checkbox", checked: em.starttls !== false }) };
    const out = h("div", { class: "small" });
    body.append(h("div", { class: "card" }, h("h2", {}, "通知先"), h("p", { class: "small muted" }, "特許の期限（目安）の事前通知と、ウォッチの新しい候補を送ります。同じ内容は一度だけ送ります。"),
      field("Webhook", hooks), field("期限の何日前に通知（カンマ区切り）", days),
      h("h3", {}, "メール（SMTP・任意）"), h("label", {}, e.enabled, " 有効"), h("div", { class: "row" }, field("サーバー", e.host), field("ポート", e.port), h("label", {}, e.starttls, " STARTTLS")),
      h("div", { class: "row" }, field("ユーザー", e.user), field("差出人", e.from), field("宛先", e.to)), h("p", { class: "small muted" }, "SMTP パスワードは 外部キー の「SMTP パスワード」に保存します。"),
      h("div", { class: "row" }, h("button", { class: "btn primary", onclick: guard(async () => {
        const webhooks = hooks.value.split("\n").map(l => l.trim()).filter(Boolean).map(l => { const [kind, url, ...rest] = l.split(/\s+/); return { kind, url, label: rest.join(" ") }; });
        await api("PUT", "/api/settings", { notify: { webhooks, deadline_days: days.value.split(",").map(x => +x.trim()).filter(x => x > 0),
          email: { enabled: e.enabled.checked, host: e.host.value, port: +e.port.value, user: e.user.value, from: e.from.value, to: e.to.value, starttls: e.starttls.checked } } }); toast("保存しました"); }) }, "保存"),
        h("button", { class: "btn", onclick: guard(async () => { const r = await api("POST", "/api/notify/test", {}); out.textContent = JSON.stringify(r.results); }) }, "テスト送信"),
        h("button", { class: "btn", onclick: guard(async () => { const r = await api("POST", "/api/notify/deadlines", {}); toast(r.sent + " 件送信"); }) }, "期限通知を今すぐ確認")), out));
  } else if (tab === "backend") {
    const b = await api("GET", "/api/vectors/backend"); const vb = b.backend || {};
    const type = sel([["memory", "RAM（既定・依存なし）"], ["qdrant", "Qdrant（Container Station 等）"]], vb.type || "memory"), url = h("input", { class: "wide", value: vb.url || "" }), coll = h("input", { value: vb.collection || "qnaplibrary" });
    body.append(h("div", { class: "card" }, h("h2", {}, "ベクトル検索の基盤"), h("p", { class: "small muted" }, "ベクトルが 10 万件を超えるまでは RAM で十分です。Qdrant を使う場合も SQLite が正本で、Qdrant は検索用の複製です（障害時は RAM に自動で戻ります）。"),
      field("方式", type), field("Qdrant URL", url), field("Qdrant コレクション名", coll), h("p", { class: "small muted" }, "API キーが必要な場合は 外部キー に「Qdrant API キー」を保存。"),
      h("div", { class: "row" }, h("button", { class: "btn primary", onclick: guard(async () => { await api("PUT", "/api/settings", { vector_backend: { type: type.value, url: url.value, collection: coll.value } }); toast("保存しました"); render(); }) }, "保存"),
        h("button", { class: "btn", disabled: vb.type !== "qdrant", onclick: guard(async () => { await api("POST", "/api/vectors/sync", { recreate: true }); toast("同期を開始しました"); }) }, "SQLite → Qdrant 全同期")),
      h("div", { class: "pre" }, JSON.stringify({ qdrant: b.qdrant, sync: b.sync, ram: b.ram }, null, 1))));
  } else if (tab === "backups") {
    const data = await api("GET", "/api/backups");
    const items = data.snapshots || [];
    body.append(h("div", { class: "card" }, h("h2", {}, "データベースのスナップショット"),
      h("p", { class: "small muted" }, "手動でのみ実行します。SQLite の一貫した複製を NAS のデータフォルダ内 backups/ に保存します。作成中は書き込みが一時的に待機する場合があります。"),
      h("p", { class: "small muted" }, "対象は library.sqlite3 のみ。settings.json・secrets.json は含まれないため、データフォルダ全体を HBS3 等でも別の場所へバックアップしてください。復元はアプリ停止後に手動で行います。"),
      h("div", { class: "row" }, h("button", { class: "btn primary", onclick: guard(async (e) => {
        if (!confirm("SQLite スナップショットを作成しますか？バックアップ中は書き込みが一時的に待機する場合があります。")) return;
        e.target.disabled = true;
        try { const r = await api("POST", "/api/backups", {}); toast("作成しました: " + r.snapshot.name); await render(); }
        finally { e.target.disabled = false; }
      }) }, "今すぐバックアップを作成")),
      items.length ? h("table", {}, h("tr", {}, h("th", {}, "作成日時"), h("th", {}, "ファイル"), h("th", {}, "容量")),
        items.map(x => h("tr", {}, h("td", {}, fmtDate(x.created)), h("td", {}, h("code", {}, x.path)),
          h("td", {}, (x.bytes / 1048576).toFixed(1) + " MiB")))) : h("p", { class: "small muted" }, "バックアップはまだありません。")));
  } else if (tab === "update") {
    const u = await api("GET", "/api/update/status"), s = (await api("GET", "/api/settings")).settings;
    const auto = h("input", { type: "checkbox", checked: s.update.auto_apply }), check = h("input", { type: "checkbox", checked: s.update.auto_check });
    body.append(h("div", { class: "card" }, h("dl", { class: "dl" }, h("dt", {}, "現在"), h("dd", {}, "v" + u.current + "（" + u.mode + "）"), h("dt", {}, "状態"), h("dd", {}, u.phase + " " + (u.message || "")),
      h("dt", {}, "最新"), h("dd", {}, u.latest ? "v" + u.latest.version + "（" + (u.latest.published_at || "") + "）" : "-"), h("dt", {}, "確認日時"), h("dd", {}, fmtDate(u.checked_at)), u.error ? [h("dt", {}, "エラー"), h("dd", {}, u.error)] : null),
      u.latest && u.latest.notes ? h("details", {}, h("summary", {}, "リリースノート"), md(u.latest.notes)) : null,
      h("div", { class: "row" }, h("button", { class: "btn", onclick: guard(async () => { await api("POST", "/api/update/check", {}); render(); }) }, "更新を確認"),
        h("button", { class: "btn primary", disabled: !u.latest || u.mode === "dev", onclick: guard(async () => { if (!confirm("v" + u.latest.version + " に更新します。再起動します。")) return; await api("POST", "/api/update/apply", {}); toast("更新を開始しました"); waitRestart(u.current); }) }, "今すぐ更新")),
      h("label", {}, check, " 毎日自動で確認"), " ", h("label", {}, auto, " 新しい版を自動で適用"),
      h("button", { class: "btn", onclick: guard(async () => { await api("PUT", "/api/settings", { update: { auto_check: check.checked, auto_apply: auto.checked } }); toast("保存しました"); }) }, "保存"),
      h("p", { class: "small muted" }, "GitHub Releases（souten-yd/QnapLibrary）の資産を SHA-256 で検証してから適用します。")));
  } else if (tab === "debug") {
    const pre = h("div", { class: "pre" }, "…");
    body.append(h("div", { class: "card" }, h("p", { class: "small muted" }, "AI に不具合調査を依頼するときは、このバンドルを渡してください（秘密情報は除去済み）。デバイストークンがあれば GET /api/debug/bundle や MCP の debug_bundle でも取得できます。"),
      h("div", { class: "row" }, h("button", { class: "btn primary", onclick: guard(async () => { const b = await api("GET", "/api/debug/bundle"); download("qnaplibrary-debug-" + Date.now() + ".json", JSON.stringify(b, null, 1)); }) }, "デバッグバンドルをダウンロード"),
        h("button", { class: "btn", onclick: guard(async () => { const b = await api("GET", "/api/debug/bundle"); navigator.clipboard.writeText(JSON.stringify(b)); toast("コピーしました"); }) }, "コピー")), pre));
    const b = await api("GET", "/api/debug/bundle");
    pre.textContent = JSON.stringify({ errors: b.errors.slice(-20), slow: b.slow, searches: b.searches.slice(-10), store: b.store, update: b.update }, null, 1);
  }
}
function httpsCard() {
  const cmd = "tailscale serve --bg --https=8443 http://127.0.0.1:" + (location.port || "17871");
  return h("div", { class: "card" }, h("h2", {}, "HTTPS（Tailscale Serve）"),
    h("p", {}, "現在: ", h("span", { class: "tag " + (S.meInfo.https ? "ok" : "warn") }, S.meInfo.https ? "HTTPS" : "HTTP"), " ", S.meInfo.https_url ? h("a", { href: S.meInfo.https_url }, S.meInfo.https_url) : null),
    h("ol", { class: "small" }, h("li", {}, "Tailscale 管理画面で MagicDNS と HTTPS 証明書を有効にする"),
      h("li", {}, "NAS に SSH で入り次を実行（証明書の取得・更新は Tailscale が自動で行います）"),
      h("li", {}, "https://<NAS名>.<tailnet名>.ts.net:8443/ を開き、パスワードでログインしてからパスキーを登録")),
    h("div", { class: "row" }, h("code", {}, cmd), h("button", { class: "btn", onclick: () => { navigator.clipboard.writeText(cmd); toast("コピーしました"); } }, "コピー")),
    h("p", { class: "small muted" }, "QnapDownloader が 443（https://<NAS名>.ts.net/）を使っているため、QnapLibrary は 8443 を使います。同じ証明書・同じ名前で共存でき、ログイン Cookie の名前も別なので干渉しません。HTTP（LAN の :" + (location.port || "17871") + "）も引き続き使えます。"));
}
function waitRestart(prev) {
  let n = 0; const t = setInterval(async () => { n++; try { const hh = await fetch("/api/health").then(r => r.json()); if (hh.version !== prev) { clearInterval(t); toast("v" + hh.version + " に更新されました"); setTimeout(() => location.reload(), 800); } } catch (e) {} if (n > 120) clearInterval(t); }, 3000);
}
async function aiSettings(body) {
  const cfg = await api("GET", "/api/llm/providers");
  const provs = cfg.providers;
  const def = sel(provs.map(p => [p.id, p.label || p.id]), cfg.default_provider);
  const cards = provs.map(p => providerCard(p));
  const emb = cfg.embedding || {};
  const eProv = sel([["", "（使わない）"]].concat(provs.map(p => [p.id, p.label || p.id])), emb.provider || ""), eModel = h("input", { value: emb.model || "", list: "emb-models", placeholder: "例: qwen/qwen3-embedding-8b / openai/text-embedding-3-small" }),
    eDim = h("input", { type: "number", value: emb.dimensions || "" }), eTrunc = h("input", { type: "number", value: emb.truncate_dim || "" }), eAuto = h("input", { type: "checkbox", checked: emb.auto !== false }),
    eList = h("datalist", { id: "emb-models" }), eStat = h("div", { class: "small muted" }), eQ = h("input", { value: emb.query_prefix || "", placeholder: "例: query: " }), eD = h("input", { value: emb.doc_prefix || "", placeholder: "例: passage: " }), topk = h("input", { type: "number", value: cfg.rag_top_k || 8 });
  body.append(h("div", { class: "card" }, field("既定のプロバイダ", def), field("RAG で渡す根拠数", topk)), ...cards.map(c => c.el),
    h("div", { class: "card" }, h("h2", {}, "埋め込み（ベクトル検索・任意）"), h("p", { class: "small muted" }, "既定は OpenRouter の qwen/qwen3-embedding-8b（多言語・低価格）。OpenRouter の API キーを登録すると、取り込んだ文書を自動でベクトル化します（NAS では計算しません）。別PCの Ollama なども選べます。未設定でも全文検索で動作します。"),
      eStat, field("プロバイダ", eProv), field("モデル", eModel), eList,
      h("div", { class: "row" }, field("次元を切り詰め（RAM節約, 推奨1024）", eTrunc), field("APIに渡す dimensions（任意）", eDim)),
      field("クエリ接頭辞", eQ), field("文書接頭辞", eD), h("label", {}, eAuto, " 取り込み時に自動でベクトル化"),
      h("div", { class: "row" }, h("button", { class: "btn", onclick: guard(async () => { const r = await api("GET", "/api/llm/embedding-models?provider=" + encodeURIComponent(eProv.value)); clear(eList).append(...r.models.map(m => h("option", { value: m.id }, m.name + (m.price ? " $" + m.price : "")))); toast(r.models.length + " モデル"); }) }, "モデル一覧を取得"),
        h("button", { class: "btn", onclick: guard(async () => { await api("POST", "/api/llm/embedding/run", {}); toast("ベクトル化を開始しました"); }) }, "未処理を今すぐベクトル化"))),
    rerankCard(cfg, provs),
    jsonEditor(provs, def),
    h("div", { class: "card row" }, h("span", { class: "spacer" }), h("button", { class: "btn primary", onclick: guard(async () => {
        await api("PUT", "/api/llm/providers", { providers: cards.map(c => c.value()), default_provider: def.value, rag_top_k: +topk.value,
          embedding: { provider: eProv.value, model: eModel.value, dimensions: eDim.value ? +eDim.value : null, truncate_dim: eTrunc.value ? +eTrunc.value : null, auto: eAuto.checked, query_prefix: eQ.value, doc_prefix: eD.value, batch: 32 } }); toast("保存しました"); render(); }) }, "すべて保存")));
  embedStatus(eStat);
}
async function embedStatus(el) {
  try { const r = await api("GET", "/api/llm/embedding"); const st = r.status;
    clear(el).append(h("span", { class: "tag " + (st.enabled ? "ok" : "warn") }, st.enabled ? "有効" : "無効（キー未設定など）"), " 未処理 ", String(st.pending ?? "-"), " / 実行中 ", st.running ? "はい" : "いいえ",
      st.last_error ? h("div", { class: "tag bad" }, st.last_error) : null, r.vector_models.length ? h("div", {}, "保存済み: " + r.vector_models.map(m => m.model + " (" + m.dim + "次元×" + m.n + ")").join(", ")) : null);
  } catch (e) { el.textContent = e.message; }
}
function rerankCard(cfg, provs) {
  const r = cfg.rerank || {};
  const en = h("input", { type: "checkbox", checked: r.enabled }), pv = sel(provs.map(p => [p.id, p.label || p.id]), r.provider || "openrouter"),
    md_ = h("input", { value: r.model || "", placeholder: "例: qwen/qwen3-reranker-8b / jina-reranker-v2 / bge-reranker-v2-m3" }), top = h("input", { type: "number", value: r.top_n || 30 });
  const save = guard(async () => { await api("PUT", "/api/llm/providers", { providers: provs.map(({ secret_status, ...x }) => x), rerank: { enabled: en.checked, provider: pv.value, model: md_.value, top_n: +top.value } }); toast("保存しました"); });
  return h("div", { class: "card" }, h("h2", {}, "リランカー（任意）"), h("p", { class: "small muted" }, "検索の上位候補を /rerank 対応 API（Cohere/Jina 形式）で並べ替えて精度を上げます。失敗時は元の順位のまま返します。"),
    h("label", {}, en, " 有効"), h("div", { class: "row" }, field("プロバイダ", pv), field("モデル", md_), field("対象件数", top)), h("button", { class: "btn", onclick: save }, "リランカー設定を保存"));
}
function jsonEditor(provs, def) {
  const clean = provs.map(({ secret_status, ...rest }) => rest);
  const ta = h("textarea", { value: JSON.stringify(clean, null, 1) }); ta.style.minHeight = "220px";
  return h("details", { class: "card" }, h("summary", {}, "プロバイダを JSON で編集（追加・削除）"),
    h("p", { class: "small muted" }, 'type は "openai"（OpenAI互換: QnapAssistant・Ollama・llama.cpp・vLLM 等）か "openrouter"。secret は 外部キー の名前。'), ta,
    h("div", { class: "row end" }, h("button", { class: "btn", onclick: guard(async () => { await api("PUT", "/api/llm/providers", { providers: JSON.parse(ta.value), default_provider: def.value }); toast("保存しました"); render(); }) }, "JSON を保存")));
}
function providerCard(p) {
  const o = p.options || {}, pr = o.provider || {}, rs = o.reasoning || {};
  const f = { label: h("input", { value: p.label || "" }), base_url: h("input", { class: "wide", value: p.base_url || "" }), model: h("input", { class: "wide", value: p.model || "", list: "models-" + p.id }), secret: h("input", { value: p.secret || "", placeholder: "secrets 名（例: openrouter_api_key）" }) };
  const num = (v) => h("input", { type: "number", step: "any", value: v ?? "" });
  const opt = { temperature: num(o.temperature), top_p: num(o.top_p), max_tokens: num(o.max_tokens) };
  const orf = p.type === "openrouter" ? {
    fallback: h("input", { class: "wide", value: (o.fallback_models || []).join(", "), placeholder: "例: anthropic/claude-sonnet-4.5, google/gemini-2.5-flash" }),
    sort: sel([["", "既定（負荷分散）"], ["price", "価格優先"], ["throughput", "スループット優先"], ["latency", "レイテンシ優先"]], pr.sort || ""),
    order: h("input", { value: (pr.order || []).join(", "), placeholder: "優先プロバイダ順" }), only: h("input", { value: (pr.only || []).join(", ") }), ignore: h("input", { value: (pr.ignore || []).join(", ") }),
    allow_fallbacks: sel([["", "既定"], ["true", "許可"], ["false", "禁止"]], pr.allow_fallbacks === undefined ? "" : String(pr.allow_fallbacks)),
    data_collection: sel([["", "既定"], ["allow", "allow"], ["deny", "deny（学習利用しない）"]], pr.data_collection || ""), zdr: h("input", { type: "checkbox", checked: pr.zdr }),
    require_parameters: h("input", { type: "checkbox", checked: pr.require_parameters }), quantizations: h("input", { value: (pr.quantizations || []).join(", "), placeholder: "例: fp8, bf16" }),
    max_prompt: num(pr.max_price && pr.max_price.prompt), max_completion: num(pr.max_price && pr.max_price.completion),
    effort: sel([["", "なし"], ["minimal", "minimal"], ["low", "low"], ["medium", "medium"], ["high", "high"]], rs.effort || ""), rmax: num(rs.max_tokens), rexclude: h("input", { type: "checkbox", checked: rs.exclude }),
    web: h("input", { type: "checkbox", checked: o.web_search }),
  } : null;
  const list = h("datalist", { id: "models-" + p.id });
  const testOut = h("span", { class: "small muted" });
  const split = (s) => s.split(",").map(x => x.trim()).filter(Boolean);
  const el = h("div", { class: "card" }, h("div", { class: "row" }, h("h2", {}, p.label || p.id), h("span", { class: "tag" }, p.type), p.secret_status ? h("span", { class: "tag " + (p.secret_status.configured ? "ok" : "warn") }, p.secret_status.configured ? "キー設定済" : "キー未設定") : null),
    field("表示名", f.label), field("Base URL（OpenAI互換 /v1）", f.base_url), field("モデル", f.model), list, field("APIキーの secrets 名（外部キーで値を設定）", f.secret),
    h("div", { class: "row" }, field("temperature", opt.temperature), field("top_p", opt.top_p), field("max_tokens", opt.max_tokens)),
    orf ? h("details", {}, h("summary", {}, "OpenRouter 詳細設定（ルーティング・推論・価格上限）"), field("フォールバックモデル（順に試行）", orf.fallback),
      h("div", { class: "row" }, field("プロバイダ並び替え", orf.sort), field("フォールバック", orf.allow_fallbacks), field("データ収集", orf.data_collection)),
      h("div", { class: "row" }, field("order", orf.order), field("only", orf.only), field("ignore", orf.ignore), field("quantizations", orf.quantizations)),
      h("div", { class: "row" }, field("最大価格 prompt ($/1M)", orf.max_prompt), field("最大価格 completion ($/1M)", orf.max_completion)),
      h("div", { class: "row" }, h("label", {}, orf.zdr, " ZDR（ゼロデータ保持）のみ"), h("label", {}, orf.require_parameters, " 全パラメータ対応プロバイダのみ"), h("label", {}, orf.web, " Web 検索プラグイン")),
      h("div", { class: "row" }, field("推論 effort", orf.effort), field("推論 max_tokens", orf.rmax), h("label", {}, orf.rexclude, " 推論過程を返さない"))) : null,
    h("div", { class: "row" }, h("button", { class: "btn", onclick: guard(async () => { const r = await api("GET", "/api/llm/models?provider=" + encodeURIComponent(p.id)); clear(list).append(...r.models.map(m => h("option", { value: m.id }, m.name + (m.free ? " (free)" : "")))); toast(r.models.length + " モデル（モデル欄で候補表示）"); }) }, "モデル一覧を取得"),
      h("button", { class: "btn", onclick: guard(async () => { testOut.textContent = "テスト中…"; try { const r = await api("POST", "/api/llm/test", { provider: p.id }); testOut.textContent = "OK: " + r.model + " " + r.ms + "ms 「" + r.content.slice(0, 20) + "」"; } catch (e) { testOut.textContent = e.message; } }) }, "接続テスト（保存後）"), testOut));
  const value = () => {
    const n = (i) => i.value === "" ? null : +i.value;
    const out = { id: p.id, type: p.type, label: f.label.value, base_url: f.base_url.value, model: f.model.value, secret: f.secret.value, options: { ...(p.options || {}), temperature: n(opt.temperature), top_p: n(opt.top_p), max_tokens: n(opt.max_tokens) } };
    if (orf) {
      const prov = { sort: orf.sort.value || null, order: split(orf.order.value), only: split(orf.only.value), ignore: split(orf.ignore.value), quantizations: split(orf.quantizations.value),
        data_collection: orf.data_collection.value || null, zdr: orf.zdr.checked || null, require_parameters: orf.require_parameters.checked || null,
        allow_fallbacks: orf.allow_fallbacks.value === "" ? null : orf.allow_fallbacks.value === "true" };
      if (orf.max_prompt.value || orf.max_completion.value) prov.max_price = { prompt: n(orf.max_prompt), completion: n(orf.max_completion) };
      Object.assign(out.options, { fallback_models: split(orf.fallback.value), provider: prov, web_search: orf.web.checked,
        reasoning: { effort: orf.effort.value || null, max_tokens: n(orf.rmax), exclude: orf.rexclude.checked || null } });
    }
    return out;
  };
  return { el, value };
}

boot().catch(e => { $app.textContent = "起動に失敗しました: " + e.message; });
})();
