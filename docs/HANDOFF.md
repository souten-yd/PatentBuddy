# HANDOFF — 現在地と次の一手

> 作業の区切りごとに更新すること（DEVELOPMENT_WORKFLOW.md §5）。中断した AI はここから再開する。

## 現在のバージョン

- **v0.5.0（リリース済み・最新）**: https://github.com/souten-yd/QnapLibrary/releases/tag/v0.5.0 — PR #8 マージ済み。手動 SQLite バックアップ、iOS ホーム画面アイコン、ホーム UI 改善と進行状況表示。
- v0.4.0（直前）: https://github.com/souten-yd/QnapLibrary/releases/tag/v0.4.0
- 履歴: v0.1.1（HTTPS 8443・OpenRouter 埋め込み）→ v0.2.0（ウォッチ・通知・分類・審査基準）→ v0.3.0（Qdrant・リランカー・分析・PC クライアント）→ v0.4.0（調査ジョブ・市場データ・規格）
- ロードマップ v0.1〜v0.5 は完了。次の候補は `docs/roadmap.md` 末尾と `docs/proposals.md`（定期バックアップ・調査の自動化など）

## 状態（2026-11-10）

- [x] 開発ルール（AGENTS.md / DEVELOPMENT_WORKFLOW.md）、実現性評価、RAG DB ランキング、特許ワークフロー設計、提案、ロードマップ
- [x] サーバー本体（REST・MCP・認証・パスキー・LAN ペアリング・検索・特許・AI チャット・コネクタ・デバッグ・自動更新）
- [x] 管理 Web（Playwright で PC 幅 1280px / スマホ幅 390px を確認、コンソールエラー 0）
- [x] Linux パッケージ: 非 root ユーザーで install.sh → 起動 → /api/health 確認
- [x] QPKG: ローカルで QDK ビルド（rsync 代替シム使用）→ 展開 → qnaplibrary.sh start/status/stop を QTS 外で確認
- [ ] QNAP 実機（TS-253Be）でのインストール・Python3 QPKG 連携・HTTPS/パスキー（**未実施**、所有者の確認待ち）
- [ ] 実 LLM（QnapAssistant / OpenRouter）・EPO OPS・JPO API との疎通（キー未設定のため未実施。単体は mock で検証）

## 検証コマンドと結果

- **v0.5.0** の GitHub Actions release workflow（run 42749131155）で Python unit/API **52 tests OK**、Linux tar.gz・QPKG ビルド成功、QPKG payload 検査成功、Release 公開完了。
- このチャットの実行環境では clone/DNS 制限のため `scripts/verify.sh` 全体のローカル実行は未実施。GitHub Actions 上で実行されたのは `unittest` テスト部分であり、verify.sh の Python/JS/shell 静的検査全体と同一ではない。
- `bash scripts/build-linux.sh dist` / `bash scripts/build-qpkg.sh dist`（rsync 必須。無いと QDK が空の data を作るため inspect-qpkg.py で検出して失敗させる）

## 自己更新の実地確認（2026-11-10）

- Linux 版 v0.1.0（非 root ユーザー、`install.sh --no-service`、`qnaplibrary-run`）→ 管理 API「更新を確認」で v0.1.1 を検出 →「適用」→
  GitHub Release から tar.gz を取得し SHA-256 一致 → `versions/0.1.1` 展開・`current` 切替 → 終了コード 75 で再起動 → `/api/health` が 0.1.1、
  更新前に登録した文書が検索で見つかる（データ保持）。旧版 `versions/0.1.0` は残りロールバック可能。
- release.yml（main マージでバージョン変更時）: v0.1.1 で成功（テスト→Linux→QPKG（payload 検査込み）→リリース作成）。
- 見つけた不具合: ランチャーを `qnaplibrary/` フォルダのあるディレクトリから起動すると `python -m` がそちらを読み込む。
  `fix/launcher-cwd` で修正（Linux ランチャーと QPKG ランナーが自分のインストール先へ cd）。v0.2.0 以降に含まれる（既存 Linux インストールでは更新後の install.sh を再実行しないと旧ランチャーが残る可能性あり）。

## 複数版をまたぐ自己更新の確認（2026-11-10）

- Linux 版 v0.1.1 → v0.4.0 を管理 API から一度で更新。新しいテーブル（watches / watch_hits / notify_log）は起動時に自動作成され、既存データは保持。`versions/` に 0.1.0・0.1.1・0.4.0 が残り（直近3版）、`current` は 0.4.0。

## v0.5.0 引き継ぎ内容（PR #8）

- SQLite 管理者専用の手動スナップショット（VACUUM INTO + quick_check、権限 0600、容量確認、Web 画面、API テスト）。
- iOS ホーム画面向け 180×180 不透明 PNG アイコンとメタデータ、既存 SVG/QPKG アイコンの共通デザイン。
- ホーム画面の KPI をモバイル 2 列表示へ整理。処理状況（埋め込み・調査・Qdrant 同期・更新）を既存 API の読み取りのみで表示し、20 秒間隔の状態更新はホーム表示中のみ実施。技術詳細は折りたたみ。
- PR #8 は `main` にマージ済み（squash SHA `bcdc7e5f82eacb0805133f85fb16f2d0836e7933`）。2026-11-10 の GitHub Actions で 52 tests OK、Linux/QPKG 両パッケージ作成・公開を確認。QNAP/iPhone 実機確認は **未実施**。

## 次の一手

1. TS-253Be 実機で v0.5.0 を更新/導入し、アプリ画面と iPhone のホームアイコン、SQLite スナップショット、設定・秘密ファイルの外部保全を確認する。
2. 必要なら開発環境で `bash scripts/verify.sh` 全体（Python/JS/shell 静的検査を含む）を別途実行する。
3. 週次バックアップ、保存世代管理、設定・秘密を含めた完全バックアップ、定期調査とレポート差分を検討する。

## 既知の問題 / 未決事項

- 所有者の決定事項は `docs/feasibility.md` 末尾（パスキー採用、Tailscale 8443、埋め込み既定 OpenRouter、JPO 未登録）
- JPO API・USPTO ODP のエンドポイントは公開仕様に基づく実験実装。キー取得後に実地調整が必要
- QTS の Python3 QPKG の SQLite に FTS5 が無い場合は LIKE 検索に自動フォールバック（遅い）。実機で `/api/v1/stats` の `fts5` を確認すること
