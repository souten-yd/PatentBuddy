"""Immutable PDF originals and extraction revisions in the one canonical DB."""
import hashlib
import json
import time

from .store import StoreError

MAX_PDF = 50 * 1024 * 1024
MAX_EXTRACTION = 12 * 1024 * 1024


def validate(content, extraction, title):
    if not isinstance(content, bytes) or not 5 <= len(content) <= MAX_PDF or not content.startswith(b'%PDF-'):
        raise StoreError('PDFは50MiB以内のPDFファイルにしてください')
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 300 or any(ord(c) < 32 for c in title):
        raise StoreError('資料名は1〜300文字で指定してください')
    digest = hashlib.sha256(content).hexdigest()
    if (not isinstance(extraction, dict) or extraction.get('sha256') != digest
            or extraction.get('size_bytes') != len(content) or type(extraction.get('schema_version')) is not int or extraction.get('schema_version') != 1):
        raise StoreError('原本と抽出結果が一致しません')
    pages = extraction.get('pages')
    if not isinstance(pages, list) or not 1 <= len(pages) <= 200 or type(extraction.get('page_count')) is not int or extraction.get('page_count') != len(pages):
        raise StoreError('ページ数が不正です')
    total = 0
    for number, page in enumerate(pages, 1):
        if (not isinstance(page, dict) or type(page.get('page')) is not int or page['page'] != number
                or page.get('method') not in ('pdf_text', 'tesseract_jpn_eng', 'pdf_text_and_ocr')
                or page.get('review_status') != 'unreviewed' or not isinstance(page.get('text'), str)):
            raise StoreError('抽出ページの形式が不正です')
        total += len(page['text'])
    if total > 1000000:
        raise StoreError('抽出本文が100万文字を超えました')
    versions = extraction.get('tool_versions')
    if not isinstance(versions, dict) or not versions or len(versions) > 10 or any(
            not isinstance(k, str) or len(k) > 50 or not isinstance(v, str) or not 1 <= len(v) <= 200
            for k, v in versions.items()):
        raise StoreError('抽出エンジンの版を記録してください')
    try:
        canonical = json.dumps(extraction, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError):
        raise StoreError('抽出結果はJSON形式にしてください') from None
    if len(canonical.encode()) > MAX_EXTRACTION:
        raise StoreError('抽出根拠が12MiBを超えました')
    return digest, hashlib.sha256(canonical.encode()).hexdigest(), canonical


def import_pdf(store, content, extraction, title, actor='system', images=None):
    source_hash, extraction_hash, canonical = validate(content, extraction, title)
    image_values = validate_images(extraction, images or {})
    with store.tx() as db:
        previous = db.execute('SELECT doc_id FROM document_pdfs WHERE extraction_sha256=?', (extraction_hash,)).fetchone()
        if previous:
            return {'doc_id': previous[0], 'source_sha256': source_hash,
                    'extraction_sha256': extraction_hash, 'unchanged': True}
        # Import credentials cannot overwrite arbitrary IDs or choose collections.
        collection = db.execute("SELECT id FROM collections WHERE name='pdf-imports'").fetchone()
        stamp = time.time()
        if not collection:
            cid = db.execute("INSERT INTO collections(name,kind,description,created,updated) VALUES('pdf-imports','generic',?,?,?)",
                             ('PDF原本とページ抽出結果', stamp, stamp)).lastrowid
        else:
            cid = collection[0]
        ext_id = 'pdf:' + extraction_hash
        if db.execute('SELECT 1 FROM documents WHERE collection_id=? AND ext_id=?', (cid, ext_id)).fetchone():
            raise StoreError('既存資料のIDと衝突しました')
        pages = extraction['pages']
        sections = {'ページ %d' % p['page']: p['text'] for p in pages}
        document = {'id': ext_id, 'title': title.strip(), 'sections': sections,
                    'source': 'sha256:' + source_hash,
                    'meta': {'source_type': 'pdf', 'source_sha256': source_hash,
                             'extraction_sha256': extraction_hash, 'page_count': len(pages),
                             'review_status': 'unreviewed'}}
        result = store.add_documents(cid, [document], actor=actor, _connection=db)
        doc_id = result['ids'][0]
        db.execute('INSERT OR IGNORE INTO source_pdfs(sha256,content,created) VALUES(?,?,?)',
                   (source_hash, content, stamp))
        db.execute('INSERT INTO document_pdfs(doc_id,source_sha256,extraction_sha256,extraction,created) VALUES(?,?,?,?,?)',
                   (doc_id, source_hash, extraction_hash, canonical, stamp))
        for image_id, image_hash, raw in image_values:
            db.execute('INSERT OR IGNORE INTO pdf_image_blobs(sha256,content) VALUES(?,?)', (image_hash, raw))
            db.execute('INSERT INTO document_pdf_images(doc_id,image_id,sha256) VALUES(?,?,?)', (doc_id, image_id, image_hash))
        store.audit(actor, 'pdf.import', 'doc:%d source:%s extraction:%s' % (doc_id, source_hash, extraction_hash))
    store.vector_version += 1
    if store.on_change:
        store.on_change()
    return {'doc_id': doc_id, 'source_sha256': source_hash,
            'extraction_sha256': extraction_hash, 'unchanged': False}


def extraction_for(store, doc_id):
    row = store.one('SELECT extraction FROM document_pdfs WHERE doc_id=?', (doc_id,))
    if not row:
        raise StoreError('PDFの抽出結果がありません')
    return json.loads(row[0])


def original_for(store, doc_id):
    # Maximum 50MiB, only when explicitly downloading an authenticated original.
    row = store.one('SELECT s.content FROM source_pdfs s JOIN document_pdfs p ON p.source_sha256=s.sha256 WHERE p.doc_id=?', (doc_id,))
    if not row:
        raise StoreError('PDFの原本がありません')
    return bytes(row[0])


def validate_images(extraction, images):
    from .pdf_images import MAX_IMAGES, MAX_TOTAL_BYTES, png_size
    metadata = extraction.get('images', [])
    if not isinstance(metadata, list) or len(metadata) > MAX_IMAGES or not isinstance(images, dict) or len(images) != len(metadata):
        raise StoreError('画像と抽出根拠の数が一致しません')
    result, seen, size = [], set(), 0
    for item in metadata:
        if not isinstance(item, dict):
            raise StoreError('画像の根拠が不正です')
        image_id = item.get('id')
        if type(image_id) is not int or not 0 <= image_id < MAX_IMAGES or image_id in seen:
            raise StoreError('画像IDが不正または重複しています')
        seen.add(image_id)
        raw = images.get(image_id)
        try:
            width, height = png_size(raw)
        except ValueError as error:
            raise StoreError(str(error)) from None
        digest = hashlib.sha256(raw).hexdigest()
        if (item.get('sha256') != digest or item.get('size_bytes') != len(raw)
                or item.get('width') != width or item.get('height') != height
                or type(item.get('page')) is not int or not 1 <= item['page'] <= extraction['page_count']
                or item.get('method') != 'pdfimages_png' or item.get('review_status') != 'unreviewed'):
            raise StoreError('画像の内容・ページと抽出根拠が一致しません')
        size += len(raw)
        if size > MAX_TOTAL_BYTES:
            raise StoreError('画像の合計は32MiB以内にしてください')
        result.append((image_id, digest, raw))
    return result


def image_for(store, doc_id, image_id):
    row = store.one('SELECT b.content FROM pdf_image_blobs b JOIN document_pdf_images i ON b.sha256=i.sha256 WHERE i.doc_id=? AND i.image_id=?', (doc_id, image_id))
    if not row:
        raise StoreError('画像がありません')
    return bytes(row[0])
