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
| POST | `/api/v1/connectors/{id}/run` | 管理者専用。公開検索語の明示承認 `public_query_confirmed:true` が必要（外部APIへ検索語が送信される） |
| POST | `/api/v1/public-patent-guidance` | 管理者専用。固定の公開特許制度ガイドのみAI利用可。 `{topic: novelty|inventive_step|claim_scope|freedom_to_operate|filing_strategy, provider}` |
| GET | `/api/debug/bundle` | AI 向けデバッグ情報 |
| GET | `/api/v1/schema` | 全ルート一覧（AI が自己発見に使う） |
| GET / POST | `/api/backups` | 管理者専用。SQLite バックアップ一覧 / 手動作成（[手順](backup.md)） |
| POST | `/mcp` | MCP（JSON-RPC 2.0）。tools: search, get_document, add_documents, patent_* , debug_bundle |

大量の文献投入には、100〜500件程度のJSONバッチをクライアントから順にPOSTしてください。サーバーは最大5,000件/リクエスト・96MBの要求本文を受け付けますが、NASのメモリ・処理時間を抑えるため小分けを推奨します。外部IDが同じ文献は差分判定され、完全一致なら書き込みを発生させません。**ネットワークエラーで再送しても同じIDなら冪等**です（ただし同じIDに異なる内容を入れた場合は更新）。

カーソル方式の初回は `?cursor=start&limit=100`、続きは `?cursor=<next_cursor>&limit=100` を使用します。`has_more=false` で終了します。ID降順でページを固定するため、途中で新文献が追加されても同一文献の二重取得は発生しません。ただし取り込み中のスナップショットではないため、途中削除や旧文献更新の完全な履歴は保証しません。カーソルモードの `total` は `null`（毎ページの全件カウントを省略）です。従来の `offset` は更新日時順・`total`ありです。

低遅延・大量のAPI検索では、最初に以下の**全文検索モード**を使います。これはOpenRouter等への埋め込み要求を発生させません（権限は従来のBearer/管理セッションのまま）。意味検索が必要な質問だけ `mode: "hybrid"` と任意のリランカーを使います。

```json
{"q":"固体電解質","collections":["patents-jp"],"mode":"keyword","rerank":false,"limit":50,"include_text":false}
```

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

## 文献分析結果

詳細GETの `revision` は本文/メタデータ/明示セクション/出典の版を表す。`POST /api/v1/documents/{id}/analyses` に `{id, kind: summary|claims, source_revision, content}` を送る。管理者またはrw、同一ユーザーの限定analysis認証のみが保存可能。ro/publishedは保存できない。同じID/内容の再送は無変更、同じIDで異なる内容や原文版が変わった要求は拒否する。本文結果は10万文字以内。

`GET /api/v1/documents/{id}/analyses` は最大20件の保存済み結果を新しい順に返し、原文が変わった結果に `stale=true` を付ける。全て `review_status=unreviewed` であり、自動で確認済み/法的結論へ昇格しない。原文の削除時は結果も外部キーで削除する。
