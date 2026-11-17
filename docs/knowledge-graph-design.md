# PatentBuddy Knowledge Graph — 解決エッセンス知識化・再利用 詳細設計

状態: **将来実装するための規範的な詳細設計（2026-11-17）**。本ファイルはdocs-onlyで、API/DB/UI/Jobsの存在を保証しない。優先順位とフェーズは [knowledge-graph-plan.md](knowledge-graph-plan.md) を参照。既存GraphRAGは [PR #23](https://github.com/souten-yd/PatentBuddy/pull/23) でDraft開発中。**mainにはこの設計の知識資産化機能は未実装**。実装時はPR #23の実ファイル・最新mainを再確認してテーブル/routeの重複を解消する。

## 1. 用語・責務・不変条件
- **原文層 Source/Evidence**: PDF/OCR、公報・請求項、論文、規格、社内メモ。ResearchDataHubの唯一の正本と文献revision・hash・引用位置・ライセンス/権限を維持する。
- **知識層 Knowledge**: 技術課題 Problem、原因 Cause、制約 Constraint、解決原理 Principle、作用機構 Mechanism、具体構成 Implementation、効果 Effect、実験条件/測定 Observation、別分野 Application。説明可能な短い「エッセンス」を記録。**原文引用とAIの解釈を区別**する。
- **アイデア層 Idea**: 仮説的な応用・改良・組合せ・請求項候補。ユーザーの選択/編集を伴う別の版管理対象。出願・権利成立・実施自由を確定した扱いにしない。
- **グラフ**: ノード/エッジの内容、関係の向き、依拠する根拠と発生元を明示した多層の知識。グラフ表示は原本でなくビュー。
- **原文の正本権限**: ResearchDataHubのSQLiteのみ。PatentBuddy/ControlDeckはlocal-only推論、Jobs、可視化と**再構築可能**なSSDキャッシュを担当する。別の永続正本・PC/NAS二重writer・SMB/NFS上の稼働SQLiteは禁止。
- **fail closed**: AIで導いた知識/リンクは初期値unreviewed。出典/版/位置を検証できないものはunverified扱いで根拠付きの事実として検索/引用しない。人が承認しても「推論」は「出典の事実」にならない。

## 2. ナレッジ抽出の表現（必須フィールド）
発明ごとに「何を解決するか→なぜ問題が発生するか→どの原理で→どう実装するか→どういう条件で→どの効果があるか→何が限界か」を中心に抽出する。単なる文献summary、claim chart、ユーザーアイデアを同一フィールドに詰めない。

### 2.1 Node候補のスキーマ（論理モデル）
- node_id: immutable opaque ID。文献/名称のみから作らない。
- node_type: source | problem | cause | constraint | principle | mechanism | implementation | effect | observation | application | claim_element | idea
- title、definition、language、aliases（日本語/英語等）、domain_tags、classification_refs（IPC/CPC/FI/F-term等。存在しない値は生成しない）
- granularity: specific | generalized。**具体実装**と**抽象原理**の両方を別ノードとして持ち、generalized_fromリンクで連結。
- basis: source_fact | model_inference | user_authored。最初から固定。review_status: unreviewed | approved | rejected、stale boolean、revision、created_at/updated_at
- visibility: private初期値。別案件の横断再利用は**権限の交差**とユーザー選択に従う。公開文献でも組合せ・調査履歴は機密とする。
- provenance: origin_document_id、source_revision、source_hash、source_section（claim/paragraph/page等）、source_start/end（Unicode code point [start,end) または既存実装の互換表現）、verbatim_quote、extraction_method、model_ref/processor_version、retrieved_at
- applicability: applicable_if（成立条件）、not_applicable_if（非適用条件）、failure_modes、unknowns。原文で直接支えられない箇所は**仮説の別statement**にする。
- quantitative_effects: value, unit, direction, baseline, measurement_condition, experimental_status の構造化候補。数字を推測で埋めない。
- consistency: source版・権限・根拠範囲を保存時に再照合。OCRテキストだけならOCRであること・ページ画像へのリンク・信頼低下を表示。

### 2.2 Edgeの型と品質
- factual/candidate: cites, belongs_to_family, has_claim_element, implements, describes, measured_as（原文で立証できる場合のみ）。
- semantic/inferred: addresses_problem, caused_by, operates_by, produces_effect, depends_on, has_limitation, generalizes_to, alternative_to, similar_to, applicable_to, contradicts, inspires, combines_with。
- エッジの方向（from_id/to_id）、type、basis、source/evidence一覧、confidence（比較用指標で法的確率でない）、review_status、stale、edge_revision、created_by、model_refを保存。
- 同じ2ノード間でも複数relation・相反する説・条件付き関係を許す。**類似**は**同一**としない。inferredは承認後もfactualへ自動昇格禁止。
- 文献由来の原文引用と、知識同士の考察/人手追加のリンクを別起源として保存。根拠が複数ある場合はprovenanceを配列または関係表で保持。

### 2.3 推奨テーブル設計（候補。既存表との照合が必須）
| 候補 | 役割 | 注意 |
| --- | --- | --- |
| graph_nodes / graph_edges | 既存PR #23の証拠付きグラフを**再利用** | 新規に同名表を並行作成しない。拡張はmigrationで整合 |
| knowledge_statements | nodeについての最小命題、basis、review、適用条件、immutable revision | ノード全体を巨大な1JSONにしない。抽出差分で更新 |
| knowledge_evidence | statement/edge→source spanを結ぶ多対多関係 | 文献版・hash・range・引用の一致を要求 |
| knowledge_aliases | 多言語同義語・正規化候補・適用分野 | alias衝突は自動mergeしない |
| knowledge_decisions | 人間の承認/却下・merge/split判断・理由・timestamp | 監査/レビューに本文や秘密を出さない |
| idea_revisions / idea_dependencies | アイデアの版、派生元node/edge/文献、検証状態 | 発明案は原文の事実にしない |
| knowledge_job_receipts | 冪等性・Host Jobとの保存照合に必要な識別子 | 本文/プロンプト/資格情報を格納しない |

テーブル名・カラムは実装時の最終仕様ではなく、現在のgraph_storage/review/analysis依存表と衝突しないようPR #23の設計を第一候補として整理する。可能なら既存graph_nodes/graph_edgesに追加の属性/関連表を持たせ、独立グラフを構築しない。

## 3. AI抽出パイプライン
1. **明示実行**: 認証済みユーザーが選んだ文献ID/版/セクションだけが対象。外部情報収集とは別ボタン。自動クラウド送信は無い。
2. **根拠準備**: ResearchDataHub APIで必要な請求項/段落/図面説明・OCR信頼度・revision/hash/ライセンスを取得。PCへは選択部分だけ。抽出時は本文改変検出。
3. **ローカルAI**: ControlDeck Hostの検証済みlocal_only LLM/Jobs、CPU/GPU lease、キャンセル、進捗上限を使用。モデルによる構造化出力はschemaとサイズ/件数で検証。モデル未対応なら停止し、クラウド/別プロバイダへfallbackしない。
4. **抽出**: problem/cause/principle/mechanism/implementation/effect/constraint/applicationを**分けて**提案。原理と実装の抽象化を両方保持。抽出できなければunknown、数値は実際の記述値のみ。
5. **原文照合**: 引用文字列・段落/ページ・Unicode範囲・文献版と完全照合。OCR低信頼・段落不明・引用不存在をconfirmedとして保存しない。意味的な支持関係はあくまで未承認。
6. **正規化**: 同義語・IPC/CPC・作用機構と適用条件を用いて既存Knowledge候補をtop-k提示。**原理が似ている**ことと**条件/意味が同じ**ことを区別。自動同一視しない。
7. **レビュー**: 保存前に新規カード/既存への接続/矛盾候補をプレビュー。人は採用/却下/編集/別ノードに保持/merge/splitを選択。AI初期proposalはunreviewedとして明示保存可能。
8. **永続化**: ユーザー承認後に正本へ原子的保存。元文献を自動書換しない。POST応答不明時はidempotency key/receiptで確認して重複を避ける。
9. **失効**: source revision/hash、source-span、参照edge revisionやreviewが変化した場合、依存statement/ideaをstaleにして再検証対象へ移す。**古い承認を復活させない**。影響伝播はboundedでqueueにし、全件一括探索を避ける。
10. **再抽出**: 同じ原文/モデル設定/抽出verへの冪等処理は新しい書込み0。モデル変更時も過去の人手承認は上書きせず新しいproposalとして差分を提示。

### 3.1 抽出結果のJSON例（説明用、非稼働API）
~~~json
{
  "kind": "knowledge_proposal",
  "source": {"document_id": "doc-example", "revision": "r3", "section": "paragraph-0010", "start": 20, "end": 38, "quote": "測定値に応じて制御ゲインを切り替える"},
  "items": [
    {"kind": "implementation", "text": "測定値に応じた制御ゲイン切替", "basis": "source_fact"},
    {"kind": "principle", "text": "運転状態に応じて応答特性を変える", "basis": "model_inference", "review_status": "unreviewed"}
  ],
  "hypothesized_applications": [
    {"domain": "冷却制御", "rationale": "状態変動に対する応答選択に類似", "basis": "model_inference", "status": "needs_validation"}
  ]
}
~~~
原文quoteとrangeの完全一致は仮想例のため計算値を示していない。実装ではテストfixtureの実テキストとオフセットを厳密照合すること。

## 4. 知識同定・誤統合を防ぐ設計
- 用語の一致、埋め込みのcosine類似、分類コード、入出力の作用、適用条件/制約、測定単位を**別の特徴量**として比較し、単一のsimilarity閾値で自動統合しない。
- 異分野で同じ語を使用する場合、機構が異なれば**別ノード**。同じ物理原理でも必須条件や適用範囲が異なるときは**上位概念と派生実装**の関係を優先。
- contradicts / counterexample / failure_mode は削除ではなく矛盾や適用範囲の注意として保存。出願日・優先日・分野・国別権利状態は文献属性として別管理。
- mergeは二段階のプレビュー/承認/可逆なalias mapを採用し、原IDと元の根拠を保持。削除で参照を壊さない。splitも旧IDから新IDへの履歴を残す。
- 誤統合率、approved後に取り消した率、根拠不一致の率を計測し、統合候補UIでは**証拠/相違点/適用条件**を併記。

## 5. 検索・GraphRAG・発明創出
### 5.1 探索モード
- 出発点はキーワード、自然文の技術課題、類似公報、請求項、Knowledge node、またはIdea。
- FTS5→embedding候補→bounded graph expansion（既存PR #23の1〜2hop、ノード/辺上限を尊重）→Host rerank→根拠検証。exact一致と意味類似・未知の区別を表示。
- 返す説明: なぜヒットしたか（同じ課題、同じ原理、類似する作用機構、適用条件の一致/相違、引用関係）、信頼状態、検証済み原文リンク、探索打切り・検索未到達分野、モデル/検索時点。
- approved factual情報はデフォルト候補。unreviewed inferred/ideaはUIの**明示フィルタ**で別レーンに出し、根拠としての重みを過大評価しない。
- 同一ユーザーでも案件分離・private文書閲覧スコープを守る。隠されたノード/辺のID、タイトル、件数、存在有無、類推される説明を公開専用tokenに漏らさない。
- 利用可能な検索結果がない場合はno evidence/coverage不足を表示し、勝手に「新規性あり」と結論しない。

### 5.2 横断応用とアイデア合成
- ユーザーが候補nodeを選んで**この知識を利用して発明案を生成**を押す。検索のみで自動生成・永続保存・外部通信を行わない。
- 各案に「解決したい課題」「選んだ原理」「異分野転用に必要な適用条件」「具体実装」「効果の根拠/仮説」「検証実験」「想定限界/コスト」「出典node ID」「意図しない副作用」を必須とする。
- 組合せ探索は2〜3要素からbounded開始し、既知の技術的整合性・禁止条件・必要な変換を明示。盲目的な大量組合せ、際限ない自己反復はしない。
- 候補は案A広範囲、案B実現性重視、案C代替原理、案D派生用途等を**候補**として表示。独立請求項と従属請求項の範囲は公報・記載要件で別審査。
- 案の保存は人による明示採用後。発明案→関連公報の再調査→新規性/進歩性論点→FTO（別審査）→追加実験→改訂を循環させ、派生グラフを保存。
- 類似度やLLM自信スコアから法的な新規性・進歩性/侵害を確定しない。国/基準日/公開時点/生存権利の未確認を表示。

## 6. ResearchDataHub / Add-on API（**提案する契約**、現時点では存在しない）
Host principal認証とResearchDataHub scoped token/ローカルUnix peer契約を再利用。既存published-only token/一般ro tokenへmutationを付与しない。版とCSRF/Origin/TLSを必須にする。

| Methodと候補path | 用途・出力 | 最小権限案 |
| --- | --- | --- |
| POST /api/v1/knowledge/extract-jobs | 選択済文献/版の抽出Job受付。実LLMはAdd-on/Host側で起動 | knowledge.propose + Host jobs/ai |
| GET /api/v1/knowledge/proposals | 生成候補/根拠/レビュー状態をページング表示 | knowledge.read |
| POST /api/v1/knowledge/proposals | schema検証済みproposalの限定保存/receipt発行 | knowledge.propose |
| POST /api/v1/knowledge/reviews | proposal採否、差分、編集元、根拠検証、version条件 | knowledge.review |
| GET /api/v1/knowledge/nodes/{id} | 必要部分だけのカード/出典・関連辺・版 | knowledge.read |
| GET /api/v1/knowledge/graph | seed ID/フィルタ/1〜2hop/上限/truncated | knowledge.read |
| GET /api/v1/knowledge/search | 技術課題・原理・適用条件の複合検索、cursor | knowledge.read |
| POST /api/v1/knowledge/merge-preview | 類義語/重複候補の差異点プレビュー。永続変更なし | knowledge.review |
| POST /api/v1/knowledge/merge | 人が明示承認した可逆なalias統合、版一致 | knowledge.review |
| POST /addon/v1/ideas/propose | 選択済みnode/制約で発明案候補を生成（Host local-only） | Add-on限定Host ai/jobs |
| POST /api/v1/ideas/revisions | 明示採用されたIdea版と依存ID保存 | idea.write |

※ path/permissionは**設計案**。既存API命名・token境界と突き合わせてから実装時に確定。外部APIに自由入力を渡すrouteではない。検索クエリ/アイデアは監査ログ/GET公開APIに流さない。

### 6.1 要求・応答の安全仕様
- ID/版/所有者・visibilityをAPI側で検証し、clientから送ったsource textをそのまま事実と認めない。最新正本revisionとの差分があれば409。
- ページング、cursor、hop、seed、ノード/エッジ/根拠数、テキスト長、ジョブ同時実行数、レスポンスbytesに固定上限を置く。超過はtruncated/partial/needs_reviewと示す。
- Undo/merge、claim/idea編集、文献権限変更等のmutationは明示操作 + 独立scope。public/published token、read-only scopes、匿名からは一律拒否。cross-projectはpermission intersection。
- 結果・根拠のETag/文献revision/edge_revisionとidempotency keyを保持し、同期中の版変更は再評価。
- プレビューGETは永続書込み0。結果がなくても推論APIへ自動fallbackしない。未確認・未登録モデル・通信失敗ではread-only全文検索を残す。

## 7. UI（Obsidian型、ただし既存ControlDeck view内）
- **Knowledge Map**: graphの限定seed view。pan/zoom、タッチ/ドラッグ、node種別/公開性/review/推論/失効を可視的に分離し、方向付きedgeと凡例。検索結果に「展開」ボタン、深さ・件数・打切りを表示。
- **Knowledge Card**: title/definition/解決エッセンス、課題・原理・メカニズム・具体例・効果・制約・応用・反例/矛盾、出典の原文位置・OCR注意、review history。
- **Evidence Pane**: 公報/原本PDFの段落・請求項・ページ・画像と正確なハイライト。引用が断片しかない場合は限定表示、推測では段落の引用が存在するように描かない。
- **Idea Canvas**: 選択知識カード（複数）→比較→明示生成→候補比較→採用/編集→先行技術再検索。元ノードへの依存関係を失わない。
- **Diff/Review**: 新しい抽出と既存カードの差分、重複候補、stale影響、merge/splitの確認を別画面にし、誤操作をundoできる。
- PCでは文献/カード/地図の分割画面、iPhone幅320pxでは単一ペインで階層を戻る方式。グラフ全体/過密ノードを描画しない。キーボード操作、凡例、色以外の識別、低視力対応を含む。
- デフォルト画面/既存ui.htmlを勝手に差し替えない。Vueをdefaultにしない。Cytoscape.js等を使用する場合は事前に依存/配布/ライセンスを別reviewし、**CDN/サーバ起動時npm buildなし**・静的固定資産を検証する。初期段階は既存UIで小型グラフ表示可能。

## 8. 実行資源・性能・保全
- サーバーのSQLiteがcanonical。FTS5と必要なグラフ索引だけを用い、PCのベクトル/描画配置は再生成可能なcache。大量のembeddingをNASへ無計画に増やさない。モデル更新時の影響/コストを測る。
- extractionは選択文献の差分/原文hash単位、1件ずつbounded処理、Host Job/資源lease/取消・再実行・crash-recovery。初期はユーザー押下のみ。夜間の自動全件再抽出は禁止。
- 無変更登録・duplicate提案の書込み0、idle 15分のwrite最小化、サーバーGET書込0を測る。正本索引とレビュー/監査書込のみ例外とし、理由をPRに記載。journal/WAL/監査の無効化は禁止。
- 1000/10000/100000文献の時、ノード数・edge密度ごとの検索P50/P95/P99、メモリRSS、CPU、実物理read/write、DB/WAL/SHM、UI表示数/応答、復元整合性を測る。数値目標はベースライン実測後に定める。
- 正本snapshotにはknowledge/ideas/evidence/reviewとversion依存を含む。移行はPC→NASの既存PR-G計画、SQLite backup/quick_check/hash/件数/秘密/復元のゲートに従う。PC cacheを正本へ自動昇格しない。

## 9. 安全性・プライバシー
- 未公開発明/請求項/検索履歴/知識連結/発明案は**private初期値**。構造化エッセンス自体も出願前の情報を漏らすので、外部LLM・外部ベクトルDB・公開APIに出さない。
- 外部検索語も発明の核心になり得る。公開情報として送信可能な固定/人手承認済み検索語を使うか、ローカル収集済み文献だけで検索。未承認の自動同義語拡張を第三者に送信しない。
- 検証済みlocal-only Host推論だけを使い、DNS/redirect/proxy/クラウド中継を避ける既存privacy防壁を弱めない。埋込・リランク・画像/OCRにも同じ規則。
- Prompt injection対策: 収集公報/添付PDF/抽出結果は**非信頼データ**として扱い、システム命令にしない。モデルの提案はschema・原文版・span・権限をサーバで再検証。
- audit/debug/notificationには本文・タイトル・引用・発明案・トークンを格納しない。公開承認/出願/権利化/無断mutation・実行を追加しない。
- 既存のui.html default / Vue read-only not default / backend authoritative / runtime level_0_manual_only / no execution capability / raw source serving・fallback・redirectなし / startup npm buildなしを維持。

## 10. テスト・受入シナリオ
**T1 正しい抽出**: 公報の記載された課題/原理/実装/効果/適用条件と複数根拠がカードになり原文に戻れる。モデルの仮説は別ラベル。
**T2 同義語の候補**: 日本語・英語/IPCの同義関係を提案し、原理・条件が違う同名語はmergeしない。merge/splitはプレビュー、承認、履歴/Undo。
**T3 横断検索**: 異なる分野の共通原理を再発見でき、検索理由・適用条件・反例・不足根拠を明示。意図的に非関連な事例が上位にならない品質評価。
**T4 派生発明**: 2〜3ノードを選んで案を生成、採用するまで正本は変化しない。採用したIdeaに依存元/元文献/生成モデル版/再調査結果を保存する。
**T5 stale**: 文献段落改訂、請求項変更、根拠削除、edge承認撤回→依存するカード/Ideaへ影響表示。元の文献に戻しても旧承認は復活しない。
**T6 セキュリティ**: published/ro権限でprivate knowledge/Idea/review mutationと存在推測を拒否。privateをクラウド、proxy、ログ、external queryへ送信0件。
**T7 障害**: 途中取消/モデル不在/AI schema不正/LLM fabricated quote/サーバー再起動/保存応答喪失/同一再投入/同時編集で部分成果や重複なし。
**T8 性能**: bounded graph上限、無変更DB write0、一覧/閲覧/idle書込みなし、1千/1万/10万の物理I/Oと検索レイテンシ、snapshot復元後も根拠一致。
**T9 UI**: Linuxブラウザ1280px/390px/320px、iPhone実機受入、スクロール/戻る/展開、注記・凡例、キーボード。横溢れ・JS例外なし。
**T10 回帰**: 既存PDF/OCR・LLM Jobs・GraphRAG・Claim chart・published API/認証・QPKG/Host manifest・mainからの更新を破壊しない。

受入評価用データセットは合成資料＋権利関係を検証可能な公開資料で構成し、精度は「根拠が一致したstatement率、unsupported率、誤統合率、Recall@k/Precision@k、stale漏れ率」を分けて計測する。品質保証/特許性の自動確定とは区別する。

## 11. Codex実装単位（Scope / Allowed / Do NOT / Expected state）
- **K1 PR**: 既存GraphRAG基盤の上で原文根拠付きKnowledge Proposal抽出とschema、read-onlyプレビュー/限定保存。Allowed: 新しい小規模型・API・Jobsアダプタ・tests。Do NOT: グラフ全面改修、公開API権限拡張、外部LLM転送。Expected: 同一資料の再抽出は無変更write0・虚偽引用拒否・根拠付き候補をreviewできる。
- **K2 PR**: 重複候補/適用条件/異説/レビュー/版失効。Allowed: 既存ノード/辺の後方互換migration、狭いreview権限、回帰tests。Do NOT: 自動merge、自動承認、人手判断上書き。Expected: 異なる原理を誤統合せず、source変更で依存先がstale。
- **K3 PR**: 地図/カード/出典表示。Allowed: 保持済みGraphRAG APIの安全なbounded read、UI静的資産・モバイルtests。Do NOT: Vue default化、CDN依存、raw source server/new execution、startup npm build。Expected: 選択ノードから文献根拠まで遷移・逆遷移。
- **K4 PR**: 横断知識検索/異分野提案。Allowed: ローカルembedding/rerankと既存Host Jobs、提案トレースと質的評価。Do NOT: 機密検索語の外送、確定法的結論、無限探索。Expected: 別案件で過去知識を見つけ適用条件を確認。
- **K5 PR**: Idea Canvasと再調査/請求項への接続。Allowed: proposal draft、明示採用、idea版管理/依存関係、先行技術の再比較。Do NOT: 無断保存、自動出願/公開、自律的永続変更。Expected: 元knowledge/文献を追跡でき、選択案を再評価できる。
- **K6**: 性能・実機/移行の最終受入。NAS移行は既存PR-Gの単一正本方針と整合し、別マイグレーションを勝手に並行実行しない。

各PR開始前にmain docs/manifest/tests/runtimeと対象PR diffを照合し、Do NOTと最終状態をPR説明へそのまま記録。少量の関連修正は次のPRに同梱し、セキュリティ境界やマイグレーションが大きい場合だけ分割。必ず bash scripts/verify.sh、必要なLinux/QPKG build、API/機密・安全grep、ControlDeck実UIの該当検証を実施し、未実施内容もHANDOFFに記載。docs-only変更はrelease不要。

## 12. 未確定事項と判断タイミング
- 知識reviewを管理者だけにするかHostのscoped principalに分離するか: K1でHost既存契約とRBACを調査して決定（既存管理APIを一般開放しない）。
- Concept正規化の粒度と類似度閾値: K2で誤統合評価の実測後に決定。スコアだけでmergeしない。
- Cytoscape.jsの採用・ライセンス/配布サイズ・依存追加: K3のADRで比較し、既存Vanilla UI+静的描画を先に評価する。
- ANNや外部GraphDBの導入: K4/K6で10万件等の実測が必要になった場合のみ別ADR。正本SQLite以外の常時サービスを増やす前に効果/書込み費用を示す。
