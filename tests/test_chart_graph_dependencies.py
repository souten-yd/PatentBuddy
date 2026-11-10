import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from qnaplibrary import evidence_graph as graph, chart_storage
from qnaplibrary.store import Store, StoreError, SCHEMA as STORE_SCHEMA
from tests import test_claim_chart as base


class GraphDependencyTests(unittest.TestCase):
    setUp = base.ChartTests.setUp
    save = base.ChartTests.save

    def graph_chart(self, source_id=None):
        edge = dict(id='edge', source=dict(kind='document', key=str(source_id or self.doc['id']), label='claim'),
                    target=dict(kind='document', key=str(self.ref['id']), label='reference'),
                    relation='citation', basis='factual', confidence=1,
                    evidence=dict(doc_id=self.ref['id'], revision=self.ref['revision'], start=0, end=2,
                                  quote='正極', retrieved_at='2026-11-11T00:00:00Z', method='manual'))
        graph.save(self.store, edge, 'test')
        approved = graph.review(self.store, 'edge', 'approved', 'test')
        value = copy.deepcopy(self.chart)
        for row in value['rows']:
            row['evidence'][0].update(via='graph:edge', graph={k: approved[k] for k in chart_storage.GRAPH_FIELDS})
        return value

    def test_approval_reversal_is_irreversible_for_saved_chart(self):
        value = self.graph_chart(); self.save(value)
        chart_storage.review(self.store, 'chart-test', 'approved', 'test')
        old = value['rows'][0]['evidence'][0]['graph']['graph_revision']
        before = self.store.db.total_changes
        self.save(value); graph.review(self.store, 'edge', 'approved', 'test')
        self.assertEqual(self.store.db.total_changes, before)
        graph.review(self.store, 'edge', 'rejected', 'test')
        current = graph.review(self.store, 'edge', 'approved', 'test')
        self.assertNotEqual(current['graph_revision'], old)
        saved = self.store.list_analyses(self.doc['id'])['items'][0]
        self.assertTrue(saved['stale']); self.assertEqual(saved['review_status'], 'unreviewed')
        with self.assertRaises(StoreError): chart_storage.review(self.store, 'chart-test', 'approved', 'test')
        with self.assertRaises(StoreError): self.save(value, 'obsolete-approval')
        self.assertEqual(self.store.one('SELECT count(*) FROM document_analyses')[0], 1)

    def test_deletion_invalidates_without_deleting_chart(self):
        value = self.graph_chart(); self.save(value)
        with self.store.tx() as db: db.execute("DELETE FROM graph_edges WHERE id='edge'")
        self.assertTrue(self.store.list_analyses(self.doc['id'])['items'][0]['stale'])
        self.assertEqual(self.store.one('SELECT count(*) FROM analysis_graph_dependencies')[0], 0)
        self.assertEqual(self.store.one('SELECT count(*) FROM document_analyses')[0], 1)
        with self.assertRaises(StoreError): self.save(value, 'missing-edge')

    def test_nonquoted_graph_endpoint_document_change_invalidates(self):
        self.store.add_documents('charts', [{'id': 'seed', 'body': '探索の開始文献'}])
        seed = self.store.one("SELECT id FROM documents WHERE ext_id='seed'")[0]
        value = self.graph_chart(seed); self.save(value)
        self.assertIsNone(self.store.one('SELECT 1 FROM analysis_dependencies WHERE doc_id=?', (seed,)))
        self.store.add_documents('charts', [{'id': 'seed', 'body': '探索の開始文献を変更'}])
        self.assertTrue(self.store.list_analyses(self.doc['id'])['items'][0]['stale'])

    def test_forged_or_missing_graph_snapshot_rejected_atomically(self):
        value = self.graph_chart()
        for field in chart_storage.GRAPH_FIELDS:
            forged = copy.deepcopy(value)
            forged['rows'][0]['evidence'][0]['graph'][field] = 'forged'
            with self.assertRaises(StoreError): self.save(forged)
        missing = copy.deepcopy(value); del missing['rows'][0]['evidence'][0]['graph']
        with self.assertRaises(StoreError): self.save(missing)
        self.assertEqual(self.store.one('SELECT count(*) FROM document_analyses')[0], 0)
        graph.review(self.store, 'edge', 'unreviewed', 'test')
        with self.assertRaises(StoreError): self.save(value)

    def test_legacy_chart_migration_retains_content_and_only_runs_once(self):
        value = self.graph_chart(); self.save(value)
        text = self.store.one('SELECT content FROM document_analyses')[0]
        with self.store.tx() as db:
            db.execute("DELETE FROM meta WHERE key='chart_graph_dependencies_v1'")
            db.execute('DELETE FROM analysis_graph_dependencies')
        chart_storage.install(self.store.db)
        self.assertEqual(self.store.one('SELECT content FROM document_analyses')[0], text)
        self.assertTrue(self.store.list_analyses(self.doc['id'])['items'][0]['stale'])
        changes = self.store.db.total_changes
        chart_storage.install(self.store.db)
        self.assertEqual(self.store.db.total_changes, changes)


class GraphMigrationTests(unittest.TestCase):
    def test_old_graph_schema_upgrades_and_reopen_does_not_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'library.sqlite3'
            db = sqlite3.connect(path)
            db.executescript(STORE_SCHEMA)
            db.executescript(graph.SCHEMA.replace(",\n graph_revision TEXT NOT NULL DEFAULT ''", ''))
            db.execute("INSERT INTO collections(id,name,created,updated) VALUES(1,'legacy',0,0)")
            db.execute("INSERT INTO documents(id,collection_id,created,updated) VALUES(1,1,0,0)")
            db.execute("INSERT INTO graph_nodes(id,kind,node_key,label,doc_id) VALUES(1,'document','1','one',1)")
            db.execute("INSERT INTO graph_nodes(id,kind,node_key,label) VALUES(2,'concept','two','two')")
            db.execute("""INSERT INTO graph_edges(id,source_node,target_node,relation,basis,evidence_doc_id,
revision,start,end,quote,retrieved_at,method,model,confidence,fingerprint,created,review_status)
VALUES('legacy',1,2,'citation','factual',1,?,0,1,'x','2026-11-11T00:00:00Z','manual','',1,?,0,'approved')""", ('a'*64,'b'*64))
            db.commit(); db.close()
            store = Store(path)
            self.assertIn('graph_revision', {r[1] for r in store.q('PRAGMA table_info(graph_edges)')})
            revision = store.one("SELECT graph_revision FROM graph_edges WHERE id='legacy'")[0]
            self.assertEqual(len(revision), 32)
            store.close()
            store = Store(path)
            self.assertEqual(store.one("SELECT graph_revision FROM graph_edges WHERE id='legacy'")[0], revision)
            before = store.db.total_changes
            graph.install(store.db); chart_storage.install(store.db)
            self.assertEqual(store.db.total_changes, before)
            self.assertEqual(store.one('PRAGMA quick_check')[0], 'ok')
            store.close()
