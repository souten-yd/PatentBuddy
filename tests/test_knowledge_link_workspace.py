"""K3b: explicit link UX stays in ControlDeck embedded read/write boundary."""
import unittest
from pathlib import Path
from html.parser import HTMLParser

WEB = Path(__file__).resolve().parents[1] / 'qnaplibrary' / 'web'


class Ids(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
    def handle_starttag(self, tag, attrs):
        self.ids.extend(v for k, v in attrs if k == 'id')


class KnowledgeLinkWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (WEB / 'addon-workspace.js').read_text(encoding='utf-8')
        cls.html = (WEB / 'addon-workspace.html').read_text(encoding='utf-8')
        cls.css = (WEB / 'addon-workspace.css').read_text(encoding='utf-8')

    def test_fields_and_source_target_confirmation_are_explicit(self):
        ids = Ids()
        ids.feed(self.html)
        self.assertEqual(len(ids.ids), len(set(ids.ids)))
        for id_ in ('knowledge-links', 'link-create', 'link-source',
                    'link-target-form', 'link-target-query', 'link-target-results',
                    'link-target-choice', 'link-evidence', 'link-relation',
                    'link-confirm', 'link-register', 'link-list', 'link-feedback',
                    'map-links'):
            self.assertIn(id_, ids.ids)
        self.assertIn('仮説として登録する', self.html)
        self.assertIn('未確認の仮説リンクを登録', self.html)
        self.assertIn('仮説リンクも参考表示', self.html)
        self.assertNotIn('<h1>PatentBuddy</h1>', self.html)

    def test_only_reviewed_k2_sources_offer_link_registration(self):
        self.assertIn("review?.status === 'approved' && review.stale !== true", self.js)
        self.assertIn('linkSources.push({', self.js)
        self.assertIn('linkSources = [];', self.js)
        self.assertIn("linkTarget.id !== currentDoc", self.js)
        self.assertIn("el('link-confirm').checked", self.js)
        self.assertIn("'link-register').disabled = !ready", self.js)
        self.assertIn("'link-target-form').addEventListener('submit'", self.js)
        self.assertIn("api('documents/' + row.doc_id + '/link-target')", self.js)
        self.assertIn("confirm_evidence: true", self.js)
        self.assertIn("source_revision: source.sourceRevision", self.js)
        self.assertIn("target_revision: target.revision", self.js)

    def test_review_requires_new_human_decision_and_keeps_hypothesis(self):
        self.assertIn("item.review_status === 'unreviewed' && !item.stale && linkAllowed", self.js)
        self.assertIn("save.disabled = true", self.js)
        self.assertIn("choice.onchange = update", self.js)
        self.assertIn("confirm.onchange = update", self.js)
        self.assertIn("expected_graph_revision: item.graph_revision", self.js)
        self.assertIn('事実扱いせず記録する', self.js)
        self.assertIn('承認しても技術的事実にはなりません', self.js)
        self.assertIn('リンクの審査結果を記録', self.js)
        self.assertNotIn('.innerHTML =', self.js)
        self.assertNotIn('autoLink', self.js)

    def test_map_optin_accessibility_and_theme(self):
        self.assertIn("el('map-links').checked ? 'true' : 'false'", self.js)
        self.assertIn("'&include_links=' + links", self.js)
        self.assertIn('map-line-hypothesis', self.js)
        self.assertIn('人が確認した技術仮説（事実ではありません）', self.js)
        self.assertIn('applyHostTheme(event.data.theme)', self.js)
        self.assertIn('min-height:44px', self.css)
        self.assertIn('font-size:16px', self.css)
        self.assertIn('max-width:767px', self.css)
        self.assertIn('prefers-reduced-motion', self.css)
        self.assertNotIn('cdn.', self.js)
        self.assertNotIn('knowledge_link_token', self.js)


if __name__ == '__main__':
    unittest.main()
