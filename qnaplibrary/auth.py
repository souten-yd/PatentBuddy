"""Authentication: admin password, RAM sessions, LAN pairing passcode and device tokens.

* Admin (management web): password (PBKDF2-SHA256) or passkey (WebAuthn: Face ID / Windows Hello).
  Sessions live in RAM only (restart = log in again), cookie HttpOnly + SameSite=Strict, CSRF token.
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
    def __init__(self, hours=12):
        self.ttl = hours * 3600
        self._items = {}
        self._lock = threading.Lock()

    def create(self, via):
        sid = secrets.token_urlsafe(32)
        with self._lock:
            t = time.time()
            for k in [k for k, v in self._items.items() if v["exp"] < t]:
                del self._items[k]
            self._items[sid] = {"exp": t + self.ttl, "csrf": secrets.token_urlsafe(24), "via": via,
                                "hash": hashlib.sha256(sid.encode()).hexdigest(), "created": t}
        return sid, self._items[sid]

    def get(self, sid):
        if not sid:
            return None
        with self._lock:
            s = self._items.get(sid)
            if not s or s["exp"] < time.time():
                self._items.pop(sid, None)
                return None
            return s

    def drop(self, sid):
        with self._lock:
            self._items.pop(sid, None)

    def clear(self):
        with self._lock:
            self._items.clear()


class Auth:
    def __init__(self, config, store):
        self.config = config
        self.store = store
        self.sessions = Sessions(config.get("auth", "session_hours", default=12))
        self.limiter = RateLimiter()
        self._device_seen = {}

    # admin --------------------------------------------------------------
    def admin_configured(self):
        return bool(self.config.secret("admin_password"))

    def set_admin_password(self, password):
        if not isinstance(password, str) or len(password) < 10:
            raise ValueError("パスワードは10文字以上にしてください")
        self.config.set_secret("admin_password", hash_password(password))

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
        if scopes not in ("rw", "ro"):
            scopes = "rw"
        with self.store.lock:
            cur = self.store.db.execute("INSERT INTO devices(name,token_hash,scopes,created) VALUES(?,?,?,?)",
                                        (name, token_hash(token), scopes, time.time()))
        return {"id": cur.lastrowid, "name": name, "token": token, "scopes": scopes}

    def device_for_token(self, token, ip):
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
