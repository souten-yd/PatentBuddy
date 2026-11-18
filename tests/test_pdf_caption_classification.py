import tempfile
import unittest
from pathlib import Path

from qnaplibrary import official_ipc, pdf_classification, pdf_figure_regions
from qnaplibrary.store import Store


class PDFEvidenceTests(unittest.TestCase):
    def test_front_page_ocr_symbol_is_only_a_dictionary_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'db')
            self.addCleanup(store.close)
            pages = [{'native_text': 'HO2M 1/12', 'ocr_text': 'HO2M 1/12 H01F 17/04'},
                     {'ocr_text': 'H02M 7/48'}]
            rows = pdf_classification.candidates(store, pages)
            self.assertEqual([(r['symbol'], r['dictionary']) for r in rows],
                             [('H02M1/12', 'unavailable'), ('H01F17/04', 'unavailable')])
            official_ipc.install(store, b'<list><symbol>H02M1/12</symbol></list>', 'H')
            rows = pdf_classification.candidates(store, pages)
            self.assertEqual([r['dictionary'] for r in rows], ['match', 'absent'])
            self.assertEqual(rows[0]['raw'], 'HO2M 1/12')
            self.assertEqual(pdf_classification.candidates(store, [{'text': 'legacy'}]), [])

    def test_native_caption_after_page_twelve_and_repeated_image(self):
        try:
            import fitz
        except ImportError:
            self.skipTest('optional PyMuPDF')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pix = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 100, 80), False)
            pix.clear_with(100)
            pix.save(str(root / '0.png'))
            with fitz.open() as doc:
                for _ in range(12):
                    doc.new_page()
                page = doc.new_page()
                page.insert_text((50, 96), 'FIG. 11')
                page.insert_image(fitz.Rect(50, 100, 150, 180), pixmap=pix)
                page = doc.new_page()
                page.insert_text((50, 96), 'FIG. 12')
                for x in (50, 220):
                    page.insert_image(fitz.Rect(x, 100, x + 100, 180), pixmap=pix)
                doc.save(root / 'sample.pdf')
            self.assertEqual(pdf_figure_regions.embedded_figure_labels(root / 'sample.pdf', root, 1),
                             [[0, 13, 11]])
