# Codexへの引き継ぎ — ResearchDataHub / PatentBuddy

更新: 2026-11-10。**この文書は実装指示であり、既に完成した機能ではない。**

## 開始時に必ず読む
1. `AGENTS.md`、`DEVELOPMENT_WORKFLOW.md`、`docs/HANDOFF.md`
2. `docs/researchdatahub-plan.md`（**最新の役割・データの正本に関する決定**）
   - **最優先のストレージ性能/低I/O受入契約:** `docs/researchdatahub-performance.md`。特許・規格・汎用DBすべてに適用する。
3. `docs/privacy-boundary.md`、`docs/patent-feature-plan.md`
4. ControlDeck本体 `souten-yd/ControlDeck` と `souten-yd/ControlDeckMediaForge`、`souten-yd/ControlDeckSonicForge` の**最新mainの実コード**。Addon v2 manifest, Host RBAC/introspection, Bridge, Feature bundleの仕様を必ず再読する。
5. 進行PR #10 / #11 / #13 / #14 / #15 のdiffと競合状態（PR本文だけでなく実ファイル）。PR #12はmainへマージ済みのセキュリティ基準。

## 名前の使い分け（混同しない）
- **ResearchDataHub**: 特許以外にも規格・論文・技術資料・研究データを保管/収集/検索/整理する**汎用サーバー**。Linux PC（現在の開発先）→ 完成後QNAP NAS（本番の主データ保存サーバー）。REST/MCPと出典・改版・権限管理の責任を持つ。
- **PatentBuddy**: ControlDeck PC上の**特許専用Add-on**。高度検索、ローカルLLM、クレームチャート、調査Jobs、GraphRAGはここで行う。将来、別の規格向けアドオンもResearchDataHub APIを使える。
- 既存リポジトリ名 `QnapPatentBuddy`、Pythonパッケージ `qnaplibrary`、QPKG ID `QnapLibrary`、旧データ領域、port 17871は**互換性維持**。Codexが一括rename/移管することを禁止。改名はユーザー向け表示と新Linux aliasから開始する。リポジトリ分割・改名は別途設計/許可。

## 配置とデータフロー
```text
開発/結合試験:
 Linux PC (Ryzen 9700X, ControlDeck, local LLM)
   ResearchDataHub 127.0.0.1:17871 -> PC SSDの唯一の正本
   PatentBuddy Add-on 127.0.0.1:9150 -> Host scoped API経由でResearchDataHubを利用
   LLM / OCR / embedding / bounded GraphRAG -> PCの計算資源
 本番移行後:
 NAS ResearchDataHub -> NASローカルファイルシステム上の唯一の正本
 PC PatentBuddy + ControlDeck -> 認証付きHTTPS/Tailscaleを経由してNAS APIを利用
 PCのQdrant/ベクトル索引 -> 再構築可能なキャッシュのみ
```
SMB/NFS経由で稼働中SQLite/WALを直接開かない。PCとNASで同じデータを**同時に正本として書き換えない**。切替はスナップショット、hash/quick_check/件数/スキーマ/秘密設定確認、停止、検証後の単一書込み開始、ロールバック計画を必須にする。

## 機密境界（誤解してはならない）
- 未公開発明、未公開請求項、アイデア、内部調査記録は**ローカルLLM以外のLLMに入力しない**。
- 認証済みのNAS⇔PCデータ転送やローカルLLMへの処理は許可する。これらを「外部への送信」と一括で禁止しない。
- ローカルLLMはクラウドへ中継しないことを検証する。localhostだから安全と断定しない。PR #12/mainのサーバ側exit gateを**維持**し緩めない。
- OpenRouter等の外部LLMは、公的資料等の許諾確認済み・管理者の明示承認済み部分だけを利用し、機密プロンプト・メタデータ・検索履歴の転送を禁止する。単に`kind=patent`等で「公開」と推定しない。外部AI連携でトークンやNASのURLをLLM本文へ渡さない。
- PR #15は **public-only専用APIのDraft**。正本のprivate資料、管理者のCSRF、device-tokenと独立して、検索/取得の前に承認済みの抜粋だけ返すことを証明する。**外部LLM送信機能は含まない**。承認済み文献でも改変後は停止。標準/規格の再配布権限にも配慮。

## Codexが次に進める順序

### PR-A: Linux PC用ResearchDataHubの起動入口と表示の互換移行（最優先）
**Scope**: ResearchDataHubという汎用名称へのUI/health表示変更、`python3 -m researchdatahub`の薄い入口、`rdh.sh doctor|serve|test`、Linux配布物への同梱、最低限の単体/プロセス起動テスト。すべて旧`qnaplibrary.server.main`を使い、二重コード・二重DBを作らない。QPKG表示名は段階移行として可能だが内部IDは固定。
**Allowed**: 新しい小規模CLI/branding/配布manifest/テストとdocsを変更。既存serverの動作ロジックを直接コピーしない。
**Do NOT**: `qnaplibrary`のimport path変更、QPKG ID変更、DB schema変更、初期管理アカウント再生成、UIをVue default化、認証/更新/検索runtime semantics変更、シークレットの表示、rootや起動時npm build、無条件データ移動、既存Release artifact名変更。
**Expected final state**: LinuxユーザーでResearchDataHubと旧`qnaplibrary`どちらの起動入口でも**同じデータディレクトリを明示したときだけ**同一DBを使用できる。PCの開発データはQNAPのQPKGデータと独立。旧ユーザーのパスキーとログイン方法を保持。
**Verification**: `bash scripts/verify.sh`, `bash scripts/build-linux.sh dist`、Linux実起動、`/api/health`、管理者ログイン、パスキーRP_ID/設定の回帰、旧ランチャーとの互換性、QPKG smoke。追加で安全grep/manifest検査。

### PR-B: 認証/セッション不具合（既存PR #11を最新mainへ整合）
- iPhone Face IDパスキーはSQLite上の登録レコードとHTTPS RP IDの一致を保持。アップグレードで消える不具合を実ファイル/データパス/マイグレーションで検証。
- セッションは設定された期間（既定約30日を検討）保持。**Bearer cookie平文は保存しない**、ハッシュだけ持続、期限切れ・ログアウト・管理者パスワード変更では失効。
- 更新確認501は単純な一般リトライで誤魔化さず、API/再起動・proxyとの関係、idempotency、UIに処理中を出す。既存の外部送信ガードを緩めない。

### PR-C: 公開資料API（既存PR #15を再検証し組込み）
- 管理者の文書単位/抜粋単位の承認、ソースハッシュ変更時の自動無効化、公開専用scoped token、TLS制約、限度付キーワード検索。
- public tokenが元文献・案件・秘密・未公開請求項・MCP・デバッグ/エクスポートを一切読めないことをテスト。
- 非公開資料のテキストはOpenRouterの要求本文にもログにも混入しない。タイトル/公開番号/抜粋を**送信プレビュー**で全部確認できるようにする。自動クラウド送信なし。

### PR-D: 大規模取り込み/検索（既存PR #13を再検証）
- **まず `docs/researchdatahub-performance.md` を読む。** 保存容量、物理ディスクI/O、大量APIのレイテンシ、復旧可能性を同時評価する。PR #13はDraftのためmainへの統合前にdiff/回帰テストを再評価する。
- 外部IDの一括照合、内容ハッシュの冪等再投入、無変更の書込0、本文を取得しない一覧、Keyset/カーソルページングを完成させる。
- 特許以外の規格識別子/改版/日付、出典とライセンスのメタデータも検索できる一般化を設計。新しいデータ収集元は公式API・RSS・許可済みサイトのみ。
- 1千/1万/10万文献でP50/P95/P99・スループット・CPU/RSS・DB/WAL/SHM増分・物理デバイスread/write bytes・アイドル15分のI/O・再起動と復元を変更前後で実測。全件RAMロード・無制限索引・WAL/同期/監査の無効化をしない。性能を数値で保証するのは基準値を取得してから。

### PR-E: ControlDeck Add-onの安全なHost結合（既存PR #14を更新）
- `addon.json` v2、Feature bundle、署名/認証/health、Host introspectionの権限分離、Cookieに頼らないsandbox UI、iPhone幅での動作。
- **PR #14の古い設計を優先しない**。`docs/researchdatahub-plan.md`が正。PatentBuddy A0の起動では別の文献正本SQLiteを作らず、ResearchDataHubのscope付きAPI接続だけを許可する。
- MediaForge/SonicForge最新mainとControlDeck contract v2の差分を読み、本体のHost認証・Jobs・GPU Brokerを契約に沿って使う。現状#14 A0はUI/LLM未接続、完成と呼ばない。
- PatentBuddyが必要とするprivate文献を「外部AI公開済み」の権限に誤って変換しない。

### PR-F: 特許ドメイン/GraphRAG（既存PR #10など）
- 確定エッジ: 文献引用、特許ファミリー、優先権、出願人、IPC/CPC、クレーム要件。出典ID/テキスト範囲/取得日時/版/抽出法を保持。
- 推定エッジ: 課題・解決手段・効果・置換可能性。根拠/信頼度/モデル版/人間の確認状態を持ち、確定エッジへ自動昇格させない。
- キーワード→vector/ANN→1〜2hop bounded graph expansion→rerankの順。全件関連付け・無限探索・自動的な特許性/侵害の確定はしない。
- CPU/VRAM/GPUリース/ジョブ中断や再開をHostで管理し、外部LLMへ未公開情報が送られないことをテスト。

### PR-G: Linux PC → QNAP本番移行（**最後**）
- 開発用PC DBの一貫snapshotと原本ファイル、設定、秘密、認証・パスキー、監査ログを含め移行項目のチェックリストを確定。
- dry-run・ハッシュ・quick_check・データ件数/数件サンプル照合、バックアップ復元試験。QNAP上の旧QPKGデータは削除・上書きしない（衝突時は別領域/マージ設計を提示）。
- PC側の書込み停止、NASを唯一の正本に昇格、ControlDeckのNAS URLをHTTPSに切替、読み書き/索引再構築・性能を確認。戻し手順を明文化。

## 開発ルール・リリース
- 既存の`main`を読む → 既存PR diff・Do NOT・expected final stateを確認 → 作業ブランチ＋早期Draft PR → 最小スコープ実装 → 関連docs/manifest/testsを同時更新。
- 完全な`bash scripts/verify.sh`、Linux/QPKGビルドと単体/API/権限境界・実機テストを実施し、そのログと**未実施の工程**をPR本文・HANDOFFに書く。ユーザーから「確認して」と言われたらmergedだけでなく**main実ファイルと差分・安全な制約**を検査する。
- docs-only PRはRelease不要。アプリバージョンを変更するPRは既存の3箇所を一致させ、`release.yml`経由で公開。CIトリガー追加や勝手な署名鍵生成は禁止。
- 1PRの変更が膨大にならないよう、関連する少量修正は次の実装PRへ同梱。互換性/セキュリティ変更が広い場合だけ追加PRに分割。
- QNAP/ControlDeck実機の検証なしに、完成・高速・秘密漏洩なしと主張しない。

## 現在の実装状態（重要）
- `main` 最新公開済みは v0.5.1。PR #12のクラウドLLM機密防壁はmainに入っている。
- PR #10、#11、#13、#14、#15 はDraftで未マージ。これらのコードは**mainにない**。
- PR #16 は議論を確定した**文書だけのチェックポイント**。Linux用のResearchDataHub aliasなどは次の実装PRで作る。現時点で新ブランドのLinuxバイナリや稼働サービスを配布したと主張しない。


### 2026-11-10 PR-A進捗
PR #16の設計はmainへ統合済み。PR #17でLinux別名入口・doctor/serve/test・health/Web表示・配布同梱を実装し、61 tests、Linux配布/非rootインストール、QPKGのLinux上smoke、ControlDeckローカルLLMの合成案件assistを検証。リリース/更新は検証待ち、PR-B〜GとQNAP実機は未完了。詳細はHANDOFF。上記の「未実装」は設計チェックポイント時点の記録。

## 次期実装契約 — Knowledge Graph / Essence Reuse（2026-11-17）

**正式な設計書**: [knowledge-graph-plan.md](knowledge-graph-plan.md)（K0〜K6の優先順位）および [knowledge-graph-design.md](knowledge-graph-design.md)（データ/保存/検索/API/UI/品質/安全の受入契約）。既存PR #23（GraphRAG根拠版・チャート）はDraft・未マージとみなし、最初に**最新mainとPR実diff/保存テーブル/Host API**の両方を確認する。先行のPR #24（公報取得）や旧PR #10（クレームチャート）と機能重複を調査する。

**Scope:** Source/Evidence→Knowledge（課題・原因・原理・メカニズム・構成・効果・成立条件・限界）→Ideaの三層で、公報/論文/規格/社内PDFからエッセンスをローカルAIで抽出し、根拠付きカードへ保存、Obsidian様の型付き関連マップへ接続し、過去知識を別発明で検索・選択・再利用する。採用した派生案は先行技術と再比較する。

**Allowed:** ResearchDataHubの既存単一正本とGraphRAGの最小後方互換拡張、限定scoped API、ControlDeck Host local-only AI/Jobs/lease、レビュー/版失効/検索/モバイルUI、必要なテスト/文書。Knowledgeの抽出案と承認済み事実、Ideaの仮説を分離。source hash+revision+span+引用完全一致を維持し、古い根拠をstaleにする。

**Do NOT:** 別の知識グラフ正本・PC永続マスター、外部LLMに発明/Knowledge/検索履歴を送信、推論の事実化、類義語のみの自動merge、人手承認の自動上書き、無制限Graph全件描画、自由入力の公開検索APIへの無断送信、実案件の特許性/非侵害の自動確定、自動出願/公開、QPKG/認証/既存API互換変更、CIトリガー追加、Vue default化、runtime `level_0_manual_only`・`ui.html` default・backend authoritative・no executionの破壊、raw source serving/fallback/redirect/startup npm build。

**Expected final state:** ①ある文献から引用/版に根拠づく構造化原理カードを採取できる、②同義・類似候補の差異と条件を見て人が統合・拒否できる、③ノードからPDF/段落に戻れるグラフを操作できる、④後続の別案件で知識を発見し、派生案の採用・版・由来・再評価を保存できる、⑤原文更新時の関連知識はstaleになり承認が自動復活しない。

**PR分割:** K0はPR #23受入と整合レビュー。K1：抽出+根拠proposal → K2：正規化・review・stale → K3：カードと部分マップUI → K4：異分野探索/適用条件 → K5：Idea Canvas・発明案再調査 → K6：スケール/QNAP移行受入。各PRは一つのまとまった目的に限定し、少量の既存不整合は次のPRに同梱。**新設計をPR #23へ丸ごと追加しない**。

**Verification:** main docs/manifest/tests/runtime実確認、各PRのscope/Do NOT/expected最終状態、根拠偽造・版不一致・private流出・出典の無い効果・誤統合・取消・重複/応答喪失・検索打切り・再起動の陰性テスト、batches/物理I/O/P50/P95/P99/RSS・15分idle、Host実local-only・320px画面。必ず bash scripts/verify.sh、ビルド/安全grepと実施できなかった工程をPR/HANDOFFに記録する。

**この文書更新はdocs-only**。ここに書かれたroute/table/UI/自動実行機能はまだ存在せず、Releaseは不要。

## K1a進捗とControlDeck UX遵守（2026-11-17）

- [ControlDeck準拠UI/UX契約](controldeck-ux-contract.md)がPatentBuddyのKnowledge Map/Card/Idea Canvasに**必須**。ControlDeckの実mainのUIガイド、Addon UXガイド、PageHeader、共通UI部品、CSSトークン、mobile-layout/Bridgeを再確認。Hostシェルを二重に作らない。
- K1aのPR #29: `qnaplibrary/knowledge_essence.py` と `tests/test_knowledge_essence.py` は、厳格な引用検証とunreviewedな知識候補だけを扱う**pure code**。抽出AI起動・永続DB/API・知識マップはまだ実装しない。
- 隔離した同一ソースのunittest10件成功。GitHubに登録したソース2ファイルのblob SHAも一致。**全verify/Host実ブラウザ/配布は未実施、Draft PRは未マージ**。K1bではPR #23の実branchと最新mainの差分、relation_proposals/generation_contract等の重複箇所を読み、共通化と安全なHost Job連携から始める。
- UI実装はControlDeckのボタン1画面1主操作、44px、progressive disclosure、Host-owned nav、dark/light/accent、320px、error/reconnect/cancelを受入契約に含める。

## K1b実装済・K1c接続指示（2026-11-17）

- [K1b→K1cの実装ガイド](knowledge-k1b-integration.md)を**現時点の次工程の指示**として参照。K1a PR #29（strict proposal validation）に依存するK1b Draft PR #30を作成した。K1bは `qnaplibrary/knowledge_generation.py`（Hostの `stream(require_provenance=True)` が必須、JSON parse、原文のユニーク引用完全一致、provenanceをHostからのみ取得）と `tests/test_knowledge_generation.py`（11件）を追加。
- **実施済み**: isolated testsでK1a 10件+K1b 11件=計21件PASS、compileall成功。GitHubの4ファイルのblob SHAとローカル実行ファイルの一致を検証。**未実施**: repo全体の `bash scripts/verify.sh`、実Host、ResearchDataHubへの保存、graph/card/UI、Linux/QPKG build。cloneがDNSで利用できないため。全体検証完了まではDraftのまま。
- K1cでは**最新mainとDraft PR #23の実コードを直接照合**する。PR #23はHost generation provenanceとrelations/graphを既に試作しており、そこで検証契約を共通化して別のHost処理や別グラフ正本を作らない。既存AnalysisJobs/Storeに単純に `kind=knowledge` を加えてread-only/published/既存analysisトークンの権限を意図せず拡張しない。新しいscoped permissionが必要なら明示設計する。原文照合を保存transaction内で再検証し、型・根拠・版・漏洩・冪等・取消をテスト。
- UIは [ControlDeck準拠UI/UX契約](controldeck-ux-contract.md)が必須で、Host-owned shell/nav、one primary action、Jobの進捗/取消、テーマ、320pxレイアウトを守る。Vue default化/ui.html default変更等のDo NOTは従来通り。

## K1c実装・K1d接続指示（2026-11-17）

- K1c [PR #31](https://github.com/souten-yd/PatentBuddy/pull/31) はK1b PR #30をbaseとしたDraft。**専用スコープつきknowledge proposal保存APIは実装済みだが、Host JobやUIには未接続**。次工程は [K1c保存・K1d接続契約](knowledge-k1c-storage.md) に従う。
- 新規 `qnaplibrary/knowledge_store.py`: 同一SQLite transactionでdocument revision/hash+Unicode exact quote+Host local_only証跡形式をK1a validatorで再検証、`document_analyses(kind='knowledge')`にimmutable save。再送のwrite0、異なるcontent同IDや古いrevisionは409、approveやGraph登録はしない。GETは20件上限、staleはrevision comparison、読み取りロック、無変更write0。
- `qnaplibrary/auth.py` / `local_auth.py` / `server.py` / `api.py` / `addon_client.py` に専用`knowledge_propose` token・同UID UDS・POST/GET routes・リモート専用`knowledge_server_token`を追加。既存`analysis`/`rw`/`pdf_analysis`/`published`トークンで知識POSTを許可しない。通常解析保存のscopeは従来通り。
- `tests/test_knowledge_store.py` は実LiveServer/実UDS/全scope/原文改訂/悪意ある引用/不正証跡/冪等/AddonClient送信先を確認する回帰テストを**追加済みだが未実行**。GitHub blob SHAと照合済みのK1c保存モジュールをisolated SQLite mockへロードした6件はPASS。full `scripts/verify.sh`未実行（repo clone不可）、実API/JOB/E2E未検証。full検証前にmerge/releaseしない。
- **K1d** はPR #23をレビュー/整合してからHost `stream(require_provenance=True)` と既存 `AnalysisJobs` のkind=knowledgeを繋ぐ。開始前のHost capability検証、local_only・proof、cancel/resume/terminal receipt、source-race→409、scoped remote tokenの実運用、Host-owned ControlDeck theme/navigation/Jobs/320px/cardをテスト。無断API拡張・自動採用・cloud fallback・default UI変更なし。

## K1d実装・次のK2/K3指示（2026-11-17）

- 現在 [Draft PR #32](https://github.com/souten-yd/PatentBuddy/pull/32) (base #31→#30→#29)。新しい [K1d実装・検証・次工程契約](knowledge-k1d-implementation.md)を優先して読む。**本番未完成・Python全体テスト未実行**。
- Implemented: HostSessionのlocal_only/require_provenance（PR #23の限定移植）、knowledge生成前capability確認、専用token preflight、既存AnalysisJobsでkind=knowledge、K1cのimmutable storage POST、既存readスコープでの知識GET proxy、ControlDeck Host theme/文献の知識抽出ボタン/未確認staleカード/正しいUnicode引用ジャンプ。
- K1c専用writer tokenを**POST knowledge-proposalsだけに制限**してprivate GETの誤許可を修正。旧analysis/rw tokenは新規POST不可。K1dのHost streamは旧summary/claims向けには従来呼出に互換で、cloud fallbackは不可。
- Scope/Allowed: 既存PB addon_host/addon_jobs/addon_client/server/webと純粋generation_contract、追加テストのみ。Do NOT: GraphRAGの独立schema/DB/Host能力/新CDN/自動review/別LLM/cloud leak/execution/mutation系拡張、Vue default/UI default変更、server起動npm build。Expected final state: ユーザー明示で根拠付き未確認知識抽出→RDHに保存→ControlDeck準拠UIで版/引用/stale確認まで。
- **Required next check**: PR #32のmain比だけでなく、stacked PR #29/#30/#31と先行PR #23の実diff、mainのdocs/manifest/Host runtime/API/testsを読む。Python tests.test_knowledge_essence, tests.test_knowledge_generation, tests.test_knowledge_store, tests.test_knowledge_host_provenance, tests.test_knowledge_host_jobs, tests.test_knowledge_workspace、node --check qnaplibrary/web/addon-workspace.js、bash scripts/verify.sh、bash scripts/build-linux.sh dist、RDH実API+Host local-only/require_provenance実ジョブ+モバイルUI E2E。テストは未実行でありPASS済みと扱わない。
- 事前停止（旧Host/保存資格なし）、prompt injection、原文引用偽造、Host model/version drift、cancel/timeout、文献改訂race→409、zero write再送、writer tokenのGET403、old rw/analysisのPOST403、No raw-source/redirect、新旧UI default、ControlDeck theme/Job実動作、iPhone 320pxを必ず検証。少量の修正は本PRまたは次のK2に同梱し、不要な追加PRを作らない。
- K2: 人間のレビュー権限と不変バージョン記録・stale propagation・approve/reject/差戻し。AI推論は承認後も事実へ自動昇格しない。K3: 既存GraphRAGを使う1〜2hopのKnowledge Map＋出典ドロワー＋320px代替一覧。先行PR #23のGraph/証跡を二重実装しない。
- マージ/リリースは必須verifyとbuild成功後、PR依存順にmerge、その後Version/QPKG/CHANGELOG3点整合で正式Release、QNAP/Linuxの起動/health/更新確認まで行う。

## K2実装とK3のGraphRAG/Knowledge Map指示（2026-11-17）

- 現在の最新stackは[Draft PR #33](https://github.com/souten-yd/PatentBuddy/pull/33)（base PR #32→#31→#30→#29）。[K2詳細設計・テストと次のK3](knowledge-k2-human-review.md)を優先。**Python全体テスト未実施、実モデル/実ブラウザ未検証、公開リリースなし**。
- 実装済（未マージ）: 同一SQLiteのappend-only`knowledge_reviews`、専用`knowledge_review`認証・同UIDソケット、`POST knowledge-proposals/{pid}/reviews`、read-only bounded履歴、`knowledge_store.list_for_document`の項目別最新判断/失効overlay、ControlDeck準拠の明示レビューUI/最新状態表示。レビューの承認はAIの`model_inference`を`source_fact`に昇格させない。旧approvalは文献版変更で必ず失効し、自動再承認しない。
- **Scope/Allowed**: `qnaplibrary/knowledge_reviews.py`新規、`store.py`への加算DDL、認証/api/server/addon_client/knowledge_storeとweb/workspace UIの限定変更、K2専用テスト、docs更新。**Do NOT**: 新DB、GraphRAG自動エッジ、モデルのクラウドfallback、raw source/redirect/実行capability/自主mutation、自動承認/出願、Vue default化、ui.html default変更、npm build at startup、HostのAI runtime semantics変更。
- **今回実施した確認**: K2 JSのV8構文PASS、HTML ID参照欠落/重複0、reviewのSQLite最新seqクエリは独立環境で正動作。**未実施のため合格と主張不可**: 実LiveServerを含む`tests.test_knowledge_reviews`/`tests.test_knowledge_review_workspace`、K1a〜K1d回帰、`bash scripts/verify.sh`、`bash scripts/build-linux.sh dist`、iOS/実Host/RDH/API E2E。
- PR #33の完全checkout後、認証境界（admin CSRF/Origin、review POST以外のwriter token全403、pairingはscope rw/roのみ、local peer creds別）、モデル生成後の人間review（原文改訂タイミング、Unicode quote、旧判断失効）、同一request idのzero writes、誤タップ防止、レビュー履歴最大30件、DB CASCADE削除・復元、非公開文書漏洩0を検証。性能は物理read/write bytes、SQLite WALとidle readsで比較。修正少量なら同一PRにまとめる。
- **K3実装**: 先行Draft PR #23の`evidence_graph.py`と`chart_storage.py`およびHost証跡との実差分/機能境界を最新mainと照合してから再利用し、独自の重複graph API/DBを作らない。RDHはauthoritative、ControlDeck Hostは表示とローカル推論。人間が承認したモデル推論をsource factと誤認せず、GraphRAG既定検索へunreviewed/stale/単純AI推論を流さない。必要な独立認定ステップが未実装なら探索デモはread-onlyに留める。
- **K3 UI/UX**: 既存ControlDeck design/theme/Bridge/Host nav/PageHeader/Job、44px、320px single-paneを踏襲。PCでは選択ノードから1〜2hop上限付きmap＋右Inspector＋出典PDF/段落へ移動、モバイルでは一覧→Card→Evidence。可視range/reason、status、truncated上限、offline/error/retry、keyboard/ScreenReaderをテスト。全件描画や外部CDN/Graph engine追加なし。
- **Expected final state K2**: 人が判断を明示し、その署名されていない装置単位の審査記録が永続し、原文版で失効・復活しない。**Expected final state K3**: 出典つき技術エッセンスとレビュー結果を、ControlDeck内部で安全・制限付きに探索できる。完全な個人認証署名は今後専用Host contractが必要。
- Merge/release: 実コード/PR diff/manifest/docs/tests/runtime/全verify/安全grepを確認→依存順PR merge→3か所のversion整合を持つrelease PRとActions成功→Linux/QNAP更新後health/実機確認。途中のDraftを勝手に完成済みと扱わない。

## K3実装・K3b/K4の詳細指示（2026-11-17）

- 最新K3は[Draft PR #34](https://github.com/souten-yd/PatentBuddy/pull/34)（stacked base #33→#32→#31→#30→#29）。[K3 Knowledge Map実装/受入設計](knowledge-k3-map.md)を優先。**main/製品はまだK1a〜K3のDraft実装を含まない**。GraphRAGの大規模PR #23は古いbaseを持つ別Draftであり、k3の`evidence_graph.py`とK1dの`generation_contract.py`が重複するため衝突整理必須。
- K3 scope: PR #23のgraph schema/triggersを同一SQLiteへ選択採用、read-only`knowledge_map.read`、bounded authenticated RDH GETとaddon Bridge GET、ControlDeck responsive map/inspector/list、出典へのUnicode quoteリンク、JS/SQLite tests。先行K2 PR #33の`knowledge_review_epochs`修正でhash revertでも旧承認が復活しないようにし、K3 mapもreview epochに従う。
- K3の既定フィルタは`review_status=approved, source_revision+epoch=current`のK2 AIエッセンス（**basisはmodel_inferenceのまま**）とPR #23`approved,stale=0,basis=factual`辺のみ。source→essenceは`provenance_only`、推論から事実/法的結論/技術因果へ自動昇格させない。include_unreviewedは人がチェックした場合だけ参考表示。GraphRAG inferred edgeはまだ不可。
- Limits: 1〜2hop、全体36 nodes/52 edges、GraphRAG24/36、knowledge snapshots20。SQLite GET write0、全文の遅延読取、graph quoteのUnicode substr再照合、truncatedと読み込み失敗の明示。PCのマップ＋右Inspector、320px一覧→カードの代替、ControlDeck Bridge theme/token、44px/reduced motion、文献リンク/Job後更新、No external assets。
- **Required next**: PR #34 branchの完全checkoutで`python3 -m unittest -v tests.test_knowledge_map tests.test_knowledge_map_workspace tests.test_knowledge_reviews`とK1a〜K2の全回帰、`node --check qnaplibrary/web/addon-workspace.js`、`bash scripts/verify.sh`、`bash scripts/build-linux.sh dist`を実行。実LiveServer/admin/ro/published/knowledge_propose/review auth、GraphRAG factual/inferred/stale、source revision/epoch/revert、409、Unicode emoji, 2hop/limits/truncated、GET write0を検証。docs/manifest/tests/runtimeの実状態照合、safety grep、ControlDeck実ブラウザ320/390/768/1280+iOSを確認し、失敗は同PRか次工程にまとめる。
- **Do NOT**: 実行capability、クラウドへの未公開文献送信、推論/採用の無断mutation、モデル候補の自動Graph登録、独立DB・raw source endpoint・redirect/fallback・Vue default化・ui.html default変更・サーバー起動npm build・新CDN。backend authoritativeとHost level_0_manual_only/no executionを維持。
- **Next K3b**: PR #23 relation_proposals/evidence_graph.save/chart_storage/Graph APIを最新mainと比較・重複除去して、安全な明示レビュー＋根拠照合の技術関係登録UI/権限を追加（AI inferをfactualに昇格しない）。**Next K4**: 承認済みエッセンスを条件/機構/効果で再利用検索し、関連特許の差異と新しい仮説を出典付きで比較。Ideaは明示採用/後続検証、Graphは1〜2hop制限。
- **Expected final state K3**: 文献から出発し、承認済みAIエッセンス/根拠付きfactual GraphRAG辺の関係と引用/失効を閲覧できる。未確認は参考表示のみ。現在はDraftで、merge/releaseなし。

## K3b実装・次K4に向けたCodex指示（2026-11-17）

- 最新は[Draft PR #35](https://github.com/souten-yd/PatentBuddy/pull/35)、base PR #34→#33→#32→#31→#30→#29。詳細仕様と必須テストは [K3b明示関係登録設計](knowledge-k3b-links.md)。PR #23 GraphRAG全体は未マージ。**現在のmain/正式版にはK1a〜K3bは未導入**。
- 今回: `knowledge_links.py`、既存graph_edgesの内部transaction連携、同一SQLiteのknowledge_link_origins（source revision/epoch/K2 latest review seq）、K2人間承認済みの引用と対象文献版を確認する狭い登録POSTと別のreview POST。既定はbasis=inferred、review_status=unreviewed。承認後もinferred。K2 latestレビューが変わった場合は以前の仮説リンクの承認が復活しない。K3 Mapでinclude_links=trueの場合だけ、人がレビューした仮説を表示する。
- 明示認証: 独立`knowledge_link` scope（qle_ UDS / 遠隔knowledge_link_token）の2POSTだけ許可。他のread/rw/analysis/knowledge_propose/knowledge_review/publishedに権限追加しない。Target pickerは`GET /link-target`で本文なしのid/title/revisionのみ。ControlDeck iframeにはauth tokenを渡さずpermission boolだけ。
- UI: 元K2根拠カードからの選択、別文献検索・対象版チェック、仮説種別、2個の明示確認（未承認登録と別の人間承認/却下）、ステータス文字と取消・エラーの出口。モバイル320px単列/44pxタップ/16px入力、Host theme/ナビ/Jobsを再利用。SVGは既存K3だけ、仮説は点線で既定非表示。
- テストコードはtests/test_knowledge_links.pyとtest_knowledge_link_workspace.py。**Python実行していないのでPASSとしない**。独立SQLite smokeのFK/revert/review seq/Unicode/cascadeとV8 JS構文/DOM IDはPASS。
- **必須の次アクション**：PR #35を正規のrepo checkoutで`python3 -m unittest -v tests.test_knowledge_links tests.test_knowledge_link_workspace tests.test_knowledge_map tests.test_knowledge_reviews`とK1a〜K3の全回帰、`node --check qnaplibrary/web/addon-workspace.js`、`bash scripts/verify.sh`、`bash scripts/build-linux.sh dist`。各routeのauth scope/CSRF/Origin、K2承認→撤回→再承認、原文rev revert/target edit/Graph edge stale、link id retry zero write、同一transaction rollback、graph_revision 409、quote一致、source/target指紋、Graph inferred/factual filter、80/320px画面、ControlDeck Host bridge、iPhone Safari、QNAP Linux運用とSQL WAL/I/Oを実測。失敗や小修正は同PR・次K4 PRへまとめる。
- **Do NOT**: PR #23と重複する別graph正本、AI自動登録・無断mutation、自動承認/factual認定/特許性確定、未公開文献のcloud leak、Host runtime/execution capability変更、Vue default化、ui.html default変更、raw source/redirect/fallback、新CDN、server startup npm build禁止。許可されたmutationはこのK3bで人が明示確認した2つの狭いGraphRAG操作だけ。
- **K4実装**: K2承認済み・現行source revision+epochの知識候補を、機構・課題・条件・効果から複数文献横断で探す。まずRDH既存SQLite FTS/read APIを再利用、read-only bounded結果、secretのクラウド送信なし。比較はAI/human hypothesisと事実を分け、出典quote/限界と根拠トレースを持たせる。2〜3件の解決原理比較→K5 Idea Canvasで明示採用。ControlDeck UX統一。
- **Expected K3b**: 人が引用と関係先を確認した仮説だけ未承認登録→別操作で審査でき、GraphRAG全体/既定事実探索を汚染しない。リンクは現行K2承認/版/seqと結合し、失効・撤回・再承認で古い判断を復活させない。Draftのため正式機能完了ではない。

## K4実装とK5 Idea Canvasの詳細Codex指示（2026-11-17）

- 最新実装は[Draft PR #36](https://github.com/souten-yd/PatentBuddy/pull/36)（base #35→#34→#33→#32→#31→#30→#29）。K4は[全詳細設計/検証とK5へ引き継ぐ仕様](knowledge-k4-cross-search.md)。**main/正式版ではまだ使用できず、テスト・マージ・リリース未実施**。
- K4 new `knowledge_cross_search.py`: 現行K2 `approved + source_revision + source_epoch`、K1a`validate`でsource quote/Host local_only証跡を再照合。検索は**SQLで先に最大241 raw reviewイベントに制限**し、1レスポンス240走査/20結果、`next_cursor`による明示的続き取得。文献本文/JSON読取上限、最小DB I/O、キャッシュ/新FTSなし。比較は異文献2〜3件、`conditions/limitations`の完全一致のみ（AI意味判断なし）。
- K4 API：`POST /api/v1/knowledge/search`と`/compare`は**read-only body JSON**（検索語をURLに入れない）、既存read scopeだけ。ControlDeck proxyはHost認証後に既存read tokenだけで接続。公開専用やwriter tokenでは403。add-on UIは通常文献未選択時にも使え、K4カード・選択・ページ分割・比較・引用へのcode-pointジャンプ・320px縦表示/Host theme/44px/16px。
- K4には新規`tests/test_knowledge_cross_search.py`・`tests/test_knowledge_cross_workspace.py`を追加したが、Python本体実行は未実施。独立SQLiteキーセットpagination/latest approval SQLとV8 JS syntax/DOM IDはPASS、これは実LiveServer合格ではない。Actions CI workflow runなし、コンテナはgithub.com DNS不通。
- **先にテストを実行・修正**：`python3 -m unittest -v tests.test_knowledge_cross_search tests.test_knowledge_cross_workspace tests.test_knowledge_links tests.test_knowledge_map tests.test_knowledge_reviews`、K1a〜K3b全回帰、`bash scripts/verify.sh`、`node --check qnaplibrary/web/addon-workspace.js`、`bash scripts/build-linux.sh dist`。SQLite EXPLAIN/240 raw events以下の実走査保証、大量reject/古いapproval、pagination重複なし、同一本文への原文revert、K2 review撤回→再承認、scope matrix/CSRF/Origin/Cloud無し、source quote/emoji codepoint、比較候補2〜3異文献、GET/POST DB writes0、iPhone 320/390・desktop画面、Graph/Host負荷を確認。失敗があればPR #36にまとめる。
- **K5 Scope/Allowed**: 人間がK4で2〜3件を比較し、「アイデアの仮説」を明示編集・明示保存できるIdea Canvas。各根拠にはdoc/proposal/item/revision/review epoch/sequence/quoteを持たせる。保存正本はRDH既存SQLiteの加算schema、専用`idea_write`スコープ、CSRF/Originとユーザー明示操作・書込最小化。未確認/失効と承認済みモデル推論を混同しない。原文・K2 review・Graph relation改訂で`needs_revalidation`、自動再承認禁止。
- **K5 Do NOT**: ユーザー操作なしにAIがアイデア作成/保存/実行、自動出願、特許性/進歩性/侵害の法的結論、未公開発明の外部LLM/クラウド流出、raw source serving/redirect/fallback、Vue default化/`ui.html` default変更、ControlDeck Host runtime `level_0_manual_only`/no execution変更、server startup npm build・別ベクトルDB/新GraphEngine/CDNは禁止。OpenRouterは未公開請求項には使わず、任意の補助推論も**ControlDeck local-only/provenance**必須。
- **Expected K4**: RDHを読み取り専用で横断検索し、承認済み知識を根拠付きで2〜3文献並列比較し、元文献へ戻れる。完全一致以上の意味判断なし。**Expected K5**: 根拠が後から再検証できる、人間主導のIdea Canvas draft。検索・比較・Ideaは権限と書込を分離。
- PR運用: PR #23の旧GraphRAGは実mainと再diff照合し二重schema/Host証跡を避ける。PR #29→#36全stackを実checkout/Allowed/Do NOT/manifest/docs/tests/runtime/safety grepで確認後、依存順にreview/merge。マイルストーン達成時だけVERSION/QPKG/addon manifestを一致させLinux/QNAP正式Release、実機healthとiPhone Safariを確認。小修正は極力次1PRに同梱する。

## K5実装とK6統合検証・低I/O指示（2026-11-18）

- 最新は[Draft PR #37](https://github.com/souten-yd/PatentBuddy/pull/37)（K4 #36上にstack）。[K5実装・テスト表・K6指示全文](knowledge-k5-idea-canvas.md)を正とする。K4 compareに`review_seq/source_epoch`を追加し、K5ではK2人間承認済み原文2〜3件を同一DB transaction内で再検証して**人間が明示確認した場合だけIdeaを保存**。本番mainはまだ未導入。
- K5: `idea_drafts/idea_versions/idea_sources`のみ既存SQLiteに追加。source doc/proposal/item/revision/epoch/latest review seq/quote/offsetを永続証跡。源文献を変更後元へ戻す・レビュー撤回→再承認・元文献削除後も`needs_revalidation`、歴史保持、自動復活/自動採用なし。初期版・編集履歴はappend-only。same request retry・unchanged textはwrite0、版競合やstaleをHTTP409。
- Idea専用scope`idea_write`（`qlj_` UDS/遠隔idea_write_token）でPOST/PUTのみ、書込tokenでGETなし。既存read/ro/rw/review/link等へ権限拡張しない。Host Bridgeの認証済みproxy、CSRF/Origin/default UI/level_0_manual_only/no executionを維持。過去版GETはread-only。
- ControlDeck K4比較→K5の出典カード・ユーザー入力・明示チェック/保存→最近の案と版履歴。失効は再抽出・再比較まで編集不可。Mobile 320px、44px touch/16px入力/テキスト引用のXSS安全/Hostテーマ。AI自動アイデア・クラウド・Graph自動link/出願は禁止。
- **次Codex最優先**：実リポジトリcheckoutで`python3 -m unittest -v tests.test_idea_canvas tests.test_idea_workspace tests.test_knowledge_cross_search tests.test_knowledge_cross_workspace tests.test_knowledge_links tests.test_knowledge_map tests.test_knowledge_reviews`＋全K1a〜K4の回帰、`node --check qnaplibrary/web/addon-workspace.js`, `bash scripts/verify.sh`, `bash scripts/build-linux.sh dist`。SQLite FK/transaction rollback/creation idempotency/409/CSRF/source revert/reapproval/deletion/history保持/total_changesとWAL、GraphRAG・UI/manifest/デフォルト、QNAP/Ubuntu/iOSを検証。不足は**本PR #37へまとめて修正**し、無駄な追加PRは避ける。
- PR #23の古いGraphRAG一式との重複`evidence_graph.py`/`generation_contract.py`を実差分で確認。#29→#30→#31→#32→#33→#34→#35→#36→#37依存順にmain実ファイル/docs/manifest/tests/runtime/Allowed/Do NOT/expected stateを検査し、全合格後に順次merge。正式ReleaseはVERSION（qnaplibrary/__init__.py）・QPKG_VER（qpkg/qpkg.cfg）・CHANGELOG.mdを3点整合・Actions build・Linux/QNAP更新とhealth・iPhone再生/表示を確認してから。テストを行っていないPRを「合格」と主張しない。
- K6を新規開発する場合は現行K5の安定化・低I/O/Ideaページング・出典再比較支援へ限定し、実行権限/自律保存/新DBを追加しない。

## K6統合実行ゲート・欠陥修正まとめ（2026-11-18）

- K6は安全に一括統合するための品質ゲート。新規PR乱立を避け、**K5 Draft PR #37へ**`scripts/verify.sh`のAddon埋込UI JSチェック、`scripts/verify-k6.sh`一括verify＋Linux build/任意QPKG、`tests/test_k6_integration_safety.py`静的安全回帰、K4比較キャッシュ無効化/対応テストを追加。[K5設計](knowledge-k5-idea-canvas.md)。
- Codexの最初の実行は**依存先PR #29〜#37の正規checkout**で`bash scripts/verify-k6.sh`。成功してもQPKGは未確認（`WITH_QPKG=1`でpin QDK buildを別実行し、成功した事実を記録する）。`python3 -m unittest -v tests.test_idea_canvas tests.test_idea_workspace tests.test_k6_integration_safety tests.test_knowledge_cross_search tests.test_knowledge_links tests.test_knowledge_reviews`で問題を個別切分け。失敗は既存PR #37に修正し、すべての結果をHANDOFFとPRへ記録。
- 重点：K4 raw review 240件制限/ページ越え旧approval再出現防止、K5同じ原文へのrevert後stale、K2撤回→再承認で旧Idea再有効化しない、原文削除で歴史保持、source quote Unicodeオフセット、read GET write0、edit version競合409、request_id retry 0write、remote+sameUID idea_write tokenの最小権限、Host認証中断/再試行/2重送信、320px/390px iOS画面。
- 必須Do NOT：`ui.html`既定をVueへ変更しない、Vueはread-only/non-default、RDH backend authoritative、Host runtime`level_0_manual_only`/no execution、新Graph/DB/自律/実行/クラウド送信/raw source serving/redirect/fallback/startup npm build禁止。PR #23の重複GraphRAG採用・CLI分割追加禁止。原則、既存PR #37で少量の修正を解消する。
- リリースはリポジトリ`DEVELOPMENT_WORKFLOW.md`に忠実に、`qnaplibrary/__init__.py`のVERSION、`qpkg/qpkg.cfg`のQPKG_VER、`CHANGELOG.md`先頭を同期更新するPRをマージしたとき`release.yml`を動かす。addon.json versionも実態と整合確認。Actions未実行、QPKG/実機未実施で正式Releaseしてはいけない。

## K6b UI/UX改修の検証と機能連携引き継ぎ（2026-11-18）

- [Draft PR #38](https://github.com/souten-yd/PatentBuddy/pull/38)はK5 #37上、`qnaplibrary/web/addon-workspace.html/js/css`と`tests/test_workspace_ux.py`だけに限定した**大規模なUI/UX変更**。[具体的なAllowed/Do NOT/Expected final state/テスト/K6bデザイン](workspace-ux-k6b.md)を必ず読む。K1〜K5のAPI/SQLite/auth/Host runtimeは触らない。Mainの管理Web/ControlDeckグローバルシェルやログインを複製しない。
- 新UI：「資料 / 知識 / アイデア」3段階のローカル作業セグメント、Arrow Left/Right/Home/End、ReactやVueなしのDOM制御、接続状態/Jobs件数、PDFショートカット、PCの資料2カラム+iPhone単列。K2現在版承認済み知識→成立条件をK4検索フォームに手動転送（自動ネット検索・自動Idea保存なし）、K4比較→K5手動Idea、K4/K5引用→元文献→「比較/Ideaに戻る」・未保存フォーム保持。別Ideaでフォームが消える時だけ人間の明示確認。
- **次の実装・検証**：正規checkoutで`python3 -m unittest -v tests.test_workspace_ux tests.test_idea_workspace tests.test_knowledge_cross_workspace tests.test_knowledge_map_workspace tests.test_k6_integration_safety`と`bash scripts/verify-k6.sh`、`WITH_QPKG=1 bash scripts/verify-k6.sh`、ControlDeck Host opaque iframe/Bridge CORS/CSP、iPhone 320/390pxの入力拡大・下部nav・safe-area、Desktop 768/1024/1280px、light/dark/OLED/accent/theme.changed、Tab/矢印/Focus/Escape、PDF→K2レビュー→K4知識比較→K5案保存→K2変更/文献削除でstaleを実HTTP+SQLiteで操作確認。失敗は原則**同PR #38**へまとめる。
- 確認規律：PR mergedのmetadataに頼らずmain実ファイル/docs/manifest/tests/runtime、旧指示のscope/Allowed/Do NOT/Expected final state、実差分、指示外変更、Vue default/ControlDeck UI default/backend authoritative/level_0_manual_only/no execution、raw-source/fallback/redirect/npm build/自律追加なしを確認。PR #23 GraphRAG重複のマージは禁止。K1→K6b全stackの実test PASSとLinux/QPKG build・QNAP/Host/iOS E2E成功までDraft/未Release。

## K6c Obsidian型Atlas＋AI必須＋データ軽量化（2026-11-18）

- 最新実装は[Draft PR #39](https://github.com/souten-yd/PatentBuddy/pull/39)（base #38 UI）。[K6c全技術設計・K7へ引継ぐテスト指示](knowledge-atlas-k6c.md)。Obsidian調査を反映し、共通SVGフォース描画・タッチ/マウスDrag/Pan/Zoom/再配置・近傍強調・表示中のノード名ハイライト、iOSでも地図を見せる。global Atlasはcollection10×文献5、詳細はcollection50件ずつ。すべて既存RDH SQLite read-only・元文献正文はAtlasへ出さない。集合所属は技術関係でないことを明示。
- **AIは必須**：Global/Local双方の文献Inspectorに「ローカルAIで知識を抽出」を追加し、明示確認で既存K1b/K1d Local Host Jobを実行、結果は必ず未確認推論→人間レビュー。新クラウドLLM/provider/自動Graph or Idea writeなし。次K7は多文献ローカルembedding検索＋K2レビュー済みKnowledge Essenceの関連候補をプライバシー/証跡付きで提示・人が採否決定する機能を優先。推論の承認/原文版/単調epoch/review seqを完全追跡し、保存の権限を別にする。
- **DB軽量化**：K6cは既存`documents_coll_id`索引だけでglobal limit 10/collection page limit50、各collection count最大1001 index rowに制限、GET DB write0。K7では実1k/10k/100k文献でreads/writes/WAL/latency/CPUと日本語FTS5/ローカルembeddingのDBサイズ・再インデックス費用を測定してから外部content/quantized vector/optional WebGLを検討。無断の常駐自動再処理や新DBは作らない。
- **Codex first step**: 正規checkout上で`python3 -m unittest -v tests.test_knowledge_atlas tests.test_knowledge_atlas_workspace tests.test_knowledge_map tests.test_idea_canvas tests.test_knowledge_cross_search`＋K1a〜K6b全回帰、`bash scripts/verify-k6.sh`、`WITH_QPKG=1 bash scripts/verify-k6.sh`、`node --check qnaplibrary/web/addon-workspace.js`。現main実ファイル/docs/manifest/tests/runtimeを確認、PR diffと旧指示Allowed/Do NOT/Expected stateを照合。UI 320/390/768/1280、ControlDeck Bridge/CSP/Theme、Touch/Mouse/Wheel/Tab/Enter/ReduceMotion、AI Local Host model ready/missing、低I/O/zero writeを実機/SQLで検証。失敗は**PR #39内**で小修正。
- **Do NOT**：`ui.html` default維持、Vue read-only/not default、backend authoritative、ControlDeck Host runtime `level_0_manual_only`/no execution、raw source serving/fallback/redirect追加なし、startup npm buildなし、未公開文献のOpenRouter/Cloud送信・自律LLM実行/保存・特許性自動判定なし。K3b Graph/Idea human approval不変。PR #23旧GraphRAG二重導入なし。K7のSigma WebGLはCSPとbuild時同梱・必要性能を確認してから別PR。


### K7a 追加確認・次の実装（2026-11-18 / Draft）

[docs/source-collector-k7a.md](source-collector-k7a.md) を**最優先で読んで**、新 tests/test_source_planner_storage_figures.py、PDF extract/store/images、LiveServer/Host Bridge/権限、安全grep、容量、WITH_QPKG=1 を実行すること。K7aはK6c #39の上のDraftであり、mainの実装ではない。初期IPC分類プレビュー/EPO手動少量取得/SQLiteファイル容量表示/PDF候補領域cropまで実装したが、公式分類辞書の補完、完全なユーザー操作の取得UI、Vision AI・グラフ数値抽出、全入口ハードquotaは未実装。前述のAllowed/Do NOTとui.html/Vue/backend authoritative/level_0_manual_only/no execution/raw source serving禁止を堅持。K7a不具合の小修正は本PR内にまとめ、依存PR #29〜#39を検査・マージ前にこのPRも統合検証する。
