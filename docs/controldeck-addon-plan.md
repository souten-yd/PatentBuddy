# PatentBuddy — ControlDeck Add-on 移行設計（規範）

状態: **ハイブリッド案を採用（2026-11-10）**。NASが唯一の永続データ正本。PC Add-onは高機能な計算・UI層。実機ホスト結合・NAS公開データAPIの本番受入は未実施。

## 決定
- PatentBuddy は ControlDeck Add-on Platform v2 の **独立プロセス**。ControlDeck本体へ特許専用コードを入れず、MediaForge/SonicForge と同じ外部サービス + manifest / sandbox embedded view を採用する。
- QNAP NASはSQLite/FTS5の**唯一の永続正本**として文献、公報、案件、請求項、監査ログ、引用・関係の確定データを所有する。QNAP自身が公式API/RSSの公開情報を取り込み、認証付きRESTで全文検索・登録・検索・データ出力を提供する。既存QPKGを維持して改善する。
- R9700X PC ControlDeck Add-onは暗号化されたNAS APIを通じてデータを参照し、ローカルLLM・埋め込み・RAG・クレーム/FTO等の計算と高度UIを担当。データの二重マスターは作らない。モデルやQdrant索引はPC SSDに**再構築可能なキャッシュ**として保持してよい。
- NASのSQLite/WALは**NASローカルのファイルシステムでNASプロセスのみが開く**。PCはネットワーク共有越しにSQLiteを直接開かない。定期バックアップはNAS内部のSQLite Online Backup APIを使用し、別世代に整合性チェック付きで保管する。PC側はHost Job再開用の状態以外を正本としない。NAS障害時にPCキャッシュを勝手に正本へ昇格させない。
- QPKG ID `QnapLibrary` と旧DBパス `QnapLibrary-data/library.sqlite3` を当面変更・削除しない。**NAS版を終了しない**。移行対象は高度UI/LLM処理であり、旧SQLiteデータをPCへ移行しない。設定・パスキー・既存NAS APIは保持する。
- `souten-yd/QnapPatentBuddy` を既存コードの継続元とし、別の新規リポジトリへ複製しない。改名はブランド/配布の層から段階的に変更する。
- 未公開発明/クレーム・個人メモを外部APIへ自動送信しない。ローカル専用AIをデフォルトとする。mainにマージ済みのPR #12の`privacy.fixed_public_request`の防壁を維持。一般的なOpenRouterへの自由入力・公報本文送信を勝手に解禁しない。外部AI用の限定データ経路は管理者が明示公開した文献のみに制約し、送信先・項目・目的・確認操作のポリシーを別途実装する。

## データ公開・外部AI・APIの強制境界

- すべての文献・案件は初期値**private**。公報の`kind=patent`、収集先、タイトルから公開可否を推定しない。
- 管理者が元URLと文献ハッシュを確認して明示承認した文献だけ、`published_documents` registryで文書単位公開。更新/削除で公開承認を無効化。検索のSQL段階で公開登録と現行ハッシュ一致をJOINし、private行をレスポンスに出さない。
- 専用`published`スコープの機械トークンは`/api/v1/published/*`のみ使用可能。元の`ro`トークンは**private文献も読めるため外部AIに渡さない**。既存ペアリングでpublished権限を発行できないようにし、管理者の明示発行だけを許可。
- 公開APIのデータ最小化: 機密の`meta`、案件情報、チャット、パスキー、秘密設定、運用ログを返さず、本文・タイトル・公開番号・日付・公開URL等の承認済みフィールドのみ。検索はキーワード限定で外部LLMへの送信を一切行わない。
- OpenRouterはあくまで**第三者へのデータ送信を伴うLLMサービス**。NAS公開検索API自体と同一視しない。第一段階ではPublic APIのレスポンスをローカルLLM/外部アプリが取得できるのみで、NASによるOpenRouterへの公報送信はしない。外部送信の第2段階はプレビュー・項目単位の承認、保存/再送/費用/ログを含め別PRで審査。
- LANからNAS APIはTLS検証必須。プライベートなNAS URLやbearer tokenをOpenRouterへ中継しない。レート制限・監査・ページング・失効とバックアップを追加する。
- リンクを開いただけで公開や外部送信が発生しない。管理UIでは`非公開`をデフォルト、明示確認後にのみ公開操作、公開中は復帰（非公開化）可能。

## 配布・ライフサイクル（MediaForge / SonicForge方式を踏襲）

- Add-onの宣言は `addon.json`、ControlDeck汎用 Feature の配布契約は `control-deck-feature.json`。後者は `feature_id`、`version`、`entrypoint`、`service_args`、`smoke_args`、`health_url` を固定する。
- Host-managed配布の場合、`CONTROL_DECK_FEATURE_DATA_DIR` に専用の持続領域を置く。パッケージ更新でその領域を消さない。コアは別環境・外部サービスであり、ControlDeckのPythonモジュールやvenvを共有しない。
- `./pb.sh doctor` は読み取り専用、`./pb.sh serve` は非rootのloopback専用、`./pb.sh test` は既存検証。A0ではAI・収集・更新の自動タスクを起動しない。
- `python3 scripts/build_cd_feature.py --out dist` は固定allowlistによる **未署名の再現可能なtar.gz** を作るだけ。未署名の成果物を信頼済みリリースと呼ばず、公開・自動導入もしない。
- 本番ではControlDeckの汎用Release Bundleが検証する形式に合わせ、配布manifest `schema_version=1, feature_id, version, platform, architecture, artifact_name, sha256, size_bytes` を規範JSONで生成し、発行者Ed25519秘密鍵で署名する。署名鍵はリポジトリ/一般CI/バンドルへ入れない。Hostのtrusted publisher公開鍵・能力allowlistに基づく検証を通って初めてインストールする。
- Hostは署名/一致確認 → 制限付き展開 → smoke/health → systemd user service登録 → atomically active version切替 → 前版ロールバックを担当。Add-onは自前のrootインストーラを作らない。
- 現在Hostの `backend/app/features/release_bundle.py` に署名検証と汎用systemd lifecycleがある。ただしPatentBuddyのpublisher鍵登録、リリース公開、Host実機受入は未実施。
- リリースとAddon/Feature/Pythonのversionを常に一致させる。既存QPKG版のリリース処理は安全な移行完了まで別扱いとする。

## Add-on Contract v2 と所有権
| 主体 | 責務 |
| --- | --- |
| ControlDeck Host | アドオンregistry/enable/disable、親ユーザー認証・権限・UIルート、限定Bearer認証、Jobs/AI/GPU Broker、ファイルgrant |
| PatentBuddy Add-on | 高度な調査/分析UI、ローカルLLM、GraphRAGの探索/再ランキング、Host Jobs・GPU制御、ローカル索引キャッシュ |
| QNAP NAS | 唯一の文献・案件・請求項・公開承認・関係グラフの正本、全文検索/公式データ収集API、認証、差分取得、世代バックアップ |

- Host内部Python moduleはimportしない。通信は scoped REST/Bridge のみ。NAS APIは**TLS検証済みのHTTPS/Tailscale経由**、短期・用途別に限定したトークン、read-only service principal、失効・ローテーションを採用。NASへのHTTP平文・Host Cookieの転送は禁止。
- 専用loopback: `http://127.0.0.1:9150` （自動起動・systemd設定は後続スライスで作成）。既存QNAPの 17871 は維持する。
- フロントは Host のopaque iframe (no same-origin)。Cookie・localStorage・sessionStorageに依存せず、Hostから来る限定service tokenのintrospectionでリクエストごとに認証する。Host Cookieを転送せず、未検証Bearerを管理者に昇格させない。
- A0は宣言的manifest・health・読み取り専用導線のみ。**PC上に2つ目のNAS文献DBを作らない**。現行`--addon`がローカルSQLiteを作る暫定構造は後続A1で取り除く必要があり、移行完成とは見なさない。Hostの認証済みprincipalがNASへの許可済みAPIだけを操作するまで旧管理APIを公開しない。
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
- **A2**: NAS主データAPIを読み取り主体でHostへ接続する。差分同期(cursor/change feed)、検索結果の根拠ID、PR #13 のスケール改善を組み込み、ControlDeck側のローカルSSDを再構築可能な索引キャッシュに限定する。
- **A3**: ローカルAI Gateway経由の特許作業とHost Jobs、明示実行・進捗・cancel。GPUを使用する場合Brokerリースを守る。
- **A4**: QNAP上のSQLite一貫バックアップ・世代保持・復元テストとNAS障害時のread-only表示。旧QPKGの廃止/データ移動は行わず、必要ならNAS側に安全なAPI新機能を追加する。
- **A5**: 正確な特許グラフ + 根拠付き意味拡張 + bounded GraphRAG。ベンチマークで効果が確認された関係のみ既定ON。

PR #10（クレーム）、#11（認証）、#13（大量投入）は別PR。PR #12（未公開発明保護）はmainへマージ済みであり制約として維持する。NAS限定公開データの独立した受入ゲートをA1より前に追加し、PR #15から実装する。**今回のPRはメインへの変更・自動リリースを伴わない**。実機検証はControlDeckを導入したUbuntu PCで行う。

## 操作可能なプレビューの導入（2026-11-10）

ユーザーの実導入要求に合わせ、PR-Eの初回配布はHost認証付き文献検索・取得と接続状態表示を先に提供する。AI/Host Jobs/GraphRAGの完了とは扱わない。ControlDeckのオプション機能から、既存release-bundleの導入/更新/有効化/無効化を使う。ResearchDataHubサーバーは独立したLinuxサービスであり、アドオン側の解除/更新では正本DBを変更しない。

接続設定はFeature data内の `connection.json`（0600）に `server_url` と `server_token`。同一PCのHTTP loopbackまたは別端末のHTTPSだけを受理し、環境proxyとredirectを無効化する。接続tokenはResearchDataHubから発行された読み取り専用を推奨し、GET/API/logへ返さない。

配布は `python3 scripts/build_cd_feature.py --out dist` と、既存publisher鍵を指定した `scripts/sign_cd_feature.py` を使う。新しい鍵は生成しない。`.tar.gz`、`.tar.gz.manifest.json`、`.tar.gz.manifest.json.sig`を同じversionのReleaseへ添付する。Host trusted catalogの公開鍵・feature_id・asset名・versionの一致と署名を検証してから導入する。Linux/QPKGの既存資産名・内部IDは維持する。

## A3実装候補とPDF/OCR追加要求（2026-11-10）

PR #19 / v0.5.8候補でHost local-only AI、Jobs、キャンセル/再実行、原文版付きの結果保存を追加。Host PR #349で推論先を検証し、機密入力の前に契約対応を確認する。別正本文献DBは作らない。実Host Jobs/LLMの合成請求項テストが成功し、ブラウザ幅1280/390/320pxは合成Host+実Addon/ResearchDataHubで成功。配布後の実Host画面受入はこれから。

ユーザーがPDF/OCR対応を追加要求。後続のPDF取り込み単位で、Host Filesの限定grant→PC上のpdftotext→必要ページのみpdftoppm/Tesseract jpn+eng→ページ/抽出法/原本hash/根拠位置付きでResearchDataHubへ保存する。OCRは精度保証せず原本との照合を可能にする。Poppler/Tesseractは現在のPCに既存、日本語/英語データ利用可。QNAPへOCR負荷を移さず、任意ファイルパス/コマンドAPIを追加しない。CPU/RAMのHost Broker制約・ページ数/画像サイズ/時間上限・キャンセルを適用する。文字入りPDFを無条件OCRせず、直接抽出を優先。現在のclient PDF抽出はOCRなしであるため既存機能と混同しない。
