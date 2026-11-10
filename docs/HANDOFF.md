# HANDOFF — ResearchDataHub / PatentBuddy

更新: 2026-11-11。`AGENTS.md` → `DEVELOPMENT_WORKFLOW.md` → 本書 → `docs/CODEX_NEXT.md` の順に確認する。計画の正本は `researchdatahub-plan.md`、性能受入は `researchdatahub-performance.md`。

## 現在地

- Repo: `souten-yd/PatentBuddy`。最新公開 **v0.5.10**、main `193f53a`（remote再確認済み）。公開版の受入は「v0.5.10実導入」を参照。
- 作業場所 **`/data1tb/PatentBuddy-graph` / feat/evidence-graph / Draft PR #23**。Host統合/PDF/OCRは公開版へ導入済み。候補では索引Jobs・vector/graph/rerankチャートとgraph承認変更の依存管理まで実装/検証済みだが未配布。次は生成モデル版の記録と人手レビュー/graph管理UI。
- ユーザー目標は計画全体の完了。**PR-E残作業・PR-F/G、QNAP実機は未完了**。勝手にPR-Cだけを全体完了としない。
- 内部package `qnaplibrary`、QPKG ID `QnapLibrary`、port17871、Cookie/パスキーRP ID、Release資産名を維持する。ResearchDataHubは唯一の正本、PatentBuddyはPC上のControlDeck Add-on。SQLiteをSMB/NFSで共有・同時二重書込みしない。
- 未公開情報は検証済みローカルLLMのみ。既存privacy gateを弱めない。NAS↔PCの認証/TLS通信とクラウドLLM送信は区別する。

## 完了した実装単位

| 計画 | 状態・証拠 |
|---|---|
| 設計 #16 | main統合済み `24cb084`、docs-only |
| PR-A #17 | v0.5.2公開、main `4170acd`、release run42809839947成功。薄いLinux入口・doctor/serve/test・Web/health表示・配布互換。61 tests、非root Linux導入、QPKGのLinux展開start/status/health/stop。QTS実機ではない |
| PR-B #11 | v0.5.3公開、main `b14ed77`、run42810849292成功。ハッシュのみセッション永続化/最大128件、通常GETと期限切れ参照はRAMのみ。再起動Cookie/CSRF/パスキー登録・RP ID・ログアウト/パスワード変更失効を検証。67 testsと配布/更新確認 |

旧公開v0.5.1の更新確認は改名前Repo名によるURL不一致で失敗することを再現。初回は手動更新が必要。公開v0.5.3をSHA-256照合し非rootで手動更新、管理者/コレクション保持、配布4 smoke tests成功。**修正済みv0.5.3→v0.5.4の管理API自己更新は成功。**

PR-Bでは未読POST本文が次のHTTP/1.1要求に混ざり501になることを実HTTPで再現・修正。一般リトライなし。iPhoneの実パスキー署名やQTS独自の別原因は未検証。rdh.shのcwd別checkout誤読も修正。

## PR-C — 公開資料API（v0.5.4公開済み）

- 既存Draft #15をmain v0.5.3へ統合し実diffをレビュー。
- 管理者専用の送信プレビューにタイトル/公開番号/抜粋を全表示。10分有効の署名tokenが文献版・全表示項目に結び付く。変更/期限切れ/再起動なら再確認。抜粋の無断切詰め/正規化なし。プレビューは永続書込みなし。
- 原文更新で承認を無効化。本文を元へ戻しても再承認まで停止。原文削除時は公開snapshotとFTS索引を削除。
- `published` tokenは専用検索/取得route以外を全件403。private資料/MCP/debug/export/settings不可。管理Cookie併用でも昇格しない。LAN pairingで発行不可。loopback以外はTLS必須、遠隔からのX-Forwarded-Proto偽装を拒否。
- 公開API **14 tests合格**。プレビュー競合/期限/再起動、失効、TLS条件、CSRF/Origin、全private route遮断、FTS代替経路、原文削除、型不正、通常検索のDB更新0を確認。
- 実TLS: 一時証明書を検証するHTTPSクライアントで承認→専用token取得→公開本文のみ取得、MCP403。`/tmp/pb-public-tls.py`。
- 実Chrome: 1280/390pxでプレビュー全項目→入力変更で無効化→同意/承認→公開用tokenで抜粋だけ取得・private403。横溢れ/JSエラー/外部リクエスト0。証拠 `.data/acceptance/pr-c/browser.json` / `preview-*.png`（合成データのみ）。`/tmp/pb-public-ui.cjs`。一時サーバーは停止済み。
- 最終verify **81 tests合格**（20.088秒、`/tmp/pb-verify-054.log`）。Linux/QPKGビルド・payload検査合格（`/tmp/pb-build-*-054.log`）。PR全diffを確認。main `b7816cf`へマージ、Release run42814233042成功。公式v0.5.3から管理API check/apply→実download/SHA検証→symlink切替/再起動→v0.5.4を確認。Cookie/CSRF/collection保持、新公開route、旧version保持すべてPASS（`/tmp/pb-autoupdate-054.json`）。QPKG展開Linux start/status/health/stopも成功。
- 書込み追加理由: 承認snapshot/FTS/監査、原文改変時の不可逆な承認停止、削除時の索引清掃が必要。検索の常駐書込みは増やさない。認証last_seenは既存ポリシー。

## ユーザー指定PDF / ControlDeck LLM検証

- ダウンロード済みPDFを実解析。成果物 `/home/souten/ダウンロード/JPA-2026116114-analysis/report.html` と同名zip。元PDFを変更せずSHA-256再照合。本文15頁、請求項14（独立1/14）、段落64、図11。表紙だけOCR+目視。原文・図・回答はGitに入れていない。
- ControlDeck管理llama.cpp（loopback8097、Qwen3.8-27BローカルGGUF、mmproj）で全文要約/請求項整理70.60秒、整合性60.80秒、図6画像11.55秒。従属関係14/14一致。回答の逆表現・自己参照接続などは原文で検証して訂正/除外、原回答を保存。実行品質を法的品質や全自動正確性と混同しない。
- 実資料の一時API取込: 本文往復一致、70チャンク、3検索語ヒット、請求項14件。実資料は本番/公開APIへ自動登録していない。HTMLはChrome1280/390pxで図11/請求項14、横溢れ/画像欠損/JSエラー0。
- 合成案件の再現スクリプト: `PYTHONPATH=. python3 scripts/test-local-llm.py --verified-local`。既存モデルを利用しロード/アンロードしない。初回合格42.58秒/1137文字、案件変更なし。

## 次の一手 / 未完了

1. PR-C配布・更新まで完了。PR-D #13へ移行。mainとの競合は最新計画/引継ぎを維持して解消、merge commit `3c8d82e`。既存scale 4 tests合格。
2. PR-D #13: 実diffと性能仕様を読みP0計測に着手。比較用の変更前checkout `/data1tb/PatentBuddy-baseline-054` はdetached `b7816cf`。既存bench_patents.pyは物理I/O・API分位点・再起動/復元・15分idleが不足するため汎用bench_datahub.pyへ拡張する。初期1千/1万件比較を `.data/bench/*-{1000,10000}.json` に保存。1万件無変更再投入: baseline 50行/204800 process write bytes、候補0行/0 bytes。出典/明示sections訂正の取りこぼしを追加修正したため最終候補の小規模再測定が必要。1千/1万/10万、P50/P95/P99、CPU/RSS、物理I/O/DB/WAL、15分idle、再起動/復元を変更前後比較。無変更書込み0、一覧本文なし、カーソルを検証。100万件対応は未実測。
3. PR-E: #14/#18の検索閲覧プレビューとローカル自動認証は公開・実導入済み。Host AI/Jobs/Brokerと特許調査操作の統合は残る。PC側に別正本文献DBを作らない。
4. PR-F #10等: 確定/推測エッジ分離、根拠・版・人手承認、bounded GraphRAG、ローカルLLMのみ。まだ未着手。
5. PR-G: **最後**にPC→QNAPのdry-run/backup/hash/quick_check/件数/秘密・認証確認/停止・単一書込み切替/ロールバック。QNAP既存領域の上書き・削除禁止。未着手。

QNAP TS-253Be/iPhone実署名・TLS実環境、公的API実キー、Host署名/publisher登録、NAS HDD性能、実案件の法的品質・審査状態は未検証。過去詳細はgit履歴と各Release/PR参照。goalはactive。

## PR-D P0/P1 作業中（2026-11-10追記）

- `scripts/bench_datahub.py`: temp合成DBの認証HTTP APIを計測。API分位点・docs/s・MiB/s・CPU/RSS・SQL execute/fetch時間・total_changes・DB/WAL/SHM・proc I/O・device counters・dbstat容量・backup/Store再open/復元・検索一致を記録。schedulerは開始しない。device countersは他プロセスの活動を含むため専有I/Oとは呼ばない。サービスプロセス再起動時間は別途必要。
- baseline 10万件+900秒idle→candidate同条件を直列実行中。**exec session57856**、shell PID65806、baseline Python PID66329（この時点で生存を確認）。ログ `/tmp/rdh-{baseline,candidate}-100000.log`、最終JSON `.data/bench/{baseline,candidate}-100000.json`。再開時はハンドル/psを再確認し、観測timeoutだけで再実行しない。
- スケール回帰8 tests: 並行batch整合、途中例外の全体rollback、cursor途中削除、コミット直前の子プロセスkill→WAL復旧/再送を追加。source訂正がunchangedとして捨てられる失敗を再現・修正。本文がある文献の明示sections変更/順序もdigestへ含める。通常文献の既存digestは維持し全件再構築を避ける。
- 現時点のControlDeck LLM: 前回の8097 listener/llama-serverは今回存在しない。既存の成功記録は履歴として保持するが今回実行したと扱わない。Host管理経由の現在のruntime選択をPR-E結合時に確認する。直接モデルを勝手に起動していない。

- P0計測方法・初期値は `docs/benchmark-datahub.md`。全verify **89 tests成功**（20.728秒、`/tmp/pb-scale-verify.log`）、後続のsections順序を含める一行修正後はscale8 tests再成功。最終全verifyはマージ前に実施。

## 追加受入 / QNAP更新問い合わせ

- ユーザーの「QNAPのv5.2で想定外のダウンロードURL」に対し、アプリv0.5.2の実tagコードと現行公式ReleaseのQPKG URLで同じ例外を再現。旧REPO `souten-yd/QnapPatentBuddy` が原因。修正済みselectorはv0.5.4資産を受理。初回のみApp Centerから手動上書き更新する手順を案内。公式QPKGを `/home/souten/ダウンロード/QnapLibrary_0.5.4_x86_64.qpkg` へ保存しGitHub digestとSHA-256一致を確認。NAS自体は変更しておらず、手動更新成功は未確認。
- `bench_datahub_restart.py`: 変更前/候補の1千/1万/10万件で実プロセス停止・再起動・別temp領域復元を検証。全6ケースで古いCookie/CSRFの読書き、件数、検索一致、snapshot SHA、quick_check成功。10万件候補のhealth再起動0.102秒、復元2.622秒、変更前0.102/1.410秒（50ms polling、各1回、同等性能保証ではない）。原データ `.data/bench/restart-*.json`、ログ `/tmp/rdh-restart.log`。
- scale testsは10件成功。SQLite変数上限500で850件batch再投入、コレクション間同一IDの独立性、FTS無効時の検索/再投入/カーソルを追加。
- ControlDeck既存Gateway APIキーをメモリ内で取得して一時テストの0600 secretsへ渡し、`http://127.0.0.1:8765/api/v1/llm/v1` 経由で実LLMテスト成功。APIキーは出力していない。`resolve_instance('auto')`でローカルGGUF Qwen3.8-27Bを確認、Hostのadmission/起動経由、68.44秒/1169文字、案件不変。`/tmp/pb-host-llm-test.json`。直接モデルプロセスを起動していない。これはAdd-on principal結合の完了ではない。
- PR-E事前調査は `docs/host-integration-review.md`。最新mainと稼働checkoutが異なるため実装時に双方の実契約を再確認。未コミットのControlDeck作業を変更していない。

## 今回の追加修正・ユーザーの管理体系指定

- ユーザーはPatentBuddyをControlDeckオプション機能の導入/更新ボタンで管理し、ResearchDataHubサーバーと明確に区別することを再指定。PR-Eの必須受入に反映する。Hostのtrusted-catalog登録、署名付きrelease-bundle、install/update/enable/disable/uninstallとデータ保持、サーバー接続先/役割/各versionの別表示が必要。現在のPR #14だけでは未達。
- `bench_datahub_restart.py`の設定ファイル名を実物のsettings.jsonへ修正し、秘密・非default RP ID/session期限・syntheticパスキーの明示照合を追加。旧結果ではsettings保持を証明できていなかった。修正版の全6ケース成功、`.data/bench/restart-v2-*.json` / `/tmp/rdh-restart-v2.log`。これは実パスキー署名ではない。
- ディスク上限でSQLITE_FULLを起こしたところ自動rollback後の二重rollbackで本来のエラーが隠れる問題を再現。transaction cleanupを修正。またBEGIN IMMEDIATE失敗時にPython lockを解放する。scale12 tests成功（容量不足後の既存内容保持/再開、別writer競合後のlock解放）。
- 直前の全verifyはREADMEのversion見出し規則で1件失敗。ユーザー向け更新対処をdocs/upgrade.mdへ移しREADMEからリンク、テスト規則は維持。修正後の全verify待ち。

## 実導入確認（2026-11-10・最新）

- PatentBuddy v0.5.5公開済み。PR #14 main統合 `9a267695391ada9aab8a45382bbf9c049d59ac53`、Release run42819243693成功。署名付きFeature資産を公開し、ControlDeck正規CLIでinstall/enable。稼働Host自身のstatusでinstalled=true/enabled=true/managed=true/version=0.5.5/health=healthyを再確認。
- Host catalog PR #348はmain統合 `65272ebf09b9411415abc9e553d471325b1a030c`。稼働checkoutの他の未コミット作業を維持し、catalogのPatentBuddyエントリだけ反映してHostを再起動済み。ユーザーunit control-deck-web / cdapp-feature-patent-buddy / qnaplibrary は全てactive。
- PatentBuddy URL: https://souten-linux.tailc8e858.ts.net/x/patent-buddy/workspace （HTTP200を確認。ログイン後の実Hostブラウザ操作は未検証、合成HostでのChrome検索/詳細表示は検証済み）。
- ResearchDataHub Linux v0.5.4: http://192.168.68.200:17871/ （Web200・health ok）、Tailscale http://100.82.8.44:17871/ 。管理者初期設定済み。パスワードは読取/変更していない。
- 接続tokenは未設定。実際の永続設定先は `/data1tb/ControlDeck/data/feature-data/patent-buddy/connection.json`、0600。server_urlは `http://127.0.0.1:17871`、server_tokenは管理Webで発行するreadonly token。tokenをチャットへ貼らない。Featureサービス稼働とサーバー接続完了を区別する。
- v0.5.5は検索/本文閲覧のプレビュー。Host AI/Jobs/GraphRAGは未実装、PR-E全体完了ではない。PR-D以降の計画は継続。次のReleaseでもHost latest参照に対応する署名付きFeature三資産の公開が必要。

## 同一ユーザーのローカル自動接続・実導入済み（最新）

- ユーザーの追加要求に従いPR #18を実装・マージ。main `73ae466c4569f411bb3a44fbfc1b18fe28eb061b`、v0.5.6、Release run42820937291成功。別worktree `/data1tb/PatentBuddy-addon` のfeat/local-addon-auth。PR-Dはこの新mainへの整合が次に必要。
- Linux同一UIDのUnix SO_PEERCREDで相互確認。0700 runtime directory/0600 socket、排他lock、RAM限定ro token、loopback限定、管理初期設定前は発行しない。再起動で失効。auth.local_auto_connect=falseで停止、manual connection.json優先。root/TLS専用/別ユーザー/独自ポート自動探索は対象外。同一OSユーザーは同じ信頼境界であり、特定実行ファイルの証明ではない。
- 最終96 tests合格23.485秒、Linux/QPKG build/payload成功。実プロセスGET200/書込み403/再起動後旧token401/再取得200。別UID・管理API拒否、無効化、非ソケット拒否・排他も検証。`/tmp/pb-local-auth-verify-final2.log` / `/tmp/pb-local-auth-process.json`。
- 公式Linux資産のSHA検証後、既存prefix/dataを指定しinstallerでv0.5.4→0.5.6更新。先に `/data1tb/ResearchDataHub/backups/pre-0.5.6` へSQLite backup/quick_checkと秘密ファイルcopy、設定/秘密の更新後一致を確認（settings.jsonは元から存在せずdefault、秘密内容を出力していない）。管理者設定を維持。
- Featureは既存publisher鍵で署名、新規鍵生成なし。公開SHA `39db9a8ee1201c8c444134800d7bbd955b315db66b4f5514134715a9ec475f10`。稼働Host正規CLI updateでv0.5.5→0.5.6、installed/enabled/managed=true、healthy。署名三資産をRelease添付済み。
- 実インストール済みAddonClientでauth_method=local_peer/server v0.5.6/reachable=true、読み取りAPI成功。connection.jsonなし。addon healthはhealthy/ready/setup=[]。全3ユーザーサービスactive。ユーザーのtoken手入力は不要となり、以前の接続設定待ちを解消。
- URL: PatentBuddy https://souten-linux.tailc8e858.ts.net/x/patent-buddy/workspace / ResearchDataHub http://192.168.68.200:17871/ 。実Hostログイン後ブラウザ受入、AI/Jobs/GraphRAGとPR-D〜Gは引き続き未完。

## PR-D再開

最新main v0.5.6を統合。HANDOFF競合はPR-D測定履歴と実導入の最新記録を保持して解消。10万件測定は両方完了、候補commit eb6354d、無変更再投入DB更新/process write/device writeすべて0。最終比較文書・一般メタデータ設計・全verify・公開/更新を続ける。

- v0.5.7候補へ版を統一。P0/P1最終比較と生JSONをdocsへ保存（合成データのみ）、P2一般識別子/版/日付/出典/ライセンス設計を追加。追加索引2,469,888 bytes、登録write増約13.17MBを深いcursorアクセスの費用として明記。PR-Dはコード/配布最終検証中、まだ公開しない。ControlDeck GatewayローカルLLMの再テストも進行中。

- v0.5.7最終全verify108 tests成功25.034秒（/tmp/pb-scale-057-verify.log）、Linux/QPKG build/payload成功。10万件のStore実装は計測候補eb6354dと同一。ControlDeckローカルLLMテストPID143325稼働を確認、結果待ち。

- ControlDeck Host Gateway経由のローカルQwen3.8-27Bテスト成功、50.02秒/1206文字、案件不変（/tmp/pb-scale-host-llm.json）。既存Host認証キーは出力せず、ローカルGGUF/runtime確認後にHost admission経由で使用。AI品質やAddon principal AI結合の完了とはしない。

## PR-D完了とPR-E続行（最新）

- PR #13はmain `11c500bb4d1985aa457961ccab1f5254fde02052`へ統合、v0.5.7 / Release run42821949480成功。mainのStore/API/Searchは検証済み候補と差分なし。README最終文書確認で存在しないtest_docs_rules名を誤指定したが、実在のtests.test_updater_docs 7件を再実行して成功（全108 testsは先行成功）。
- 公式v0.5.6配布から管理API check/apply→download/SHA→再起動→v0.5.7へ自己更新成功。Cookie/CSRF/文献保持、cursor/外部ID一致/無変更再投入を確認。`/tmp/pb-autoupdate-057.json`、一時プロセス停止済み。
- 実Linuxサービスも公式資産SHA検証後v0.5.7へ更新。`/data1tb/ResearchDataHub/backups/pre-0.5.7`に一貫SQLite backup/quick_checkと秘密保全。既存設定/秘密一致を確認。ControlDeck正規Feature updateでv0.5.7、installed/enabled/managed=true/healthy、署名付き三資産公開。SHA eb31ee045416de6c34b2b7306790a964910e92257b5554f8d0937d8e37d65092。
- 実AddonClientからserver v0.5.7/local_peer自動認証と読取API成功、addon health healthy/ready。実Hostブラウザでのログイン後受入とAI/Jobs/GraphRAGはまだ未完。
- 次はPR-E A3: Host capability-scoped AI/Jobs/Broker。稼働Hostのai_gatewayはllama.cpp/Ollama選択のみだが、capabilities応答はlocal-onlyを証明せずOllamaのremote/cloud設定を排除できない。機密入力の前にHostでlocal-only要求を検証する契約を追加し、Addonはその応答/拒否を使う必要がある。ローカルURLだけを証明にしない。
- 稼働ControlDeck checkoutにはユーザーのpasskey作業が引き続き存在。触らない。Host側変更は隔離worktree/別PRで行う。PatentBuddyの独自永続文献DBは作らず、研究結果/案件の正本はResearchDataHubに保存。現在ro自動tokenの書込み権限を無条件rwへ広げない。

## PR-E A3 / PR #19 作業中

- Host PR #349 main `3913d167ca3497cd0b5ba9902c8daaf5202e8d94`。local_only厳密bool、Host管理llama.cpp/GGUF/loopback検証、GPU admission前後再検証、proxy/redirect禁止。52関連/全1225 tests（2skip）、frontend build成功。実Host service token→Broker→ローカルGGUF応答1.3秒/68文字。稼働Hostの製品3ファイルだけbase一致確認後反映、既存ユーザーpasskey変更保持。テストuser削除FK失敗はsession削除・監査FKのみNULL化で解消、監査6件保持。
- PatentBuddyにHost AI/Jobs client、短期job credential/所有者/capability確認・更新、stream切断キャンセル、限定analysis権限の正本保存API、原文revisionと冪等結果ID、再起動interrupted/再実行/Host終端再送を実装中。アドオンは本文/回答/tokenを永続化せず、最大32件の再開メタデータだけ0600保存。同時2件/所有者1件、本文10万文字上限を明示し無断切詰めなし。
- Chrome合成Host API/AI+実Addon/ResearchDataHubで1280/390/320pxの要約/請求項操作、320pxキャンセル/再実行成功。横溢れ/JSエラー0、`.data/addon-ai-ui.json`。これは実Hostブラウザ受入ではない。
- キャンセルをfailed表示する回帰を修正しjobs5 tests成功。実socketでblocked SSEをabortしてpartial回答を採用しないことも確認。最終全verifyはこれから。
- 実ControlDeck Host Jobs/AIと候補Addon clientを使う合成案件テスト `/tmp/pb-analysis-live.py` を実行中（session94450）。候補データはtempだけ。稼働サービスのPatentBuddy/ResearchDataHubはまだv0.5.7、PR19変更は未公開/未導入。

- v0.5.8候補。実Host Jobs/AI→候補Addon→temp ResearchDataHubで請求項分析成功22.59秒/1585文字、Host終端同期成功。キャンセル時の未保存も確認。一時アドオン/user/session削除、監査/job履歴は保持（owner FKのみ解除）。/tmp/pb-analysis-live.jsonl。
- 最終verifyの前段119 tests成功30.433秒。snapshot復元と分析専用Unix認証の検証を追加し121 testsを実行したところ、HANDOFFに候補版番号を書き忘れた文書規則で1件失敗。実装テストは成功。候補版を追記し再検証する。
- 追加ディスク書込み: 正本のdocument_analyses表/索引と作成時監査、Addon側の最大32件のジョブ状態checkpoint（0600）が再実行/冪等保存/原文版照合に必要。本文/回答はAddonへ永続化しない。GET一覧と既存無変更投入は追加writeなし。

- v0.5.8最終121 tests成功33.258秒、Linux/QPKG build/payload成功。保存snapshot復元/監査保持、独立analysis Unix tokenとro境界を確認。公開/実更新/実Host画面はこれから。
- 追加ユーザー要求: PDF読み取りと必要時OCR。PC上にpdftotext/pdftoppm/tesseract、jpn/eng/osdが既存。画面からのPDF取込/OCRは未実装。指定PDFの表紙OCRは過去の個別処理でありアプリ統合と区別。PR19 AI/Jobsを完了後、Host Files/Brokerとページ単位抽出・原本hash/ページ/方法の根拠保存を実装する。

## v0.5.8実導入とHost画面の修正（作業中）

- PR19はmain725e3ecへ統合、Release42827637382成功。公式Linuxと署名Featureを実更新し双方v0.5.8。旧0.5.7の管理APIから公式自己更新も成功（/tmp/pb-autoupdate-058.json）。121 tests成功。
- 実Hostブラウザ受入で停止中表示を再現。Hostの厳格AddonHealthReportがapp/version/service_roleという余剰fieldを拒否している。合成Host試験では検出できなかった契約不一致。さらに更新後の新規ai.inference/jobs.write権限は既存grantに自動追加されない。画面で使える状態に直してからPDF/OCRに進む。
- 本修正PRはhealth契約整合と実Host画面受入に限定。PDF/OCRは次の作業で、現在アプリには未統合。

- v0.5.9候補: health余剰fieldを除去。手動token設定時もsetup済みとし、接続検証は認証済みstatus/UIで行う。新規AI/Jobs権限をHost正規enable APIで明示付与する。

- Host実スキーマはhealthy時のreason_code=readyも拒否するため省略へ修正。setup_required/healthy双方を実Host AddonHealthReportで検証成功。最終122 tests成功30.752秒、Linux/Feature build成功。/tmp/pb-health-059-verify-final.log。追加ディスク書込みなし。

## PDF/OCR次の実装単位

- 隔離worktree `/data1tb/PatentBuddy-pdf`、feat/pdf-ocr-import。計画は `docs/pdf-ocr-plan.md`。まず上限/キャンセル付きのページ単位ローカル抽出とテスト、その後Host Files/Jobs/CPU lease・限定保存認証・原本snapshot・UIを結合する。
- Host画面修正PR20はmain6963a54へ統合、v0.5.9 Release42829063808成功。署名Featureを実更新済み、実ブラウザ受入中。サーバーはv0.5.8（healthのみのAddon修正と区別）。

## v0.5.9実画面受入とPDFコア（最新）

- PR20 main6963a54924551d12debf7af56b2c0de470f9b8f3 / v0.5.9 / Release42829063808成功。署名Feature SHA1d3022e466778b97dca26b60637440040abc1f244aad3823e1d2cc4b5e9db849、実update成功。公式0.5.8→0.5.9自己更新でcookie/CSRF/文献・分析結果保持成功（/tmp/pb-autoupdate-059.json）。
- 実Host HTTPSログイン/Bridge/導入済みAddon/実local-only LLMで1280px要約・320px請求項分析とキャンセル成功、横溢れ/JSエラーなし。合成資料のtemp ResearchDataHubだけを接続して隔離検証（実本番文献の受入ではない）。証拠 `/data1tb/PatentBuddy-addon/.data/installed-ai-browser.json`。enable要求の初回403は試験scriptのCSRF header漏れ、正規X-Requested-With付与後成功。
- Host正規enable APIで既存3capにai.inference/jobs.writeを明示追加。テストconnection.jsonを撤去し、実サーバー17871/v0.5.8/local_peerへの自動接続復帰確認。temp user/session/job metadata削除、監査・Host job履歴保持、remaining_job_count=0。全3ユーザーサービスactive、pre0.5.8から秘密保持確認。旧合成UI試験プロセスも停止。
- PR21 PDFコア `qnaplibrary/pdf_extract.py` を追加中。Linux別processでCPU/AS/file-size上限、子process group停止、入力50MiB/200page/100万字上限、固定tool argv・shellなし・ページ長辺2400pixel。新依存は追加せず任意既存Poppler/Tesseractを使用。まだAPI/UI/Host lease/保存には未接続。
- 指定PDFの初回native抽出は15ページ1.83秒だが、表紙の出願人等の画像部分を取りこぼすことを確認。pdfimages一覧で画像入りページを検出し、表紙と12〜15ページだけOCRするよう改善。再試験15ページ6.86秒（直接CPUの候補module試験、Host Jobではない）、native10/OCR併用5。原本hash/ページ/nativeとOCR本文/エンジン版/単語信頼度を保持。表紙OCRは29低信頼単語があり品質完了とはしない。
- 任意tool有無/入力サイズ/偽PDF/取消/リンク拒否/実child停止/実native/強制OCR/画像混在PDFを4 testsで確認。画像混在回帰込み3.433秒成功。`.data/pdf-extract-user.json`はローカル試験データでgit追跡しない。初回edit scriptの構文エラーはコード変更前に失敗、修正して再実行済み。
- 次: コア最終tests・コードreview後push。Host Files grant・Jobs/CPU lease・狭いimport認証・原本blob/ページ根拠の正本保存/復元・UIを実装する。PDF原本/抽出資料をAddon永続文献DBへ保存しない。PR21はDraftでリリース未実施。PR-F/P2/PR-Gも未完。

- PDFコア最終全verify126 tests成功（/tmp/pb-pdf-extract-verify-final.log）。低信頼単語の行/段落を最大1000件残し、超過時は省略flagを明示。実際のOCR取り込み画面・Host Job/Broker・原本保存は引き続き未実装。次回は `/data1tb/PatentBuddy-pdf` のPR21から続ける。

## PR21 PDFの正本保存・Host接続（作業中）

- `pdf_store.py` / API POST `/api/v1/pdf-imports` を追加。原本はSHA256キーのSQLite BLOBとして1個だけ保存、抽出版ごとにimmutable文献とページ根拠を作る。取り込み専用scopeはfixed `pdf-imports` コレクションへの新規作成のみ、任意文献更新/削除/設定/分析保存不可。原本readは認証必須、published tokenでは不可。
- 原本/抽出/本文/FTS/監査は同じtransaction。既存add_documentsに内部connection引数を追加して正本transaction内で再利用（外部APIから指定不可、通知はcommit後）。全抽出版を削除したときだけ原本BLOBを削除する。snapshotに原本も含まれるので、別ディレクトリコピーによる復元漏れはない。
- 独立RAM `pdf_import` tokenとUnix socketを追加。ro/analysis tokenは既存のまま。別UID/非loopback/再起動/無効化時に受け付けない。NASの手動接続は現時点rw tokenが必要で、狭い永続import tokenと接続設定UIはまだ未対応。
- `addon_pdf_host.py`: 正規grant UUID/期限/サイズ/PDF名確認、Host原本stream取得、2GiBのHost RAM/CPU lease取得・activate/renew/release、GPUへの代替を拒否、取消時にsocket停止。Host実RuntimeResourceRequestで要求schema検証成功。HostSessionのrequired能力をclass属性にし、PDF処理にAI能力を不要とする。
- 関連9 tests成功3.486秒、全133 tests成功35.100秒（/tmp/pb-pdf-storage-verify.log）。atomic失敗rollback、二重取込DB変更0、抽出版2つに原本1個、最終参照削除、原本/抽出/監査のsnapshot復元、scope境界、独立Unix token失効を確認。
- 指定122330-byte PDFのtemp正本保存測定: 初回0.0095秒/process write622592 bytes/DB changes214、WAL総量1009432 bytes（増分とは異なる）。同一再投入0.0004秒/DB changes0/process write0。snapshot733184 bytes、復元含む0.0082秒、原本SHA一致/quick_check=ok、maxRSS23380 KiB。/tmp/pb-pdf-store-measure.json。これは1資料のPC上観測であり大量/NAS/50MiB上限の性能保証ではない。原本BLOBと版根拠の追加writeがバックアップ一貫性に必要。
- 実Host Jobs/CPU lease/files grantで指定PDFを取得する試験を実行。初回は高速nativeページのprogressがHostの2Hz制約に当たりHTTP429。途中成功扱いせず、lease解放/一時addon・user・session除去。失敗証拠 /tmp/pb-pdf-host-live-attempt1.*。progressを1Hzにまとめ、最終page通知は取消可能な待ちで間隔維持、回帰4 tests成功。
- 再試験 `/tmp/pb-pdf-host-live.py` は実Hostで原本取得→15ページOCR併用→temp ResearchDataHub保存→CPUlease解放→Host完了照合まで成功。続けて同文献を実Host local-only LLMで要約中。結果は `/tmp/pb-pdf-host-live.jsonl`、session66815。実原本を使うが本番DBへはまだ未登録。
- 次: LLM試験/一時grant metadata cleanup/最終verify結果を確認してpush。PDFJob managerの中断・再起動・Host終端再送・一時原本掃除、UIのFiles pickerとページ根拠/原本/図閲覧、署名配布/実更新/実画面受入が未完。既存AnalysisJobsと並行できるよう上限とowner境界を保持。PR-F/P2/PR-Gも継続。

- 再試験完了: 指定PDFの取込後に実Host local-only LLMの要約生成/正本保存/Host終端同期成功64.59秒/3962文字。これは内容品質の人間承認ではない。temp addon/user/session削除、監査/Host履歴保持、一時grant metadata 2件も除去。最終134 tests成功37.560秒（/tmp/pb-pdf-storage-verify-final.log）。lease解放応答のID/状態/Job照合も追加し回帰検証済み。

## PR21 PDF UI / Job管理（最新、未公開）

- `PDFJobs`を実装。独立最大32件のmetadata履歴、PDF同時1件、所有者境界、CPU leaseと認証の5秒監視、キャンセル、原本SHAを確認する再選択実行、Host終端再送。原本/抽出本文/filename/tokenはmetadataへ保存しない。一時原本と中間画像は0700 scratchの中で処理し、終了時削除。再起動時は排他lock取得後に当該scratch残骸だけ削除する。
- 保存API応答を失ったときは抽出版hashの読取receiptで照合。照合先まで落ちていればinterrupted/確認待ちとし、後で保存済み資料を回収する。原本/結果を保存済みなのに失敗と決めつけたり重複文献を作らない。新API GET `/api/v1/pdf-imports/{digest}` はread、published拒否は既存境界を維持。
- UIにHost Files picker・OCRページ指定・進捗/取消・状態照合/再選択・原本download・ページ根拠/低信頼語数を追加。取り込み中は新規選択buttonを無効化。分析へそのまま進める。Host capabilitiesにfiles.pick/resources.acquire追加（配布後に正規enableで明示grantが必要）。
- `tests.test_addon_pdf_jobs`は原本/秘密がmetadataに残らない、取消未保存/owner拒否、一時領域掃除、応答喪失receipt復旧、保存確認待ち、Host終端再送、排他lockを検証。既存AddonShell test teardownへPDFJobs.close追加。urllib HTTPError responseもcloseし、最終139 tests成功43.919秒、ResourceWarningなし（/tmp/pb-pdf-jobs-ui-verify-final.log）。前段139 testsは成功したが未close警告があり修正した。
- 実Host Chromeの1280pxで選択→指定PDF15ページ取り込み→原本download/SHA一致→ローカルAI要約表示成功。320pxで頁根拠表示/原本SHA/取消成功。横溢れ/JSエラーなし。fixtureは候補Addon+temp ResearchDataHubで、導入済み製品の受入ではない。`.data/pdf-ui-first.json` / `/tmp/pb-pdf-ui-browser.log`。
- テストscriptのフォルダbutton名は末尾「›」を含むため、最初の2回はexact locatorがtimeout。部分一致に修正。最初の320pxは前回成功資料を先に開いていたため、次回は新規成功カード数の増加を待つよう改善。busy button修正後の再試験で1280/320双方の新規取込と原本SHA/取消も成功（/tmp/pb-pdf-ui-browser2.log、LLM再実行は省略）。
- fixtureの初回起動は実class名を誤りImportError。生成直後の一時user1件はJob/session未作成を確認し削除、classをAddonShellへ修正して再起動。その後のfixture停止ではtemporary addon/user/session/grantとtemp原本/DBを除去、監査/Hostjob履歴を保持する。
- 未完の重要契約: Hostのlease解放済み/期限切れ状態を再起動後に照合するGET `/resources/leases/{id}` が現在ない。PDF clientに409時のGET照合を実装したが、Host側の最小read route追加/権限テスト/PRと実反映が必要。確認できない場合はhost_sync_pendingを残す。Hostを勝手に完了扱いしない。
- 次はこのHost復旧契約、原本からの図/ページ画像の保存・閲覧、狭い永続PDF取込token（NAS接続でrwを要求しない）、リリース用docs/版整合・Linux/QPKG/署名Featureビルド、実更新・導入済み画面受入。その後PR-F/P2/PR-Gを続ける。現在本番はPatentBuddy v0.5.9 / RDH v0.5.8のまま。

- 2回目の実Host UI fixtureも停止・一時addon/user/session/grant除去を確認。本番Addon healthはhealthyのまま。最後にPDF取込のJSON配列を400で拒否する型検査を追加し、保存/Jobs/client関連12 testsを再検証。全体139 tests以降の変更はこの入力検証とテストだけ。

## v0.5.10候補・画像と復旧の仕上げ

- ControlDeck PR350はmain5e1dde7へ統合。scoped GET lease追加/所有者DB照合をto_thread化。35関連tests成功4.69秒。初回全体1件失敗は新worktreeにfrontend/distがなくSPA route不在だったため（Project Lab 404/405）、コード/テストを緩めずfrontend build21.32秒後に同一test成功。全1226 tests成功112.41秒/2skip/既存warning。実Hostのresources.pyが元mainと一致すること・active Jobsゼロを確認して当該1ファイルだけ反映、ユーザーpasskey変更を保持して正常再起動。
- 実Hostでlease GETが期限を延長しないこと、二重releaseが409→GET released確認で復旧することを検証成功（/tmp/pb-host-lease-live2.jsonl）。初回は古い試験scriptがmanifestへ既存capabilityを二重追加して422、dedupe後成功。一時addon/user/session除去、監査/Host履歴保持。
- 指定PDFの埋め込み画像13点/64182 bytesを抽出（表紙の画像を含む、図番号の自動確定ではない）。PDF画像のページ/index/PNG hash/寸法を保持。PNGはCRC/完結/画素上限確認、1点2MiB/200点/合計32MiB。workerのpdfimages出力も1file2MiBに制限してから実行する。原本と同様に共有BLOB+抽出版参照として原子的に保存し、最後の参照削除で削除する。
- PNGの壊れ/偽装/頁・hash不一致拒否、atomic rollback、画像共有、無変更write0、snapshot復元/最後の参照削除、private読取境界を追加。全142 tests成功38.790秒（/tmp/pb-pdf-images-verify.log）。その後、狭い永続analysis/pdf_import/pdf_analysis scopeを追加、関連7 tests成功1.954秒。一般CRUD/admin拒否。
- UIで13点の画像を1枚ずつ表示/保存する機能を追加。実画面でblob画像が既存img-srcポリシーに遮断されることを再現し、Addonモードのimg-srcだけblobを追加。サーバー管理WebのCSPは変更しない。関連13 tests成功3.040秒。実画像ブラウザ再試験中。
- 版を0.5.10へ整合、README/認証/OCR仕様を更新。新規ディスク書込みは原本/抽出版/画像BLOB・参照索引・import監査と最大32件のjob状態に必要。UIの表示/GETで新しい画像を再生成しない。次は実画像UI結果確認、最終verify/build、PR21 review/merge、公式更新/署名Feature更新、導入済み画面受入。本番DBへの指定PDFの登録も配布後に行う。

## PDF/OCR配布前の最終受入（2026-11-11）

- 最終verifyは143 tests成功39.690秒（/tmp/pb-pdf-0510-verify.log）。Linux・QPKG・Featureビルド成功。全diff/checkを確認。
- 実Hostブラウザ1280/320pxで、指定PDF15ページ・画像13点の新規取込、PNG表示/保存、原本SHA一致、320pxで取消が成功。横溢れ・JS例外ゼロ（.data/pdf-ui-browser.json、スクリーンショット）。回路図の実表示を目視確認。今回は画像受入のためLLM再実行を省略し、前回の実HostローカルLLM受入を維持。
- 一時fixtureを正常停止、一時addon/user/session/grantの除去を確認。本番の接続・文献DBはまだ変更していない。v0.5.10の公開・実更新・本番PDF取込は次の工程。

## v0.5.10実導入（2026-11-11・最新）

- PDF/OCR PR21をmain7fd0cdaへ統合、Release run42840942211成功。既存publisher鍵による署名Feature三資産も公開。マージ後のruntime/manifest差分なしを確認。
- 公式v0.5.8から管理API check/apply経由でv0.5.10への自動更新成功。session/CSRF/collection/旧版保持・更新後分析保存を確認（/tmp/pb-autoupdate-0510.json）。
- 本番Linux DBをオンラインbackup、quick_check成功。設定/秘密はpre-0.5.10へ保持。公式Linux archiveのSHAを検証し既存prefix/data/portを維持して0.5.8→0.5.10導入、秘密設定の一致を確認。
- ControlDeck正規Feature CLIで0.5.9→0.5.10更新、installed/enabled/managed=true・healthy。正規enable APIでfiles.pick/resources.acquireを含む7権限を承認。3ユーザーサービスはactive。
- 本番connection.jsonを作らず同一UID自動認証で、指定PDFを実Host Files pickerから正本DBへ保存。15ページ・13画像、PNG表示/保存・原本SHA一致、1280/320pxで横溢れ/JS例外ゼロ・320px取消が成功。ローカルLLM要約も保存成功（/tmp/pb-pdf-installed-browser.log）。未確認のOCR/分析結果を自動的に承認済みとはしない。
- URL: PatentBuddy https://souten-linux.tailc8e858.ts.net/x/patent-buddy/workspace / ResearchDataHub http://192.168.68.200:17871/ 。NAS自体は未更新・未移行。
- 請求項分析も保存成功。正本DBは文献1件・原本1件・画像参照13件・要約3775文字/請求項確認6510文字を保持、quick_check成功。15ページのうち直接抽出10、直接抽出+OCR5。OCR/AIの内容精度は人手未承認。請求項ブラウザ試験初回は既存要約の表示完了前の件数取得で誤判定したため、再生成せず「請求項の確認」の表示待ちに修正して成功（/tmp/pb-pdf-installed-claims-recheck.log）。
- 一時ユーザー/session/grantと試験ジョブ履歴を正常除去（remaining_jobs=0）。原本・抽出結果・分析は本番正本に保持。利用者は文献検索で「JPA」などから開ける。connection.jsonなし、同一UID自動認証を維持。
- docs-only追記の全verifyも143 tests成功39.361秒。古いガイド記載のtest_docs_rulesは存在せずimport失敗、実際のtest_updater_docs 7 testsと全verifyで検証した。PR-F/P2/PR-Gは未完了、全体goalはactive。

## PR-F 根拠付き関係データの基盤（2026-11-11・作業中）

- 前turnはprogress: PDF/OCR v0.5.10を公開/導入、指定PDFの保存と実Host LLM要約/請求項確認まで完了。今回もgoal active。最新main193f53aとopen PR10の実diffを確認し、旧chart_aiには行別引用検証はあるがHost Jobs・永続根拠の版/人手承認が不足していると判断。
- 新worktree `/data1tb/PatentBuddy-graph`、branch `feat/evidence-graph`、Draft PR23。`docs/evidence-graph.md`がPR-Fの作業契約。PR10はまだ未マージ。今回のサーバー基盤を旧サーバーLLM経路へ接続していない。
- graph_nodes/graph_edgesを単一正本DBに追加。引用範囲と原文revisionの一致、取得日時/抽出法/モデル版/信頼度、factual/inferredの固定区別、人手reviewを保存。原文・sourceまたは文献ノード変更でtriggerによりstale・承認失効、元へ戻しても復活なし。FK削除・rollback・snapshot復元を検証。
- 同じID同内容の再投入と探索はDB変更ゼロ。状態/承認/種別を含む隣接索引で出方向1〜2hop、seed20/ノード100/関係200以内。未承認・stale除外、推測は明示指定時のみ、上限はtruncated。API mutation/reviewは現在admin限定、private read可・published拒否。
- 関連5 tests成功5.369秒、全verify148 tests成功42.363秒（/tmp/pb-graph-tests2.log、/tmp/pb-graph-verify.log）。EXPLAINでadjacency索引利用を確認。GraphRAG実LLM、性能/索引write bytes測定、アドオンUI、scope付きproposal、逆方向探索、検索→vector→graph→rerank、クレームチャート/確認操作は未完。本番v0.5.10へ未反映、版変更/公開なし。
- 次はこの基盤をアドオンのHost Jobsと根拠付きクレームチャートへ接続する。PR-F完了後もP2汎用メタデータ検索とPR-G NAS移行を残す。現行データ/接続/サービスを維持する。

## PR23 クレームチャートのHost接続（2026-11-11・作業中）

- 前turnはprogress（根拠グラフ基盤99820cf push）。今回 `/data1tb/PatentBuddy-graph` のclean状態と実コードを確認して継続。claim_chart.py/chart_storage.pyを追加、AnalysisJobsにchart/claim_noを追加。
- 原文の請求項見出しと説明文境界を検証し、最大16行・行別3根拠・引用650字でbounded化。構成要件の欠落/重複/別行引用を原子的に拒否。正本saveでも原文/根拠revisionと文字範囲を検証。review/dependency表で根拠改変/削除の承認を不可逆失効。
- 既存Host Jobs・local_only推論・取消・再実行に接続し、請求項番号も再実行一致を検証。取得進捗は1Hz以下。検索はkeyword/rerank=falseを明示しサーバーLLMを呼ばない。最大3seedの2hop承認済みgraph候補も取得。vector/rerankは未実装として結果に明記し、代替済み/全体完成としない。
- 関連9 tests成功5.438秒、最終全verify152 tests成功44.949秒（/tmp/pb-chart-verify.log）。その後UIの確認状態文言と採用引用の明示だけを修正、Node構文チェックは追記後に実施。
- 実Host一時addon pb-chart-ui-acceptance/一時RDHを使い、合成請求項と対比文献でControlDeckの実ローカルLLM生成・保存・1280/320pxの引用表示DOM検証が成功、横溢れ/JSエラーなし（/tmp/pb-chart-ui-browser.log）。スクリーンショットは上部でチャート本体が画角外のため、チャートの目視受入とは呼ばない。fixtureをSIGINTで正常終了、一時addon/user/session/grants/DB除去を確認（/tmp/pb-chart-ui-fixture.log）。本番v0.5.10は不変。
- 次: vector/Host rerank接続、モデル版の保存、狭い提案/人手承認scopeとUI、関係管理UI/逆方向、実根拠の誤判定・取消/応答消失の復旧・性能I/O・配布受入を継続。PR10未マージ、PR23 Draft。P2汎用索引とPR-G NAS移行も未完。goal active。

## PR23 検索AI契約の追加（2026-11-11・作業中）

- 前turnはprogress（chart Host接続3c8c2ec push）。今回actual Host AI contractを確認するとtext/visionのみでembedding/rerankなし。Host所有権を維持するためControlDeck別worktree `/data1tb/ControlDeck-retrieval-ai` / `feat/addon-local-retrieval-ai` / Draft PR351 / 6e49086を追加した。現行live Hostファイルは変更していない。
- Host側 /ai/retrieval/capabilities と /execute はai.inference認可、ローカル登録GGUF役割・loopback確認、既存gateway lease/ensure_ready/releaseを使用。32入力/64KiB/応答4MiB/8192次元、有限数・行/index完全被覆、proxy/redirect拒否、切断時task cancelを検証。モデル名/pathを返さずfile metadata指紋model_refを返す（内容hashではない）。
- Host関連46 tests成功3.04秒。初回4failは既存disable HTTP409の誤期待・asyncテストplugin不存在。asyncio.runに修正、依存追加なし。frontend build19.08秒、初回全体1fail/1231passはbuild完了前に起動したSPA routeの404/405。build完了後の全1232 tests成功105.70秒/2skip。logs /tmp/pb-host-retrieval-tests2.log、*-build.log、*-full2.log。
- PatentBuddy HostSession.retrievalと応答契約を実装。古いHostへ本文を送る前に能力/ローカル方針/model_refを確認。返答の指紋・次元/行数・重複/欠落/非有限数を拒否。取消時にsocketを閉じる実HTTP試験を追加。全verify156 tests成功47.169秒（/tmp/pb-retrieval-client-verify.log）。生成/検索パイプラインへまだ接続していない。
- 実登録モデルはQwen3.8-27B LLMのみと確認。既存role-presets APIからBGE-M3（job04d5b26334e3）/Qwen3-Reranker-4B（job6a49ba113107）を通常導入中。前者は直近API succeeded、後者running。helperPID480692、exec26005、logs /tmp/pb-retrieval-model-install2.log/.err。初回helperがjob_id応答をidと誤読したが、作成済みjobをDBで特定して再投入せず監視を引継いだ。
- 導入済みrootは /data1tb/LLM、二つのpreset directory。既存モデルは変更しない。ダウンロード中のHost再起動を避ける。helper終了時は一時ユーザー/sessionを除去（進行中ならinactiveとして保持）し監査/jobsは保持する設計。成功/cleanupは次turnで実確認が必要。
- 次: 残りpreset導入の実handleを再確認→Host PR351最終review/mergeと既存dirty passkey変更を保持した限定反映→実retrieval APIと取消/モデル指紋確認→正本vector索引のscoped保存/版・モデル空間・再構築→keyword/vector/graph/rerank→人手review UI。文章生成のモデル版記録、性能/配布、P2/PR-Gも引き続き未完。本番PatentBuddy/RDHは0.5.10のまま、goal active。

## Host検索AIの実反映・ベクトル保存（2026-11-11・最新）

- 前turnはprogress（PB d017a12 / Host PR351 6e49086 push）。今回job/helper実PIDを確認して待機を継続し、BGE/Reranker両preset導入succeeded、一時user除去まで確認（/tmp/pb-retrieval-model-install2.log）。同じdownloadを再実行していない。
- Host PR351をmain8296974へmerge。live routerがpre-change5e1dde7とbyte一致、新retrieval_ai.pyが存在しないこと、active queued/running Jobsゼロを確認して当該2ファイルだけ反映。既存dirty passkey等の全ファイルhashを保持し、正規./deck.shで正常再起動（PID486674、/api/v1/health200）。restart後も既存変更hash不変。/api/healthを最初に誤指定して404だったが正規pathで確認済み。
- 実Host scoped API→HostSession.retrievalでBGEの2文/1024次元、Rerankerの2文/関連文上位が成功。execution_policy=local_only/model_ref確認。cold観測10.30秒/11.33秒、性能保証ではない。/tmp/pb-host-retrieval-live.log。一時addon/user/session除去、audit/Host Jobs履歴保持。
- 正本serverにhost_vector_spaces/host_vectorsを追加（旧vectorsを上書きしない）。最大8モデル空間/バッチ32/8192次元。chunk text SHAとdocument revisionを送信前後で検証して原子的保存、異なる結果上書き拒否、無変更再送write0。本文/source変更triggerとchunk FKで除去。専用embeddingと新research_analysis scope、独立同一UID qle_ credential/socketを追加。旧pdf_analysisには権限追加なし。
- pending readは最大32/cursor、space削除adminのみ。一般CRUD/admin/publicとのscope分離、無効数/float32 overflow/重複id・モデル分離・改変/削除・batchrollback・Unixsocket再起動失効を検証。関連8 tests成功3.463秒（その後embedding socket test追加）、全160 tests成功48.414秒（/tmp/pb-host-vector-verify.log）。diff末尾空行のみ全test後に修正。
- 実Hostの埋め込み2件を一時RDHへembedding tokenで保存し、再送unchanged2/DB変更0を確認。warm観測0.11秒（保存往復含む）/rerank1.79秒、synthetic2件のみ。/tmp/pb-host-vector-storage-live.log。実client→Host→model→canonical serverの結合成功。一時RDH/addon/user/sessionを除去、本番文献DB不変。
- 次はこの正本vectorのbounded検索/索引・再構築Host Jobsを実装し、keyword→vector→graph→rerankと画面へ接続。現在chart生成はkeyword/graphのみで、vector/rerank未実装表示を残している。推論モデル版保存/人手review UI/graph管理/性能I/O/配布も未完。PR23 Draft、本番PatentBuddy/RDHは0.5.10のまま。Host docsの実機前記録はPR351時点の履歴で、最新live結果は本節。P2/PR-Gを含めgoal active。

## ベクトルsnapshotと再構築可能cache（2026-11-11・最新）

- 前turnはprogress（1cf253d、実Host検索AI/正本vector保存まで確認）。今回最新worktree clean/HEADを確認して継続。
- 正本host_vector_versionsにepoch/generation/countを追加。既存モデル空間の不足行だけ初期化。vector変更と同一transactionのtriggerで識別子/件数更新、rollbackで戻る。manifest/page GET、同一vector再送は書込みなし。ページ128件/float32-le/base64、本文を転送しない。page前後のetag照合。
- vector_cache.pyはPCの0700 vector-cache配下に0600 SQLiteで再生成可能なvector/ID/revisionのみ保存。最大2GiB/100万件/完成2ファイル、一時ファイルで整合性・件数・最終manifestを検証してatomic replace。部分同期の公開禁止/取消・変更時のscratch除去。warm syncはmanifestのみ。検索は128行ずつのexact cosine/top-k heap、最大30秒、超過truncated。大量RAMロード・常時server全vector転送なし。ANNや大規模性能の合格とは扱わない。
- 関連7 tests成功4.162秒、全164 tests成功51.563秒（/tmp/pb-vector-cache-tests.log、/tmp/pb-vector-cache-verify.log）。snapshot途中変更の拒否、削除/rollback/epoch再生成、warm転送なし、private API、取消/time limit、cacheが本文を持たないことを確認。
- 実Hostの2GiB CPU/RAM leaseとlocal-only BGEを使い、2文を一時RDHへ保存→PCcache同期→query embedding→関連文上位を確認。warm syncはGET manifest1回のみ、cache20,480 bytes。/tmp/pb-vector-cache-live.log。一時addon/user/session/DB/cacheを除去、audit/Jobs履歴保持。これは2件の機能受入で、タイミングは性能保証ではない。
- 本番PatentBuddy/RDHは0.5.10のまま。PR23 Draft。次はEmbeddingJobs（全資料の版検証・小バッチ・取消/再開/Host CPU lease/Model ref保持）と構築ボタン、vector/graph/Host rerankへのchart接続。cacheの大規模物理I/O/CPU/RSS、source更新競合・応答消失の復旧、generation model provenance、人手承認UI、PR-F残、P2/PR-Gも未完、goal active。

## 索引構築workerと共通Host資源管理（2026-11-11）

- 前turnのOCR回答は状態確認のみでgoalのコード進捗なし。今回PR23で`ComputeHostSession`を抽出し、PDF既存権限を変えずCPU/RAM lease/heartbeat/release/進捗頻度制御を共有化。
- `embedding_build.build`: 全コーパスpendingのkeyset、32件/8192文字/UTF-8 64KiB分割、原文hash/版/model_ref/次元照合、保存済みを再計算しない再開、カーソル前の更新検出、取消/応答消失後の再開。PC本文DBやworker中間vectorファイルは追加しない。既存正本vector保存以外の永続書込みなし。
- 実HostのJob+CPU lease下でBGE-M3 2文/1024次元のworker構築成功、再実行DB更新0、cache検索関連文上位/再同期manifestのみ、Qwen3-Reranker実推論成功。`/tmp/pb-embedding-build-live.log`、err空。一時addon/user/session/DB/cacheは除去済み、Host Job/auditは保持。初回は日本語phaseがHostの英数字契約に反しHTTP422、修正して同試験成功。fixture `/tmp/pb-embedding-build-live.py` は終了済み。
- 次はこのworkerを製品EmbeddingJobsへ接続（所有者/取消/再開/heartbeat/再起動・terminal照合/CPU lease）、構築ボタンとvector→graph→rerank chart接続。worker単独の完成を画面機能の完成としない。推論モデル版/人手レビュー/大規模性能/PR-F残/P2/PR-Gは引き続き未完。本番0.5.10は不変、PR23 Draft、goal active。
- 最終全verify **169 tests成功51.036秒**（`/tmp/pb-embedding-build-verify-final.log`）。新增5 testsはUTF-8分割/無変更無推論・書込み0/取消再開/model変更・本文hash不正/カーソル前更新/commit応答消失後再開を確認。PDF lease回帰4 testsも成功。配布ビルド・リリースはPR23の残機能完成後。

## 索引構築の製品Jobs・画面接続（2026-11-11）

- 前turnはworker実装/実Host検証/8bf2efe pushのprogress。今回は`EmbeddingJobs`と`/addon/v1/embedding-jobs`、独立した構築・更新ボタン/取消/再開/Host照合/履歴除外を実装。全資料が対象で、選択文献に依存しない。owner分離、最大32件、同時実行1、未同期があれば先に照合。
- ComputeHostSessionのrequest/lease ID取得直後にメタデータを保存。再起動後はinterruptedとして資源解放→terminal照合。heartbeatはlease activate後に開始し、部分activate状態をrenewしない。モデルをジョブへ固定し、再開時モデル変更は拒否。書込みは資源/状態遷移・5秒ごとの小さな進捗だけ、本文/ベクトル/tokenはPCジョブJSONへ保存しない。
- 全verify **172 tests成功55.036秒**（`/tmp/pb-embedding-jobs-verify.log`）。その後HTTP認証・不正body/任意model/URL拒否の回帰を既存testへ追加し、関連12 tests成功3.032秒。JS構文成功。所有者越境/取消→Host失敗→照合→再開/モデル変更拒否/再起動資源照合/履歴除外後vector保持を検証。
- 実Host UI fixture `/tmp/pb-index-ui-fixture.py` で一時ResearchDataHub+research_analysis scopeを使用。1280pxで実BGEモデル2文/1024次元の索引構築、320pxで再実行0件、両方succeeded/host_sync_pending=false、横溢れ/JS例外0（`/tmp/pb-index-ui-browser.log`）。`.data/index-320.png`で構築ボタンの目視確認。完了ジョブはスクリーンショットの下方外なので状態はDOM/API検証と区別。
- fixture PID494273をSIGINTで正常cleanup、一時addon/user/session/grants/DBとsecret除去。末尾KeyboardInterruptは待機解除の終了で、cleanup完了行を確認。Host Job/auditは保持。本番の接続/DB/0.5.10は変更していない。
- 次はクレームチャートへkeyword→vector→bounded graph→Host rerankを接続する。exact chunk read API、CPU lease/cache利用、原文/model revisionの保存が必要。人手承認UI/graph提案権限・管理/生成モデル版/大量検索性能/PR-F残/P2/PR-Gは未完。PR23 Draft、goal active。

## チャート用のbounded候補検索（2026-11-11）

- 前turnはEmbeddingJobs/UI接続e9d6610 pushのprogress。今回は`evidence_read.py`のchunk evidence/文献range read APIと`chart_retrieval.py`を追加。650文字上限、原文位置と版、本文に一致しないsection除外、公開token拒否/GET書込み0。
- ChartRetrieval: keyword8→Host query embedding→cache上位8→keyword/vectorから最大3doc/20seed・2hop/20node/20edgeのapproved factual graph→Host reranker。各経路最大4/計12候補、最終3根拠。未索引/モデル変更/原文変更/取消は停止、黙示fallbackなし。traceにモデル版/索引etag/走査数・truncated/候補数を返す。生成UIへの接続はまだ行っていない。
- cache旧版清掃に4世代同期→完成cache2個だけ保持の回帰を追加。途中でregex不具合と誤認したが、実diffと通常文字列のescape解釈を再確認し既存実装が正しいことを確認。vector_cache.pyのコード変更はない。
- 実Host Job/CPU leaseでBGE-M3とQwen3-Rerankerを使用し、一時RDH2文→索引構築→新候補検索エンジン→関連文上位・引用2件・truncated=falseを確認（`/tmp/pb-chart-retrieval-live.log`、err空）。graphは実fixtureでは空、非空承認graph候補のrerankはAPI回帰テスト。fixture終了・一時addon/user/session/DB/cache除去済み、Host Job/audit保持。
- 次は`claim_chart.generate`を新エンジンへ切替、AnalysisJobsのchartだけComputeHostSessionとCPU lease/永続request・lease/終了前解放/再起動照合へ接続する。現chart.generateのnot_implemented表示はまだ正しいので維持。最終保存時のモデル/traceとgraph承認変更の扱い、人手レビューUI、生成モデル版、性能/配布、P2/PR-Gも未完。本番0.5.10不変、PR23 Draft、goal active。
- 最終全verify **177 tests成功55.941秒**（`/tmp/pb-chart-retrieval-verify-final.log`）。初回は「全文APIなし」テストの末尾一致判定がgraph/documents APIも誤って拾い1件失敗。正しい完全一致へ直し、モデル変更/取消停止の回帰も追加して最終全件成功。関連5 tests成功3.063秒。コードdiff確認済み、配布前の中間コミットとして保持。

## 全検索経路をチャート生成へ接続（2026-11-11）

- 前turnは候補検索エンジンea862f3 pushのprogress。今回`claim_chart.generate`をChartRetrievalへ切替し、旧not_implementedを除去。keyword→vector→approved factual graph→rerankと行別モデル/索引/打切りtraceを保存。LLM回答の全行/同一行引用・正本保存時の原文版/範囲照合は維持。
- AnalysisJobs chartのみComputeHostSession。request/lease即時保存、同時chart1件、heartbeatはCPUactivate後に開始、取消後/終了前にmonitor停止→資源解放→Host terminal照合。再起動はhost_sync_pendingとして保持し、未同期履歴の自動除去を禁止。新receipt APIはID/doc/kind/source_revisionだけ、保存POST応答消失/再起動時に重複生成せず保存済み結果を確認する。
- 書込み理由: チャートtraceは正本の根拠/モデル再現性、PCの資源IDとterminal確認状態は中断復旧に必要。本文/LLM回答/秘密をPCジョブJSONへ追加しない。通常分析もterminal一致確認時に小さなメタデータ更新1回を追加し、未同期状態を解消する。
- 全verify **180 tests成功58.249秒**（`/tmp/pb-chart-integration-verify.log`）、JS構文成功。追加ChartJobs3 testsで全pipeline/保存応答消失/取消・再開・再起動済み結果照合、CPU解放がterminalより先・永続leaseID・検索モデルtrace保存を確認。既存summary/claims回帰も成功。
- 実Host UI一時fixture `/tmp/pb-chart-full-ui-fixture.py` で、索引構築→実BGE-M3→Qwen3-Reranker→Qwen3.8-27Bローカル生成→3要件チャート保存が成功。1280/320pxで引用A-E1/B-E1・全検索経路表示、横溢れ/JS例外0（`/tmp/pb-chart-full-ui-browser.log`）。`.data/chart-full-320.png`はチャート本体を目視し、3要件/引用/未確認表示を確認。追加実ブラウザAPI照合でhost_sync_pending=false、lease/request=None、行別model trace保存を確認。
- 実fixtureのgraphは空、非空graph候補の検証は前turnのAPI回帰範囲。fixture PID500256はSIGINTで終了し、一時addon/user/session/grants/DB/secret除去済み（`/tmp/pb-chart-full-ui-fixture.log`）。本番0.5.10や接続/資料は変更なし。
- 次: 生成LLMのモデル版の確実な保存/Host attestation、graph承認変更・削除に対するチャート依存管理、人手レビューとgraph提案・管理UIを実装する。大量検索性能/物理I/O、配布更新受入、P2一般メタデータ、PR-G NAS最終移行までgoal active。PR23はDraftで未配布。
- 全verify後の変更は再照合後メッセージ/phaseの整合と案内文、receipt境界テスト。関連12 tests再成功、receipt含むchart5 tests成功2.931秒。receiptの未認証401/published403/本文なし・GET更新0を確認。最終HTML案内追加は文言のみ。

## グラフ承認変更に対するチャート依存管理（2026-11-11）

- 前turnは73eee43の全検索経路チャート/実Host UI成功のprogress。今回graph_revisionとanalysis_graph_dependencies、保存時graph snapshot検証、変更/削除時の不可逆stale/unreviewedを追加。同一review再送は版を変えず、取消→再承認は別版。引用していない探索端点の原文更新でもgraph stale経由でチャートを無効化。
- graph旧候補schemaは列追加/版付与をatomic transaction、再openで書換えなし。旧chart graph引用は初回のみ32件ずつ読み、本文を保持しstale化。移行markerで毎起動の全chart scanを避ける。追加書込み理由は承認版/依存索引と変更時失効。新Storeインストールはgraph→chart→vectorの順を維持。
- 全verify **187 tests成功61.999秒**（`/tmp/pb-chart-graph-deps-verify.log`）。追加6 testsで取消/再承認、関係削除、非引用の端点文献更新、snapshot欠落/偽造・原子的拒否、同一再送0更新、旧チャート本文保持/一度だけ移行、既存edge入り旧schema→版付与/reopen/quick_checkを確認。
- 実Host fixture `/tmp/pb-chart-graph-ui-fixture.py` で承認済みfactual edgeを作り、実BGE/Qwen3-reranker/Qwen3.8生成を通したchartを保存。graph依存1件、chartのテスト承認後にedge承認取消→stale/unreviewed、再承認後もstaleを確認（`/tmp/pb-chart-graph-ui-fixture.log`）。1280/320px生成・引用表示・全検索経路、横溢れ/JS例外0（`/tmp/pb-chart-graph-ui-browser.log`）。`.data/chart-graph-stale-320.png`で根拠変更表示と未確認・引用を目視、API stateと一致。
- 最初のfixture生成コマンドはcwd誤りでFileNotFoundErrorとなり起動前に停止。絶対pathへ修正して実行。途中の新表示文言テストは起動済みStaticCacheの旧JSを参照してtimeout、文言変更を本差分から外して既存根拠変更表示で再検証成功。状態変更の不具合ではない。
- fixture PID504352をSIGINTで終了し一時addon/user/session/grants/DB/secret除去を確認、Host jobs/audit保持。本番0.5.10は不変。remote main193f53aを再確認し、HANDOFF冒頭の旧作業branch表記を現PR23へ訂正。
- 次は生成LLMのmodel versionのHost attestationと保存、人手レビュー/graph提案・管理UI。検索traceの保存境界検証、graphの推測表示/逆方向要否、性能/物理I/O・配布更新、P2一般メタデータ、PR-G最終NAS移行は未完。goal active、PR23 Draft。

## 生成モデル版のHost API実装・実導入（2026-11-11）

- 前turnはgraph承認依存d84b63a pushのprogress。今回はHostの独立worktree `/data1tb/ControlDeck-generation-provenance`、branch `feat/addon-generation-provenance`、PR352を作成しmain **2c951d7**へ統合。実装commit2a828a4。Host本体のAGENTS/statusと実ai_gateway/llama/systemdを確認。
- 新要求 `require_provenance:true` はlocal_only必須/strict bool。capabilities.request_options.require_provenance.supported=true。complete応答のprovenance、stream正常終了直前の `{type:'provenance',provenance:{...}}` → done を追加。既定falseの既存呼出は互換。証明はexecution_policy=local_only、revision_kind=host_process_file_metadata_v1、model_ref/runtime_ref各SHA256 64hexだけ。
- Host helperは選択モデル/補助mmproj・draft/実行binaryのstat（path/dev/inode/size/mtime/ctime）を指紋化。admission/ensure_ready後にsystemd MainPID、同一UID、実exe/argvのmodel/alias/port/host、LISTEN所有者、ファイルがprocess開始後に変わっていないことを確認。推論後も同じmodel/runtime指紋の場合だけ証明を返す。変化/取消時はstreamに証明/doneを返さない。stat/process readはasyncio.to_thread。重み内容hashや完全な数値再現性の証明ではない。秘密/alias/path/PID/argvは応答しない。
- 関連61 tests成功3.29秒、frontend build17.98秒、全 **1253 passed/2 skipped/既存warning** 107.00秒（`/tmp/pb-provenance-host-full.log`）。補助draft被覆を追加後helper12 tests成功0.02秒。初回helper11 testsと既存API回帰、生成前/後差替え・strict opt-in・stream cancel/lease解放も確認。新CIや新依存なし。
- ライブHost `/data1tb/ControlDeck/app` はactive jobs=0、ai.pyが変更前main8296974とbyte一致を確認。新mainのai.py/generation_provenance.py **2ファイルだけ**反映し通常`./deck.sh`再起動、health200。既存dirty/untracked **21ファイル**はhashを前後照合し保持（`/tmp/pb-host-generation-preserved.json`、backup `/tmp/pb-host-ai-pre-generation.py`、restart log `/tmp/pb-host-generation-restart.log`）。ユーザーpasskey作業を維持。Host checkout自体は切替えていない。
- 実Host正規一時addon/Job/CPU leaseで実Qwen3.8生成、complete61文字とstream provenance→doneの両方を確認。helper前後のmodel_ref/runtime_refとも一致（`/tmp/pb-generation-provenance-api-live.log`、err空）。先行helper-only試験59文字は `/tmp/pb-generation-provenance-live.log`。一時addon/user/session削除、Host jobs/audit保持。全fixture終了済み。本番PatentBuddy/RDHは0.5.10のまま。
- Host実機受入文書の追加commit b40989cをpushしdocs-only follow-up PRを作成。Host `.venv`/frontend/node_modules symlink、生成tsbuildinfoはstageしない。旧worktree `/data1tb/ControlDeck-retrieval-ai` のdirtyも不変。
- **次の実装:** PB `/data1tb/PatentBuddy-graph` のHostSession.streamにopt-inを追加。要求前にcapabilities対応確認、provenance eventのpolicy/kind/64hex/重複・欠落・done順を厳密検証し、欠落時は原文を送らない/結果を保存しない。chart.generateから要求し、実際に生成した場合だけ検証済み生成版を正本chart JSONへ保存（候補なしでLLM未実行なら明示）。旧schemaの保存/閲覧互換と新schemaの検証を検討。既存HostSession/summary/claimsを暗黙に壊さない。Host新APIはすでに実導入済みなので再反映/再起動不要。
- その後、人手レビュー/graph提案・管理UI、検索trace保存境界の検証、性能/配布、P2/PR-Gを続ける。goal active。
