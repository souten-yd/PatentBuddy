import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class HomeUiTest(unittest.TestCase):
    def test_compact_kpis_and_optional_technical_details(self):
        app = (ROOT / "qnaplibrary/web/app.js").read_text()
        css = (ROOT / "qnaplibrary/web/style.css").read_text()
        home = app.split("// ---------- home ----------", 1)[1].split("// ---------- search ----------", 1)[0]
        self.assertIn('"home-kpis"', home)
        self.assertIn('"文書", s.documents', home)
        self.assertIn('"コレクション", s.collections', home)
        self.assertIn('"特許案件", s.patents', home)
        self.assertIn('h("details", { class: "card home-technical" }', home)
        self.assertIn('if (deadlines.length)', home)
        self.assertIn(".home-kpis{grid-template-columns:repeat(2,minmax(0,1fr))", css)

    def test_processing_status_is_read_only_and_polled_only_on_home(self):
        app = (ROOT / "qnaplibrary/web/app.js").read_text()
        home = app.split("// ---------- home ----------", 1)[1].split("// ---------- search ----------", 1)[0]
        for path in ("/api/llm/embedding", "/api/v1/research", "/api/update/status", "/api/vectors/backend"):
            self.assertIn('api("GET", "' + path, home)
        self.assertIn('main.isConnected && S.view === "home"', home)
        self.assertIn('refreshActivity()', home)
        self.assertNotIn('api("POST"', home)
        self.assertNotIn('api("PUT"', home)
        self.assertNotIn('api("DELETE"', home)


if __name__ == "__main__":
    unittest.main()
