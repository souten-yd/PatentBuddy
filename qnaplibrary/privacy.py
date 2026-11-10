"""Fail-closed destinations for non-public inventions and patent documents.

A 'local' provider is a literal loopback address, never a cloud service type,
proxy, or DNS hostname. Private LAN requires a deliberate HTTPS-only opt-in.
"""
import ipaddress
from urllib.parse import urlsplit

PRIVATE_NETS = tuple(ipaddress.ip_network(n) for n in
                     ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                      "100.64.0.0/10", "fc00::/7"))


def local_endpoint(url, allow_lan_https=False):
    try:
        p = urlsplit(str(url or ""))
        if p.scheme not in ("http", "https") or p.username or p.password or p.fragment:
            return False
        if not p.hostname or not p.port and p.netloc.endswith(":"):
            return False
        host = p.hostname.lower().rstrip(".")
        if host == "localhost":
            return True
        addr = ipaddress.ip_address(host)
        if addr.is_loopback:
            return True
        return bool(allow_lan_https and p.scheme == "https" and
                    any(addr in net for net in PRIVATE_NETS))
    except (ValueError, TypeError):
        return False


def confidential_allowed(provider, config):
    # A localhost API may itself be a cloud proxy. An administrator must
    # affirm that the backing model is genuinely local/offline.
    if provider.get("type") == "openrouter" or provider.get("local_only_verified") is not True:
        return False
    allow = config.get("privacy", "allow_lan_https_llm", default=False)
    return local_endpoint(provider.get("base_url"), allow_lan_https=bool(allow))


PUBLIC_REFERENCE_TOPICS = {
    "novelty": "日本の特許制度について、公開されている新規性の一般的な審査上の考え方と確認項目を解説してください。",
    "inventive_step": "特許の進歩性の一般論として、課題と相違点・動機付けを検討する方法を解説してください。",
    "claim_scope": "特許請求の範囲の設計で、独立請求項と従属請求項の役割、明細書サポート要件を一般論として解説してください。",
    "freedom_to_operate": "公開特許を用いたFTO調査の一般的な手順、権利存続期間・請求項解釈・国別判断の注意事項を説明してください。",
    "filing_strategy": "日本国内出願と外国出願、優先権、公開時期の一般的な選択肢を簡潔に説明してください。",
}


def public_reference_messages(topic):
    """Build a fixed prompt WITHOUT a project, custom search, or user-authored text."""
    if topic not in PUBLIC_REFERENCE_TOPICS:
        raise ValueError("公開情報ガイドの種類が不正です")
    return [{"role": "system", "content": "一般公開されている特許制度の説明のみ。個別案件の評価や出願の結論は行わず、公式資料確認を促してください。"},
            {"role": "user", "content": PUBLIC_REFERENCE_TOPICS[topic]}]


def fixed_public_request(path, body):
    """Prove externally-bound prompts equal one of our server-owned templates."""
    if path != "/chat/completions" or not isinstance(body, dict):
        return False
    messages = body.get("messages")
    # A fixed connection check is also public-safe, unlike arbitrary user chat.
    if messages == [{"role": "user", "content": "「OK」とだけ答えてください。"}]:
        return True
    return any(messages == public_reference_messages(topic)
               for topic in PUBLIC_REFERENCE_TOPICS)
