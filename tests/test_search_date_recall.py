import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qnaplibrary.store import Store
from qnaplibrary.search import Searcher


class Config:
    def get(self, *args, default=None):
        return default


class DateRecallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'db')
        self.addCleanup(self.store.close)
        self.cid = self.store.create_collection('patents', 'patent')['id']
        docs = [{'id': str(i), 'body': 'semiconductor', 'date': '2020-01-01'} for i in range(120)]
        docs += [{'id': 'target', 'body': 'semiconductor filter detail', 'date': '2025-06-01'},
                 {'id': 'unknown', 'body': 'semiconductor', 'date': ''}]
        self.store.add_documents(self.cid, docs)
        self.search = Searcher(self.store, Config())
        rows = self.store.q('SELECT c.id,d.ext_id FROM chunks c JOIN documents d ON c.doc_id=d.id')
        self.store.put_vectors([(row[0], [0.8, 0.2] if row[1] == 'target' else [1., 0.])
                                for row in rows], 'test')

    def test_keyword_filter_precedes_candidate_limit(self):
        for fts in (True, False):
            with patch.object(self.store, 'fts', fts):
                result = self.search.search('semiconductor', mode='keyword', limit=1,
                                            date_from='2025-06-01', date_to='2025-06-01')
                self.assertEqual([r['ext_id'] for r in result['results']], ['target'])

    def test_vector_filter_precedes_top_k_with_and_without_numpy(self):
        import qnaplibrary.search as module
        for numpy in (module._np, None):
            with patch.object(module, '_np', numpy):
                engine = Searcher(self.store, Config(), backend_fn=lambda: object())
                for mode in ('vector', 'hybrid'):
                    result = engine.search('semiconductor', mode=mode, qvec=[1., 0.],
                                           limit=1, date_from='2025-06-01')
                    self.assertEqual([r['ext_id'] for r in result['results']], ['target'])
                    self.assertEqual(engine.search('semiconductor', mode=mode, qvec=[1., 0.],
                                                   date_from='2030-01-01')['results'], [])

    def test_open_upper_bound_and_legacy_unfiltered_call(self):
        self.assertTrue(self.store.fts_search('semiconductor', [self.cid], 3))
        result = self.search.search('semiconductor', mode='keyword', date_to='2019-12-31')
        self.assertEqual(result['results'], [])
