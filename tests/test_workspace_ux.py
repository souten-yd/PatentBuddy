"""K6b UI/UX contract for task-oriented, embedded ControlDeck workspace.

No browser automation is implied by these source-based assertions. Real
ControlDeck Host/Ubuntu/QNAP/iOS Safari remains a pre-merge release gate.
"""
from html.parser import HTMLParser
from pathlib import Path
import unittest

WEB = Path(__file__).resolve().parents[1] / 'qnaplibrary' / 'web'


class Markup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.tabs = []
        self.panels = []
        self.forms = []
        self.labels = []
        self.elements = []
    def handle_starttag(self, tag, attrs):
        props = dict(attrs)
        self.elements.append((tag, props))
        if props.get('id'):
            self.ids.append(props['id'])
        if props.get('role') == 'tab':
            self.tabs.append(props)
        if props.get('role') == 'tabpanel':
            self.panels.append(props)
        if tag == 'form':
            self.forms.append(props)
        if tag == 'label':
            self.labels.append(props)


class WorkbenchUXTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (WEB / 'addon-workspace.html').read_text(encoding='utf-8')
        cls.js = (WEB / 'addon-workspace.js').read_text(encoding='utf-8')
        cls.css = (WEB / 'addon-workspace.css').read_text(encoding='utf-8')
        cls.parser = Markup()
        cls.parser.feed(cls.html)

    def test_tabs_three_local_stages_and_global_shell_unchanged(self):
        parser = self.parser
        self.assertEqual(len(parser.ids), len(set(parser.ids)), 'duplicate DOM IDs')
        self.assertEqual(len(parser.tabs), 3)
        self.assertEqual(len(parser.panels), 3)
        for step in ('research', 'knowledge', 'ideas'):
            tab = next(x for x in parser.tabs if x.get('id') == 'workspace-tab-' + step)
            panel = next(x for x in parser.panels if x.get('id') == 'workspace-panel-' + step)
            self.assertEqual(tab['aria-controls'], panel['id'])
            self.assertEqual(panel['aria-labelledby'], tab['id'])
            self.assertEqual(panel.get('tabindex'), '0')
            if step == 'research':
                self.assertEqual(tab['aria-selected'], 'true')
                self.assertNotIn('hidden', panel)
            else:
                self.assertEqual(tab['aria-selected'], 'false')
                self.assertIn('hidden', panel)
        self.assertIn('id="workspace-tabs"', self.html)
        self.assertIn('role="tablist"', self.html)
        self.assertNotIn('<h1>PatentBuddy</h1>', self.html)
        self.assertNotIn('role="navigation"', self.html)
        self.assertNotIn('id="global-nav"', self.html)

    def test_all_existing_features_remain_reachable(self):
        ids = set(self.parser.ids)
        for key in ('server', 'message', 'reconnect', 'import-pdf', 'ocr-pages',
                    'pdf-jobs', 'search', 'query', 'submit', 'library-collection',
                    'library-items', 'results', 'detail', 'title', 'analyze',
                    'knowledge', 'knowledge-links', 'knowledge-map', 'source-details',
                    'cross-search-form', 'cross-results', 'cross-compare-results',
                    'idea-canvas', 'idea-form', 'idea-save', 'idea-history', 'jobs',
                    'workspace-source-return', 'document-compare-action',
                    'research-pdf-quick', 'workspace-activity',
                    'workspace-job-count', 'workspace-pdf-import'):
            self.assertIn(key, ids)
        # Navigation controls are separate from resource mutations.
        self.assertIn('id="idea-confirm"', self.html)
        self.assertIn('id="link-confirm"', self.html)
        self.assertIn('id="map-unreviewed"', self.html)
        self.assertIn('id="map-links"', self.html)

    def test_workspace_keyboard_navigation_and_focus_without_new_host_routes(self):
        js = self.js
        for text in ('function switchWorkspace(next,',
                     "const WORKSPACE_STEPS = ['research', 'knowledge', 'ideas']",
                     "tab.setAttribute('aria-selected', active ? 'true' : 'false')",
                     'pane.hidden = !active',
                     "event.key === 'ArrowRight'",
                     "event.key === 'ArrowLeft'",
                     "event.key === 'Home'",
                     "event.key === 'End'",
                     "switchWorkspace(WORKSPACE_STEPS[target], {focusTab: true})"):
            self.assertIn(text, js)
        self.assertIn('switchWorkspace(previous, {focusTab: true, scroll: false})', js)
        self.assertIn("sourceReturnWorkspace = previous === 'research' ? null : previous", js)
        self.assertIn('sourceReturnWorkspace = null;', js)
        self.assertIn("'workspace-source-return').hidden = true", js)
        self.assertNotIn('history.pushState(', js)
        self.assertNotIn('location.href =', js)

    def test_explicit_feature_handoff_and_no_autonomous_search_or_idea(self):
        js = self.js
        self.assertIn("el('research-pdf-quick').onclick = () =>", js)
        self.assertIn("el('workspace-pdf-import').open = true", js)
        self.assertIn("el('document-compare-action').onclick = () =>", js)
        self.assertIn("'この条件から関連知識を探す'", js)
        self.assertIn("el('cross-query').value = Array.from(condition).slice(0, 120).join('')", js)
        self.assertIn("switchWorkspace('knowledge', {scroll: true})", js)
        self.assertIn("switchWorkspace('ideas', {scroll: false})", js)
        self.assertIn('canvas.onclick = () => beginIdeaFromComparison(result.items)', js)
        self.assertIn('confirm_manual: true', js)
        self.assertIn("ideaDirty && !window.confirm(", js)
        self.assertIn('ideaDirty = true;', js)
        self.assertIn('if (!ideaWriteReady)', js)
        self.assertNotIn('.innerHTML =', js)
        self.assertNotIn('localStorage.setItem', js)
        self.assertNotIn('autoApprove', js)

    def test_connection_jobs_and_accessible_activities(self):
        ids = set(self.parser.ids)
        self.assertIn('connection-state', ids)
        self.assertIn('workspace-activity', ids)
        self.assertIn('workspace-job-count', ids)
        self.assertIn('role="status"', self.html)
        self.assertIn("indicator.dataset.state = ready ? 'ready' : 'attention'", self.js)
        self.assertIn('updateActivitySummary()', self.js)
        self.assertIn('activeAnalysisJobs = data.items.filter(', self.js)
        self.assertIn('activePDFJobs = data.items.filter(', self.js)
        self.assertIn('実行履歴を確認', self.js)
        self.assertIn('ResearchDataHub', self.html)

    def test_host_theme_iphone_style_and_visible_hidden_boundary(self):
        css = self.css
        self.assertIn('.workspace-tabs', css)
        self.assertIn('.workspace-tab[aria-selected="true"]', css)
        self.assertIn('[hidden] { display:none !important; }', css)
        self.assertIn('background:var(--pb-surface)', css)
        self.assertIn('border-color:var(--pb-border)', css)
        self.assertIn('border-bottom:2px solid var(--pb-accent)', css)
        self.assertIn('max-width:767px', css)
        self.assertIn('max-width:390px', css)
        self.assertIn('min-height:44px', css)
        self.assertIn('font-size:16px', css)
        self.assertIn('env(safe-area-inset-bottom)', css)
        self.assertIn('prefers-reduced-motion', css)
        self.assertIn('applyHostTheme(event.data.theme)', self.js)
        self.assertNotIn('@import url(', css)
        self.assertNotIn('https://', self.html)
        self.assertNotIn('cdn.', self.js)


if __name__ == '__main__':
    unittest.main()
