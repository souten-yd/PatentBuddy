"""User-initiated source smoke checks using configured credentials only.

No data import, no key returned, no arbitrary URL, no spontaneous scheduling.
Provider availability and app operational readiness are separate concepts.
"""
import re

from . import connectors
from .official_ipc_titles import section_title_url, parse_titles
from .official_ipc import section_url, parse_valid_symbols

SOURCE_IDS = ("wipo_ipc_titles", "wipo_ipc_symbols", "epo_ops",
              "jpo", "uspto", "openalex")
REQUIRED_KEYS = {
    "wipo_ipc_titles": (),
    "wipo_ipc_symbols": (),
    "epo_ops": ("epo_ops_key", "epo_ops_secret"),
    "jpo": ("jpo_username", "jpo_password"),
    "uspto": ("uspto_api_key",),
    "openalex": (),
}


def readiness(secret):
    items = []
    for source_id in SOURCE_IDS:
        keys = REQUIRED_KEYS[source_id]
        configured = all(bool(secret(key)) for key in keys)
        items.append({
            "id": source_id,
            "keys_required": bool(keys),
            "configured": configured,
            "run_requires_admin_action": True,
            "last_live_tested": False,  # no saved verifications; never fabricate
            "status": "ready_for_manual_test" if configured else "requires_key_at_install",
            "uses_private_query": False,
        })
    return {"items": items, "no_automatic_test": True,
            "note": "ここに表示するreadyは接続成功を意味しません。実際のテストを実行してください。"}


def probe(name, secret, *, public_sample="", section="H"):
    """Return only sample count and categorical status, never raw response or keys.

    Network is intentionally performed only after an authenticated administrator
    explicitly clicks a test button. No test writes SQLite documents.
    """
    if name not in SOURCE_IDS:
        raise ValueError("未対応のソースです")
    required = REQUIRED_KEYS[name]
    missing = [key for key in required if not secret(key)]
    if missing:
        return {"source": name, "status": "requires_key_at_install",
                "success": False, "received": 0, "reason_code": "missing_credentials",
                "manual_only": True}
    try:
        if name == "wipo_ipc_titles":
            raw = connectors.http_get(section_title_url(section), timeout=45, pace=2.0)
            count = len(parse_titles(raw, section))
        elif name == "wipo_ipc_symbols":
            raw = connectors.http_get(section_url(section), timeout=45, pace=2.0)
            count = len(parse_valid_symbols(raw, section))
        elif name == "epo_ops":
            # Fixed PUBLIC classification only, no unpublished theme text.
            docs = connectors.epo_search("ic=H02M and pn=EP", secret("epo_ops_key"),
                                         secret("epo_ops_secret"), limit=1)
            count = len(docs)
        elif name == "jpo":
            # No fabricated sample application; the user chooses a public one.
            if not isinstance(public_sample, str) or not re.fullmatch(
                    r"(?:[0-9]{4}-?)?[0-9]{6}", public_sample):
                return {"source": name, "status": "requires_public_application",
                        "success": False, "received": 0, "reason_code": "sample_required",
                        "manual_only": True}
            docs = connectors.jpo_progress(public_sample, secret("jpo_username"), secret("jpo_password"))
            count = len(docs)
        elif name == "uspto":
            # Fixed generic PUBLIC technical query; the account must be enabled.
            docs = connectors.uspto_search("inverter", secret("uspto_api_key"), limit=1)
            count = len(docs)
        else:
            # Low-cost, first-page scientific metadata only. Anonymous mode
            # can work as a demo, but a free key is preferred for normal use.
            docs = connectors.openalex_works("inverter", secret("openalex_api_key") or "", limit=1)
            count = len(docs)
        return {"source": name, "status": "sample_verified" if count else "empty_sample",
                "success": bool(count), "received": count, "reason_code": "",
                "manual_only": True, "no_data_written": True}
    except (connectors.ConnectorError, ValueError, TypeError, OSError):
        # Provider errors may contain tokens or user identifiers. Never expose
        # raw exceptions through the browser or persist as source history.
        return {"source": name, "status": "failed", "success": False, "received": 0,
                "reason_code": "provider_or_schema_error", "manual_only": True,
                "no_data_written": True}
