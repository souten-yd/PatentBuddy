import base64
import hashlib
import shutil
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from qnaplibrary import pdf_store
from qnaplibrary.pdf_images import png_size
from qnaplibrary.backup import Backups
from qnaplibrary.store import Store, StoreError
from tests.helpers import Client, LiveServer
from tests.test_pdf_store import CONTENT, extraction


def png():
    def chunk(kind, content):
        return struct.pack('>I', len(content)) + kind + content + struct.pack('>I', zlib.crc32(kind + content))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\x00\xff\xff\xff')) + chunk(b'IEND', b'')


def value():
    image = png(); result = extraction()
    result['images'] = [{'id': 0, 'page': 1, 'kind': 'image', 'width': 1, 'height': 1,
                         'sha256': hashlib.sha256(image).hexdigest(), 'size_bytes': len(image),
                         'method': 'pdfimages_png', 'review_status': 'unreviewed'}]
    return result


class PDFImageTests(unittest.TestCase):
    def test_png_validation_and_binding(self):
        self.assertEqual(png_size(png()), (1, 1))
        for data in (b'<svg>bad</svg>', png()[:-1], png() + b'extra', png()[:28] + b'x' + png()[29:]):
            with self.assertRaises(ValueError): png_size(data)
        for changes in ({'sha256': '0' * 64}, {'page': 2}, {'review_status': 'approved'}, {'width': 2}):
            data = value(); data['images'][0].update(changes)
            with self.assertRaises(StoreError): pdf_store.validate_images(data, {0: png()})
        with self.assertRaises(StoreError): pdf_store.validate_images(value(), {})

    def test_atomic_images_snapshot_dedup_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'source.sqlite3')
            try:
                with patch.object(store, 'audit', side_effect=OSError('simulated full disk')):
                    with self.assertRaises(OSError): pdf_store.import_pdf(store, CONTENT, value(), 'test', images={0: png()})
                for table in ('pdf_image_blobs', 'document_pdf_images', 'documents', 'source_pdfs'):
                    self.assertEqual(store.one('SELECT count(*) FROM ' + table)[0], 0)
                first = pdf_store.import_pdf(store, CONTENT, value(), 'test', images={0: png()})
                before = store.db.total_changes
                self.assertTrue(pdf_store.import_pdf(store, CONTENT, value(), 'test', images={0: png()})['unchanged'])
                self.assertEqual(before, store.db.total_changes)
                second_value = value(); second_value['pages'][0]['text'] += '抽出版2'
                second = pdf_store.import_pdf(store, CONTENT, second_value, 'test', images={0: png()})
                self.assertEqual(store.one('SELECT count(*) FROM pdf_image_blobs')[0], 1)
                backup = Backups(store).create()
                restored = Store(Path(tmp) / backup['path'])
                try:
                    self.assertEqual(restored.one('PRAGMA quick_check')[0], 'ok')
                    self.assertEqual(pdf_store.image_for(restored, first['doc_id'], 0), png())
                finally: restored.close()
                store.delete_document(first['doc_id'])
                self.assertEqual(store.one('SELECT count(*) FROM pdf_image_blobs')[0], 1)
                store.delete_document(second['doc_id'])
                self.assertEqual(store.one('SELECT count(*) FROM pdf_image_blobs')[0], 0)
            finally: store.close()

    def test_image_api_private_boundary(self):
        server = LiveServer()
        try:
            admin = Client(server.base); admin.login_setup()
            importer = Client(server.base); importer.token = server.app.auth.local_token('pdf_import')
            body = {'title': 'test', 'pdf_base64': base64.b64encode(CONTENT).decode(), 'extraction': value(),
                    'images': [{'id': 0, 'data_base64': base64.b64encode(png()).decode()}]}
            code, result = importer.call('POST', '/api/v1/pdf-imports', body)
            self.assertEqual(code, 200, result)
            url = '/api/v1/documents/%d/images/0' % result['doc_id']
            reader = Client(server.base); reader.token = server.app.auth.local_token()
            self.assertEqual(reader.call('GET', url, raw=True), (200, png()))
            published = Client(server.base); published.token = server.app.auth.create_device('public', 'published')['token']
            self.assertEqual(published.call('GET', url)[0], 403)
            self.assertEqual(Client(server.base).call('GET', url)[0], 401)
            body['images'][0]['data_base64'] = base64.b64encode(b'not PNG').decode()
            self.assertEqual(importer.call('POST', '/api/v1/pdf-imports', body)[0], 400)
        finally: server.close()


if __name__ == '__main__': unittest.main()
