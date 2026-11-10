import runpy
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class IosIconTest(unittest.TestCase):
    def test_generated_icon_matches_committed_asset(self):
        generator = runpy.run_path(str(ROOT / "scripts/make-icons.py"))["png"]
        expected = generator(180, ios=True)
        self.assertEqual((ROOT / "qnaplibrary/web/apple-touch-icon.png").read_bytes(), expected)
        self.assertEqual(expected[:8], bytes.fromhex("89504e470d0a1a0a"))

    def test_html_has_home_screen_metadata(self):
        html = (ROOT / "qnaplibrary/web/index.html").read_text()
        self.assertIn('rel="apple-touch-icon"', html)
        self.assertIn('href="/apple-touch-icon.png"', html)
        self.assertIn('name="apple-mobile-web-app-title"', html)


if __name__ == "__main__":
    unittest.main()
