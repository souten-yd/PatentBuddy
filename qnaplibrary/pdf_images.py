"""Bounded extraction and validation of embedded PDF raster images."""
import hashlib
from pathlib import Path
import re
import struct
import zlib

MAX_IMAGES = 200
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_PIXELS = 16000000


def png_size(data):
    if not isinstance(data, bytes) or not 33 <= len(data) <= MAX_IMAGE_BYTES or data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('画像は2MiB以内のPNGにしてください')
    pos, dimensions, ended, has_pixels = 8, None, False, False
    while pos < len(data):
        if len(data) - pos < 12:
            raise ValueError('PNGのチャンクが不正です')
        length = struct.unpack('>I', data[pos:pos + 4])[0]
        end = pos + length + 12
        if end > len(data):
            raise ValueError('PNGの長さが不正です')
        kind = data[pos + 4:pos + 8]
        if zlib.crc32(data[pos + 4:end - 4]) != struct.unpack('>I', data[end - 4:end])[0]:
            raise ValueError('PNGのCRCが一致しません')
        if pos == 8:
            if kind != b'IHDR' or length != 13:
                raise ValueError('PNGのヘッダーが不正です')
            dimensions = struct.unpack('>II', data[pos + 8:pos + 16])
            if not all(dimensions) or dimensions[0] * dimensions[1] > MAX_PIXELS:
                raise ValueError('画像の画素数が上限を超えました')
        if kind == b'IDAT' and length:
            has_pixels = True
        if kind == b'IEND':
            ended = length == 0 and end == len(data)
            break
        pos = end
    if not ended or not has_pixels:
        raise ValueError('PNGが完了していません')
    return dimensions


def extract_images(pdf, directory, listing, cancel, run):
    rows = {}
    for line in listing.splitlines():
        fields = line.split()
        if len(fields) >= 5 and fields[0].isdigit() and fields[1].isdigit():
            page, index, width, height = int(fields[0]), int(fields[1]), int(fields[3]), int(fields[4])
            if width * height > MAX_PIXELS or len(rows) >= MAX_IMAGES:
                raise ValueError('PDF内の画像は200点・各1600万画素以内にしてください')
            rows[index] = {'page': page, 'kind': fields[2], 'width': width, 'height': height}
    target = Path(directory)
    target.mkdir(mode=0o700)
    if not rows:
        return []
    # All names are produced by pdfimages under the caller's private scratch.
    # The worker caps each output file at 2MiB; at most 200 files are possible.
    run('pdfimages', ['-png', '-p', str(pdf), str(target / 'image')], target, cancel)
    images, total = [], 0
    for path in sorted(target.iterdir()):
        if path.name == 'command-output':
            continue
        match = re.fullmatch(r'image-([0-9]+)-([0-9]+)\.png', path.name)
        if not match or path.is_symlink() or not path.is_file():
            raise ValueError('画像抽出の出力形式が不正です')
        page, index = int(match[1]), int(match[2])
        row = rows.get(index)
        if not row or row['page'] != page or path.stat().st_size > MAX_IMAGE_BYTES:
            raise ValueError('画像のページまたはサイズが一致しません')
        data = path.read_bytes(); total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise ValueError('PDF内の画像合計が32MiBを超えました')
        width, height = png_size(data)
        if (width, height) != (row['width'], row['height']):
            raise ValueError('画像の寸法が一致しません')
        destination = target / ('%d.png' % index)
        path.rename(destination)
        images.append({'id': index, 'page': page, 'kind': row['kind'], 'width': width, 'height': height,
                       'sha256': hashlib.sha256(data).hexdigest(), 'size_bytes': len(data),
                       'method': 'pdfimages_png', 'review_status': 'unreviewed'})
    if len(images) != len(rows):
        raise ValueError('一部の画像を抽出できませんでした')
    return sorted(images, key=lambda item: item['id'])
