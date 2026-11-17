"""K3: ControlDeck Knowledge Map static UX and information security contracts."""
import unittest
from html.parser import HTMLParser
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / 'qnaplibrary' / 'web'


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
    def handle_starttag(self, tag, attrs):
        self.ids.extend(value for key, value in attrs if key == 'id')


class KnowledgeMapWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (WEB / 'addon-workspace.js').read_text(encoding='utf-8')
        cls.html = (WEB / 'addon-workspace.html').read_text(encoding='utf-8')
        cls.css = (WEB / 'addon-workspace.css').read_text(encoding='utf-8')

    def test_map_has_selection_inspector_accessible_list_and_bounded_controls(self):
        parser = Elements()
        parser.feed(self.html)
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        for name in ('knowledge-map', 'map-hops', 'map-unreviewed', 'map-refresh',
                     'map-status', 'map-svg', 'map-list', 'map-inspector', 'source-details'):
            self.assertIn(name, parser.ids)
        self.assertIn('<option value="1">1段階</option>', self.html)
        self.assertIn('<option value="2">2段階</option>', self.html)
        self.assertIn('未確認・却下・失効候補も参考表示', self.html)
        self.assertIn('aria-label="知識の関連一覧"', self.html)
        self.assertIn('role="status"', self.html)
        self.assertNotIn('<h1>PatentBuddy</h1>', self.html)

    def test_read_only_explicit_opt_in_and_source_jump(self):
        self.assertIn("el('map-unreviewed').checked ? 'true' : 'false'", self.js)
        self.assertIn("await api('documents/' + id + '/knowledge-map?hops='", self.js)
        self.assertIn('renderKnowledgeMap(data)', self.js)
        self.assertIn('drawKnowledgeMap(data, select)', self.js)
        self.assertIn('renderMapInspector(data, id)', self.js)
        self.assertIn('mapItemStatus(node)', self.js)
        self.assertIn('focusKnowledgeEvidence(evidence)', self.js)
        self.assertIn('if (currentDoc !== edge.evidence.doc_id) await openDocument(', self.js)
        self.assertIn('loadKnowledgeMap(currentDoc)', self.js)
        self.assertNotIn('autoLink', self.js)
        self.assertNotIn('.innerHTML =', self.js)
        self.assertNotIn('eval(', self.js)

    def test_model_inference_not_mislabeled_as_legal_fact(self):
        self.assertIn('人間レビュー済みのAI推論', self.js)
        self.assertIn('出典リンクのみ・技術的関係の認定ではありません', self.js)
        self.assertIn('人が承認していても、AI推論が出典の確定した事実に', self.js)
        self.assertIn('技術的な因果関係ではありません', self.js)
        self.assertIn("edge.basis === 'factual'", self.js)
        self.assertIn('quote.textContent = evidence.quote', self.js)

    def test_host_theme_and_mobile_accessibility(self):
        self.assertIn('applyHostTheme(event.data.theme)', self.js)
        self.assertIn('--pb-accent', self.css)
        self.assertIn('grid-template-columns:', self.css)
        self.assertIn('.map-visual {display:none}', self.css)
        self.assertIn('max-width:767px', self.css)
        self.assertIn('min-height:44px', self.css)
        self.assertIn('prefers-reduced-motion', self.css)
        self.assertIn('map-list-item', self.css)
        self.assertNotIn('@import url(', self.css)
        self.assertNotIn('cdn.', self.js)


if __name__ == '__main__':
    unittest.main()
