# HTTPS（Tailscale Serve）とパスキー

## 方式

TLS 終端は NAS 上の Tailscale が行い、QnapLibrary は従来どおり HTTP :17871 で待ち受けます。証明書の取得・更新は Tailscale が自動で行います。

```sh
tailscale serve --bg --https=8443 http://127.0.0.1:17871
```

開く URL: `https://<NAS名>.<tailnet名>.ts.net:8443/`

## QnapDownloader との共存

| 項目 | QnapDownloader | QnapLibrary | 競合 |
|---|---|---|---|
| Tailscale Serve の HTTPS ポート | 443 → 127.0.0.1:17864 | **8443** → 127.0.0.1:17871 | なし（ポート別） |
| 証明書 / ホスト名 | `<NAS>.ts.net` | 同じ | 共用で問題なし |
| ログイン Cookie | QnapDownloader 独自名 | `ql_session` | 名前が別のため上書きしない（Cookie はポートで分離されない点に注意して命名） |
| パスキーの RP ID | `<NAS>.ts.net` | 同じ `<NAS>.ts.net` | 各アプリは自分が登録した資格情報 ID だけを `allowCredentials` に渡すため誤ログインなし。端末のパスキー一覧には両方が並ぶので、登録名を分けると分かりやすい |
| HSTS | 送らない | 送らない | LAN の http も引き続き使える |

## 判定ロジック

- 接続元が loopback（Serve は 127.0.0.1 から接続）で、`X-Forwarded-Proto: https` または Host が `*.ts.net` のとき HTTPS とみなす。loopback 以外からの `X-Forwarded-Proto` は信用しない。
- パスキーは HTTPS かつ名前付きホスト（IP アドレス不可）のときだけ登録・ログイン可能。RP ID は Host からポートを除いた名前。
- HTTPS で管理者がログインすると、その URL を `server.https_url` に一度だけ記録し、HTTP 画面に「HTTPS で開く」リンクを表示する。

## 注意

- Serve 経由の接続元は全端末で 127.0.0.1 になるため、ログイン失敗回数制限は端末共通の枠になる。
- Serve 経由のリクエストは LAN 扱いになり、ペアリングとデバイストークンが使える（tailnet 内からのみ到達可能なため）。
- MagicDNS 名（マシン名・tailnet 名）を変えるとパスキーは使えなくなる。パスワードで入り、登録し直す。
- Tailscale を使わない場合: `server.tls_cert` / `server.tls_key` に証明書を指定して直接 HTTPS で起動することもできる（更新は手動）。
