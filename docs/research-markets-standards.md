# 調査ジョブ・市場データ・規格メタデータ（v0.4）

## 調査ジョブ
- 収集画面の「調査ジョブ」、`POST /api/v1/research {question, collections?, provider?, use_news?}`、MCP `research_start` / `research_get`。
- 手順: LLM がサブ質問（最大 6）と英語ニュース検索語を作る → 質問とサブ質問ごとにライブラリ検索（各 6 件、根拠は最大 30）→
  任意で GDELT（直近 1 か月・25 件を `news-research` に保存）→ LLM が根拠番号付き Markdown レポート → `reports` コレクションに保存・通知。
- 同時に 1 件だけ実行（NAS 負荷と API 費用の暴走防止）。

## 市場・企業・統計
| 収集元 | キー | 内容 |
|---|---|---|
| e-Stat | アプリケーションID（無料登録） | 政府統計の表一覧（表名・調査年月・府省・URL） |
| EDINET | API キー（無料登録） | 指定日の提出書類一覧（会社名・書類名で絞り込み） |
| SEC EDGAR | 不要。ただし連絡先付き User-Agent 必須（設定 > 外部キー） | CIK の最新提出書類（10-K/10-Q/8-K 等）のリンク |

## 規格メタデータ（JIS / ISO / IEC など）
- 種別 `standard` のコレクションで「規格CSVテンプレート」（id,title,date,status,org,ics,intl,url,body）を使う。本文は正規に入手したもののみ取り込む（JISC の閲覧画面は保存・印刷不可）。
- 規格番号は表記ゆれを吸収して索引（`JIS B 1194` / `JISB1194` / 全角も同じ）。文書 ID も検索対象。

## 検索の改善
- 文章の質問（例「固体電解質の課題は？」）でフレーズ一致が少ないときは、語の重なり（2-gram の OR）で追加順位付け（trace の `bm25_loose`）。チャットの RAG・調査ジョブの取りこぼしを防ぐ。
