# K1d — ControlDeck Host知識抽出・知識カード統合（2026-11-17）

状態: **Draft PR #32**。依存はPR #31→#30→#29。全体verify・実モデル/ブラウザ・配布検証は**未実施**。コードを書いた段階で本番完成とは扱わない。

## 実コードで確認した契約
- [ControlDeckのHost AI](https://github.com/souten-yd/ControlDeck/blob/main/backend/app/addon_runtime/ai.py) はlocal_only＋require_provenanceをサポート。ストリームはprovenanceイベント→doneを返す。
- [ControlDeckのモデル証跡](https://github.com/souten-yd/ControlDeck/blob/main/backend/app/models_mgmt/generation_provenance.py) はrevision_kind=host_process_file_metadata_v1、model_ref/runtime_refのopaque指紋。**モデル重み全文のハッシュではなく、ファイルメタデータ・ローカルプロセスの連続性を確認する契約**。PID/秘密/パスは公開しない。
- [EmbeddedAddonView](https://github.com/souten-yd/ControlDeck/blob/main/frontend/src/features/addons/EmbeddedAddonView.tsx) のthemeはtoken_version=1.0、color_scheme/accent/bg/surface/text/border/muted/motion_reducedを含む。PatentBuddyのCSS変数をHost Bridgeの通知へ追従させ、グローバルナビ/認証/ヘッダーを重複させない。
- Draft PR #23のgeneration_contract.pyを**同じ内容で再利用**し、HostSession.stream(require_provenance=True)に最小機能を移植。**PR #23全体（GraphRAG等）を取り込んだわけではない**。後の統合時は共通diffを解消する。

## 実装フロー
1. ControlDeck PatentBuddy画面で文献を選択。分析内容の初期値は「知識エッセンスを抽出」で、1つの主操作ボタンから明示開始。従来の要約/請求項確認は選択肢として残す。
2. POST /addon/v1/jobs (kind=knowledge)。既存AnalysisJobsの所有者検証、同時実行枠、cancel/reconcile/履歴を再利用。**本文取得より前**にHost local_onlyかつrequire_provenance対応とResearchDataHub専用knowledge_propose資格を確認。非対応Hostや無資格なら503、本文送信0件。Cloud/legacy fallbackなし。
3. 既存RDH read権限で文献のbody+revisionを取得、Host detached JobでControlDeckローカルAIにだけ投入。K1bのknowledge_generationがモデル応答JSONを解析し、原文に一意に存在するquoteのUnicode位置とHost側generation_provenanceを検証。結果はmodel_inference/unreviewedだけ。
4. K1cのPOST /api/v1/documents/{did}/knowledge-proposalsへ専用tokenで送る。RDH正本SQLiteの同一transaction内でdoc revision/quoteを再検証し、document_analyses(kind=knowledge)へimmutable保存。冪等再送はwrite0、古い版/ID衝突は409。AIによるapprovalやGraph edge追加なし。
5. Host Job terminal/reconcileで完了し、保存済み候補をGET /addon/v1/documents/{did}/knowledge-proposals（別のread token）で取得。カードには課題/原理/効果、未確認・stale、quote、成立条件、限界を表示。原文への移動ではPythonコードポイントとJS UTF-16の差をArray.from(body)で吸収し、再照合してからtext node+markで強調。引用をinnerHTMLに渡さない。
6. 失敗/取消/再実行、Host状態の照合、再接続導線は既存JobsとControlDeckのUIパターンを踏襲。保存開始後の取消はimmutable結果を消さない既存の境界規則を維持。

## Scope / Allowed
- qnaplibrary/generation_contract.py: PR #23の証跡検証関数
- qnaplibrary/addon_host.py: 生成版証跡の事前確認、SSE取得とfail closed。既存stream(messages)は互換。
- qnaplibrary/addon_client.py: RDH専用write資格の事前確認
- qnaplibrary/addon_jobs.py: 既存Jobへkind=knowledge、K1b生成→K1c保存を追加
- qnaplibrary/server.py: 認証済みread APIのadd-on proxyルートのみ。K1cからのwrite-only token/GET拒否を維持
- qnaplibrary/web/addon-workspace.html/css/js: ControlDeck theme token、44px、320px、単一主操作、候補/出典カード、stale/error表示
- tests/test_knowledge_host_provenance.py、tests/test_knowledge_host_jobs.py、tests/test_knowledge_workspace.py: Host証跡・実SQLiteによるジョブ保存/取消・UI契約の回帰テストコードを追加

## 実施した確認と未実施
- **実施**: ControlDeck/PB現行mainおよびPR #23・#29〜#32の実ファイル/差分を比較。ControlDeckのAIストリームと証跡形式が一致することを確認。K1dのJavaScriptをV8で構文検証しPASS。addon-workspace.htmlとJSのID参照は欠落0/重複0。Host theme、Unicode照合、textContent、44px、モバイル表示、Host shell非重複を静的に検査。
- **未実施**: K1dの3つのPythonテストファイル、K1a〜K1cと既存全テスト、scripts/verify.sh、Linux/QPKG build、実ControlDeckモデル・実RDH API・iPhone/QNAP実動作、性能/ディスクI/O検証。実行環境からgithub.comのDNS解決ができずrepo checkout不可。追加したテストコードを**合格済みと表示しない**。
- **依存**: PR #23（GraphRAG/Host証跡の大型Draft）は未マージ、PR #29/#30/#31/#32もDraft。今後PR #23の重複Host改変を実diffで整理する。手元のControlDeck Hostにはcapabilityが存在するが、実モデル/環境で証跡が成立するか未試験。
- **既知のUX不足**: Obsidian型Knowledge Map・人間review/承認は未実装。遠隔RDHでは独立knowledge_server_tokenの設定が必要な場合があり、完全なゼロ設定導線は別工程で改善する。Embedded ViewのControlDeckテーマ対応は追加済みだが、Safari/縮小表示E2Eは未実施。

## マージ前受入と次のCodex指示
- Python tests: python3 -m unittest -v tests.test_knowledge_essence tests.test_knowledge_generation tests.test_knowledge_store tests.test_knowledge_host_provenance tests.test_knowledge_host_jobs tests.test_knowledge_workspace
- JavaScript: node --check qnaplibrary/web/addon-workspace.js
- 全体: bash scripts/verify.sh、bash scripts/build-linux.sh dist。Host+RDHの本番同等環境で合成文献を登録→ユーザー明示抽出→Host local_only/proof→immutable保存→GET原文ジャンプまで通し、cancel、capability不足、引用不一致、原文改訂race、409、無変更write0、token scopeを検証。
- 旧analysis/rw/published tokenの知識POSTは403。新knowledge_propose tokenは**専用POSTだけ許可**し、RDH文献/コレクションのGETは403。管理者セッションはCSRF/Origin必須。
- **Do NOT**: cloud/private-leak/自動承認・自動出願・自律実行、別DB、Graphの新正本、Vue default化、ui.html default変更、runtime level_0_manual_only緩和、raw source serving、redirect/CDN、server起動npm build、shell=Trueなどの追加。
- **Expected final state K1d**: 文献を選択してControlDeckのローカルAIから根拠付き未確認の知識候補を生成し、RDHへ保存・ControlDeck準拠カードで閲覧できる。法律判断・fact認定・人間approval・GraphRAG登録は行わない。
- **Next K2**: versioned human review、approve/reject/差戻し、stale承認復活防止を既存RDH正本/限定権限に実装。AI推論のhuman approvalはsource factへの自動昇格ではない。
- **Next K3**: PR #23 GraphRAGと統合したbounded 1〜2hop Knowledge Map、出典/インスペクタ、320px代替リスト、ControlDeck Jobs/Offline UX。GraphRAGがmainにない間に重複graph/schemaを追加しない。
- release: 全体verify合格・リリース版3点整合→PRマージ→公開Release→Linux/QNAP更新後health確認。現在はDraftのまま。
