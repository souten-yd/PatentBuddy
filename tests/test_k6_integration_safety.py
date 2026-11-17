"""K6 integration guardrails for the staged K1a–K5 release train.

These are inexpensive source contracts; the real HTTP/SQLite tests and
scripts/verify-k6.sh are still required before any main merge/release.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(path):
    return (ROOT / path).read_text(encoding='utf-8')


class K6IntegrationSafetyTests(unittest.TestCase):
    def test_standard_verifier_checks_both_web_entrypoints(self):
        script = source('scripts/verify.sh')
        self.assertIn('node --check qnaplibrary/web/app.js', script)
        self.assertIn('node --check qnaplibrary/web/addon-workspace.js', script)
        self.assertIn('python3 -m unittest discover -s tests -t . -q', script)
        gate = source('scripts/verify-k6.sh')
        self.assertIn('bash scripts/verify.sh', gate)
        self.assertIn('bash scripts/build-linux.sh dist', gate)
        self.assertIn('WITH_QPKG', gate)
        self.assertIn('QPKG: NOT TESTED', gate)

    def test_k4_k5_are_backed_by_the_existing_store_only(self):
        from qnaplibrary import knowledge_cross_search, idea_canvas
        for mod in (knowledge_cross_search, idea_canvas):
            filename = Path(mod.__file__)
            text = filename.read_text(encoding='utf-8')
            self.assertNotIn('sqlite3.connect', text)
            self.assertNotIn('subprocess.', text)
            self.assertNotIn('os.system(', text)
        self.assertIn('with store.tx() as db:', source('qnaplibrary/idea_canvas.py'))
        self.assertIn('with store.lock:', source('qnaplibrary/knowledge_cross_search.py'))
        tables = source('qnaplibrary/store.py')
        self.assertIn('CREATE TABLE IF NOT EXISTS idea_drafts(', tables)
        self.assertIn('CREATE TABLE IF NOT EXISTS idea_versions(', tables)
        self.assertIn('CREATE TABLE IF NOT EXISTS idea_sources(', tables)

    def test_only_manually_requested_idea_mutations_are_allowed(self):
        routes = source('qnaplibrary/api.py')
        self.assertIn('@route("POST", "/api/v1/ideas", "idea_write")', routes)
        self.assertIn('@route("PUT", "/api/v1/ideas/{iid}", "idea_write")', routes)
        self.assertIn('@route("GET", "/api/v1/ideas", "read")', routes)
        self.assertIn('@route("GET", "/api/v1/ideas/{iid}/versions/{ver}", "read")',
                      routes)
        server = source('qnaplibrary/server.py')
        self.assertIn('req.device["scopes"] == "idea_write"', server)
        self.assertIn('method in ("POST", "PUT") and access == "idea_write"', server)
        self.assertIn('access == "idea_write" and req.actor != "admin"', server)
        client = source('qnaplibrary/addon_client.py')
        self.assertIn("config.get('idea_write_token')", client)
        self.assertIn("'idea_write_available': self.idea_write_ready()", client)

    def test_version_history_and_stale_approvals_fail_closed(self):
        code = source('qnaplibrary/idea_canvas.py')
        for critical in ('source_revision', 'source_epoch', 'review_seq',
                         'confirm_manual', 'expected_version',
                         "if latest['stale']:", "return {'id': identifier",
                         "version': expected + 1", 'get_version(store, identifier, version)'):
            self.assertIn(critical, code)
        self.assertIn('knowledge approval or source changed; compare again', code)
        self.assertIn("'state': 'needs_revalidation' if stale else 'manual_draft'", code)

    def test_main_user_interface_not_replaced_by_addon_features(self):
        # RDH management remains its own index.html. The embedded ControlDeck
        # workspace has no standalone login shell, execution or external CDN.
        server = source('qnaplibrary/server.py')
        self.assertIn('index.html', server)
        workspace = source('qnaplibrary/web/addon-workspace.js')
        html = source('qnaplibrary/web/addon-workspace.html')
        self.assertIn('control-deck-addon.connect', workspace)
        self.assertNotIn('.innerHTML =', workspace)
        self.assertNotIn('idea_write_token', workspace)
        self.assertIn('id="idea-confirm"', html)
        self.assertNotIn('<h1>PatentBuddy</h1>', html)


if __name__ == '__main__':
    unittest.main()
