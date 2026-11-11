# 特許の検索・原本取得元

調査日: 2026-11-11。実装は本書の計画と区別しHANDOFFで追跡する。

|取得元|公式手段|条件|今回の扱い|
|---|---|---|---|
|PATENTSCOPE|ブラウザ検索/手動ダウンロード|WIPOアカウント無料。自動ロボット禁止|公式画面への導線とダウンロード済PDF取り込み|
|WIPO PCT Webservice|SOAP|limited CHF600/年、full CHF2000/年、条件付き利用|有料契約を勝手に行わない。未実装|
|EPO European Publication Server|REST v1.2 PDF/XML等|登録不要、欧州A/B公報のみ|番号指定PDF取得を先行実装。キーワード検索APIではない|
|EPO OPS|REST|利用登録、4GB/週まで無料|既存書誌/要約検索。画像取得は別工程|
|USPTO ODP|REST|アカウント/APIキー必要|既存実験的検索。文書取得は別工程|

EPO容量上限は公式fair-useページ5GB/7日と2024年API仕様10GB/7日に差があるため、大きい方を保証しない。単発・上限付き取得とし、同時実行と転送速度を制限する。検索や公報番号の送信は明示操作だけで行い、私的な本文から外部検索語を自動生成・送信しない。

公式資料:
- https://www.wipo.int/en/web/patentscope/faqs_patentscope
- https://www.wipo.int/en/web/patentscope/data/index
- https://data.epo.org/publication-server/doc/EPS%20REST%20services.pdf
- https://www.epo.org/en/service-support/ordering/fair-use
- https://data.uspto.gov/apis/bulk-data/search

実装条件: stdlibのみ、固定HTTPS origin、リダイレクト拒否、URL/パス入力不可、公報番号厳密検証、PDF magic/サイズ/時間上限、管理者認証/CSRF、秘密値なし、取得だけで正本に自動登録しない。既存PDF取込からOCR・原本保存・Host LLMへ接続する。
