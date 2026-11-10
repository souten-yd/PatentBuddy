"""LLM providers: QnapAssistant (OpenAI-compatible on the same NAS), OpenRouter (with routing
options), and any OpenAI-compatible endpoint (Ollama, llama.cpp, vLLM, LM Studio...).

Only urllib is used. Streaming uses Server-Sent Events from the upstream and is relayed as-is.
API keys come from secrets.json and are never returned or logged.
"""
import json
import logging
import time
import urllib.error
import urllib.request

from . import privacy

LOG = logging.getLogger("qnaplibrary.llm")
APP_URL = "https://github.com/souten-yd/QnapPatentBuddy"
OPENROUTER_PROVIDER_KEYS = ("order", "only", "ignore", "sort", "allow_fallbacks", "require_parameters",
                            "data_collection", "zdr", "quantizations", "max_price")
SAMPLING_KEYS = ("temperature", "top_p", "top_k", "max_tokens", "frequency_penalty", "presence_penalty",
                 "repetition_penalty", "min_p", "seed", "stop")


_QUERY_CACHE = {}


class LLMError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Redirects must not move a confidential payload outside the checked host.
        return None


# Do not honor system HTTP(S)_PROXY for invention-bearing model requests.
_DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


class Providers:
    def __init__(self, config):
        self.config = config

    def list(self):
        out = []
        for p in self.config.get("llm", "providers", default=[]):
            item = dict(p)
            if p.get("secret"):
                item["secret_status"] = self.config.secret_status(p["secret"])
            out.append(item)
        return out

    def get(self, pid=None):
        pid = pid or self.config.get("llm", "default_provider")
        for p in self.config.get("llm", "providers", default=[]):
            if p.get("id") == pid:
                return p
        raise LLMError("provider not found: %s" % pid)

    def save(self, providers, default_provider=None):
        if not isinstance(providers, list) or not providers:
            raise LLMError("providers must be a non-empty list")
        clean, ids = [], set()
        for p in providers:
            if not isinstance(p, dict) or not p.get("id") or p["id"] in ids:
                raise LLMError("each provider needs a unique id")
            if p.get("type") not in ("openai", "openrouter"):
                raise LLMError("type must be openai or openrouter")
            url = str(p.get("base_url", ""))
            if not url.startswith(("http://", "https://")):
                raise LLMError("base_url must be http(s)")
            ids.add(p["id"])
            clean.append({k: p.get(k) for k in ("id", "type", "label", "base_url", "model", "secret", "options")
                          if p.get(k) is not None})
        llm = self.config.get("llm")
        llm["providers"] = clean
        if default_provider:
            llm["default_provider"] = default_provider
        self.config.replace_section("llm", llm)

    # http ----------------------------------------------------------------
    def _headers(self, p):
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        key = self.config.secret(p["secret"]) if p.get("secret") else None
        if key:
            h["Authorization"] = "Bearer " + key
        if p.get("type") == "openrouter":
            h["HTTP-Referer"] = APP_URL
            h["X-Title"] = "QnapPatentBuddy"
        return h

    def _request(self, p, path, body=None, timeout=120, stream=False, scope="confidential"):
        # Validate BEFORE creating the request or contacting the provider.
        # No caller-supplied task prompt is allowed to claim public scope.
        if body is not None and scope != "public_reference" and not privacy.confidential_allowed(p, self.config):
            raise LLMError("機密保護: この操作はローカルLLM限定です。外部AIへの送信を遮断しました")
        url = p["base_url"].rstrip("/") + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=self._headers(p), method="POST" if data is not None else "GET")
        try:
            resp = _DIRECT_OPENER.open(req, timeout=timeout)
        except urllib.error.HTTPError as error:
            # Do not include response content: remote services may echo secrets.
            raise LLMError("%s %s: HTTP %d" % (p["id"], path, error.code))
        except (urllib.error.URLError, OSError) as error:
            raise LLMError("%s: 接続に失敗しました（エンドポイントを確認してください）" % p["id"])
        if stream:
            return resp
        with resp:
            raw = resp.read(32 * 1024 * 1024)
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            raise LLMError("%s: JSON ではない応答" % p["id"])

    # chat ----------------------------------------------------------------
    def build_body(self, p, messages, overrides=None, stream=False):
        opts = dict(p.get("options") or {})
        opts.update(overrides or {})
        body = {"model": opts.get("model") or p.get("model") or "", "messages": messages, "stream": stream}
        if not body["model"]:
            body.pop("model")
        for k in SAMPLING_KEYS:
            if opts.get(k) not in (None, ""):
                body[k] = opts[k]
        if p.get("type") == "openrouter":
            fallback = [m for m in (opts.get("fallback_models") or []) if m]
            if fallback:
                body["models"] = [body.get("model", "openrouter/auto")] + fallback
            prov = {k: v for k, v in (opts.get("provider") or {}).items()
                    if k in OPENROUTER_PROVIDER_KEYS and v not in (None, "", [], {})}
            if prov:
                body["provider"] = prov
            reasoning = {k: v for k, v in (opts.get("reasoning") or {}).items() if v not in (None, "")}
            if reasoning:
                body["reasoning"] = reasoning
            if opts.get("web_search"):
                body["plugins"] = [{"id": "web", "max_results": int(opts.get("web_max_results") or 5)}]
            if opts.get("transforms"):
                body["transforms"] = opts["transforms"]
            if stream:
                body["usage"] = {"include": True}
        return body

    def chat(self, messages, provider=None, overrides=None, timeout=180, scope="confidential"):
        p = self.get(provider)
        t0 = time.time()
        data = self._request(p, "/chat/completions", self.build_body(p, messages, overrides), timeout=timeout, scope=scope)
        try:
            choice = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("%s: 応答に choices がありません: %s" % (p["id"], str(data)[:300]))
        return {"content": choice.get("content") or "", "reasoning": choice.get("reasoning") or "",
                "model": data.get("model"), "usage": data.get("usage"), "provider": p["id"],
                "ms": round((time.time() - t0) * 1000)}

    def chat_stream(self, messages, provider=None, overrides=None, timeout=300, scope="confidential"):
        """Yield dict events: {"delta": str} / {"reasoning": str} / {"done": True, "usage":..., "model":...}."""
        p = self.get(provider)
        resp = self._request(p, "/chat/completions", self.build_body(p, messages, overrides, stream=True),
                             timeout=timeout, stream=True, scope=scope)
        usage, model = None, None
        with resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    event = json.loads(payload)
                except ValueError:
                    continue
                if event.get("error"):
                    raise LLMError(str(event["error"])[:400])
                model = event.get("model") or model
                usage = event.get("usage") or usage
                for choice in event.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if delta.get("reasoning"):
                        yield {"reasoning": delta["reasoning"]}
                    if delta.get("content"):
                        yield {"delta": delta["content"]}
        yield {"done": True, "usage": usage, "model": model, "provider": p["id"]}

    def models(self, provider=None):
        p = self.get(provider)
        data = self._request(p, "/models", timeout=30)
        items = data.get("data") if isinstance(data, dict) else data
        out = []
        for m in items or []:
            if not isinstance(m, dict):
                continue
            pricing = m.get("pricing") or {}
            out.append({"id": m.get("id"), "name": m.get("name") or m.get("id"),
                        "context": m.get("context_length"), "prompt_price": pricing.get("prompt"),
                        "completion_price": pricing.get("completion"),
                        "free": str(m.get("id", "")).endswith(":free") or pricing.get("prompt") in ("0", 0)})
        return out

    # embeddings ----------------------------------------------------------
    def embedding_config(self):
        return self.config.get("llm", "embedding", default={}) or {}

    def embedding_enabled(self):
        cfg = self.embedding_config()
        if not (cfg.get("provider") and cfg.get("model")):
            return False
        try:
            p = self.get(cfg["provider"])
        except LLMError:
            return False
        return privacy.confidential_allowed(p, self.config) and (not p.get("secret") or bool(self.config.secret(p["secret"])))

    def embedding_tag(self):
        """Identifier stored with vectors: model + truncation, so different spaces never mix."""
        cfg = self.embedding_config()
        tag = str(cfg.get("model") or "")
        if cfg.get("truncate_dim"):
            tag += "@%d" % int(cfg["truncate_dim"])
        return tag

    def embed(self, texts, query=False):
        cfg = self.embedding_config()
        if not self.embedding_enabled():
            raise LLMError("埋め込みプロバイダが未設定です（OpenRouter の場合は API キーを設定）")
        key = None
        if query and len(texts) == 1:
            key = (self.embedding_tag(), texts[0])
            hit = _QUERY_CACHE.get(key)
            if hit is not None:
                return [hit]
        vecs = self._embed_raw(cfg, texts, query)
        trunc = int(cfg.get("truncate_dim") or 0)
        if trunc:
            vecs = [v[:trunc] for v in vecs]
        if key is not None:
            if len(_QUERY_CACHE) > 256:
                _QUERY_CACHE.pop(next(iter(_QUERY_CACHE)))
            _QUERY_CACHE[key] = vecs[0]
        return vecs

    def embedding_models(self, provider=None):
        p = self.get(provider or self.embedding_config().get("provider"))
        path = "/embeddings/models" if p.get("type") == "openrouter" else "/models"
        data = self._request(p, path, timeout=30)
        items = data.get("data") if isinstance(data, dict) else data
        return [{"id": m.get("id"), "name": m.get("name") or m.get("id"),
                 "price": (m.get("pricing") or {}).get("prompt")} for m in items or [] if isinstance(m, dict)]

    def rerank_config(self):
        return self.config.get("llm", "rerank", default={}) or {}

    def rerank_enabled(self):
        cfg = self.rerank_config()
        if not (cfg.get("enabled") and cfg.get("provider") and cfg.get("model")):
            return False
        try:
            return privacy.confidential_allowed(self.get(cfg["provider"]), self.config)
        except LLMError:
            return False

    def rerank(self, query, documents, top_n=None):
        """Return [(index, score)] best first. Cohere/Jina-compatible /rerank endpoint."""
        cfg = self.rerank_config()
        p = self.get(cfg["provider"])
        body = {"model": cfg["model"], "query": query, "documents": [d[:4000] for d in documents]}
        if top_n:
            body["top_n"] = int(top_n)
        data = self._request(p, "/rerank", body, timeout=60)
        results = data.get("results") or data.get("data") or []
        out = []
        for r in results:
            idx = r.get("index")
            score = r.get("relevance_score", r.get("score"))
            if isinstance(idx, int) and score is not None:
                out.append((idx, float(score)))
        out.sort(key=lambda x: -x[1])
        return out

    def _embed_raw(self, cfg, texts, query):
        p = self.get(cfg["provider"])
        prefix = (cfg.get("query_prefix") or "") if query else ""
        body = {"model": cfg["model"], "input": [prefix + t[:8000] for t in texts]}
        if cfg.get("dimensions"):
            body["dimensions"] = int(cfg["dimensions"])
        data = self._request(p, "/embeddings", body, timeout=120)
        try:
            vecs = [d["embedding"] for d in sorted(data["data"], key=lambda d: d.get("index", 0))]
        except (KeyError, TypeError):
            raise LLMError("埋め込み応答の形式が不正です: %s" % str(data)[:200])
        return vecs
