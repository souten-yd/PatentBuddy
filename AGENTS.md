# AGENTS.md — AI エージェント／開発者向けガイド

## 最初に読む順番

1. 本ファイル（概要と絶対ルール）
2. `DEVELOPMENT_WORKFLOW.md`（PR・CI・リリース・文書ルール）
3. `docs/HANDOFF.md`（**現在地と次の一手**。引き継ぎ時はここから再開）
4. 必要に応じて `docs/architecture.md`、`docs/patent-workflow.md`、`docs/feasibility.md`

## プロジェクト概要

QnapLibrary は QNAP NAS（主対象 TS-253Be / x86_64 / QTS 5.x）と一般 Linux で動く「戦略的データベース基盤」。
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
