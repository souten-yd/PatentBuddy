"""K7a source smoke checks: no credentials until installation, no secret echo."""
import json
import unittest
from unittest.mock import patch

from qnaplibrary import connectors, official_ipc_titles, source_probes
from tests.helpers import LiveServer, Client

WIPO_TITLE_SAMPLE = (
    "H\tELECTRICITY\n"
    "H02\tGENERATION, CONVERSION, OR DISTRIBUTION OF ELECTRIC POWER\n"
    "H02M\tAPPARATUS FOR CONVERSION BETWEEN AC AND AC, DC AND DC, OR AC AND DC\n"
    "H02M0001440000\tVery long group title with continuation\n"
    "wrapped group description that is not another tab-separated row\n"
).encode("utf-8")
OPENALEX_SAMPLE = json.dumps({"meta": {"count": 1}, "results": [
    {"id": "https://openalex.org/W123456", "title": "Inverter circuit analysis",
     "publication_year": 2025, "publication_date": "2025-03-17",
     "doi": "https://doi.org/10.1234/example", "cited_by_count": 12,
     "authorships": [{"author": {"display_name": "Researcher A"}}],
     "referenced_works": ["https://openalex.org/W234567"],
     "primary_location": None},
]}).encode("utf-8")


class OpenAlexSourceTests(unittest.TestCase):
    def test_first_page_public_metadata_without_key(self):
        with patch("qnaplibrary.connectors.http_get", return_value=OPENALEX_SAMPLE) as get:
            result = connectors.openalex_works("inverter", "", limit=1,
                                              year_from=2023, year_to=2025)
        self.assertEqual(len(result), 1)
        item = result[0]
        self.assertEqual(item["id"], "openalex:W123456")
        self.assertEqual(item["meta"]["authors"], ["Researcher A"])
        self.assertEqual(item["meta"]["referenced_works_sample"],
                         ["https://openalex.org/W234567"])
        self.assertEqual(item["meta"]["cited_by_count"], 12)
        self.assertTrue(item["meta"]["metadata_only"])
        self.assertNotIn("api_key=", get.call_args.args[0])
        self.assertIn("per-page=1", get.call_args.args[0])
        self.assertIn("from_publication_date%3A2023", get.call_args.args[0])
        self.assertEqual(get.call_args.kwargs["pace"], 2.0)

    def test_key_is_opt_in_and_invalid_requests_never_leave_pc(self):
        with patch("qnaplibrary.connectors.http_get", return_value=OPENALEX_SAMPLE) as get:
            connectors.openalex_works("inverter", "fake-local-unit-test-key", limit=1)
        self.assertIn("api_key=fake-local-unit-test-key", get.call_args.args[0])
        for args in ({"query": ""},
                     {"query": "unpublished\nsecret"},
                     {"query": "inverter", "limit": 200},
                     {"query": "inverter", "year_from": 2000},
                     {"query": "inverter", "year_from": 2010, "year_to": 2025}):
            with self.subTest(args=args), patch("qnaplibrary.connectors.http_get") as no_network:
                with self.assertRaises(connectors.ConnectorError):
                    connectors.openalex_works(**args)
                no_network.assert_not_called()
        with patch("qnaplibrary.connectors.http_get",
                   return_value=b'{"results": "not-an-array"}'):
            with self.assertRaises(connectors.ConnectorError):
                connectors.openalex_works("inverter", limit=1)

    def test_catalog_has_paper_connector_and_optional_key(self):
        entry = next(x for x in connectors.CATALOG if x["id"] == "openalex")
        self.assertEqual(entry["kind"], "paper")
        self.assertIsNone(entry["key"])


class WIPOActualFormatFixtureTests(unittest.TestCase):
    def test_official_title_section_class_subclass_and_wrapped_group(self):
        names = official_ipc_titles.parse_titles(WIPO_TITLE_SAMPLE, "H")
        self.assertEqual(set(names), {"H", "H02", "H02M"})
        self.assertIn("CONVERSION", names["H02M"])
        self.assertNotIn("H02M0001440000", names)
        with self.assertRaises(ValueError):
            official_ipc_titles.parse_titles(WIPO_TITLE_SAMPLE, "F")
        with self.assertRaises(ValueError):
            official_ipc_titles.parse_titles(b"H\tElectricity", "H")
        with self.assertRaises(ValueError):
            official_ipc_titles.parse_titles(b"\x00"+WIPO_TITLE_SAMPLE, "H")


class ManualSourceTestAPITests(unittest.TestCase):
    def test_readiness_requires_key_but_not_registration_now(self):
        result = source_probes.readiness(lambda name: "")
        byid = {item["id"]: item for item in result["items"]}
        self.assertFalse(byid["epo_ops"]["configured"])
        self.assertTrue(byid["wipo_ipc_titles"]["configured"])
        self.assertTrue(byid["openalex"]["configured"])
        self.assertFalse(byid["jpo"]["last_live_tested"])

    def test_probe_does_not_save_and_filters_provider_error(self):
        no_key = source_probes.probe("epo_ops", lambda name: "")
        self.assertEqual(no_key["status"], "requires_key_at_install")
        with patch("qnaplibrary.source_probes.connectors.http_get",
                   return_value=WIPO_TITLE_SAMPLE) as call:
            result = source_probes.probe("wipo_ipc_titles", lambda name: "", section="H")
        self.assertEqual(result["status"], "sample_verified")
        self.assertEqual(result["received"], 3)
        self.assertTrue(result["no_data_written"])
        self.assertIn("EN_ipc_section_H", call.call_args.args[0])
        with patch("qnaplibrary.source_probes.connectors.epo_search",
                   return_value=[{"id": "EP1"}]) as call:
            result = source_probes.probe("epo_ops", lambda name: "mock-key")
        self.assertEqual(result["status"], "sample_verified")
        self.assertEqual(call.call_args.args[0], "ic=H02M and pn=EP")
        with patch("qnaplibrary.source_probes.connectors.epo_search",
                   side_effect=connectors.ConnectorError("secret_token_should_not_echo")):
            result = source_probes.probe("epo_ops", lambda name: "mock-key")
        self.assertNotIn("secret_token_should_not_echo", str(result))
        self.assertEqual(result["reason_code"], "provider_or_schema_error")
        with patch("qnaplibrary.source_probes.connectors.jpo_progress") as call:
            result = source_probes.probe("jpo", lambda name: "mock-key")
        self.assertEqual(result["reason_code"], "sample_required")
        call.assert_not_called()
        with patch("qnaplibrary.source_probes.connectors.uspto_search",
                   return_value=[{"id": "US1"}]) as call:
            result = source_probes.probe("uspto", lambda name: "mock-key")
        self.assertTrue(result["success"])
        self.assertEqual(call.call_args.args[0], "inverter")

    def test_live_server_auth_and_bounded_manual_sample(self):
        server = LiveServer()
        try:
            admin = Client(server.base)
            admin.login_setup()
            read = Client(server.base)
            read.token = server.app.auth.local_token()
            anon = Client(server.base)
            self.assertEqual(anon.call("GET", "/api/v1/source-tests")[0], 401)
            status, options = read.call("GET", "/api/v1/source-tests")
            self.assertEqual(status, 200, options)
            self.assertIn("wipo_ipc_titles", [x["id"] for x in options["items"]])
            request = {"source": "wipo_ipc_titles", "section": "H", "confirmed": True}
            self.assertEqual(read.call("POST", "/api/v1/source-tests/run", request)[0], 403)
            self.assertEqual(admin.call("POST", "/api/v1/source-tests/run",
                                        dict(request, confirmed=False))[0], 400)
            initial = server.app.store.one("SELECT count(*) FROM documents")[0]
            with patch("qnaplibrary.source_probes.connectors.http_get",
                       return_value=WIPO_TITLE_SAMPLE):
                code, result = admin.call("POST", "/api/v1/source-tests/run", request)
            self.assertEqual(code, 200, result)
            self.assertEqual(result["received"], 3)
            self.assertTrue(result["no_data_written"])
            self.assertEqual(server.app.store.one("SELECT count(*) FROM documents")[0], initial)
        finally:
            server.close()


if __name__ == "__main__":
    unittest.main()
