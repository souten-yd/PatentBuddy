"""Minimal MCP server (JSON-RPC 2.0 over HTTP POST /mcp, "streamable HTTP" without sessions).

Lets AI assistants (QnapAssistant, ControlDeck agents, Claude Desktop via a bridge...) use the
library as tools. Authentication is the same device bearer token as the REST API.
"""
import json

from . import VERSION

PROTOCOL = "2025-06-18"


def _tool(name, description, props, required=()):
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": props, "required": list(required)}}


TOOLS = [
    _tool("list_collections", "ライブラリのコレクション（DB）一覧と件数", {}),
    _tool("search", "ハイブリッド検索（全文＋ベクトル）。特許・規格・ニュース等を横断して根拠付きで返す",
          {"query": {"type": "string"}, "collections": {"type": "array", "items": {"type": "string"}},
           "limit": {"type": "integer", "default": 10}}, ["query"]),
    _tool("get_document", "文書の本文とメタデータを取得", {"doc_id": {"type": "integer"}}, ["doc_id"]),
    _tool("add_documents", "コレクションへ文書を追加/更新（ext_id で上書き）",
          {"collection": {"type": "string"}, "kind": {"type": "string", "default": "generic"},
           "documents": {"type": "array", "items": {"type": "object"}}}, ["collection", "documents"]),
    _tool("patent_projects", "特許案件の一覧（段階・次の期限）", {}),
    _tool("patent_project", "特許案件の詳細（請求項・先行文献・期限）", {"id": {"type": "integer"}}, ["id"]),
    _tool("patent_claim_chart", "請求項の構成要件ごとにライブラリから根拠候補を検索",
          {"id": {"type": "integer"}, "claim_no": {"type": "integer", "default": 1},
           "collections": {"type": "array", "items": {"type": "string"}}}, ["id"]),
    _tool("debug_bundle", "不具合調査用のデバッグ情報（秘密は除去済み）", {}),
]


def handle(app, message, scopes="rw"):
    """Return a JSON-RPC response dict, or None for notifications."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
    mid, method, params = message.get("id"), message.get("method"), message.get("params") or {}
    if mid is None:
        return None  # notification (e.g. notifications/initialized)

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    try:
        if method == "initialize":
            return ok({"protocolVersion": params.get("protocolVersion") or PROTOCOL,
                       "capabilities": {"tools": {"listChanged": False}},
                       "serverInfo": {"name": "QnapLibrary", "version": VERSION},
                       "instructions": "戦略的データベース。search で根拠を探し、get_document で本文を読む。特許案件は patent_* を使う。"})
        if method == "ping":
            return ok({})
        if method == "tools/list":
            return ok({"tools": TOOLS})
        if method == "tools/call":
            name, args = params.get("name"), params.get("arguments") or {}
            data = call_tool(app, name, args, scopes)
            return ok({"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)[:400000]}],
                       "isError": False})
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found: %s" % method}}
    except Exception as error:
        return ok({"content": [{"type": "text", "text": "error: %s" % error}], "isError": True})


def call_tool(app, name, args, scopes):
    if name == "list_collections":
        return app.store.list_collections()
    if name == "search":
        res = app.searcher.search(args.get("query", ""), args.get("collections") or None, int(args.get("limit") or 10))
        for r in res["results"]:
            r.pop("text", None)
        return res
    if name == "get_document":
        return app.store.get_document(int(args["doc_id"]))
    if name == "add_documents":
        if scopes != "rw":
            raise PermissionError("read-only device")
        coll = app.store.ensure_collection(args["collection"], args.get("kind") or "generic")
        return app.store.add_documents(coll["id"], args.get("documents") or [], actor="mcp")
    if name == "patent_projects":
        return app.patents.list()
    if name == "patent_project":
        return app.patents.get(int(args["id"]))
    if name == "patent_claim_chart":
        return app.patents.claim_chart(int(args["id"]), args.get("collections") or None, int(args.get("claim_no") or 1))
    if name == "debug_bundle":
        return app.debug_bundle()
    raise ValueError("unknown tool: %s" % name)
