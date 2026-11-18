"""Offline checks for the real, manually pinned 2026-11 public patent pilot.

Public source HTML is not distributed. The fixture has only small factual
metadata extracted in a one-shot GitHub Actions test, plus its SHA-256 digests.
"""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import patent_public_sample_report as pilot

FIXTURE = Path(__file__).parent / "fixtures" / "k7a_public_patents_20261118.json"


class PublicPatentPilotTests(unittest.TestCase):
    def test_real_public_records_are_unique_traceable_and_non_confidential(self):
        fixture = json.loads(FIXTURE.read_text("utf-8"))
        self.assertEqual(fixture["sample_id"], "K7a-public-patent-pilot-2026-11-18")
        self.assertEqual(len(fixture["records"]), 11)
        self.assertEqual(sum(r["classification_count"] for r in fixture["records"]), 231)
        self.assertEqual(sum(r["dc_relation_count"] for r in fixture["records"]), 164)
        identifiers = [r["publication"] for r in fixture["records"]]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertTrue(set(identifiers) <= set(pilot.PUBLIC_IDS))
        for row in fixture["records"]:
            with self.subTest(doc=row["publication"]):
                self.assertTrue(pilot.ALLOWED_ID.fullmatch(row["publication"]))
                self.assertEqual(row["url"], pilot.BASE + row["publication"] + "/en")
                self.assertTrue(row["title"].strip())
                self.assertEqual(len(row["sha256_of_downloaded_html"]), 64)
                self.assertGreater(row["html_bytes"], 10000)
                self.assertTrue(row["publication_date"].startswith(("20", "19")))
                self.assertNotIn("body", row)
                self.assertNotIn("claims", row)
                self.assertNotIn("credentials", row)

    def test_offline_parser_keeps_only_metadata_not_full_description(self):
        html = (b'<html><head><meta name="DC.title" content="Common-mode choke converter">'
                b'<meta name="DC.date" content="2021-01-02">'
                b'<meta name="DC.date" content="2022-02-03">'
                b'<meta name="DC.contributor" content="Some Inventor">'
                b'<meta name="DC.relation" content="US:1234567:B2"></head>'
                b'<span itemprop="Code">H02M1/44</span>'
                b'<div itemprop="abstract">This common mode filter is connected to an inverter.</div>'
                b'<tr itemprop="forwardReferencesFamily"></tr>'
                b'<span itemprop="thumbnail"></span></html>')
        result = pilot.parse_one("US11996769B2", html)
        self.assertEqual(result["publication_date"], "2022-02-03")
        self.assertEqual(result["first_dc_date"], "2021-01-02")
        self.assertEqual(result["subclass_codes"], ["H02M"])
        self.assertEqual(result["dc_contributors_sample_unverified"], ["Some Inventor"])
        self.assertEqual(result["references_metadata_count"], 1)
        self.assertEqual(result["forward_reference_rows"], 1)
        self.assertEqual(result["figure_thumbnail_rows"], 1)
        self.assertIn("共通モード", result["topic_indicators"])
        self.assertNotIn("abstract", result)
        self.assertNotIn("body", result)

    def test_fixed_public_urls_and_explicit_fetch_only(self):
        self.assertLessEqual(len(pilot.PUBLIC_IDS), pilot.MAX_RECORDS)
        self.assertEqual(len(pilot.PUBLIC_IDS), len(set(pilot.PUBLIC_IDS)))
        for candidate in (
            "https://example.org", "../US11996769B2", "US11996769B2?foo",
            "US11996769B2/../../", "EP0401234B2",
        ):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                pilot.download_once(candidate, None)
        self.assertEqual(pilot.PACING_SEC, 2.5)
        with patch.object(pilot.urllib.request, "urlopen") as transport:
            pilot.parse_one("US11996769B2",
                            b'<meta name="DC.title" content="Public inventor title">')
            transport.assert_not_called()


if __name__ == "__main__":
    unittest.main()
