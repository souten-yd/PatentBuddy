# QnapLibrary

QNAP NAS と Linux で動く「戦略的データベース基盤」です。特許・規格・ニュース・市場情報などを複数のデータベース（コレクション）に集め、
日本語全文検索とベクトル検索で根拠を探し、AI（同じ NAS の QnapAssistant や OpenRouter）が特許取得までの作業を支援します。
別の PC や AI アシスタントは API / MCP からデータの取り込み・検索ができます。

## 主な機能

- **特許支援**: 発明記録から登録までの 11 段階の案件管理、期限（目安）の自動計算、請求項の版管理と構成要件分解、クレームチャート、
  AI 支援（ヒアリング、派生発明、検索式設計、新規性・進歩性評価、請求項ドラフト、拒絶理由対応、侵害・FTO）
- **検索**: SQLite FTS5 による日本語検索（2-gram、AND/OR/除外/フレーズ）＋任意のベクトル検索をハイブリッド（RRF）
- **データ管理**: コレクションの作成、NDJSON/JSON/CSV/テキスト取り込み、エクスポート、外部埋め込みの格納
- **AI チャット**: ライブラリを根拠にした回答（出典番号付き、ストリーミング）。QnapAssistant / OpenRouter（モデル・フォールバック・プロバイダ順・価格上限・データ収集拒否・ZDR・推論設定など）/ 任意の OpenAI 互換 API
- **収集**: GDELT（世界ニュース）、RSS、EPO OPS、JPO 特許情報取得API、USPTO Open Data Portal
- **接続**: LAN で事前パスコードによるペアリング → 以後トークンで無制限に利用。MCP（`/mcp`）対応
- **ログイン**: パスワード、パスキー（Face ID / Windows Hello などの顔認証。HTTPS 接続時）
- **AI 向けデバッグ出力**: 状態・直近エラー・検索トレースを JSON で取得（秘密は除去）
- **自動更新**: GitHub Releases から SHA-256 を検証して更新
- **バックアップ**: 管理 Web からSQLiteの一貫したスナップショットを手動作成（設定・秘密情報は別途保全が必要）
- **iPhoneホーム画面**: Safariの「ホーム画面に追加」で専用アイコンから起動。ホームは主要件数をコンパクト表示し、ベクトル化・調査・更新の処理状況を確認できます
- **低負荷**: 標準ライブラリのみ、ディスク書き込み最小、ログはメモリのみ

## 必要環境

- QNAP: x86_64、QTS 5.0 以降、App Center の **Python3**（3.9 以上）
- Linux: Python 3.9 以上（sqlite3 / FTS5 付き）、systemd 推奨

## インストール

### QNAP
1. [Releases](https://github.com/souten-yd/QnapLibrary/releases) から `QnapLibrary_<版>_x86_64.qpkg` を取得
2. App Center → 手動インストール で選択
3. `http://<NAS>:17871/` を開き、管理者パスワードを設定（LAN から）

データは QPKG の隣の `QnapLibrary-data` フォルダに保存され、更新しても残ります。

### Linux
```bash
tar xzf qnaplibrary-<版>-linux.tar.gz && cd qnaplibrary-<版>
./install.sh                # 自分のユーザーで systemd --user サービスとして導入
# sudo ./install.sh --system  # /opt に導入し専用ユーザーで実行
```

## 初期設定

1. 管理者パスワードを設定
2. 設定 > 外部キー: OpenRouter の API キーを登録（AI 支援とベクトル化に使用。ベクトル化は既定で OpenRouter、設定 > AI で変更可）
3. 設定 > デバイス接続: ペアリング用パスコードを設定（別PC・AI から利用する場合）
4. データ: コレクションを作成して取り込み、または 収集 から外部データを取得

## HTTPS とパスキー（顔認証）

パスキーはブラウザの仕様で HTTPS が必要です。NAS で次を実行し、`https://<NAS名>.<tailnet名>.ts.net:8443/` で開いてください
（QnapDownloader が使う 443 とは別ポートなので共存できます）。詳しくは [docs/https.md](docs/https.md)。

```sh
tailscale serve --bg --https=8443 http://127.0.0.1:17871
```

## 使い方

- 検索: スペースで AND、`OR`、`-除外`、`"フレーズ"`。コレクションで絞り込み
- 特許: 案件を作成 → 段階ボタンで進行 → 各段階の AI ボタンで支援を実行
- 別PCから: [docs/api.md](docs/api.md)

## データと更新

- 設定 > 更新 で確認・適用（自動適用も選べます）。Linux 版は旧版を残すので `install.sh rollback` で戻せます
- バックアップ対象: データフォルダ（`library.sqlite3*`、`settings.json`、`secrets.json`）。管理 Web「設定 > バックアップ」のスナップショットは SQLite のみ。詳しくは [docs/backup.md](docs/backup.md)

## トラブルシューティング

- 起動しない（QNAP）: App Center で Python3 が有効か確認。`QNAPLIBRARY_LOG_MODE=disk` で起動するとデータフォルダにログが出ます
- 不具合の報告: 設定 > デバッグ からバンドルをダウンロードして AI や開発者に渡してください

## 開発

[AGENTS.md](AGENTS.md)、[DEVELOPMENT_WORKFLOW.md](DEVELOPMENT_WORKFLOW.md)、[docs/HANDOFF.md](docs/HANDOFF.md) を参照。

## ドキュメント

- [アーキテクチャ](docs/architecture.md) / [API と接続](docs/api.md) / [特許支援の設計](docs/patent-workflow.md)
- [RAG 向け DB ランキング](docs/rag-db-ranking.md) / [実現性評価](docs/feasibility.md) / [提案](docs/proposals.md) / [ロードマップ](docs/roadmap.md)
