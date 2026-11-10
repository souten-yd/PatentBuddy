"""REST API routes.

Access levels: public | read (admin or any device) | user (admin or read-write device) | admin.
Machine clients use `Authorization: Bearer qlt_...` obtained via /api/v1/pair.
"""
import csv
import io
import json
import re
import time

from . import VERSION, connectors, debuglog, mcp, patents as patents_mod, store as store_mod, webauthn
from .auth import is_local_network
from .llm import LLMError

ROUTES = []
SECRET_NAMES = ("openrouter_api_key", "epo_ops_key", "epo_ops_secret", "jpo_username", "jpo_password",
                "uspto_api_key", "openai_api_key")


def route(method, pattern, auth="admin"):
    regex = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern) + "$")

    def deco(fn):
        ROUTES.append({"method": method, "pattern": pattern, "regex": regex, "auth": auth, "fn": fn})
        return fn
    return deco


def match(method, path):
    for r in ROUTES:
        if r["method"] == method:
            m = r["regex"].match(path)
            if m:
                return r, m.groupdict()
    return None, {}


def _err(status, message):
    from .server import HTTPError
    return HTTPError(status, message)


# ---------------------------------------------------------------------------
# health / auth
@route("GET", "/api/health", "public")
def health(req):
    a = req.app
    return {"app": "QnapLibrary", "version": VERSION, "ok": True, "setup_required": not a.auth.admin_configured(),
            "pairing": a.auth.pairing_enabled(), "https": req.is_https(), "https_url": a.config.get("server", "https_url", default=""), "uptime_s": round(time.time() - a.started)}


@route("GET", "/api/auth/me", "public")
def me(req):
    return {"authenticated": req.actor is not None, "actor": req.actor,
            "csrf": req.session["csrf"] if req.session else None,
            "setup_required": not req.app.auth.admin_configured(),
            "passkeys": req.app.store.one("SELECT COUNT(*) FROM passkeys")[0],
            "https": req.is_https(), "https_url": req.app.config.get("server", "https_url", default=""),
            "passkey_ready": _passkey_host_ok(req)}


def _passkey_host_ok(req):
    host = req.rp_id()
    return req.is_https() and "." in host and not re.fullmatch(r"[0-9.]+|\[?[0-9a-f:]+\]?", host)


def _login_response(req, via):
    sid, session = req.app.auth.sessions.create(via)
    secure = "; Secure" if req.is_https() else ""
    if req.is_https() and _passkey_host_ok(req):
        url = req.origin()
        if req.app.config.get("server", "https_url") != url:  # remember once (written only on change)
            req.app.config.update({"server": {"https_url": url}})
    cookie = "ql_session=%s; Path=/; HttpOnly; SameSite=Strict%s; Max-Age=%d" % (sid, secure, req.app.auth.sessions.ttl)
    req.app.store.audit("admin", "login", via + " " + req.ip)
    return req.h.send_json(200, {"ok": True, "csrf": session["csrf"]}, {"Set-Cookie": cookie})


@route("POST", "/api/auth/setup", "public")
def setup(req):
    a = req.app.auth
    if a.admin_configured():
        raise _err(409, "管理者は設定済みです")
    if not is_local_network(req.ip):
        raise _err(403, "初期設定は LAN からのみ行えます")
    a.set_admin_password(req.json().get("password", ""))
    return _login_response(req, "setup")


@route("POST", "/api/auth/login", "public")
def login(req):
    a = req.app.auth
    key = "login:" + req.ip
    if a.limiter.blocked(key):
        raise _err(429, "試行回数が多すぎます。10分後に再試行してください")
    if not a.check_admin_password(req.json().get("password", "")):
        a.limiter.fail(key)
        raise _err(401, "パスワードが違います")
    a.limiter.reset(key)
    return _login_response(req, "password")


@route("POST", "/api/auth/logout", "admin")
def logout(req):
    req.app.auth.sessions.drop(req.session_id)
    return req.h.send_json(200, {"ok": True}, {"Set-Cookie": "ql_session=; Path=/; Max-Age=0"})


@route("POST", "/api/auth/password", "admin")
def change_password(req):
    body = req.json()
    if not req.app.auth.check_admin_password(body.get("current", "")):
        raise _err(401, "現在のパスワードが違います")
    req.app.auth.set_admin_password(body.get("password", ""))
    return {"ok": True}


# passkeys (Face ID / Windows Hello) -----------------------------------------
def _passkey_rows(app):
    return app.store.q("SELECT credential_id, name, created, last_used, public_key, alg, sign_count FROM passkeys")


@route("POST", "/api/auth/passkey/register/options", "admin")
def passkey_register_options(req):
    app = req.app
    if not _passkey_host_ok(req):
        raise _err(400, "パスキーは https://<名前>（例: Tailscale の *.ts.net）で開いたときだけ登録できます")
    rp_id, origin = req.rp_id(), req.origin()
    challenge = app.challenges.issue("create", req.session["hash"], rp_id, origin)
    handle = app.config.secret("passkey_user_handle")
    if not handle:
        import secrets as _s
        handle = webauthn.b64url_encode(_s.token_bytes(16))
        app.config.set_secret("passkey_user_handle", handle)
    return {"publicKey": {
        "challenge": challenge, "rp": {"id": rp_id, "name": "QnapLibrary"},
        "user": {"id": handle, "name": "admin", "displayName": "QnapLibrary 管理者"},
        "pubKeyCredParams": [{"type": "public-key", "alg": webauthn.ALG_ES256}, {"type": "public-key", "alg": webauthn.ALG_RS256}],
        "timeout": 120000, "attestation": "none",
        "authenticatorSelection": {"residentKey": "preferred", "userVerification": "required"},
        "excludeCredentials": [{"type": "public-key", "id": webauthn.b64url_encode(r["credential_id"])} for r in _passkey_rows(app)]}}


@route("POST", "/api/auth/passkey/register/verify", "admin")
def passkey_register_verify(req):
    body = req.json()
    raw_id = webauthn.b64url_decode(str(body.get("id", "")), webauthn.CREDENTIAL_ID_MAX)
    client_data = webauthn.b64url_decode(str(body.get("clientDataJSON", "")), 4096)
    attestation = webauthn.b64url_decode(str(body.get("attestationObject", "")), 8192)
    try:
        result = webauthn.verify_registration(req.app.challenges, req.session["hash"], req.rp_id(), req.origin(),
                                              client_data, attestation, raw_id)
    except webauthn.WebAuthnError as error:
        raise _err(400, str(error))
    name = str(body.get("name") or "パスキー")[:60]
    with req.app.store.lock:
        req.app.store.db.execute("INSERT OR REPLACE INTO passkeys(credential_id,public_key,alg,sign_count,name,created) VALUES(?,?,?,?,?,?)",
                                 (result["credential_id"], result["public_key"], result["alg"], result["sign_count"], name, time.time()))
    req.app.store.audit("admin", "passkey.register", name)
    return {"ok": True}


@route("POST", "/api/auth/passkey/login/options", "public")
def passkey_login_options(req):
    app = req.app
    if not _passkey_host_ok(req):
        raise _err(400, "パスキーは https の名前付きアドレスで開いたときだけ使えます")
    rows = _passkey_rows(app)
    if not rows:
        raise _err(404, "パスキーが登録されていません")
    import secrets as _s
    bind = _s.token_urlsafe(16)
    challenge = app.challenges.issue("get", bind, req.rp_id(), req.origin())
    return {"bind": bind, "publicKey": {"challenge": challenge, "rpId": req.rp_id(), "timeout": 120000,
                                        "userVerification": "required",
                                        "allowCredentials": [{"type": "public-key", "id": webauthn.b64url_encode(r["credential_id"])} for r in rows]}}


@route("POST", "/api/auth/passkey/login/verify", "public")
def passkey_login_verify(req):
    app = req.app
    key = "passkey:" + req.ip
    if app.auth.limiter.blocked(key):
        raise _err(429, "試行回数が多すぎます")
    body = req.json()
    try:
        raw_id = webauthn.b64url_decode(str(body.get("id", "")), webauthn.CREDENTIAL_ID_MAX)
        row = app.store.one("SELECT * FROM passkeys WHERE credential_id=?", (raw_id,))
        if not row:
            raise webauthn.WebAuthnError("このパスキーは登録されていません")
        count = webauthn.verify_assertion(
            app.challenges, str(body.get("bind", "")), req.rp_id(), req.origin(),
            {"public_key": row["public_key"], "sign_count": row["sign_count"]},
            webauthn.b64url_decode(str(body.get("clientDataJSON", "")), 4096),
            webauthn.b64url_decode(str(body.get("authenticatorData", "")), 4096),
            webauthn.b64url_decode(str(body.get("signature", "")), 1024))
    except webauthn.WebAuthnError as error:
        app.auth.limiter.fail(key)
        raise _err(401, str(error))
    with app.store.lock:
        app.store.db.execute("UPDATE passkeys SET sign_count=?, last_used=? WHERE credential_id=?", (count, time.time(), raw_id))
    return _login_response(req, "passkey")


@route("GET", "/api/auth/passkeys", "admin")
def passkeys_list(req):
    return [{"id": webauthn.b64url_encode(r["credential_id"]), "name": r["name"], "created": r["created"],
             "last_used": r["last_used"]} for r in _passkey_rows(req.app)]


@route("DELETE", "/api/auth/passkeys/{cid}", "admin")
def passkeys_delete(req):
    raw = webauthn.b64url_decode(req.params["cid"], webauthn.CREDENTIAL_ID_MAX)
    with req.app.store.lock:
        n = req.app.store.db.execute("DELETE FROM passkeys WHERE credential_id=?", (raw,)).rowcount
    return {"deleted": n}


# devices / pairing ----------------------------------------------------------
@route("POST", "/api/v1/pair", "public")
def pair(req):
    a = req.app.auth
    if not is_local_network(req.ip, req.app.config.get("server", "trusted_networks", default=["tailscale"])):
        raise _err(403, "ペアリングは LAN / Tailscale からのみ可能です")
    if not a.pairing_enabled():
        raise _err(409, "管理Webでペアリング用パスコードを設定してください")
    key = "pair:" + req.ip
    if a.limiter.blocked(key):
        raise _err(429, "試行回数が多すぎます")
    body = req.json()
    if not a.check_passcode(body.get("passcode", "")):
        a.limiter.fail(key)
        raise _err(401, "パスコードが違います")
    a.limiter.reset(key)
    dev = a.create_device(body.get("name") or ("device@" + req.ip), body.get("scopes", "rw"))
    req.app.store.audit("pair", "device.create", "%s %s" % (dev["name"], req.ip))
    return dict(dev, usage="Authorization: Bearer <token> を付けて /api/v1/* と /mcp を呼び出してください")


@route("GET", "/api/devices", "admin")
def devices(req):
    return {"devices": req.app.auth.list_devices(), "pairing_enabled": req.app.auth.pairing_enabled()}


@route("POST", "/api/devices", "admin")
def device_create(req):
    body = req.json()
    return req.app.auth.create_device(body.get("name"), body.get("scopes", "rw"))


@route("DELETE", "/api/devices/{id}", "admin")
def device_delete(req):
    return {"deleted": req.app.auth.delete_device(req.params["id"])}


@route("PUT", "/api/devices/pairing", "admin")
def pairing_set(req):
    req.app.auth.set_pairing_passcode(req.json().get("passcode", ""))
    return {"pairing_enabled": req.app.auth.pairing_enabled()}


# ---------------------------------------------------------------------------
# settings / secrets
@route("GET", "/api/settings", "admin")
def settings_get(req):
    return {"settings": req.app.config.all(),
            "secrets": {k: req.app.config.secret_status(k) for k in SECRET_NAMES}}


@route("PUT", "/api/settings", "admin")
def settings_put(req):
    patch = req.json()
    allowed = {"server", "auth", "update", "search", "connectors"}
    bad = set(patch) - allowed
    if bad:
        raise _err(400, "変更できない項目: %s（LLMは /api/llm/providers）" % ", ".join(sorted(bad)))
    return {"settings": req.app.config.update(patch), "note": "server.* の変更は再起動後に有効"}


@route("PUT", "/api/secrets/{name}", "admin")
def secret_put(req):
    name = req.params["name"]
    if name not in SECRET_NAMES:
        raise _err(400, "unknown secret")
    value = req.json().get("value")
    if value is not None and (not isinstance(value, str) or len(value) > 4096):
        raise _err(400, "invalid value")
    req.app.config.set_secret(name, (value or "").strip())
    req.app.store.audit("admin", "secret.set", name)
    req.app.embedder.kick()
    return req.app.config.secret_status(name)


# ---------------------------------------------------------------------------
# collections / documents
@route("GET", "/api/v1/collections", "read")
def collections_list(req):
    return {"collections": req.app.store.list_collections(), "kinds": list(store_mod.KINDS)}


@route("POST", "/api/v1/collections", "user")
def collections_create(req):
    b = req.json()
    return req.app.store.create_collection(b.get("name"), b.get("kind", "generic"), b.get("description", ""), b.get("settings"))


@route("GET", "/api/v1/collections/{cid}", "read")
def collection_get(req):
    return req.app.store.get_collection(req.params["cid"])


@route("PATCH", "/api/v1/collections/{cid}", "user")
def collection_patch(req):
    return req.app.store.update_collection(req.params["cid"], req.json())


@route("DELETE", "/api/v1/collections/{cid}", "admin")
def collection_delete(req):
    c = req.app.store.delete_collection(req.params["cid"])
    req.app.store.audit(req.actor, "collection.delete", c["name"])
    return {"deleted": c["name"]}


@route("GET", "/api/v1/collections/{cid}/documents", "read")
def documents_list(req):
    return req.app.store.list_documents(req.params["cid"], int(req.arg("offset", 0)), int(req.arg("limit", 50)), req.arg("q", ""))


@route("POST", "/api/v1/collections/{cid}/documents", "user")
def documents_add(req):
    body = req.json(limit=96 * 1024 * 1024)
    docs = body.get("documents") if isinstance(body, dict) else body
    return req.app.store.add_documents(req.params["cid"], docs, actor=req.actor)


def parse_import(fmt, data):
    if fmt == "ndjson":
        return [json.loads(line) for line in data.splitlines() if line.strip()]
    if fmt == "json":
        v = json.loads(data)
        return v.get("documents", v) if isinstance(v, dict) else v
    if fmt == "csv":
        docs = []
        for row in csv.DictReader(io.StringIO(data)):
            known = {k: row.pop(k, "") for k in ("id", "title", "body", "url", "date", "source", "abstract")}
            known["meta"] = {k: v for k, v in row.items() if k and v}
            docs.append(known)
        return docs
    if fmt == "text":
        return [{"title": data.strip().splitlines()[0][:200] if data.strip() else "text", "body": data}]
    raise ValueError("format must be ndjson/json/csv/text")


@route("POST", "/api/v1/collections/{cid}/import", "user")
def documents_import(req):
    body = req.json(limit=96 * 1024 * 1024)
    docs = parse_import(body.get("format", "ndjson"), body.get("data", ""))
    total = {"added": 0, "updated": 0, "unchanged": 0}
    for i in range(0, len(docs), 2000):
        r = req.app.store.add_documents(req.params["cid"], docs[i:i + 2000], actor=req.actor)
        for k in total:
            total[k] += r[k]
    return total


@route("GET", "/api/v1/collections/{cid}/export", "read")
def documents_export(req):
    c = req.app.store.get_collection(req.params["cid"])
    req.h.start_stream("application/x-ndjson")
    for d in req.app.store.iter_documents(c["id"]):
        req.h.wfile.write((json.dumps(d, ensure_ascii=False) + "\n").encode("utf-8"))
    return 200


@route("GET", "/api/v1/documents/{did}", "read")
def document_get(req):
    return req.app.store.get_document(req.params["did"], with_chunks=req.arg("chunks") == "1")


@route("DELETE", "/api/v1/documents/{did}", "user")
def document_delete(req):
    return {"deleted": req.app.store.delete_document(int(req.params["did"]))}


# vectors ---------------------------------------------------------------------
@route("POST", "/api/v1/vectors", "user")
def vectors_put(req):
    """Push embeddings computed elsewhere: {model, items:[{chunk_id, vector}]}."""
    b = req.json(limit=96 * 1024 * 1024)
    items = [(i["chunk_id"], i["vector"]) for i in b.get("items", [])]
    return {"stored": req.app.store.put_vectors(items, str(b.get("model") or "external"))}


@route("GET", "/api/v1/collections/{cid}/pending-chunks", "read")
def vectors_pending(req):
    """Chunks that still need an embedding (for an external embedding worker). ?model=<tag>"""
    c = req.app.store.get_collection(req.params["cid"])
    rows = req.app.store.chunks_missing_vectors(c["id"], min(int(req.arg("limit", 256)), 2000), model=req.arg("model"))
    return {"chunks": [{"chunk_id": r["id"], "title": r["title"], "section": r["section"], "text": r["text"]} for r in rows]}


@route("POST", "/api/v1/collections/{cid}/embed", "user")
def vectors_embed(req):
    """Embed up to N missing chunks now with the configured embedding provider (bounded)."""
    c = req.app.store.get_collection(req.params["cid"])
    try:
        done = req.app.embedder.run_once(min(int(req.json().get("limit", 256)), 2000), c["id"])
    except LLMError as error:
        raise _err(502, str(error))
    more = bool(req.app.store.chunks_missing_vectors(c["id"], 1, model=req.app.providers.embedding_tag()))
    return {"embedded": done, "more": more}


@route("DELETE", "/api/v1/collections/{cid}/vectors", "admin")
def vectors_delete(req):
    """Delete vectors of a collection (e.g. after changing the embedding model)."""
    c = req.app.store.get_collection(req.params["cid"])
    return {"deleted": req.app.store.delete_vectors(c["id"])}


@route("GET", "/api/llm/embedding", "admin")
def embedding_status(req):
    return {"status": req.app.embedder.info(), "vector_models": req.app.store.vector_models()}


@route("POST", "/api/llm/embedding/run", "admin")
def embedding_run(req):
    req.app.embedder.kick()
    if not req.app.providers.embedding_enabled():
        raise _err(409, "埋め込みが無効です（プロバイダのキーを設定してください）")
    return req.app.embedder.info()


@route("GET", "/api/llm/embedding-models", "admin")
def embedding_models(req):
    try:
        return {"models": req.app.providers.embedding_models(req.arg("provider"))}
    except LLMError as error:
        raise _err(502, str(error))


# search ----------------------------------------------------------------------
@route("POST", "/api/v1/search", "read")
def search(req):
    b = req.json()
    q = str(b.get("q") or b.get("query") or "").strip()
    if not q:
        raise _err(400, "q が必要です")
    res = req.app.searcher.search(q, b.get("collections") or None, b.get("limit") or 20, b.get("mode") or "hybrid",
                                  b.get("group_by_doc", True), b.get("vector"))
    if not b.get("include_text"):
        for r in res["results"]:
            r.pop("text", None)
    return res


@route("GET", "/api/v1/stats", "read")
def stats(req):
    return {"store": req.app.store.stats(), "vectors": req.app.searcher.vectors.info(), "version": VERSION,
            "embedding": req.app.embedder.info()}


@route("GET", "/api/v1/schema", "read")
def schema(req):
    return {"version": VERSION, "routes": [{"method": r["method"], "path": r["pattern"], "auth": r["auth"],
                                            "doc": (r["fn"].__doc__ or "").strip().split("\n")[0]} for r in ROUTES],
            "mcp": {"endpoint": "/mcp", "tools": [t["name"] for t in mcp.TOOLS]},
            "document_format": {"id": "外部ID（同じIDは上書き）", "title": "str", "body": "本文", "abstract": "要約",
                                "sections": {"claims": "請求項（1項ずつ索引）", "description": "明細書"},
                                "url": "str", "date": "YYYY-MM-DD", "source": "str", "meta": "任意のJSON"}}


# ---------------------------------------------------------------------------
# patents
@route("GET", "/api/v1/patents/meta", "read")
def patents_meta(req):
    return {"stages": patents_mod.STAGES, "events": patents_mod.EVENT_KINDS, "ref_categories": patents_mod.REF_CATEGORIES,
            "tasks": {k: v["label"] for k, v in patents_mod.PROMPTS.items()}}


@route("GET", "/api/v1/patents", "read")
def patents_list(req):
    return {"projects": req.app.patents.list()}


@route("POST", "/api/v1/patents", "user")
def patents_create(req):
    b = req.json()
    return req.app.patents.create(b.get("title"), b.get("data"))


@route("GET", "/api/v1/patents/{pid}", "read")
def patents_get(req):
    return req.app.patents.get(req.params["pid"])


@route("PATCH", "/api/v1/patents/{pid}", "user")
def patents_patch(req):
    return req.app.patents.update(req.params["pid"], req.json())


@route("DELETE", "/api/v1/patents/{pid}", "admin")
def patents_delete(req):
    return {"deleted": req.app.patents.delete(req.params["pid"])}


@route("POST", "/api/v1/patents/{pid}/events", "user")
def patents_event(req):
    b = req.json()
    return req.app.patents.add_event(req.params["pid"], b.get("kind"), b.get("date"), b.get("note", ""))


@route("DELETE", "/api/v1/patents/{pid}/events/{eid}", "user")
def patents_event_delete(req):
    return req.app.patents.delete_event(req.params["pid"], req.params["eid"])


@route("POST", "/api/v1/patents/{pid}/claims", "user")
def patents_claims(req):
    b = req.json()
    return req.app.patents.save_claims(req.params["pid"], b.get("text", ""), b.get("note", ""))


@route("POST", "/api/v1/patents/{pid}/refs", "user")
def patents_ref(req):
    b = req.json()
    return req.app.patents.add_ref(req.params["pid"], b.get("ref", ""), b.get("doc_id"), b.get("category", "A"),
                                   b.get("relevance", ""), b.get("note", ""))


@route("DELETE", "/api/v1/patents/{pid}/refs/{rid}", "user")
def patents_ref_delete(req):
    return req.app.patents.delete_ref(req.params["pid"], req.params["rid"])


@route("POST", "/api/v1/patents/{pid}/chart", "read")
def patents_chart(req):
    b = req.json()
    return req.app.patents.claim_chart(req.params["pid"], b.get("collections") or None, b.get("claim_no", 1))


@route("POST", "/api/v1/patents/{pid}/assist", "user")
def patents_assist(req):
    b = req.json()
    try:
        return req.app.patents.assist(req.params["pid"], b.get("task"), b.get("collections") or None,
                                      b.get("provider"), b.get("extra", ""))
    except LLMError as error:
        raise _err(502, str(error))


@route("POST", "/api/v1/patents/parse-claims", "read")
def patents_parse(req):
    text = req.json().get("text", "")
    from .textproc import split_claims
    return {"claims": [{"no": n, "text": t, "elements": patents_mod.claim_elements(t)} for n, t in split_claims(text)]}


# ---------------------------------------------------------------------------
# LLM / chat
@route("GET", "/api/llm/providers", "admin")
def llm_providers(req):
    cfg = req.app.config.get("llm")
    return {"providers": req.app.providers.list(), "default_provider": cfg.get("default_provider"),
            "embedding": cfg.get("embedding"), "rag_top_k": cfg.get("rag_top_k")}


@route("PUT", "/api/llm/providers", "admin")
def llm_providers_put(req):
    b = req.json()
    try:
        req.app.providers.save(b.get("providers"), b.get("default_provider"))
    except LLMError as error:
        raise _err(400, str(error))
    if isinstance(b.get("embedding"), dict) or b.get("rag_top_k"):
        llm = req.app.config.get("llm")
        if isinstance(b.get("embedding"), dict):
            llm["embedding"] = b["embedding"]
        if b.get("rag_top_k"):
            llm["rag_top_k"] = max(1, min(int(b["rag_top_k"]), 30))
        req.app.config.replace_section("llm", llm)
    req.app.embedder.kick()
    return llm_providers(req)


@route("GET", "/api/llm/models", "admin")
def llm_models(req):
    try:
        return {"models": req.app.providers.models(req.arg("provider"))}
    except LLMError as error:
        raise _err(502, str(error))


@route("POST", "/api/llm/test", "admin")
def llm_test(req):
    b = req.json()
    try:
        r = req.app.providers.chat([{"role": "user", "content": "「OK」とだけ答えてください。"}], b.get("provider"),
                                   {"max_tokens": 16}, timeout=60)
    except LLMError as error:
        raise _err(502, str(error))
    return r


@route("GET", "/api/chat/threads", "admin")
def chat_threads(req):
    return {"threads": [dict(r) for r in req.app.store.q("SELECT id, title, created, updated FROM chat_threads ORDER BY updated DESC LIMIT 200")]}


@route("POST", "/api/chat/threads", "admin")
def chat_thread_create(req):
    b = req.json()
    t = time.time()
    with req.app.store.lock:
        cur = req.app.store.db.execute("INSERT INTO chat_threads(title,settings,created,updated) VALUES(?,?,?,?)",
                                       (str(b.get("title") or "新しいチャット")[:120], json.dumps(b.get("settings") or {}), t, t))
    return {"id": cur.lastrowid}


@route("GET", "/api/chat/threads/{tid}", "admin")
def chat_thread_get(req):
    tid = int(req.params["tid"])
    row = req.app.store.one("SELECT * FROM chat_threads WHERE id=?", (tid,))
    if not row:
        raise _err(404, "thread not found")
    msgs = [{"id": r["id"], "role": r["role"], "content": r["content"], "meta": json.loads(r["meta"] or "{}"), "created": r["created"]}
            for r in req.app.store.q("SELECT * FROM chat_messages WHERE thread_id=? ORDER BY id", (tid,))]
    return {"id": tid, "title": row["title"], "settings": json.loads(row["settings"] or "{}"), "messages": msgs}


@route("DELETE", "/api/chat/threads/{tid}", "admin")
def chat_thread_delete(req):
    with req.app.store.lock:
        req.app.store.db.execute("DELETE FROM chat_threads WHERE id=?", (int(req.params["tid"]),))
    return {"ok": True}


RAG_SYSTEM = ("あなたは QnapLibrary の調査アシスタントです。与えられた『参照資料』を優先して日本語で回答し、"
              "根拠となる資料を [番号] で示してください。資料に無いことは一般知識として区別して述べ、推測は推測と明記します。")


@route("POST", "/api/chat/threads/{tid}/messages", "admin")
def chat_send(req):
    """Send a user message; streams SSE events {delta}/{reasoning}/{sources}/{done}."""
    app = req.app
    tid = int(req.params["tid"])
    b = req.json()
    content = str(b.get("content") or "").strip()
    if not content:
        raise _err(400, "content が必要です")
    if not app.store.one("SELECT id FROM chat_threads WHERE id=?", (tid,)):
        raise _err(404, "thread not found")
    history = [{"role": r["role"], "content": r["content"]} for r in
               app.store.q("SELECT role, content FROM (SELECT id, role, content FROM chat_messages WHERE thread_id=? ORDER BY id DESC LIMIT 20) ORDER BY id", (tid,))]
    sources, context = [], ""
    rag = b.get("rag") or {}
    if rag.get("enabled", True):
        try:
            res = app.searcher.search(content, rag.get("collections") or None, app.config.get("llm", "rag_top_k", default=8))
            sources = res["results"]
            context = "\n\n".join("[%d] %s（%s %s）\n%s" % (i + 1, s["title"], s["collection"], s.get("ext_id") or "", s["text"][:1200])
                                  for i, s in enumerate(sources))
        except Exception as error:
            debuglog.LOG.warning("rag search failed: %s", error)
    messages = [{"role": "system", "content": RAG_SYSTEM + (("\n\n# 参照資料\n" + context) if context else "")}] + history + \
               [{"role": "user", "content": content}]
    t = time.time()
    with app.store.lock:
        app.store.db.execute("INSERT INTO chat_messages(thread_id,role,content,meta,created) VALUES(?,?,?,?,?)",
                             (tid, "user", content, "{}", t))
        if not history:
            app.store.db.execute("UPDATE chat_threads SET title=? WHERE id=?", (content[:60], tid))
    req.h.start_stream()
    src_meta = [{"n": i + 1, "doc_id": s["doc_id"], "title": s["title"], "collection": s["collection"],
                 "ext_id": s["ext_id"], "url": s["url"]} for i, s in enumerate(sources)]
    req.h.stream_event({"sources": src_meta})
    answer, reasoning, final = [], [], {}
    try:
        for ev in app.providers.chat_stream(messages, b.get("provider"), b.get("overrides")):
            if "delta" in ev:
                answer.append(ev["delta"])
            if "reasoning" in ev:
                reasoning.append(ev["reasoning"])
            if ev.get("done"):
                final = ev
            req.h.stream_event(ev)
    except LLMError as error:
        req.h.stream_event({"error": str(error)})
        final = {"error": str(error)}
    except (BrokenPipeError, ConnectionResetError):
        final = {"error": "client disconnected"}
    meta = {"sources": src_meta, "model": final.get("model"), "provider": final.get("provider"), "usage": final.get("usage")}
    if final.get("error"):
        meta["error"] = final["error"]
    with app.store.lock:
        app.store.db.execute("INSERT INTO chat_messages(thread_id,role,content,meta,created) VALUES(?,?,?,?,?)",
                             (tid, "assistant", "".join(answer), json.dumps(meta, ensure_ascii=False), time.time()))
        app.store.db.execute("UPDATE chat_threads SET updated=? WHERE id=?", (time.time(), tid))
    return 200


# ---------------------------------------------------------------------------
# connectors
@route("GET", "/api/v1/connectors", "read")
def connectors_list(req):
    out = []
    for c in connectors.CATALOG:
        item = dict(c)
        item["configured"] = all(req.app.config.secret(k) for k in (c["key"] or []))
        out.append(item)
    return {"connectors": out}


@route("POST", "/api/v1/connectors/{name}/run", "user")
def connectors_run(req):
    b = req.json()
    name = req.params["name"]
    spec = next((c for c in connectors.CATALOG if c["id"] == name), None)
    if not spec:
        raise _err(404, "unknown connector")
    if spec["key"] and not all(req.app.config.secret(k) for k in spec["key"]):
        raise _err(409, "%s は未登録（キー未設定）のため使えません。設定 > 外部キー で登録すると利用できます" % spec["label"])
    t0 = time.time()
    try:
        docs = connectors.run(name, b.get("params") or {}, req.app.config.secret)
    except connectors.ConnectorError as error:
        raise _err(502, str(error))
    coll = req.app.store.ensure_collection(b.get("collection") or ("%s-%s" % (spec["kind"], name)), spec["kind"])
    result = req.app.store.add_documents(coll["id"], docs, actor=req.actor)
    result.pop("ids", None)
    return dict(result, collection=coll["name"], fetched=len(docs), ms=round((time.time() - t0) * 1000))


# ---------------------------------------------------------------------------
# debug / update
@route("GET", "/api/debug/bundle", "read")
def debug_bundle(req):
    return req.app.debug_bundle()


@route("GET", "/api/debug/logs", "admin")
def debug_logs(req):
    level = req.arg("level", "")
    items = list(debuglog.RECORDS)
    if level:
        items = [i for i in items if i["level"] == level.upper()]
    return {"logs": items[-500:]}


@route("GET", "/api/update/status", "admin")
def update_status(req):
    return req.app.updater.status()


@route("POST", "/api/update/check", "admin")
def update_check(req):
    req.app.updater.check()
    return req.app.updater.status()


@route("POST", "/api/update/apply", "admin")
def update_apply(req):
    asset = req.app.updater.apply()
    req.app.store.audit("admin", "update.apply", asset["version"])
    return {"started": True, "target": asset["version"]}


@route("GET", "/api/audit", "admin")
def audit(req):
    return {"audit": [dict(r) for r in req.app.store.q("SELECT * FROM audit ORDER BY id DESC LIMIT 200")]}


# ---------------------------------------------------------------------------
# MCP
@route("POST", "/mcp", "read")
def mcp_endpoint(req):
    body = req.json(limit=32 * 1024 * 1024)
    scopes = req.device["scopes"] if req.device else "rw"
    if isinstance(body, list):
        out = [r for r in (mcp.handle(req.app, m, scopes) for m in body) if r is not None]
        return req.h.send_json(200, out) if out else req.h.send_bytes(202, b"", "text/plain")
    resp = mcp.handle(req.app, body, scopes)
    if resp is None:
        return req.h.send_bytes(202, b"", "text/plain")
    return req.h.send_json(200, resp)
