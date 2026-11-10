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
| POST | `/api/v1/collections/{c}/import` | `{format: ndjson|json|csv|text, data}` |
| GET | `/api/v1/collections/{c}/export` | NDJSON ストリーム |
| POST | `/api/v1/search` | `{q, collections, limit, mode: hybrid|keyword|vector, vector?, include_text?}` |
| GET | `/api/v1/documents/{id}?chunks=1` | 文書本文とチャンク |
| GET | `/api/v1/collections/{c}/pending-chunks` | 埋め込み未計算のチャンク（外部ワーカー用） |
| POST | `/api/v1/vectors` | `{model, items:[{chunk_id, vector}]}` 外部で計算した埋め込みを格納 |
| GET/POST | `/api/v1/patents...` | 特許案件（`/meta` に段階・タスク一覧） |
| POST | `/api/v1/connectors/{id}/run` | 管理者専用。公開検索語の明示承認 `public_query_confirmed:true` が必要（外部APIへ検索語が送信される） |
| POST | `/api/v1/public-patent-guidance` | 管理者専用。固定の公開特許制度ガイドのみAI利用可。 `{topic: novelty|inventive_step|claim_scope|freedom_to_operate|filing_strategy, provider}` |
| GET | `/api/debug/bundle` | AI 向けデバッグ情報 |
| GET | `/api/v1/schema` | 全ルート一覧（AI が自己発見に使う） |
| GET / POST | `/api/backups` | 管理者専用。SQLite バックアップ一覧 / 手動作成（[手順](backup.md)） |
| POST | `/mcp` | MCP（JSON-RPC 2.0）。tools: search, get_document, add_documents, patent_* , debug_bundle |

文書の形式:

```json
{"id":"JP2024-123456A","title":"…","abstract":"…",
 "sections":{"claims":"【請求項１】…【請求項２】…","description":"…"},
 "url":"https://…","date":"2024-07-01","source":"JPO","meta":{"ipc":["H01M10/0562"],"applicant":"…"}}
```

## 3. 埋め込みワーカーの例（**信頼できるオフライン別PCのOllama専用**）

**機密警告:** このAPIを利用した場合は機密文書本文がAPIクライアントへ渡ります。別PCの推論エンジンがクラウド中継しないことと、NAS-PC間の通信を保護することを事前に確認してください。クラウドエンベディングへ送信してはいけません。

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
- **QnapAssistant**: QnapPatentBuddy 側から OpenAI 互換 `http://127.0.0.1:11435/v1` をチャット/AI支援のプロバイダとして利用（既定で登録済みだが**ローカル専用と管理者が確認するまで機密利用不可**）。
- **Claude Desktop 等**: MCP に機密情報を公開する場合は、接続先がクラウドへ記録・転送しないことを確認してください。HTTP トランスポートで `/mcp` を指定（ヘッダに Bearer）。

## 5. 機密保護（v0.5.1）

未公開の発明/要約/請求項/検索語/論点/引用の組み合わせはデフォルト機密。バックエンドがクラウドLLM・クラウド埋め込み・リランカへの送信を拒否します。ローカルAIはモデルの実体と中継設定を管理者が確認済みである必要があります（`local_only_verified:true`）。管理用APIに機密プロンプトを付与しただけで公開送信の例外指定はできません。

**ウォッチ:** `params.public_only_confirmed:true` がない旧ウォッチは自動外部収集停止。公開検索語のみと承認したものだけ再開できます。外部検索APIの実行は管理者専用。通知には案件名/本文を含めません。詳しくは [privacy-boundary.md](privacy-boundary.md)。


## 公開承認済み資料（v0.5.4）

管理セッションで `POST /api/v1/publications/preview`（doc_id, excerpt）を呼び、返されたpublicationのtitle/publication_number/textを全件確認する。同じdoc_id/excerptとpreview_token、confirm_public:trueで `POST /api/v1/publications` を呼ぶ。10分期限・文献変更・再起動後はプレビューを取り直す。取消は `DELETE /api/v1/publications/{doc_id}`。

管理者発行のscopes=published tokenは `POST /api/v1/public-catalog/search`（q, limit:最大50）と `GET /api/v1/public-catalog/{public_id}` のみ。元文献、案件、MCP、debug/export、設定APIへのアクセス不可。通常rw/ro tokenとは権限が異なる。loopback以外はHTTPS必須。公開APIは外部LLMを呼ばない。詳しくはpublic-catalog.md。
