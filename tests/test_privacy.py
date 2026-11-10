"""Fail-closed checks for invention confidentiality across all outgoing paths."""
import json
import tempfile
import unittest
from unittest import mock

from qnaplibrary import privacy
from qnaplibrary.config import Config
from qnaplibrary.llm import LLMError, Providers
from qnaplibrary.notify import Notifier
from qnaplibrary.store import Store
from tests.helpers import Client, LiveServer


class PrivacyDestinationsTest(unittest.TestCase):
    def test_strict_destinations_and_no_dns_bypass(self):
        self.assertTrue(privacy.local_endpoint("http://127.0.0.1:11435/v1"))
        self.assertTrue(privacy.local_endpoint("http://[::1]:11434"))
        self.assertTrue(privacy.local_endpoint("http://localhost:11434"))
        for url in ("https://openrouter.ai/api/v1", "http://127.0.0.1.evil.invalid/v1",
                    "http://192.168.1.10:11434", "https://example.com/v1",
                    "https://127.0.0.1@evil.invalid/v1", "https://192.168.1.1:443"):
            self.assertFalse(privacy.local_endpoint(url), url)
        self.assertTrue(privacy.local_endpoint("https://192.168.1.10:443/v1", allow_lan_https=True))
        self.assertFalse(privacy.local_endpoint("http://192.168.1.10/v1", allow_lan_https=True))
        self.assertFalse(privacy.local_endpoint("https://8.8.8.8/v1", allow_lan_https=True))

    def test_fail_closed_before_any_socket_and_auto_embedding(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg = Config(temp)
            p = Providers(cfg)
            cfg.set_secret("openrouter_api_key", "sk-test")
            self.assertFalse(p.embedding_enabled())  # no automatic external chunks
            self.assertFalse(privacy.confidential_allowed(p.get("openrouter"), cfg))
            with mock.patch("qnaplibrary.llm._DIRECT_OPENER.open", side_effect=AssertionError("leak")):
                with self.assertRaisesRegex(LLMError, "機密保護"):
                    p.chat([{"role": "user", "content": "未公開の発明秘密"}], provider="openrouter")
                with self.assertRaisesRegex(LLMError, "機密保護"):
                    p.chat_stream([{"role": "user", "content": "秘密"}], provider="openrouter").__next__()
                with self.assertRaises(LLMError):
                    p.embed(["未公開発明の図面"])
                with self.assertRaisesRegex(LLMError, "機密保護"):
                    p.rerank("未公開の検索", ["技術詳細"])
            self.assertFalse(privacy.confidential_allowed(p.get("qnapassistant"), cfg))
            with self.assertRaises(LLMError):
                p.chat([{"role": "user", "content": "秘密"}], provider="qnapassistant")
            # Explicit approval is stored, but only literal loopback destinations work.
            providers = cfg.get("llm", "providers")
            providers[0]["local_only_verified"] = True
            p.save(providers)
            self.assertTrue(privacy.confidential_allowed(p.get("qnapassistant"), cfg))

    def test_public_scope_cannot_be_forged(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Providers(Config(temp))
            with mock.patch("qnaplibrary.llm._DIRECT_OPENER.open", side_effect=AssertionError("leak")):
                with self.assertRaisesRegex(LLMError, "固定公開"):
                    p.chat([{"role": "user", "content": "企業秘密"}],
                           provider="openrouter", scope="public_reference")
                with self.assertRaisesRegex(LLMError, "固定公開"):
                    p._request(p.get("openrouter"), "/embeddings",
                               {"input": ["秘密の実施例"]}, scope="public_reference")

    def test_public_reference_prompts_are_fixed_and_ignore_inventions(self):
        self.assertEqual(len(privacy.PUBLIC_REFERENCE_TOPICS), 5)
        for topic in privacy.PUBLIC_REFERENCE_TOPICS:
            messages = privacy.public_reference_messages(topic)
            self.assertNotIn("未公開発明", json.dumps(messages, ensure_ascii=False))
            self.assertEqual([m["role"] for m in messages], ["system", "user"])
        with self.assertRaises(ValueError):
            privacy.public_reference_messages("invented_topic")

    def test_notifier_never_includes_confidential_title_or_content(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg = Config(temp)
            store = Store(temp + "/library.sqlite3")
            cfg.update({"notify": {"webhooks": [{"url": "https://example.invalid/hook"}]}})
            sent = []
            try:
                with mock.patch.object(Notifier, "_webhook", side_effect=lambda hook, title, text, url: sent.append((title, text, url))):
                    Notifier(cfg, store).send("発明の秘密タイトル", "秘密の請求項と図面", key=None, url="secret-url")
                self.assertEqual(len(sent), 1)
                self.assertNotIn("秘密", repr(sent))
                self.assertIsNone(sent[0][2])
            finally:
                store.close()


class PrivacyApiTest(unittest.TestCase):
    def test_public_ai_cannot_send_private_payload(self):
        srv = LiveServer()
        try:
            c = Client(srv.base)
            c.login_setup()
            captured = []
            with mock.patch.object(srv.app.providers, "chat", side_effect=lambda messages, **kw: (
                    captured.append((messages, kw)) or {"content": "制度の一般論", "model": "m"})):
                st, data = c.call("POST", "/api/v1/public-patent-guidance",
                                  {"topic": "claim_scope", "provider": "openrouter",
                                   "project": {"title": "未公開発明の秘密"}, "extra": "秘密請求項"})
            self.assertEqual(st, 200, data)
            self.assertEqual(captured[0][1]["scope"], "public_reference")
            self.assertNotIn("秘密", json.dumps(captured, ensure_ascii=False))
            self.assertEqual(c.call("POST", "/api/v1/public-patent-guidance", {"topic": "fake"})[0], 400)

            st, proj = c.call("POST", "/api/v1/patents", {"title": "未公開発明の秘密"})
            self.assertEqual(st, 200)
            with mock.patch("qnaplibrary.llm._DIRECT_OPENER.open", side_effect=AssertionError("external leak")):
                st, data = c.call("POST", "/api/v1/patents/%d/assist" % proj["id"],
                                  {"task": "idea", "provider": "openrouter"})
                self.assertEqual(st, 502, data)
            self.assertEqual(c.call("POST", "/api/v1/research",
                                    {"question": "発明の秘密", "use_news": True})[0], 400)
            self.assertEqual(c.call("POST", "/api/v1/connectors/gdelt/run",
                                    {"params": {"query": "秘密"}})[0], 403)
        finally:
            srv.close()


if __name__ == "__main__":
    unittest.main()
