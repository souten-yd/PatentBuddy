# HANDOFF — ResearchDataHub / PatentBuddy

更新: 2026-11-10。`AGENTS.md` → `DEVELOPMENT_WORKFLOW.md` → 本書 → `docs/CODEX_NEXT.md` の順に確認する。計画の正本は `researchdatahub-plan.md`、性能受入は `researchdatahub-performance.md`。

## 現在地

- Repo: `souten-yd/PatentBuddy`。最新公開 **v0.5.4**、main `b7816cf`。
- 現在は **feat/control-deck-addon-foundation** / PR #14、v0.5.5候補。PR-C #15は公開済み。PR-D #13は別worktreeで計測中。
- ユーザー目標は計画全体の完了。**PR-D〜G、QNAP実機は未完了**。勝手にPR-Cだけを全体完了としない。
- 内部package `qnaplibrary`、QPKG ID `QnapLibrary`、port17871、Cookie/パスキーRP ID、Release資産名を維持する。ResearchDataHubは唯一の正本、PatentBuddyはPC上のControlDeck Add-on。SQLiteをSMB/NFSで共有・同時二重書込みしない。
- 未公開情報は検証済みローカルLLMのみ。既存privacy gateを弱めない。NAS↔PCの認証/TLS通信とクラウドLLM送信は区別する。

## 完了した実装単位

| 計画 | 状態・証拠 |
|---|---|
| 設計 #16 | main統合済み `24cb084`、docs-only |
| PR-A #17 | v0.5.2公開、main `4170acd`、release run42809839947成功。薄いLinux入口・doctor/serve/test・Web/health表示・配布互換。61 tests、非root Linux導入、QPKGのLinux展開start/status/health/stop。QTS実機ではない |
| PR-B #11 | v0.5.3公開、main `b14ed77`、run42810849292成功。ハッシュのみセッション永続化/最大128件、通常GETと期限切れ参照はRAMのみ。再起動Cookie/CSRF/パスキー登録・RP ID・ログアウト/パスワード変更失効を検証。67 testsと配布/更新確認 |

旧公開v0.5.1の更新確認は改名前Repo名によるURL不一致で失敗することを再現。初回は手動更新が必要。公開v0.5.3をSHA-256照合し非rootで手動更新、管理者/コレクション保持、配布4 smoke tests成功。**修正済みv0.5.3から次版への自動更新をv0.5.4公開後に検証する。**

PR-Bでは未読POST本文が次のHTTP/1.1要求に混ざり501になることを実HTTPで再現・修正。一般リトライなし。iPhoneの実パスキー署名やQTS独自の別原因は未検証。rdh.shのcwd別checkout誤読も修正。

## PR-C — 公開資料API（現在の作業）

- 既存Draft #15をmain v0.5.3へ統合し実diffをレビュー。
- 管理者専用の送信プレビューにタイトル/公開番号/抜粋を全表示。10分有効の署名tokenが文献版・全表示項目に結び付く。変更/期限切れ/再起動なら再確認。抜粋の無断切詰め/正規化なし。プレビューは永続書込みなし。
- 原文更新で承認を無効化。本文を元へ戻しても再承認まで停止。原文削除時は公開snapshotとFTS索引を削除。
- `published` tokenは専用検索/取得route以外を全件403。private資料/MCP/debug/export/settings不可。管理Cookie併用でも昇格しない。LAN pairingで発行不可。loopback以外はTLS必須、遠隔からのX-Forwarded-Proto偽装を拒否。
- 公開API **14 tests合格**。プレビュー競合/期限/再起動、失効、TLS条件、CSRF/Origin、全private route遮断、FTS代替経路、原文削除、型不正、通常検索のDB更新0を確認。
- 実TLS: 一時証明書を検証するHTTPSクライアントで承認→専用token取得→公開本文のみ取得、MCP403。`/tmp/pb-public-tls.py`。
- 実Chrome: 1280/390pxでプレビュー全項目→入力変更で無効化→同意/承認→公開用tokenで抜粋だけ取得・private403。横溢れ/JSエラー/外部リクエスト0。証拠 `.data/acceptance/pr-c/browser.json` / `preview-*.png`（合成データのみ）。`/tmp/pb-public-ui.cjs`。一時サーバーは停止済み。
- 最終verify **81 tests合格**（20.088秒、`/tmp/pb-verify-054.log`）。Linux/QPKGビルド・payload検査合格（`/tmp/pb-build-*-054.log`）。PR全diffを確認。マージ、v0.5.4公開、自動更新はこれから。
- 書込み追加理由: 承認snapshot/FTS/監査、原文改変時の不可逆な承認停止、削除時の索引清掃が必要。検索の常駐書込みは増やさない。認証last_seenは既存ポリシー。

## ユーザー指定PDF / ControlDeck LLM検証

- ダウンロード済みPDFを実解析。成果物 `/home/souten/ダウンロード/JPA-2026116114-analysis/report.html` と同名zip。元PDFを変更せずSHA-256再照合。本文15頁、請求項14（独立1/14）、段落64、図11。表紙だけOCR+目視。原文・図・回答はGitに入れていない。
- ControlDeck管理llama.cpp（loopback8097、Qwen3.8-27BローカルGGUF、mmproj）で全文要約/請求項整理70.60秒、整合性60.80秒、図6画像11.55秒。従属関係14/14一致。回答の逆表現・自己参照接続などは原文で検証して訂正/除外、原回答を保存。実行品質を法的品質や全自動正確性と混同しない。
- 実資料の一時API取込: 本文往復一致、70チャンク、3検索語ヒット、請求項14件。実資料は本番/公開APIへ自動登録していない。HTMLはChrome1280/390pxで図11/請求項14、横溢れ/画像欠損/JSエラー0。
- 合成案件の再現スクリプト: `PYTHONPATH=. python3 scripts/test-local-llm.py --verified-local`。既存モデルを利用しロード/アンロードしない。初回合格42.58秒/1137文字、案件変更なし。

## 次の一手 / 未完了

1. PR-C最終検証→v0.5.4公開→旧v0.5.3から管理API自己更新・再起動/セッション・データ保持を確認。
2. PR-D #13: 実diffと性能仕様に沿ってP0計測から着手。1千/1万/10万、P50/P95/P99、CPU/RSS、物理I/O/DB/WAL、15分idle、再起動/復元を変更前後比較。無変更書込み0、一覧本文なし、カーソルを検証。100万件対応は未実測。
3. PR-E #14: ControlDeck/MediaForge/SonicForge最新mainの実契約を再読しHost権限/Jobs/Broker/Feature/署名/UIを結合。PC側に別正本文献DBを作らない。まだ未着手。
4. PR-F #10等: 確定/推測エッジ分離、根拠・版・人手承認、bounded GraphRAG、ローカルLLMのみ。まだ未着手。
5. PR-G: **最後**にPC→QNAPのdry-run/backup/hash/quick_check/件数/秘密・認証確認/停止・単一書込み切替/ロールバック。QNAP既存領域の上書き・削除禁止。未着手。

QNAP TS-253Be/iPhone実署名・TLS実環境、公的API実キー、Host署名/publisher登録、NAS HDD性能、実案件の法的品質・審査状態は未検証。過去詳細はgit履歴と各Release/PR参照。goalはactive。

## PR-E / ユーザー指定の実導入（2026-11-10）

- 最新要求: PatentBuddyをControlDeckに導入して操作可能にし、ResearchDataHubをLinuxサービスとして導入。テスト/開発利用も許可。これに合わせPR-Eの操作可能なプレビュー導入を優先するが、計画全体の完了条件は縮めない。
- ResearchDataHub公式v0.5.4をSHA検証後 `/data1tb/ResearchDataHub/app` / `data` に非root導入。systemd user `qnaplibrary` active。Webは http://192.168.68.200:17871/ / http://100.82.8.44:17871/。初回管理者設定はユーザー向けに残し、NASデータは変更していない。
- このworktree `/data1tb/PatentBuddy-addon`、PR #14。main v0.5.4をmergeし、Host introspection→scope検証→ResearchDataHub検索/取得を追加。文献DBを作らない。workspaceはbridge nonceを使い、アドオン/サーバー役割・各version・URLを表示。
- connection.jsonはFeature data内の0600ファイル（server_url/server_token）。defaultはloopback17871、遠隔HTTPは禁止。HostURLはloopback8765。初期接続設定はまだ未完。AI/Host Jobs/GraphRAGはこのプレビューには未実装。
- ControlDeck側 `/data1tb/ControlDeck-patentbuddy-feature` の `feat/patentbuddy-option` でtrusted catalog entryを準備。既存SonicForge publisherの公開鍵を再利用し、新規鍵生成なし。署名・公開・実installは未実施。稼働Hostのユーザー作業を変更していない。
- v0.5.5候補でbundle identity統一。addon/API/境界/配布12 tests成功。全verify/Host release-bundle tests実行中、実ブラウザ/署名/導入/更新はこれから。
- PR-D計測は別worktree `/data1tb/PatentBuddy` のsession57856が継続。candidate PID119637で10万件+900秒idle中。PR-D全93 tests成功、まだ未release。こちらのブランチを切り替えて測定中コードを変えない。

- 最終全verify93 tests成功（22.189秒）、Linux/QPKGビルド・payload検査成功。Hostのrelease-bundle20 tests成功。既存publisher鍵でv0.5.5 Featureを署名・自己検証し、Hostの実_load_packageとtrusted public keyで署名/能力/identity検証成功。新しい鍵は生成していない。Host登録PRは https://github.com/souten-yd/ControlDeck/pull/348 （Draft）。
- ResearchDataHub初期管理者設定はユーザーにより完了したことをhealthで確認。パスワードを読んだり変更していない。アドオン接続の読み取りtokenは未設定、ユーザーにファイル保存/画面入力の希望を非同期確認中。

- iframeのX-Frame-OptionsをアドオンモードのみSAMEORIGINへ変更し、standaloneサーバーはDENYを維持。Host proxyがXFOを引き継ぐ実コードを確認して修正。最終verify93 tests成功22.424秒、全配布物再build/署名済み。
- Chrome 1280/390/320pxで、合成Host proxy+実Addon+実ResearchDataHub APIを通してbridge handshake→接続状態→検索→本文表示を確認。横溢れ/JSエラー0、`.data/addon-ui.json`/screenshots。これは稼働ControlDeckの実ブラウザ受入ではなく、その受入は導入後に行う。
