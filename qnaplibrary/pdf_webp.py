"""Optional, isolated, pixel-verified lossless encoding of extracted PNGs."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import time

MAX_BYTES = 2 * 1024 * 1024


def webp_size(raw):
    if (not isinstance(raw, bytes) or not 25 <= len(raw) <= MAX_BYTES
            or raw[:4] != b'RIFF' or raw[8:12] != b'WEBP'
            or struct.unpack('<I', raw[4:8])[0] + 8 != len(raw)
            or raw[12:16] != b'VP8L' or raw[20] != 0x2f):
        raise ValueError('可逆WebPの形式が不正です')
    size = struct.unpack('<I', raw[16:20])[0]
    if size < 5 or 20 + size + (size & 1) != len(raw):
        raise ValueError('可逆WebPの長さが不正です')
    bits = struct.unpack('<I', raw[21:25])[0]
    width, height = (bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1
    if bits >> 29 or width * height > 16000000:
        raise ValueError('可逆WebPの画素数が上限を超えています')
    return width, height


def image_info(raw):
    if not isinstance(raw, bytes):
        raise ValueError('画像データが不正です')
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):
        from .pdf_images import png_size
        return png_size(raw), 'image/png'
    return webp_size(raw), 'image/webp'


def compress_images(images, directory, cancel):
    """Keep PNG on optional encoder failure. Update metadata only after validation."""
    directory = Path(directory)
    report = directory / 'webp-report.json'
    with report.open('wb') as output:
        try:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                                        '--worker', str(directory.resolve())],
                                       stdin=subprocess.DEVNULL, stdout=output,
                                       stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            report.unlink(missing_ok=True)
            return
        deadline = time.monotonic() + 90
        try:
            while process.poll() is None and not cancel.is_set() and time.monotonic() < deadline:
                cancel.wait(.1)
            if process.poll() is None:
                process.kill()
            process.wait()
            if process.returncode or report.stat().st_size > 65536:
                return
            rows = json.loads(report.read_text())
            if not isinstance(rows, list) or len(rows) > 200:
                return
            by_id = {item['id']: item for item in images}
            for row in rows:
                if not isinstance(row, dict) or type(row.get('id')) is not int:
                    continue
                item = by_id.get(row['id'])
                if not item:
                    continue
                path = directory / ('%d.webp' % row['id'])
                if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
                    continue
                raw = path.read_bytes()
                if (webp_size(raw) != (item['width'], item['height'])
                        or row.get('source_sha256') != item['sha256']
                        or len(raw) >= item['size_bytes']
                        or hashlib.sha256(raw).hexdigest() != row.get('sha256')):
                    continue
                item.update(source_png_sha256=item['sha256'], source_png_bytes=item['size_bytes'],
                            sha256=row['sha256'], size_bytes=len(raw), mime_type='image/webp',
                            compression='lossless_webp_pixel_verified')
        except (ValueError, OSError, KeyError, TypeError):
            return
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            report.unlink(missing_ok=True)


def worker(directory):
    import importlib
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_BYTES, MAX_BYTES))
    Image = importlib.import_module('PIL.Image')
    root = Path(directory)
    results = []
    for path in sorted(root.glob('*.png')):
        if not path.stem.isdecimal() or path.is_symlink() or not 0 <= int(path.stem) < 200:
            continue
        if path.stat().st_size > MAX_BYTES:
            continue
        raw = path.read_bytes()
        from io import BytesIO
        with Image.open(BytesIO(raw)) as image:
            if image.width * image.height > 16000000:
                continue
            original = image.convert('RGBA')
            buffer = BytesIO()
            original.save(buffer, format='WEBP', lossless=True, method=6, exact=True)
            encoded = buffer.getvalue()
            if len(encoded) >= len(raw):
                continue
            webp_size(encoded)
            with Image.open(BytesIO(encoded)) as decoded:
                if decoded.convert('RGBA').tobytes() != original.tobytes():
                    continue
        destination = path.with_suffix('.webp')
        with destination.open('xb') as stream:
            stream.write(encoded)
        results.append(dict(id=int(path.stem), source_sha256=hashlib.sha256(raw).hexdigest(),
                            sha256=hashlib.sha256(encoded).hexdigest()))
    print(json.dumps(results))


if __name__ == '__main__' and len(sys.argv) == 3 and sys.argv[1] == '--worker':
    worker(sys.argv[2])
