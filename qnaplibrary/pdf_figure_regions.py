"""Optional local-only PDF figure-region preview and crop.

This module is a bounded, opt-in PC worker helper, not an HTTP file serving
endpoint. A candidate rectangle is NOT a verified patent figure or a value
extracted from a chart. The original PDF remains authoritative.

Uses PyMuPDF if installed on the PC; never downloads models or remote data.
"""
import hashlib
import math
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

MAX_PDF = 50 * 1024 * 1024
MAX_PAGES = 200
MAX_SCAN_PAGES = 12
MAX_CANDIDATES = 60
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_PIXELS = 16_000_000


def _fitz():
    try:
        import importlib
        # The core remains stdlib-only; PyMuPDF is optional and loaded only
        # inside the resource-limited child on an explicitly imported PDF.
        fitz = importlib.import_module("fitz")
    except ImportError as error:
        raise RuntimeError("図面位置の解析には任意のローカルPyMuPDFが必要です") from error
    return fitz


def _open(path):
    fitz = _fitz()
    pdf = Path(path)
    if pdf.is_symlink() or not pdf.is_file() or not 5 <= pdf.stat().st_size <= MAX_PDF:
        raise ValueError("通常の50MiB以下のPDFだけ指定できます")
    doc = fitz.open(str(pdf))
    if doc.needs_pass or not 1 <= len(doc) <= MAX_PAGES:
        doc.close()
        raise ValueError("暗号化PDFまたはページ数が上限外です")
    return doc


def _rect(rect, width, height):
    if not isinstance(rect, (list, tuple)) or len(rect) != 4:
        raise ValueError("座標は[x0,y0,x1,y1]で指定してください")
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in rect):
        raise ValueError("座標が不正です")
    x0, y0, x1, y1 = (float(value) for value in rect)
    if x0 < 0 or y0 < 0 or x1 > width + 0.01 or y1 > height + 0.01 or x1-x0 < 10 or y1-y0 < 10:
        raise ValueError("切り抜き領域がページ範囲外か小さすぎます")
    return (round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2))


def scan(path, *, limit_pages=MAX_SCAN_PAGES):
    """Find image and large-vector candidate bounds, never claiming verification.

    Scanned full-page images are intentionally not labelled as individual figures.
    The result is metadata only; no source PDF or bitmap is returned.
    """
    if type(limit_pages) is not int or not 1 <= limit_pages <= MAX_SCAN_PAGES:
        raise ValueError("スキャン対象ページ数は1〜12です")
    doc = _open(path)
    try:
        found = []
        for page_num in range(min(len(doc), limit_pages)):
            page = doc[page_num]
            width, height = float(page.rect.width), float(page.rect.height)
            if width <= 0 or height <= 0:
                continue
            boxes = []
            for img in page.get_image_info(xrefs=False)[:80]:
                try:
                    bbox = _rect(tuple(img["bbox"]), width, height)
                except (ValueError, KeyError):
                    continue
                if (bbox[2]-bbox[0]) * (bbox[3]-bbox[1]) > .85 * width * height:
                    continue
                boxes.append(("embedded_image", bbox))
            # Large drawing paths provide hints for vector-line patent figures.
            # Do not merge arbitrary paths across diagrams: that would invent a
            # region and could hide captions, dimensions, or unrelated figures.
            for drawing in page.get_drawings()[:400]:
                try:
                    bbox = _rect(tuple(drawing["rect"]), width, height)
                except (ValueError, KeyError):
                    continue
                area = (bbox[2]-bbox[0]) * (bbox[3]-bbox[1])
                if area >= 2500 and area <= .75 * width * height:
                    boxes.append(("vector_region", bbox))
            # Stable candidate ordering, de-duplication, and per-document cap.
            seen = set()
            for kind, bbox in boxes:
                ident = (page_num + 1, bbox)
                if ident in seen:
                    continue
                seen.add(ident)
                found.append({"page": page_num + 1, "bbox_points": list(bbox),
                              "kind": kind, "status": "unreviewed", "figure_number": None,
                              "origin": "local_pdf_geometry"})
                if len(found) >= MAX_CANDIDATES:
                    break
            if len(found) >= MAX_CANDIDATES:
                break
        return {"page_count": len(doc), "pages_scanned": min(len(doc), limit_pages),
                "candidates": found, "truncated": len(found) >= MAX_CANDIDATES,
                "note": "図面領域の候補です。図番号・切り抜き位置は原本と照合してください。表やグラフの値は抽出しません。"}
    finally:
        doc.close()


def crop(path, *, page_number, bbox_points, dpi=120):
    """Render a verified rectangle to bounded PNG; caller owns private storage."""
    if type(page_number) is not int or not 1 <= page_number <= MAX_PAGES:
        raise ValueError("ページ番号が不正です")
    if type(dpi) is not int or not 72 <= dpi <= 160:
        raise ValueError("解像度は72〜160dpiです")
    doc = _open(path)
    try:
        if page_number > len(doc):
            raise ValueError("ページが存在しません")
        page = doc[page_number-1]
        box = _rect(bbox_points, page.rect.width, page.rect.height)
        pixels = (box[2]-box[0]) * (box[3]-box[1]) * (dpi/72)**2
        if pixels > MAX_PIXELS:
            raise ValueError("画像領域が大きすぎます")
        fitz = _fitz()
        pix = page.get_pixmap(dpi=dpi, clip=fitz.Rect(box), alpha=False)
        raw = pix.tobytes("png")
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("圧縮後の画像が2MiBを超えています")
        return {"png": raw, "page": page_number, "bbox_points": list(box), "dpi": dpi,
                "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw),
                "width": pix.width, "height": pix.height,
                "method": "local_pdf_page_crop", "status": "unreviewed"}
    finally:
        doc.close()



def embedded_figure_labels(pdf, directory, first):
    """Match standalone native captions to one nearby, pixel-identical embedded image."""
    fitz = _fitz()
    if not first:
        return []
    matches = defaultdict(list)
    with _open(pdf) as doc:
        for page in doc:
            captions = []
            for block in page.get_text("blocks"):
                label = unicodedata.normalize("NFKC", block[4]).strip()
                match = re.fullmatch(r"(?:【図([1-9][0-9]{0,2})】|FIG\.?\s*([1-9][0-9]{0,2}))", label, re.I)
                if match:
                    captions.append((block, int(match[1] or match[2])))
            if not captions:
                continue
            placements = page.get_image_info(hashes=True)
            proposals = defaultdict(list)
            for block, number in captions:
                nearby = [item for item in placements
                          if abs(item["bbox"][0] - block[0]) <= 12
                          and 0 <= item["bbox"][1] - block[3] <= 18]
                if len(nearby) == 1 and sum(n == number for _, n in captions) == 1:
                    proposals[nearby[0]["digest"]].append(number)
            for digest, numbers in proposals.items():
                if len(numbers) == 1 and sum(item["digest"] == digest for item in placements) == 1:
                    matches[digest].append((page.number + 1, numbers[0]))
    labels = []
    if matches:
        for index in range(first):
            path = directory / ("%d.png" % index)
            if path.is_file():
                pix = fitz.Pixmap(str(path))
                for page, number in matches.get(pix.digest, []):
                    labels.append([index, page, number])
                    if len(labels) >= 200:
                        return labels
    return labels


def _isolated_worker():
    """Private PC PDF geometry worker; only invoked with exact arguments by parent.

    Standard input is closed, no shell or arbitrary command selection, and no
    network or external AI call is used. Results are unreviewed candidates.
    """
    import json
    import resource
    import sys

    if len(sys.argv) != 6 or sys.argv[1] != "--isolated-worker":
        raise SystemExit(2)
    pdf, directory = Path(sys.argv[2]), Path(sys.argv[3])
    try:
        first, count = int(sys.argv[4]), int(sys.argv[5])
    except ValueError:
        raise SystemExit(2)
    if not 0 <= first <= 200 or not 1 <= count <= 12 or first + count > 200:
        raise SystemExit(2)
    # Limits are installed BEFORE loading the optional third-party PDF parser.
    # Fsize applies to any one output file; parent also checks combined bytes.
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (40, 40))
    resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024, 2 * 1024 * 1024))
    if pdf.is_symlink() or not pdf.is_file() or directory.is_symlink() or not directory.is_dir():
        raise SystemExit(2)
    try:
        candidates = scan(pdf, limit_pages=12)
    except RuntimeError:
        print(json.dumps({"status": "optional_pdf_geometry_unavailable", "images": [],
                          "candidates": [], "truncated": False}), flush=True)
        return
    try:
        labels = embedded_figure_labels(pdf, directory, first)
    except (RuntimeError, ValueError):
        labels = []
    images = []
    for candidate in candidates["candidates"][:count]:
        try:
            result = crop(pdf, page_number=candidate["page"],
                          bbox_points=candidate["bbox_points"], dpi=120)
        except ValueError:
            continue
        image_id = first + len(images)
        dest = directory / ("%d.png" % image_id)
        # 'xb' refuses existing extracted source images. Never overwrite.
        with dest.open("xb") as stream:
            stream.write(result["png"])
        images.append({"id": image_id, "page": candidate["page"],
                       "kind": "figure_candidate", "width": result["width"],
                       "height": result["height"], "sha256": result["sha256"],
                       "size_bytes": result["size_bytes"],
                       "method": "local_pdf_page_crop", "review_status": "unreviewed",
                       "bbox_points": result["bbox_points"]})
    print(json.dumps({
        "status": "unreviewed", "pages_scanned": candidates["pages_scanned"],
        "candidates": candidates["candidates"][:60],
        "truncated": candidates["truncated"] or len(candidates["candidates"]) > count,
        "images": images, "embedded_labels": labels,
    }, ensure_ascii=False, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    _isolated_worker()
