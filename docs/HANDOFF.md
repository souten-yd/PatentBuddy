# HANDOFF — 現在地と次の一手

> 作業の区切りごとに更新すること（DEVELOPMENT_WORKFLOW.md §5）。中断した AI はここから再開する。

## 現在のバージョン

- v0.1.0（PR #1 `feat/v0.1.0-foundation` → main、タグ `v0.1.0` で release.yml が QPKG / Linux tar.gz を公開）

## 状態（2026-11-10）

- [x] 開発ルール（AGENTS.md / DEVELOPMENT_WORKFLOW.md）、実現性評価、RAG DB ランキング、特許ワークフロー設計、提案、ロードマップ
- [x] サーバー本体（REST・MCP・認証・パスキー・LAN ペアリング・検索・特許・AI チャット・コネクタ・デバッグ・自動更新）
- [x] 管理 Web（Playwright で PC 幅 1280px / スマホ幅 390px を確認、コンソールエラー 0）
- [x] Linux パッケージ: 非 root ユーザーで install.sh → 起動 → /api/health 確認
- [x] QPKG: ローカルで QDK ビルド（rsync 代替シム使用）→ 展開 → qnaplibrary.sh start/status/stop を QTS 外で確認
- [ ] QNAP 実機（TS-253Be）でのインストール・Python3 QPKG 連携・HTTPS/パスキー（**未実施**、所有者の確認待ち）
- [ ] 実 LLM（QnapAssistant / OpenRouter）・EPO OPS・JPO API との疎通（キー未設定のため未実施。単体は mock で検証）

## 検証コマンドと結果

- `bash scripts/verify.sh` → 32 tests OK
- `bash scripts/build-linux.sh dist` / `bash scripts/build-qpkg.sh dist`（rsync 必須。無いと QDK が空の data を作るため inspect-qpkg.py で検出して失敗させる）

## 次の一手

1. v0.1.0 リリース後、Linux 版 v0.1.0 → v0.1.1 の自己更新を実地確認（結果をここに記録）
2. `docs/proposals.md` の 1（特許ウォッチ）→ 2（IPC/FI 辞書）→ 3（審査基準）→ 5（期限通知）

## 既知の問題 / 未決事項

- `docs/feasibility.md`「早期判断が必要な点」4 点は所有者の回答待ち（既定は推奨案で実装済み）
- JPO API・USPTO ODP のエンドポイントは公開仕様に基づく実験実装。キー取得後に実地調整が必要
- QTS の Python3 QPKG の SQLite に FTS5 が無い場合は LIKE 検索に自動フォールバック（遅い）。実機で `/api/v1/stats` の `fts5` を確認すること
