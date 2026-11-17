"""K5 embedded ControlDeck Idea Canvas safety and UX contracts."""
import unittest
from html.parser import HTMLParser
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / 'qnaplibrary' / 'web'


class IDs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.labels = []
    def handle_starttag(self, name, attrs):
        values = dict(attrs)
        if 'id' in values:
            self.ids.append(values['id'])
        if name == 'label' and 'for' in values:
            self.labels.append(values['for'])


class IdeaCanvasWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (WEB / 'addon-workspace.html').read_text(encoding='utf-8')
        cls.js = (WEB / 'addon-workspace.js').read_text(encoding='utf-8')
        cls.css = (WEB / 'addon-workspace.css').read_text(encoding='utf-8')

    def test_form_fields_are_labeled_and_have_no_duplicate_ids(self):
        parser = IDs()
        parser.feed(self.html)
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        for element in ('idea-canvas', 'idea-form', 'idea-heading', 'idea-source-list',
                        'idea-status', 'idea-save-status', 'idea-recent', 'idea-history',
                        'idea-confirm', 'idea-save', 'idea-new', 'idea-refresh'):
            self.assertIn(element, parser.ids)
        for field in ('title', 'problem', 'solution', 'effect', 'conditions',
                      'limitations'):
            self.assertIn('idea-' + field, parser.ids)
            self.assertIn('idea-' + field, parser.labels)
        self.assertIn('role="status"', self.html)
        self.assertIn('Idea Canvas — 発明仮説の作成', self.html)
        self.assertNotIn('<h1>PatentBuddy</h1>', self.html)

    def test_explicit_manual_only_save_and_history(self):
        self.assertIn("canvas.onclick = () => beginIdeaFromComparison(result.items)", self.js)
        self.assertIn("el('idea-form').addEventListener('submit', async event =>", self.js)
        self.assertIn("el('idea-confirm').checked", self.js)
        self.assertIn('ideaWriteReady && !ideaSaving && active && confirmed', self.js)
        self.assertIn('confirm_manual: true', self.js)
        self.assertIn('expected_version: existing.version', self.js)
        self.assertIn('crypto.randomUUID().replaceAll', self.js)
        self.assertIn('showIdeaHistory(detail)', self.js)
        self.assertIn('第' , self.js)
        self.assertIn('needs_revalidation', self.js)
        self.assertIn('!currentIdea || !currentIdea.stale', self.js)
        self.assertIn('ideaSources.length >= 2 && ideaSources.length <= 3', self.js)
        self.assertIn('new Set(ideaSources.map(s => s.doc_id)).size >= 2', self.js)
        self.assertNotIn('.innerHTML =', self.js)
        self.assertNotIn('localStorage.setItem', self.js)
        self.assertNotIn('autoApprove', self.js)

    def test_stale_comparison_cannot_be_reused_after_filter_or_selection_changes(self):
        # The previous K4 comparison was cached for a manual K5 draft. A new
        # search or selection must invalidate it before an Idea can be reopened.
        self.assertIn("function clearCrossSelection() {\n  ++crossCompareRequest;\n  lastComparedItems = [];", self.js)
        self.assertIn("check.onchange = () => {\n      ++crossCompareRequest;\n      lastComparedItems = [];", self.js)
        self.assertIn("button.disabled = true;\n  lastComparedItems = [];\n  crossSelected.clear();", self.js)
        self.assertIn("if (lastComparedItems.length < 2)", self.js)

    def test_provenance_and_no_external_model_execution(self):
        for field in ('source_revision', 'source_epoch', 'review_seq',
                      'proposal_id', 'item_index'):
            self.assertIn(field, self.js)
        self.assertIn('quote.textContent = source.evidence.quote', self.js)
        self.assertIn('元文献の引用へ', self.js)
        self.assertIn('記入だけでは保存されません', self.js)
        self.assertIn("await openDocument(item.doc_id)", self.js)
        self.assertNotIn('idea_write_token', self.js)
        self.assertNotIn('shell:true', self.js)

    def test_host_theme_mobile_and_accessible_editing(self):
        self.assertIn('applyHostTheme(event.data.theme)', self.js)
        self.assertIn('--pb-accent', self.css)
        self.assertIn('.idea-canvas', self.css)
        self.assertIn('font-size:16px', self.css)
        self.assertIn('min-height:44px', self.css)
        self.assertIn('max-width:767px', self.css)
        self.assertIn('#idea-source-list {display:flex;flex-direction:column}', self.css)
        self.assertIn('prefers-reduced-motion', self.css)
        self.assertNotIn('@import url(', self.css)
        self.assertNotIn('cdn.', self.js)


if __name__ == '__main__':
    unittest.main()
