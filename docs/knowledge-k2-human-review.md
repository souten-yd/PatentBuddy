# K2 — 根拠付き知識エッセンスの人間レビューと版失効

**状態：Draft PR #33（2026-11-17）／マージ・リリース未実施**。K1d PR #32 → K1c PR #31 → K1b PR #30 → K1a PR #29への依存を維持。GraphRAG PR #23は別Draftであり、K2から自動Graph登録はしない。

## 目的・完成条件

文献の技術知識候補（常にAI推論・未確認）に対し、人間が明示操作で「承認」「却下」「差戻し」を記録する。原文や出典が変化すれば旧判断を**失効**させ、再確認前に承認状態へ戻さない。保存先はResearchDataHubの既存SQLite正本ひとつ。ControlDeckは認証/Embedded View/UIを所有し、PatentBuddyは機能領域のみを描く。

### データモデル（K2で実装）
- `knowledge_reviews`：`seq`順のappend-onlyイベント、重複不可の`request_id`、`proposal_id`（既存`document_analyses(kind=knowledge)`参照、CASCADE削除）、`item_index`（0〜11）、`decision`、`source_revision`、`reviewer`、`created`。既存Store.SCHEMAへの冪等な加算のみ。別DBや別の生成結果正本を作らない。
- `approved`/ `rejected`/ `changes_requested`の判断イベントは上書きしない。最新判断は`seq`最大で決定。新しい判断を記録しても過去のイベントを削除・書き換えない。同一ID/同一内容/同一reviewerの再送は**書込0**。異なる内容への同一ID再使用は409。
- 審査前に**同じSQLite write transaction内**で文献のID・版・本文、保存済み候補の原文引用範囲・Host生成証跡形式、indexを再検証。原文/版の競合はHTTP409。モデル出力由来の`model_inference`は承認後も`source_fact`に変えない。
- `knowledge_store.list_for_document`のGETは、最大20件の候補について項目ごとの`reviews`を読取専用で付与する。原文改訂時は`status=unreviewed,stale=true,previous_decision=旧判断`として表示し**旧承認を有効扱いしない**。学習用Graphにレビューだけで即登録しない。
- `GET /api/v1/documents/{did}/knowledge-proposals/{pid}/reviews`は直近30イベントに限った読取専用履歴。秘密の本文/請求項を監査ログに記録しない。auditにはイベントID・判断だけを記録。

### 認証・API境界
- POST `/api/v1/documents/{did}/knowledge-proposals/{pid}/reviews`は新しい**knowledge_review**専用スコープか、既存管理者セッション＋CSRF/Originチェックのみ。
- 新しいscopeとtokenは既存`knowledge_propose`（AIが未承認候補を保存）、`analysis`、`rw`、`ro`、`published`、`pdf_import`とは別。既存トークンへのレビュー権限追加なし。reviewトークンでは**上記レビューPOST以外のAPI、文献GET、コレクションGET、一般分析POSTも403**。
- 同UIDのLinux Unixソケット`knowledge_review`とランダム`qlv_`トークンを追加。LAN/QNAPのリモート接続では別の`knowledge_review_token`を管理者が明示発行し`connection.json`へ保持（権限0600）。既存read/write tokenへフォールバックしない。認証情報をWeb/ログ/API応答に含めない。
- Reviewerはサーバーで信頼できる`admin`または`device:<device_id>`として採番。**この方式は個々のControlDeckユーザーの本人署名・本人確認を証明するものではない**。ControlDeckのユーザー単位証跡が必要ならHost側の署名済みprincipal契約を別途設計し、フロント入力のreviewer名を信用しない。
- Add-onではHost Bridgeで認証した操作だけをルーティングし、`reviewAvailable`相当はboolのみを画面へ渡す。読み取りは既存read token、レビューPOSTはreview token、知識生成はpropose tokenで分離。

### ControlDeck準拠のUI
- 文献の画面では従来どおり**主操作1個「知識を抽出」**。各知識カード内のレビュー詳細（progressive disclosure）を開き、判断を選択してから明示ボタンで保存。選択前はボタン無効。
- 受信後はGETで確定状態を再取得し、AI推論/未確認・人間承認/却下/差戻し・失効を文字で表示。承認しても「技術的事実の確定ではない」と常に明記。Review historyはグループのdetails内から**ユーザーが開いた時だけ**読取り、最大30件を表示。
- 権限がない、文献が旧版、403/409、通信断では「原因と次の操作」を表示。409は再取得を促す。画面側で自動承認/再承認しない。
- 既存ControlDeck HostのBridgeテーマ/アクセント、44pxタップ領域、BottomSheetに近い詳細展開、iPhone単一カラム、キーボード、reduced motionを維持。opaque iframeからHost React内部をimportしない。原文/LLM出力はtextContentを使いinnerHTMLへ入れない。

## Scope / Allowed（今回のPR）

- `qnaplibrary/knowledge_reviews.py`（新規）、`knowledge_store.py`（GETにreview overlay）、`store.py`（同一SQLiteへのappend-only履歴DDL）
- `api.py`, `auth.py`, `local_auth.py`, `server.py`, `addon_client.py`（専用token/UDSとPOST/GETに限定したルート）
- `web/addon-workspace.js/css`（明示レビュー操作・進捗・stale/履歴）
- `tests/test_knowledge_reviews.py`, `tests/test_knowledge_review_workspace.py`（新規）
- `docs/knowledge-k2-human-review.md`, `docs/CODEX_NEXT.md`, `docs/HANDOFF.md`, `docs/roadmap.md`, `docs/knowledge-graph-design.md`（状態・設計・次工程）

## 検証の現状
- **実施済み**：GitHub上のmainとPR #23/#29〜#32の実ファイル/契約を照合。K2 JSのV8構文PASS、HTMLの参照ID欠落・重複ゼロ、theme.changed/アクセント、quote textContent、権限と旧版判定を静的確認。SQLiteに同形のreview履歴テーブルを作り、項目ごと最新seqを引くSQLを独立実行して期待通りの3行を確認。
- **追加済み・未実行**：K2のLiveServer/実SQLite/auth/UDS/履歴/冪等/APIテストとUI contract test。PRの追加テストを全PASS済みとして扱わない。
- **未実施**：リポジトリ本体の`bash scripts/verify.sh`、`node --check qnaplibrary/web/addon-workspace.js`、`bash scripts/build-linux.sh dist`、実Host/RDHへのレビューE2E、デバイス発行/QNAP/iOS画面実機・I/O計測。コンテナからgithub.comをDNS解決できずrepo全体のcheckoutができない。**Draft保持・本番未リリース**。

## K2マージ前の必須試験
1. `python3 -m unittest -v tests.test_knowledge_essence tests.test_knowledge_generation tests.test_knowledge_store tests.test_knowledge_host_provenance tests.test_knowledge_host_jobs tests.test_knowledge_workspace tests.test_knowledge_reviews tests.test_knowledge_review_workspace`
2. 既存全回帰`bash scripts/verify.sh`、JS構文`node --check qnaplibrary/web/addon-workspace.js`、`bash scripts/build-linux.sh dist`。全テスト実行前にパス・import・Authの既存挙動を読む。失敗は**このPRに含めて修正**し、小さな修正だけのPRを量産しない。
3. 実RDH HTTP: admin＋CSRF、各scope全組み合わせ、同UID UDS、レビュー前後のreadとwrite、同一request_id再送のwrite0、違う判断の409、本文更新直前/後で旧approval失効、削除時CASCADE、段階的decision変更、局所Graphを誤用しないことを確認。
4. ControlDeck PC/iPhone: 320/390/768/1280、テーマ/アクセント、キーボード、焦点、失効カード、履歴ロード失敗・再試行、Host Bridge認証、ゼロ/1/12件、公開/未公開文書を確認。
5. 背景Jobは従来どおりlocal_only・証跡必須で未公開情報を外部へ送信しない。新たな自動保存/承認・自律実行・raw source配信・CSP緩和/redirectなし。

## 次のK3へのCodex向け詳細指示
- 先に**PR #23のGraphRAG部分の実main差分を再評価し、レビューと出典ベースのgraph_nodes/graph_edgesへ統合**。今回のK2で承認してもK3までグラフへ自動登録しない。`review_status=approved`のモデル推論は人間承認の「提案」であって、原文事実や特許性の判断ではない。factual edgeへの昇格には別の根拠・review contractを必要とする。
- K3 Graph Query: 探索は**1〜2hop、最大node/edge、truncated**をserverから明示、approvedかつstale=falseのリンクのみ既定検索で参照。単一正本DB、source引用のUnicode範囲→文献へ戻る、bidirectional deep link、更新時の辺/依存アイデアの失効伝播、人間の再承認は自動では行わない。
- K3 UI: [ControlDeck UI/UX規範](controldeck-ux-contract.md)に準じ、PCは部分Graphと右Inspector、iPhone 320pxは知識一覧→Card→根拠。Host Shellとナビは二重化しない。大量nodeの全件描画/CDN/独自デザインシステムを禁止。Job状態、進捗、Offline/Reconnecting/Emptyの出口を実装。
- K3のScope/Allowed/Do NOT/Expected final stateをPR本文に明記し、PR #23の既存レイアウト・データモデルを**移植する前に整合確認**。小修正は次予定PRへ同梱。バージョンは最終検証・正式Release直前に3点整合して更新。

## 追補: 同じ原文への復元でも旧レビューを復活させない（2026-11-17）

従来の`source_revision=sha256(hash,source)`のみで失効判定すると、本文変更後に同じ文面へ戻した際に旧approvalが自動復活しうる問題を修正。既存ResearchDataHub SQLiteに`knowledge_review_epochs(doc_id,epoch)`を置き、`documents.hash/source`が実際に変化するUPDATEだけでepochを単調増加させるDB triggerを追加。reviewイベント自体はappend-onlyで`source_epoch`を記録する。GETで現行epochとレビューepochを照合し、内容が元に戻った場合も旧承認は`status=unreviewed,stale=true`で再承認が必要。無変化の文書更新や読取はepochの追加writeなし。

初期K2 Draftで作った古い`knowledge_reviews`テーブルには一回だけ`source_epoch DEFAULT -1`をALTER追加し、証跡がなかった旧イベントは安全側で失効。新イベントのepochは0以上。既存レビュー履歴は保持。テスト`test_reverting_document_text_does_not_reactivate_old_review`を追加したが**LiveServerテストは未実行**。K3 mapはこのepoch境界を利用する。
