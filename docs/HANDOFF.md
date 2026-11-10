# HANDOFF — 現在地と次の一手

> 作業の区切りごとに更新すること（DEVELOPMENT_WORKFLOW.md §5）。中断した AI はここから再開する。

## 現在のバージョン

- v0.1.0: PR #1 をマージ済み（リリースは未作成。開発環境からのタグ push・API でのタグ作成・workflow_dispatch がプロキシで禁止されているため）
- v0.1.1: PR #2（release.yml を「main マージでバージョンファイルが変わったら自動リリース」に変更、Tailscale Serve HTTPS、OpenRouter 既定の自動ベクトル化、未登録キーの収集元を無効表示）

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

1. PR #2 マージ → v0.1.1 の自動リリース確認 → ローカルの Linux 版 v0.1.0 から v0.1.1 への自己更新を実地確認（結果をここに記録）
2. `docs/proposals.md` の 1（特許ウォッチ）→ 2（IPC/FI 辞書）→ 3（審査基準）→ 5（期限通知）

## 既知の問題 / 未決事項

- 所有者の決定事項は `docs/feasibility.md` 末尾（パスキー採用、Tailscale 8443、埋め込み既定 OpenRouter、JPO 未登録）
- JPO API・USPTO ODP のエンドポイントは公開仕様に基づく実験実装。キー取得後に実地調整が必要
- QTS の Python3 QPKG の SQLite に FTS5 が無い場合は LIKE 検索に自動フォールバック（遅い）。実機で `/api/v1/stats` の `fts5` を確認すること
