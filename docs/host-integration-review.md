# PatentBuddy Host連携 — PR-E着手前の実コード確認

2026-11-10。これは実装済みの宣言ではない。PR-Dの待機時間にPR-Eの前提を確認した。

## 確認したrevision

- ControlDeck `origin/main` `815fc05d3055b948b5dbd4c3416dbcc0da64f220`。稼働側checkout HEAD `b8528a6`とは異なる。稼働checkoutには別作業の未コミット変更があり、変更・切替していない。
- ControlDeckMediaForge最新main `79527ca5b4a5002d4949aea049562536b538eb8a`（`/tmp/pb-contract-MediaForge`）。
- ControlDeckSonicForge最新main `bdd89b8299f284483e06871a3a26ccd556b38a6a`（`/tmp/pb-contract-SonicForge`）。
- PatentBuddy PR #14のheadは `feat/control-deck-addon-foundation`。既存manifestのhost_capabilitiesは空で、本格LLM/UI結合が未完了。

## 実契約と実装時の扱い

| 項目 | 実コードで確認した契約 | PatentBuddyで必要な対応 |
|---|---|---|
| 身元 | `backend/app/addon_runtime/router.py`: POST `/api/v1/addon-runtime/token/introspect`。active/addon_id/subject/expires_at/granted_capabilities、存在すればactor_subject | 期限・対象addon・能力をサーバーで毎回検証。subjectと長期所有者actor_subjectを混同しない。raw bearerはログに出さない |
| AI | `addon_runtime/ai.py`: `ai.inference`、`/{addon_id}/ai/capabilities`、`complete`、`stream` | text.generate/vision.analyzeを指定。model名・provider URLをユーザー入力で選ばせずHostが選択 |
| GPU | `_complete_with_host_admission` / `_stream_with_host_admission`: llama.cppはHost gateway leaseでadmissionしensure_ready、終了/cancelでrelease | Host推論に対して別のGPU leaseを重複取得しない。PatentBuddy独自計算が必要な場合だけresources契約を使う |
| ローカル性 | `models_mgmt/ai_gateway.py`: runtime policyでllama.cppまたはOllama。capabilities応答はavailable等のみで、クラウド中継不在の証明は返さない | localhost/availableだけを安全根拠にしない。実Host runtimeの設定と実行元を検証し、未確認なら機密入力を拒否。外部LLMへのfallbackを作らない |
| 長期job | SonicForge `host/client.py`: create/attach、control、credential refreshとlease refresh時にscope/subjectを照合 | 調査jobのキャンセル/再開と短期token更新はHost契約で処理。独自の無期限credentialを発行しない |
| UI | Host `design-addon-platform-v2.md`: `/addon-frame/{id}/...`、opaque-origin sandbox、MessagePort bridge | NAS管理Cookie/localStorageを前提とせずHost proxy/bridgeを使う。320pxを含む実ブラウザ受入が必要 |
| 配布 | Add-on v2とFeature bundle、Host側manifest検証・安全展開・health・atomic switch・署名 | 配布物/署名/publisherを既存契約に合わせる。勝手な署名鍵作成・Host再起動はしない |

ResearchDataHubのscope付きAPIが唯一の正本への入口。Host principalをResearchDataHubの公開専用tokenへ変換しない。private業務APIへの権限対応と、明示公開抜粋APIは別経路にする。

## 今回の実行確認範囲

旧ControlDeckローカルLLM port8097のlistener/llama-serverは不在だった。前回のPDF解析成功は保持するが、今回のLLM成功として再利用しない。Host認証済みAI呼出し・インストール済みFeature・署名・iPhone幅の操作は未検証。PR-Eで現在の管理認証/設定を使って結合し、モデル起動はHost admissionへ任せる。
