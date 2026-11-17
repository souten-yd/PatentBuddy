# K5 Idea Canvas — 明示操作・出典固定・失効・編集履歴

状態：**2026-11-18 / Draft PR #37**（base: K4 PR #36 → K3b #35 → K3 #34 → K2 #33 → K1d #32 → K1c #31 → K1b #30 → K1a #29）。PR #23の大型GraphRAGは別Draft。**K5は利用者が入力・確認した発明仮説を保存する機能であり、自律AI発明・自動出願・技術的事実認定は行わない**。

## Scope / 絶対に維持する安全境界
- ResearchDataHubの**既存SQLite**が唯一の正本。新しいDBファイル、Graphエンジン、LLM Provider/CDN・ベクトルIndexは追加しない。
- K4で**人間が承認した現行版のK2知識**を異なる文献から2〜3件比較した場合のみ新案の出典として選べる。AI推論の`basis=model_inference`を事実に変更しない。Ideaは`basis=manual_hypothesis`、意匠・権利・新規性・進歩性・侵害の法的結論を自動生成/確定しない。
- 書込みは独立の`idea_write`権限かadmin+CSRFに限る。**ユーザーが入力フォームを確認してチェックした後に「保存」を押した場合だけ**書込。バックグラウンド/自動Job/自動保存/LLM呼出し・外部送信・クラウドfallbackはない。
- ControlDeck Host shell/nav/認証/theme/accent/level_0_manual_only/no executionとbackend authoritativeを維持。既定Web UI（RDHのindex.html）や既存ControlDeckのui.html/Vue read-only/nondefault/manifest/runtimeに変更なし。raw-source serving、redirect、fallback、server startup npm buildは禁止。

## 追加されたデータ構造とAPI

既存`store.py`のSCHEMA（同じSQLiteファイル）へ以下を追加する。

- `idea_drafts`：ID（`idea_<32hex>`）、作成request_id（一意）、content+source fingerprintのSHA256、creator、created。作成を同じrequest_id・同じ入力・同じactorで再送した場合には**追加書込0**、内容衝突は409。
- `idea_versions`：`idea_id, version, request_id, expected_version, content, actor,created`。初版はversion=1、以降は**append-only revision**。別編集と競合するexpected_versionは409。再送時は同一request_id+内容+actorなら書込0。前版と内容が変わらない場合も書込0。直近20バージョンの監査情報を返す。
- `idea_sources`：`idea_id, ordinal, proposal_id,item_index,doc_id,source_revision,source_epoch,review_seq,quote,quote_start,quote_end,statement`。source listは作成時に固定し、後のeditは本文だけを改訂する。故意に元文献を削除しても**Ideaの引用・出典IDの履歴を失わない**よう、sourceの外部キーはIdea本体以外に置かない。これは根拠が現在も有効だと主張するものではなく、むしろ`needs_revalidation`と表示するため。
- `qnaplibrary/idea_canvas.py`：`create/update/get/list_recent/get_version`。createはK4の`compare()`を**同一SQLite transaction**内で再実行し、source revision＋単調epoch＋latest review seq＋K1a Unicode quoteとHost local_only provenanceを再検証。K4比較画面に残った古い入力は409。editは新しいversionを追記する前に全出典の文献版・epoch・review seq・現在のapproved・quoteを再照合。変更/撤回→再承認/原文を変更後元に戻す場合も旧根拠は自動復活しない。
- GET時に各sourceの`status=current_approved_inference|needs_revalidation`とIdea全体の`state=manual_draft|needs_revalidation`を計算。read-only GETでDBへ書込みは行わない。古いIdeaは閲覧・引用履歴を保持するが編集保存は409。新しい出典で再比較して**別のIdea案を明示的に作る**まで自動転記/再承認しない。

### 正式API契約
| Method / Path | access | 操作 |
|---|---|---|
| GET `/api/v1/ideas` | read | 新しい20件まで、title/version/validity/status（書込0） |
| GET `/api/v1/ideas/{iid}` | read | 最新本文・source quote/epoch/review seq/validity・直近20版 |
| GET `/api/v1/ideas/{iid}/versions/{ver}` | read | 過去版の本文をread_onlyで表示（復元・上書きは不可） |
| POST `/api/v1/ideas` | idea_write | `{request_id,sources,content,confirm_manual:true}` を厳密検証、初版保存 |
| PUT `/api/v1/ideas/{iid}` | idea_write | `{request_id,expected_version,content,confirm_manual:true}` による競合防止付き編集 |

`content`の**必須キーは6つ**：title(最大160),problem(1500),solution(2500),effect(1200),conditions(1200),limitations(1200)。title/problem/solutionは空不可。それ以外も空文字で必須キーとして渡す。入力の型、改行以外の制御文字、余分なキー、重複source、不正レビューID/epochは400。原文/レビューが更新されている場合は409。すべてのwriteはIDと操作名のみをauditに記録し、未公開発明の本文をログに出さない。

- `auth.py`：`idea_write`専用device scope（`qlt_`）と同UID一時トークン`qlj_`。専用tokenは**IdeaのPOST/PUTのみ**可能で、GET文献・検索・他のwriteへのアクセスは403。既存`ro/rw/analysis/knowledge_propose/review/link/published`へIdea書込権限を追加しない。
- `local_auth.py`：同UIDのprivate Unix socket`idea_write`のみでローカルトークンを取得。遠隔環境は専用の`idea_write_token`を明示設定する。AddonClientはread認証をwriteに流用せず、Web/iframeにはavailabilityの**booleanだけ**を渡す。認証の既存Origin/CSRF検証をそのまま適用。
- `server.py`：Host Bridge認証済み`/addon/v1/ideas`,`/addon/v1/ideas/{id}`,`/versions/{ver}`とPOST/PUTを限定proxy。request body最大16KiB(create)/12KiB(update)。未公開本文を外部へ送る新経路なし。

## ControlDeckの具体的操作
1. K4「技術知識を横断検索・比較」で異なる文献から2〜3件を明示選択し、原文・成立条件・限界を確認する。
2. 比較結果から「この比較を材料にIdea Canvasへ」を押す（この時点は**メモリ上のフォームを開くだけ**。自動作成・自動保存なし）。
3. 参照元カードのstatement/quote/原文ジャンプを確認し、title/problem/solutionをユーザーが入力、effect/conditions/limitationsを任意に記述。
4. 明示確認checkboxをONにし「この案を保存」を押した場合だけIdea write scopeでPOST。サーバーが新たにK4の出典現在版を照合し、要件成立時のみ同一SQLiteへ保存。接続失敗・再送は同じrequest_idで冪等。
5. 保存済みの案一覧で選択→最新本文・出典・状態・版履歴を表示。人の編集はversionを増やすPUT、同じ入力の再試行は重複書込なし。履歴は版ごとにread-only表示し、古い内容の自動復元はしない。
6. 旧原文/旧レビュー/リンク元削除のいずれかで`needs_revalidation`。履歴は残すが保存は拒否し、新しい比較から別案を明示作成する。iOS 320pxは1列・16px入力・44px touch・Host theme/reduced motionを維持。原文/仮説テキストは`textContent`を使用する。

## 検証状況
- **実施済み**：GitHubでK4/mainの実Store/API/auth/local UDS/AddonClient/Host proxy/JS/docファイルを直接確認。K5 JavaScriptのV8構文検査**PASS**、JS参照DOM IDs欠落0・重複0、Host theme、mobile一列、textContent、専用scope/no execution/no new DB fileを静的確認。
- **実施済み**：独立Python SQLite smokeでK5と同形のDDLを作成し、FK/二段階version、emoji quoteのSQLite`substr`、source hashの変更→復元epoch、source documentの削除後もIdea引用が保持されること、GETの`total_changes`0を確認**PASS**。
- **追加したテストコード・まだ実行していない**：`tests/test_idea_canvas.py`は実Store/LiveServer/HTTPで、manual create、2文献出典、update append-only、同一request retry write0、違うpayload同ID409、内容同一edit write0、source revert、review revoke→reapprove、document delete→history保持、read0-write、invalid fields400、scope matrix/admin CSRF、Local same-UID token、AddonClientのread/write資格分離を検証する。`tests/test_idea_workspace.py`は比較→Canvas手動開始/保存、出典表示、スマホ入力、版履歴、No autosave・セーフティ契約の静的テスト。
- **未実施**：K5実Python/LiveServerテスト、K1a〜K4の全回帰、`bash scripts/verify.sh`、Linux/QPKG build、ControlDeck HostとRDH実HTTP E2E、iPhone Safari/実QNAP・性能/低I/O。作業コンテナはgithub.com DNS解決不可で完全cloneできず、PRに自動CI runがなければ実際のテスト合格とは呼ばない。**Draft/未マージ/未リリース**。

## 次のK6/リリース統合に向けた詳細Codex指示
1. **K5テスト最優先**：正規checkout上で`python3 -m unittest -v tests.test_idea_canvas tests.test_idea_workspace tests.test_knowledge_cross_search tests.test_knowledge_cross_workspace tests.test_knowledge_links tests.test_knowledge_map tests.test_knowledge_reviews`＋全K1a〜K4回帰、`node --check qnaplibrary/web/addon-workspace.js`、`bash scripts/verify.sh`、`bash scripts/build-linux.sh dist`。テスト失敗は本PRへ修正、軽微な変更を別PRにしない。
2. **型/トランザクション/競合**：idea createの`compare`検証→DB INSERTが同じ`store.tx()`か、書込専用tokenでGET不可、review/source撤回後に409、同じ本文への復元でもstale、K2却下→再承認後に新seqとなって旧Ideaはstale、原文削除後もhistorical quoteが残る、casefold/emoji quoteの位置と正確さ、expected_versionで競合、request_id二重送信write0、invalid fields400、read-only historyが無断書込をしないことを確認。
3. **安全性監査**：main実ファイル・PR diffでscope/Allowed/Do NOT/expected final stateを突合。ui.html/defaultとVue nondefault、RDH既定index.html、Host level_0_manual_only/no execution、backend authoritative、raw-source/redirect/fallback、server startup npm build、クラウド送信/automated mutation無し。保存されたIdeaのログ/Crash dump/APIにシークレットや未公開本文が混入しないか確認。
4. **UX実機**：ControlDeck内でK4検索→引用比較→K5手動作成→保存→再編集→過去版閲覧→原文変更でstaleまで操作。PC 1280/768px、iPhone 390/320px、キーボード/VoiceOver/接続断、デバイストークン設定、ログイン維持。ページ再読み込みとHost nonce更新で重複保存されないかテスト。
5. **低I/O・大量データ**：QNAP TS-253be相当でSQLite total_changes、WALサイズ増分、20件listのSELECT回数、同時ユーザーのversion lock、非常に大きな文献/異常なquote/履歴過多の上限、保存時のみ適切なfsyncを検証。原文を何度も読み戻すことを避ける。
6. **K6の範囲**：K5の安定化・Cursor付きIdea一覧、履歴・根拠差分表示、再比較を人が選択するUI、NAS低書込/大規模検索性能に絞る。別GraphRAG/Host実行系と重複させない。未公開発明のLLM再提案を導入する場合は後続でlocal-only/provenance/ユーザーの明示操作が必須。
7. **マージと正式配布**：Draft PR #29→#30→#31→#32→#33→#34→#35→#36→#37をmain/docs/manifest/tests/runtime実照合で全検証合格後に依存順merge。PR #23の旧GraphRAGとの差分・二重schema/Host provenanceを整理。リリース時だけVERSION/QPKG/addon manifestを一致更新し正式Releaseを作成。QNAP/Linuxの更新/healthとiPhone操作まで確認し、推測で「本番動作済み」としない。

**Expected final state K5**：人の判断で複数文献の承認済み知識から発明仮説を作り、完全な根拠と編集履歴を追跡できる。原文変更・知識レビュー変更・元文献削除により古い仮説は`needs_revalidation`へ移行し、自動復活しない。GraphRAGの承認や自律実行・出願は一切伴わない。
