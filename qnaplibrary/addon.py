"""Fail-closed ControlDeck Add-on v2 A0 status.

No Host credentials, proprietary document content, or execution endpoints are
exposed here. The complete Host browser bridge / identity integration is A1.
"""

from . import VERSION


def health_report(local_connected=False):
    """Host Add-on v2 status: do not advertise an unimplemented workspace as ready."""
    report = {
        "app": "PatentBuddy", "version": VERSION, "service_role": "patent-addon",
        "status": "setup_required",
        "contract_version": "2.0",
        "reason_code": "setup_incomplete",
        "message": "ResearchDataHubの接続設定を確認してください。PatentBuddyは特許調査アドオンです。",
        "action": {"kind": "documentation"},
        "contributions": {
            "navigation:workspace": "available",
            "embedded_view:workspace": "available",
        },
        "setup": [{
            "id": "integration", "label": "ResearchDataHubへの接続",
            "state": "missing",
            "detail": "文献の保存先サーバーと接続トークンを設定してください。",
            "action": {"kind": "documentation"},
        }],
    }

    if local_connected:
        report.update(status="healthy", reason_code="ready", message="ResearchDataHubへローカル自動認証で接続済みです。", setup=[])
        report.pop("action", None)
    return report
