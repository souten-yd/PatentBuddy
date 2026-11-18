# K6c — Obsidian風 Knowledge Atlas / 多数文献の低I/O探索 / ローカルAI連携

日付：2026-11-18。対象：[Draft PR #39](https://github.com/souten-yd/PatentBuddy/pull/39)（base：UI/UX K6b PR #38 → K5 #37 → K4 #36 → K3b #35 → K3 #34 → K2 #33 → K1d #32 → K1c #31 → K1b #30 → K1a #29）。**未マージ・未リリース。**

## 今回の方針とObsidian/Sigma比較

Obsidian公式[Graph view](https://obsidian.md/help/plugins/graph)は、ノードのフォース配置・ドラッグ・ズーム/パン・ローカル/グローバル切替・深さ/フィルタ/グループ・Center/Repel/Link force・ラベル濃淡を備える。PatentBuddyの旧K3は36 nodes/52 edgesを固定放射状SVG配置し、iPhoneで地図を非表示にしていたので、単なる色替えでは改善しない。

[Sig­ma.js](https://www.sigmajs.org/docs/)は[WebGLレンダラー](https://www.sigmajs.org/concepts/rendering/)でGraphologyに依存し、数千〜数万の可視ノードに適する。[Graphology ForceAtlas2 Worker](https://graphology.github.io/standard-library/layout-forceatlas2.html)も将来候補。**WebGIではなくWebGL+Sigma.js/Graphology**がこの用途の適切な候補。ただし全資料を同時表示すると技術的関連のないノードが毛玉状に混ざるため、初期は既存DB上の文献集合→部分グラフへ段階展開する。初期の可視最大61点にWebGL/npm依存を追加する費用対効果は小さいので、K6cではCSP/Hostを変えずSVGで実装し、実データ/端末のベンチ後にWebGL化を判定する。

## 実装済みの構成

- `qnaplibrary/knowledge_atlas.py`（新規）：**唯一のResearchDataHub SQLite**で、コレクション名/種別・文献ID/タイトルだけを読む。文献全文・未公開請求項・PDF・ベクトル・AI原文をGlobal Atlas APIで返さない。
- `read(store,cursor=0,limit=10)`は保存先をPK keyset 10件ずつ取得、最大5文献をそれぞれ見本表示（全体最大61ノード/60エッジ）。コレクション件数は`documents_coll_id`既存索引を使う最大**1001件のbounded SELECT**で計測し、1000件超は正確な値ではなく`count_is_lower_bound=true`と「少なくとも1000件」を返す。億単位の文献をCOUNTするためにディスクを無制限に読まない。
- `read_collection(store,collection_id,cursor=0,limit=50)`は選択した分野内の文献をID降順keysetで50件ずつ、最大51ノード/50エッジ。段階的に次ページ。全件の本文ロード・自動インデックス構築・キャッシュファイル書込・新規Graph DBなし。GET/検索/パン/ズームではDB write 0。
- `GET /api/v1/knowledge/atlas?cursor=0&limit=10&collection_id=0`は既存**read**権限、admin/ro/rwだけが利用。重複/不明クエリ、数字以外、signed63超、範囲外は400。published/knowledge_propose/review/link/idea_write専用tokenからは403。ControlDeck Host session認証下の`GET /addon/v1/knowledge/atlas`は既存read-only資格を使い、書込権限を偽装/流用しない。
- Global Atlasの接続は`basis=catalog_index`、関係の意味は**保存先への所属のみ**。技術的類似、因果関係、発明の同一性、特許性を意味しない。文献をクリックすると既存K3ローカルマップの原文引用/承認済み出典関係へ移動。K3b `basis=inferred` は明示チェック時のみ点線、K2 `basis=model_inference` は人間の承認後も確定事実に昇格しない。
- `addon-workspace.js`：共通`makeForceGraph`で最大84点/160辺クライアント防御（実APIはさらに少数）。ノード反発/リンク引力/中心制御、最大55 frames・1 frame 2 ticksで停止、inactive/Reduced-motionは同期で上限80 ticks。SVG force placementは**永続化しない**ので編集やタッチのたびにQNAPディスクへ書込なし。
- グラフは**ノードドラッグ・背景パン・ホイールと＋−ズーム・全体表示・再配置・タップ/キーボードEnter/Spaceでの選択・ホバー/選択ノード近傍強調・ノード名フィルタ**に対応。iPhoneはタッチ操作のSVGが表示され、検索・インスペクタは縦に配置。Hoverのない端末でもタップ選択で詳細確認可能。Hostテーマを継承し、文字列は常に`textContent`、JS `eval`・外部CDN・新Vue/Reactなし。
- Node Inspectorは文献→全文と現行K3近傍・元根拠、コレクション→保存先資料一覧または50件ページの文献マップを開く。Globalは`scope=catalog_sample/catalog_page`を表示し、サンプルを全件と誤認させない。

## 必須AI連携：今回実装した操作と次段階の仕様

**今回**：全体アトラスと文献近傍のInspectorに「ローカルAIで知識を抽出」を設置。ユーザーが明示選択・確認した文献についてのみ、既存の`POST /addon/v1/jobs {doc_id,kind:'knowledge'}`を通じてK1b/K1dの**ControlDeck Host local-only＋provenance付き**モデル実行を要求する。成功時は既存ジョブ/knowledgeレビューが更新され、人間の承認前は必ずAI未確認推論。リモートLLM/OpenRouterへのフォールバック、勝手なGraph relationやIdea保存・特許性確定は**なし**。ローカルモデル未稼働・Host証跡なし・書込認証不足の場合は失敗として表示。

**次K7の必須設計（今回未実装）**：大量文献から意味的に近い解決原理・課題・機構・効果の**AI関連候補**を返す2段階探索。既存ResearchDataHubの`chunks_fts`/既存vectorsを再利用し、QNAPが文献・索引の正本、ControlDeck PC側のローカルembedding/LLMが明示要求時に計算する。未公開文献は外部生成AIに渡さない。関連候補は`basis=model_inference,review_status=unreviewed`、`doc_id/proposal_id/item_index/source_revision/source_epoch/review_seq/quote/range/Host provenance`と類似性根拠を持つ。スコアだけで技術的事実や因果関係と判定しない。ユーザーが原文を確認→候補を採用/却下→K3bに準拠した明示リンク審査を経るまでは**persistent factual GraphRAGに追加しない**。AI提案のクラスタと保存先所属クラスタは色と凡例を明確に分ける。

## データ量とSQLite低I/Oのロードマップ（推測の自動Index増設なし）

1. Document・source PDF・抽出chunk・embedding・knowledge・GraphRAGは既存SQLite正本。新Qdrant/Neo4j/Vector DBをデフォルト追加しない。既存の`documents_coll_id`/Graph edges/FTS5/vector indexを利用。最大10 collections/5 docs（全体）、選択collection 50 docs（詳細）、K3 36 nodesで常にユーザーの視点へ切り替える。
2. 1,000/10,000/100,000文献でDB file/wal/shm size、個別資料JSON response bytes、p50/p95 latency、CPU/RAM、**physical reads/writes**、後方pageの深さ、iPhone/Ubuntu 30/60fpsを計測する。K6cの段階取得では全文をブラウザにロードしないが、実環境での性能目標達成をまだ主張しない。
3. FTS5を増設する場合は[SQLite FTS5公式](https://www.sqlite.org/fts5.html)のexternal-content/contentlessによる重複抑制を測定してから検討。日本語の分かち書き・trigram索引増大、FTS auto-mergeのディスク書込を比較。従来K4のraw review 240イベント走査/ページは大規模運用には不十分な可能性があるので、ユーザー操作から明示Index作成/ローカルmodel推論の処理経路を分離する。
4. モデルのembeddingはローカルPCのバッチ処理/増分更新のみで、NASへの保存時に圧縮/量子化の精度・再計算費用を測る。無効化の正本は文献hash+epoch+review seq、変更時の差分だけ再計算。入力を送らず既存結果を返せるときは推論を実行しない。
5. **可視ノードが200〜500超/数千edgesなど、UI応答が実測で悪化した場合**は[Sigma.js+Graphology WebGL](https://www.sigmajs.org/docs/)とForceAtlas2 Web Workerを**build時に同梱**し、CSP/Host Bridgeで検証。WebGL不可ならCanvas2D/SVGへの安全fallbackを明示の仕様として設計する。**サーバ起動時npm build/外部CDNの新規導入はしない**。GPUの高性能より、必要な文献を素早く絞り込めるUXを優先。

## 検証済み・未検証

- **確認**：Obsidian公式/Sigma.js/Graphology/SQLite公式資料と、GitHubのK3/Host/K1b/K4/K5実コードおよびPR #38のUI仕様を直接比較。K6c JSをV8 `new Function`で構文検査PASS、HTML参照ID欠落/重複0、CSS括弧整合、global/local詳細・Local AI手動Job導線を静的検査。
- **独立SQLite smoke（実施）**：100,500文献の同形`documents/collections/documents_coll_id`テーブルで、`EXPLAIN QUERY PLAN`が`documents_coll_id`索引を使用すること、50件ずつ次ページの重複なし、最大1001インデックス項目を読む下限Count、SELECTから元本文が漏れないことを確認PASS。**実ResearchDataHubのHTTP/SQLite統合テスト合格とは異なる**。
- **追加テストコード（未実行）**：`tests/test_knowledge_atlas.py`に本物のLiveServerとStoreを使ったkeyset/限界/zero-write/scope/metadata-only/巨大collection/Index検証、`tests/test_knowledge_atlas_workspace.py`でObsidian操作/Reduced-motion/タッチ/Host theme/ローカルAIの明示実行を静的検証。
- **未実施**：実Python unittest、`bash scripts/verify-k6.sh`、ControlDeck/Ubuntu/QNAP/iPhone WebKit/実LLM/資料数10万の物理Disk I/O、WebGLベンチ。コンテナからgithub.com DNSが解決できず完全checkoutできない。**Draftを維持、既存本番版0.5.12を変更・配布しない**。

## 次のCodex・本番ゲート指示

- まずK6c追加tests + K1a〜K6b全回帰 + `bash scripts/verify-k6.sh` + `WITH_QPKG=1 bash scripts/verify-k6.sh`を正規checkout上で実行。Python route Scope400/403/404、JSON件数・重複、SQLite index usage/total_changes/WAL、UI Node/Pointer/Touch/Pan/Zoom/Tab/Enter/Focus/ReduceMotionを端末で確認。修正は**PR #39内**で完結させ、細かい追加PRを乱立させない。
- 1,000/10,000/100,000文献の現実的な性能計測でpage取得・CPU・RAM・NAS disk writesを検証。大規模化の需要があれば**別K7 PRで**索引・検索・埋込AI・WebGLを導入し、data/provenance/scope/backward-compatibilityを先に設計する。
- main実ファイル/docs/manifest/tests/runtimeをPR #29→#39の全stackと比較し、Allowed/Do NOT/expected final stateを正確に確認。特に`ui.html` default、Vue read-only/non-default、backend authoritative、Host runtime `level_0_manual_only`/no execution、raw-source/fallback/redirect、server startup npm build、LLMクラウド漏えい、勝手なReview/Idea保存がないこと。
- 全検証後に依存順merge、リリース時にVERSION/QPKG_VER/CHANGELOG/addon manifestを一致させUbuntu/QNAP package health/iPhone画面を検証し正式Release。

**Expected K6c final state**：数多い文献を「全体の保存先→50件ずつの文献→K3出典と承認された知識」という段階的なObsidian風操作可能なマップで探索でき、ローカルAI知識抽出は人の明示操作により実行できる。AI推論/資料の所属/原文確認済みrelationは混ぜない。大量データでもread-only表示とno corpus-wide scanを維持する。
