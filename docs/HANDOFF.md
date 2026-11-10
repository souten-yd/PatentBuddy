# HANDOFF — ResearchDataHub / PatentBuddy

更新: 2026-11-10。`AGENTS.md` → `DEVELOPMENT_WORKFLOW.md` → 本書 → `docs/CODEX_NEXT.md` の順に確認する。計画の正本は `researchdatahub-plan.md`、性能受入は `researchdatahub-performance.md`。

## 現在地

- Repo: `souten-yd/PatentBuddy`。最新公開 **v0.5.4**、main `b7816cf`。
- 作業ブランチ **feat/scale-document-ingestion-pagination**、Draft **PR #13 / PR-D**。PR-C #15はマージ・v0.5.4公開・自動更新確認済み。
- ユーザー目標は計画全体の完了。**PR-D〜G、QNAP実機は未完了**。勝手にPR-Cだけを全体完了としない。
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
3. PR-E #14: ControlDeck/MediaForge/SonicForge最新mainの実契約を再読しHost権限/Jobs/Broker/Feature/署名/UIを結合。PC側に別正本文献DBを作らない。まだ未着手。
4. PR-F #10等: 確定/推測エッジ分離、根拠・版・人手承認、bounded GraphRAG、ローカルLLMのみ。まだ未着手。
5. PR-G: **最後**にPC→QNAPのdry-run/backup/hash/quick_check/件数/秘密・認証確認/停止・単一書込み切替/ロールバック。QNAP既存領域の上書き・削除禁止。未着手。

QNAP TS-253Be/iPhone実署名・TLS実環境、公的API実キー、Host署名/publisher登録、NAS HDD性能、実案件の法的品質・審査状態は未検証。過去詳細はgit履歴と各Release/PR参照。goalはactive。

## PR-D P0/P1 作業中（2026-11-10追記）

- `scripts/bench_datahub.py`: temp合成DBの認証HTTP APIを計測。API分位点・docs/s・MiB/s・CPU/RSS・SQL execute/fetch時間・total_changes・DB/WAL/SHM・proc I/O・device counters・dbstat容量・backup/Store再open/復元・検索一致を記録。schedulerは開始しない。device countersは他プロセスの活動を含むため専有I/Oとは呼ばない。サービスプロセス再起動時間は別途必要。
- baseline 10万件+900秒idle→candidate同条件を直列実行中。**exec session57856**、shell PID65806、baseline Python PID66329（この時点で生存を確認）。ログ `/tmp/rdh-{baseline,candidate}-100000.log`、最終JSON `.data/bench/{baseline,candidate}-100000.json`。再開時はハンドル/psを再確認し、観測timeoutだけで再実行しない。
- スケール回帰8 tests: 並行batch整合、途中例外の全体rollback、cursor途中削除、コミット直前の子プロセスkill→WAL復旧/再送を追加。source訂正がunchangedとして捨てられる失敗を再現・修正。本文がある文献の明示sections変更/順序もdigestへ含める。通常文献の既存digestは維持し全件再構築を避ける。
- 現時点のControlDeck LLM: 前回の8097 listener/llama-serverは今回存在しない。既存の成功記録は履歴として保持するが今回実行したと扱わない。Host管理経由の現在のruntime選択をPR-E結合時に確認する。直接モデルを勝手に起動していない。
