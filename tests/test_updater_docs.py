import hashlib
import io
import os
import re
import tarfile
import tempfile
import unittest
from pathlib import Path

import qnaplibrary
from qnaplibrary import updater

ROOT = Path(__file__).resolve().parents[1]


def release(tag, name, data=b"x" * 10, **kw):
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    return dict({"tag_name": tag, "draft": False, "prerelease": False, "assets": [{
        "name": name, "digest": digest, "size": len(data),
        "browser_download_url": "https://github.com/%s/releases/download/%s/%s" % (qnaplibrary.REPO, tag, name)}]}, **kw)


class UpdaterTest(unittest.TestCase):
    def test_select(self):
        a = updater.select(release("v9.0.0", "qnaplibrary-9.0.0-linux.tar.gz"), "0.1.0", "linux")
        self.assertEqual(a["version"], "9.0.0")
        self.assertIsNone(updater.select(release("v0.0.9", "qnaplibrary-0.0.9-linux.tar.gz"), "0.1.0", "linux"))
        self.assertIsNone(updater.select(release("v9.0.0", "x", prerelease=True), "0.1.0", "linux"))
        with self.assertRaises(ValueError):
            updater.select(release("v9.0.0", "other.tar.gz"), "0.1.0", "linux")
        q = updater.select(release("v9.0.0", "QnapLibrary_9.0.0_x86_64.qpkg"), "0.1.0", "qpkg")
        self.assertTrue(q["name"].endswith(".qpkg"))
        bad = release("v9.0.0", "qnaplibrary-9.0.0-linux.tar.gz")
        bad["assets"][0]["browser_download_url"] = "https://evil.example/x"
        with self.assertRaises(ValueError):
            updater.select(bad, "0.1.0", "linux")

    def test_safe_extract_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as d:
            tar_path = os.path.join(d, "a.tar.gz")
            with tarfile.open(tar_path, "w:gz") as t:
                info = tarfile.TarInfo("../evil")
                info.size = 1
                t.addfile(info, io.BytesIO(b"x"))
            with self.assertRaises(ValueError):
                updater.safe_extract(tar_path, os.path.join(d, "out"))

    def test_linux_apply_switches_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "inst"
            (root / "versions" / "0.1.0").mkdir(parents=True)
            os.symlink("versions/0.1.0", str(root / "current"))
            tar_path = Path(d) / "pkg.tar.gz"
            with tarfile.open(str(tar_path), "w:gz") as t:
                t.add(str(ROOT / "qnaplibrary"), arcname="qnaplibrary-9.9.9/qnaplibrary",
                      filter=lambda i: None if "__pycache__" in i.name else i)
            u = updater.Updater.__new__(updater.Updater)
            u.root, u.shutdown, u.state, u._lock = root, None, {}, __import__("threading").Lock()
            u._apply_linux(tar_path, "9.9.9")
            self.assertEqual(os.readlink(str(root / "current")), os.path.join("versions", "9.9.9"))
            self.assertTrue((root / "versions" / "9.9.9" / "qnaplibrary" / "server.py").is_file())


class DocsRulesTest(unittest.TestCase):
    def test_versions_aligned(self):
        cfg = (ROOT / "qpkg" / "qpkg.cfg").read_text()
        self.assertIn('QPKG_VER="%s"' % qnaplibrary.VERSION, cfg)
        first = re.search(r"^## v(\S+)", (ROOT / "CHANGELOG.md").read_text(), re.M).group(1)
        self.assertEqual(first, qnaplibrary.VERSION)

    def test_handoff_rules_exist(self):
        for f in ("AGENTS.md", "CLAUDE.md", "DEVELOPMENT_WORKFLOW.md", "docs/HANDOFF.md", "docs/feasibility.md"):
            self.assertTrue((ROOT / f).is_file(), f)
        self.assertIn(qnaplibrary.VERSION, (ROOT / "docs" / "HANDOFF.md").read_text())

    def test_only_release_workflow(self):
        flows = sorted(p.name for p in (ROOT / ".github" / "workflows").glob("*.y*ml"))
        self.assertEqual(flows, ["release.yml"])
        text = (ROOT / ".github" / "workflows" / "release.yml").read_text()
        on = text.split("\non:", 1)[1].split("permissions:", 1)[0]
        self.assertNotIn("pull_request", on)
        # only merges to main that change the version file may trigger it
        self.assertIn('branches: [main]', on)
        self.assertIn('paths: ["qnaplibrary/__init__.py"]', on)

    def test_readme_has_no_version_history(self):
        readme = (ROOT / "README.md").read_text()
        self.assertNotRegex(readme, r"(?m)^#+ .*v\d+\.\d+\.\d+")


if __name__ == "__main__":
    unittest.main()
