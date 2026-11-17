# K3b — K2根拠付き技術仮説の明示的な関係登録・審査

状態：**Draft PR #35（2026-11-17）／未マージ・未リリース**。base：K3 Draft PR #34 → K2 #33 → K1d #32 → K1c #31 → K1b #30 → K1a #29。PR #23はGraphRAGの大規模Draftのまま。K3bは**承認済みの技術エッセンスから別の文献への仮説を、人が選択して登録する機能**。外部LLMを呼ばず、事実認定も行わない。

## 前提の実コード確認
- [PR #23 evidence_graph.py](https://github.com/souten-yd/PatentBuddy/blob/feat/evidence-graph/qnaplibrary/evidence_graph.py) の `graph_nodes`, `graph_edges`, stale trigger, `save`, `review`, `expand`を引き続き唯一の関係保存として利用する。K3bではPR #23のグラフに別テーブルを重複生成せず、同一SQLiteの小さな`knowledge_link_origins`のみ追加。GraphRAG `save/review`には内部引数`_connection`を加え、K2の根拠検証と同じtransactionで呼べるようにした。引数省略時のPR #23インターフェース/振る舞いは維持する。
- [PR #23 relation_proposals.py](https://github.com/souten-yd/PatentBuddy/blob/feat/evidence-graph/qnaplibrary/relation_proposals.py) は`document_analyses(kind=relations)`からAI生成提案を登録する経路で、今回のK1a〜K2 `kind=knowledge`とは異なる。**同じ生成候補を二重にLLM抽出することは避け**、K2で承認されたknowledge itemのquote/条件/Host provenanceを使って明示的に人が別文献と紐づける。後からPR #23のrelation flowを導入するときは差分確認・重複排除が必要。
- K2では`source_revision`と単調増加`knowledge_review_epochs`の両方を利用し、原文を変更後元に戻しても旧承認を復活させない。K3bではさらに**K2最新レビューの`seq`**をリンク作成時に保持し、K2が却下→再承認されても古いリンク承認が復活しないようにする。

## 操作フロー
1. ControlDeckの文献詳細でK2人間レビュー済みの知識カードを選択。原文の一意な引用・技術原理/効果/成立条件・限界を確認する。
2. 「別文献と技術仮説リンクを作成」を開き、保存済み特許を既存の検索機能で探してターゲットを指定する。ターゲットの確認は`GET /api/v1/documents/{did}/link-target`で`id/title/revision`だけ取得し、**本文や請求項全文を不要に転送しない**。
3. 関係種別はPR #23の`INFERRED`：`problem/solution/effect/substitution`だけ。公開分類の`citation/family/requirement`等の`factual`を選択・作成できない。初期は未選択。
4. ユーザーが「引用と関係先を確認し、仮説として登録する」を明示チェック後、登録ボタンを押す。**専用scope `knowledge_link`（またはadmin+CSRF）**だけが`POST /api/v1/documents/{did}/knowledge-proposals/{pid}/links`可能。K2のlatest decisionが`approved`かつsource revision+epoch+review seq一致、quoteが原文と完全一致、ターゲットの版がユーザー選択時と一致、異なる文献IDであることを同一DB transaction内で検証。
5. GraphRAGの`save(...,_connection=db)`により`graph_edges`へ`basis=inferred,review_status=unreviewed,confidence=0.0`で保存。モデル証跡を`model_ref:runtime_ref`として引継ぎ、原文のUnicode位置・retrieved_at/methodを添付。技術的事実への変換・自動承認・外部送信なし。
6. リンクは未承認の一覧に表示する。人は別途リンクの引用・関係先を確認して承認または却下を選択、確認チェックを付けて`POST /api/v1/knowledge-links/{eid}/review`で判断を保存。`expected_graph_revision`の版競合ならHTTP409。**承認してもbasisはinferredのまま**。失効した引用、K2承認の撤回、ターゲットの変更、K2のreview seq更新時は再承認できない。
7. K3のKnowledge Mapは既定でfactual GraphRAGと現行版K2確認済み知識だけ。仮説リンクは独立チェックボックス「人が確認した技術仮説リンクも参考表示」を選んだ場合だけ、`include_links=true`で**人が承認済み/現在版K2承認が継続/元review seq同一**の関係を最大8本表示。外部AI提案の未確認リンク、PR #23のその他inferred辺は表示しない。描画は点線、Inspectorに「人が確認した技術仮説（事実ではありません）」と明記。

## API・認証
- GET（既存read権限、最大30リンク）：`/api/v1/documents/{did}/knowledge-links`。新しい書込権限だけのトークンからのGETは禁止。リンクが以前承認済みでも、最新のK2レビューが変わった場合は`review_status=unreviewed,stale=true,previous_review_status=approved`として表示。旧判断は残すがactiveではない。
- GET（既存read権限）：`/api/v1/documents/{did}/link-target`。ID、タイトル、版のみ。本文・秘密は新たな公開経路にしない。
- POST（新規`knowledge_link`専用）：`/api/v1/documents/{did}/knowledge-proposals/{pid}/links`（未確認リンクの登録）、`/api/v1/knowledge-links/{eid}/review`（承認/却下の別操作）。他の全APIは同じ`qle_`専用トークンでHTTP403。pairingには追加しない。adminは既存CSRF/Origin下でのみ可。
- Linux同UID UDS`knowledge_link`で専用tokenを渡す。QNAP/遠隔PCでは別`knowledge_link_token`を管理者が用意する。旧read/rw/analysis/knowledge_propose/knowledge_reviewトークンを流用しない。ControlDeckのWeb UIには`knowledge_link_available:bool`だけ渡す。シークレットをHTML、console、audit、URLへ入れない。
- `knowledge_link_origins`は`graph_edges(id)`と`document_analyses(id)`へのFKを持ち、`proposal_id,item_index,source_doc_id,source_epoch,source_review_seq,target_doc_id`を保持。GraphRAG以外の関係正本を作らない。データ削除時はFK cascade。生成元approvalが更新されたら旧リンクは明示的な再登録・再審査まで無効（同一文書への復元でも復活なし）。
- 同じ原文/レビューイベント/ターゲット版/関係種別の再送はdeterministic link IDで**追加write0**。別版/別レビューを登録すると新IDになる。旧`graph_revision`のレビューは409で拒否。監査はリンクIDと判断だけ、原文/発明内容なし。

## UI/UX / 使用可能範囲
- ControlDeck Embedded Workspaceに、文献検索→選択、確認済み知識の選択、引用確認、関係種別、1段階目の登録、2段階目のレビューを配置。選択前のボタンは無効。必要なボタンは44px以上、iOS入力16px、モバイルは1カラム/タップ操作、Hostのtheme/accentとreduced-motion継承。raw quoteは`textContent`のみでinnerHTMLへ流さない。
- 未確認/承認済み仮説/却下/失効を文字で表示し、版競合・認証不足・接続失敗は次の操作と再読み込みを案内。登録だけでマップへ自動採用されない。参照元・関係先は既存文献ページへ移動可能。Mapには別の明示チェックがある。
- PCは既存K3のマップ＋右Inspectorを維持し、仮説は点線で表示。320〜767pxは一覧→詳細→根拠。別のReact/Graphライブラリ/CDN・ControlDeck shellを増設しない。

## 検証状況（2026-11-17）
- **静的検証済み**：PR #23 GraphRAGとK2/K3の実ファイルを直接確認。K3bのJSをV8で構文チェックPASS、HTMLのJS参照ID欠落0/重複0、ControlDeck Hostテーマ、44px/16px、textContent、scope分離、no cloud/fallback/no exec/no new graph engineを確認。
- **独立SQLite smoke PASS**：Graphテーブル作成より前のFK宣言、review最新行JOINとread-only、emoji入り引用のUnicode substr、原文復帰時のepoch増加、旧K2 approvalのsource_review_seqによる失効、Graph edge削除でorigin cascadeを確認。
- **追加テストファイル（本repo環境では未実行）**：`tests/test_knowledge_links.py`（real Store/LiveServer/HTTP、K2 approval前後、2段階、inferred-only、revert/reapprove、same-ID write0、version409、token scope、AddonClient）、`tests/test_knowledge_link_workspace.py`（明示操作、アクセシビリティ、source/target/quote確認、Host shell非重複）。
- **未実施・マージ前必須**：`python3 -m unittest -v tests.test_knowledge_links tests.test_knowledge_link_workspace tests.test_knowledge_map tests.test_knowledge_reviews`、K1a〜K3a含む全`bash scripts/verify.sh`、`node --check qnaplibrary/web/addon-workspace.js`、`bash scripts/build-linux.sh dist`、ControlDeck/ResearchDataHub本番同等モデル＋HTTP＋Ubuntu/QNAP/iPhone WebKit E2E、SQL並列競合/負荷・物理ディスクI/O。現在の作業コンテナはgithub.comのDNS解決不可で全repository checkoutできないため、新規PythonテストをPASS済みとは言わない。**Draft維持、マージ/正式リリースなし**。

## 次のK4 Codex向け指示
1. **まずK3bのテストを実行・修復する**。実Repoで新SQL table FK / trigger / CASCADE / GraphRAG `_connection`の既存PR #23テスト回帰、Review version guard、Unicode emoji quote、認証行列、API schema、ControlDeckテーマ/320px/iPhoneでE2E。source/target同時更新、source版戻し、K2承認→却下→再承認の厳密失効、リンクID再送write0、旧graph_revision409、出典が一致しない場合の全体rollback、Graph node label driftを必ず確認。
2. **K4の解決エッセンス再利用検索**：既存の知識正本から`kind/conditions/limitations`を条件とした読み取り専用検索を追加（まずSQLite FTS/構造化検索を再利用し、別ベクトルDBは作らない）。人間レビュー済み・source revision/epochが現行の知識だけを既定検索結果へ出す。inferred linkもデフォルト検索では無効。検索クエリに秘密の未公開請求項をCloud APIへ流さない。
3. **横断比較**：似た課題で異なる解決原理・成立条件・制約/効果を2〜3件選んで「類似/差異/異分野応用候補」を`idea_hypothesis`で提示。既定はread-only仮説。ユーザーが明示するまでIdeaをDB保存/Graph link採用しない。出典doc/revision/quote/reviewer/限界を必ず残す。法的な新規性判断や侵害判断は決めつけず再調査を促す。
4. **UI**：ControlDeckのSegmentedTabs相当「知識を検索 / Map / 比較」をHostシェル内に実装。PCは一覧/条件とInspector、モバイルはリスト、全読み込み/空/権限/切断/再試行の状態を設ける。原文/引用リンクはiOSで維持。新CDN・別UIフレームワーク・全件描画・自動Jobなし。
5. **検証からマージまで**：PR #29→#30→#31→#32→#33→#34→#35をmain実ファイルとscope/Allowed/Do NOT/expected stateで点検、全テスト・CI buildを実際に完了してから依存順にmerge。PR #23の未マージGraphRAG全体は重複しないよう必要部分を段階採用し、版3点整合・正式Release・QNAP/Linux health・iPhone UXまで確認する。少量修正は次のPRにまとめ、細分化PRを増やさない。

**Expected final state（K3b）**：選択した文献のK2承認済み知識から、別文献に対する仮説を引用根拠付き・専用権限下・2段階の人間操作で登録/審査できる。推論は最後まで推論であり、既定の事実検索と分離される。関連づけの結果は1〜2hopのKnowledge Mapに明示opt-inでだけ表示される。
