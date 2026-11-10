import unittest
from tests.helpers import Client, LiveServer


class AnalysisTests(unittest.TestCase):
    def test_scope_revision_idempotence_and_staleness(self):
        server = LiveServer()
        try:
            admin = Client(server.base); admin.login_setup()
            admin.call('POST', '/api/v1/collections', {'name': 'analysis-synthetic'})
            admin.call('POST', '/api/v1/collections/analysis-synthetic/documents', {'documents': [
                {'id': 'synthetic', 'body': '特許試験本文', 'source': 'source-v1'}]})
            doc_id = server.app.store.list_documents('analysis-synthetic')['items'][0]['id']
            path = '/api/v1/documents/%s/analyses' % doc_id
            _, doc = admin.call('GET', '/api/v1/documents/%s' % doc_id)
            value = {'id': 'test-job', 'kind': 'summary', 'source_revision': doc['revision'], 'content': '合成要約'}
            reader = Client(server.base); reader.token = server.app.auth.local_token()
            writer = Client(server.base); writer.token = server.app.auth.local_token('analysis')
            self.assertEqual(reader.call('POST', path, value)[0], 403)
            self.assertEqual(Client(server.base).call('GET', path)[0], 401)
            self.assertEqual(writer.call('POST', '/api/v1/collections', {'name': 'forbidden'})[0], 403)
            self.assertEqual(writer.call('GET', '/api/settings')[0], 403)
            self.assertEqual(writer.call('POST', path, value)[0], 200)
            before = server.app.store.db.total_changes
            self.assertEqual(writer.call('POST', path, value)[0], 200)
            self.assertEqual(server.app.store.db.total_changes, before)
            self.assertEqual(writer.call('POST', path, dict(value, content='replacement'))[0], 400)
            self.assertEqual(reader.call('GET', path)[1]['items'][0]['review_status'], 'unreviewed')
            admin.call('POST', '/api/v1/collections/analysis-synthetic/documents', {'documents': [
                {'id': 'synthetic', 'body': '特許試験本文', 'source': 'source-v2'}]})
            self.assertEqual(writer.call('POST', path, dict(value, id='new-job'))[0], 400)
            self.assertTrue(reader.call('GET', path)[1]['items'][0]['stale'])
            self.assertEqual(reader.call('GET', path)[1]['items'][0]['content'], '合成要約')
            for change in ({'id': '../unsafe'}, {'content': 'x' * 100001}, {'kind': 'admin'}, {'source_revision': ''}):
                self.assertEqual(writer.call('POST', path, dict(value, **change))[0], 400)
            server.app.store.delete_document(doc_id)
            self.assertEqual(server.app.store.one('SELECT count(*) FROM document_analyses')[0], 0)
        finally: server.close()
