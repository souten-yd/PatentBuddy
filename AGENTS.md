# AGENTS.md — AI エージェント／開発者向けガイド

> **2026-11-10の開発方針（最優先）**: 汎用データ保存・収集・検索APIサーバーの新しい表示名は**ResearchDataHub**、ControlDeck特許専用アドオンは**PatentBuddy**。まずRyzen 7 9700XのLinux PCで両方を開発・結合し、完成後にResearchDataHubの唯一の正本DB/実行先をQNAPへ移行する。旧QPKG/SQLite/パスキーを維持し、未公開発明・請求項を外部LLMに渡さない（ローカルLLMへの入力、認証済みPC↔NASの転送は可）。正本は `docs/researchdatahub-plan.md`、Codex指示は `docs/CODEX_NEXT.md`、進捗は `docs/HANDOFF.md`。**PR #16はdocs-only、Linux別名入口は未実装。**

## 最初に読む順番

1. 本ファイル（概要と絶対ルール）
2. `DEVELOPMENT_WORKFLOW.md`（PR・CI・リリース・文書ルール）
3. `docs/HANDOFF.md`（**現在地と次の一手**。引き継ぎ時はここから再開）
4. `docs/researchdatahub-plan.md`、`docs/CODEX_NEXT.md`（新アーキテクチャとCodex実装契約）
5. 必要に応じて `docs/architecture.md`、`docs/patent-workflow.md`、`docs/feasibility.md`

## プロジェクト概要

現時点の実装は内部名 `QnapLibrary` のQNAP/Linux対応アプリ。将来の役割は、ResearchDataHub（特許・規格・技術文献等の汎用データAPI基盤）とPatentBuddy（ControlDeck特許専用アドオン）に分割していく。ただし既存の内部パス/QPKGを一括改名しない。
- API サーバー: LAN の PC・AI（ControlDeck、QnapAssistant 等）からデータ取り込み・検索・格納
- 複数コレクション（DB）: 全文検索（SQLite FTS5 + 日本語 2-gram）＋任意のベクトル検索、ハイブリッド RRF
- 特許支援（最優先）: 発明登録→先行技術調査→請求項→出願→審査→登録までの案件管理と AI 支援
- 管理 Web: パスワード＋パスキー（Face ID 等の顔認証）でログイン、コレクション/データセット管理、検索、AI チャット
- AI 向けデバッグ出力: `/api/debug/bundle` で状態・直近エラー・検索トレースを JSON で取得
- MCP（`/mcp`）: AI アシスタントからツールとして利用
- 自動更新: GitHub Releases から SHA-256 検証付き

## 起動とテスト

```bash
python3 -m qnaplibrary --data ./.data --port 17871   # 開発起動（初回は管理Webで管理者パスワード設定）
bash scripts/verify.sh                                # 全テスト＋静的チェック（マージ前に必須）
bash scripts/build-linux.sh dist                      # Linux 配布物
```

## 新アーキテクチャの絶対条件

- ResearchDataHubのDB正本は常に1個。開発中はPC SSD、完成後にQNAPのローカルディスクへ移す。**同時二重書込みとSMB/NFS共有上の稼働SQLiteは禁止**。
- 未公開アイデア・発明・請求項・調査履歴をOpenRouterなどの外部LLMへ入力しない。ローカルに見えてもクラウド中継するモデルは不可。公開資料だけ別権限で手動確認して扱う。
- QNAP↔PC間は認証/暗号化されたAPI経由でデータ交換し、PatentBuddyの高度なLLM/GPU処理はControlDeckのHost権限とジョブ契約に従う。
- PR #10/#11/#13/#14/#15の未マージコードを、mainの実装済み機能と混同しない。次のCodex作業では必ずmainとPR diffを直接読む。
- 旧`qnaplibrary` import、QPKG ID `QnapLibrary`、port 17871、既存データ、Passkey RP ID、管理認証は移行完了まで維持。

## 絶対ルール

1. 標準ライブラリのみ。新しい外部依存を足さない（任意加速は import 失敗時に無効化）。
2. `shell=True` 禁止、任意コマンド実行 API 禁止、root 前提禁止。
3. 秘密値をログ・デバッグバンドル・GET 応答に出さない。
4. すべての API で認証（セッション/デバイストークン）と CSRF/Origin を確認。公開してよいのは `/api/health` とログイン系のみ。
5. ディスク書き込みを増やす変更は理由を PR に書く（`DEVELOPMENT_WORKFLOW.md` §4）。
6. 外部データ取得は公式 API/RSS のみ。規約違反のスクレイピングをしない。
7. 作業の区切りで `docs/HANDOFF.md` を更新して push（トークン切れ対策）。

## コード地図

| パス | 役割 |
|---|---|
| `qnaplibrary/server.py` | HTTP サーバー、ルーティング、静的配信（gzip/ETag） |
| `qnaplibrary/api.py` | REST API ハンドラ群 |
| `qnaplibrary/store.py` | SQLite（設定・コレクション・文書・チャンク・FTS・ベクトル） |
| `qnaplibrary/textproc.py` | 正規化、日本語 2-gram、チャンク分割 |
| `qnaplibrary/vectors.py` | RAM 常駐ベクトル索引（numpy 任意） |
| `qnaplibrary/auth.py` | 管理者パスワード、セッション、LAN ペアリング/デバイストークン |
| `qnaplibrary/webauthn.py` | パスキー検証（QnapDownloader から移植） |
| `qnaplibrary/llm.py` | QnapAssistant / OpenRouter / OpenAI 互換のチャット・埋め込み |
| `qnaplibrary/patents.py` | 特許案件ワークフロー、請求項分解、期限計算、AI プロンプト |
| `qnaplibrary/connectors.py` | 外部データ源（GDELT、RSS、EPO OPS、JPO API、USPTO ODP） |
| `qnaplibrary/mcp.py` | MCP（JSON-RPC over HTTP）ツール |
| `qnaplibrary/debuglog.py` | RAM リングバッファ、デバッグバンドル |
| `qnaplibrary/updater.py` | GitHub Release 自動更新 |
| `qnaplibrary/web/` | 管理 Web（素の JS） |
| `qpkg/`、`packaging/linux/` | QPKG と Linux パッケージ |
