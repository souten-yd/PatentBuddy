"""Verify the one-time update bridge keeps QPKG identity and new update destination."""
import unittest
from pathlib import Path
import qnaplibrary
from qnaplibrary.updater import asset_name, API

ROOT = Path(__file__).resolve().parents[1]


class UpdateChannelBridgeTest(unittest.TestCase):
    def test_target(self):
        self.assertEqual(qnaplibrary.VERSION, "0.5.13")
        self.assertEqual(qnaplibrary.REPO, "souten-yd/ResearchDataHub")
        self.assertIn("/souten-yd/ResearchDataHub/releases/latest", API)

    def test_legacy_asset_identity(self):
        self.assertEqual(qnaplibrary.DEFAULT_PORT, 17871)
        self.assertEqual(asset_name(qnaplibrary.VERSION, "qpkg"), "QnapLibrary_0.5.13_x86_64.qpkg")
        self.assertEqual(asset_name(qnaplibrary.VERSION, "linux"), "qnaplibrary-0.5.13-linux.tar.gz")
        cfg=(ROOT/"qpkg/qpkg.cfg").read_text()
        self.assertIn('QPKG_NAME="QnapLibrary"', cfg)
        self.assertIn('QPKG_VER="0.5.13"', cfg)


if __name__ == "__main__":
    unittest.main()
