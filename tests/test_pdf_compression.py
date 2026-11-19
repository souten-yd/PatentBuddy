"""Lossless persistence and optional encoder failure regression checks."""
import hashlib
import io
import tempfile
import threading
import unittest
import urllib.request
import zlib
from pathlib import Path
from unittest.mock import patch

from qnaplibrary import pdf_store, pdf_webp
from qnaplibrary.store import Store, StoreError
from tests.test_pdf_store import CONTENT, extraction
from tests.helpers import Client, LiveServer


class CompressionTests(unittest.TestCase):
    def test_text_roundtrip_legacy_and_corruption(self):
        text = '請求項・図面の説明 abc\n' * 1000
        packed = pdf_store.packed_extraction(text)
        self.assertIsInstance(packed, bytes)
        self.assertLess(len(packed), len(text.encode()))
        self.assertEqual(pdf_store.unpacked_extraction(packed), text)
        self.assertEqual(pdf_store.unpacked_extraction(text), text)
        for bad in (b'bad', packed[:-1], packed + b'extra', b'PBZ1' + zlib.compress(b'\xff')):
            with self.assertRaises(StoreError):
                pdf_store.unpacked_extraction(bad)
        with patch.object(pdf_store, 'MAX_EXTRACTION', 5):
            with self.assertRaises(StoreError):
                pdf_store.unpacked_extraction(packed)

    def test_compressed_database_and_legacy_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'db.sqlite')
            try:
                value = extraction()
                value['pages'][0]['text'] = 'コモンモードノイズ 課題 請求項\n' * 100
                result = pdf_store.import_pdf(store, CONTENT, value, 'test')
                row = store.one('SELECT extraction FROM document_pdfs')[0]
                self.assertIsInstance(row, bytes)
                self.assertEqual(pdf_store.extraction_for(store, result['doc_id']), value)
                canonical = pdf_store.validate(CONTENT, value, 'test')[2]
                store.db.execute('UPDATE document_pdfs SET extraction=?', (canonical,))
                self.assertEqual(pdf_store.extraction_for(store, result['doc_id']), value)
            finally:
                store.close()

    def test_encoder_spawn_failure_keeps_png(self):
        images = [{'id': 0, 'sha256': 'abc'}]
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(pdf_webp.subprocess, 'Popen', side_effect=OSError('unavailable')):
                pdf_webp.compress_images(images, tmp, threading.Event())
            self.assertEqual(images, [{'id': 0, 'sha256': 'abc'}])

    def test_lossless_pixels_and_store_binding(self):
        try:
            from PIL import Image, features
        except ImportError:
            self.skipTest('optional Pillow unavailable')
        if not features.check('webp'):
            self.skipTest('optional WebP unavailable')
        image = Image.new('RGB', (256, 256), 'white')
        for pos in range(256):
            image.putpixel((pos, pos), (0, 0, 0))
        buffer = io.BytesIO()
        image.save(buffer, format='PNG', compress_level=0)
        raw = buffer.getvalue()
        item = dict(id=0, page=1, kind='image', width=256, height=256,
                    sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw),
                    method='pdfimages_png', review_status='unreviewed')
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, '0.png').write_bytes(raw)
            pdf_webp.compress_images([item], tmp, threading.Event())
            self.assertEqual(item.get('mime_type'), 'image/webp')
            encoded = Path(tmp, '0.webp').read_bytes()
            self.assertLess(len(encoded), len(raw))
            with Image.open(io.BytesIO(encoded)) as decoded:
                self.assertEqual(decoded.convert('RGBA').tobytes(), image.convert('RGBA').tobytes())
            value = extraction()
            value['images'] = [item]
            store = Store(Path(tmp) / 'db.sqlite')
            try:
                result = pdf_store.import_pdf(store, CONTENT, value, 'test', images={0: encoded})
                self.assertEqual(pdf_store.image_for(store, result['doc_id'], 0), encoded)
                self.assertEqual(pdf_store.extraction_for(store, result['doc_id']), value)
            finally:
                store.close()
            server = LiveServer()
            try:
                result = pdf_store.import_pdf(server.app.store, CONTENT, value, 'test', images={0: encoded})
                Client(server.base).login_setup()
                token = server.app.auth.local_token()
                request = urllib.request.Request(
                    server.base + '/api/v1/documents/%d/images/0' % result['doc_id'],
                    headers={'Authorization': 'Bearer ' + token})
                with urllib.request.urlopen(request, timeout=10) as response:
                    self.assertEqual(response.headers['Content-Type'], 'image/webp')
                    self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
                    self.assertEqual(response.read(), encoded)
            finally:
                server.close()
            for bad in (encoded[:-1], encoded + b'extra', raw):
                with self.assertRaises(ValueError):
                    pdf_webp.webp_size(bad)
