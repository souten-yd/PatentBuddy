# ロードマップ

## v0.1（土台・特許支援優先） — 本PR
- API サーバー（REST + MCP）、LAN ペアリング、管理Web（パスワード＋パスキー）
- コレクション／文書／FTS5 日本語検索／RAM ベクトル／RRF ハイブリッド
- 特許案件ワークフロー（11段階、期限計算、請求項の版管理、構成要件分解、クレームチャート、AI 支援 12 タスク）
- AI チャット（QnapAssistant / OpenRouter 詳細設定 / OpenAI 互換、RAG、SSE）
- コネクタ: GDELT、RSS、EPO OPS、JPO API（実験的）、USPTO ODP（実験的）
- デバッグバンドル、GitHub Releases 自動更新、Linux tar.gz / QPKG

## v0.2（特許の網羅性） — 完了
- 特許ウォッチ（定期収集・差分・類似度で X/Y 候補提示）
- IPC/FI/Fターム辞書、審査基準コレクションの取り込み支援
- 期限通知（Webhook / メール）

## v0.3（スケールと品質） — 完了
- Qdrant アダプタ、外部リランカー、集計ダッシュボード
- PDF 取り込みクライアント（別PC）

## v0.4（市場・規格） — 完了
- 規格メタデータの整備支援（JIS/ISO/IEC 番号・ICS・対応関係）
- e-Stat / EDINET / SEC コネクタ、調査ジョブ

## v0.5（データ保全・iOSホーム画面）
- 管理者専用の SQLite 手動スナップショットと整合性確認（設定/秘密情報は既存の HBS3 と併用）
- iOS Safari「ホーム画面に追加」用の 180px アイコン・メタデータ
- ホーム KPI のコンパクト化と処理状態の読み取り表示

## 汎用ResearchDataHub + ControlDeck PatentBuddyへの移行（2026-11-10決定）

1. **設計チェックポイント（PR #16、docs-only）**: 名前/責務/データ正本/機密境界を `researchdatahub-plan.md` に確定。Codex向け詳細は `CODEX_NEXT.md`。**まだLinux aliasなどの新コードは未実装**。
2. **Linux PC用ResearchDataHub（次のPR）**: `python3 -m researchdatahub` と `rdh.sh`、同じbackendのままLinux配布へ。旧`qnaplibrary` / QPKG ID / 17871 / DBパスを壊さずブランドを分離。
3. **認証・公開資料API**: 既存Draft PR #11（パスキー/セッション/更新501）と #15（公開承認済み抜粋限定API）を再検証。未公開発明/請求項はクラウドLLMに出さない（PR #12はmain反映済み）。
4. **ResearchDataHub保存効率・低I/O・大量API**: [性能要件](researchdatahub-performance.md)に従って、同一再送/大量登録/索引検索/アイドル時の物理I/Oと時間を測定。Draft PR #13のバッチ冪等・必要列のみ一覧・IDカーソルをテストして汎用化。索引・圧縮・並列化は実測で利点が確認できた場合のみ採用。
5. **ControlDeck PatentBuddy**: Draft PR #14のAdd-on v2 A0を更新し、Host認証、ResearchDataHub API接続、ローカルLLM、Jobs、GraphRAG、iPhone対応へ進む。PCに別の正本DBを作らない。
6. **本番のQNAP移行（最後）**: PCの正本から検証済みスナップショット、設定・パスキー・秘密・文書をQNAPへ安全移動。PCとNASの同時書込は不可。ControlDeck側はそのまま利用。

[決定したアーキテクチャ](researchdatahub-plan.md) / [保存・I/O性能受入基準](researchdatahub-performance.md) / [Codex実装・受入指示](CODEX_NEXT.md)

## 特許専用ロードマップ（v0.6以降）

詳細は [patent-feature-plan.md](patent-feature-plan.md) を参照。機密保護をゲートに、発明創出・ブレスト・請求項→先行技術/新規性・進歩性→競合/回避設計・FTO→出願文書へ段階的に進める。AIの外部送信は公開一般論に限定し、未公開発明・案件資料はローカル専用。


### 2026-11-10 PR-A進捗
PR #16の設計はmainへ統合済み。PR #17でLinux別名入口・doctor/serve/test・health/Web表示・配布同梱を実装し、61 tests、Linux配布/非rootインストール、QPKGのLinux上smoke、ControlDeckローカルLLMの合成案件assistを検証。リリース/更新は検証待ち、PR-B〜GとQNAP実機は未完了。詳細はHANDOFF。上記の「未実装」は設計チェックポイント時点の記録。

## K0–K6: 知識エッセンスを蓄積・再利用する特許発明支援（2026-11-17計画追加）

- **計画の正本**: [知識グラフ・エッセンス再利用計画](knowledge-graph-plan.md) / [詳細設計](knowledge-graph-design.md)。
- 既存 [PR #23](https://github.com/souten-yd/PatentBuddy/pull/23) のDraft GraphRAG（文献/請求項の根拠・版・引用の追跡）が**先行依存**。PR #23の未配布機能をmainの実装済みと混同しない。
- **K0** 既存GraphRAGと正本所有権/認証を実コード・diffで確認 → **K1** 文献からProblem/Principle/Mechanism/Implementation/Effect/Constraintの根拠付き知識提案抽出 → **K2** 同義語・上位概念、重複候補/人手review、版失効 → **K3** Obsidian型部分グラフ・知識カード・原文への逆引き。
- **K4** 別案件・異分野の知識検索と応用条件の提示 → **K5** 選択知識の組合せからIdea案を作り、先行技術・請求項・FTOへ再照合 → **K6** 大量データ、NAS低I/O、実機と単一正本移行を受入。
- **文書だけの計画**: 知識化・地図UI・発明案生成はこのPRで実装しない。既存検索/論文/PDF/特許性評価を壊さない。軽微な共有型はPR #23に同梱し得るが、K1以降の主要機能は後続PRへ分割する。

## K1a着手 — ControlDeck準拠の知識エッセンス抽出契約（2026-11-17）

[ControlDeck UI/UX受入契約](controldeck-ux-contract.md)をK3のKnowledge Map/Knowledge Card/Idea Canvasに必須化。見た目と操作はControlDeckのHost shell、theme、共通PageHeader、Job状態/BottomSheet/モバイル規則を踏襲し、独自UI体系を新設しない。

K1a Draft PR #29に原文範囲・source revision・Host local_only証跡形式・未承認推論固定を検証する純粋モジュールと10件の単体テストを追加。**モデルによる生成/保存/API/画面は未接続**。K1bは先行Draft PR #23のHost generation provenanceとrelation_proposalsの差分を確認して共通化する。

## K1c — 根拠付き知識候補の保存API（2026-11-17 / Draft PR #31）

- K1a validator (PR #29)・K1b local-only generator (PR #30)に続き、K1cは既存 `document_analyses` へのimmutable知識候補保存・原文版/引用のtransaction内再検証・新 `knowledge_propose`専用権限を実装。[詳細と次のK1d指示](knowledge-k1c-storage.md)。
- K1cの新規テストを追加したが**LiveServer/実UDS/全体verifyは未実施**。隔離SQLite mock testの6件のみ成功。K1c APIはHost分析ジョブ・Knowledge Mapへは未接続。
- 次のK1d: PR #23のHost provenance/GraphRAGのmain統合をレビューし、Host Jobs→generator→scoped DB保存→ControlDeck準拠カードと状態表示を接続。UI/UXは [ControlDeck準拠](controldeck-ux-contract.md)。すべてのDraft PRを無検証でmerge/releaseしない。

## K1d Hostジョブ・ControlDeck知識カード（2026-11-17）

- [Draft PR #32](https://github.com/souten-yd/PatentBuddy/pull/32)でControlDeck現行local_only/require_provenance Hostと既存AnalysisJobsを接続、知識抽出→専用K1c保存→ControlDeckテーマ追従の知識カード・出典ジャンプを追加。詳細は [knowledge-k1d-implementation.md](knowledge-k1d-implementation.md)。
- K1c writer scopeは専用POST以外の一般private GETを禁止するよう強化。AI結果はunreviewed/model_inferenceのみ、stale/引用一致を表示。原文にないquote、モデル証跡未検証、権限不足はfail closed。
- **実装コードはDraftのみ**。JS構文・HTML ID・ControlDeck実コード契約は静的確認したが、Python/実API/実ControlDeck/iPhone/QNAP、全verify、build未実施。正式リリース不可。
- K2ではversioned human review、K3ではPR #23 GraphRAGを再利用したbounded Knowledge Map、K4では異分野再利用検索、K5ではIdea Canvasと出典付き先行技術再照合、K6ではQNAP移行と低I/O検証へ進める。

## K2人間レビューの実装（2026-11-17 / Draft PR #33）

- K1dの知識候補抽出の次段階として[Draft PR #33](https://github.com/souten-yd/PatentBuddy/pull/33)へ、版別・項目別のappend-only人間レビュー（承認・却下・差戻し）、専用トークン/同UIDソケット、旧原文への自動失効、最大30件の履歴、ControlDeck準拠のカード操作を実装。[K2詳細設計・残検証](knowledge-k2-human-review.md)。
- **未マージ/未リリース**。JS構文/HTML ID、SQL最終decisionの独立検証のみ合格。追加Python LiveServerテストと全verify、ControlDeck/RDH/iPhone実機は未実施。モデル出力が事実へ自動昇格する機能はない。
- 次工程K3: PR #23のGraphRAGを実ファイルで整合してbounded Knowledge Mapを作る。AI推論・旧版・未確認の誤表示を禁止し、Host nav/theme/モバイル/キーボードを継承。K4〜K6は既存ロードマップに準ずる。

## K3 Knowledge Mapの初期実装（2026-11-17 / Draft PR #34）

- K3 [PR #34](https://github.com/souten-yd/PatentBuddy/pull/34) はK2レビュー結果＋PR #23の既存GraphRAGを**同一SQLiteの読取専用Projection**として表示する初期マップを実装。範囲1〜2hop、36 nodes/52 edges、PR #23版トリガー、承認済み/根拠付き事実辺のみ既定、AI推論はhuman review後もmodel_inference表示。未確認/旧版は明示opt-in、原文quoteは再照合。ControlDeck PCはSVG＋Inspector、iPhoneは一覧＋根拠。
- K2にはhash/sourceの単調`review_epoch`と失効判定を追加し、旧文面への復帰でも過去の承認を自動復活させない。[K3設計と次のK3b/K4指示](knowledge-k3-map.md)。
- **Draft/未検証**: GraphRAG/LiveServer/Pythonの実行は未実施。V8 JS構文/HTML IDと独立SQLite Unicode/epoch smokeのみ合格。旧PR #23の全体GraphRAG導入・手動関連リンク登録・発明キャンバス・リリースはまだ。
- K3bで人間確認済みの根拠付き関係の明示登録、K4で蓄積知識の横断検索・異分野応用候補抽出、K5でIdea Canvas/新規性再調査、K6でNAS低I/O最適化/配布へ。
