# 特許庁 特許情報取得API（任意）

方針: **既定では登録しない（使わない）**。登録した場合にすぐ使えるよう、接続部分は実装済み。

## 未登録のときの特許データの集め方

- EPO OPS（無料・4GB/週、日本の公報の書誌・要約も含む）
- 別PC からの一括投入（`/api/v1/collections/{name}/documents`、請求項は `sections.claims`）
- 手作業での取り込み（管理Web > データ > 取り込み）と、J-PlatPat 固定アドレス URL の保存（自動取得はしない）

## 登録する場合

1. 特許庁の案内（https://www.jpo.go.jp/system/laws/sesaku/data/api-provision.html ）の利用規約・利用の手引きを確認
2. 利用申込書をメールで提出（個人でも可）。ID とパスワードが発行される
3. 管理Web > 設定 > 外部キー に `JPO 特許情報取得API ID` と `パスワード` を登録
4. 収集 > 「JPO 特許情報取得API（経過情報）」が有効になる

## 実装メモ（要実地確認）

- 認証: `POST {base_url}/auth/token`（password グラント）→ Bearer トークン
- 経過情報: `GET {base_url}/api/patent/v1/app_progress/{出願番号数字}`
- `base_url` は設定 `connectors.jpo.base_url`（既定 `https://ip-data.jpo.go.jp`）。仕様変更時はここと `connectors.jpo_progress()` を直す
- API ごとに日次アクセス上限がある。1 リクエストごとに 1 秒以上空けている
