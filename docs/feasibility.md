# 実現性評価と代替案

評価者: Claude Opus 5.5（フロンティアモデル）／評価日 2026-11-10。対象環境: TS-253Be（Celeron J3455・4C/4T・AVX なし・RAM 16GB・HDD）、QTS 5.x。
判定: ◎ そのまま実現 ／ ○ 制約付きで実現 ／ △ 代替案で実現 ／ × 現実的でない（代替のみ）

| # | 要望 | 判定 | 根拠 | 採用方針・代替案 |
|---|---|---|---|---|
| 1 | NAS の API サーバーを介したデータ収集・格納（別PCから取り込み） | ◎ | 標準ライブラリ HTTP + SQLite で十分 | REST `/api/v1/*` と MCP `/mcp`。取り込みはバッチ JSON / NDJSON |
| 2 | Linux 用サーバーパッケージ + QPKG | ◎ | Python 標準ライブラリのみで両対応 | Linux: tar.gz + `install.sh`（systemd user/system unit）。QPKG: QDK で Release ワークフローのみビルド |
| 3 | GitHub Release から自動更新 | ◎ | QnapDownloader で実績のある方式 | SHA-256（GitHub `digest`）検証 → 切替。QPKG はインストーラ実行、Linux はバージョンディレクトリ切替＋再起動 |
| 4 | LAN から事前パスコードで無制限アクセス | ○ | 平文 HTTP の LAN では盗聴余地あり | ペアリングコード（管理Webで発行・10分有効・1回限り）→ 長期デバイストークン。LAN/Tailscale 送信元のみ有効、レート制限なし。HTTPS 推奨 |
| 5 | 管理 Web に顔認証でアクセス | ○ | ブラウザのカメラも WebAuthn も **HTTPS（secure context）必須**。サーバー側顔認識は J3455 では重く、なりすまし対策も困難 | **パスキー（WebAuthn）で Face ID / Windows Hello 顔認証**。HTTPS は (a) Tailscale の `*.ts.net` 証明書、(b) myQNAPcloud 証明書、(c) 自己署名 CA を端末に導入、のいずれか。HTTP 時はパスワードで入れる |
| 6 | 複数種類の DB 保有、検索、データセット管理（管理 Web） | ◎ | | コレクション＝DB 単位。種別（patent/standard/news/market/generic）ごとのスキーマ付きメタデータ |
| 7 | AI 向けデバッグ情報出力 | ◎ | | `/api/debug/bundle`（秘密除去済み JSON）、検索トレース、直近エラー、遅いクエリ。MCP ツールからも取得 |
| 8 | 同 NAS の AI Assistant（QnapAssistant）・OpenRouter を使う AI チャット | ◎ | QnapAssistant は OpenAI 互換 `:11435/v1` | プロバイダ: QnapAssistant / OpenRouter（モデル・fallback・provider order/only/ignore/sort・data_collection・ZDR・max_price・reasoning・温度等）/ 任意 OpenAI 互換（Ollama 等）。SSE ストリーミング |
| 9 | RAG 向け DB の最新調査と用途別ランキング | ◎ | | `docs/rag-db-ranking.md`。本体は SQLite FTS5 + RAM ベクトル（依存ゼロ）、大規模時は Qdrant コンテナへ拡張 |
| 10 | 埋め込み（ベクトル）を NAS 上で計算 | △ | J3455・AVX なしでは埋め込みモデル推論が遅い（数十〜数百ms/チャンク、大量取り込みは数時間〜日） | **埋め込みは外部で計算**: 別PC（GPU）から `/api/v1/vectors` に投入、または OpenRouter/Ollama の埋め込み API。NAS は BM25(2-gram) を主、ベクトルは任意で併用 |
| 11 | 特許調査（詳細内容・新規特許創出・侵害・新規性） | ○ | 公的 API は登録制・回数上限あり。J-PlatPat の自動取得は不可 | 取り込み経路: JPO 特許情報取得API（要登録）、EPO OPS（無料 4GB/週）、USPTO ODP（要キー、2026-06 からログイン必須）、手動/CSV/XML 取り込み、別PCからの投入。AI 支援は RAG + 構造化プロンプト（請求項分解、クレームチャート、進歩性論点） |
| 12 | 規格調査（JIS 等） | △ | JIS 本文は JISC で**閲覧のみ（印刷・保存不可）**、本文販売は JSA。全文 DB 化は著作権・規約上不可 | 規格**メタデータ**（番号・名称・制定/改正年・対応国際規格・ICS）と、利用者が**正規に入手した PDF/購入版**の私的取り込み、JISC 閲覧ページへのリンク、自分のメモを DB 化 |
| 13 | 世界情勢・市場・ニュース調査 | ○ | GDELT DOC 2.0 は無料・キー不要（直近3か月、約5秒に1回）。NewsAPI 等は有料 | GDELT + RSS（官公庁・各社）+ e-Stat/EDINET/SEC（キー登録制）をコネクタ化。本文の全文保存は配信元の規約に従い、既定は見出し・要約・URL |
| 14 | UI/UX と読み込みのスムーズさ | ◎ | | ビルド不要の軽量 SPA、gzip+ETag+長期キャッシュ、ページング、SSE |
| 15 | ディスク読み書き最小 | ○ | 永続性とのトレードオフ | WAL + NORMAL、RAM キャッシュ、バッチ commit、ログは RAM。HDD スピンダウンを妨げないよう定期書き込みなし |
| 16 | ControlDeck から接続し AI Assistant から活用 | ◎ | ControlDeck は外部検索/RAG ノードを持つ | REST + MCP + OpenAPI 風 `/api/v1/schema`。デバイストークンで接続 |
| 17 | 自動での「戦略的データベース」構築（ローカル LLM による収集・調査） | ○ | 0.6B 級ローカル LLM では要約・分類品質が低い | 収集ジョブはルール/API ベースで確実に、要約・分類は OpenRouter など高性能モデルか別PC LLM に任せる。ジョブは上限件数・頻度付き（暴走防止） |

## 早期判断が必要な点（所有者への提示）

1. **顔認証 = パスキー方式**で良いか（推奨）。カメラ映像をサーバーで照合する方式は HTTPS 必須に加え、J3455 では遅く安全性も劣るため非推奨。
2. **HTTPS の手段**: Tailscale を既に使っているため、`tailscale cert` による `*.ts.net` 証明書が最も簡単（推奨）。
3. **埋め込みの計算場所**: OpenRouter の埋め込み API（有料・少額）か、別PC の Ollama（無料）か。未設定でも全文検索だけで動く。
4. **JPO 特許情報取得API の利用登録**（個人でも可、メール申込）。登録までは EPO OPS・手動取り込みで代替。
