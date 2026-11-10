# ResearchDataHub / PatentBuddy — 名前・配置・責務の決定

状態: 2026-11-10 合意方針。Linux PCで開発・検証し、検証完了後にデータ正本をQNAPへ移す。現在のQPKG・データは変更・削除しない。

## 製品名

- **ResearchDataHub**: 特許公報・規格（JIS/ISO/IECなど、利用許諾を守る）・論文・技術資料・公的制度・構造化データなどを保管し、出典と改版・検索・収集・認証付きREST/MCP APIを提供する**汎用研究データサーバー**。
- **PatentBuddy**: ResearchDataHubを利用するControlDeck Add-on v2。発明・請求項・先行技術調査・GraphRAG・ローカルLLMなど、特許専門の高機能UI/分析を提供。
- 将来の規格調査などは独立アドオンでもResearchDataHubの同じ文献/権限/検索APIを再利用する。サーバーへ特許専用ロジックを無制限に追加しない。

## 開発/運用トポロジー

| フェーズ | ResearchDataHub 実行・正本DB | PatentBuddy 実行 | 補助索引 |
|---|---|---|---|
| 開発・負荷/回帰試験 | **ControlDeck PC上のLinux**、PCローカルSSD。テスト用/本番用のデータディレクトリを分離 | 同PCのControlDeck独立Add-on | SSD上で再生成可能 |
| 結合試験 | PC側の両サービスをTLSプロキシ経由の認証付きHTTPで接続。機密情報はローカルLLMのみ | 同PCのControlDeck | NAS直接のSQLiteアクセスは禁止 |
| 完成後の移行 | **QNAP NASのローカルストレージ**へスナップショットと設定を検証・移行。NAS上のResearchDataHubが唯一の正本 | 引き続きPC | PC索引はNAS正本から再生成 |

- 2台で同じSQLiteを同時に書き込まない。停止/SQLite Online Backup APIで一貫スナップショットを作り、SHA-256・quick_check・文献件数・データschema・設定/シークレットとパスキー・原本の移行チェックをしてからNASを有効化する。移行失敗時はPC側を維持。
- 規格原本は著作権・契約による再配布可否を確認。公開API用のデータと機密データはサービス側で別権限とし、未公開の発明/請求項は**ローカルLLMだけに入力可能**。PC⇔NAS間の認証済み転送は制限対象ではない。OpenRouter等の外部LLMは許可された公開資料だけを入力対象とする。
- 遅い処理（OCR/埋め込み/GraphRAG/大規模RAG）はControlDeck PCへ寄せ、サーバーはデータ保存/収集/検索APIを保持する。確定した引用・特許family・文献改版などの関係データはResearchDataHubが保存する。
- 既存 `qnaplibrary` Pythonパッケージ、`QPKG_NAME=QnapLibrary`、データディレクトリ `QnapLibrary-data`、port 17871 は互換性のため維持。表示ブランド・Linux入口だけを段階的に移す。名称の変更で既存データ・パスキーを初期化しない。

## 本PRの実装境界

1. Linux PCから `python3 -m researchdatahub` と `./rdh.sh doctor|serve|test` で利用できる入口を追加。起動処理は既存 `qnaplibrary.server.main` を再利用し、二重DB/二重実装を作らない。
2. Server/UI/health/QPKG表示名を `ResearchDataHub` に変更。旧内部識別子・QNAP配布ファイル名・ポート・DB schema・データパス・既存REST意味論は変えない。
3. Linux tar.gz配布に新しい入口を同梱。既存 `qnaplibrary` ランチャーとsystemdサービスは互換維持。
4. 認証・機密防壁・収集・検索エンジン・スケジューラの機能挙動は変更しない。データ共有のためSMB/NFS上の稼働SQLiteを使わない。
5. テストにブランド/入口/データ独立性/配布同梱/実行権限を追加。フルverifyとLinux/QPKG build、ControlDeck PC実機受入が通るまでPRはDraftにする。

## 次の段階

- **S1**: まずPCにResearchDataHubとPatentBuddy A0を並列導入。A0はまだ準備画面だけで、認証・本格UIは未実装。
- **S2**: ControlDeck Host principal認証+ResearchDataHub scoped API（private業務APIとpublished-only外部AI API）を接続。公開資料の手動承認はPR #15のレビュー対象。
- **S3**: 大量検索・バッチ登録・文献出典/規格検索フィールドを追加。PR #13の拡張を検証・統合し、実測性能に基づき最適化。
- **S4**: ControlDeckのローカルLLMとJobsを使うGraphRAG/請求項/引用・規格リンク。外部LLMには未公開の発明・請求項を入力しない。
- **S5**: PC → QNAPのdry-run移行、整合性検証・切替・復元・トークン/パスキー再確認。その後にだけQNAPへ本番移設。
