"""Bounded USPTO ODP bulk metadata catalogue, not a bulk downloader."""
import json
import unittest
from unittest.mock import patch

from qnaplibrary import patent_bulk_catalog, source_probes
from tests.helpers import Client, LiveServer

FIXTURE = json.dumps({
    "count": 1,
    "bulkDataProductBag": [{
        "productIdentifier": "PTGRXML",
        "productTitleText": "Patent Grant Full-Text Data (No Images) - XML",
        "productFileBag": {
            "count": 2,
            "fileDataBag": [
                {"fileName": "ipg260101.zip", "fileSize": 18_100_000,
                 "fileTypeText": "ZIP",
                 "fileDataFromDate": "2026-01-01",
                 "fileDataToDate": "2026-01-01",
                 "fileReleaseDate": "2026-01-06T00:00:00",
                 "fileDownloadURI": "https://malicious.example/should-never-be-returned"},
                {"fileName": "ipg260108.zip", "fileSize": 690_000_000,
                 "fileTypeText": "ZIP", "fileDataFromDate": "2026-01-08"},
            ]
        }
    }]
}).encode()


class BoundedUSPTOBulkInventoryTests(unittest.TestCase):
    def test_known_products_are_pinned_and_without_bulk_execution(self):
        options = patent_bulk_catalog.product_options()
        self.assertEqual({x["id"] for x in options["products"]},
                         {"PTGRXML", "PTFWPRD", "PTFWPRE"})
        self.assertTrue(options["download_implemented"])
        self.assertTrue(options["bounded_staging_only"])
        self.assertFalse(options["archive_parse_implemented"])
        self.assertTrue(options["manual_only"])

    def test_official_fixed_url_and_api_key_in_header_only(self):
        with patch("qnaplibrary.patent_bulk_catalog.connectors.http_get",
                   return_value=FIXTURE) as get:
            result = patent_bulk_catalog.preview("fake-secret-key", product_id="PTGRXML",
                                                 limit=2, date_from="2026-01-01",
                                                 date_to="2026-01-31")
        self.assertEqual(result["files_previewed"], 2)
        self.assertEqual(result["file_bytes_total"], 708_100_000)
        self.assertTrue(result["files"][1]["over_advisory_cap"])
        self.assertTrue(result["no_files_downloaded"])
        self.assertTrue(result["no_data_stored"])
        self.assertNotIn("fileDownloadURI", str(result))
        self.assertNotIn("malicious.example", str(result))
        uri = get.call_args.args[0]
        self.assertTrue(uri.startswith("https://api.uspto.gov/api/v1/datasets/products/PTGRXML?"))
        self.assertIn("includeFiles=true", uri)
        self.assertIn("fileDataFromDate=2026-01-01", uri)
        self.assertNotIn("fake-secret-key", uri)
        self.assertEqual(get.call_args.kwargs["headers"]["X-API-KEY"], "fake-secret-key")

    def test_invalid_params_and_responses_fail_before_network(self):
        invalid = [
            {"api_key": "", "product_id": "PTGRXML"},
            {"api_key": "key", "product_id": "PTGRXML/../../foo"},
            {"api_key": "key", "product_id": "PTGRXML", "limit": 100},
            {"api_key": "key", "product_id": "PTGRXML", "limit": True},
            {"api_key": "key", "product_id": "PTGRXML", "date_from": "2026-01-01"},
            {"api_key": "key", "product_id": "PTGRXML",
             "date_from": "2025-01-01", "date_to": "2026-03-01"},
            {"api_key": "key\nx", "product_id": "PTGRXML"},
        ]
        for value in invalid:
            with self.subTest(value=value):
                with patch("qnaplibrary.patent_bulk_catalog.connectors.http_get") as http:
                    with self.assertRaises(ValueError):
                        patent_bulk_catalog.preview(**value)
                    http.assert_not_called()
        data = json.loads(FIXTURE.decode())
        for payload in (
            b"not-json",
            json.dumps({"bulkDataProductBag": []}).encode(),
            json.dumps({"bulkDataProductBag": [dict(data["bulkDataProductBag"][0],
                                                    productIdentifier="EVIL")]}).encode(),
            json.dumps({"bulkDataProductBag": [{
                "productIdentifier": "PTGRXML",
                "productFileBag": {"fileDataBag": [
                    {"fileName": "../evil.zip", "fileSize": 120}]}
            }]}).encode(),
            json.dumps({"bulkDataProductBag": [{
                "productIdentifier": "PTGRXML",
                "productFileBag": {"fileDataBag": [
                    {"fileName": "ok.zip", "fileSize": True}]}
            }]}).encode(),
        ):
            with self.subTest(payload=payload[:70]):
                with self.assertRaises(ValueError):
                    patent_bulk_catalog.normalize_payload(payload, "PTGRXML", 2)
        with self.assertRaises(ValueError):
            patent_bulk_catalog.normalize_payload(FIXTURE, "PTGRXML", 1)
        with self.assertRaises(ValueError):
            patent_bulk_catalog.normalize_payload(b" "*(2*1024*1024+1), "PTGRXML", 2)

    def test_preview_is_admin_only_and_does_not_write_database(self):
        server = LiveServer()
        try:
            admin = Client(server.base)
            admin.login_setup()
            reader = Client(server.base)
            reader.token = server.app.auth.local_token()
            anon = Client(server.base)
            request = {"product": "PTGRXML", "limit": 2, "confirmed": True}
            self.assertEqual(anon.call("POST", "/api/v1/uspto-bulk/preview", request)[0], 401)
            self.assertEqual(reader.call("POST", "/api/v1/uspto-bulk/preview", request)[0], 403)
            self.assertEqual(admin.call("POST", "/api/v1/uspto-bulk/preview",
                                        dict(request, confirmed=False))[0], 400)
            self.assertEqual(admin.call("POST", "/api/v1/uspto-bulk/preview",
                                        dict(request, url="https://evil"))[0], 400)
            self.assertEqual(admin.call("POST", "/api/v1/uspto-bulk/preview", request)[0], 400)
            before = server.app.store.one("SELECT count(*) FROM documents")[0]
            server.app.config.set_secret("uspto_api_key", "test-secret")
            with patch("qnaplibrary.patent_bulk_catalog.connectors.http_get",
                       return_value=FIXTURE) as http:
                code, result = admin.call("POST", "/api/v1/uspto-bulk/preview", request)
            self.assertEqual(code, 200, result)
            self.assertEqual(result["files_previewed"], 2)
            self.assertEqual(server.app.store.one("SELECT count(*) FROM documents")[0], before)
            self.assertTrue(http.called)
            status, offline = reader.call("GET", "/api/v1/uspto-bulk/options")
            self.assertEqual(status, 200, offline)
            self.assertFalse(offline["download_implemented"])
        finally:
            server.close()

    def test_single_source_probe_can_preview_without_archives(self):
        with patch("qnaplibrary.patent_bulk_catalog.preview",
                   return_value={"files_previewed": 1}) as preview:
            result = source_probes.probe("uspto_bulk_catalog", lambda k: "example-test-key")
        self.assertTrue(result["success"])
        self.assertTrue(result["no_data_written"])
        self.assertEqual(preview.call_args.kwargs["product_id"], "PTFWPRD")
        self.assertEqual(preview.call_args.kwargs["limit"], 1)


if __name__ == "__main__":
    unittest.main()
