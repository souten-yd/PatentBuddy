"""Explicit, bounded patent-topic scope suggestions. No requests or writes."""
import re
import unicodedata

# A conservative hand-curated bootstrap, NOT a replacement for IPC/CPC title
# catalogues. Each result is a candidate that needs human confirmation.
CANDIDATES = (
    ("H02M", "電力変換・変換器", ("インバータ", "inverter", "逆変換", "power converter", "コンバータ", "電力変換"), "power"),
    ("H02P", "電動機の制御", ("インバータ", "inverter", "モータ", "motor", "電動機", "ベクトル制御"), "power"),
    ("B60L", "電動車両の電気推進", ("インバータ", "inverter", "電気自動車", "ev", "駆動"), "vehicle"),
    ("H02J", "電力供給・給配電", ("電気", "electric", "電源", "電力", "power", "給電"), "power"),
    ("H01F", "磁石・インダクタ・変圧器", ("電気", "electric", "インダクタ", "チョーク", "transformer", "磁気"), "power"),
    ("H01H", "電気スイッチ", ("電気", "electric", "スイッチ", "switch", "開閉器"), "power"),
    ("F16H", "機械伝動", ("機械", "mechanical", "機構", "ギヤ", "gear", "変速"), "mechanical"),
    ("F16C", "軸・軸受", ("機械", "mechanical", "軸受", "bearing", "シャフト"), "mechanical"),
    ("F16D", "クラッチ・ブレーキ", ("機械", "mechanical", "クラッチ", "clutch", "ブレーキ"), "mechanical"),
    ("F04D", "非容積形ポンプ・送風機", ("機械", "mechanical", "ポンプ", "fan", "送風機"), "mechanical"),
)
SUPPORTED = frozenset(row[0] for row in CANDIDATES)
MAX_TOPIC = 120
DEFAULT_PER_REQUEST = 25


def normalize_topic(topic):
    if not isinstance(topic, str):
        raise ValueError("調査テーマは文字列で指定してください")
    cleaned = unicodedata.normalize("NFKC", topic).strip()
    if not 1 <= len(cleaned) <= MAX_TOPIC or any(ord(c) < 32 or ord(c) == 127 for c in cleaned):
        raise ValueError("調査テーマは制御文字なしの1〜120文字にしてください")
    return cleaned


def plan(topic):
    """Show classifications before external traffic. Never transmit the topic."""
    topic = normalize_topic(topic)
    needle = topic.casefold()
    found = []
    for code, label, terms, category in CANDIDATES:
        if any(term.casefold() in needle for term in terms):
            found.append({"code": code, "scheme": "IPC", "label": label, "category": category,
                          "status": "candidate", "cql_preview": "ic=" + code})
    return {
        "topic": topic, "candidates": found, "preview_only": True,
        "source_options": [
            {"id": "epo_ops", "mode": "existing_connector", "default_limit": DEFAULT_PER_REQUEST,
             "requires_registration": True},
            {"id": "jpo", "mode": "per_application_only", "requires_registration": True},
            {"id": "uspto", "mode": "experimental", "requires_registration": True},
            {"id": "jpo_bulk", "mode": "manual_import_planned"},
            {"id": "patstat_tip", "mode": "export_import_planned"},
        ],
        "limitations": [
            "候補分類は一部のみ。正式なIPC/CPC辞書との照合、検索式の確認が必要です。",
            "分類を選んでも外部通信・収集・保存は始まりません。",
            "未公開テーマを外部検索語に送らないでください。機密確認が必要です。",
            "分類コード単独検索は広すぎる場合があり、技術語・期間・地域で再絞り込みします。",
        ],
        "max_results_per_request": DEFAULT_PER_REQUEST,
    }


def accepted_ipc(code):
    """Only the reviewed bootstrap prefixes may be used for a future CQL."""
    if not isinstance(code, str) or code not in SUPPORTED or not re.fullmatch(r"[A-H][0-9]{2}[A-Z]", code):
        raise ValueError("候補のIPCを選択してください")
    return "ic=" + code
