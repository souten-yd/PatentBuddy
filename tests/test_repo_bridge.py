"""Verify the one-time update bridge keeps QPKG identity and new update destination."""
import unittest
from pathlib import Path
import qnaplibrary
from qnaplibrary.updater import asset_name, API

ROOT = Path(__file__).resolve().parents[1]


class UpdateChannelBridgeTest(unittest.TestCase):
    def test_target(self):
        self.assertGreaterEqual(tuple(map(int, qnaplibrary.VERSION.split("."))), (0, 5, 13))
        self.assertEqual(qnaplibrary.REPO, "souten-yd/ResearchDataHub")
        self.assertIn("/souten-yd/ResearchDataHub/releases/latest", API)

    def test_legacy_asset_identity(self):
        self.assertEqual(qnaplibrary.DEFAULT_PORT, 17871)
        self.assertEqual(asset_name(qnaplibrary.VERSION, "qpkg"), f"QnapLibrary_{qnaplibrary.VERSION}_x86_64.qpkg")
        self.assertEqual(asset_name(qnaplibrary.VERSION, "linux"), f"qnaplibrary-{qnaplibrary.VERSION}-linux.tar.gz")
        cfg=(ROOT/"qpkg/qpkg.cfg").read_text()
        self.assertIn('QPKG_NAME="QnapLibrary"', cfg)
        self.assertIn(f'QPKG_VER="{qnaplibrary.VERSION}"', cfg)


if __name__ == "__main__":
    unittest.main()
