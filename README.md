# ResearchDataHub

QNAP NAS と Linux で動く**研究資料の保存・収集・検索APIサーバー**です。特許創出・先行技術調査・請求項・権利化の支援機能を備えています。公報・規格・公開審査基準を根拠に、日本語全文検索や任意のベクトル検索を利用できます。未公開発明は、管理者が確認したローカル専用LLMから出さない設計です。
別の PC や AI アシスタントは API / MCP からデータの取り込み・検索ができます。

## 主な機能

- **特許支援**: 発明記録から登録までの 11 段階の案件管理、期限（目安）の自動計算、請求項の版管理と構成要件分解、クレームチャート、
  AI 支援（ヒアリング、派生発明、検索式設計、新規性・進歩性評価、請求項ドラフト、拒絶理由対応、侵害・FTO）
- **検索**: SQLite FTS5 による日本語検索（2-gram、AND/OR/除外/フレーズ）＋任意のベクトル検索をハイブリッド（RRF）
- **データ管理**: コレクションの作成、NDJSON/JSON/CSV/テキスト取り込み、エクスポート、外部埋め込みの格納
- **AI チャット**: 機密の案件・文書・検索結果は検証済みローカルLLMのみ。OpenRouter等の外部AIには、固定の公開制度ガイドや接続試験以外は送信しません。
- **収集**: GDELT（公開世界ニュース）、RSS、EPO OPS、JPO 特許情報取得API、USPTO Open Data Portal。外部へ検索式を送る場合は公開情報のみと明示確認。
- **接続**: LAN で事前パスコードによるペアリング → 以後トークンで無制限に利用。MCP（`/mcp`）対応
- **ログイン**: パスワード、パスキー（Face ID / Windows Hello などの顔認証。HTTPS 接続時）
- **公開資料API**: 管理者がタイトル・公開番号・抜粋を確認して承認した資料だけを専用トークンで検索・取得。原文更新で承認を停止します。自動クラウド送信はありません。詳しくは [公開資料API](docs/public-catalog.md)。
- **AI 向けデバッグ出力**: 状態・直近エラー・検索トレースを JSON で取得（秘密は除去）
- **自動更新**: [ResearchDataHub Releases](https://github.com/souten-yd/PatentBuddy/releases) から SHA-256 を検証して更新
- **バックアップ**: 管理 Web からSQLiteの一貫したスナップショットを手動作成（設定・秘密情報は別途保全が必要）
- **iPhoneホーム画面**: Safariの「ホーム画面に追加」で専用アイコンから起動。ホームは主要件数をコンパクト表示し、ベクトル化・調査・更新の処理状況を確認できます
- **機密保護**: 既定でクラウドLLM送信不可。手動承認の公開検索語だけ公的APIへ送信。通知は本文や案件名なし。詳しくは [機密境界](docs/privacy-boundary.md) / [開発計画](docs/patent-feature-plan.md)
- **低負荷**: 標準ライブラリのみ、ディスク書き込み最小、ログはメモリのみ

## 必要環境

- QNAP: x86_64、QTS 5.0 以降、App Center の **Python3**（3.9 以上）
- Linux: Python 3.9 以上（sqlite3 / FTS5 付き）、systemd 推奨

## インストール

### QNAP
1. [Releases](https://github.com/souten-yd/PatentBuddy/releases) から `QnapLibrary_<版>_x86_64.qpkg` を取得。旧版で更新URLエラーが出る場合は[手動上書き更新の手順](docs/upgrade.md)に従ってください。
2. App Center → 手動インストール で選択
3. `http://<NAS>:17871/` を開き、管理者パスワードを設定（LAN から）

データは従来通り QPKG の隣の `QnapLibrary-data` フォルダに保存され、更新しても残ります。**表示名は QnapPatentBuddy ですが、既存のQPKG識別子・配布ファイル名・ポートは互換性のためQnapLibraryのままです。**

### Linux
```bash
tar xzf qnaplibrary-<版>-linux.tar.gz && cd qnaplibrary-<版>
./install.sh                # 自分のユーザーで systemd --user サービスとして導入
# sudo ./install.sh --system  # /opt に導入し専用ユーザーで実行
```

## 初期設定

1. 管理者パスワードを設定
2. 特許案件や未公開文書をAIに処理させる場合は、NAS内のローカル推論機を準備し、「AIプロバイダ」で「ローカル専用確認済み」をチェックしてください。QnapAssistantがクラウド中継していないことも確認が必要です。
3. OpenRouterのキーは公開制度の一般ガイドなど公開用途にのみ使えます。登録しても発明本文の自動ベクトル化や機密チャットには使いません。

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

- 「想定外のダウンロードURLです」: [旧版からの更新手順](docs/upgrade.md)を参照。

- 起動しない（QNAP）: App Center で Python3 が有効か確認。`QNAPLIBRARY_LOG_MODE=disk` で起動するとデータフォルダにログが出ます
- 不具合の報告: 設定 > デバッグ からバンドルをダウンロードして AI や開発者に渡してください

## 開発

[AGENTS.md](AGENTS.md)、[DEVELOPMENT_WORKFLOW.md](DEVELOPMENT_WORKFLOW.md)、[docs/HANDOFF.md](docs/HANDOFF.md) を参照。

## ドキュメント

- [アーキテクチャ](docs/architecture.md) / [API と接続](docs/api.md) / [特許支援の設計](docs/patent-workflow.md)
- [RAG 向け DB ランキング](docs/rag-db-ranking.md) / [実現性評価](docs/feasibility.md) / [提案](docs/proposals.md) / [ロードマップ](docs/roadmap.md)


## Linux の ResearchDataHub 入口

既存の `qnaplibrary` サーバーと同じ実装・データ形式を使います。
新入口では保存先を明示してください（`QNAPLIBRARY_DATA` 環境変数も利用可能）。
旧入口のデフォルト保存先、サービス名、Cookie、パスキーRP ID、QPKG IDは維持します。
同じ保存先で新旧サーバーを同時起動しないでください。

```sh
python3 -m researchdatahub --data /path/to/pc-data --bind 127.0.0.1 --port 17871
./rdh.sh doctor
./rdh.sh serve --data /path/to/pc-data --bind 127.0.0.1
./rdh.sh test
```

`doctor` はメモリ上でPython/SQLite/FTS5の可用性のみを確認し、秘密や設定を読みません。
`test` は一時データとloopback上の実サーバーで起動・ログイン・保存先互換を確認する
配布smokeです。全開発検査は `bash scripts/verify.sh` を使用します。
Linux tar.gzに同梱し、インストール後は `<prefix>/current/rdh.sh` から使用できます。
既存の `<prefix>/bin/qnaplibrary-run` とsystemdサービスは引き続き利用できます。

## PatentBuddy（ControlDeckの特許アドオン）

ResearchDataHubは資料の保存・収集・検索サーバーです。別のPatentBuddyアドオンはControlDeckのオプション機能として管理し、サーバーの認証APIへ接続して文献を検索・閲覧します。アドオン内に文献の正本DBは作りません。画面には各サービスの役割・接続先・バージョンを表示します。接続は [アドオン設定](docs/controldeck-addon-plan.md) を参照してください。

同じLinuxユーザーで稼働するPatentBuddyとResearchDataHubは、トークン入力なしで読み取り専用接続を確立します。[ローカル自動認証の条件](docs/local-addon-auth.md)を参照してください。
