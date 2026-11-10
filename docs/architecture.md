# アーキテクチャ

```
 別PC / AI / ControlDeck ──(Bearer token)──┐          ┌── QnapAssistant :11435/v1 (同NAS)
 ブラウザ(管理Web, パスキー) ──(cookie+CSRF)─┤          ├── OpenRouter (詳細ルーティング)
                                            ▼          │
                     QnapLibrary :17871  ThreadingHTTPServer (stdlib)
                     ├ api.py  REST /api/v1/*  + /mcp (JSON-RPC)
                     ├ auth    パスワード / WebAuthn / LANペアリング
                     ├ search  FTS5(2-gram BM25) + RAMベクトル → RRF
                     ├ patents 案件・期限・構成要件・AI支援
                     ├ connectors GDELT / RSS / EPO OPS / JPO / USPTO
                     ├ debuglog RAMリング → /api/debug/bundle
                     └ updater GitHub Releases (SHA-256) → 切替/QPKG
                                 │
                       data dir: settings.json / secrets.json(0600) / library.sqlite3(WAL)
```

## データモデル

- `collections`（DB）: name, kind（generic/patent/standard/news/market/law/paper/note）
- `documents`: ext_id（外部ID、同一IDは上書き＝冪等な再投入）, title, url, source, date, meta(JSON), body, hash（変更なしの再投入はディスクに書かない）
- `chunks` + `chunks_fts`（FTS5）: 本文を約800字で分割、特許の請求項は 1 項 1 チャンク
- `vectors`: chunk_id → float32 BLOB（外部で計算した埋め込み）
- `patents` / `patent_events` / `patent_claims`（版）/ `patent_refs`（X/Y/A 分類）
- `devices`（トークンは SHA-256 で保存）/ `passkeys` / `chat_threads` / `chat_messages` / `audit`

## 大規模化の実装方針（PR #13）

- NAS側は外部IDによる冪等取り込みをバッチ化し、FTS5日本語2-gramとSQLite索引で検索する。
- 全文を含む文書詳細と一覧の読み出しを分離する。一覧は必要項目だけにし、深いページ取得にはIDカーソルを使う。
- 既存のコレクション・索引・認証・データをそのまま維持。最初の起動時のみ新しい文献カーソル索引を作成する（大容量DBで起動が長くなる可能性）。
- ベクトル規模が増えたときのQdrant/PC分担・実データ性能測定は [scalability.md](scalability.md) にまとめる。

## 低ディスク I/O の工夫

| 項目 | 方法 |
|---|---|
| SQLite | WAL、synchronous=NORMAL、cache 64MB、mmap 256MB、temp_store=MEMORY、バッチトランザクション |
| 再投入 | 内容ハッシュが同じ文書は書き込まない |
| アクセスログ | 書かない（RAM リングのみ） |
| デバイス最終利用 | 10 分に 1 回だけ更新 |
| 静的ファイル | 起動後は RAM から gzip 済みで配信、ETag で 304 |
| ベクトル | 初回検索時に RAM へ読み込み、変更時のみ再読込 |
| 定期処理 | 更新確認（1日1回）はネットワークのみでディスクに書かない |

## セキュリティ

- 管理 API はセッション（RAM、HttpOnly、SameSite=Strict）＋ CSRF トークン＋ Origin 検査。
- デバイストークンは LAN / Tailscale 送信元のみ有効（`server.allow_remote_devices` で変更可）。ro / rw スコープ。
- ログイン・ペアリング・パスキーは IP ごとの失敗回数制限。
- コネクタは公開アドレスのみ取得（SSRF 対策）、応答 8MB 上限。
- CSP `default-src 'self'`、frame-ancestors none、外部 CDN 不使用。
- 任意コマンド実行 API なし。更新は署名ではなく GitHub の SHA-256 digest と固定 URL で検証。
