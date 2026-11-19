"""Figure coverage must report actual work, including bounded early exits."""
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from qnaplibrary import pdf_figure_regions as regions
from qnaplibrary.pdf_extract import _geometry_candidates


class Page:
    rect = SimpleNamespace(width=600, height=800)
    def __init__(self, count=0):
        self.count = count
    def get_image_info(self, **kwargs):
        return []
    def get_drawings(self):
        return [{'rect': (i, i, i + 60, i + 60)} for i in range(self.count)]


class Document(list):
    def close(self):
        pass


class FigureCoverageTests(unittest.TestCase):
    def test_late_page_is_scanned(self):
        doc = Document([Page() for _ in range(14)] + [Page(1)])
        with patch.object(regions, '_open', return_value=doc):
            result = regions.scan('unused')
        self.assertEqual(result['candidates'][0]['page'], 15)
        self.assertEqual(result['pages_scanned'], 15)
        self.assertTrue(result['scan_complete'])

    def test_early_cap_reports_actual_pages(self):
        doc = Document([Page(60)] + [Page() for _ in range(14)])
        with patch.object(regions, '_open', return_value=doc):
            result = regions.scan('unused')
        self.assertEqual(result['pages_scanned'], 1)
        self.assertFalse(result['scan_complete'])
        self.assertTrue(result['truncated'])

    def test_page_limit_and_per_page_limit_are_incomplete(self):
        for doc, limit in [(Document([Page(), Page()]), 1), (Document([Page(401)]), 1)]:
            with patch.object(regions, '_open', return_value=doc):
                result = regions.scan('unused', limit_pages=limit)
            self.assertFalse(result['scan_complete'])
            self.assertTrue(result['truncated'])

    def test_real_vector_on_page_15(self):
        try:
            import fitz
        except ImportError:
            self.skipTest('optional PyMuPDF unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'late.pdf'
            doc = fitz.open()
            for _ in range(15):
                doc.new_page()
            doc[14].draw_rect(fitz.Rect(40, 40, 160, 160))
            doc.save(path)
            doc.close()
            result = regions.scan(path)
            self.assertEqual(result['pages_scanned'], 15)
            self.assertTrue(any(x['page'] == 15 for x in result['candidates']))

            output = Path(tmp) / 'images'
            output.mkdir()
            preview, images = _geometry_candidates(path, output, 0, 12, threading.Event())
            self.assertEqual(preview['status'], 'unreviewed')
            self.assertEqual(preview['pages_scanned'], 15)
            self.assertTrue(preview['scan_complete'])
            self.assertTrue(any(x['page'] == 15 for x in images))
