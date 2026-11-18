"""K7a: user-driven official IPC tree and strictly local AI proposals."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from qnaplibrary import official_ipc, source_advisor, source_scope
from qnaplibrary.store import Store
from tests.helpers import Client, LiveServer


class OfficialIPCTreeTests(unittest.TestCase):
    def test_atomic_manual_catalog_browse_and_version_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / "source.sqlite3")
            try:
                payload = (b'<?xml version="1.0" encoding="utf-8"?>'
                           b'<valid-symbol-list><valid-symbol>H02M7/48</valid-symbol>'
                           b'<valid-symbol>H02M5/00</valid-symbol>'
                           b'<valid-symbol>H01F1/00</valid-symbol>'
                           b'<valid-symbol>H02M7/48</valid-symbol></valid-symbol-list>')
                response = official_ipc.install(store, payload, "H")
                self.assertEqual(response["count"], 3)
                self.assertFalse(response["unchanged"])
                self.assertTrue(official_ipc.install(store, payload, "H")["unchanged"])
                self.assertEqual(official_ipc.status(store)["catalogs"][0]["edition"], "2026.01")
                tree = official_ipc.browse(store)
                self.assertTrue(next(x for x in tree["items"] if x["code"] == "H")["imported"])
                classes = official_ipc.browse(store, "H")["items"]
                self.assertIn("H02", [x["code"] for x in classes])
                subclasses = official_ipc.browse(store, "H02")["items"]
                self.assertEqual([x["code"] for x in subclasses], ["H02M"])
                self.assertTrue(official_ipc.verified_subclass(store, "H02M"))
                self.assertFalse(official_ipc.verified_subclass(store, "G01R"))
                dynamic = source_scope.build_scope(ipc="H02M", limit=1, official_verified=True)
                self.assertEqual(dynamic["cql"], "ic=H02M")
                # Dynamic subclass G01R only works when the authoritative catalogue
                # is checked by the endpoint. Setting a client bool cannot do this.
                with self.assertRaises(ValueError):
                    source_scope.build_scope(ipc="G01R", limit=1)
                self.assertFalse(official_ipc.verified_subclass(store, "H02P"))
                previous = store.one("SELECT count(*) FROM official_ipc_symbols")[0]
                for bad in (b"", b"<!DOCTYPE test><valid-symbol>H02P1/00</valid-symbol>",
                            b"<valid-symbol-list><bad>H02P1/00</bad></valid-symbol-list>"):
                    with self.assertRaises(ValueError):
                        official_ipc.install(store, bad, "H")
                self.assertEqual(store.one("SELECT count(*) FROM official_ipc_symbols")[0], previous)
                for parent in ("A01N1/00", "H02M or id=secret", "h", "Z"):
                    with self.assertRaises(ValueError):
                        official_ipc.browse(store, parent)
            finally:
                store.close()

    def test_dynamic_official_code_needs_import_and_explicit_admin_consent(self):
        server = LiveServer()
        try:
            admin = Client(server.base)
            admin.login_setup()
            reader = Client(server.base)
            reader.token = server.app.auth.local_token()
            code, root = reader.call("POST", "/api/v1/ipc-catalog/browse", {"parent": ""})
            self.assertEqual(code, 200, root)
            self.assertEqual(reader.call("POST", "/api/v1/ipc-catalog/import",
                                         {"section": "G", "confirm_public_source": True})[0], 403)
            # Import official-format fixture via trusted module, no network.
            official_ipc.install(server.app.store,
                b"<valid-symbol-list><valid-symbol>G01R31/00</valid-symbol></valid-symbol-list>", "G")
            scope = {"ipc": "G01R", "limit": 1, "publication_country": "JP",
                     "year_from": 2020, "year_to": 2025, "first": 1}
            code, reply = reader.call("POST", "/api/v1/source-scope/preview", scope)
            self.assertEqual(code, 200, reply)
            self.assertTrue(reply["official_catalog_verified"])
            self.assertEqual(reply["cql"], 'ic=G01R and pn=JP and pd within "20200101 20251231"')
            self.assertEqual(reader.call("POST", "/api/v1/source-acquisitions",
                                         dict(scope, public_only_confirmed=True))[0], 403)
            self.assertEqual(admin.call("POST", "/api/v1/source-acquisitions",
                                        dict(scope, public_only_confirmed=False))[0], 400)
            with patch("qnaplibrary.connectors.epo_search", return_value=[
                {"id": "JP111A1", "title": "Example", "source": "EPO OPS"}]) as ops:
                code, result = admin.call("POST", "/api/v1/source-acquisitions",
                                          dict(scope, public_only_confirmed=True))
            self.assertEqual(code, 200, result)
            self.assertEqual(ops.call_args.args[0], reply["cql"])
        finally:
            server.close()


class LocalClassificationAdvisorTests(unittest.TestCase):
    def test_unverified_proposal_cannot_become_official_choice(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / "source.sqlite3")
            try:
                answer = json.dumps({"codes": ["G01R", "H02M", "HACK", "H02M"],
                                     "reason": "測定と変換", "clarify": "測定対象は？"})
                result = source_advisor.parse_answer(answer, store)
                self.assertEqual([c["code"] for c in result["codes"]], ["G01R", "H02M"])
                self.assertTrue(all(not c["official_catalog_verified"] for c in result["codes"]))
                official_ipc.install(store,
                    b"<valid-symbol-list><valid-symbol>G01R1/00</valid-symbol></valid-symbol-list>", "G")
                checked = source_advisor.parse_answer(answer, store)
                self.assertTrue(checked["codes"][0]["official_catalog_verified"])
                self.assertFalse(checked["codes"][1]["official_catalog_verified"])
                self.assertFalse(checked["automatic_search"])
            finally:
                store.close()

    def test_only_verified_local_provider_can_answer(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / "source.sqlite3")
            try:
                providers = Mock()
                providers.list.return_value = [
                    {"id": "cloud", "type": "openrouter", "local_only_verified": False},
                    {"id": "local", "type": "openai", "local_only_verified": True,
                     "base_url": "http://127.0.0.1:11434/v1"}
                ]
                config = Mock()
                with patch("qnaplibrary.source_advisor.privacy.confidential_allowed",
                           side_effect=lambda provider, cfg: provider["id"] == "local"):
                    with self.assertRaises(ValueError):
                        source_advisor.advise("未公開の技術", "cloud", providers, config, store)
                    providers.chat.assert_not_called()
                    providers.chat.return_value = {
                        "content": '{"codes":["G01R"],"reason":"電気測定","clarify":""}', "model": "local-v1"}
                    response = source_advisor.advise(
                        "未公開の技術", "local", providers, config, store)
                    self.assertEqual(response["codes"][0]["code"], "G01R")
                    self.assertFalse(response["automatic_search"])
                    self.assertEqual(providers.chat.call_args.kwargs["scope"], "confidential")
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
