#!/usr/bin/env python3
"""List the tar members embedded in a .qpkg and fail if the app payload is missing.

QDK's qbuild silently produces an empty data archive when /usr/bin/rsync is absent,
so every build must pass this check before publishing.
   python3 scripts/inspect-qpkg.py dist/QnapLibrary_X.Y.Z_x86_64.qpkg
"""
import io
import sys
import tarfile
import zlib

REQUIRED = ("qnaplibrary/server.py", "qnaplibrary/web/app.js", "qnaplibrary.sh", "python3-path")


def members(data):
    names, pos = [], 0
    while True:
        pos = data.find(b"\x1f\x8b\x08", pos)
        if pos < 0:
            return names
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            raw = d.decompress(data[pos:], 64 * 1024 * 1024)
            # an inner data.tar.gz stored inside an outer tar is also scanned by the find() loop
            names.extend(tarfile.open(fileobj=io.BytesIO(raw)).getnames())
            pos += len(data[pos:]) - len(d.unused_data)
        except (zlib.error, tarfile.TarError, EOFError):
            pos += 3


def main(path):
    names = members(open(path, "rb").read())
    missing = [r for r in REQUIRED if not any(n.endswith(r) for n in names)]
    print("%d entries" % len(names))
    if missing:
        sys.exit("QPKG payload is missing: %s (is rsync installed?)" % ", ".join(missing))
    print("payload ok")


if __name__ == "__main__":
    main(sys.argv[1])
