# K6b — ControlDeck準拠のタスク中心UI/UXと機能連携

状態：**Draft PR #38（2026-11-18）／未マージ・未リリース**。base：K5 PR #37（K4 #36 → K3b #35 → K3 #34 → K2 #33 → K1d #32 → K1c #31 → K1b #30 → K1a #29）。今回の範囲は**PatentBuddyのControlDeck埋込画面のUI/UX**に限定する。ResearchDataHub backend, 認証, Host runtime, API, SQLite schema, GraphRAGの推論・承認・保存意味論を変更しない。

## 変更の動機

これまでのWorkspaceは、PDF取込/資料一覧/通常検索/K4横断検索/K5 Idea Canvas/開いた文献のK2レビューやMap/Jobsを1ページに縦積みしていた。1280pxでは空間を使い切れず、iPhoneでは検索→原文確認→比較→Ideaを行き来すると数画面以上のスクロールになる。操作の意味や権限が不明瞭になりやすい。ControlDeck Host mainの実`PageHeader.tsx`, `styles/index.css`, `docs/mobile-layout.md`と[UX契約](controldeck-ux-contract.md)を参照し、グローバルHostシェルは変更せず、**コンテンツの作業手順だけ**を段階的に表示する。

## UI実装・具体的操作

1. **作業領域内のセグメント**「01 資料／02 知識／03 アイデア」。`role=tablist/tab/tabpanel`, `aria-controls/aria-labelledby/aria-selected`, 1つだけアクティブ、非選択は`hidden`。左右矢印・Home/Endでキーボード操作。切替時に検索結果や入力途中のIdeaを**破棄せず保持**。これはHostのグローバルナビではなく、iframe内部コンテンツの三つの状態。URL/ブラウザー履歴/Host routeを更新しない。
2. **資料**：PCでは文献キーワード検索と保存済み資料一覧を2列配置。文献詳細は全幅でMap・レビュー・リンク・原文/PDF根拠を確認。PDF取込は必要な時だけ開く`details`へまとめ、セクション見出しの「PDFを追加する」から直接展開可能。処理中のAnalysis/PDF件数をサーバーの既存Jobs応答から表示し、処理状況は作業領域共通の開閉パネルに集約（既存の取消/再実行/Host同期も保持）。
3. **知識**：K4のread-only横断検索/検索結果/別文献2〜3件の比較を専用コンテンツパネルへ。K2で**人間が承認済みかつ現行版の知識カードだけ**に「この条件から関連知識を探す」を表示。押すとまず`conditions[0]`（無ければstatement）を最大120 Unicodeコードポイントで検索フォームに入れて「知識」へ切替。**自動検索や推論、Graph・Idea保存はしない**。利用者が検索語を変更・確認した後に検索ボタンを押す。
4. **アイデア**：K4比較完了時の既存「この比較を材料にIdea Canvasへ」は、K5の人間編集フォームを開くと同時に「アイデア」へ切替。自動保存/採用はない。ユーザーの手動確認チェック・別scope `idea_write`・明示保存が必須。編集中のフォームを別のIdea/新規比較で置換しようとする際だけ、未保存入力を破棄する確認を表示。**タブ移動や原文参照ではフォームの内容を維持**。
5. **証拠を参照し戻る**：K4検索/比較またはK5のsourceカードの「原文の引用へ」で資料パネルに切替し、既存`openDocument`と`focusKnowledgeEvidence`でUnicodeコードポイント原文引用を確認。文献詳細に「比較画面へ戻る／Idea Canvasへ戻る」を表示。戻ると前の比較結果・Idea入力欄を保持。通常の別文献表示ではこの専用戻りボタンを解除する。文献詳細には「知識の横断比較へ」の直接操作を設ける。
6. **接続と状態**：接続状態はコンパクトにResearchDataHub接続済み・要設定/再接続を文字で表示。失敗時の検索・Idea保存ボタンを無効にし、再接続操作と理由を表示。処理状況はバックグラウンドのHost shellへ複製せず既存Jobsだけを参照する。
7. **デザイン**：Host Bridgeの`--pb-accent/bg/surface/text/border/muted`のみで中立色に統一。見出しの階層、入力欄、検索結果、引用カード、知識カード、Idea履歴の余白・角丸・フォーカスを整理。PC 768px以上は資料検索/一覧2列・K4比較3カラム、767px以下は全1列。iPhone 390px以下はステップ切替の副説明を省略してタップ範囲を維持。全主要ボタン44px、入力16px、safe area bottom/reduced-motion、横あふれなし。外部CDN/独立UIフレームワーク不要。

## Allowed / Do NOT

Allowedは`qnaplibrary/web/addon-workspace.html/js/css`のレイアウト・状態・文脈ナビ、`tests/test_workspace_ux.py`の回帰、docs・PR本文のみ。**既存K1a〜K5のbackend/route/auth/schema/provenance/DB writeやruntime semanticsを変更しない**。ユーザーの依頼と無関係な機能・生成AI実行を追加しない。

禁止：ControlDeckのグローバルヘッダー/サイドバー/モバイル下部ナビ/ログイン/戻る/履歴の二重化、Host Vue default化、ui.html default変更、RDHのindex.html default変更、raw source serving・新redirect/fallback、新DB・Graph engine・外部CDN、未公開特許のクラウド送信、無断Graph/Idea mutation、model_inferenceを事実認定、Host runtime `level_0_manual_only`/no execution変更、サーバー起動時npm build、PR用Actionsの無断作成。

## 検証状況

- **実実装確認**：GitHub connectorで旧PR #37のHTML/CSS/JS、K2/K4/K5の知識・比較・Idea動線、現ControlDeck mainのPageHeader/Theme/Mobile実ソースを読んでscopeを確認。
- **静的検証済み**：V8で`new Function(addon-workspace.js)`の構文チェックPASS、JSで参照するHTML ID欠落・重複**0件**、3つのtab/tabpanel整合、HTMLタグ階層、K2 approvedのみ条件引継ぎ、textContentによるquote、ControlDeckテーマ/320px単列・44px/16px、権限・schema・runtime非変更を確認。
- **追加テスト**：`tests/test_workspace_ux.py`に3タブ/roleとaria、既存全機能ID保持、キーボード操作・フォーム破棄保護、明示連携、接続状態/Jobs、Host theme/モバイル/safe area/No innerHTML/No external/CDNを検証する静的回帰を追加。**追加したPythonテストコードは未実行**。
- **未実施**：`bash scripts/verify-k6.sh`, 全K1a〜K5 HTTP/SQLite/Node CLI、Ubuntu/QNAP build、ControlDeck Host/iPhone Safari/iPadの実画面/キーボード/タッチ/VoiceOver、接続切断/復旧・Jobs取消・ページ履歴・CSP・低I/O。作業用containerはGitHub DNS解決不可のため正規repo checkoutができず、**PR #38はDraft維持。マージ・Releaseしない**。

## 次Codex実装/検証指示（K6bリリース前統合）

1. **UIを実ブラウザーで確認**：1280/1024/768/390/320px、Light/Dark/OLED/アクセント変更、iPhone Safari(standalone含む)/iPad/ControlDeck Host opaque iframe/Host token更新。検索ボタン・セグメント・Inputのfocusとキーボード時scroll、safe-area/横はみ出し、旧PDF/Map/review/Ideaアクセス、Tab/Arrow/Home/End、スクリーンリーダーのタブ説明を確認。セグメントはHostナビでなくiframeコンテンツだけ。
2. **一連の利用ケース**：PDF取込→保存文献→抽出→K2承認→「この条件から関連知識を探す」→修正して手動K4検索→2〜3件比較→根拠で資料へ→戻る→Idea Canvas→入力→根拠参照→戻る→明示保存→旧版履歴→K2却下/原文更新でIdea失効、の全工程を実HTTP/SQLiteで確認。
3. **非同期レース・回帰**：データロード中のセグメント切替、検索中の選択解除、古い比較APIレスポンス/Idea入力保持、原文閲覧失敗からの戻り、Host再接続時のdisabled、PDF Job完了・キャンセル。文献更新はsource_revision/epoch/seqのbackendチェックが権威でありUI表示を認可根拠にしない。
4. **実テスト**：`bash scripts/verify-k6.sh`、必要なら`python3 -m unittest -v tests.test_workspace_ux tests.test_idea_workspace tests.test_k6_integration_safety tests.test_knowledge_cross_workspace tests.test_knowledge_map_workspace`、`WITH_QPKG=1 bash scripts/verify-k6.sh`、Linux/QNAP配布テスト。実行出力と失敗修正をPRへ添付。**テスト未実施をPASSとみなさない**。
5. **安全差分**：現main実ファイルと各PR #29→#38をAllowed/Do NOT/Expected final state、docs/manifest/tests/runtime/Host Bridgeで照合。K2人間承認済み推論の事実昇格、新DB、Vue default、raw source/fallback/redirect、server startup npm build、autonomous/exec/network を追加していないことを直接安全grepで確認。#23旧GraphRAGは二重導入しない。
6. **運用**：細かいUX修正は**PR #38へ同梱**して追加PRを増やさない。全stack実検証後に依存順でmainへmergeし、`VERSION/QPKG_VER/CHANGELOG`とaddon manifestを実整合させた正式リリースを実行、Ubuntu/QNAP healthとiPhone操作を検査。

**Expected final state（K6b）**：通常の検索・PDF・レビュー・Mapの機能を一つも失わず、PC/スマホとも3段階のわかりやすい作業領域から資料→知識比較→Ideaへ進め、引用の確認後は元画面へ戻り入力を失わない。データ正本と権限、すべての明示人間操作は従来どおり。
