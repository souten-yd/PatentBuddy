# 大規模化・分析・PC クライアント（v0.3）

## Qdrant（任意）

- 設定 > 検索基盤 で「Qdrant」を選び URL（例 `http://127.0.0.1:6333`）とコレクション名を保存 →「SQLite → Qdrant 全同期」。
- 以後、保存されたベクトルは SQLite と Qdrant の両方に入る（SQLite が正本）。検索は Qdrant を使い、失敗したら RAM 索引に戻す。
- ペイロード `collection_id`・`model` で絞り込むため、埋め込みモデルを変えても空間が混ざらない。
- Container Station 例: `docker run -d --name qdrant -p 6333:6333 -v /share/Container/qdrant:/qdrant/storage qdrant/qdrant`（RAM 目安: 1024 次元×10 万件で数百 MB）。

## リランカー（任意）

- 設定 > AI > リランカー。`POST {base_url}/rerank`（Cohere/Jina 形式 `{model, query, documents, top_n}` → `results[{index, relevance_score}]`）に対応する API を指定。
- 上位 N 件（既定 30）だけを並べ替える。エラー時は元の順位。検索 API は `rerank: true/false` で個別指定可。

## 検索フィルタ

- `/api/v1/search` に `date_from` / `date_to`（YYYY-MM-DD、文書の date）と `kinds`（コレクション種別）を追加。画面の検索にも日付欄。

## 分析

- `GET /api/v1/analytics?collection=&field=` … 年別・出典別件数、meta 項目（配列可。applicants, ipc など）の上位 25、上位 10 値×年の行列。
- 画面「分析」で棒グラフとヒートマップ（空白領域・出願人の動向の把握に）。

## PC クライアント `qnaplibrary_client.py`

Release 資産と Linux 版 tar.gz に同梱（標準ライブラリのみ）。

```sh
python3 qnaplibrary_client.py pair --url http://NAS:17871 --passcode <パスコード> --name my-pc
python3 qnaplibrary_client.py push --collection 審査基準 --kind law ./審査基準/        # txt/md/pdf/csv/ndjson/json
python3 qnaplibrary_client.py embed --collection patents-jp --endpoint http://localhost:11434/v1 --model qwen3-embedding:0.6b
python3 qnaplibrary_client.py search "固体電解質" --collection patents-jp
```

- PDF は `pdftotext`（poppler）か Python の `pypdf` があれば変換（スキャン PDF の OCR は対象外）。
- `embed` は NAS の `/api/v1/embedding-info` の切り詰め次元に合わせ、モデル名＋次元をタグにして保存する。検索時のクエリも同じ空間で埋め込むため、NAS の 設定 > AI > 埋め込み も同じモデル（別PC の Ollama など）にする。
