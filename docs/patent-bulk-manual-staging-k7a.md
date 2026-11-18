# K7a — USPTO ODP バルクZIPの手動・容量限定ダウンロード（2026-11-18）

## 現在の実装

パターンは「公式ファイル一覧で対象と容量を確認 → **管理者が明示承認** → 1ファイルだけ取得 → 進捗を確認／停止／手動再開」。自動巡回や外部検索の一括実行ではない。

- 一覧: `POST /api/v1/uspto-bulk/preview` (admin), 認証済みの固定USPTO公式ODP API で製品ファイル名・公開日/期間・期待バイト数を検証。対応製品は PTGRXML/PTFWPRD/PTFWPRE の3種類のみ。
- 保存開始: `POST /api/v1/uspto-bulk/transfer/start` (admin), `product,file_name,expected_bytes,confirmed` を必須、`restart,date_from,date_to` を任意指定。本人が承認した範囲のみ受付。**開始時に公式一覧を再取得**してファイル名とサイズが一致することを確認。利用者が入力したURLや任意保存パスを一切受け付けない。
- 保存状態: `GET /api/v1/uspto-bulk/transfer/status` (read), `POST /api/v1/uspto-bulk/transfer/cancel` (admin)。ControlDeck Hostに管理者の取得・取消権限は追加しない。現在の転送状態はメモリ、途中のメタデータはディスク上の専用場所へ保持。
- 保管先: サーバー `data_dir/bulk_staging/{PTGRXML|PTFWPRD|PTFWPRE}/` 下。ファイル名の文字種/長さを検証し、外部公開するHTTPルートはなし。root/途中ファイルのsymlinkを拒否し、0o700ディレクトリ/0o600ファイル。QNAPで起動した場合はNASデータ領域に保存されるので**本機能はLinux PCで実行することを推奨**。PCからNASへ必要な文献のみ後で登録する。
- 制限: ファイル当たり最大512MiB、専用領域全体最大2GiB、空き容量に256MiB追加の余裕、1転送だけ、最大15分、最大2000個の管理対象ファイル走査。別プロセス間もflockで同時書込み防止。総容量は実保存ファイル数に基づくバックエンドのhard preflight。管理者UIは上限超過を選択不可として表示。現行の文献DB全経路に対するsoft budgetはhard limitに昇格したわけでは**ない**。
- 転送安全性: HTTPS固定URL、`X-API-KEY`をHTTPヘッダーにのみ設定、TLS検証はstdlibデフォルト。未許可のリダイレクトを拒否。新規は200+一致するContent-Lengthのみ、再開は強いETagと`If-Range`+`Range`、正確なHTTP206/Content-Range/Content-Length、同じETagの時だけ追記する。リダイレクトやHTTP200へのダウングレード時は追記せず失敗。gzip transfer encodingを禁止。先頭ZIPシグネチャと計画ファイル長を検査。128KiB刻みで読みながらSHA-256計算。受信完了時のみ原子的に .part から .zip に変更しSHA-256をreceiptへ記録。
- 停止・再開: ユーザー操作時のみ停止イベントを設定し、途中ファイルは保持。次回の明示操作時に公式一覧を再取得してサイズが同じか検証、ETag/Rangeが有効なら続きを取得。危険な途中ファイル、転送元ETag変更時は**明示した最初からの再取得のみ**。サーバー起動時に自動再開しない。進捗取得は軽量、メタデータにAPIキー/URLを保存しない。
- 未実装: 完成ZIPの読み出し・配信API、ZIP内部展開、CSV/XML/JSON一文献単位の解析、IPC/CPC/国/年による収集対象の絞り込み、家族/引用のDB更新、元ファイル検証用の提供元SHA256照合。SHA-256自体は自前の転送完了記録であり**公式提供元の署名・ハッシュと一致確認したものではない**。リリース段階の物理QNAP/iPhone/ControlDeck、登録済みUSPTO本番キーでのZIP実取得は未テスト。

## 新APIの管理権限とI/O

| Action | Route | Auth | Disk effect |
|---|---|---|---|
| オフライン製品選択肢 | GET /api/v1/uspto-bulk/options | read | なし |
| 実際のファイル一覧 | POST /api/v1/uspto-bulk/preview | admin | なし |
| ZIP1件の手動取得 | POST /api/v1/uspto-bulk/transfer/start | admin | backend専用データ領域への明示保存 |
| 進捗表示 | GET /api/v1/uspto-bulk/transfer/status | read | なし |
| 手動停止 | POST /api/v1/uspto-bulk/transfer/cancel | admin | 既に保存済みの部分ファイルは維持 |
| 出力ZIPを外部配信 | なし | ― | **禁止・未実装** |

## テストと実用化ゲート

- `tests/test_patent_bulk_transfer.py`: ZIP固定公式URL・サイズ・SHA256・既存receipt冪等・HTTP200/206/ETag/Range照合・切断・停止・不正ZIP・HTTPリダイレクト拒否・シンボリックリンク・空き容量/総2GiB制限・flock重複防止・管理者権限/認証・新規start時の公式一覧再確認。
- `tests/test_patent_bulk_catalog.py`: 対象製品/メタデータ照合・keyのHTTPヘッダー・URL漏洩なし・権限境界。
- GitHub CI（テスト用workflowは正式releases-only規則に従い実行後削除）でターゲット22件/失敗0、`bash scripts/verify-k6.sh`: 全体339件/失敗0/3 skip、構文・安全grep・バージョントリプル・Linux artifact作成PASS。任意PyMuPDFを導入した隔離図面抽出もPASS。証跡: https://github.com/souten-yd/PatentBuddy/actions/runs/44240112831
- 追加した総2GiB・flock・起動時I/Oゼロの3テストは後続CIで確認する（最終結果に合わせ更新する）。
- **実USPTO ZIPのライブ取得はまだ行っていない**。導入時 `設定 → 外部キー` に`uspto_api_key`を登録後、対象が512MiB以下の公開ZIPで1ファイルを選び、取得開始/停止/再開/最終SHA256/スペース消費を検査すること。公式APIがファイルダウンロードで302などのリダイレクトを必要とする場合、勝手に追従しない。正式配布元の転送先ホスト・署名付きURL契約を確認し、allowlist/credential leakage/retryの別レビューが必要。
- `main`のデフォルトui.html/manifest/Vue read-only、ControlDeck Host、runtime level_0_manual_only、backend authoritative、no execution/no raw source serving/no fallback/no redirect/no startup npm buildを改変しない。Draft依存PR #39以下もレビュー前のマージは禁止。

## 次のCodex実装指示：安全なZIP選別解析

1. **再現可能なサンプル**: 公開されている公式USPTO ZIP・JSON/XMLの最小資料を取得し、実schema/文字コード/公報種別/日付/IPC/CPCフィールドを実測で固定fixtureに落とす。入力は1ファイル、サイズ・開いたエントリ数・総展開量をhard capにする。外部zipfile内部の symlink、zip slip、圧縮率が異常なZIP、DOCTYPE/XML ENTITY、壊れた中央ディレクトリを拒否。
2. **1件ずつの抽出**: ZIP全展開禁止、memory limit・ストリーム解析・XML iterparseで要素を早期クリアし、大量ファイルをRAMに丸読みしない。IPC/CPC・公開国・公開年でフィルターして必要な公開書誌だけをデータベースへ送る。発行番号+kind+国とファミリー・引用を重複識別に使用する。元ZIP保管/削除はユーザーに選択させ、NASへの書き込みを最小化する。
3. **ステージング移行**: 今回はPatentServerのdata_dir配下へ保存する。PC用Linux導入で本当に容量がある専用データ領域に構成できるようにする場合は、設定画面で**許可された設定済み保存ルートのみ**を選択し、任意の絶対パスや外部URLを入力させない。保存先をホストのファイルシステムへ公開するコマンド/APIを作らない。
4. **公式キー実接続テスト**: WIPO HとOpenAlexの少量実取得実績を維持、USPTO/ EPO / JPO の実キーは環境導入時に登録。公式zipの短いファイルで200/206/ETag/Content-Length/Range/302の振舞いを確認し、許可されたリダイレクト先が存在するならTLS証明書・ホスト・署名・秘密鍵送信範囲を追加検証。自動巡回、Range偽装、規約違反のダウンロードは禁止。
5. **ユーザー確認/PRレビュー**: リリース前の `bash scripts/verify-k6.sh`, `WITH_QPKG=1` は可能な範囲、実ControlDeck/Linux/QNAP/iPhone受入、main/docs/manifest/tests/runtimeセマンティクス検証、依存PR確認。少修正は次PRに含め、不要な追加PRを増やさない。
