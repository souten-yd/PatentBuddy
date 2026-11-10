# API と接続方法（別PC・AI Assistant・ControlDeck）

## 1. ペアリング（LAN で一度だけ）

管理Web > 設定 > デバイス接続 でパスコードを設定し、クライアントから:

```bash
curl -X POST http://NAS:17871/api/v1/pair -H 'Content-Type: application/json' \
     -d '{"passcode":"<設定したパスコード>","name":"research-pc","scopes":"rw"}'
# => {"token":"qlt_...", ...}   以降 Authorization: Bearer qlt_... を付ける
```

## 2. 主なエンドポイント

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/api/v1/collections` | コレクション一覧 |
| POST | `/api/v1/collections` | 作成 `{name, kind, description}` |
| POST | `/api/v1/collections/{name|id}/documents` | 文書追加/上書き `{documents:[...]}`（最大5000件/回） |
| GET | `/api/v1/collections/{c}/documents?cursor=start&limit=100` | 件数が多い場合のメタデータ一覧。返された `next_cursor` を次回の `cursor` に渡す。従来の `offset` も使用可 |
| GET | `/api/v1/collections/{c}/documents?ext_id=JP2024-123456A` | 公開番号などの**完全一致**ID検索（既存の複合UNIQUE索引を使用）。該当文献のメタデータのみ返す |
| POST | `/api/v1/collections/{c}/import` | `{format: ndjson|json|csv|text, data}` |
| GET | `/api/v1/collections/{c}/export` | NDJSON ストリーム |
| POST | `/api/v1/search` | `{q, collections, limit, mode: hybrid|keyword|vector, vector?, include_text?}` |
| GET | `/api/v1/documents/{id}?chunks=1` | 文書本文とチャンク |
| GET | `/api/v1/collections/{c}/pending-chunks` | 埋め込み未計算のチャンク（外部ワーカー用） |
| POST | `/api/v1/vectors` | `{model, items:[{chunk_id, vector}]}` 外部で計算した埋め込みを格納 |
| GET/POST | `/api/v1/patents...` | 特許案件（`/meta` に段階・タスク一覧） |
| POST | `/api/v1/connectors/{id}/run` | 外部データ収集 |
| GET | `/api/debug/bundle` | AI 向けデバッグ情報 |
| GET | `/api/v1/schema` | 全ルート一覧（AI が自己発見に使う） |
| GET / POST | `/api/backups` | 管理者専用。SQLite バックアップ一覧 / 手動作成（[手順](backup.md)） |
| POST | `/mcp` | MCP（JSON-RPC 2.0）。tools: search, get_document, add_documents, patent_* , debug_bundle |

大量の文献投入には、100〜500件程度のJSONバッチをクライアントから順にPOSTしてください。サーバーは最大5,000件/リクエスト・96MBの要求本文を受け付けますが、NASのメモリ・処理時間を抑えるため小分けを推奨します。外部IDが同じ文献は差分判定され、完全一致なら書き込みを発生させません。**ネットワークエラーで再送しても同じIDなら冪等**です（ただし同じIDに異なる内容を入れた場合は更新）。

カーソル方式の初回は `?cursor=start&limit=100`、続きは `?cursor=<next_cursor>&limit=100` を使用します。`has_more=false` で終了します。ID降順でページを固定するため、途中で新文献が追加されても同一文献の二重取得は発生しません。ただし取り込み中のスナップショットではないため、途中削除や旧文献更新の完全な履歴は保証しません。カーソルモードの `total` は `null`（毎ページの全件カウントを省略）です。従来の `offset` は更新日時順・`total`ありです。

文書の形式:

```json
{"id":"JP2024-123456A","title":"…","abstract":"…",
 "sections":{"claims":"【請求項１】…【請求項２】…","description":"…"},
 "url":"https://…","date":"2024-07-01","source":"JPO","meta":{"ipc":["H01M10/0562"],"applicant":"…"}}
```

## 3. 外部埋め込みワーカーの例（別PC・Ollama）

```python
import json, urllib.request
NAS, TOKEN = "http://NAS:17871", "qlt_..."
def call(m, p, b=None):
    r = urllib.request.Request(NAS + p, method=m, data=json.dumps(b).encode() if b else None,
        headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r))
while True:
    chunks = call("GET", "/api/v1/collections/patents-jp/pending-chunks?limit=64")["chunks"]
    if not chunks: break
    emb = json.load(urllib.request.urlopen(urllib.request.Request("http://localhost:11434/v1/embeddings",
        data=json.dumps({"model": "qwen3-embedding:0.6b", "input": [c["text"] for c in chunks]}).encode(),
        headers={"Content-Type": "application/json"})))["data"]
    call("POST", "/api/v1/vectors", {"model": "qwen3-embedding:0.6b",
         "items": [{"chunk_id": c["chunk_id"], "vector": e["embedding"]} for c, e in zip(chunks, emb)]})
```

## 4. ControlDeck / AI Assistant からの利用

- **ControlDeck**: HTTP ノードで `/api/v1/search` を呼ぶか、MCP 対応エージェントに `http://NAS:17871/mcp`（Bearer トークン）を登録。
- **QnapAssistant**: QnapLibrary 側から OpenAI 互換 `http://127.0.0.1:11435/v1` をチャット/AI支援のプロバイダとして利用（既定で登録済み）。
- **Claude Desktop 等**: MCP の HTTP トランスポートで `/mcp` を指定（ヘッダに Bearer）。
