"""Manual local PDF capacity measurement. Outputs JSON; uses disposable SQLite."""
import argparse
import json
from pathlib import Path
import tempfile
import time
import zlib

from qnaplibrary.pdf_extract import extract_pdf
from qnaplibrary.pdf_store import import_pdf
from qnaplibrary.store import Store


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('pdf', type=Path)
    cli.add_argument('--drawing-pages', required=True, help='Comma-separated 1-based pages verified against original')
    args = cli.parse_args()
    selected = {int(value) for value in args.drawing_pages.split(',')}
    with tempfile.TemporaryDirectory(prefix='patent-capacity-') as tmp:
        root = Path(tmp)
        started = time.perf_counter()
        extraction = extract_pdf(args.pdf, image_directory=root / 'images')
        elapsed = time.perf_counter() - started
        if not selected or min(selected) < 1 or max(selected) > extraction['page_count']:
            cli.error('drawing pages outside document')
        original = args.pdf.read_bytes()
        text = '\n'.join(page['text'] for page in extraction['pages']).encode()
        images = {item['id']: (root / 'images' / ('%d.png' % item['id'])).read_bytes()
                  for item in extraction['images']}
        drawings = [item for item in extraction['images']
                    if item['page'] in selected and item['method'] == 'pdfimages_png']
        store = Store(root / 'measurement.sqlite3')
        try:
            store.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            before = (root / 'measurement.sqlite3').stat().st_size
            import_pdf(store, original, extraction, args.pdf.name, images=images)
            store.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            growth = (root / 'measurement.sqlite3').stat().st_size - before
        finally:
            store.close()
        print(json.dumps({
            'source_sha256': extraction['sha256'],
            'page_count': extraction['page_count'],
            'original_bytes': len(original),
            'text_utf8_bytes': len(text),
            'text_zlib9_bytes': len(zlib.compress(text, 9)),
            'all_png_bytes': sum(map(len, images.values())),
            'selected_png_bytes': sum(len(images[item['id']]) for item in drawings),
            'selected_image_count': len(drawings),
            'sqlite_increment_bytes': growth,
            'extract_seconds': elapsed,
            'tool_versions': extraction['tool_versions'],
            'limits': 'Single-document increment; excludes download, AI, backup, transient WAL and concurrency. Selected scan pages may contain multiple figures.'
        }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
