import hashlib
import threading
import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from qnaplibrary.addon_client import AddonError
from qnaplibrary.embedding_build import build

MODEL = 'a' * 64


class BuildTests(unittest.TestCase):
    def fixture(self, count=4, text='電池' * 4000):
        rows = [dict(chunk_id=i+1, text=text, revision='b'*64,
                     chunk_sha256=hashlib.sha256(text.encode()).hexdigest()) for i in range(count)]
        stored = set()
        def data(method, path, body=None):
            if method == 'GET':
                params = parse_qs(urlsplit(path).query)
                after = int(params.get('after', ['0'])[0]); limit = int(params.get('limit', ['32'])[0])
                items = [r for r in rows if r['chunk_id'] > after and r['chunk_id'] not in stored][:limit]
                return dict(model_ref=MODEL, items=items, next_cursor=items[-1]['chunk_id'] if items else None)
            self.assertTrue(all('text' not in row for row in body['items']))
            stored.update(r['chunk_id'] for r in body['items'])
            return dict(model_ref=MODEL, stored=len(body['items']), unchanged=0)
        client = Mock(); client.data.side_effect = data
        host = Mock(); host.aborted = threading.Event()
        host.call.return_value = {'text.embed': dict(available=True, execution_policy='local_only',
            revision_kind='host_file_metadata_v1', model_ref=MODEL)}
        def embed(capability, inputs):
            self.assertLessEqual(sum(len(s.encode()) for s in inputs), 65536)
            return dict(model_ref=MODEL, revision_kind='host_file_metadata_v1', execution_policy='local_only',
                        dimensions=2, vectors=[[1, 0] for _ in inputs])
        host.retrieval.side_effect = embed
        return client, host, stored, rows

    def test_byte_bounded_batches_and_warm_no_inference_or_write(self):
        client, host, stored, _ = self.fixture()
        self.assertEqual(build(client, host)['completed_chunks'], 4)
        self.assertEqual(host.retrieval.call_count, 2)
        self.assertEqual(host.progress.call_args.args, ('embedding', 4, None))
        host.retrieval.reset_mock(); client.data.reset_mock()
        self.assertEqual(build(client, host)['completed_chunks'], 0)
        host.retrieval.assert_not_called()
        self.assertTrue(all(c.args[0] == 'GET' for c in client.data.call_args_list))

    def test_cancel_after_commit_resumes_without_reembedding(self):
        client, host, stored, _ = self.fixture()
        host.progress.side_effect = lambda *args: host.aborted.set()
        with self.assertRaises(AddonError): build(client, host)
        self.assertEqual(stored, {1, 2})
        host.aborted.clear(); host.progress.side_effect = None; host.retrieval.reset_mock()
        self.assertEqual(build(client, host)['completed_chunks'], 2)
        self.assertEqual(host.retrieval.call_count, 1)

    def test_model_swap_or_source_hash_rejected_before_save(self):
        client, host, stored, rows = self.fixture(count=1, text='電池')
        embed = host.retrieval.side_effect
        host.retrieval.side_effect = lambda *a: dict(embed(*a), model_ref='c'*64)
        with self.assertRaises(AddonError): build(client, host)
        self.assertEqual(stored, set())
        host.retrieval.side_effect = embed; host.retrieval.reset_mock()
        rows[0]['text'] += '変更'
        with self.assertRaises(AddonError): build(client, host)
        host.retrieval.assert_not_called()

    def test_source_changes_behind_cursor_require_resume(self):
        client, host, stored, _ = self.fixture(count=1, text='電池')
        host.progress.side_effect = lambda *args: stored.clear()
        with self.assertRaisesRegex(AddonError, '更新'): build(client, host)
        self.assertEqual(host.retrieval.call_count, 1)

    def test_commit_response_lost_restarts_from_canonical_checkpoint(self):
        client, host, stored, _ = self.fixture()
        data = client.data.side_effect
        def lost(method, path, body=None):
            value = data(method, path, body)
            if method == 'POST':
                raise AddonError(502, 'connection lost after commit')
            return value
        client.data.side_effect = lost
        with self.assertRaises(AddonError): build(client, host)
        self.assertEqual(stored, {1, 2})
        client.data.side_effect = data; host.retrieval.reset_mock()
        self.assertEqual(build(client, host)['completed_chunks'], 2)
        self.assertEqual(host.retrieval.call_count, 1)
