import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from qnaplibrary import pdf_extract as pdf


def minimal_pdf(path, raster=False):
    content = b'BT /F1 12 Tf 40 700 Td (This patent has an electrode and a solid electrolyte layer.) Tj ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length ' + str(len(content)).encode() + b' >>\nstream\n' + content + b'\nendstream']
    if raster:
        objects[2] = objects[2].replace(b'/Resources <<', b'/Resources << /XObject << /Im 6 0 R >>')
        data = b'\x00' * 5000
        objects.append(b'<< /Type /XObject /Subtype /Image /Width 200 /Height 200 /ColorSpace /DeviceGray /BitsPerComponent 1 /Length 5000 >>\nstream\n' + data + b'\nendstream')
        content += b' q 200 0 0 200 40 300 cm /Im Do Q'
        objects[4] = b'<< /Length ' + str(len(content)).encode() + b' >>\nstream\n' + content + b'\nendstream'
    value, offsets = b'%PDF-1.4\n', []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(value))
        value += str(number).encode() + b' 0 obj\n' + obj + b'\nendobj\n'
    start = len(value)
    value += ('xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1)).encode()
    value += b''.join(('%010d 00000 n \n' % offset).encode() for offset in offsets)
    value += ('trailer << /Size %d /Root 1 0 R >>\nstartxref\n' % (len(objects) + 1)).encode() + str(start).encode() + b'\n%%EOF'
    path.write_bytes(value)


class PDFExtractionTest(unittest.TestCase):
    def test_tsv_confidence_and_lines_are_evidence_not_approval(self):
        value = 'level\tblock_num\tpar_num\tline_num\tconf\ttext\n5\t1\t1\t1\t95\t電池\n5\t1\t1\t2\t35\t固体\n'
        text, quality = pdf._ocr_words(value)
        self.assertEqual(text, '電池\n固体')
        self.assertEqual(quality['low_confidence_words'], 1)
        self.assertEqual(quality['mean_word_confidence'], 65)
        with self.assertRaises(pdf.PDFError):
            pdf._ocr_words(value.replace('95', 'nan'))

    def test_input_boundaries_before_tool_invocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'input.pdf'
            source.write_bytes(b'not pdf')
            with patch.object(pdf, '_run') as command:
                with self.assertRaises(pdf.PDFError):
                    pdf.extract_pdf(source)
                source.write_bytes(b'%PDF-' + b'x' * 20)
                with patch.object(pdf, 'MAX_PDF_BYTES', 10):
                    with self.assertRaises(pdf.PDFError):
                        pdf.extract_pdf(source)
                with self.assertRaises(pdf.PDFError):
                    pdf.extract_pdf(source, force_pages=[True])
                event = threading.Event(); event.set()
                with self.assertRaises(pdf.PDFError):
                    pdf.extract_pdf(source, cancel=event)
                command.assert_not_called()
            link = Path(tmp) / 'symlink.pdf'; link.symlink_to(source)
            with self.assertRaises(OSError):
                pdf.extract_pdf(link)

    @unittest.skipUnless(os.name == 'posix', 'Linux process limits')
    def test_cancel_kills_real_child_and_waits(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            fake = directory / 'pdfinfo'
            fake.write_text('#!/usr/bin/python3\nimport os,time\nopen("pid", "w").write(str(os.getpid()))\ntime.sleep(20)\n')
            fake.chmod(0o700)
            event = threading.Event()
            timer = threading.Timer(.3, event.set); timer.start()
            start = time.monotonic()
            try:
                with patch.object(pdf.shutil, 'which', return_value=str(fake)):
                    with self.assertRaisesRegex(pdf.PDFError, 'キャンセル'):
                        pdf._run('pdfinfo', [], directory, event)
                self.assertLess(time.monotonic() - start, 3)
                pid = int((directory / 'pid').read_text())
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)
            finally:
                timer.cancel()

    @unittest.skipUnless(all(pdf.capabilities().values()), 'optional local PDF/OCR tools missing')
    def test_real_native_then_forced_ocr(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'input.pdf'; minimal_pdf(source)
            native = pdf.extract_pdf(source)
            self.assertEqual(native['page_count'], 1)
            self.assertEqual(native['pages'][0]['method'], 'pdf_text')
            self.assertIn('solid electrolyte', native['pages'][0]['text'])
            ocr = pdf.extract_pdf(source, force_pages=[1])
            self.assertEqual(ocr['sha256'], native['sha256'])
            self.assertEqual(ocr['pages'][0]['method'], 'tesseract_jpn_eng')
            self.assertIn('electrode', ocr['pages'][0]['text'])
            self.assertEqual(ocr['pages'][0]['review_status'], 'unreviewed')
            self.assertIn('tesseract', ocr['tool_versions'])
            minimal_pdf(source, raster=True)
            mixed = pdf.extract_pdf(source)
            self.assertTrue(mixed['pages'][0]['contains_raster'])
            self.assertEqual(mixed['pages'][0]['method'], 'pdf_text_and_ocr')
            self.assertIn('solid electrolyte', mixed['pages'][0]['native_text'])
            with self.assertRaisesRegex(pdf.PDFError, '存在しない'):
                pdf.extract_pdf(source, force_pages=[2])


if __name__ == '__main__':
    unittest.main()
