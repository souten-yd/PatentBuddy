# RAG 向けデータベースの調査と用途別ランキング（2026-11 時点）

調査日: 2026-11-10。2026 年の比較記事・公式情報をもとに、**TS-253Be（J3455・RAM16GB・HDD）上の QnapLibrary** と、
将来の別PC/コンテナ拡張の両面で評価した。評価は 5 段階（★5 が最良）。

## 前提となる 2026 年の動向

- 2026 年の「ハイブリッド検索」は、密ベクトル・学習型スパース（SPLADE 系）・BM25 を融合（RRF 等）するのが標準。固有名詞・型番・特許番号は密ベクトルだけでは取りこぼすため、**BM25 の併用が必須**。
- 専用ベクトル DB の主要候補は Pinecone（マネージド）、Weaviate（ハイブリッド重視 OSS）、Qdrant（Rust・フィルタ性能・セルフホスト）、Milvus（超大規模）、Vespa（大規模ハイブリッド）。
- 「専用ベクトル DB が要らない」ケースも増加: pgvector（Postgres 拡張）、組込み型の sqlite-vec / LanceDB / Chroma / DuckDB VSS。
- sqlite-vec の安定版 v0.1.9（2026-03）はブルートフォース検索のみで、IVF/DiskANN は alpha 版のみ。数十万ベクトル程度までが現実的。
- 2026-09 に SQLite 本体のソースツリーへベクトル検索拡張 vec1 が取り込まれた（将来、標準 SQLite でベクトル索引が使える可能性）。
- 埋め込みモデルは多言語の Qwen3-Embedding（0.6B/4B/8B、Matryoshka で次元可変）、日本語特化の ruri-v3 系（70m〜310m、JMTEB で高精度）が有力。API では OpenRouter が `/api/v1/embeddings` を提供（OpenAI 互換）。

## 評価軸

| 軸 | 意味 |
|---|---|
| NAS適合 | J3455/16GB/HDD で常駐できるか（RAM・CPU・ディスク I/O・依存） |
| 日本語 | 日本語の語彙検索（形態素/2-gram）とハイブリッドの組みやすさ |
| 規模 | 快適に扱える件数 |
| 運用 | 導入・更新・バックアップの容易さ（QPKG 単体で完結するか） |
| 機能 | フィルタ、ハイブリッド、マルチベクトル、スナップショット |

## 総合ランキング（QnapLibrary の本体ストアとして）

| 順位 | 方式 | NAS適合 | 日本語 | 規模 | 運用 | 機能 | 判定 |
|---|---|---|---|---|---|---|---|
| 1 | **SQLite FTS5（2-gram）+ RAM ベクトル（本実装）** | ★★★★★ | ★★★★☆ | ★★★☆☆（〜数百万チャンク/ベクトル〜10万） | ★★★★★（依存ゼロ・1ファイル） | ★★★☆☆ | **採用**。全文は BM25、ベクトルは任意。I/O 最小 |
| 2 | SQLite + sqlite-vec（vec0） | ★★★★☆ | ★★★★☆ | ★★★☆☆ | ★★★☆☆（拡張の配布・Python の拡張ロード可否に依存） | ★★★☆☆ | 将来の任意加速。QTS の Python が load_extension 可なら有効化 |
| 3 | Qdrant（Container Station） | ★★★☆☆（常駐 RAM 数百MB〜） | ★★★☆☆（BM25 はスパースで別途） | ★★★★★ | ★★★☆☆ | ★★★★★ | **10万ベクトル超で推奨する拡張先**。payload フィルタとスナップショットが強い |
| 4 | LanceDB（組込み） | ★★★☆☆（Python ホイール必要） | ★★★☆☆ | ★★★★☆ | ★★☆☆☆（QTS Python へ pip が必要） | ★★★★☆（FTS+ベクトル） | 別PC側の大規模処理向け |
| 5 | PostgreSQL + pgvector（+pg_bigm） | ★★☆☆☆ | ★★★★★（pg_bigm で日本語 2-gram） | ★★★★☆ | ★★☆☆☆ | ★★★★☆ | 既に Postgres を運用しているなら有力 |
| 6 | Weaviate | ★★☆☆☆ | ★★★☆☆ | ★★★★★ | ★★☆☆☆ | ★★★★★（BM25F+ベクトル統合） | 別サーバー向け |
| 7 | Chroma | ★★★☆☆ | ★★☆☆☆ | ★★★☆☆ | ★★★☆☆ | ★★★☆☆ | 試作向け |
| 8 | Milvus / Vespa | ★☆☆☆☆ | ★★★☆☆ | ★★★★★ | ★☆☆☆☆ | ★★★★★ | 億件規模。本用途には過剰 |
| — | Pinecone 等マネージド | — | ★★★☆☆ | ★★★★★ | ★★★★☆ | ★★★★★ | データを外部に出すため特許の未公開情報には不適 |

## 用途別ランキング

### 特許調査（新規性・進歩性・侵害・FTO）
1. **FTS5（2-gram）主体 + 請求項単位チャンク + ベクトル補助**: 特許は用語の一致が決定的（構成要件・数値範囲・化学名）。請求項を 1 項 1 チャンクで索引し、BM25 で網羅、ベクトルで言い換えを拾う。
2. Qdrant（IPC/FI/出願人/日付の payload フィルタ）: 文献数が 10 万件を超え、分類・日付で絞る調査が多くなったら。
3. pgvector + pg_bigm: SQL での集計（出願人別・年別の件数推移）を重視する場合。

### 新規特許創出（アイデア発想・空白領域探索）
1. ベクトル（意味の近さ）+ 分類（IPC）集計: 近いが組合せが無い領域を探す。埋め込みは Qwen3-Embedding / ruri-v3。
2. 本実装の RRF ハイブリッド + LLM による差分抽出。

### 規格調査（JIS・ISO・IEC）
1. **FTS5 メタデータ DB**（規格番号・名称・制定/改正年・ICS・対応国際規格）＋利用者が正規入手した本文の私的取り込み。規格番号の完全一致検索が最重要。
2. ベクトルは本文を取り込める範囲のみ。

### 世界情勢・市場・ニュース
1. FTS5 + 日付ソート（新しさが重要）。件数が多くても見出し・要約中心なので軽い。
2. ベクトルは要約の重複除去・話題クラスタリングに使う（任意）。

### 社内メモ・議事録・汎用
1. ハイブリッド（BM25 + ベクトル）。文書数が少ないうちは RAM ベクトルで十分。

## 結論（採用方針）

- **本体**: SQLite（WAL）+ FTS5（日本語 2-gram、`unicode61`）+ RAM 常駐ベクトル（float32、numpy があれば行列演算）+ RRF。依存ゼロで QPKG に同梱でき、ディスク読み書きは取り込み時とページキャッシュ外読み出しのみ。
- **埋め込み**: NAS では計算しない（J3455 は AVX 無し）。OpenRouter / 別PC の Ollama 等で計算し `/api/v1/vectors` へ投入、または管理Webの「ベクトル化」で外部 API を呼ぶ。
- **拡張**: ベクトルが 10 万件を超えたら Qdrant（Container Station）アダプタを追加（`docs/roadmap.md`）。SQLite に vec1 が標準搭載されたら移行を検討。

## 出典

- [Vector database comparison 2026 (BigData Boutique)](https://bigdataboutique.com/blog/vector-database-comparison-2026)
- [Best Vector Databases for RAG in 2026 (FutureAGI)](https://futureagi.com/blog/best-vector-databases-for-rag-2026/)
- [Best Vector Databases in 2026 (Dupple)](https://dupple.com/learn/best-vector-databases)
- [Self-Hosted Vector Databases for RAG 2026 (D-Central)](https://d-central.tech/self-hosted-vector-databases/)
- [Comparing Embedded Vector Databases in 2026 (Actian)](https://www.actian.com/blog/developer/comparing-embedded-vector-databases/)
- [SQLite、ベクトル検索拡張 vec1 を本体リポジトリに取り込み](https://book.st-hakky.com/news/sqlite-vec1-vector-search-extension)
- [Ruri: Japanese General Text Embeddings](https://arxiv.org/html/2409.07737v1)
- [OpenRouter Embeddings API](https://openrouter.ai/docs/api/reference/embeddings)
