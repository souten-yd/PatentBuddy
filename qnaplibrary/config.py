"""Settings (settings.json) and secrets (secrets.json, mode 0600) in the persistent data dir.

Both are small JSON files written atomically and only when they change.
"""
import copy
import hashlib
import json
import os
import threading
from pathlib import Path

DEFAULTS = {
    "server": {"bind": "0.0.0.0", "port": 17871, "tls_cert": "", "tls_key": "",
               "allow_remote_devices": False, "trusted_networks": ["tailscale"], "https_url": ""},
    "auth": {"session_hours": 12, "rp_id": ""},
    "update": {"channel": "stable", "auto_check": True, "auto_apply": False},
    "search": {"default_limit": 20, "hybrid": True, "rrf_k": 60},
    "llm": {
        "default_provider": "qnapassistant",
        "providers": [
            {"id": "qnapassistant", "type": "openai", "label": "QnapAssistant (同NAS)",
             "base_url": "http://127.0.0.1:11435/v1", "model": "", "secret": ""},
            {"id": "openrouter", "type": "openrouter", "label": "OpenRouter",
             "base_url": "https://openrouter.ai/api/v1", "model": "openrouter/auto", "secret": "openrouter_api_key",
             "options": {"fallback_models": [], "provider": {}, "reasoning": {}, "temperature": None,
                         "top_p": None, "max_tokens": None, "web_search": False}},
            {"id": "ollama", "type": "openai", "label": "Ollama / OpenAI互換 (別PC)",
             "base_url": "http://192.168.1.10:11434/v1", "model": "", "secret": ""},
        ],
        # Default: OpenRouter qwen/qwen3-embedding-8b (multilingual, low cost). Used only once the
        # OpenRouter key is set. Vectors are truncated to 1024 dims (Matryoshka) to save RAM.
        "embedding": {"provider": "openrouter", "model": "qwen/qwen3-embedding-8b", "dimensions": None,
                      "truncate_dim": 1024, "batch": 32, "auto": True, "query_prefix": "", "doc_prefix": ""},
        "rag_top_k": 8,
    },
    "connectors": {"epo_ops": {"enabled": False}, "jpo": {"enabled": False, "base_url": "https://ip-data.jpo.go.jp"},
                   "uspto_odp": {"enabled": False}, "gdelt": {"enabled": True}, "rss": {"enabled": True}},
}


def _merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def atomic_write(path, data, mode=0o644):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(str(tmp), mode)
    os.replace(str(tmp), str(path))


class Config:
    def __init__(self, data_dir):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.dir / "settings.json"
        self.secrets_path = self.dir / "secrets.json"
        self._lock = threading.RLock()
        self._settings = _merge(DEFAULTS, self._read(self.settings_path))
        self._secrets = self._read(self.secrets_path)

    @staticmethod
    def _read(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    # settings -----------------------------------------------------------
    def get(self, *keys, default=None):
        with self._lock:
            cur = self._settings
            for k in keys:
                if not isinstance(cur, dict) or k not in cur:
                    return default
                cur = cur[k]
            return copy.deepcopy(cur)

    def all(self):
        with self._lock:
            return copy.deepcopy(self._settings)

    def update(self, patch):
        with self._lock:
            new = _merge(self._settings, patch)
            if new != self._settings:
                self._settings = new
                atomic_write(self.settings_path, json.dumps(new, ensure_ascii=False, indent=1))
            return copy.deepcopy(new)

    def replace_section(self, key, value):
        with self._lock:
            if self._settings.get(key) != value:
                self._settings[key] = copy.deepcopy(value)
                atomic_write(self.settings_path, json.dumps(self._settings, ensure_ascii=False, indent=1))

    # secrets ------------------------------------------------------------
    def secret(self, name):
        with self._lock:
            return self._secrets.get(name)

    def set_secret(self, name, value):
        with self._lock:
            if value in (None, ""):
                if name not in self._secrets:
                    return
                self._secrets.pop(name, None)
            else:
                if self._secrets.get(name) == value:
                    return
                self._secrets[name] = value
            atomic_write(self.secrets_path, json.dumps(self._secrets), mode=0o600)

    def secret_status(self, name):
        value = self.secret(name)
        if not value:
            return {"configured": False}
        if isinstance(value, str):
            return {"configured": True, "fingerprint": hashlib.sha256(value.encode()).hexdigest()[:10]}
        return {"configured": True}
