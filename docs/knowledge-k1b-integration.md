# K1bからK1cへの実装接続 — Host証跡・正本保存・レビュー

状態: **K1b実装とK1c以降の手順**（2026-11-17）。この文書では未実装のAPI/Job/UIを既存機能として扱わない。

## 現在の成果
- K1a [PR #29](https://github.com/souten-yd/PatentBuddy/pull/29) の `knowledge_essence.validate(document, proposal)` が、候補のスキーマ・出典文書のID/版・原文中Unicode文字範囲・未承認/推論属性・Host provenance形式を検査する。
- K1b [PR #30](https://github.com/souten-yd/PatentBuddy/pull/30) の `knowledge_generation.generate(session, document)` は、選択した文献本文をHostの `stream(require_provenance=True)` のみへ渡す。JSONは**itemsのみ**をモデルが返し、版/ID/根拠位置/生成provenance/basis/reviewはアドオン側で構成する。
- quoteが原文に1回だけ存在するときのみ位置を復元し、欠落・曖昧さ・JSON異常・引用詐称を拒否。独自モデルfallback、別LLM、勝手な保存なし。空配列は妥当な結果（無理に知識を発明しない）。
- `qnaplibrary/addon_host.py` の**現行main**の `HostSession.stream(messages)` はrequire_provenance非対応。対応はDraft [PR #23](https://github.com/souten-yd/PatentBuddy/pull/23) にあり、Host AI応答のmodel/runtimeのopaque fingerprintを返す。K1bは**旧Hostで自動的に失敗**して文献本文を送信しない。成功はローカルfake Hostでの契約試験に限る。
- K1a 10件 + K1b 11件のunittest = **21件PASS**。4つの実ソースがGitHub branchのGit blob SHAに一致し、Python compileall PASS。全体verifyと実Hostは未実施。

## K1c: 実ジョブと保存の最小スライス（次のPR）
1. **main/既存PR確認**: PR #29, #30, #23, #24の状態と全diff、mainの `addon_host.py`, `addon_jobs.py`, `store.py`, `api.py`, `server.py`, `addon_client.py`, `auth.py`, `local_auth.py`, `tests/`, manifest、およびControlDeck Hostのlocal_only/provenance/API contractsを直接読む。PR #23の大きな変更を黙って採用せず、競合点を一覧にする。
2. **Host契約**: 既存のhost `stream(require_provenance=True)` と生成証跡・resource lease/heartbeat/cancel/terminal receiptを共有する。古いHostは**開始前に明示的に拒否**し、機密文献をlegacy Host、クラウドAI、公開検索、第三者APIに送らない。
3. **保存契約**: 永続正本はResearchDataHubの既存SQLiteのみ。可能なら `document_analyses` にkind=knowledge（あるいは後方互換の小さな専用候補表）として**immutable snapshot**を保存。POSTのHTTP管理者/トークンスコープは最小権限の知識候補保存用に切り、既存read-only, published-only, pdf_analysis, analysis等の権限を**暗黙に広げない**。必要なら専用scope（knowledge.propose）をHost/Add-on/API認証経路と整合し設計し直す。権限拡張を偶然に生む新kindの単純追加は不可。
4. **二段階原文検証**: アドオン受取時+**ResearchDataHubサーバー保存transaction内**で、doc ID、revision/hash、範囲、quoteを再照合。根拠を保存することで意味的事実が確定したと表示しない。保存時のソース変更は409相当でfail closed。
5. **冪等**: 同じHost Job/result IDと同じcontentは再送でwriteゼロ。異なる結果の同ID再送、job取消/保存応答消失、model版が異なる再生成は別版/明示再実行。GET/idleはSQLite writeゼロ。監査ログはID/操作だけで原文・アイデア・プロンプトなし。
6. **レビュー/graph**: 生成直後はunreviewed/model_inference、原文に合致してもfactualに自動昇格なし。グラフへ登録する操作は明示的で、PR #23のgraph_nodes/edgesまたはその後継を再利用。AI仮説は未承認GraphRAGデフォルト探索に混入しない。本文改訂で関連proposal/approved edge/依存chart/ideaをstale、承認復活なし。
7. **UI**: ControlDeckの既存Embedded View内に一つの「知識を抽出」主操作を設け、Host Jobsの待機理由/取消/失敗/再試行を表示する。見出しやグローバルナビを二重化しない。知識カードはControlDeck theme、PageHeader/EmptyState/BottomSheet/44px、320px 1列の[UI/UX契約](controldeck-ux-contract.md)に従う。埋込は読み取り専用を既定にし、生成と登録だけ明示的mutationとする。
8. **検証**: 合成文献で local-only Host→AI→quote→正本保存→文献原文へ戻るE2E、原文変更409、無変更write0、旧Host停止、provenance不在/改竄、fake quote、同一語複数箇所、500/取消・保存途中停止、各tokenで認証、残存旧主画面・startupを検証。性能とディスクI/Oは [researchdatahub-performance.md](researchdatahub-performance.md) を使う。

## K1bのScope / Do NOT
**Scope**: モデルからの出力JSONを厳密に検証された候補に変える、**保存しない**pure adapter。`HostSession`の実ネットワークや既存分析ジョブをこのPRでは変更しない。

**Do NOT**: 新しいDB/サービス・外部API/クラウドfallback/自動文献検索、無断公開・自動出願・自動統合、Host強制upgrade、Vue default化、ui.html default変更、runtime level_0_manual_onlyの緩和、raw source serving/redirect/npm build。契約上の「local_only」は実HostとResearchDataHubの出口双方で引き続き検証。

**Expected final state**: JSONのみの検証済みローカルHost応答から原文位置付きunreviewed Knowledge Proposalを生成でき、未知Host・異常データ・模型回答の権限偽装でfail closed。完全な知識蓄積・マップはK1c以降。

**Release**: PR #30はDraft。全体 `bash scripts/verify.sh` とControlDeck/ResearchDataHub実接続未検証のためmainへマージもReleaseもしない。K1bで今使える機能を過大に説明しない。
