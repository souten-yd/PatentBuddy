# ResearchDataHub / PatentBuddy — 名前・配置・責務の決定

状態: 2026-11-10 合意方針。Linux PCで開発・検証し、検証完了後にデータ正本をQNAPへ移す。現在のQPKG・データは変更・削除しない。

## 製品名

- **ResearchDataHub**: 特許公報・規格（JIS/ISO/IECなど、利用許諾を守る）・論文・技術資料・公的制度・構造化データなどを保管し、出典と改版・検索・収集・認証付きREST/MCP APIを提供する**汎用研究データサーバー**。
- **PatentBuddy**: ResearchDataHubを利用するControlDeck Add-on v2。発明・請求項・先行技術調査・GraphRAG・ローカルLLMなど、特許専門の高機能UI/分析を提供。
- 将来の規格調査などは独立アドオンでもResearchDataHubの同じ文献/権限/検索APIを再利用する。サーバーへ特許専用ロジックを無制限に追加しない。

## 開発/運用トポロジー

| フェーズ | ResearchDataHub 実行・正本DB | PatentBuddy 実行 | 補助索引 |
|---|---|---|---|
| 開発・負荷/回帰試験 | **ControlDeck PC上のLinux**、PCローカルSSD。テスト用/本番用のデータディレクトリを分離 | 同PCのControlDeck独立Add-on | SSD上で再生成可能 |
| 結合試験 | PC側の両サービスをTLSプロキシ経由の認証付きHTTPで接続。機密情報はローカルLLMのみ | 同PCのControlDeck | NAS直接のSQLiteアクセスは禁止 |
| 完成後の移行 | **QNAP NASのローカルストレージ**へスナップショットと設定を検証・移行。NAS上のResearchDataHubが唯一の正本 | 引き続きPC | PC索引はNAS正本から再生成 |

- 2台で同じSQLiteを同時に書き込まない。停止/SQLite Online Backup APIで一貫スナップショットを作り、SHA-256・quick_check・文献件数・データschema・設定/シークレットとパスキー・原本の移行チェックをしてからNASを有効化する。移行失敗時はPC側を維持。
- 規格原本は著作権・契約による再配布可否を確認。公開API用のデータと機密データはサービス側で別権限とし、未公開の発明/請求項は**ローカルLLMだけに入力可能**。PC⇔NAS間の認証済み転送は制限対象ではない。OpenRouter等の外部LLMは許可された公開資料だけを入力対象とする。
- 遅い処理（OCR/埋め込み/GraphRAG/大規模RAG）はControlDeck PCへ寄せ、サーバーはデータ保存/収集/検索APIを保持する。確定した引用・特許family・文献改版などの関係データはResearchDataHubが保存する。
- 既存 `qnaplibrary` Pythonパッケージ、`QPKG_NAME=QnapLibrary`、データディレクトリ `QnapLibrary-data`、port 17871 は互換性のため維持。表示ブランド・Linux入口だけを段階的に移す。名称の変更で既存データ・パスキーを初期化しない。

## 最優先の非機能要件：保存効率・低ディスクI/O・大量処理性能

[ResearchDataHubストレージ性能仕様](researchdatahub-performance.md) を**Codex向けの受入契約**とする。特許だけでなく、規格・論文・汎用コレクションすべてに適用する。

- **PC開発中もQNAP本番でも、正本DBは各時点で1台のローカルストレージ上のみ**に置く。SQLite/WALをNAS共有から複数PCが同時に開かない。
- 取り込みは冪等キー、バッチ、差分判定、無変更再送の書き込み削減を優先する。追加索引が検索を速くする一方で書込みを増やすトレードオフは実測して判断する。
- 検索APIは必要な列・スニペット・cursorだけ返す。大容量本文・ベクトル・GraphRAG全件を毎回読み出さない。
- アイドル/大量投入/検索/チェックポイントそれぞれで**物理read/write bytes・DB/WALサイズ・P50/P95/P99・RSS・CPU**を計測する。ベンチで改善が再現できない最適化は採用しない。
- 既存のWAL・同期・監査・認証を無効化して見かけの高速化をしない。圧縮・blob分離・並列読取・外部インデックスは実測後のオプションであり、最初から追加依存を増やさない。
- **PR #13はDraftで未マージ**。実装案のレビュー・回帰テストを行ってから現在のmain（機密保護PR #12を含む）へ取り込むこと。

## 本PRは設計・引き継ぎのみ（2026-11-10 checkpoint）

このPR #16 は **documentation-only**。ResearchDataHub のLinux実行入口、サービス起動、QPKG表示変更、データ移行、ControlDeck Host接続、公開データAPIは**実装しない**。以下の列挙は **Codex が次の実装PRで実行する仕様**であり、既に動く機能を示していない。READMEは現在の実装だけを示し、旧製品名の互換エイリアスは将来のLinux PRにて追加する。設計上の正本はこの文書、日々の進捗正本は `docs/HANDOFF.md`、Codex向け受入手順は `docs/CODEX_NEXT.md`。

## 次の実装PR（予定）の範囲

1. 次の実装PRで Linux PCから `python3 -m researchdatahub` と `./rdh.sh doctor|serve|test` で利用できる入口を追加。起動処理は既存 `qnaplibrary.server.main` を再利用し、二重DB/二重実装を作らない。
2. 次の実装PRで Server/UI/health/QPKG表示名を `ResearchDataHub` に変更。旧内部識別子・QNAP配布ファイル名・ポート・DB schema・データパス・既存REST意味論は変えない。
3. 次の実装PRで Linux tar.gz配布に新しい入口を同梱。既存 `qnaplibrary` ランチャーとsystemdサービスは互換維持。
4. 次の実装PRでは認証・機密防壁・収集・検索エンジン・スケジューラの機能挙動は変更しない。データ共有のためSMB/NFS上の稼働SQLiteを使わない。
5. 次の実装PRでテストにブランド/入口/データ独立性/配布同梱/実行権限を追加。フルverifyとLinux/QPKG build、ControlDeck PC実機受入が通るまでPRはDraftにする。

## 次の段階

- **S1**: まずPCにResearchDataHubとPatentBuddy A0を並列導入。A0はまだ準備画面だけで、認証・本格UIは未実装。
- **S2**: ControlDeck Host principal認証+ResearchDataHub scoped API（private業務APIとpublished-only外部AI API）を接続。公開資料の手動承認はPR #15のレビュー対象。
- **S3**: 大量検索・バッチ登録・文献出典/規格検索フィールドを追加。PR #13の拡張を検証・統合し、実測性能に基づき最適化。
- **S4**: ControlDeckのローカルLLMとJobsを使うGraphRAG/請求項/引用・規格リンク。外部LLMには未公開の発明・請求項を入力しない。
- **S5**: PC → QNAPのdry-run移行、整合性検証・切替・復元・トークン/パスキー再確認。その後にだけQNAPへ本番移設。

## 確定した安全境界（Codexの実装で強制する）

- QNAPとPC間のデータ送受信は認証付き・暗号化したHTTP(S)で許可する。ローカルLLMへの未公開データ入力は許可する。これは**外部LLMへの未公開情報送信禁止**とは別の境界である。
- OpenRouterなどのクラウドLLMへの送信は、公開済みであることを確認・承認した資料に限定する。公開公報本文でも検索履歴/社内コメント/未公開の請求項案との組み合わせから機密が推定されるため、自由入力・内部注釈の丸ごと転送は禁止。既存のmainの`privacy` fail-closed制約を弱めない。
- NASへ本番移行してもResearchDataHubの正本DBは**1つだけ**。開発PC側とQNAP側が同時に正本として動作する切り替えは不可。データ持ち出し・復旧検証・停止・切り替え・復元の全工程を明示。
- 「ローカルLLM」は単にローカルのURLを指すのではなく**クラウド中継しない推論器として検証した接続先**を指す。環境プロキシ/HTTPリダイレクト/外向き通信を検証する。
- 公開資料の利用許諾と著作権の確認は出典ごとに必要。特に規格の全文は公開されていても再配布可能とは限らない。
- 初期の管理Webやパスキーの既存動作を維持する。名前・アイコンの変更でWebAuthn RP ID、QPKGパッケージID、データフォルダ、cookie名を変更しない。
- CPU/NAS I/Oを減らすため、巨大な検索結果を丸ごとPCへ転送する代わりにクエリ・必要な証拠断片・ページング/差分同期を使う。GraphRAGは出典/方向/版/信頼度を持つ関係と候補的意味関係を区別する。

## GitHub PRの位置づけ（2026-11-10）
- PR #10: AIクレームチャートの仮判定（Draft、未マージ）
- PR #11: セッション保持・パスキー/更新確認501修正（Draft、未マージ）
- PR #12: 未公開発明の外部送信保護（**マージ済み、v0.5.1**）
- PR #13: 大量特許データの取り込み/ページング（Draft、未マージ）
- PR #14: ControlDeck Add-on v2 A0基盤（Draft、未マージ）。この文書のResearchDataHub構成を参照し、古いPC正本案を採用しない
- PR #15: 公開承認済み文献だけの検索APIと機械トークン（Draft、未マージ）。第三者LLMへの送信機能そのものは未実装
- PR #16: **本チェックポイント（docs-only）**。コード実装なし、マージ後にCodexが実装PRを作成する


### 2026-11-10 PR-A進捗
PR #16の設計はmainへ統合済み。PR #17でLinux別名入口・doctor/serve/test・health/Web表示・配布同梱を実装し、61 tests、Linux配布/非rootインストール、QPKGのLinux上smoke、ControlDeckローカルLLMの合成案件assistを検証。リリース/更新は検証待ち、PR-B〜GとQNAP実機は未完了。詳細はHANDOFF。上記の「未実装」は設計チェックポイント時点の記録。

## 2026-11-10 実装の更新

PR-A/B/CとPR-Eの検索閲覧・同一ユーザーローカル自動認証はv0.5.6で公開/実導入済み。PR-D #13はv0.5.7候補。P0/P1の1千/1万/10万件測定と15分idle、全6再起動/復元受入が完了し、結果・索引の費用・遅くなった観測を `benchmark-datahub.md` と `benchmarks/pr-d-linux.json` に記録した。P2の一般フィールド/改版/出典/ライセンスと段階的索引設計は `document-metadata-design.md`。P2の検索表実装とP3のNAS移設は未完で、P0/P1完了から推定しない。旧節のDraft/未実装表記は設計当時の履歴。
