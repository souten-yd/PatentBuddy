"""Notifications: webhooks (generic JSON / Discord / Slack / ControlDeck) and e-mail (SMTP).

Destinations are configured by the admin only, so private LAN addresses (ControlDeck, a local
relay) are allowed. Each message is sent at most once per key (notify_log) to avoid repeats.
"""
import json
import logging
import smtplib
import ssl
import time
import urllib.request
from email.message import EmailMessage

LOG = logging.getLogger("qnaplibrary.notify")


class Notifier:
    def __init__(self, config, store):
        self.config, self.store = config, store

    def settings(self):
        return self.config.get("notify", default={}) or {}

    def already(self, key):
        return self.store.one("SELECT 1 FROM notify_log WHERE key=?", (key,)) is not None

    def mark(self, key):
        with self.store.lock:
            self.store.db.execute("INSERT OR REPLACE INTO notify_log(key, sent) VALUES(?,?)", (key, time.time()))
            self.store.db.execute("DELETE FROM notify_log WHERE sent < ?", (time.time() - 400 * 86400,))

    def send(self, title, text, key=None, url=None):
        """Send to every destination. Returns a list of per-destination results."""
        if key and self.already(key):
            return [{"skipped": "already sent"}]
        cfg = self.settings()
        results = []
        for hook in cfg.get("webhooks") or []:
            if not hook.get("url"):
                continue
            try:
                self._webhook(hook, title, text, url)
                results.append({"to": hook.get("label") or hook["url"][:40], "ok": True})
            except Exception as error:
                LOG.warning("webhook failed: %s", error)
                results.append({"to": hook.get("label") or hook["url"][:40], "ok": False, "error": str(error)[:200]})
        mail = cfg.get("email") or {}
        if mail.get("enabled") and mail.get("host") and mail.get("to"):
            try:
                self._email(mail, title, text + ("\n\n" + url if url else ""))
                results.append({"to": "email", "ok": True})
            except Exception as error:
                LOG.warning("email failed: %s", error)
                results.append({"to": "email", "ok": False, "error": str(error)[:200]})
        if key and any(r.get("ok") for r in results):
            self.mark(key)
        return results

    @staticmethod
    def _webhook(hook, title, text, url):
        kind = hook.get("kind") or "json"
        if kind == "discord":
            body = {"content": ("**%s**\n%s" % (title, text))[:1900]}
        elif kind == "slack":
            body = {"text": "*%s*\n%s" % (title, text)}
        else:  # generic JSON (ControlDeck webhook node etc.)
            body = {"app": "QnapLibrary", "title": title, "text": text, "url": url, "ts": time.time()}
        req = urllib.request.Request(hook["url"], data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "User-Agent": "QnapLibrary"}, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read(1000)

    def _email(self, mail, title, text):
        msg = EmailMessage()
        msg["Subject"] = "[QnapLibrary] " + title
        msg["From"] = mail.get("from") or mail.get("user") or "qnaplibrary@localhost"
        msg["To"] = mail["to"]
        msg.set_content(text)
        port = int(mail.get("port") or 587)
        if port == 465:
            smtp = smtplib.SMTP_SSL(mail["host"], port, timeout=20, context=ssl.create_default_context())
        else:
            smtp = smtplib.SMTP(mail["host"], port, timeout=20)
            if mail.get("starttls", True):
                smtp.starttls(context=ssl.create_default_context())
        with smtp:
            password = self.config.secret("smtp_password")
            if mail.get("user") and password:
                smtp.login(mail["user"], password)
            smtp.send_message(msg)
