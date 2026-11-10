"""ControlDeck Feature bundle identity and archive safety (no release signing key)."""
import hashlib
import json
import runpy
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FeatureBundleTest(unittest.TestCase):
    def test_feature_package_and_addon_versions_match(self):
        feature = json.loads((ROOT / "control-deck-feature.json").read_text())
        addon = json.loads((ROOT / "addon.json").read_text())
        from qnaplibrary import VERSION

        self.assertEqual(feature["schema_version"], 1)
        self.assertEqual(feature["version"], VERSION)
        self.assertEqual(feature["feature_id"], addon["id"])
        self.assertEqual(addon["version"], VERSION)
        self.assertEqual(feature["health_url"], addon["runtime"]["base_url"] + addon["runtime"]["health_path"])
        self.assertEqual(feature["entrypoint"], "pb.sh")
        self.assertEqual(feature["service_args"], ["serve"])
        self.assertEqual(feature["smoke_args"], ["doctor"])
        self.assertEqual(feature["provision_args"], [])

    def test_bundle_contains_only_safe_release_sources(self):
        build = runpy.run_path(str(ROOT / "scripts/build_cd_feature.py"))["build"]
        with tempfile.TemporaryDirectory() as directory:
            result = build(Path(directory))
            self.assertFalse(result["signed"])
            path = Path(result["artifact"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), result["sha256"])
            with tarfile.open(path, "r:gz") as archive:
                members = archive.getmembers()
                self.assertGreater(len(members), 8)
                self.assertTrue(all(m.isfile() and not m.issym() and not m.islnk() for m in members))
                self.assertTrue(all(m.name.startswith("patent-buddy-" + result["version"] + "/") for m in members))
                names = {m.name.split("/", 1)[1]: m for m in members}
                for required in ("addon.json", "control-deck-feature.json", "pb.sh",
                                 "qnaplibrary/__init__.py", "qnaplibrary/server.py",
                                 "qnaplibrary/web/addon-workspace.html"):
                    self.assertIn(required, names)
                self.assertEqual(names["pb.sh"].mode, 0o755)
                self.assertFalse(any("secret" in n.lower() or "data/" in n or ".venv" in n
                                     or "__pycache__" in n for n in names))

    def test_bundle_is_reproducible(self):
        build = runpy.run_path(str(ROOT / "scripts/build_cd_feature.py"))["build"]
        with tempfile.TemporaryDirectory() as directory:
            a = build(Path(directory) / "a")
            b = build(Path(directory) / "b")
            self.assertEqual(a["sha256"], b["sha256"])


if __name__ == "__main__":
    unittest.main()
