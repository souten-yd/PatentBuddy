# K1c — 知識候補の正本保存・専用権限（実装契約）

状態: **Draft PR #31**（2026-11-17）、base: Draft PR #30 → Draft PR #29。**本番UI/Hostジョブとの連結は未実装**。

## K1cの実装

- `qnaplibrary/knowledge_store.py` はResearchDataHub既存SQLiteの `document_analyses` に `kind='knowledge'` でimmutableなJSON候補を保存。GraphRAGノードへの自動登録・別DB・DB schema migrationはなし。
- 保存時に**同じSQLite書込transaction内**で本文・document revisionを読み直し、`knowledge_essence.validate`を再実行。真正の引用文字範囲、モデル候補が `model_inference/unreviewed` のみであること、local_onlyのHost model/runtime fingerprint形式、12件・字数上限を検査。偽造・版違いは保存前に拒否し、transactionをrollback。
- `id` はHost Jobから渡す不変識別子（1〜128英数字・`_`・`-`）。同じ `id/doc_id/source_revision/canonical_content` への再送は**DB更新/監査追記ゼロ**、別内容で同じIDを再利用すると拒否。保存時に原文・原文全文を監査ログへ書かず、IDのみ記録。
- `GET /api/v1/documents/{did}/knowledge-proposals` は認証済みread権限で直近20件をread-only取得。元文書の現revisionと保存revisionの比較で `stale` を表示し、`review_status` は常に `unreviewed`。一貫した読取のためStore lock内でrevisionとrowsを取得。承認/採用更新のAPIはまだ存在しない。
- `POST /api/v1/documents/{did}/knowledge-proposals` は専用 `knowledge_propose` scopeまたは管理者セッション**のみ**。既存 `analysis`/`pdf_analysis`/`pdf_import`/`rw`/`ro`/`published` tokenの権限は増やさない。`POST /api/v1/documents/{did}/analyses` は今までどおりsummary/claimsのみ（PR #23でrelations/chart追加予定だが本PRは触らない）。
- Linux同一UID UDSには **`knowledge_propose`専用socket** を追加し、ランダム `qlk_` プレフィクスのトークンを別発行。Loopback以外拒否、権限0600・同一UIDの既存検証を再利用。RDHのHTTPSリモートモードでは管理者発行済みの専用device tokenを `connection.json` の `knowledge_server_token` に別管理できるが、**ユーザーのキー入力なしのUI導線は未実装**。従来 `server_token` を黙って使い回さない。
- `qnaplibrary/addon_client.py` は保存先の厳密なURL形式でのみ別権限へ切替。検索・通常解析・PDF取り込み・既存読み取り経路には新tokenを渡さない。ControlDeck Hostからの新しい実行capabilityは追加しない。

## 実際のテスト結果と未検証

- `tests/test_knowledge_store.py` に実サーバーLiveServerを使う回帰シナリオを**追加した**。対象: admin/anonymous/各token scope/ローカル同一UID、保存冪等・GETゼロwrite・偽引用/不正JSON/approved偽装/cloud偽装・原文改訂stale・結果ID衝突・AddonClient credential切替。
- **実行したテスト**: GitHub上の `knowledge_store.py` と同一blob SHA (`cbe1e60aa7e6ba1a403a36e5715f224797d5ef5b`) を隔離環境に配置し、SQLite mock Storeと簡略化したknowledge validatorで保存ロジック6件PASS。これは**実Store・実HTTPの受入テストとは異なる**。新規LiveServerテスト・既存全体の `scripts/verify.sh` は、ローカルrepoをcloneできず未実施。新APIの稼働確認/End-to-endも未実施。
- Runtime/manifest/ControlDeck frontend/Vue default変更、DB schema追加、外部CDN/ネットワーク、Shell実行、autonomous control、起動時npm buildなし。旧Hostは`require_provenance`未対応、知識の生成と保存をひとつのHost jobとして使える状態ではない。

## K1d: 実接続を行う次のPR — Codex向け詳細指示

**Scope/Allowed**: 既存ControlDeck Host `HostSession` と `AnalysisJobs` を使い、UIの「知識を抽出」から `knowledge_generation.generate` を実行→ `serialize`→新しい `knowledge-proposals` POSTへ保存→GET結果表示の最短経路のみ。上限・取消/lease・Host finished receipt・失敗表示・冪等を既存ジョブ実装から継承。ControlDeck [UI/UX規範](controldeck-ux-contract.md)準拠。PR #23の `require_provenance` を**先にmainに検証統合**し、重複改変しない。

1. `main`, Draft PR #23/#29/#30/#31の**実diff/real files**（`addon_host.py`, `addon_jobs.py`, `generation_contract.py`, `relation_proposals.py`, `api.py`, `store.py`, `auth.py`, `server.py`, `addon_client.py`, tests, manifest, UI）を読み、先行PRの競合を解消する。
2. Host `ai/capabilities` で `local_only` と `require_provenance` がともにsupportedの場合だけJob作成可。旧Hostへ本文を一切送らない（後からTypeErrorで失敗させるだけでなくUI操作前に不足を説明する）。
3. `AnalysisJobs.start(...,kind='knowledge')` は機能選択による明示開始。既存Host credentials/lease/heartbeat/cancel/resume/final receiptを再利用。モデル応答の `generation_provenance` をHostから取得しモデル本文内のprovenanceは信用しない。AI出力が原文に存在しない/引用複数なら「根拠を特定できない」と失敗して保存しない。
4. 保存は `kind=knowledge`, `content=serialize(validate(...))` で今回の専用POSTを利用し、失敗時に通常analysis権限へfallbackしない。Hostジョブ/保存の整合失敗では再実行・reconcileを提示。
5. ControlDeck Embedded Viewのtheme/Bridge/Host shellを踏襲し、画面の主操作は「知識を抽出」1つ、待機/実行/失敗/再試行/取消、知識カードと正確なquoteを表示。320pxで1ペイン、Host navを二重化しない。既存ui.htmlをdefaultのまま保ちVue/read-onlyやruntime level_0_manual_onlyを変更しない。
6. 合成文献を使うE2E: Host provenanceなし/無効、live生成、source改訂直前のrace、scope横断（analysis/rw/publishedが保存不可）、冪等write count、同じ引用複数該当、cancel at save boundary、Job state restart、iOS接続切れ、原文戻りリンク。 `bash scripts/verify.sh`, `bash scripts/build-linux.sh dist`, ControlDeck実機で確認後にのみレビュー→マージ→バージョン更新と公開Release。

**Do NOT**: 旧Hostプロトコルへ暗黙fallbackしない、クラウドへ未公開情報を送信しない、raw source配信・redirect/CDN・自動出願/自律実行・権限拡張・独自グラフDB・別API新設・起動時npm build・Vue default化をしない。

**Expected final state**: 利用者がControlDeck画面から対象文献を選び、ローカルモデルで抽出したunreviewedの知識候補を既存RDHのSQLiteへ安全に保存し、ControlDeck準拠のUIで根拠・stale表示を見られる。証拠のない推論は事実扱いせず、採用/レビューを明示的に残す。未検証の場合はDraftのまま。
