# K7a OSS特許バルク取得調査と取り込み計画（2026-11-18）

ユーザー方針：GitHubの特許一括収集・分析ツールを積極的に参考にする。出典・ライセンス・現行API・安全性を確認し、容量制限付きの機能として順次実装。ControlDeckランタイムの実行能力、自動実行、raw-source配信は追加しない。

## 調査済みの主要リポジトリ

| リポジトリ | ライセンスと現状 | 参考にする部分 | 注意事項 |
|---|---|---|---|
| https://github.com/patent-dev/bulk-file-loader | MIT。2026年11月も更新あり | EPO BDDS、USPTO ODP、DPMAの製品一覧、差分ファイル、キュー、再試行、SHA256、低頻度の進捗記録 | 自動スケジュール・常駐worker・webhookは移植しない。NASのディスク書込を増やさない |
| https://github.com/DunlapCoddingPC/pyUSPTO | MIT。Python>=3.11 | USPTO公式 bulk product APIとX-API-KEY、ファイル名/サイズ/期間のモデル、Office Action等 | QNAPコアにrequests/高バージョンPython依存を強制せず、標準ライブラリで必要なAPIを限定実装 |
| https://github.com/ip-tools/python-epo-ops-client | Apache-2.0。継続更新 | OAuth2、EPO rate limiting、X-OPS-Range含むキャッシュキー、429制御 | 依存丸ごと導入を避ける |
| https://github.com/patent-dev/uspto-odp | Go、現行ODP API client | バルクファイルとODP本文・審査データAPIのスキーマ検証 | Go常駐サービスを加えない |
| https://github.com/google/patents-public-data | Apache-2.0、リポジトリはarchived | BigQueryでIPC/CPC・国・年・必要列を先に絞る。大規模分析 | Google Cloudの課金/外向き通信/転送額は事前dry-run、追加費用の無承認実行は禁止 |
| https://github.com/junhe-S/Google-Public-Patent-Downloader | 公開実装、ライセンス未確認 | Parquet分割転送、DuckDBによる選択的索引、途中再開の発想 | コードの転用をしない。世界特許を全件取り込む方式は使わない |
| https://github.com/parkerhancock/patent_client | 2026年4月archived | 多ソース統一APIの設計 | 新規依存にはしない |
| https://github.com/lens-org/PatentPublicData | 実質古いbulk対応、ライセンス不明確 | 1文献ずつ読み取り、正規化、対象IPCだけ取り込む | 古い配布先URLや未検証パーサーを採用しない |

MIT/Apacheのコードを将来複製する場合はLICENSE/NOTICEを同梱。データ再配布条件はコードのライセンスと別問題。現段階は参照実装の仕様を確認して独自コードを書いており、外部OSSファイルをコピーしたものではない。

## このPRに追加した機能

- qnaplibrary/patent_bulk_catalog.py: 現行USPTO ODP公式 GET https://api.uspto.gov/api/v1/datasets/products/{ID} を固定3製品ID（PTGRXML, PTFWPRD, PTFWPRE）・手動確認に限定して呼び、productFileBag.fileDataBagのファイル名/byte数/期間/配布日を表示する。X-API-KEYは既存の管理者設定から取得してHTTPヘッダ送付のみ。キー/URLをレスポンスに含めない。
- GET /api/v1/uspto-bulk/options は認証済みreadでローカル選択肢を返す。POST /api/v1/uspto-bulk/preview はadmin専用・明示確認・source_fetch_lock共有。要求は製品IDと最大10件/任意の366日以内に限定。2MiB超のレスポンスや不正ファイル名、異常byte数、製品ID不一致を拒否する。
- 管理Webへファイル一覧・サイズ・512MiB参考上限のプレビューを表示するパネルを追加。USPTOキーは設置時入力。ControlDeck Host側の接続・ファイル取得・実行capabilityは拡張しない。source_probesに1件だけのmetadata接続確認追加。
- 2026-11-18後続実装: 公式一覧のファイルを管理者が選んで明示承認した場合だけ、1ファイル512MiB以下・専用領域総量2GiB以下のZIPを非公開領域にダウンロード可能。途中停止とETag/HTTP206再開、SHA-256記録にも対応。**ZIP内部の抽出・文献DBへの取込・自動ダウンロードはまだしない**。ODP実キーでの本番取得は環境導入後に検証する。詳細: [手動ZIP取得の設計とテスト](patent-bulk-manual-staging-k7a.md)。

## 現在のテスト実績

- GitHub一時Actions Run https://github.com/souten-yd/PatentBuddy/actions/runs/44236606303 : tests.test_patent_bulk_catalog + tests.test_source_connectivity、計13件、失敗0。Python compileall、管理画面JS、ControlDeck JSの構文PASS。
- 一時workflowは検証後削除し、リポジトリ既存のrelease.yml以外を残さない。
- 本体APIの後続小修正（ODP不正JSONを502へ正規化）は全体回帰未再実行。実USPTO取得はキー登録後に要検証。
- WIPO Hセクション実データ取得・SQLite保存・H02M照合とOpenAlexの匿名1件成功/429実測は source-smoke-evidence-2026-11-18.md を参照。

## 段階的な大量データ取得：最初の2工程は実装済み、ZIP選別解析は次工程

1. **限定実装済み**：管理者が公式ファイル一覧から選択した1ファイルだけ手動取得。ファイル上限512MiB、専用領域総量2GiB、並列1、256MiBの空き容量余裕。Linux PCで実行推奨（現状はサーバーのdata_dir配下に保存され、QNAPで実行すればNASディスクに書かれるため注意）。多数ファイル一括選択は未実装。
2. **限定実装済み**：強いETagとHTTP206/Rangeの厳密照合、.partと計算したSHA256、原子的renameによる手動再開・管理者停止。公式配布元のSHA256との一致比較は未実装。無条件のリダイレクトは禁止しているため、ODPが外部CDNへの302を必須とする場合は本番キー検証後に安全な送付先allowlistが必要。自動再開・スケジューリングなし。
3. ZIP/JSON/XMLを文献単位でstreaming解析し、ZipSlip・symlink・展開爆弾・CPU/メモリ制限を検証。IPC/CPCと公開国・公開年から候補を絞る。元の巨大ZIPをSQLite BLOBに格納しない。文献ID/公報種別/ファミリーIDによる二重登録回避。全文/図面は必要文献だけ別途処理。
4. EPO BDDSとDPMA Connect Plusはアカウント・規約確認後、USPTO ODPと同様の選択可能なmanifestへ。Google BigQuery/Parquet/DuckDBは料金dry-runと明示ユーザー承認を必須にして別計画で。
5. backend authoritative、ui.html default、Vue read-only/not default、runtime level_0_manual_only、no execution、no raw serving/fallback/redirect、no startup npm build、ローカルAI機密限定を維持。PR #39など依存変更も含むmainコードのレビューと実機統合テストが完了するまでmerge/releaseしない。


**最新のK7a検証**: [手動ダウンロードとCodex向け実装条件](patent-bulk-manual-staging-k7a.md)。一時Actions https://github.com/souten-yd/PatentBuddy/actions/runs/44240112831 にて対象22件と全339件（skip3）・Linuxビルド・隔離PDF図面テストが合格。総容量/プロセスlock/起動時無書込みの追加テストも別CIで合格済み。実キーを使ったODP本番ファイルは未取得。実ユーザーZIPの解析やDB取り込みは次工程。
