# PatentBuddy — ControlDeck Add-on 移行設計（規範）

状態: 移行着手、NAS側既存データは変更しない。実機ホスト結合・データ移行は未実施。

## 決定
- PatentBuddy は ControlDeck Add-on Platform v2 の **独立プロセス**。ControlDeck本体へ特許専用コードを入れず、MediaForge/SonicForge と同じ外部サービス + manifest / sandbox embedded view を採用する。
- R9700X PC が全文検索・分析・GraphRAG・ローカルLLMへの依頼を担当する。別PC/サーバー側へ特許固有の依存を共有しない。
- NAS は公報の原本、検証済みデータベース・設定のスナップショット、世代管理、復元用メタデータの保管先。**稼働中のSQLite/WALをSMB/NFSで直接共有して配置しない**。ローカルSSDの稼働DB + SQLite Online Backup APIによる一貫したチェックポイントをNASへコピー（転送途中名 → ハッシュ検証 → 原子的な昇格）。失敗した時は旧世代を残す。SSDの完全故障時は最後の成功スナップショットまでがRPOとなる。
- QPKG ID `QnapLibrary` と旧DBパス `QnapLibrary-data/library.sqlite3` を当面変更・削除しない。旧データからPCへ移す場合は、QPKG停止または既存手動スナップショットからコピーし、検証・dry-run・ロールバックを先行する。上書きしない。
- `souten-yd/QnapPatentBuddy` を既存コードの継続元とし、別の新規リポジトリへ複製しない。改名はブランド/配布の層から段階的に変更する。
- 未公開発明/クレームを外部APIへ自動送信しない。ローカル専用AIをデフォルトとする。既存のPR #12の安全方針を優先。

## Add-on Contract v2 と所有権
| 主体 | 責務 |
| --- | --- |
| ControlDeck Host | アドオンregistry/enable/disable、親ユーザー認証・権限・UIルート、限定Bearer認証、Jobs/AI/GPU Broker、ファイルgrant |
| PatentBuddy Add-on | 文献・構成要件・出願/引用/特許ファミリーのストア、検索、可視化、特許ドメインAPI、生成物の根拠 |
| QNAP NAS | 原文・完全性を検証したスナップショット・バックアップの保管。実行主体ではない |

- Host内部Python moduleはimportしない。通信は scoped REST/Bridge のみ。
- 専用loopback: `http://127.0.0.1:9150` （自動起動・systemd設定は後続スライスで作成）。既存QNAPの 17871 は維持する。
- フロントは Host のopaque iframe (no same-origin)。Cookie・localStorage・sessionStorageに依存せず、Hostから来る限定service tokenのintrospectionでリクエストごとに認証する。Host Cookieを転送せず、未検証Bearerを管理者に昇格させない。
- 起動初期の今回のスライスは宣言的 manifest と Add-on health、および読み取り専用の初期導線。既存の管理画面全機能を未検証でHostへ公開しない。Hostに統合された文献検索・データ取り込み・AIは後続PRに分割。
- Hostへの `host_capabilities` は必要なものだけ要求。Jobs・AIなどは実装時に追加し、それ以前に権限があると主張しない。
- ブラウザの埋め込みrouteとワークスペース状態は Hostのroute/theme Bridgeに追従。認証とCSPを満たすまで機能の公開をしない。

## GraphRAG — 特許専用の根拠付き多層関係
1. **正確な確定関係（先行）**: 公開・出願・優先権番号、family ID、引用の方向、出願人、IPC/CPC/FI/F-term、請求項・要件・出典版。各edgeに `source_document_id`, `source_section`, `source_span`, `confidence`, `extraction_method`, `verified`, `revision` を持たせる。
2. **候補の意味関係（後続）**: 同義語・技術効果・課題/解決手段・材料/工程・置換可能性をローカルLLMで候補抽出。自動で確定関係に昇格させない。
3. **検索**: FTS5/BM25 → dense/ANN（規模拡大時はQdrant）→ 引用/特許ファミリー/共有IPCで1〜2hopのbounded expansion → rerank → 元文献とクレーム箇所を表示。hop数、関連文献数、コストに固定上限。
4. **保存/更新**: immutable元文献 ID を軸にし、抽出モデル/改版/ソースハッシュが変わった場合だけ関係を再評価。見出し文字列だけの同名entityマージはしない。
5. **評価**: 文献・根拠に対するprecision@k / recall@k、重複/誤結合、1万/10万/100万件時のP50/P95、SSD/NAS I/O、CPU/RAM、復元可能性を測定。実測がないうちは高速と断言しない。

ControlDeck本体の汎用 `workflows/rag_graph.py` にはLLM三つ組抽出の小型実装があるが、PatentBuddyの本格特許グラフの正規化/根拠追跡要件を満たさず、内部importも禁止なので、構造や限界の参考に留める。

## 実装順・受入ゲート
- **A0（本PR）**: manifest契約/health、loopback Add-on 起動入口、host integration policy、ドキュメント・契約テスト。フルUI・AI・NAS同期は未実装を明記。
- **A1**: Host token introspection・権限分離、Cookie不要なワークスペース、iPhone 320px〜、Host theme/route、安全なナビ。旧認証はstandalone用途のみ。
- **A2**: ドキュメント/特許案件APIをHost principalに限定公開。既存の特許コネクタと全文検索機構を再利用。PR #13 のスケール改善を取り込む。
- **A3**: ローカルAI Gateway経由の特許作業とHost Jobs、明示実行・進捗・cancel。GPUを使用する場合Brokerリースを守る。
- **A4**: NASバックアップ/移行ツール（dry-run/チェックサム/復元テスト）、旧QPKGからの移行受入後にQPKGリリースの凍結。
- **A5**: 正確な特許グラフ + 根拠付き意味拡張 + bounded GraphRAG。ベンチマークで効果が確認された関係のみ既定ON。

競合PR #10（クレーム）、#11（認証）、#12（未公開発明）、#13（大量投入）は別PRとして維持し、必要な実装がmainに入った後に取り込む。**今回のPRはメインへの変更・自動リリースを伴わない**。実機検証はControlDeckを導入したUbuntu PCで行う。
