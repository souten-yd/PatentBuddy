"""Fail-closed ControlDeck Add-on v2 A0 status.

No Host credentials, proprietary document content, or execution endpoints are
exposed here. The complete Host browser bridge / identity integration is A1.
"""

from . import VERSION


def health_report():
    """Host Add-on v2 status: do not advertise an unimplemented workspace as ready."""
    return {
        "status": "setup_required",
        "contract_version": "2.0",
        "reason_code": "setup_incomplete",
        "message": "ControlDeck連携の初期設定が必要です。既存データの移行と認証連携は未実施です。",
        "action": {"kind": "documentation"},
        "contributions": {
            "navigation:workspace": "available",
            "embedded_view:workspace": "available",
        },
        "setup": [{
            "id": "integration", "label": "ControlDeck認証とデータの移行",
            "state": "missing",
            "detail": "A0: 登録/状態ページのみ。読み書き・AIは未公開。",
            "action": {"kind": "documentation"},
        }],
    }
