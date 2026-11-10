# 同一ユーザーのローカル自動接続

Linuxの同一OSユーザーで動作するResearchDataHubとPatentBuddyを、UnixソケットのSO_PEERCREDで相互確認して接続する。loopback HTTPに来たという理由だけでは権限を与えない。

- `/run/user/<uid>/researchdatahub/<port>.sock`、ディレクトリ0700/ソケット0600。rootでは利用しない。
- 認証情報はサーバープロセスのRAMだけに保持し、再起動時に失効。読み取り専用・loopback限定。管理者初期設定前は発行しない。
- 明示的なconnection.jsonがあれば優先。リモート接続への自動適用なし。
- 同一OSユーザーのプロセスは同じ信頼境界。アドオンIDの自己申告だけでプロセスを識別できるとは主張しない。別ユーザー・Webからの接続は認めない。
- サーバー設定 `auth.local_auto_connect=false` で無効化できる。

HTTP loopbackの同一PC構成が対象。TLS専用サーバー、root、別OSユーザー、独自ポートの自動探索は対象外で、明示的な接続設定を利用する。

ソケット/排他lockのみを作成し、認証の都度DBや秘密ファイルへ書き込まない。認証済みHost経由でのみアドオンの検索APIを利用できる。

## 分析結果保存の限定権限

読み取り用の既存ソケット/tokenは変更しない。分析結果を保存するときだけ、同じUID確認を行う `<port>-analysis.sock` から独立したRAM内認証を取得する。この権限は通常の読取と `POST /api/v1/documents/{id}/analyses` だけに使用でき、文献/案件の書換えや管理操作は許可しない。サーバー再起動・local_auto_connect=falseで停止する。別端末には自動適用しない。
