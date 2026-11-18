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

任意ライブラリPyMuPDFのAGPL/商用ライセンス適合性と、外部由来PDFを解析する際のCPU/メモリ制限・ワーカー隔離を確認する。今回の図面領域抽出はCPU/RAM/ファイルサイズ上限付き別プロセス化まで実装したが、OSサンドボックスによるネットワーク遮断等は未実装であり、無条件の本番リリースを認めない。必ずサンドボックス/別プロセスでの上限強制、異常/破損PDFでのハング・メモリ使用、実特許の多数図・回転・複数列をテストし、合格しなければ図面cropを既定無効にするか既存Popplerの安全な限定実装へ切り替える。設定 max_figures_per_pdf は0〜12で、PDF workerがResearchDataHubの設定を読んで適用する（旧サーバ404のみ互換デフォルト12）。

## 2026-11-18 継続実装・レビュー待ち

- 新規 source_history.py と source_acquisition_runs テーブルに、管理者が明示実行したEPO OPS分類別取得の開始・成功・失敗・IPC・件数・応答バイト数を記録。生の外部エラー・APIキー・未公開検索語は残さない。GET /api/v1/source-acquisitions?limit=20 は認証付きread専用。
- GET /api/v1/source-storage?counts=1&breakdown=1 はDB/WAL/SHMの実ファイルサイズに加え、直近2,000文献に限定した出典別のタイトル・メタデータに限定した論理バイト標本を返す（本文・PDF・画像・索引は読む/含むことをしない）。これは物理的な出典別ディスク占有量でも全件合計でもない。選択時のみクエリを行う。
- ResearchDataHub管理Webの既存「収集」画面に、テーマからIPC候補確認→公開分類の明示承認→EPO最大25件単発取得→履歴確認、容量ソフト上限・件数・PDF図面上限設定を追加。ControlDeck側は候補・容量・履歴の閲覧のみで、Hostのadmin昇格はしない。
- 既存の分類コレクションとFTS索引がある場合、テーマに合う分類辞書結果をローカルで最大8件参考表示する。ただし検索結果を承認済み外部検索コードに自動追加しない。公式IPC/CPC辞書の全導入は次工程。
- PDF図面候補の任意PyMuPDF処理は別Python workerへ移し、CPU40秒・仮想メモリ1GiB・1ファイル2MiB、親側60秒タイムアウトとキャンセル、PNG形式・SHA256再検証を導入。補助処理に失敗した場合は図面候補を省いてPDF原本の取り込みを継続。原文PDFを正本とする。
- 追加テスト: tests/test_source_planner_storage_figures.py（履歴/例外/同時操作/容量/分類辞書/PDF候補worker）と tests/test_source_management_workspace.py（管理者/Host分離・UI/制約）。図表数値の読取、Vision LLM、JPO/PATSTATバルク、全経路ハード容量制限は未実装。

### 確認結果と未実施の境界

GitHub実ファイルのResearchDataHub管理JSとControlDeck JSはV8構文検査PASS（管理JSの括弧漏れを発見し修正）、ControlDeck HTML ID重複0。独立SQLiteのrun履歴INSERT/UPDATEとsource別タイトル/メタの限定計測SQL、合成PDFのベクターbboxから制限付きPython別プロセスで401x384/1,334BのPNGを切り抜いてSHA256を照合する独立smokeはPASS。これらはGitHub正規checkout内のPython unittest/実HTTP/PDFジョブ全体実行ではない。

未実施: 新規Python unittest、LiveServer全回帰、実EPO OPS、ControlDeck/iPhone/QNAP実機、verify-k6.sh、QPKG、PDF高負荷時の物理I/O、PyMuPDFライセンスの正式受入。Draft #40・未マージ・未リリースを維持する。次Codexはまず全追加tests・認証/Host/PDF・scripts/verify-k6.sh・WITH_QPKG=1を実行し、失敗修正を本PRへ集約する。ui.html default、Vue read-only/non-default、backend authoritative、level_0_manual_only、no execution、raw source/fallback/redirect禁止、外部AIへの機密ゼロ、npm build at startup禁止を維持する。取得中電断によるrunの残留表示、PyMuPDF任意依存の安全性もレビューする。

## 2026-11-18 継続3 — 公開国・公開年・手動ページングによる収集範囲の限定

EPO OPS公式 Published-data CQL (Reference Guide v1.3.20, pp. 142–146, 61)を参照: https://link.epo.org/web/searching-for-patents/data/en-ops-v3.2-documentation-version-1.3.20.pdf
WIPO公式 IPC 2026.01: https://www.wipo.int/en/web/classification-ipc

- 新規 source_scope.py は固定IPC allowlist (H02Mなど) に、公開国 ALL/JP/US/EP/WO/CN/KR/DE/FR/GB と公開日による暦年範囲(最大10年)と、EPO結果1〜2000番の1回最大25件を安全に結合する。例: ic=H02M and pn=JP and pd within "20200101 20251231"。登録済の未公開のユーザー技術テーマは含まれない。公開日は出願日・優先日とは別で、公開国は出願先/市場への参入と同義ではない。
- POST /api/v1/source-scope/preview (read) は外部接続ゼロのCQL表示。POST /api/v1/source-acquisitions (admin) の追加許容値: publication_country/year_from/year_to/first。従来のipc/limit/public_only_confirmedだけの呼び出しも維持。余分なcql/query等は400。管理者画面では「検索条件を確認」後に公開分類・公開年等の送信を再承認し、変更時は承認が無効になる。自動ページ送り・一括収集はなし。
- EPO OPS connector: Published-data正式のX-OPS-Range HTTP header (Registerとは異なる) に変更し、従来 generic connectorのlimit数値文字列は維持。ネストしたexchange-document配列のJSON解析修正と不正JSON/認証エラーの安全な拒否。1回最大25件の制限は**新しい分類取得APIのみ**に適用し、既存generic connectorの100件上限は変更しない。
- 取得履歴は公開国/公開年/開始位置を保持し、既存の早期K7aデータベースには起動時にカラムだけを移行。出典別の参考量は**最新2000文献のタイトル/メタデータのみ**をSQLで測る。重い全文・PDF・画像・ベクターは参照しない。SQLite/WAL/SHMの物理総使用量とは別に表示し、全件の完全な出典別占有率とは呼ばない。
- ControlDeck側には同じ検索範囲の**読み取り専用プレビュー**を追加。Host Bridgeは既存read tokenでPOST /addon/v1/source-scope/preview -> ResearchDataHub read APIのみを中継。取得POST/admin tokenは設けない。
- テストを tests/test_source_scope.py および tests/test_source_management_workspace.py に追加。国/年/件数/2000件上限/悪意あるCQLの拒否、管理者権限・明示公開確認、公式range headerとOPS配列JSON、Host read-only/再承認要件を対象とする。
- 未実施: 正規checkoutでのPython unittest、実EPO無料キー接続、全verify-k6、ControlDeck/QNAP/iPhone実機。GitHub実JS構文PASS、実HTML DOM重複0は確認。型・API/テストの統合は**未認証**としてDraft維持。

次工程: 公式IPC/CPC/FI辞書をライセンスに従ってローカル登録し、入力語の曖昧性・境界・confidenceを手動検証させる。2000結果を超える場合は期間・分類を再分割させる（無制限に取得しない）。原本PDF + local-only Vision AI図番号照合、図表数値検証/スキップ、硬い全入口quota、収集ジョブの手動中断・履歴監査を実装。現時点は未実装。


## 2026-11-18: 分類の低操作UI — ローカルAI提案／公式IPC階層

- ユーザー要望で、独自に用意した固定のインバータ・機械などの選択ボタンを主画面から削除。第一経路は日本語の自然文から検証済みローカルAIへ手動問い合わせ、第二経路はWIPO IPC 2026.01の公式階層 A-H → H02 → H02M と選択。ControlDeckで外部取得や辞書の更新は行わない。
- AIによる分類候補は最大5件、JSON形式のみ、未確認。バックエンドは登録済みWIPO公式記号とサブクラスを照合し、辞書未登録コードを画面で選択不可とする。ユーザーが検索条件を再承認するまでEPOへ送信しない。ローカルAIは既存の confidential_allowed + Providers.chat confidential の二重確認を再利用し、クラウド代替接続・オートラン・ツール実行をしない。質問最大360文字、単発・並列1件・60秒上限。
- WIPO公式データは固定2026.01 URLからの有効記号XMLを、管理者の承認した単一セクションごとに最大3MiB/3万件で手動取得し、SQLiteへ版・セクション・SHA256・件数を登録。同一内容は再書込みを回避。IPC階層はローカルの保存済み公式記号から閲覧し、AI候補でも公式で検証できれば固定の10候補以外も対象にできる。backend authoritative。
- 制約: 有効記号リストは分類タイトル/日本語定義を含まず、今後WIPO Scheme/JPO日本語IPC/CPC正式XMLをライセンスを守って追加する必要がある。WIPO実XMLの本番解析、外部接続、正規checkoutのPythonテストは未実施。今回追加した synthetic XMLとHTTP mockの tests/test_ipc_ai_selection.py もまだ実行していない。全CI、ユーザー実機、PyMuPDF性能/ライセンス、既存PR依存確認が終わるまでDraft維持。
- 静的確認: GitHubの実 app.js / addon-workspace.js はV8構文PASS。HTML重複ID0、JSから参照されるID欠落0、Hostに辞書更新・EPO取得POSTなし。固定テーマの選択肢も撤去。mainのUIデフォルトやVue/runtime/manifestの変更無し。


## 実接続・テスト進捗（2026-11-18：以前の「未実施」記録を更新）

公式のWIPO IPC 2026.01 Hセクションについて、英語分類名66件/841,166 bytes、公式有効記号10,607件/1,227,656 bytesの**実HTTP取得→実XML/TXTパーサー→一時SQLite保存→H02M名称付き閲覧**を完了。OpenAlexは公開論文1件の実取得に成功後、匿名HTTP 429も実測。分類GUIには公式名取得ボタン、OpenAlexには最大25件の軽量metadata connectorを実装。管理画面ではEPO/JPO/USPTO等のキーを導入時に入力し、ユーザーが手動で少量の接続テストを実行できる（テストで資料は保存しない）。

一時CIで対象29テストは27件成功＋2件スキップ。全体325テストは1件失敗＋3件スキップ（禁止されている一時CI workflowが唯一の失敗原因）であり、一時workflowは検証後撤去済み。撤去後の全体再テスト未実施。実機、EPO/JPO/USPTO実認証、PyMuPDF任意依存の実確認は残る。[根拠・ログ](source-smoke-evidence-2026-11-18.md)。本PRはDraftのまま。
## K7a OSSバルク研究・実装（2026-11-18）

現行USPTO ODPのProduct/Files APIを、MITのpyUSPTO・patent-dev/bulk-file-loaderを参照し、標準ライブラリで容量限定の読み取り専用カタログとして実装。管理者専用POST /api/v1/uspto-bulk/preview、既存read認証のローカルGET /api/v1/uspto-bulk/options、管理UI、導入後のAPIキー入力、モック13テストPASS。2026-11-18後続では管理者が明示したZIP1ファイルのダウンロード、容量上限512MiB/合計2GiB、Range/ETag/206再開、.part、SHA256、手動停止まで実装した。ZIP爆弾検査・ZIP内文献のストリーミング解析・IPC選別/差分DB保存は次工程。詳細は [patent-bulk-open-source-k7a.md](patent-bulk-open-source-k7a.md)。


最新の[USPTOファイルの限定取得設計](patent-bulk-manual-staging-k7a.md)を参照。初期カタログ-only記述は時系列の前段階で、現在はユーザーが承認して初めてZIPを保存する処理も実装済み。自動検索/自動取得・ControlDeck実行能力の追加はない。


2026-11-18 公開特許11件の実データを用いた「少量取得→規則ベース解析→10種グラフ」パイロットを実施した。Google Patents個別ページだけであり公式バルクZIP取得とは別物。標本選定と定義上の注意は[public-patent-pilot-2026-11-18.md](public-patent-pilot-2026-11-18.md)。データとSHAはtests/fixtures/k7a_public_patents_20261118.json、取得run44311874751。AI無しで分析継続可能、ControlDeckのAIジョブは手動deferredを維持。次は正式ZIPのストリーム解析・DBチェックポイント。
