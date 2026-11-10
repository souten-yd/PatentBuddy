"""Bounded local PDF extraction, used by the PC worker (not an HTTP path API).

Callers own Host file grants, CPU leases and canonical storage. This module
creates private temporary files only; it does not call an LLM or a network API.
"""
import csv
import hashlib
import io
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time

MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_PAGES = 200
MAX_TEXT = 1000000
MAX_OUTPUT = 32 * 1024 * 1024
TOOLS = ('pdfinfo', 'pdftotext', 'pdftoppm', 'pdfimages', 'tesseract')


class PDFError(ValueError):
    pass


def capabilities():
    return {name: shutil.which(name) is not None for name in TOOLS}


def _check_cancel(cancel):
    if cancel.is_set():
        raise PDFError('PDF処理をキャンセルしました')


def _run(tool, args, directory, cancel, timeout=120, version=False):
    _check_cancel(cancel)
    executable = shutil.which(tool) if tool in TOOLS else None
    if not executable:
        raise PDFError('%sが未導入です' % tool)
    output = directory / 'command-output'
    env = dict(os.environ, LC_ALL='C', OMP_THREAD_LIMIT='1')
    # A separate Python worker sets limits before exec; preexec_fn is unsafe in
    # the threaded Add-on server. No user-supplied command or shell is accepted.
    with output.open('wb') as stream:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                                    '--worker', executable] + args,
                                   stdin=subprocess.DEVNULL, stdout=stream,
                                   stderr=subprocess.STDOUT if version else subprocess.DEVNULL, cwd=directory,
                                   env=env, start_new_session=True)
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                _check_cancel(cancel)
                if time.monotonic() > deadline:
                    raise PDFError('%sの処理時間が上限を超えました' % tool)
                cancel.wait(.1)
            _check_cancel(cancel)
            if process.returncode:
                raise PDFError('%sで読み取れませんでした（破損・暗号化・上限を確認してください）' % tool)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    if output.stat().st_size > MAX_OUTPUT:
        raise PDFError('抽出結果が上限を超えました')
    return output.read_bytes()


def _ocr_words(tsv):
    reader = csv.DictReader(io.StringIO(tsv), delimiter='\t', quoting=csv.QUOTE_NONE)
    expected = {'level', 'text', 'conf', 'block_num', 'par_num', 'line_num'}
    if not expected.issubset(reader.fieldnames or []):
        raise PDFError('OCR応答の形式が不正です')
    lines, current, words, confidence, uncertain = [], None, [], [], []
    for row in reader:
        if row['level'] != '5' or not row['text'].strip():
            continue
        key = (row['block_num'], row['par_num'], row['line_num'])
        if key != current and words:
            lines.append(' '.join(words)); words = []
        current = key
        words.append(row['text'])
        try:
            value = float(row['conf'])
            if not 0 <= value <= 100:
                raise ValueError()
            if len(confidence) >= 50000:
                raise PDFError('OCR単語数がページ上限を超えました')
            confidence.append(value)
            if value < 60 and len(uncertain) < 1000:
                uncertain.append({'text': row['text'], 'confidence': value,
                                  'block': key[0], 'paragraph': key[1], 'line': key[2]})
        except ValueError:
            raise PDFError('OCR信頼度の形式が不正です') from None
    if words:
        lines.append(' '.join(words))
    return '\n'.join(lines), {
        'mean_word_confidence': round(sum(confidence) / len(confidence), 2) if confidence else None,
        'low_confidence_words': sum(x < 60 for x in confidence),
        'word_count': len(confidence),
        'low_confidence_items': uncertain,
        'low_confidence_items_truncated': sum(x < 60 for x in confidence) > len(uncertain),
    }


def extract_pdf(source, cancel=None, force_pages=(), progress=None, scratch_parent=None):
    """Return all pages or raise; no partial-success or silent truncation.

    force_pages uses 1-based page numbers. OCR confidence is an engine score,
    not a probability of correctness; all output remains unreviewed.
    """
    cancel = cancel or threading.Event()
    forced = set(force_pages)
    if any(type(p) is not int or p < 1 for p in forced):
        raise PDFError('OCRページ番号は1以上の整数で指定してください')
    if os.name != 'posix':
        raise PDFError('PDF処理はLinux PCで実行してください')
    with tempfile.TemporaryDirectory(prefix='patent-buddy-pdf-', dir=scratch_parent) as temporary:
        directory = Path(temporary)
        pdf = directory / 'source.pdf'
        digest, size = hashlib.sha256(), 0
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as incoming, pdf.open('wb') as outgoing:
            if not stat.S_ISREG(os.fstat(incoming.fileno()).st_mode):
                raise PDFError('通常のPDFファイルを選択してください')
            while True:
                _check_cancel(cancel)
                chunk = incoming.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_PDF_BYTES:
                    raise PDFError('PDFは50MiB以内にしてください')
                digest.update(chunk); outgoing.write(chunk)
        with pdf.open('rb') as stream:
            if stream.read(5) != b'%PDF-':
                raise PDFError('PDFの形式ではありません')
        info = _run('pdfinfo', [str(pdf)], directory, cancel).decode('utf-8', 'replace')
        count = re.search(r'^Pages:\s+(\d+)\s*$', info, re.M)
        if not count or not 1 <= int(count[1]) <= MAX_PAGES:
            raise PDFError('PDFは1〜200ページにしてください')
        count = int(count[1])
        if forced and max(forced) > count:
            raise PDFError('存在しないOCRページが指定されています')
        if re.search(r'^Encrypted:\s+yes', info, re.M):
            raise PDFError('暗号化されたPDFには対応していません')
        image_listing = _run('pdfimages', ['-list', str(pdf)], directory, cancel).decode('utf-8', 'replace')
        image_pages = set()
        for line in image_listing.splitlines():
            fields = line.split()
            if len(fields) >= 5 and fields[0].isdigit() and fields[2] == 'image':
                if int(fields[3]) >= 200 and int(fields[4]) >= 200:
                    image_pages.add(int(fields[0]))
        versions = {tool: _run(tool, ['-v'], directory, cancel, version=True)
                    .decode('utf-8', 'replace').splitlines()[0][:200]
                    for tool in ('pdfinfo', 'pdftotext', 'pdfimages')}
        started = time.monotonic()
        pages, total = [], 0
        for page in range(1, count + 1):
            if time.monotonic() - started > 900:
                raise PDFError('PDF処理全体の時間上限を超えました')
            raw = _run('pdftotext', ['-f', str(page), '-l', str(page), '-layout',
                                   '-enc', 'UTF-8', str(pdf), '-'], directory, cancel)
            text = raw.decode('utf-8').strip(' \r\n\t\f')
            native_text = text
            method, quality = 'pdf_text', {}
            # Sparse native text can be a heading over a scan. Forced OCR is
            # available for dense but incorrect hidden text layers.
            if page in forced or page in image_pages or len(''.join(text.split())) < 20 or '\ufffd' in text:
                if 'tesseract' not in versions:
                    for tool, flag in (('pdftoppm', '-v'), ('tesseract', '--version')):
                        versions[tool] = _run(tool, [flag], directory, cancel, version=True).decode('utf-8', 'replace').splitlines()[0][:200]
                prefix = directory / 'page'
                _run('pdftoppm', ['-f', str(page), '-l', str(page), '-singlefile',
                                 '-scale-to', '2400', '-png', str(pdf), str(prefix)], directory, cancel)
                raster = prefix.with_suffix('.png')
                if not raster.is_file() or raster.stat().st_size > MAX_OUTPUT:
                    raise PDFError('ページ画像が上限を超えました')
                tsv = _run('tesseract', [str(raster), 'stdout', '-l', 'jpn+eng', 'tsv'], directory, cancel)
                text, quality = _ocr_words(tsv.decode('utf-8'))
                raster.unlink()
                method = 'tesseract_jpn_eng'
                quality['ocr_text'] = text
                if native_text and page not in forced:
                    method = 'pdf_text_and_ocr'
                    text = native_text + '\n\n[画像部分を含むページOCR・未確認]\n' + text
            total += len(text)
            if total > MAX_TEXT:
                raise PDFError('抽出本文が100万文字を超えました')
            pages.append(dict(page=page, text=text, native_text=native_text, method=method,
                              contains_raster=page in image_pages,
                              review_status='unreviewed', empty=not bool(text.strip()), **quality))
            if progress:
                progress(page, count)
        _check_cancel(cancel)
        return {'sha256': digest.hexdigest(), 'size_bytes': size, 'page_count': count,
                'pages': pages, 'tool_versions': versions, 'schema_version': 1}


def _worker():
    import resource
    executable = Path(sys.argv[2])
    if executable.name not in TOOLS or not executable.is_absolute():
        raise SystemExit(2)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (90, 90))
    resource.setrlimit(resource.RLIMIT_AS, (1024 ** 3, 1024 ** 3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT, MAX_OUTPUT))
    os.execv(str(executable), [str(executable)] + sys.argv[3:])


if __name__ == '__main__' and len(sys.argv) >= 3 and sys.argv[1] == '--worker':
    _worker()
