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

## K3b 根拠付き技術仮説リンク登録（2026-11-17 / Draft PR #35）

- [Draft PR #35](https://github.com/souten-yd/PatentBuddy/pull/35)はK2人間レビュー済みの知識→別文献の引用根拠付き技術仮説リンクを、専用権限で未承認登録・別の明示レビューできるようにする。PR #23 GraphRAGのsave/reviewを同一SQLite transactionで再利用し、**inferredのままでfactualへ自動昇格しない**。[詳細設計とK4手順](knowledge-k3b-links.md)。
- K2 latest review seq / doc epoch / source/target revision / quoteを同時に照合。撤回・再承認を行っても旧リンク承認は失効し、新たな登録・レビューが必要。GraphRAGの既定検索はfactualのみ。仮説をK3 Mapに表示するには人が明示`include_links=true`にする。
- ControlDeck埋込UIに文献検索選択・根拠選択・仮説種別・2段階確認・失効通知/履歴への入口、iOS単列対応を追加。独立SQLite smokeとV8構文/DOMチェック済みだが、**Python実LiveServer/全repo verify/配布・実機未検証、Draft未マージ未リリース**。
- 次K4は承認済み技術エッセンスの複数文献横断検索と条件/手段/効果比較、K5はIdea Canvas/先行技術検証。PR #23の大型GraphRAGは重複を整理して必要部分だけ採用する。

## K4 解決エッセンスの横断検索・条件比較（2026-11-17 / Draft PR #36）

- [PR #36](https://github.com/souten-yd/PatentBuddy/pull/36)はK3b PR #35の上で、K2人間承認済み/現行版の解決原理・作用機構・効果・条件・限界を**複数文献から読み取り専用検索**し、2〜3件で並列比較する初期K4を実装。検索語は認証付きPOST本文で取得、SQLite追加IndexやAI推論ジョブなし。[K4設計とK5実装手順](knowledge-k4-cross-search.md)。
- 1回の検索は最大240 raw reviewイベント/20件結果、SQL内の先行LIMIT＋降順cursorで次ページを明示取得。画面60件上限、比較2〜3異文献、文言完全一致だけ共通点表示。文献revision+epoch/K1a Unicode quote+Host証跡を読取時再検証し、旧reviewは返さない。元の文献原文へジャンプ。
- **Draft/未検証**: K4 JavaScript構文・HTML参照ID・独立SQLiteキーセットSQLはPASS。新規Python LiveServer/全`verify.sh`/Linux/QNAP/iPhone実機とディスクI/Oは未実施。#29〜#36 stacked Draftのまま、正式マージ/Releaseなし。
- 次はK5: 2〜3件の比較から人が編集・保存するIdea Canvasと出典revision/epoch/seqの再検証。K6はNAS低書込・大量検索/配布品質。

## K5 人手Idea Canvas（2026-11-18 / Draft PR #37）

- [Draft PR #37](https://github.com/souten-yd/PatentBuddy/pull/37)でK4の2〜3文献比較から、人が課題・仕組み・効果・条件・限界を入力して明示保存するIdea Canvasを追加。K2承認/source revision/epoch/review seq/quoteを同じSQLite transactionで再検証。出典固定・版追記・再送write0・旧原文復元でも`needs_revalidation`、過去版read-only参照を提供。[K5/K6設計](knowledge-k5-idea-canvas.md)。
- 専用`idea_write`scopeと同UID token、ControlDeck Host認証代理。通常rw/ro/knowledge review・link・publishedには新権限なし。自律LLM/自動出願/Graph関係自動変更なし。PC/mobile画面/出典・履歴を追加。
- 独立SQLite smokeとJS V8構文/DOM IDsの静的検証はPASS。**実Python/LiveServer/全verify/Ubuntu-QNAP build/iPhone実機は未実施、Draft・未マージ・未リリース**。次はK6の安定化/低I/Oと全stack実動作検証を優先する。
