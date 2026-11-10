# HANDOFF — ResearchDataHub / PatentBuddy

更新: 2026-11-10。`AGENTS.md` → `DEVELOPMENT_WORKFLOW.md` → 本書 → `docs/CODEX_NEXT.md` の順に確認する。計画の正本は `researchdatahub-plan.md`、性能受入は `researchdatahub-performance.md`。

## 現在地

- Repo: `souten-yd/PatentBuddy`。最新公開 **v0.5.7**、main `11c500b`。
- 作業ブランチ **feat/patentbuddy-host-ai-jobs**。PR #13 / PR-Dはマージ・公開・更新済み。PR-C #15はマージ・v0.5.4公開・自動更新確認済み。
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
