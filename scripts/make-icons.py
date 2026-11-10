#!/usr/bin/env python3
"""Render the QPKG icons (PNG) with the standard library only (mirrors web/icon.svg).

Usage: python3 scripts/make-icons.py <output-dir>
"""
import struct
import sys
import zlib
from pathlib import Path

# shapes in a 64x64 design space: (x, y, w, h, rgb)
BG = (0x1f, 0x4f, 0x8f)
BARS = [(13, 14, 8, 36, (255, 255, 255)), (24, 18, 8, 32, (0xcf, 0xe0, 0xff)), (35, 12, 8, 38, (255, 255, 255))]


def inside_round_rect(x, y, size, r):
    if r <= x < size - r or r <= y < size - r:
        return True
    cx = r if x < r else size - r
    cy = r if y < r else size - r
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def pixel(px, py, size, gray):
    x, y = (px + 0.5) * 64 / size, (py + 0.5) * 64 / size
    if not inside_round_rect(x, y, 64, 14):
        return (0, 0, 0, 0)
    color = BG
    for bx, by, bw, bh, c in BARS:
        if bx <= x < bx + bw and by <= y < by + bh:
            color = c
    # tilted yellow book: parallelogram from (46,20)-(53,48)
    t = (y - 20) / 28.0
    if 0 <= t <= 1 and 46 + 7 * t - 3 <= x <= 46 + 7 * t + 3 and 20 <= y <= 49:
        color = (0xff, 0xd1, 0x66)
    if gray:
        g = int(0.3 * color[0] + 0.59 * color[1] + 0.11 * color[2])
        color = (g, g, g)
    return color + (255,)


def png(size, gray=False):
    rows = b"".join(b"\x00" + b"".join(struct.pack("4B", *pixel(x, y, size, gray)) for x in range(size)) for y in range(size))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "QnapLibrary.png").write_bytes(png(256))
    (out / "QnapLibrary_80.png").write_bytes(png(80))
    (out / "QnapLibrary_gray.png").write_bytes(png(256, gray=True))
    print("icons written to", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "qpkg/icons")
