"""K7a EPO source scope and official result-window contracts (offline/mock only)."""
import unittest
from unittest.mock import patch
from qnaplibrary import connectors, source_scope
from tests.helpers import LiveServer, Client


class ScopeBuilderTests(unittest.TestCase):
    def test_office_year_and_page_cql_is_fixed_not_user_text(self):
        plan = source_scope.build_scope(
            ipc="H02M", publication_country="JP", year_from=2020,
            year_to=2025, first=26, limit=25)
        self.assertEqual(plan["cql"],
            'ic=H02M and pn=JP and pd within "20200101 20251231"')
        self.assertEqual((plan["first_result"], plan["last_result"]), (26, 50))
        self.assertEqual(plan["date_basis"], "publication_date")
        self.assertFalse(plan["query_sends_topic_text"])
        self.assertEqual(source_scope.build_scope(ipc="H02M", limit=1)["cql"], "ic=H02M")
        self.assertEqual(source_scope.build_scope(ipc="H02M", first=2000, limit=1)["last_result"], 2000)

    def test_rejects_unsupported_country_year_and_cql_injection(self):
        values = [
            {"ipc": "H02M OR ta=secret"},
            {"ipc": "H02M", "publication_country": "JP OR US"},
            {"ipc": "H02M", "publication_country": "ZZ"},
            {"ipc": "H02M", "year_from": 2020},
            {"ipc": "H02M", "year_to": 2025},
            {"ipc": "H02M", "year_from": 2010, "year_to": 2025},
            {"ipc": "H02M", "year_from": True, "year_to": 2020},
            {"ipc": "H02M", "year_from": 2027, "year_to": 2030},
            {"ipc": "H02M", "first": 1990, "limit": 25},
            {"ipc": "H02M", "first": 0},
            {"ipc": "H02M", "first": "26"},
            {"ipc": "H02M", "limit": 26},
            {"ipc": "H02M", "limit": True},
        ]
        for data in values:
            with self.subTest(data=data), self.assertRaises(ValueError):
                source_scope.build_scope(**data)

    def test_scoped_api_requires_explicit_admin_consent(self):
        server = LiveServer()
        try:
            admin = Client(server.base); admin.login_setup()
            ro = Client(server.base); ro.token = server.app.auth.local_token()
            anon = Client(server.base)
            value = {"ipc": "H02M", "publication_country": "JP",
                     "year_from": 2020, "year_to": 2025, "first": 26, "limit": 2}
            self.assertEqual(anon.call("POST", "/api/v1/source-scope/preview", value)[0], 401)
            with patch("qnaplibrary.connectors.epo_search", side_effect=AssertionError("must not run")):
                code, plan = ro.call("POST", "/api/v1/source-scope/preview", value)
            self.assertEqual(code, 200, plan)
            self.assertIn("pn=JP", plan["cql"])
            self.assertEqual(ro.call("POST", "/api/v1/source-scope/preview",
                                     dict(value, cql="ta=unpublished"))[0], 400)
            self.assertEqual(ro.call("POST", "/api/v1/source-acquisitions",
                                     dict(value, public_only_confirmed=True))[0], 403)
            self.assertEqual(admin.call("POST", "/api/v1/source-acquisitions",
                                        dict(value, public_only_confirmed=False))[0], 400)
            with patch("qnaplibrary.connectors.epo_search", return_value=[
                {"id": "JP202501A", "title": "Test", "source": "EPO OPS"}]) as search:
                code, result = admin.call("POST", "/api/v1/source-acquisitions",
                                          dict(value, public_only_confirmed=True))
            self.assertEqual(code, 200, result)
            self.assertEqual(result["scope"]["publication_country"], "JP")
            self.assertEqual(result["scope"]["publication_year_to"], 2025)
            self.assertEqual(search.call_args.args[0], plan["cql"])
            self.assertEqual(search.call_args.kwargs, {"start": 26})
            self.assertEqual(result["next_first_result_hint"], None)
            history = ro.call("GET", "/api/v1/source-acquisitions")[1]["items"][0]
            self.assertEqual(history["publication_country"], "JP")
            self.assertEqual(history["publication_year_from"], 2020)
            self.assertEqual(history["first_result"], 26)
        finally:
            server.close()


class EpoConnectorContracts(unittest.TestCase):
    def test_page_range_header_and_literal_cql(self):
        payload = {"ops:world-patent-data": {
            "ops:biblio-search": {"ops:search-result": {"exchange-documents": {
                "exchange-document": [
                    {"@country": "JP", "@doc-number": "123", "@kind": "A1",
                     "bibliographic-data": {"invention-title": {"@lang": "en", "$": "Motor inverter"}}},
                    {"@country": "JP", "@doc-number": "124", "@kind": "A1",
                     "bibliographic-data": {"invention-title": {"@lang": "en", "$": "Power converter"}}},
                ]}}}}}
        self.assertEqual(len(connectors._epo_docs(payload)), 2)
        self.assertEqual(connectors._epo_docs(payload)[0]["id"], "JP123A1")
        self.assertEqual(len(connectors._epo_docs({"ops:world-patent-data":
               {"ops:biblio-search": {"ops:search-result": {}}}})), 0)
        with self.assertRaises(connectors.ConnectorError):
            connectors._epo_docs({"ops:world-patent-data": {}})
        import json
        with patch.object(connectors, "_epo_auth", return_value="public-fake-token"), patch.object(
                connectors, "http_get", return_value=json.dumps(payload).encode()) as get:
            result = connectors.epo_search("ic=H02M and pn=JP", "key", "secret", 2, start=26)
        self.assertEqual(len(result), 2)
        self.assertEqual(get.call_args.kwargs["headers"]["X-OPS-Range"], "26-27")
        self.assertIn("q=ic%3DH02M", get.call_args.args[0])
        self.assertNotIn("Range=", get.call_args.args[0])
        for start, limit in [(0, 1), (2000, 25), (True, 10), (1, "invalid")]:
            with self.assertRaises(connectors.ConnectorError):
                connectors.epo_search("ic=H02M", "key", "secret", limit, start=start)
        with patch.object(connectors, "_epo_auth", return_value="fake"), patch.object(
                connectors, "http_get", return_value=json.dumps(payload).encode()) as get:
            connectors.epo_search("ic=H02M", "key", "secret", "5")
        self.assertEqual(get.call_args.kwargs["headers"]["X-OPS-Range"], "1-5")


if __name__ == "__main__":
    unittest.main()
