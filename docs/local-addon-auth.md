# 同一ユーザーのローカル自動接続

Linuxの同一OSユーザーで動作するResearchDataHubとPatentBuddyを、UnixソケットのSO_PEERCREDで相互確認して接続する。loopback HTTPに来たという理由だけでは権限を与えない。

- `/run/user/<uid>/researchdatahub/<port>.sock`、ディレクトリ0700/ソケット0600。rootでは利用しない。
- 認証情報はサーバープロセスのRAMだけに保持し、再起動時に失効。読み取り専用・loopback限定。管理者初期設定前は発行しない。
- 明示的なconnection.jsonがあれば優先。リモート接続への自動適用なし。
- 同一OSユーザーのプロセスは同じ信頼境界。アドオンIDの自己申告だけでプロセスを識別できるとは主張しない。別ユーザー・Webからの接続は認めない。
- サーバー設定 `auth.local_auto_connect=false` で無効化できる。

実装・受入は進行中。
