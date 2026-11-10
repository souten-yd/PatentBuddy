# HANDOFF — ResearchDataHub / PatentBuddy

**更新日**: 2026-11-10。中断後はまず `AGENTS.md` → `DEVELOPMENT_WORKFLOW.md` → 本ファイル → `docs/researchdatahub-plan.md` → `docs/CODEX_NEXT.md` を読む。

## 現在地（確認済み事実）

- GitHub: `souten-yd/PatentBuddy`、default branch `main`。
- **公開済みの最新バージョンはv0.5.1**: https://github.com/souten-yd/QnapPatentBuddy/releases/tag/v0.5.1（2026-11-10）。バイナリは旧互換名 `QnapLibrary_0.5.1_x86_64.qpkg`, `qnaplibrary-0.5.1-linux.tar.gz`。QNAP実機での更新・パスキー・保存先継続の動作は未確認。
- PR #12（未公開発明をクラウドへ送らないガード）は**mainにマージ済み**。出入口のネットワーク境界は `docs/privacy-boundary.md` を参照。
- **PR #16はdocs-onlyとしてマージ済み**。PR-AのLinux入口はPR #17で実装・検証済み、リリース待ち。Host結合/NAS移行は未実装。
- 既存v0.5.0 release workflowはPython 52件テスト成功＋Linux/QPKGビルド成功（当時）。今回のPR #16に関してローカル完全 `scripts/verify.sh`、Linux/QPKGビルド、ControlDeck実機、PC→QNAP移行テストを実施したとは主張しない。

## 2026-11-10に決定したアーキテクチャ（最優先）

| 区分 | 名称と役割 | 実行場所 |
|---|---|---|
| 汎用データ基盤 | **ResearchDataHub**: 特許・規格・学術/技術文献などを収集・保存・検索・版管理し、認証付きAPIを提供 | 今はControlDeck Linux PCのSSD、完成後はQNAPのローカルデータ領域 |
| 高度な特許利用 | **PatentBuddy**: ControlDeck Add-on v2、ローカルLLM、GraphRAG、請求項、調査・AI Jobs、特許向けUI | 今後もControlDeckのPC |
| 権限付き外部API | ResearchDataHubの**公開承認済みデータ専用API**。外部LLM本体へはユーザーの秘密プロンプトを送らない | ResearchDataHub側 |
| データの正本 | 唯一のSQLite/原本/案件/承認情報。検索キャッシュは正本でない | 開発中PC、完成後QNAP |

**既存実装の内部識別子を変更しない**: Python package `qnaplibrary`、QPKG `QnapLibrary`、旧データ/設定/パスキー、port 17871、Release資産名。ResearchDataHubはユーザー向け名称+新Linux起動別名として実装する予定（未実装）。

**重要な機密境界**: 未公開の発明・請求項を**ローカルLLM以外のLLMへ渡さない**。認証/TLS保護されたResearchDataHub⇔PatentBuddy/ControlDeckのデータ通信は許可。OpenRouter等の外部LLMは公開・承認・送信プレビュー済みの資料だけ、既存`privacy`のfail-closed制限を弱めずに別実装する。QNAP/PCを同時正本化しない。SMB/NFSで稼働中SQLite/WALを直接開かない。

## 最優先の性能受入契約（ResearchDataHub）

[ストレージ効率・低ディスクI/O・大量データ性能仕様](researchdatahub-performance.md) をCodexの強制的な受入基準とする。単なる速度向上ではなく、**保存容量、CPU/RSS、物理ディスクread/write bytes、WAL増分、検索/取り込み P50/P95/P99、バックアップ復元**を変更前後で計測する。

- 現在の`main`はWAL・FTS5・ハッシュ重複判定がある一方、文献ごとの重複SELECT、一覧の`SELECT *`、無変更バッチでもコレクションUPDATE、共有RLockなど改善余地あり。
- PR #13でこれらの一部をDraft実装済みだが**未マージ・全テスト/実機ベンチ未検証**。性能改善を実装済みや100万件対応済みと主張しない。
- **P0計測→P1 PR #13レビュー/冪等・軽量一覧/カーソル→P2索引/保存最適化→P3並行性・NAS移行時のHDD計測**の順とし、安易なDB分割・圧縮・無制限インデックス追加はしない。
- アイドル15分、無変更再投入、大量登録、検索、WALチェックポイントを別々に測り、NASでのガリガリ音につながるランダムI/Oも検証する。見かけの高速化目的で`journal_mode=OFF`、`synchronous=OFF`、監査の削除、起動時の毎回の全索引再構築を行わない。
- PC上Linux実機とQNAP TS-253Beの測定はまだない。計測コマンド/環境/結果/未実施をPR本文と本ファイルへ残す。

## 未マージの開発PR（mainには入っていない）

| PR | 内容 | 状態/注意 |
|---|---|---|
| #10 | LLMによる根拠付きクレームチャート | Draft。PR #12の新しい機密ポリシーへ整合させてから再検証 |
| #11 | セッション保持/Face IDパスキー更新後問題/一時501 | Draft。main v0.5.1とのバージョン競合・実機再現を確認 |
| #13 | 大量文献の一括冪等/低書込/カーソルAPI | Draft。実データ100万件の速度は未実測 |
| #14 | ControlDeck Add-on v2 A0/Feature bundle | Draft。**旧設計からの経緯あり**。新しいResearchDataHub API正本方針を優先し、PC上の別SQLite正本を作らない |
| #15 | 外部AI向け公開資料の承認・限定検索API | Draft。公開専用トークンの権限分離/出典・タイトル・抜粋の確認など要再テスト。外部LLMへ自動送信する機能ではない |
| #16 | ResearchDataHubとPatentBuddyの分離・PC→QNAP移行・Codex引継ぎ | 本docs-onlyチェックポイント。Linux CLI等は**次のPR** |

## Codexの次の作業（優先順）
1. **mainを取得、上記PRの実diffを読む**。`docs/CODEX_NEXT.md`記載のPR-Aから実装する。基本は1PR=1目的、早期Draft作成。
2. Linux PCで `python3 -m researchdatahub` と `./rdh.sh doctor|serve|test` を既存サーバーの**薄い別名入口**として実装する。ResearchDataHub表示/API health/管理Webのブランディング、Linux tar.gz同梱とテストを同じPRで扱う。旧package/DB/QPKG/port/cookie/パスキーRP IDの互換を守る。
3. PR #11を更新後認証/保持/501修正として検証し、PR #15の公開専用API、PR #13の高速化、PR #14のControlDeck接続を**新しい設計に合わせて**順次取り込む。PR #10のAIはローカルLLMだけで処理。
4. 特許/規格の文献実体とAPIの境界を整理し、GraphRAGは確定した引用/ファミリー等の関係から導入。出典/改版と推測関係の区別を必須にする。
5. **最後に**PC側のSQLite正本/原本/設定/秘密/パスキーをQNAPへdry-run→backup→hash/quick_check/件数照合→ロールバック可能な停止・切替を実施する。QNAP既存データを上書き・削除しない。

## マージ前に必ず確認する内容

- 前回指示のscope/Allowed/Do NOT/expected final stateと、**mainの実ファイル**、diff、docs、manifest、tests、runtimeの一致
- `bash scripts/verify.sh`、`bash scripts/build-linux.sh dist`、Linux非root実起動/API・セッション/パスキー回帰、必要なQPKGビルド/検査（実施できなければ未実施と記録）
- 機密用トークン/公開資料専用トークンのスコープ漏れ、外部AIへ流れるデータのリクエスト本文、プロキシ経路、秘密ログ、無断Web公開の有無
- 認証・Cookie・CSRF・RP ID・旧データの後方互換、不要な自動実行/npm build/外部依存/過剰機能追加の有無
- 低ディスクI/O・書込負荷、バックアップ復元、1000/10000/100000レコードのベンチ、iPhone UIと既存管理Webの動作
- docs-only PRなら **バージョンを上げずRelease不要**。コード変更をマージする場合はバージョン・CHANGELOG・QPKG設定整合とRelease、更新確認を行う。

## 既存の未解決事項
- iPhoneのパスキーが更新後に登録なし表示されること、ログイン保持、更新確認の一時501：PR #11の**未マージの修正候補**。解決したと主張しない。
- QNAP TS-253Beでの本番動作/自動更新/HTTPS・WebAuthn、各公的APIの実キー疎通、Host Feature署名・publisher登録は未検証。
- 古い自己更新クライアントはリポジトリ改名前のURLを使う場合がある。Release assetと手動導入手順を確認。
- 規格(JIS/ISO/IEC)の全文はライセンスに制約があり得る。APIから公開する前に権利確認が必要。

これまでの詳細な旧版の検証・変更履歴は各GitHub Release、PR #6/#8/#9/#12と`CHANGELOG.md`を参照。**今後のCodexの実装完了条件を満たしたものだけこのファイルの完了欄へ移す。**

## PR-A / PR #17 — v0.5.2 開発中（2026-11-10）
- PR #16 をレビュー・マージ。ベース `24cb084`。main v0.5.1 のローカル verify は58 testsと静的検査が合格。
- Linux別名入口/表示/配布互換を `feat/researchdatahub-linux-entry` / PR #17で実装。PR-B〜Gは未完了。
- ControlDeck管理のllama.cppプロセス（loopback 8097、ローカルGGUF Qwen3.8-27B）を確認。実LLM検証は下記。

- 新旧プロセスの共通DB・管理者ログイン・RP ID・保存先分離、doctor無書込みを検証。61 tests合格（版番号更新前）。v0.5.2版番号更新後にHANDOFFの版記載不足をテストが検出し、追記して再検証中。
- ControlDeck Qwen3.8-27Bへテスト観点を照会し、18.314秒/983 tokensで応答。合成案件の実API検証も追加。出力本文や秘密は記録せず件数・モデル名・所要時間だけを保存。

- **v0.5.2 候補の検証**: `bash scripts/verify.sh` 61 tests＋Python/JS/shell/依存検査合格。Linux/QPKGビルド成功、QPKG payload 43 entries検査成功。
- tar.gzを一時領域へ展開しdoctor/3 smoke tests成功、非root install.sh→旧binの0.5.2表示→インストール済み新入口の3 smoke tests成功。
- QPKGを一時展開してLinux上でstart/status/health/stop成功（app=ResearchDataHub/version=0.5.2）。**QTS実機試験ではない**。
- `PYTHONPATH=. python3 scripts/test-local-llm.py --verified-local`: ControlDeck管理のllama.cpp/Qwen3.8-27Bに合成案件のassistを実API送信、42.58秒、回答1137文字、案件の変更なし。初回はテスト側の応答キーをcontentと誤指定し失敗、実APIのanswerへ修正して再実行合格。法的品質/実案件品質は未評価。
- PR-Aは薄い入口/表示/配布のみで新規DBスキーマ・常駐I/Oなし。testは明示実行時だけ一時DBへ書込み、doctorはメモリのみ。
- Release公開・旧版からの自己更新は次の検証。iPhone実パスキー、QNAP本番、PR-B〜G、性能ベンチ、Host署名/結合、GraphRAG、NAS移行は**未完了**。


## PR-B / PR #11 — v0.5.3 開発中

- PR-A #17はmain `4170acd`へマージ、**v0.5.2公開済み**。release run `42809839947`成功、Linux/QPKG資産公開を確認。
- 公開済みv0.5.1を一時非rootインストールし、管理APIの更新確認が「想定外のダウンロードURL」で失敗することを再現。公開済みv0.5.2をSHA-256照合後に手動インストールすると、healthが0.5.2/ResearchDataHub、既存管理者ログイン/コレクション保持を確認。
- 公開配布のrdh.shを別チェックアウトから呼ぶとcwd内のPython packageを誤読する問題も検出。PR #11で明示した配布ルートをsys.path先頭にして修正、偽packageを置いたcwdからの回帰試験を追加。
- PR #11を現mainへマージして旧ブランド/機密保護の競合を解消。既存機密ガードとResearchDataHub表示を保持。セッションはSHA-256 IDのみSQLiteへ保存、RAM/DB最大128件。通常の認証/期限切れGETは書込みなし。ログイン時の清掃/追加のみトランザクション、ログアウトとパスワード変更は必要な失効書込み。
- **501再現と修正**: 本文を消費しない更新確認POSTの後に同じHTTP接続でGETすると501になる実テストを追加し、修正前FAILを確認。未読本文がある応答はConnection: closeとして修正後PASS。一般リトライは追加していない。QTS側の別要因は未確認。
- リポジトリ名を実際のsouten-yd/PatentBuddyへ合わせ、実GitHub metadataからv0.5.2の資産/digestを選べることを確認。配布済み旧クライアントには手動更新が必要。
- 再起動後のcookie/CSRF継続・パスキー登録レコード/ユーザーハンドル/RP ID・ログアウト後の再起動失効を実HTTPで検証。パスキーは合成登録レコードであり、iPhone実署名検証ではない。
- PR-Bの最終verify/配布ビルド/リリースは進行中。PR-C〜Gは未完了。次は公開資料API #15の実diffと権限分離検証。

- PR-B候補: `scripts/verify.sh` **67 tests＋全静的検査合格**。旧版v0.5.1→ローカル候補v0.5.3の手動更新で管理者/コレクション保持、新入口4 smoke tests合格。Linux/QPKG最終ビルドを実施中。全体目標は継続中で、PR-C以降を完了と扱わない。

- v0.5.3最終Linux/QPKGビルドとpayload検査成功。QPKGをLinux一時領域へ展開しstart/status/health(0.5.3)/stop合格。ローカル確認済み、QTS実機は未実施。
