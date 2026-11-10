"""ControlDeck Add-on v2 health: only fields accepted by the Host contract."""


def health_report(connection_configured=False):
    """Host Add-on v2 status: do not advertise an unimplemented workspace as ready."""
    report = {
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

    if connection_configured:
        report.update(status="healthy", message="ResearchDataHubの接続設定があります。接続状況は画面で確認してください。", setup=[])
        report.pop("action", None)
        report.pop("reason_code", None)
    return report
