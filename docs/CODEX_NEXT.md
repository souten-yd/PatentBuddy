# Codexへの引き継ぎ — ResearchDataHub / PatentBuddy

更新: 2026-11-10。**この文書は実装指示であり、既に完成した機能ではない。**

## 開始時に必ず読む
1. `AGENTS.md`、`DEVELOPMENT_WORKFLOW.md`、`docs/HANDOFF.md`
2. `docs/researchdatahub-plan.md`（**最新の役割・データの正本に関する決定**）
3. `docs/privacy-boundary.md`、`docs/patent-feature-plan.md`
4. ControlDeck本体 `souten-yd/ControlDeck` と `souten-yd/ControlDeckMediaForge`、`souten-yd/ControlDeckSonicForge` の**最新mainの実コード**。Addon v2 manifest, Host RBAC/introspection, Bridge, Feature bundleの仕様を必ず再読する。
5. 進行PR #10 / #11 / #13 / #14 / #15 のdiffと競合状態（PR本文だけでなく実ファイル）。PR #12はmainへマージ済みのセキュリティ基準。

## 名前の使い分け（混同しない）
- **ResearchDataHub**: 特許以外にも規格・論文・技術資料・研究データを保管/収集/検索/整理する**汎用サーバー**。Linux PC（現在の開発先）→ 完成後QNAP NAS（本番の主データ保存サーバー）。REST/MCPと出典・改版・権限管理の責任を持つ。
- **PatentBuddy**: ControlDeck PC上の**特許専用Add-on**。高度検索、ローカルLLM、クレームチャート、調査Jobs、GraphRAGはここで行う。将来、別の規格向けアドオンもResearchDataHub APIを使える。
- 既存リポジトリ名 `QnapPatentBuddy`、Pythonパッケージ `qnaplibrary`、QPKG ID `QnapLibrary`、旧データ領域、port 17871は**互換性維持**。Codexが一括rename/移管することを禁止。改名はユーザー向け表示と新Linux aliasから開始する。リポジトリ分割・改名は別途設計/許可。

## 配置とデータフロー
```text
開発/結合試験:
 Linux PC (Ryzen 9700X, ControlDeck, local LLM)
   ResearchDataHub 127.0.0.1:17871 -> PC SSDの唯一の正本
   PatentBuddy Add-on 127.0.0.1:9150 -> Host scoped API経由でResearchDataHubを利用
   LLM / OCR / embedding / bounded GraphRAG -> PCの計算資源
 本番移行後:
 NAS ResearchDataHub -> NASローカルファイルシステム上の唯一の正本
 PC PatentBuddy + ControlDeck -> 認証付きHTTPS/Tailscaleを経由してNAS APIを利用
 PCのQdrant/ベクトル索引 -> 再構築可能なキャッシュのみ
```
SMB/NFS経由で稼働中SQLite/WALを直接開かない。PCとNASで同じデータを**同時に正本として書き換えない**。切替はスナップショット、hash/quick_check/件数/スキーマ/秘密設定確認、停止、検証後の単一書込み開始、ロールバック計画を必須にする。

## 機密境界（誤解してはならない）
- 未公開発明、未公開請求項、アイデア、内部調査記録は**ローカルLLM以外のLLMに入力しない**。
- 認証済みのNAS⇔PCデータ転送やローカルLLMへの処理は許可する。これらを「外部への送信」と一括で禁止しない。
- ローカルLLMはクラウドへ中継しないことを検証する。localhostだから安全と断定しない。PR #12/mainのサーバ側exit gateを**維持**し緩めない。
- OpenRouter等の外部LLMは、公的資料等の許諾確認済み・管理者の明示承認済み部分だけを利用し、機密プロンプト・メタデータ・検索履歴の転送を禁止する。単に`kind=patent`等で「公開」と推定しない。外部AI連携でトークンやNASのURLをLLM本文へ渡さない。
- PR #15は **public-only専用APIのDraft**。正本のprivate資料、管理者のCSRF、device-tokenと独立して、検索/取得の前に承認済みの抜粋だけ返すことを証明する。**外部LLM送信機能は含まない**。承認済み文献でも改変後は停止。標準/規格の再配布権限にも配慮。

## Codexが次に進める順序

### PR-A: Linux PC用ResearchDataHubの起動入口と表示の互換移行（最優先）
**Scope**: ResearchDataHubという汎用名称へのUI/health表示変更、`python3 -m researchdatahub`の薄い入口、`rdh.sh doctor|serve|test`、Linux配布物への同梱、最低限の単体/プロセス起動テスト。すべて旧`qnaplibrary.server.main`を使い、二重コード・二重DBを作らない。QPKG表示名は段階移行として可能だが内部IDは固定。
**Allowed**: 新しい小規模CLI/branding/配布manifest/テストとdocsを変更。既存serverの動作ロジックを直接コピーしない。
**Do NOT**: `qnaplibrary`のimport path変更、QPKG ID変更、DB schema変更、初期管理アカウント再生成、UIをVue default化、認証/更新/検索runtime semantics変更、シークレットの表示、rootや起動時npm build、無条件データ移動、既存Release artifact名変更。
**Expected final state**: LinuxユーザーでResearchDataHubと旧`qnaplibrary`どちらの起動入口でも**同じデータディレクトリを明示したときだけ**同一DBを使用できる。PCの開発データはQNAPのQPKGデータと独立。旧ユーザーのパスキーとログイン方法を保持。
**Verification**: `bash scripts/verify.sh`, `bash scripts/build-linux.sh dist`、Linux実起動、`/api/health`、管理者ログイン、パスキーRP_ID/設定の回帰、旧ランチャーとの互換性、QPKG smoke。追加で安全grep/manifest検査。

### PR-B: 認証/セッション不具合（既存PR #11を最新mainへ整合）
- iPhone Face IDパスキーはSQLite上の登録レコードとHTTPS RP IDの一致を保持。アップグレードで消える不具合を実ファイル/データパス/マイグレーションで検証。
- セッションは設定された期間（既定約30日を検討）保持。**Bearer cookie平文は保存しない**、ハッシュだけ持続、期限切れ・ログアウト・管理者パスワード変更では失効。
- 更新確認501は単純な一般リトライで誤魔化さず、API/再起動・proxyとの関係、idempotency、UIに処理中を出す。既存の外部送信ガードを緩めない。

### PR-C: 公開資料API（既存PR #15を再検証し組込み）
- 管理者の文書単位/抜粋単位の承認、ソースハッシュ変更時の自動無効化、公開専用scoped token、TLS制約、限度付キーワード検索。
- public tokenが元文献・案件・秘密・未公開請求項・MCP・デバッグ/エクスポートを一切読めないことをテスト。
- 非公開資料のテキストはOpenRouterの要求本文にもログにも混入しない。タイトル/公開番号/抜粋を**送信プレビュー**で全部確認できるようにする。自動クラウド送信なし。

### PR-D: 大規模取り込み/検索（既存PR #13を再検証）
- 外部IDの一括照合、内容ハッシュの冪等再投入、無変更の書込0、本文を取得しない一覧、Keyset/カーソルページングを完成させる。
- 特許以外の規格識別子/改版/日付、出典とライセンスのメタデータも検索できる一般化を設計。新しいデータ収集元は公式API・RSS・許可済みサイトのみ。
- 1千/1万/10万文献でP50/P95/スループット、CPU/RAM、WAL/ディスクI/O、同時APIリクエストを実測。大量データを全件RAMに置くことはしない。

### PR-E: ControlDeck Add-onの安全なHost結合（既存PR #14を更新）
- `addon.json` v2、Feature bundle、署名/認証/health、Host introspectionの権限分離、Cookieに頼らないsandbox UI、iPhone幅での動作。
- **PR #14の古い設計を優先しない**。`docs/researchdatahub-plan.md`が正。PatentBuddy A0の起動では別の文献正本SQLiteを作らず、ResearchDataHubのscope付きAPI接続だけを許可する。
- MediaForge/SonicForge最新mainとControlDeck contract v2の差分を読み、本体のHost認証・Jobs・GPU Brokerを契約に沿って使う。現状#14 A0はUI/LLM未接続、完成と呼ばない。
- PatentBuddyが必要とするprivate文献を「外部AI公開済み」の権限に誤って変換しない。

### PR-F: 特許ドメイン/GraphRAG（既存PR #10など）
- 確定エッジ: 文献引用、特許ファミリー、優先権、出願人、IPC/CPC、クレーム要件。出典ID/テキスト範囲/取得日時/版/抽出法を保持。
- 推定エッジ: 課題・解決手段・効果・置換可能性。根拠/信頼度/モデル版/人間の確認状態を持ち、確定エッジへ自動昇格させない。
- キーワード→vector/ANN→1〜2hop bounded graph expansion→rerankの順。全件関連付け・無限探索・自動的な特許性/侵害の確定はしない。
- CPU/VRAM/GPUリース/ジョブ中断や再開をHostで管理し、外部LLMへ未公開情報が送られないことをテスト。

### PR-G: Linux PC → QNAP本番移行（**最後**）
- 開発用PC DBの一貫snapshotと原本ファイル、設定、秘密、認証・パスキー、監査ログを含め移行項目のチェックリストを確定。
- dry-run・ハッシュ・quick_check・データ件数/数件サンプル照合、バックアップ復元試験。QNAP上の旧QPKGデータは削除・上書きしない（衝突時は別領域/マージ設計を提示）。
- PC側の書込み停止、NASを唯一の正本に昇格、ControlDeckのNAS URLをHTTPSに切替、読み書き/索引再構築・性能を確認。戻し手順を明文化。

## 開発ルール・リリース
- 既存の`main`を読む → 既存PR diff・Do NOT・expected final stateを確認 → 作業ブランチ＋早期Draft PR → 最小スコープ実装 → 関連docs/manifest/testsを同時更新。
- 完全な`bash scripts/verify.sh`、Linux/QPKGビルドと単体/API/権限境界・実機テストを実施し、そのログと**未実施の工程**をPR本文・HANDOFFに書く。ユーザーから「確認して」と言われたらmergedだけでなく**main実ファイルと差分・安全な制約**を検査する。
- docs-only PRはRelease不要。アプリバージョンを変更するPRは既存の3箇所を一致させ、`release.yml`経由で公開。CIトリガー追加や勝手な署名鍵生成は禁止。
- 1PRの変更が膨大にならないよう、関連する少量修正は次の実装PRへ同梱。互換性/セキュリティ変更が広い場合だけ追加PRに分割。
- QNAP/ControlDeck実機の検証なしに、完成・高速・秘密漏洩なしと主張しない。

## 現在の実装状態（重要）
- `main` 最新公開済みは v0.5.1。PR #12のクラウドLLM機密防壁はmainに入っている。
- PR #10、#11、#13、#14、#15 はDraftで未マージ。これらのコードは**mainにない**。
- PR #16 は議論を確定した**文書だけのチェックポイント**。Linux用のResearchDataHub aliasなどは次の実装PRで作る。現時点で新ブランドのLinuxバイナリや稼働サービスを配布したと主張しない。
