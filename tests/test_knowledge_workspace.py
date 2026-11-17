"""ControlDeck-owned-shell UX contract: static safety and accessibility regression."""
import unittest
from html.parser import HTMLParser
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / 'qnaplibrary' / 'web'


class IDs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []

    def handle_starttag(self, tag, attrs):
        self.ids.extend(value for key, value in attrs if key == 'id')


class KnowledgeUXContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (WEB / 'addon-workspace.html').read_text(encoding='utf-8')
        cls.js = (WEB / 'addon-workspace.js').read_text(encoding='utf-8')
        cls.css = (WEB / 'addon-workspace.css').read_text(encoding='utf-8')

    def test_selection_cards_and_source_exists_without_extra_shell(self):
        ids = IDs()
        ids.feed(self.html)
        self.assertEqual(len(ids.ids), len(set(ids.ids)))
        for field in ('analysis-kind', 'analyze', 'jobs', 'knowledge', 'source-details', 'body'):
            self.assertIn(field, ids.ids)
        self.assertIn('<option value="knowledge">', self.html)
        self.assertNotIn('<h1>PatentBuddy</h1>', self.html)
        self.assertIn('loadKnowledge(id)', self.js)
        self.assertIn('focusKnowledgeEvidence(evidence)', self.js)

    def test_evidence_is_displayed_only_as_text_not_trusted_html(self):
        self.assertIn('quote.textContent = item.evidence.quote;', self.js)
        self.assertIn('statement.textContent = item.statement;', self.js)
        self.assertIn('Array.from(currentDocBody)', self.js)
        self.assertIn("codepoints.slice(evidence.start, evidence.end).join('') !== evidence.quote", self.js)
        self.assertIn("snapshot.stale ? '原文が更新されています'", self.js)
        self.assertNotIn('.innerHTML =', self.js)
        self.assertNotIn('eval(', self.js)

    def test_host_theme_and_safe_responsive_components(self):
        self.assertIn('applyHostTheme(event.data.theme)', self.js)
        self.assertIn("'theme.changed'", self.js)
        self.assertIn("theme.token_version !== '1.0'", self.js)
        self.assertIn('--pb-accent', self.css)
        self.assertIn('var(--pb-surface)', self.css)
        self.assertIn('min-height:44px', self.css)
        self.assertIn('prefers-reduced-motion', self.css)
        self.assertIn('max-width:767px', self.css)
        self.assertNotIn('@import url(', self.css)

    def test_jobs_stay_bounded_authenticated_and_explicit(self):
        self.assertIn("kind: el('analysis-kind').value", self.js)
        self.assertIn("job.kind === 'knowledge'", self.js)
        self.assertIn("jobs/' + job.id + '/cancel'", self.js)
        self.assertIn("jobs/' + job.id + '/reconcile'", self.js)
        self.assertIn("'X-Control-Deck-Bridge-Session': nonce", self.js)
        self.assertIn("credentials: 'omit'", self.js)
        self.assertNotIn('knowledge_server_token', self.js)


if __name__ == '__main__':
    unittest.main()
