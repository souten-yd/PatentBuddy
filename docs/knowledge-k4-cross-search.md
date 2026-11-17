# K4 — 審査済み技術エッセンスの横断検索・出典比較

**2026-11-17 / Draft PR #36。未マージ・未リリース。** 本実装はK3b PR #35 → K3 PR #34 → K2 PR #33 → K1d PR #32 → K1c PR #31 → K1b PR #30 → K1a PR #29をbaseとする。GraphRAGの大型PR #23は別Draftのまま。本PRは**read-only検索・手動比較**に限定する。

## 目的・受入条件

ResearchDataHubへ蓄積した複数の特許・規格・技術文献の解決原理/機構/成立条件/限界を横断検索し、利用者が異なる文献から**2〜3件を選んで並列比較**できるようにする。単語・原文引用をたどり、新しい発明に転用できそうな点を人間が検討する入口にする。**意味的な一致・新規性・進歩性・実現可能性・侵害判断をモデルが自動決定しない**。検索・比較で新しいGraph edge、review、Idea、Documentを保存しない。

## 正本・選別契約（Do NOTとexpected final state）

- 既存`document_analyses(kind=knowledge)`と`knowledge_reviews`、`knowledge_review_epochs`、`documents`のみ利用。別検索DB、永続向けベクトルIndex、クラウド検索エンジンを追加しない。
- **最新の人間reviewイベントが`decision=approved`**であることを必須とする。原文の`document_revision(hash+source)`・`source_epoch`がレビューと候補の両方に一致しなければ返さない。原文を一度変更し元に戻す、K2承認→却下→再承認、削除/改訂でも旧結果を自動復活させない。
- 候補のJSONはモデルを信頼せず、K1a `knowledge_essence.validate`で、モデル証跡形式（`execution_policy=local_only`等）、各itemの`basis=model_inference,review_status=unreviewed`、原文版・Unicodeコードポイント引用の完全一致・条件/限界フィールドを毎回再検証。人が承認しても`source_fact`にはしない。
- GET/POSTは**読み取り専用**で、SQLiteのINSERT/UPDATE/audit/自動キャッシュ作成・新しいバックグラウンドJobなし。検索語や未公開文献は外部LLM/クラウドに送信しない。既存`store.lock`により複数の照合を一貫した読取ビューで実施する。クライアント側は`textContent`で引用・推論を表示し、HTMLとして解釈しない。
- `docs/controldeck-ux-contract.md`に基づき、Host owns top-level shell/nav/theme/Bridge/auth。K4はPatentBuddy内部のコンテンツのみ、`ui.html` defaultを変更せず、Vue read-only/not default、backend authoritative、`level_0_manual_only`/no execution、raw source serving/fallback/redirect、サーバー起動時`npm build`を追加しない。

## API実装と性能境界

### 1. `POST /api/v1/knowledge/search`（権限`read`）
JSON:`{"q":"冷却","kind":"principle","limit":20,"cursor":0}`。すべて任意だが余分なフィールドは400。文字列`q`は最大120文字（改行/制御文字禁止）、`kind`はK1aの9分類か空、`limit`は整数1〜20、`cursor`は0またはsigned 63bit非負整数。boolean/SQL断片/不正kindは400。
- **レビューイベントの降順keyset pagination**を使い、SQL内部のレビューイベント走査をまず最大**241イベント**に限定してから、最新承認・source revision/epochを確認する。実際に判定する上限は毎回240イベント。承認済みを先にフィルタしてからLIMITすると、却下が大量にあるとSQLの走査が無制限になるため禁止。最新のapprovedでないreviewは読み飛ばしつつcursorを進める。
- 1レスポンス最大20 item。多い場合は`truncated=true,next_cursor=<last consumed review seq>`を返し、次回POSTでさらに古いイベントを探索。**ページをまたいでも未確認/旧版/不適合なitemは返さない**。検索上限だけで一致0件になり得るので、`next_cursor`がある限り「次の候補」を明示操作で続けられる。
- 永続FTSは追加せず、ローカルPythonの`casefold`による部分文字列照合を`statement/conditions/limitations/evidence.quote`に適用。語彙の意味的類似は現段階で検出しない。重い全文検索を無制限に実行しない。
- SQLite側`CASE WHEN length(CAST(content AS BLOB))<=131072 THEN content ELSE NULL END`、原文の`substr(body,1,100001)`で、巨大な既存データの読取量を限定。K1a validator通過前に外部へ返さない。対象文献の本文は絞り込んだ候補に対してのみ遅延取得。
- 応答は`items:[{proposal_id,item_index,doc_id,title,kind,statement,conditions,limitations,evidence:{start,end,quote},source_revision,review_status:'approved',basis:'model_inference',reviewed_at}]`、`next_cursor,scanned,scan_limit=240,limit,coverage='paged_review_events',truncated,note`。判定は承認済みAI推論であり検証済み技術的事実ではない。

### 2. `POST /api/v1/knowledge/compare`（権限`read`）
JSON:`{"items":[{"proposal_id":"abc","item_index":0},{"proposal_id":"def","item_index":0}]}`。**異なる文献から2〜3件**、項目の重複なし、IDは正規表現で制限。入力文献の生本文やモデルプロンプトは受け取らない。
- 選択IDをDBから再取得し、**比較実行時に**source revision/epoch/latest K2 approval/K1a exact quoteとHost証跡を再検証。画面で承認されていた時と現在の判断が変わった場合は**比較結果を返さない**。DB書き込みゼロ。
- 2〜3列（モバイルは縦）に各文献の`kind/statement/conditions/limitations/evidence.quote`と原文へ戻るボタンを表示。`shared_conditions_exact`、`shared_limitations_exact`は**文言完全一致のみ**。意味的に同じ/特許が新規/実現可能/同一発明という判断をしない。応答`comparison_type=side_by_side_literal,basis=model_inference`。
- AIが新しい関連を提案することも、Idea/Graph/Review保存も行わない。K5でUser-controlled Idea Canvasを追加するまで比較は閲覧専用。

### 3. ControlDeck Add-on Proxy
`POST /addon/v1/knowledge/search`・`POST /addon/v1/knowledge/compare`を既存Host Bridgeセッション認証の下で新設。ResearchDataHubへは既存**read token**のみを使用。`knowledge_propose`, `knowledge_review`, `knowledge_link`, `published`専用トークンからは両ルートへアクセスできない（HTTP403）。adminセッションは従来CSRF/Originチェック対象。本文各4KiBを上限にする。
- 検索語を**GETのクエリ文字列ではなくPOST JSON**で送る（URL履歴・URLアクセスログに未公開調査語を載せない）。検索はread-only POSTであって、mutation権限や実行権限の追加ではない。

## UI/UX（ControlDeck準拠）
- 文献を選択する前から使える「技術知識を横断検索・比較」を追加。キーワード、種類（9分類）、検索ボタン、根拠付き結果カード（タイトル/statement/conditions/limitations/quote）、原文のUnicodeコードポイント位置へ移動。
- 別文献から最大3件チェックボックスで選択し「選んだ知識を比較」を明示操作。選択なし・異なる文献が2件未満の場合は無効。比較結果はレスポンスの`side_by_side_literal`契約を確認し、事実認定・因果関係の断言をしない。
- 独立した「次の候補を探す」は`next_cursor`がある場合だけ表示し、ユーザーが押した時だけ次ページを取る。1回のサーバー走査上限240、画面の結果カードは**最大60件**に限定し、以降は検索語の絞り込みを案内。拒否・失効した候補を自動的に補完しない。検索・選択状態が変わったときは古い比較レスポンスを破棄する。
- Desktopは2〜3列で並列カード。iPhone 320px〜767pxは単一カラムで入力16px/タップ44px、`prefers-reduced-motion`、Hostテーマ変数とAccentに準拠。原文・推論・比較欄はDOM `textContent`、外部CDN・独自UI frameworkなし。空・読み込み・再接続・失効・上限・再試行の行先を持つ。

## 実施した確認 / 未検証
- **実施**：GitHubを介してPR #35/mainのAuth/API/Store/K1a〜K3b/ControlDeck UI実ソースを直接確認し、K4の差分と安全境界を照合。K4 JSをV8で構文検査、JS参照HTML ID欠落0/重複0、read-only代理API/モデル根拠/60件/44px/16pxを静的検査。
- **実施**：独立のPython SQLite環境に同形の`documents/document_analyses/knowledge_reviews`テーブルを作り、keysetページ順と最新review seq判定SQLを実行。承認後却下された旧イベントを除外し、異なるページに跨って候補へ進めることを確認。
- **追加・未実行**：`tests/test_knowledge_cross_search.py`（実LiveServer/SQLite、approval/revocation/原文revert、2〜3文献、先頭/続き/上限、scope/CSRF、write0）、`tests/test_knowledge_cross_workspace.py`（Controls/Hostテーマ/原文引用/安全DOM/モバイル）。
- **未実施**：これらのPythonファイル本体の実行、K1a〜K3b回帰、`bash scripts/verify.sh`, `node --check qnaplibrary/web/addon-workspace.js`, `bash scripts/build-linux.sh dist`、実ResearchDataHub/ControlDeck Host QNAP/Linux/iPhone Safari/低I/O性能測定。作業コンテナからgithub.comのDNS解決不可で完全checkoutできず、GitHub Actions自動実行は0件。合格済みと主張せず**Draft・未マージ・未リリース**。

## K5 Codex詳細指示 — Idea Canvasへの受け渡し
1. **先にK4を検証**：PR #36を実repo checkoutして全新テスト＋K1a〜K3bの回帰と`verify.sh`、Linux/QPKG build、ControlDeck Host/ResearchDataHub/http auth/iOS実機を確認。特に大量の却下イベントの存在下でも240 raw reviewイベント以内でqueryが止まることをSQLite EXPLAIN QUERY PLAN/実負荷で確認し、no-write/WAL/IO/Concurrent updateを測る。問題があれば小さな同PR修正で対処。
2. **K5 Idea Canvasの新機能**：比較した2〜3件のK2承認済みエッセンスを明示的な入力に、`problem/known_solution/conditions/limitations/effect/application`などの仮説カードを作れるUIを設計。AIでの自動idea保存・自律発明・自動特許出願は禁止。作成・保存・出力は人が明示ボタンで確認した場合のみ、新しい狭い権限と人間の編集履歴を持つ。
3. **根拠と安全境界**：Ideaの各文にはsource doc/proposal/item/revision/review epoch/review seq/quote（必要ならGraph edge）を保持。原文/レビュー/関係の版が変わればIdeaを`needs_revalidation`に失効させ、旧証拠による自動復活なし。新規性/進歩性・侵害を法的に自動認定せず、先行技術調査の再検索候補として分ける。
4. **AI活用は限定・任意**：未公開発明はControlDeckの**local-only/provenance必須Host**のみで、ユーザーが明示的に提案作成を押した場合に検討。できる/できないを安全に分け、クラウド(OpenRouter等)へのフォールバック・自動実行・外部送信禁止。LLMによる`idea_hypothesis`は人間採用前に事実扱いしない。
5. **UI**：ControlDeck Host shell/nav/themeを継承し、Desktopは検索/比較/Idea Canvasの段階的導線、mobileは選択リスト→根拠→仮説カード。オフライン/空/権限/429/409/サーバー再起動の出口と、キーボード・スクリーンリーダー対応を用意。別のCDN/ライブラリ導入を慎重に検討し、原則追加しない。
6. **PR運用**：K5を1つの独立PRで安全なスコープから段階実装。既存PR #23のGraphRAG/Host証跡重複を全diffで照合。PR #29→#36のstackを実mainファイル/docs/manifest/tests/runtime、Allowed/Do NOT、UI default/Vue/Host/実行と照合し、**全テスト実行**後に依存順にレビュー/マージ。正式Release時のみVERSION/QPKG/addon manifestの3点一致を更新してLinux/QNAP/iPhone healthまで確認。追加小PRを量産しない。

**Expected final state（K4）**：人間承認済み・現在版のモデル推論を、ResearchDataHubから読み取り専用・上限付き・続き取得可能な方式で複数文献横断検索し、条件/効果/限界/引用を2〜3文献で比較し、元文献へ確実に戻れる。意味的解釈・法的結論・Idea書込は後段の明示操作に分離する。
