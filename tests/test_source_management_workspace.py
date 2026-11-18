"""K7a UI contracts: admin source management vs read-only ControlDeck bridge."""
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "qnaplibrary" / "web"


class Ids(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
    def handle_starttag(self, tag, attrs):
        value = dict(attrs).get("id")
        if value:
            self.ids.append(value)


class SourceManagementWorkspaceTests(unittest.TestCase):
    def test_admin_scoped_acquisition_has_explicit_user_consent(self):
        js = (WEB / "app.js").read_text("utf-8")
        for item in ('async function scopedSourceCard(main, connectors)',
                     '"/api/v1/source-plan"', '"/api/v1/source-acquisitions"',
                     '"/api/v1/source-storage?counts=1&breakdown=1"',
                     '"/api/v1/source-acquisitions?limit=20"',
                     "if (!approved.checked || !selectCode.value || !epoReady) return;",
                     '"public_only_confirmed: true"'.replace('"', ''),
                     'if (!confirm("確認済みの公開IPC・公開国・公開年だけをEPO OPSへ送信し、"',
                     '"allow_scheduled_collection: false"'.replace('"', '')):
            self.assertIn(item, js)
        self.assertIn('"source-acquisition"', (ROOT / "qnaplibrary" / "api.py").read_text("utf-8"))
        self.assertNotIn('eval(', js)
        self.assertNotIn('sourceFetchAutoRun', js)

    def test_host_source_panel_is_read_only_and_no_admin_proxy(self):
        js = (WEB / "addon-workspace.js").read_text("utf-8")
        html = (WEB / "addon-workspace.html").read_text("utf-8")
        server = (ROOT / "qnaplibrary" / "server.py").read_text("utf-8")
        parser = Ids()
        parser.feed(html)
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        for field in ("source-planning", "source-plan-form", "source-topic",
                      "source-plan-results", "source-storage-status", "source-breakdown",
                      "source-acquisition-receipts"):
            self.assertIn(field, parser.ids)
        for path in ("source-plan", "source-storage", "source-acquisitions"):
            self.assertIn("'" + path + "'", js)
        self.assertNotIn("api('source-acquisitions', {", js)
        self.assertIn('method == "GET" and path == "/addon/v1/source-acquisitions"', server)
        self.assertNotIn('path == "/addon/v1/source-acquisitions" and method == "POST"', server)
        self.assertNotIn(".innerHTML =", js)

    def test_office_year_scope_preview_is_read_only_and_requires_explicit_reapproval(self):
        admin = (WEB / "app.js").read_text("utf-8")
        host = (WEB / "addon-workspace.js").read_text("utf-8")
        html = (WEB / "addon-workspace.html").read_text("utf-8")
        bridge = (ROOT / "qnaplibrary" / "server.py").read_text("utf-8")
        for field in ('source-ipc-select', 'source-office', 'source-year-from',
                      'source-year-to', 'source-page-first', 'source-page-limit',
                      'source-scope-preview', 'source-scope-status'):
            self.assertIn('id="' + field + '"', html)
        self.assertIn('"/api/v1/source-scope/preview"', admin)
        self.assertIn("api('source-scope/preview'", host)
        self.assertIn('method == "POST" and path == "/addon/v1/source-scope/preview"', bridge)
        self.assertNotIn('method == "POST" and path == "/addon/v1/source-acquisitions"', bridge)
        self.assertIn('previewSignature', admin)
        self.assertIn('signature() !== previewSignature', admin)
        self.assertIn('approved.checked = false', admin)
        self.assertIn('publication_country: publicationCountry.value', admin)
        self.assertIn('first: Number(firstIndex.value)', admin)
        self.assertIn('"X-OPS-Range"', (ROOT / "qnaplibrary" / "connectors.py").read_text("utf-8"))


    def test_source_storage_limits_and_figure_worker_isolation(self):
        policy = (ROOT / "qnaplibrary" / "source_storage.py").read_text("utf-8")
        pdf = (ROOT / "qnaplibrary" / "pdf_extract.py").read_text("utf-8")
        worker = (ROOT / "qnaplibrary" / "pdf_figure_regions.py").read_text("utf-8")
        self.assertIn('("max_figures_per_pdf", 0, 12)', policy)
        self.assertIn('allow_scheduled_collection', policy)
        self.assertIn('subprocess.Popen(argv, stdin=subprocess.DEVNULL', pdf)
        self.assertIn('start_new_session=True', pdf)
        self.assertIn('resource.setrlimit(resource.RLIMIT_CPU', worker)
        self.assertIn('resource.setrlimit(resource.RLIMIT_AS', worker)
        self.assertNotIn('shell=True', pdf)
        self.assertNotIn('request.urlopen', worker)
        self.assertNotIn('openrouter', worker.lower())


if __name__ == "__main__":
    unittest.main()
