# K3 Knowledge Map — ResearchDataHub正本とControlDeck表示の詳細設計

状態：**Draft PR #34**（2026-11-17）。baseはK2 Draft PR #33→#32→#31→#30→#29。PR #23は既存GraphRAGの別Draftで未マージ。**K3は読み取り専用の制限付き可視化**であり、技術的な関係の自動登録やアイデア統合は未実装。

## 目的と既存機能の再利用
- 根拠となる文献と「課題・原理・手段・機構・効果・応用」の知識エッセンスを、Obsidian型の接続図で辿る。マップを眺めるだけで未公開の発明・請求項を外部へ送らない。
- GraphRAGは[先行Draft PR #23のevidence_graph.py](https://github.com/souten-yd/PatentBuddy/blob/feat/evidence-graph/qnaplibrary/evidence_graph.py)を**同じソースとして導入**。Schemaと版変更トリガーも同じResearchDataHub SQLite内にインストールする。別グラフDB、Graphサービス、CDN、フレームワークは新設しない。K1dのgeneration_contractもPR #23から既に導入しているため、後でPR #23を統合する際には**重複差分を消して1実装に揃える**。
- K2の`document_analyses(kind=knowledge)`と`knowledge_reviews`を読取して描画する。技術的な関係はGraphRAGの`graph_edges`から取得できる場合だけ表示し、AI文面の類似や知識種類から**意味的なリンクを捏造しない**。

## データ・権限・上限
- `GET /api/v1/documents/{did}/knowledge-map?hops=1|2&include_unreviewed=false|true`: ResearchDataHubの既存read認証のみ（admin/ro/rwなど、公開専用・knowledge_propose・knowledge_reviewスコープは不可）。POSTやdelete APIはK3では追加しない。
- ControlDeck Add-onの`GET /addon/v1/documents/{did}/knowledge-map`は従来のHost認証を通し、GETだけを別のread資格で転送する。queryはhopsとinclude_unreviewedだけの単一値を許可。リダイレクトやraw-source公開はしない。
- Server固定上限：全体**36ノード/52接続**、GraphRAGへ割り当てるのは最大24ノード/36接続、Hop数は1または2。Knowledge snapshotsは最新20件だけを読取。上限に達したら`truncated=true`を必ず表示。無制限拡張や大容量の全件Graph描画は禁止。
- 既定`include_unreviewed=false`：**現在原文版とレビューepochが一致し、人が承認したモデル推論ノード**と、PR #23の`approved,stale=0,basis=factual`な事実関係だけ表示する。K2の`approved`はhuman-reviewedな**AI推論**であって、特許性・法的な事実認定にはならない。
- 明示的なチェックボックスで`include_unreviewed=true`：未確認・却下・差戻し・旧版知識候補を**参考表示**する。これらは関連性探索に採用せず、既定で表示しない。PR #23の**inferred GraphRAG関係はこのチェックを入れても表示しない**（K3bで別の明示条件・review契約を整備してから検討）。
- 文献→知識候補の接続は`relation=proposal_evidence_source,basis=provenance_only`と明記。技術的因果関係や類似の立証ではない。GraphRAGの事実関係だけ`basis=factual`として方向・quote・doc_id/revision/offsetを示す。
- 追加の生データを取得しないようGraphRAG引用はSQLite`substr(body,start+1,end-start)`でUnicode文字単位の最大4,000文字を再照合。知識の原文本文は必要な場合にだけ1度遅延読込み、現在の版に対してK1aの厳格なquote/provenance検証を行う。旧版は原文移動ボタンを無効にする。
- DB読取は`store.lock`で一貫化。GETや初期表示でSQLiteのINSERT/UPDATE/auditを行わない。追加書込はK2の実際の文献内容変更時の単調増加review epoch triggerに限り、K3で新しいバックグラウンド作業は開始しない。

## UI/UX: ControlDeck準拠
- 文献表示内にKnowledge Mapを追加し、**Hostのグローバルナビ・ヘッダー・認証を二重表示しない**。Host Bridge`theme.changed`/connectedのaccent/bg/surface/text/border/mutedを使用。カード/余白/44px touch/16px input/reduced motionを尊重。
- PC：接続図の放射配置（SVG、ローカル静的JS、外部グラフライブラリなし）、一覧、右インスペクタ。ノード選択で種別・承認/失効/モデル推論・成立条件/限界・出典quote・関係方向/根拠を表示。原文リンクは既存`openDocument`→`focusKnowledgeEvidence`（Unicode code point再照合）。
- モバイル320px〜767px：巨大SVGを縮小せず**一覧→詳細カード→出典**。SVGは非表示、キーボード操作できるbutton一覧から選択可能。スクリーンリーダーが意味を失わないよう一覧・ステータス・ラベルを付ける。
- Loading、空状態、通信・認証エラー、再取得ボタン、`truncated`表示。未確認の情報を色だけで区別しない。GraphRAG実体のない新規導入直後は「審査済み関係がまだない」状態で表示し、リンクを捏造しない。
- K2レビュー判断が成功、またはK1dの知識抽出ジョブ完了時はMapを再読取。ネットワーク切断時に古い結果を採用せず、currentDoc/request idを照合する。

## 変更ファイル（K3許可スコープ）
- `qnaplibrary/evidence_graph.py`（PR #23の同一ソース）、`store.py`（PR #23スキーマ設置＋K2 epoch安全修正）、`knowledge_map.py`（新規read-only投影）、`api.py`と`server.py`（GETのみ）
- `web/addon-workspace.html/js/css`（MapとInspectorおよびMobile一覧）
- `tests/test_knowledge_map.py`, `tests/test_knowledge_map_workspace.py`（実SQLite/HTTP + UI契約回帰コード）
- docs/knowledge-k3-map.md, docs/HANDOFF.md, docs/CODEX_NEXT.md, docs/roadmap.md, docs/controldeck-ux-contract.md（進捗・次工程・制限）
- K2ブランチの追加安全修正`knowledge_review_epochs`、review `source_epoch`と失効比較をK3にも同期する。文献変更後に旧原文へ戻した時にも**昔のapprovalが自動復活しない**。旧K2スキーマはsource_epoch=-1として安全側で失効。

## Test matrix / 実行状態
- **実装したテストコード**: 初期値は承認済みのみ、opt-in時だけ未確認表示、人間承認してもbasis=model_inferenceのまま、PR #23のfactual 2-hopのみ、推論graph edge除外、原文改訂→graphとレビュー失効、旧原文へ復帰→承認が復活しない、Unicode emojiの前後引用、36/52上限・truncated、GETのwrite0、匿名/公開専用/書込専用トークン403、bad query 400、No mutation route、ControlDeckテーマ/320px/根拠リンク・innerHTML非使用。
- **実施済み**: ControlDeck/PBの実mainとPR #23/#29〜#33の実ファイル/スキーマ確認。K3 JavaScriptをV8で構文検査**PASS**、HTML全ID参照に欠落/重複なし、44px、Mobile list、Hostテーマトークン、引用のtextContentと原文検証を静的確認。PR #23のGraphRAG code SHAを同じ内容として確認。
- **未実施**: `python3 -m unittest -v tests.test_knowledge_map tests.test_knowledge_map_workspace`、K1a〜K2を含むPython全体、`node --check`のnode CLI、`bash scripts/verify.sh`、`bash scripts/build-linux.sh dist`、実RDH/ControlDeckホスト・QNAP/iPhone・性能/物理disk I/O。作業環境ではgithub.comのDNS解決不可で全repo checkoutできない。テストコード作成は合格済みを意味しない。手元で実際に検証した範囲以上の完了を主張しない。

## 次のK3b/K4 Codex実装指示（詳細）
1. **K3b明示的な技術関係登録**：先行PR #23の`relation_proposals.py`、`evidence_graph.save/review`、`chart_storage`、Graph APIと現行K1a〜K3の実diffを照合。既存PR #23が追加している仕様・修正を二重実装しない。承認済み知識ノード間の技術的関連リンクはAIに勝手に書込ませず、引用・条件・レビュー状態を人間が確認して**別の明示的権限**で登録する。モデル推論のhuman approvalをfactual edgeに変換しない。資料更新→リンク・依存Idea/Chartがstaleで自動再承認なし。改訂時のepochも確認する。
2. **K4知識再利用の検索**：複数の調査で使う解決エッセンスのタイプ別・条件別・効果別の検索と、既存Graph 1〜2hopの組合せを提示。異分野応用は`idea_hypothesis`として明示ラベル付けし、出典/制約/検証不足と元文献へのリンクを残す。複数文献の類似だけで“同一発明”と断定しない。
3. **UI**：ControlDeckと同じテーマ・アクセント・PageHeader/Jobs・1主操作、PCはmap+right inspector、iPhoneは単一ペイン。深いリンク/戻る/焦点移動・アクセシブルなMap一覧、オフライン・未権限・取得失敗の出口を整備。追加ライブラリ/CDN・Host shell二重化を禁止。
4. **検証ゲート**：実Host local_only/provenance→保存→human review→K3 mapを合成文献でE2E、Graph登録/削除・revision/epoch、同時更新・race、token scope行列、SQLite total_changesとWAL、巨大資料/計測、1280/768/390/320ブラウザ、QNAP/Linux build、`scripts/verify.sh`。追加修正が小さければ次のPRに同梱し、不要な細分化PRを避ける。
5. **マージと正式リリース**：#29→#30→#31→#32→#33→#34をmain/実コード・all tests・Allowed/Do NOT/expected final stateで検証し順次統合。PR #23は古い大規模Draftのため差分を整理してから別途採用し、今回移植した`generation_contract.py`と`evidence_graph.py`を二重にしない。version/QPKG/addon manifestを3点一致させるリリースPR、build/Actions、QNAP/Linux healthとiPhone実機確認後に正式Release。

**Expected final state K3**：User-selectedな1文献の関連証拠ノードと人間確認したAIエッセンスが、正本SQLiteから上限付き/read-onlyで表示され、関係方向・引用・原文版・人間判断・失効状態まで戻れる。意味的な技術リンクや自律アイデア生成は後段で、無断に作らない。
