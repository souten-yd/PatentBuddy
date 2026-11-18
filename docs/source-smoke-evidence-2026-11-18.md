# K7a 実取得・CIテスト記録 — 2026-11-18

対象: Draft PR #40, branch `feat/scoped-sources-storage-figures-k7a`。ベースPR #39もDraftであり、mainへ未マージ。キーはCIに登録していない。どの接続テストも実ユーザー文献DBには書き込まない。

## 実データ取得結果

- **WIPO 2026.01 H（電気） 英語IPC見出し:** 公式配布TXTを実HTTP取得（841,166 bytes）。`parse_titles` は大分類・クラス・サブクラスの **66** 見出しを解析してPASS。
- **WIPO 2026.01 H 有効記号:** 公式配布XMLを実HTTP取得（1,227,656 bytes）。当初はXMLの `{http://www.wipo.int/classifications/ipc/masterfiles}IPCSymbol` 名前空間・数字ゼロ埋め形式を認識できず失敗。実XML構造に合わせパーサー修正後、**10,607** 記号を解析してPASS。
- **WIPO SQLite実投入:** 認証不要の公式TXT/XMLを取得し、CIの一時SQLiteへ `import_titles` と `install` を実行。H02Mを公式分類名付きでブラウズでき、`verified_subclass('H02M')` PASS。文献テーブルのデータは0件のまま（資料DB非汚染）。
- **OpenAlex 検索:** キーなしで `openalex_works('inverter', limit=1)` が1レコードの実取得に成功した回がある。一方、別の実行ではHTTP **429** / anonymous search temporarily rate-limited / retryAfter 30s を確認。したがってキーなし運用を常時利用可能とは扱わず、ユーザー導入後の**無料APIキー登録を推奨**する。OpenAlex公式情報では無料キーなしの少量デモと無料キーによる使用枠拡大を区別している。
- **EPO OPS / JPO / USPTO:** 利用者の認証情報未設定のため実API取得は**未実施**。接続コードと模擬HTTP応答・認証境界のPythonテストのみ。サンプル成功・本番利用可能と称さない。

実行ログ: https://github.com/souten-yd/PatentBuddy/actions/runs/44233327596 （WIPO解析・OpenAlex実取得）、https://github.com/souten-yd/PatentBuddy/actions/runs/44234005222 （WIPO正式SQLite保存・分類検索、OpenAlex匿名429検出）。

## テスト結果

- targeted source/Host/auth/IPC/AI tests: `python -m unittest tests.test_source_connectivity tests.test_ipc_ai_selection tests.test_source_scope tests.test_source_planner_storage_figures tests.test_source_management_workspace -v` — **29 tests, 2 skips, failures 0**（最新CI）。
- `bash scripts/verify.sh`: Python・JavaScript・shell構文、標準ライブラリ制約、安全grepを通過。全unittestは **325 tests / 1 failure / 3 skips**。唯一の失敗は `tests.test_updater_docs.DocsRulesTest.test_only_release_workflow` で、一次的な `.github/workflows/k7a-source-smoke.yml` が `release.yml` 以外のworkflowを禁止する規約に抵触。**検証後に一時workflowを削除済み**（commit 5f9a66897f450507dc2273b53f4fa8328fd929c4）。全体テストの最終PASSは削除後に再実行していないので、全件合格と表記しない。
- 個別の失敗原因と修正: WIPO XMLタグ/コード形式、optional PyMuPDF importの標準ライブラリスキャン、異常な空比較リクエストのテスト期待値、ControlDeck AI非因果注記、活動履歴表示文言、WIPO TXT長文折り返し。後者はすべて現在のPRに修正済み。
- PDF内のベクター図形処理はPyMuPDFなしのCIではスキップ。実ユーザーPDF・iOS/ControlDeck/QNAP・高負荷I/Oは**未実施**。

## 導入時のキー入力と接続テスト

ResearchDataHubの「設定 → 外部キー」から、必要なソースだけ登録する。CIやGitHub上には登録しない。

| Source | 後で入力するもの | 導入直後の手動チェック |
|---|---|---|
| EPO OPS | consumer key + secret | 固定公開IPC `H02M` の欧州書誌を1件 |
| JPO | 正式な申込によるID + password | ユーザーが指定する**公開済み**出願番号を1件 |
| USPTO ODP | USPTO.govから発行されるAPI key | 固定の公開技術キーワードで1件 |
| OpenAlex | 無料API key（匿名デモも可能） | 固定の公開語 `inverter` で1件。429なら無料キー登録 |
| WIPO IPC 2026.01 | 不要 | Hセクション英語名／有効記号を公式配布元から取得・解析 |

「収集 → データソースの接続・取得テスト」から、管理者が**明示した1ソースだけ**少量取得。サンプルはDB保存しない。設定状態表示は実接続成功と混同しない。失敗は固定コードで表示し、キー・生エラー・未公開技術を含むログは出さない。テスト後に実運用を始めるには、各APIの規約・適法な保存範囲・レート制限を確認する。

## 次Codex/レビューの受入ゲート

1. 正規checkoutで `bash scripts/verify-k6.sh`、PDF任意ライブラリあり/なし、QPKG任意ビルド、ControlDeck/iPhone/QNAP実機試験。全件PASSと本番キーでのサンプル接続前にmerge/releaseしない。
2. `main` 実ファイル、manifest、docs、tests、runtimeをPR #29〜#40と照合。ui.html default, Vue read-only/not default, backend authoritative, runtime level_0_manual_only, no execution, no raw source serving/fallback/redirect, no startup npm build。今回のテスト目的の一時workflowは削除済み、`release.yml` だけ維持。
3. WIPO公式分類データの著作権表示・帰属: 公開製品での使用時は WIPO 著作権表示・出典を表示。ローカル保存するedition/hashを再確認。
4. OpenAlex新APIの匿名使用上限や429時の再試行待機を遵守し、無料キーを導入時入力する。未公開発明や機密検索語は外部へ送信しない。全入口hard quotaは別途設計・実装が必要。
