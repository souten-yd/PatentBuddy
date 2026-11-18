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
- デフォルトでは「バルクZIPをダウンロードしない」「DBへ文献を保存しない」。この機能は**カタログの下見でありバルクファイル取得機能ではない**。ODP実キーによる接続は未実施で、導入後にテストする。

## 現在のテスト実績

- GitHub一時Actions Run https://github.com/souten-yd/PatentBuddy/actions/runs/44236606303 : tests.test_patent_bulk_catalog + tests.test_source_connectivity、計13件、失敗0。Python compileall、管理画面JS、ControlDeck JSの構文PASS。
- 一時workflowは検証後削除し、リポジトリ既存のrelease.yml以外を残さない。
- 本体APIの後続小修正（ODP不正JSONを502へ正規化）は全体回帰未再実行。実USPTO取得はキー登録後に要検証。
- WIPO Hセクション実データ取得・SQLite保存・H02M照合とOpenAlexの匿名1件成功/429実測は source-smoke-evidence-2026-11-18.md を参照。

## 次の段階：安全な大容量取得・ファイル単位差分

1. 実装先はLinux ControlDeck PCを優先し、QNAPは書込を最小化した正規化DB/メタデータ保管に集中。公式ファイル一覧のうちユーザーが選んだファイルだけ手動取得。初期値は並列1、1ファイル512MiB以下、1回2GiB・5ファイルまで。実バイト数・空き容量・取得元条件を事前確認し、上限はソフトではなく実バイトに強制する。
2. Range/If-Range/ETag/HTTP206の厳密検証、.part一時ファイル、SHA256、原子的renameにより安全に中断・明示再開。もしサーバが206を返さない場合は追記しない。取得元の署名付きURLを無条件に信頼せず、公式配布経路だけを許可する。ハッシュ不一致は保存完了にしない。自動再開やスケジューリングはしない。
3. ZIP/JSON/XMLを文献単位でstreaming解析し、ZipSlip・symlink・展開爆弾・CPU/メモリ制限を検証。IPC/CPCと公開国・公開年から候補を絞る。元の巨大ZIPをSQLite BLOBに格納しない。文献ID/公報種別/ファミリーIDによる二重登録回避。全文/図面は必要文献だけ別途処理。
4. EPO BDDSとDPMA Connect Plusはアカウント・規約確認後、USPTO ODPと同様の選択可能なmanifestへ。Google BigQuery/Parquet/DuckDBは料金dry-runと明示ユーザー承認を必須にして別計画で。
5. backend authoritative、ui.html default、Vue read-only/not default、runtime level_0_manual_only、no execution、no raw serving/fallback/redirect、no startup npm build、ローカルAI機密限定を維持。PR #39など依存変更も含むmainコードのレビューと実機統合テストが完了するまでmerge/releaseしない。
