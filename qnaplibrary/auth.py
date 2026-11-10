"""Authentication: admin password, persistent sessions, LAN pairing passcode and device tokens.

* Admin (management web): password (PBKDF2-SHA256) or passkey (WebAuthn: Face ID / Windows Hello).
  Sessions keep only SHA-256 digests in persistent SQLite (survive restarts),
  and a bounded RAM cache; cookies are HttpOnly + SameSite=Strict, CSRF protected.
* Devices (other PCs, AI assistants, ControlDeck): the admin sets a pairing passcode; a client on
  the LAN posts it once to /api/v1/pair and receives a long-lived bearer token. Tokens are stored
  as SHA-256 hashes; they work without rate limits from LAN / Tailscale addresses.
"""
import hashlib
import hmac
import ipaddress
import secrets
import threading
import time

PBKDF2_ROUNDS = 240000
TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")
TAILSCALE_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")


def hash_password(password, salt=None, rounds=PBKDF2_ROUNDS):
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return "pbkdf2$%d$%s$%s" % (rounds, salt.hex(), dk.hex())


def verify_password(password, stored):
    try:
        _, rounds, salt, digest = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(dk.hex(), digest)
    except (ValueError, AttributeError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_local_network(ip, trusted=("tailscale",)):
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if getattr(addr, "ipv4_mapped", None):
        addr = addr.ipv4_mapped
    if addr.is_loopback or addr.is_private or addr.is_link_local:
        return True
    if "tailscale" in trusted and (addr in TAILSCALE_NET or addr in TAILSCALE_V6):
        return True
    for net in trusted:
        if net == "tailscale":
            continue
        try:
            if addr in ipaddress.ip_network(net, strict=False):
                return True
        except ValueError:
            continue
    return False


class RateLimiter:
    """Failed-attempt limiter for login/pairing (per IP)."""

    def __init__(self, max_fail=8, window=600):
        self.max_fail, self.window = max_fail, window
        self._fails = {}
        self._lock = threading.Lock()

    def blocked(self, key):
        with self._lock:
            t = time.time()
            items = [x for x in self._fails.get(key, []) if t - x < self.window]
            self._fails[key] = items
            return len(items) >= self.max_fail

    def fail(self, key):
        with self._lock:
            self._fails.setdefault(key, []).append(time.time())
            if len(self._fails) > 10000:
                self._fails.clear()

    def reset(self, key):
        with self._lock:
            self._fails.pop(key, None)


class Sessions:
    """Bounded persistent admin sessions, with only hashed cookie IDs on disk."""

    MAX_SESSIONS = 128

    def __init__(self, hours=720, store=None):
        try:
            self.ttl = max(3600, min(int(hours) * 3600, 30 * 86400))
        except (ValueError, TypeError, OverflowError):
            self.ttl = 30 * 86400
        self.store = store
        self._lock = threading.Lock()
        self._items = {}
        if store is not None:
            # In-memory lookups avoid disk reads/writes per request.
            for row in store.q("SELECT sid_hash, csrf, exp, via, created FROM admin_sessions WHERE exp>? ORDER BY created DESC, sid_hash DESC LIMIT ?",
                               (time.time(), self.MAX_SESSIONS)):
                self._items[row["sid_hash"]] = {
                    "exp": row["exp"], "csrf": row["csrf"], "via": row["via"],
                    "hash": row["sid_hash"], "created": row["created"],
                }

    @staticmethod
    def _digest(sid):
        return hashlib.sha256(sid.encode("utf-8")).hexdigest()

    def create(self, via):
        sid = secrets.token_urlsafe(32)
        digest, t = self._digest(sid), time.time()
        session = {"exp": t + self.ttl, "csrf": secrets.token_urlsafe(24), "via": via,
                   "hash": digest, "created": t}
        with self._lock:
            active = {k: v for k, v in self._items.items() if v["exp"] > t}
            active[digest] = session
            kept = sorted(active, key=lambda k: (active[k]["created"], k), reverse=True)[:self.MAX_SESSIONS]
            if self.store is not None:
                with self.store.lock:
                    self.store.db.execute("BEGIN IMMEDIATE")
                    try:
                        self.store.db.execute("DELETE FROM admin_sessions WHERE exp<=?", (t,))
                        self.store.db.execute(
                            "INSERT INTO admin_sessions(sid_hash,csrf,exp,via,created) VALUES(?,?,?,?,?)",
                            (digest, session["csrf"], session["exp"], via, t))
                        self.store.db.execute(
                            "DELETE FROM admin_sessions WHERE sid_hash NOT IN "
                            "(SELECT sid_hash FROM admin_sessions ORDER BY created DESC, sid_hash DESC LIMIT ?)",
                            (self.MAX_SESSIONS,))
                        self.store.db.execute("COMMIT")
                    except Exception:
                        self.store.db.execute("ROLLBACK")
                        raise
            self._items = {k: active[k] for k in kept}
        return sid, session

    def get(self, sid):
        if not sid or not isinstance(sid, str):
            return None
        digest = self._digest(sid)
        with self._lock:
            session = self._items.get(digest)
            if not session:
                return None
            if session["exp"] <= time.time():
                self._items.pop(digest, None)
                # Expiry reads stay RAM-only; prune disk rows on the next login.
                return None
            return session

    def drop(self, sid):
        if not sid:
            return
        digest = self._digest(sid)
        with self._lock:
            if self.store is not None:
                with self.store.lock:
                    self.store.db.execute("DELETE FROM admin_sessions WHERE sid_hash=?", (digest,))
            self._items.pop(digest, None)

    def clear(self):
        with self._lock:
            if self.store is not None:
                with self.store.lock:
                    self.store.db.execute("DELETE FROM admin_sessions")
            self._items.clear()


class Auth:
    def __init__(self, config, store):
        self.config = config
        self.store = store
        self.sessions = Sessions(config.get("auth", "session_hours", default=720), store)
        self.limiter = RateLimiter()
        self._device_seen = {}
        self._local_token = "qll_" + secrets.token_urlsafe(32)
        self._local_analysis_token = "qla_" + secrets.token_urlsafe(32)
        self._local_import_token = "qli_" + secrets.token_urlsafe(32)

    # admin --------------------------------------------------------------
    def admin_configured(self):
        return bool(self.config.secret("admin_password"))

    def set_admin_password(self, password):
        if not isinstance(password, str) or len(password) < 10:
            raise ValueError("パスワードは10文字以上にしてください")
        password_hash = hash_password(password)
        self.sessions.clear()
        self.config.set_secret("admin_password", password_hash)

    def check_admin_password(self, password):
        stored = self.config.secret("admin_password")
        return bool(stored) and verify_password(password or "", stored)

    # pairing ------------------------------------------------------------
    def set_pairing_passcode(self, passcode):
        if passcode in (None, ""):
            self.config.set_secret("pairing_passcode", "")
            return
        if len(passcode) < 8:
            raise ValueError("パスコードは8文字以上にしてください")
        self.config.set_secret("pairing_passcode", hash_password(passcode, rounds=120000))

    def pairing_enabled(self):
        return bool(self.config.secret("pairing_passcode"))

    def check_passcode(self, passcode):
        stored = self.config.secret("pairing_passcode")
        return bool(stored) and verify_password(passcode or "", stored)

    def create_device(self, name, scopes="rw"):
        token = "qlt_" + secrets.token_urlsafe(32)
        name = (name or "device").strip()[:80] or "device"
        if scopes not in ("rw", "ro", "published", "analysis", "pdf_import", "pdf_analysis"):
            raise ValueError("unsupported device token scope")
        with self.store.lock:
            cur = self.store.db.execute("INSERT INTO devices(name,token_hash,scopes,created) VALUES(?,?,?,?)",
                                        (name, token_hash(token), scopes, time.time()))
        return {"id": cur.lastrowid, "name": name, "token": token, "scopes": scopes}

    def local_token(self, scope="read"):
        if self.admin_configured() and self.config.get("auth", "local_auto_connect", default=True):
            return {"analysis": self._local_analysis_token, "read": self._local_token, "pdf_import": self._local_import_token}.get(scope)
        return None

    def device_for_token(self, token, ip):
        if token and token.startswith(("qll_", "qla_", "qli_")):
            import ipaddress
            try:
                loopback = ipaddress.ip_address(ip).is_loopback
            except ValueError:
                loopback = False
            scope = "pdf_import" if token.startswith("qli_") else "analysis" if token.startswith("qla_") else "read"
            current = self.local_token(scope)
            if loopback and current and secrets.compare_digest(token, current):
                return {"id": 0, "name": "Local same-user client", "scopes": "ro" if scope == "read" else scope}
            return None
        if not token or not token.startswith("qlt_"):
            return None
        row = self.store.one("SELECT * FROM devices WHERE token_hash=?", (token_hash(token),))
        if not row:
            return None
        if not self.config.get("server", "allow_remote_devices", default=False) and \
                not is_local_network(ip, self.config.get("server", "trusted_networks", default=["tailscale"])):
            return None
        # update last_seen at most every 10 minutes (avoid a write per request)
        t = time.time()
        if t - self._device_seen.get(row["id"], 0) > 600:
            self._device_seen[row["id"]] = t
            with self.store.lock:
                self.store.db.execute("UPDATE devices SET last_seen=?, last_ip=? WHERE id=?", (t, ip, row["id"]))
        return {"id": row["id"], "name": row["name"], "scopes": row["scopes"]}

    def list_devices(self):
        return [{"id": r["id"], "name": r["name"], "scopes": r["scopes"], "created": r["created"],
                 "last_seen": r["last_seen"], "last_ip": r["last_ip"]}
                for r in self.store.q("SELECT * FROM devices ORDER BY id")]

    def delete_device(self, device_id):
        with self.store.lock:
            return self.store.db.execute("DELETE FROM devices WHERE id=?", (int(device_id),)).rowcount
