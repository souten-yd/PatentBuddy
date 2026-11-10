import base64
import copy
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qnaplibrary import pdf_store
from qnaplibrary.backup import Backups
from qnaplibrary.store import Store, StoreError
from tests.helpers import Client, LiveServer


CONTENT = b'%PDF-1.4\nSynthetic fixture; not a parser acceptance test.\n'


def extraction(text='電池を備える。'):
    return {'sha256': hashlib.sha256(CONTENT).hexdigest(), 'size_bytes': len(CONTENT),
            'page_count': 1, 'schema_version': 1, 'tool_versions': {'fixture': 'test'},
            'pages': [{'page': 1, 'text': text, 'method': 'pdf_text', 'review_status': 'unreviewed'}]}


class PDFStoreTests(unittest.TestCase):
    def test_atomic_revision_dedup_snapshot_and_last_reference_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'source.sqlite3')
            try:
                first = pdf_store.import_pdf(store, CONTENT, extraction(), '合成PDF')
                changes = store.db.total_changes
                self.assertTrue(pdf_store.import_pdf(store, CONTENT, extraction(), '合成PDF')['unchanged'])
                self.assertEqual(store.db.total_changes, changes)
                second = pdf_store.import_pdf(store, CONTENT, extraction('抽出を修正した電池本文'), '合成PDF')
                self.assertNotEqual(second['doc_id'], first['doc_id'])
                self.assertEqual(store.one('SELECT count(*) FROM source_pdfs')[0], 1)
                self.assertEqual(store.one('SELECT count(*) FROM document_pdfs')[0], 2)
                self.assertIn('ページ 1', store.get_document(first['doc_id'])['body'])
                self.assertIn('電池', store.get_document(first['doc_id'])['body'])
                snapshot = Backups(store).create()
                path = Path(tmp) / 'restored.sqlite3'
                shutil.copy2(Path(tmp) / snapshot['path'], path)
                restored = Store(path)
                try:
                    self.assertEqual(restored.one('PRAGMA quick_check')[0], 'ok')
                    self.assertEqual(pdf_store.original_for(restored, first['doc_id']), CONTENT)
                    self.assertEqual(pdf_store.extraction_for(restored, first['doc_id']), extraction())
                    self.assertEqual(restored.one("SELECT count(*) FROM audit WHERE action='pdf.import'")[0], 2)
                finally:
                    restored.close()
                store.delete_document(first['doc_id'])
                self.assertEqual(store.one('SELECT count(*) FROM source_pdfs')[0], 1)
                store.delete_document(second['doc_id'])
                self.assertEqual(store.one('SELECT count(*) FROM source_pdfs')[0], 0)
            finally:
                store.close()

    def test_validation_and_transaction_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'source.sqlite3')
            try:
                for changes in ({'sha256': '0' * 64}, {'page_count': 2}, {'pages': []}):
                    with self.assertRaises(StoreError):
                        pdf_store.import_pdf(store, CONTENT, dict(extraction(), **changes), 'fixture')
                value = extraction(); value['pages'][0]['review_status'] = 'approved'
                with self.assertRaises(StoreError):
                    pdf_store.import_pdf(store, CONTENT, value, 'fixture')
                with patch.object(store, 'audit', side_effect=OSError('synthetic disk error')):
                    with self.assertRaises(OSError):
                        pdf_store.import_pdf(store, CONTENT, extraction(), 'fixture')
                for table in ('collections', 'documents', 'chunks', 'source_pdfs', 'document_pdfs', 'chunks_fts'):
                    self.assertEqual(store.one('SELECT count(*) FROM ' + table)[0], 0, table)
                self.assertFalse(store.db.in_transaction)
                self.assertFalse(pdf_store.import_pdf(store, CONTENT, extraction(), 'fixture')['unchanged'])
            finally:
                store.close()

    def test_authenticated_import_only_scope_and_original_read(self):
        server = LiveServer()
        try:
            admin = Client(server.base); admin.login_setup()
            importer = Client(server.base); importer.token = server.app.auth.local_token('pdf_import')
            readonly = Client(server.base); readonly.token = server.app.auth.local_token()
            analysis = Client(server.base); analysis.token = server.app.auth.local_token('analysis')
            public = Client(server.base); public.token = server.app.auth.create_device('published', 'published')['token']
            body = {'title': 'fixture', 'pdf_base64': base64.b64encode(CONTENT).decode(), 'extraction': extraction()}
            for client, status in ((Client(server.base), 401), (readonly, 403), (analysis, 403), (public, 403)):
                self.assertEqual(client.call('POST', '/api/v1/pdf-imports', body)[0], status)
            code, result = importer.call('POST', '/api/v1/pdf-imports', body)
            self.assertEqual(code, 200, result)
            original = '/api/v1/documents/%d/original.pdf' % result['doc_id']
            evidence = '/api/v1/documents/%d/pdf-extraction' % result['doc_id']
            self.assertEqual(readonly.call('GET', original, raw=True), (200, CONTENT))
            self.assertEqual(readonly.call('GET', evidence), (200, extraction()))
            self.assertEqual(public.call('GET', evidence)[0], 403)
            self.assertEqual(public.call('GET', original)[0], 403)
            self.assertEqual(importer.call('GET', '/api/settings')[0], 403)
            self.assertEqual(importer.call('POST', '/api/v1/collections', {'name': 'forbidden'})[0], 403)
            self.assertEqual(importer.call('DELETE', '/api/v1/documents/%d' % result['doc_id'])[0], 403)
            self.assertEqual(importer.call('POST', '/api/v1/documents/%d/analyses' % result['doc_id'], {})[0], 403)
            self.assertIsNone(server.app.auth.device_for_token(importer.token, '192.168.1.2'))
            self.assertIsNone(server.app.auth.device_for_token(importer.token, 'bad-ip'))
            self.assertEqual(importer.call('POST', '/api/v1/pdf-imports', dict(body, pdf_base64='invalid!'))[0], 400)
        finally:
            server.close()


if __name__ == '__main__':
    unittest.main()
