"""K6c Obsidian-like force graph, huge corpus drilldown and local-AI UX."""
from html.parser import HTMLParser
from pathlib import Path
import unittest

WEB = Path(__file__).resolve().parents[1] / 'qnaplibrary' / 'web'


class Markup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.tags = []
    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        for k, v in attrs:
            if k == 'id':
                self.ids.append(v)


class KnowledgeAtlasWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (WEB / 'addon-workspace.js').read_text(encoding='utf-8')
        cls.html = (WEB / 'addon-workspace.html').read_text(encoding='utf-8')
        cls.css = (WEB / 'addon-workspace.css').read_text(encoding='utf-8')
        cls.parsed = Markup()
        cls.parsed.feed(cls.html)

    def test_global_atlas_and_local_map_controls_are_accessible(self):
        self.assertEqual(len(self.parsed.ids), len(set(self.parsed.ids)))
        for element in (
            'knowledge-atlas', 'atlas-svg', 'atlas-inspector', 'atlas-status',
            'atlas-next', 'atlas-reload', 'atlas-zoom-in', 'atlas-zoom-out',
            'atlas-fit', 'atlas-reflow', 'map-svg', 'map-inspector', 'map-list',
            'map-zoom-in', 'map-zoom-out', 'map-fit', 'map-reflow',
            'map-hops', 'map-links', 'map-unreviewed', 'map-refresh',
            'map-node-find', 'atlas-node-find',
        ):
            self.assertIn(element, self.parsed.ids)
        self.assertIn('role="status"', self.html)
        self.assertIn('Knowledge Atlas', self.html)
        self.assertIn('所属関係', self.html)
        self.assertIn('AI推論', self.html)
        self.assertIn('ノードをドラッグ', self.html)
        self.assertNotIn('<h1>PatentBuddy</h1>', self.html)

    def test_force_directed_graph_is_bounded_nonpersistent_and_interactive(self):
        js = self.js
        for text in (
            'function makeForceGraph(svg, data, onSelect, initialFocus)',
            'const WIDTH = 960, HEIGHT = 600',
            '.slice(0, 84)',
            '.slice(0, 160)',
            'const degrees = new Map(',
            'const neighbors = new Map(',
            'function settle()',
            'const scale = 1450 / (dx * dx + dy * dy + 120)',
            'if (++tick < 55) request = requestAnimationFrame(animate)',
            'function zoom(factor,',
            'svg.onwheel = event =>',
            'svg.onpointerdown = event =>',
            'svg.onpointermove = event =>',
            'svg.onpointerup=finish',
            "const target = event.target.closest?.('[data-node-id]')",
            "event.key === 'Enter' || event.key === ' '",
            'setPointerCapture(event.pointerId)',
            'cancelAnimationFrame(request)',
            "prefers-reduced-motion: reduce",
            "let localForceView = null;",
            "let atlasForceView = null;",
            'localForceView?.focus(id)',
            'localForceView?.reflow()',
            'atlasForceView?.reflow()',
        ):
            self.assertIn(text, js)
        self.assertIn("let filterTerm = ''", js)
        self.assertIn('function filter(query)', js)
        self.assertIn('is-filter-match', js)
        self.assertIn('is-filtered', js)
        self.assertIn("'map-node-find').oninput =", js)
        self.assertIn("'atlas-node-find').oninput =", js)
        self.assertIn('pointer-events:none', self.css)
        self.assertIn('touch-action:none', self.css)
        self.assertIn('is-neighbor', self.css)
        self.assertIn('is-dimmed', self.css)
        self.assertIn('map-line-hypothesis', self.css)
        self.assertIn('map-line-catalog', self.css)
        self.assertNotIn('localStorage.setItem', js)
        self.assertNotIn('.innerHTML =', js)

    def test_global_overview_drills_down_without_bulk_corpus_transfer(self):
        js = self.js
        self.assertIn("void loadAtlas(0, item.collection_id)", js)
        self.assertIn("async function loadAtlas(cursor = 0, collectionId = 0)", js)
        self.assertIn("'&limit=' + (collectionId ? 50 : 10)", js)
        self.assertIn("data.scope !== (collectionId ? 'catalog_page' : 'catalog_sample')", js)
        self.assertIn('data.nodes.length > 61 || data.edges.length > 60', js)
        self.assertIn("next.dataset.collectionId = String(collectionId)", js)
        self.assertIn("'続きの文献を表示'", js)
        self.assertIn("'全体アトラスへ戻る'", js)
        self.assertIn('atlasForceView = makeForceGraph(', js)
        self.assertIn("await showLibrary()", js)
        self.assertIn("await openDocument(item.document_id)", js)
        self.assertIn("if (next === 'knowledge' && !atlasLoaded && !atlasLoading)", js)

    def test_ai_integration_is_existing_local_host_job_and_explicit_review(self):
        js = self.js
        self.assertIn("async function startLocalKnowledgeAI(docId, button, statusId)", js)
        self.assertIn("window.confirm('この文献の知識をControlDeckのローカルAI", js)
        self.assertIn("await api('jobs', {doc_id: docId, kind: 'knowledge'})", js)
        self.assertIn('人間によるレビュー前には技術的事実になりません', js)
        self.assertIn("startLocalKnowledgeAI(item.document_id, ai, 'atlas-status')", js)
        self.assertIn("startLocalKnowledgeAI(node.document_id, ai, 'map-status')", js)
        self.assertNotIn('fetch("https://', js)
        self.assertNotIn('fetch(\'https://', js)
        self.assertNotIn('openrouter_api_key', js)
        self.assertNotIn('autoApprove', js)

    def test_control_deck_host_theme_and_mobile_not_hidden(self):
        css = self.css
        self.assertIn('background:var(--pb-surface)', css)
        self.assertIn('border:1px solid var(--pb-border)', css)
        self.assertIn('stroke:var(--pb-accent)', css)
        self.assertIn('#knowledge-map .map-visual {display:block', css)
        self.assertIn('#atlas-svg {height:340px;display:block}', css)
        self.assertIn('max-width:767px', css)
        self.assertIn('max-width:390px', css)
        self.assertIn('min-height:44px', css)
        self.assertIn('prefers-reduced-motion:reduce', css)
        self.assertIn('applyHostTheme(event.data.theme)', self.js)
        self.assertNotIn('@import url(', css)
        self.assertNotIn('cdn.', self.js)


if __name__ == '__main__':
    unittest.main()
