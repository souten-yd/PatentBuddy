"""Never expose drafts through the external-app public catalogue token."""
import re
import tempfile
from unittest import mock
import unittest

from tests.helpers import Client, LiveServer
from qnaplibrary.public_catalog import PublicCatalog


class PublicCatalogApiTest(unittest.TestCase):
    def setUp(self):
        self.server = LiveServer()
        self.admin = Client(self.server.base)
        self.admin.login_setup()
        code, col = self.admin.call("POST", "/api/v1/collections", {"name": "patents", "kind": "patent"})
        self.assertEqual(code, 200, col)
        self.cid = col["id"]
        code, data = self.admin.call("POST", "/api/v1/collections/patents/documents", {
            "documents": [
                {"id": "JP2024-111111A", "title": "公開された電池公報",
                 "body": "正極と固体電解質層を備える。内部メモ：絶対秘密の発明案"},
                {"id": "JP-PRIVATE-001", "title": "未公開の請求項案",
                 "body": "未公開請求項の秘密情報"},
            ]})
        self.assertEqual(code, 200, data)
        self.doc_id, self.private_id = data["ids"]
        code, public_token = self.admin.call(
            "POST", "/api/devices", {"name": "public-api-client", "scopes": "published"})
        self.assertEqual(code, 200, public_token)
        self.public = Client(self.server.base)
        self.public.token = public_token["token"]

    def approve(self, payload):
        status, preview = self.admin.call("POST", "/api/v1/publications/preview", payload)
        if status != 200:
            return status, preview
        return self.admin.call("POST", "/api/v1/publications",
                               dict(payload, preview_token=preview["preview_token"]))

    def tearDown(self):
        self.server.close()

    def test_fail_closed_before_public_approval(self):
        status, result = self.public.call("POST", "/api/v1/public-catalog/search", {"q": "固体電解質"})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["results"], [])
        for method, endpoint, body in (
            ("GET", "/api/v1/collections", None),
            ("POST", "/api/v1/search", {"q": "請求項"}),
            ("GET", "/api/v1/patents", None),
            ("GET", "/api/auth/me", None),
            ("GET", "/api/v1/documents/%s" % self.private_id, None),
            ("POST", "/api/v1/collections/patents/documents",
             {"documents": [{"id":"E1","title":"bad"}]}),
        ):
            status, _ = self.public.call(method, endpoint, body)
            self.assertEqual(status, 403, (method, endpoint))

    def test_admin_must_review_excerpt_and_attest_publication(self):
        for payload in (
            {"doc_id": self.doc_id, "excerpt": "正極と固体電解質層を備える。"},
            {"doc_id": self.doc_id, "excerpt": "正極と固体電解質層を備える。", "confirm_public": "true"},
            {"doc_id": self.doc_id, "excerpt": "入力していない任意の社外機密", "confirm_public": True},
        ):
            status, _ = self.approve(payload)
            self.assertEqual(status, 400, payload)
        status, approved = self.approve({"doc_id": self.doc_id, "excerpt": "正極と固体電解質層を備える。",
             "confirm_public": True})
        self.assertEqual(status, 200, approved)
        status, result = self.public.call(
            "POST", "/api/v1/public-catalog/search", {"q": "固体電解質"})
        self.assertEqual(status, 200, result)
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["id"], approved["id"])
        self.assertEqual(result["external_llm_called"], False)
        self.assertNotIn("絶対秘密", str(result))
        self.assertNotIn("doc_id", result["results"][0])
        self.assertNotIn("meta", result["results"][0])
        status, doc = self.public.call("GET", "/api/v1/public-catalog/" + approved["id"])
        self.assertEqual(status, 200, doc)
        self.assertEqual(doc["text"], "正極と固体電解質層を備える。")
        status, blocked = self.public.call(
            "POST", "/api/v1/public-catalog/search", {"q": "絶対秘密"})
        self.assertEqual(status, 200, blocked)
        self.assertEqual(blocked["results"], [])

    def test_source_edit_invalidates_without_sending_old_excerpt(self):
        status, approved = self.approve({"doc_id": self.doc_id, "excerpt": "正極と固体電解質層を備える。",
             "confirm_public": True})
        self.assertEqual(status, 200)
        code, updated = self.admin.call(
            "POST", "/api/v1/collections/patents/documents",
            {"documents": [{"id": "JP2024-111111A", "title": "変更済み公報",
                            "body": "代替固体電解質を使用する新しい本文"}]})
        self.assertEqual(code, 200, updated)
        self.assertEqual(updated["updated"], 1)
        self.assertEqual(self.public.call(
            "GET", "/api/v1/public-catalog/" + approved["id"])[0], 404)
        self.assertEqual(self.public.call(
            "POST", "/api/v1/public-catalog/search", {"q":"固体電解質"})[1]["results"], [])
        statuses = self.admin.call("GET", "/api/v1/publications")[1]
        self.assertFalse(statuses["items"][0]["active"])
        self.assertEqual(self.admin.call("DELETE", "/api/v1/publications/%s" % self.doc_id)[1],
                         {"revoked": True})

    def test_token_cannot_be_created_via_public_pairing(self):
        self.admin.call("PUT", "/api/devices/pairing", {"passcode": "secret-pass-2026"})
        anon = Client(self.server.base)
        status, _ = anon.call(
            "POST", "/api/v1/pair", {"passcode": "secret-pass-2026", "name": "bad",
                                   "scopes": "published"})
        self.assertEqual(status, 403)
        status, _ = self.admin.call("POST", "/api/devices", {"name":"bad","scopes":"something"})
        self.assertEqual(status, 400)

    def test_non_public_tokens_have_no_published_api_privileges(self):
        status, token = self.admin.call("POST", "/api/devices", {"name":"internal", "scopes":"ro"})
        self.assertEqual(status, 200)
        client = Client(self.server.base)
        client.token = token["token"]
        self.assertEqual(client.call("POST", "/api/v1/public-catalog/search", {"q":"電池"})[0],403)

    def test_admin_can_revoke_publication_without_deleting_source(self):
        status, approved = self.approve({"doc_id": self.doc_id, "excerpt": "正極と固体電解質層を備える。",
             "confirm_public": True})
        self.assertEqual(status, 200)
        status, response = self.admin.call("DELETE", "/api/v1/publications/%s" % self.doc_id)
        self.assertEqual(status, 200)
        self.assertTrue(response["revoked"])
        self.assertEqual(self.public.call("GET", "/api/v1/public-catalog/"+approved["id"])[0],404)
        self.assertEqual(self.admin.call("GET", "/api/v1/documents/%s" % self.doc_id)[0], 200)

    def test_fts_off_keeps_approval_filter(self):
        self.approve({"doc_id":self.doc_id, "excerpt":"正極と固体電解質層を備える。",
                         "confirm_public":True})
        self.server.app.public_catalog.fts = False
        status, response = self.public.call("POST", "/api/v1/public-catalog/search", {"q":"固体電解質"})
        self.assertEqual(status, 200)
        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(self.public.call("POST", "/api/v1/public-catalog/search",
            {"q":"絶対秘密"})[1]["results"], [])

    def test_preview_required_exact_and_invalid_after_edit(self):
        payload = {"doc_id": self.doc_id, "excerpt": "正極と固体電解質層を備える。", "confirm_public": True}
        self.assertEqual(self.admin.call("POST", "/api/v1/publications", payload)[0], 400)
        st, preview = self.admin.call("POST", "/api/v1/publications/preview", payload)
        self.assertEqual(st, 200)
        self.assertEqual(preview["publication"], {"title": "公開された電池公報",
            "publication_number": "JP2024-111111A", "text": payload["excerpt"]})
        self.assertEqual(self.admin.call("POST", "/api/v1/publications", dict(payload,
            preview_token=preview["preview_token"], excerpt="内部メモ：絶対秘密の発明案"))[0], 400)
        for token in ("", "0.fake", "9999999999." + "あ" * 64):
            self.assertEqual(self.admin.call("POST", "/api/v1/publications", dict(payload, preview_token=token))[0], 400)
        self.admin.call("POST", "/api/v1/collections/patents/documents", {"documents": [
            {"id": "JP2024-111111A", "title": "新しい秘密タイトル", "body": payload["excerpt"]}]})
        self.assertEqual(self.admin.call("POST", "/api/v1/publications", dict(payload,
            preview_token=preview["preview_token"]))[0], 400)

    def test_restoring_original_content_does_not_restore_approval(self):
        payload = {"doc_id": self.doc_id, "excerpt": "正極と固体電解質層を備える。", "confirm_public": True}
        st, approved = self.approve(payload)
        self.assertEqual(st, 200)
        for title, body in (("変更", "別の本文"), ("公開された電池公報", "正極と固体電解質層を備える。内部メモ：絶対秘密の発明案")):
            self.assertEqual(self.admin.call("POST", "/api/v1/collections/patents/documents", {"documents": [
                {"id": "JP2024-111111A", "title": title, "body": body}]})[0], 200)
        self.assertEqual(self.public.call("GET", "/api/v1/public-catalog/" + approved["id"])[0], 404)
        self.assertEqual(self.public.call("POST", "/api/v1/public-catalog/search", {"q": "固体電解質"})[1]["results"], [])
        self.assertEqual(self.approve(payload)[0], 200)

    def test_public_token_denied_on_every_non_catalog_route_without_llm_egress(self):
        from qnaplibrary.api import ROUTES
        with mock.patch("qnaplibrary.llm._DIRECT_OPENER.open", side_effect=AssertionError("unexpected LLM request")) as outgoing:
            for route in ROUTES:
                if route["auth"] == "published":
                    continue
                path = re.sub(r"\{\w+\}", "1", route["pattern"])
                with self.subTest(method=route["method"], path=path):
                    status, _ = self.public.call(route["method"], path,
                        {} if route["method"] != "GET" else None)
                    self.assertEqual(status, 403)
            outgoing.assert_not_called()


if __name__ == "__main__":
    unittest.main()
