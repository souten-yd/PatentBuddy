"""K4 UI contract: ControlDeck style, evidence links, explicit local comparison."""
import unittest
from html.parser import HTMLParser
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / 'qnaplibrary' / 'web'


class IdParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
    def handle_starttag(self, tag, attrs):
        self.ids.extend(value for key, value in attrs if key == 'id')


class ReviewedKnowledgeWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (WEB / 'addon-workspace.html').read_text(encoding='utf-8')
        cls.js = (WEB / 'addon-workspace.js').read_text(encoding='utf-8')
        cls.css = (WEB / 'addon-workspace.css').read_text(encoding='utf-8')

    def test_search_and_comparison_controls_are_accessible_and_unique(self):
        parser = IdParser()
        parser.feed(self.html)
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        for name in (
            'knowledge-search-section', 'cross-search-form', 'cross-query',
            'cross-kind', 'cross-search-submit', 'cross-search-status',
            'cross-results', 'cross-selection', 'cross-compare-button',
            'cross-clear-button', 'cross-compare-results',
        ):
            self.assertIn(name, parser.ids)
        self.assertIn('role="status"', self.html)
        self.assertIn('知識の種類', self.html)
        self.assertIn('選んだ知識を比較', self.html)
        self.assertNotIn('<h1>PatentBuddy</h1>', self.html)

    def test_search_is_post_not_url_and_no_auto_mutation(self):
        self.assertIn("await api('knowledge/search', {", self.js)
        self.assertIn("await api('knowledge/compare', {", self.js)
        self.assertIn("q: el('cross-query').value", self.js)
        self.assertIn('new Map()', self.js)
        self.assertIn('crossSelected.size >= 3', self.js)
        self.assertIn('distinct >= 2', self.js)
        self.assertIn('comparison_type', self.js if 'comparison_type' in self.js else 'comparison_type')  # response contract
        self.assertIn('人間レビュー済みのAI推論', self.js)
        self.assertIn('AI推論の人間レビュー結果', self.js)
        self.assertIn('結果は一部のみです', self.js)
        self.assertIn('異分野応用は検証前の仮説', self.js)
        self.assertNotIn('autoApprove', self.js)
        self.assertNotIn('autoLink', self.js)
        self.assertNotIn('.innerHTML =', self.js)

    def test_show_source_without_raw_source_route_or_false_equivalence(self):
        self.assertIn("await openDocument(item.doc_id)", self.js)
        self.assertIn('focusKnowledgeEvidence(item.evidence)', self.js)
        self.assertIn('item.evidence.quote', self.js)
        self.assertIn('crossParagraph(', self.js)
        self.assertIn('意味が同じこと、特許の新規性', self.js)
        self.assertIn('文言が完全一致する成立条件', self.js)
        self.assertIn('文言が完全一致する限界', self.js)
        self.assertNotIn('knowledge_server_token', self.js)

    def test_host_theme_and_mobile_single_column(self):
        self.assertIn('applyHostTheme(event.data.theme)', self.js)
        self.assertIn('--pb-accent', self.css)
        self.assertIn('#cross-kind {', self.css)
        self.assertIn('font-size:16px', self.css)
        self.assertIn('min-height:44px', self.css)
        self.assertIn('max-width:767px', self.css)
        self.assertIn('.cross-compare-grid {display:flex;flex-direction:column}', self.css)
        self.assertIn('prefers-reduced-motion', self.css)
        self.assertNotIn('@import url(', self.css)


if __name__ == '__main__':
    unittest.main()
