# 汎用文献メタデータと索引の設計

PR-Dで実装済みなのはコレクション内外部IDの完全一致、本文を返さない一覧、IDカーソル、冪等バッチ。以下の構造化フィルタは後続P2の設計であり、現行APIの実装済み機能ではない。

## 正本と互換

`(collection_id, ext_id)`を唯一の冪等キーとする。外部IDがない資料には再送の重複保証をしない。同一IDの版を別文献として保持する収集元は、入力時に版を含む安定IDを割り当てる。元の識別子・版・出典表記はmetaに残し、既存ext_idを一括書き換えない。

本文はdocuments.body、検索断片はchunks、FTSは派生索引、vectorsは再構築可能な計算結果。FTS contentの重複は現在の互換設計に由来し、contentless/external-content化や原本blob保存はこのPRで無条件に変更しない。

## フィールド契約案

| 意味 | 元表記の保存 | 検索用正規形案 |
|---|---|---|
| 特許公開/出願番号 | meta.identifiersのscheme/value | scheme別規則で国・番号・kindを分離。欠落kindを推測しない |
| JIS/ISO/IEC規格番号 | 同上 | 発行団体・番号・部番号を分離し、版年を独立列へ |
| 改版 | meta.edition | 文字列版と版日を区別。前後関係を推測せずsource/version保持 |
| IPC/CPC/ICS | meta.classificationsのscheme/code | scheme別の記号正規化、1文献複数値を許可 |
| 公開/発行/改訂日 | meta.datesのkind/value | ISO日付、精度(year/month/day)を保持し不明日を補完しない |
| 出願人/発行者 | meta.partiesのrole/name | 原名と検索用正規形を並存。法人同一性を自動確定しない |
| 出典/利用許諾 | source/url + meta.provenance/license | 取得日時・原本hash・利用条件URL・確認日時。公開属性と再配布承認を分離 |

既存自由形式metaを拒否/削除せず、追加の検索表 `document_identifiers(doc_id, scheme, value, edition)`、`document_classifications(doc_id, scheme, code)` と日付/出典の必要列を段階追加する。元metaと派生表を同一トランザクションで更新し、原本変更時の公開承認無効化を維持する。初回バックフィルは明示ジョブ・小バッチ・進捗カーソルで再開可能にし、毎起動全件再構築は禁止。

完全一致は `(scheme,value,edition,doc_id)`、分類は `(scheme,code,doc_id)`、日付は `(kind,value,doc_id)` を候補とする。実装前後でEXPLAIN QUERY PLAN・各索引容量・追加write bytesを比較して採用する。未指定フィルタのために全件metaをPythonへ読み込まない。APIはAND/OR・日付精度・改版の意味を明示し、カーソルはフィルタ条件に結び付ける。旧タイトル部分一致は互換用で索引検索とは呼ばない。

## 後続受入

特許/規格/論文を混ぜた1千/1万/10万件で、原表記の往復一致、複数分類、版衝突、更新/削除/rollback、復元、構造化フィルタの結果・索引利用とI/Oを検証する。ライセンス検索で外部AI公開権限を自動付与しない。原本PDFは別の内容hash blob設計とGC/復元検証が完了するまで二重保存を追加しない。
