# K7a — 分野限定収集・容量表示・PDF図面（2026-11-18）

状態: **Draft / 未マージ / 未リリース**。base: Draft PR #39 (K6c Atlas)。本PRは最初の機能スライスであり、全機能が完成したとは扱わない。

## 今回の実装

- Private-first分類プレビュー: インバータ、電気、機械、モータ等から初期候補のIPCサブクラス（H02M/H02P/B60L/H02J/H01F/H01H/F16H/F16C/F16D/F04D）を返す。分類は候補であり正式辞書との照合前。未対応語は空結果。プレビューでは外部送信/保存をしない。API: POST /api/v1/source-plan (read) と Host Bridge POST /addon/v1/source-plan。
- 取得: 管理者のみ POST /api/v1/source-acquisitions。IPC固定候補、明示 public_only_confirmed=true、1回上限25件、公式EPO OPSの既存コネクタから限定書誌を取得し既存SQLiteに追加。任意の検索語/Cloud AI/定期自動取得/複数アカウントで上限回避はしない。Host Bridge のread権限から管理者の収集操作は不許可。
- 容量: GET /api/v1/source-storage (read) と GET /addon/v1/source-storage (Host read)でSQLite/WAL/SHM各ファイルバイト・ディスク空き・任意の文献/原本PDF/画像件数を表示。図書全件の本文を読む処理はしない。PUT /api/v1/source-storage/policy (admin)で soft_limit_mib（初期5120）、max_results_per_fetch（初期25）、max_figures_per_pdf（初期12）、定期収集不可を保存。保存容量はソフト上限であり、全既存インポートのハードquotaではない。計測対象はSQLite物理ファイルで、論理文献サイズ別内訳ではない。
- ControlDeckの「資料」画面に技術テーマ入力、IPC候補、読み取り専用の容量手動更新を追加。取得の管理者操作は現状ResearchDataHub側APIのみ。UIでの管理者収集導線・進捗は次工程。
- PDF図面: 既存の埋込ラスター抽出に加え、Linux PC上に任意のローカルPyMuPDFがある場合、先頭12ページで埋込画像/大きなベクターパスの領域候補を最大60件検出し、最大12候補を120dpi PNGでcrop。既存画像合計32MiB/200件、1画像2MiB上限とSHA-256重複抑止を維持。原文PDFを正本として、ページ、PDF point座標、未確認、抽出方式を保持。図番号/技術内容はまだ確認済みとして扱わない。任意依存がない時は既存PDF抽出経路を継続する。
- グラフ/表の数値解析: 現段階は未実装。ローカルAIが軸/単位/目盛り/線の関係を検証できた場合だけ値を抽出し、曖昧ならスキップ。原図は維持、値を捏造しない。

## 実施済みと未実施

GitHubの実JS全文を V8 構文検査しPASS、HTMLのID重複0。独立PyMuPDFの合成ベクターPDFで矩形候補の抽出/PNG crop/不正座標の拒否PASS。初期分類語の独立照合PASS。これらは正規リポジトリのPython/HTTP統合テストではない。

未実施: 新規 tests/test_source_planner_storage_figures.py、実LiveServer、PDF import全経路、EPO実接続・API料金/無料枠、ControlDeck/iPhone/QNAP実機、全 scripts/verify-k6.sh。環境からGitHubの正規checkoutができないためこれらをPASSと記載しない。

## 次のCodex指示（重要）

1. このPRの全コードを正規checkoutし、新規Python unittest、PDF extract/store/image、auth/HTTP/Host bridge、scripts/verify-k6.sh と WITH_QPKG=1 を実行。失敗修正は原則このPRへまとめる。任意PyMuPDF有/無、キャンセル、異常PDF、大量線画、メモリ・CPU・I/O上限、バックアップ/削除/重複保存・ソフト上限を実査。
2. IPC/CPC/FI/Fタームの公式辞書を適法に入手し版管理。既存 /api/v1/classify の分類索引と連動し、公開検索語・国・優先日/公開日・件数上限をユーザーが確認してから収集開始。広い「電気」「機械」は追加絞り込みが必要。公式EPO OPSを実接続で検証し、JPO/USPTOの実験的コネクタと、JPOバルク/PATSTAT TIP/Google BigQuery/OpenAlexの契約可否・ライセンスを個別確認し追加実装。料金は無料優先で無断支払いをしない。
3. 各ソースの取得進捗・件数・最終更新・再試行・失敗・原本ライセンス/保管期限・容量を表示。静的容量ソフト上限を全書込経路に効く「ハード」上限と混同しない。SQLite/WAL/FTS/PDF/画像を含む差分容量計測と同時書込・ロールバックを設計してからハードquotaを導入。削除は原本や承認知識の参照整合性を確認しユーザー明示操作のみ許可。
4. 図面候補はFIG/図ラベル位置と描画領域の対応検証とユーザーレビューを実装。Local-only ControlDeck Vision AI jobで図番号・説明・構成要素・グラフ/表数値の候補を生成し、source hash/page/bbox/units/model/provenanceを持たせる。原文と不一致なら保存しない。図面画像を外部LLMへ出さない。今回の bbox は暫定で実特許の多図面ページについて未検証。
5. PR #29～#39 と main 実ファイル、docs/manifest/tests/runtime を照合。ui.html default、Vue read-only/non-default、backend authoritative、level_0_manual_only、no execution、外部への機密漏れ、raw source serving/fallback/redirect、server起動時npm buildを加えない。テスト失敗が残る限りDraft維持。依存順でのみmerge・マイルストーンで正式release。

## Expected Final State（今回）

ResearchDataHubのIPC少量取得(明示管理者操作)＋ControlDeckの分野プレビュー/容量閲覧＋既存PDFインポート時の位置根拠付き圧縮PNG候補。多数データソースの一括自動収集、UI収集管理、図表値抽出・ローカルAI Vision、完全ハードquotaは**次工程**。

## リリース前の追加安全ゲート

任意ライブラリPyMuPDFのAGPL/商用ライセンス適合性と、外部由来PDFを解析する際のCPU/メモリ制限・ワーカー隔離を確認する。今回の図面領域抽出はPDFジョブのプロセス内から任意ライブラリを呼ぶ暫定実装なので、無条件の本番リリースを認めない。必ずサンドボックス/別プロセスでの上限強制、異常/破損PDFでのハング・メモリ使用、実特許の多数図・回転・複数列をテストし、合格しなければ図面cropを既定無効にするか既存Popplerの安全な限定実装へ切り替える。設定 max_figures_per_pdf は0〜12で、PDF workerがResearchDataHubの設定を読んで適用する（旧サーバ404のみ互換デフォルト12）。
