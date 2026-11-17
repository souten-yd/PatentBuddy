"""K2 review UX stays inside ControlDeck's embedded knowledge card surface."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'qnaplibrary' / 'web'


class KnowledgeReviewWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (ROOT / 'addon-workspace.js').read_text(encoding='utf-8')
        cls.css = (ROOT / 'addon-workspace.css').read_text(encoding='utf-8')
        cls.html = (ROOT / 'addon-workspace.html').read_text(encoding='utf-8')

    def test_requires_explicit_user_choice_and_active_permission(self):
        self.assertIn('reviewAllowed = ready && s.knowledge_review_available === true', self.js)
        self.assertIn('if (!reviewAllowed || snapshot.stale)', self.js)
        self.assertIn("const submit = document.createElement('button')", self.js)
        self.assertIn('submit.disabled = true', self.js)
        self.assertIn('choice.onchange', self.js)
        self.assertIn('const reviewPanel = document.createElement', self.js)
        self.assertIn("'approved'", self.js)
        self.assertIn("'rejected'", self.js)
        self.assertIn("'changes_requested'", self.js)
        self.assertIn("source_revision: snapshot.source_revision", self.js)

    def test_review_request_is_idempotent_and_never_auto_approved(self):
        self.assertIn("crypto.randomUUID().replaceAll('-', '')", self.js)
        self.assertIn("if (!pending || pending.decision !== choice.value)", self.js)
        self.assertIn('request_id: pending.id', self.js)
        self.assertIn('await api(', self.js)
        self.assertIn("'/reviews'", self.js)
        self.assertIn('review?.status', self.js)
        self.assertIn('AI推論', self.js)
        self.assertIn('技術的事実の確定ではありません', self.js)
        self.assertNotIn('autoApprove', self.js)
        self.assertNotIn('.innerHTML =', self.js)

    def test_stale_source_and_permissions_show_context_not_blank_screen(self):
        self.assertIn('snapshot.stale ? ', self.js)
        self.assertIn('再抽出した候補を確認してください', self.js)
        self.assertIn('レビュー専用の権限が未設定です', self.js)
        self.assertIn('reviewAllowed = false', self.js)
        self.assertIn('loadKnowledge(id)', self.js)
        self.assertIn('reviewPanel.append(choice, submit)', self.js)

    def test_control_deck_accessibility_and_no_shell_duplication(self):
        self.assertIn('.knowledge-review > summary', self.css)
        self.assertIn('min-height:44px', self.css)
        self.assertIn('font-size:16px', self.css)
        self.assertIn('max-width:767px', self.css)
        self.assertIn('prefers-reduced-motion', self.css)
        self.assertIn('applyHostTheme(event.data.theme)', self.js)
        self.assertNotIn('<h1>PatentBuddy</h1>', self.html)


if __name__ == '__main__':
    unittest.main()
