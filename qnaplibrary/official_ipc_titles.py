"""Official WIPO IPC 2026.01 English titles, section-scoped and version-pinned.

Source: https://www.wipo.int/classifications/data/ipc/
 ITSupport_and_download_area/20260101/IPC_scheme_title_list/
 EN_ipc_section_H_title_list_20260101.txt

Each row is TSV: SECTION or CLASS or SUBCLASS or GROUP-code <TAB> title.
Group-code is a longer numeric WIPO key; this first slice imports only the
section, class, subclass labels needed for a low-touch classification browser.
No untrusted URLs, patent data, model calls, or large-body storage.
"""
import hashlib
import re
import time

from .official_ipc import EDITION, SECTIONS

BASE = ("https://www.wipo.int/classifications/data/ipc/"
        "ITSupport_and_download_area/20260101/IPC_scheme_title_list/")
CODE = re.compile(r"^[A-H](?:[0-9]{2}(?:[A-Z])?)?$")
MAX_RAW_BYTES = 2 * 1024 * 1024
MAX_TITLE_BYTES = 4096
MAX_ENTRIES_PER_SECTION = 500
LANGUAGE = "en"


def section_title_url(section):
    if type(section) is not str or section not in SECTIONS:
        raise ValueError("公式IPCセクションはA〜Hを指定してください")
    return BASE + "EN_ipc_section_" + section + "_title_list_20260101.txt"


def parse_titles(raw, section):
    section_title_url(section)
    if not isinstance(raw, bytes) or not 2 <= len(raw) <= MAX_RAW_BYTES:
        raise ValueError("公式IPC分類名リストが空、または2MiBを超えます")
    if b"\x00" in raw:
        raise ValueError("IPCタイトルのデータ形式が不正です")
    try:
        data = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("公式IPC分類名はUTF-8形式でなければなりません") from None
    titles = {}
    previous_heading = None
    for line in data.splitlines():
        if len(line) > 6000:
            raise ValueError("分類名が異常に長い行があります")
        if not line:
            continue
        if "\t" not in line:
            # WIPO's authentic title list sometimes wraps a long GROUP title
            # over multiple physical lines. Do not reject an entire section.
            # Heading continuations are bounded before storing.
            if previous_heading is not None:
                joined = titles[previous_heading] + " " + line.strip()
                if len(joined.encode("utf-8")) > MAX_TITLE_BYTES:
                    raise ValueError("見出しの分類名が大きすぎます")
                titles[previous_heading] = joined
            continue
        code, title = line.split("\t", 1)
        code, title = code.strip(), title.strip()
        previous_heading = None
        # WIPO includes e.g. H02M0001440000 group titles. Only the heading
        # level is used here; never mistake raw group keys for IPC subclasses.
        if not CODE.fullmatch(code):
            if not re.fullmatch(r"[A-H][0-9]{2}[A-Z][0-9]{10}", code):
                raise ValueError("WIPO分類名のコード形式が不正です")
            continue
        if code[0] != section or not title or len(title.encode("utf-8")) > MAX_TITLE_BYTES:
            raise ValueError("分類名のセクション・内容が不正です")
        if code in titles:
            raise ValueError("公式分類名のコードが重複しています")
        titles[code] = title
        previous_heading = code
        if len(titles) > MAX_ENTRIES_PER_SECTION:
            raise ValueError("セクション内の分類名が多すぎます")
    if section not in titles or not any(len(code) == 3 for code in titles) or not any(
            len(code) == 4 for code in titles):
        raise ValueError("WIPOのIPC分類タイトルが不完全です")
    return titles


def import_titles(store, section, raw):
    labels = parse_titles(raw, section)
    digest = hashlib.sha256(raw).hexdigest()
    row = store.one(
        "SELECT source_sha256,entry_count FROM official_ipc_title_catalogs "
        "WHERE edition=? AND section=? AND language=?",
        (EDITION, section, LANGUAGE))
    if row and row[0] == digest and row[1] == len(labels):
        return {"edition": EDITION, "section": section, "language": LANGUAGE,
                "entries": len(labels), "sha256": digest, "unchanged": True}
    with store.tx() as db:
        db.execute("DELETE FROM official_ipc_titles WHERE edition=? AND section=? AND language=?",
                   (EDITION, section, LANGUAGE))
        db.executemany("INSERT INTO official_ipc_titles(edition,section,language,code,title) "
                       "VALUES(?,?,?,?,?)",
                       [(EDITION, section, LANGUAGE, code, title) for code, title in labels.items()])
        db.execute(
            "INSERT INTO official_ipc_title_catalogs "
            "(edition,section,language,source_sha256,entry_count,imported_at) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(edition,section,language) DO UPDATE SET "
            "source_sha256=excluded.source_sha256,entry_count=excluded.entry_count,"
            "imported_at=excluded.imported_at",
            (EDITION, section, LANGUAGE, digest, len(labels), time.time()))
    return {"edition": EDITION, "section": section, "language": LANGUAGE,
            "entries": len(labels), "sha256": digest, "unchanged": False}


def section_status(store):
    rows = store.q(
        "SELECT edition,section,language,entry_count,source_sha256,imported_at "
        "FROM official_ipc_title_catalogs WHERE edition=? ORDER BY section",
        (EDITION,))
    return {"edition": EDITION, "language": LANGUAGE, "source": BASE,
            "imported_sections": [dict(r) for r in rows],
            "type": "official_section_class_subclass_titles",
            "manual_only": True, "english_only": True}


def get_title(store, code):
    if not isinstance(code, str) or not CODE.fullmatch(code):
        return None
    row = store.one(
        "SELECT title FROM official_ipc_titles "
        "WHERE edition=? AND section=? AND language=? AND code=?",
        (EDITION, code[0], LANGUAGE, code))
    return row[0] if row else None
