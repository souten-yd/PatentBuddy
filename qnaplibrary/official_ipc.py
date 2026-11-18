"""Official WIPO IPC valid-symbol snapshot, manually installed by section.

Read the fixed WIPO 2026.01 section XML (not PATENTSCOPE), validate and store
only classification codes. This is a classification catalogue, NOT patent data.
It deliberately does not run vector embeddings or create documents/chunks.
"""
import hashlib
import re
import time
from xml.etree import ElementTree as ET

EDITION = "2026.01"
SECTIONS = frozenset("ABCDEFGH")
BASE = ("https://www.wipo.int/classifications/data/ipc/"
        "ITSupport_and_download_area/20260101/valid_symbol_list/")
MAX_SOURCE_BYTES = 3 * 1024 * 1024
MAX_SYMBOLS = 30000
CODE_RE = re.compile(r"^[A-H][0-9]{2}[A-Z](?:[0-9]{1,4}/[0-9]{1,6})?$")


def section_url(section):
    if not isinstance(section, str) or section not in SECTIONS:
        raise ValueError("WIPO IPCのセクションはA〜Hから選んでください")
    return BASE + "ipc_valid_symbols_20260101_" + section + ".xml"


def local_tag(tag):
    return str(tag).rsplit("}", 1)[-1].lower()


def normalized_symbol(raw):
    if not isinstance(raw, str):
        return ""
    code = re.sub(r"\s+", "", raw.upper())
    if not CODE_RE.fullmatch(code):
        return ""
    return code


def parse_valid_symbols(raw, section):
    """Parse WIPO's validity-symbol variants; fail closed on unknown format.

    A class-only symbol is H02 and cannot be a valid IPC search target; only
    subclass H02M and full group symbols enter the collection.
    """
    section_url(section)  # validate section
    if not isinstance(raw, bytes) or len(raw) > MAX_SOURCE_BYTES or not raw:
        raise ValueError("分類辞書が3MiBの上限を超えているか空です")
    if b"<!DOCTYPE" in raw[:4096].upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("DTD・外部実体を含むXMLは許可されません")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise ValueError("IPC有効記号XMLを解析できません") from None

    found = set()
    for node in root.iter():
        kind = local_tag(node.tag)
        candidates = []
        if kind in ("ipc-entry", "classification-item", "ipcr-symbol",
                    "ipc-symbol", "classification-symbol", "valid-symbol"):
            for attribute in ("symbol", "id", "code"):
                if attribute in node.attrib:
                    candidates.append(node.attrib[attribute])
            if kind in ("ipc-symbol", "classification-symbol", "valid-symbol"):
                if node.text and len(node.text) < 32:
                    candidates.append(node.text)
            # WIPO validity symbols may use decomposed ST.8 elements.
            parts = {}
            if kind in ("ipcr-symbol", "ipc-symbol"):
                for child in node:
                    label = local_tag(child.tag)
                    if label in ("section", "class", "subclass", "main-group", "subgroup"):
                        parts[label] = (child.text or "").strip()
                if all(key in parts for key in ("section", "class", "subclass")):
                    sub = (parts["section"] + parts["class"] + parts["subclass"])
                    if "main-group" in parts and "subgroup" in parts:
                        try:
                            sub += str(int(parts["main-group"])) + "/" + str(int(parts["subgroup"])).zfill(2)
                        except ValueError:
                            sub = ""
                    candidates.append(sub)
        for candidate in candidates:
            code = normalized_symbol(candidate)
            if code and code[0] == section:
                found.add(code)
                if len(found) > MAX_SYMBOLS:
                    raise ValueError("分類記号が30,000件を超えました")
    # A non-empty schema with at least one true IPC symbol is required. Never
    # replace a valid existing edition with a silently empty import.
    if not found:
        raise ValueError("有効なIPC記号が検出されませんでした。公式XML形式を確認してください")
    return sorted(found)


def status(store):
    rows = store.q(
        "SELECT edition,section,source_sha256,symbol_count,imported_at "
        "FROM official_ipc_catalogs ORDER BY edition DESC,section")
    return {"catalogs": [dict(r) for r in rows], "source": "WIPO_IPC_valid_symbols",
            "official_edition": EDITION, "sections": sorted(SECTIONS),
            "free_source_url": BASE, "manual_import_only": True,
            "title_coverage": "none_symbols_only",
            "notes": ["この辞書は有効IPC記号の一覧です。タイトル・分類定義は別データです。",
                      "分類辞書の版・セクションと出願公開データは区別します。"]}


def install(store, raw, section):
    """Atomic replace of one edition+section, preserving all other editions."""
    symbols = parse_valid_symbols(raw, section)
    digest = hashlib.sha256(raw).hexdigest()
    current = store.one(
        "SELECT source_sha256,symbol_count FROM official_ipc_catalogs "
        "WHERE edition=? AND section=?", (EDITION, section))
    if current and current[0] == digest and current[1] == len(symbols):
        return {"section": section, "edition": EDITION, "count": len(symbols),
                "unchanged": True, "sha256": digest, "manual_only": True}
    with store.tx() as db:
        db.execute("DELETE FROM official_ipc_symbols WHERE edition=? AND section=?",
                   (EDITION, section))
        db.executemany(
            "INSERT INTO official_ipc_symbols(edition,section,symbol) VALUES(?,?,?)",
            [(EDITION, section, symbol) for symbol in symbols])
        db.execute(
            "INSERT INTO official_ipc_catalogs(edition,section,source_sha256,symbol_count,imported_at) "
            "VALUES(?,?,?,?,?) ON CONFLICT(edition,section) DO UPDATE SET "
            "source_sha256=excluded.source_sha256,symbol_count=excluded.symbol_count,"
            "imported_at=excluded.imported_at",
            (EDITION, section, digest, len(symbols), time.time()))
    return {"section": section, "edition": EDITION, "count": len(symbols),
            "unchanged": False, "sha256": digest, "manual_only": True}


def lookup(store, prefix, *, limit=30):
    prefix = normalized_symbol(prefix)
    if not prefix or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("有効なIPCコードで照会してください")
    # Safe anchored LIKE. Escape wildcard characters before binding.
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = store.q(
        "SELECT edition,section,symbol FROM official_ipc_symbols "
        "WHERE edition=? AND section=? AND symbol LIKE ? ESCAPE '\\' "
        "ORDER BY symbol LIMIT ?", (EDITION, prefix[0], escaped + "%", limit))
    return {"query": prefix, "items": [dict(r) for r in rows], "edition": EDITION,
            "source": "WIPO_IPC_valid_symbols", "official_title_available": False}
