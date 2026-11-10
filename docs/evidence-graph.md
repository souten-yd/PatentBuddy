# 根拠付き関係データとGraphRAG

PR-F作業中。既存PR10の行別引用検証を参考にするが、その旧サーバーLLM経路をアドオンへコピーしない。

## 実装順序

1. ResearchDataHubの単一DBに汎用ノード・関係・根拠の版と範囲・取得日時・抽出法・モデル・確認状態を保存。確定候補（引用/ファミリー/優先権/出願人/分類/要件）と推測（課題/解決/効果/置換）を区別し、人手承認しても推測を事実へ変換しない。
2. 根拠の本文変更で関係をstaleにし、承認を無効化。1〜2hop、ノード/エッジ上限、循環除外、indexed adjacencyで全件走査しない。API認証と公開専用tokenの分離を検証。
3. PatentBuddy側でキーワード→vector候補→bounded graph→rerankをHostのローカル推論/Jobs契約へ接続。引用範囲・版を検証したクレームチャート提案と明示承認を画面から操作する。
4. 合成データの境界/取消/復旧/引用偽造と、ControlDeck実LLM・実画面で検証。性能とディスクI/Oを記録し、配布・更新まで実施。

新しい永続書込みは根拠/関係/レビューの正本と監査に必要。探索GETやアイドルで関係を再生成しない。本文や引用・モデル応答を監査に書かない。関係保存の成功だけをGraphRAG全体の完成としない。

## 現在の基盤実装（未配布）

`graph_nodes`/`graph_edges`は正本SQLite内に保持。根拠は文献ID・本文revision・Unicode文字オフセットの半開区間[start,end)・引用原文・UTC取得日時・抽出法を必須とし、推測はモデル版も必須。範囲と引用の完全一致を保存時に検証するが、引用の意味が関係を裏付けるかは人手確認事項。

同じedge ID/同じ内容の再投入は書込みゼロ。異なる結果は新IDが必要。作成時は必ずunreviewed。明示reviewでapproved/rejectedへ変更してもbasis=factual/inferredは変更しない。根拠文献または文献ノードの本文/source変更をSQLite triggerでstaleにし、承認を無効化する。原文を元へ戻しても復活しない。削除はFKで関係を除去。監査にはIDと操作だけを残す。

現段階の書込み/review APIは管理者限定。private read tokenは読取可、published tokenは全拒否。アドオンが提案を保存する狭い権限と人手承認のUIは後続実装。探索は出方向のみ、1〜2hop、seed20/ノード100/関係200以内。承認済みかつ非staleだけを返し、推測は明示include_inferred=true時のみ。隣接索引は状態/確認/根拠種別を含み、上限を返すために不採用関係全件を走査しない。上限到達はtruncatedで知らせる。逆方向探索や検索/LLM/rerank接続は未実装。

## クレームチャート接続（未配布）

アドオンの分析にchartを追加。指定請求項を最大16要件へ分割し、段落の説明文を最後の請求項へ混入させない。前提/結びも行として保持。キーワード検索と承認済みgraph候補から行ごと最大3根拠を選び、Hostのlocal_onlyストリーム/Jobs/取消/heartbeatを利用する。ベクトル候補と再順位付けは未接続で、保存結果にnot_implementedと明記する。生成AIによる要件分割や法的判断の正しさを保証しない。

モデルの行欠落/重複/未知ラベル・他行の引用・肯定判定の根拠欠落を全体拒否。正本保存時も請求項原文/各根拠の版・文字範囲を再検証。analysis_dependenciesとanalysis_reviewsを同一transactionで保存し、根拠の改変・削除時は不可逆にstale/未確認へ戻す。レビューAPIは現在admin専用。画面からの承認と狭いHost認可は後続実装。

合成請求項と対比文献について実ControlDeckローカルLLMで生成/保存、1280/320pxで引用表示・横溢れ/JSエラーなしを確認。一時ユーザー/addon/DB/grantは除去済み。本番文献/接続は変更していない。スクリーンショットはページ上部のみでありチャート領域の目視受入は未完。自動DOM検証と区別する。

## Host検索AIとベクトル正本（未配布）

ControlDeck PR351のlocal-only埋め込み/再順位付けAPIを実Hostへ反映し、BGE-M3とQwen3-Reranker-4Bの既存プリセットで実推論を検証。モデルのopaque file-metadata revisionを座標空間の識別子として扱う（内容hashとは区別）。文献チャンクの本文hash/原文revisionを往復してから最大32件のfloat32ベクトルを正本SQLiteへ原子的に保存する。旧vectors表を上書きしない専用host_vectors/host_vector_spacesを使い、最大8モデル空間。古い空間の削除はadminの明示操作。

原文変更時とチャンク削除時に派生ベクトルを除去。同一チャンク/モデルへ異なる結果を上書きせず明示再構築を要求し、同一結果の再送は書込みゼロ。途中で1件でも版/hash/次元/有限数の検証が失敗すれば空間作成も含め全体rollback。GET pendingは最大32件のcursor形式で全本文を一括転送しない。

embedding scopeはベクトル保存だけ、research_analysisはPDF/分析/ベクトル保存の明示的な新scope。既存pdf_analysis等の権限は増やさない。同一UID自動認証は独立qle_ tokenと専用Unix socket、loopback限定、再起動で失効。検索用のベクトル走査/索引と、アドオンからの再構築Jobs・graph/rerankへの接続は次の実装。

## ベクトルのsnapshot転送とPCキャッシュ（未配布）

正本にモデル空間ごとのランダムepoch・generation・件数を保持し、vector INSERT/DELETE/UPDATEと同じtransactionで更新する。無変更再投入やmanifest/page GETでは更新しない。モデル空間の削除/再作成はepochが変わる。配布済みDBからの移行は最大8空間の不足version行だけを作成し、毎起動全vectorを再構築しない。

認証付きmanifest/page APIは最大128件、float32-le/base64とchunk/doc ID・revisionだけを返す。pageごとにetagを照合。PCはprivate0600の一時SQLiteへ書き、全件数と最終etagを確認してからatomic replaceする。正本変更/取消/不正応答は部分cacheを公開しない。cacheに本文/タイトル/秘密は保持しない。

キャッシュは1ファイル2GiB/100万vector以内、完成済み最大2ファイル（構築中に追加の一時領域が必要）。通常の検索時はmanifest照合だけで、全vectorを再転送しない。PC上で128行ずつ読み、cosine exact top-kを固定サイズheapで集計する。最大30秒の時間制限でtruncatedを返す。これはANNではない。大量データの時間/物理I/O/RSS、Host CPU leaseとの製品Jobs接続とスマホUIは未完。

実Host CPU/RAM lease下で、実BGEの2vectorを一時RDHへ保存→cache同期→query embedding→cosine検索・関連文上位、再同期manifestのみを確認。cache20,480 bytes。これは合成2文の結合試験で、大量検索性能の保証ではない。

## 再開可能な索引構築worker（未配布）

`embedding_build.build`はHostのlocal-only/model_refを固定し、正本pendingを32件ずつ取得する。入力は各8192文字・合計UTF-8 64KiB以内に分割し、本文hashと原文revisionを検証してから推論/正本保存する。モデル・次元の変更は拒否。PCに本文やジョブ用ベクトルを永続化せず、正本にコミットされた行を再開地点とする。取消や保存応答消失後も再実行で保存済み行を除外する。カーソルより前の原文更新を最後のpending再照合で検出し、完了扱いせず再開を要求する。

CPU/RAM lease・更新・解放と進捗の頻度制御をComputeHostSessionへ共通化。PDFの既存権限は維持。workerの呼出元にHost Job/lease/heartbeat/terminal照合の責任があり、製品のEmbeddingJobs/開始ボタンはまだ未接続。実HostのJob/CPU leaseとBGE-M3で合成2文の構築・無変更再実行DB更新0・cache検索・Qwen3 rerankを確認。初回の進捗phase日本語によるHTTP422は、Host契約の英数字phaseへ直して再検証済み。

## 索引ジョブと画面（未配布）

EmbeddingJobsを追加し、独立した「検索索引を構築・更新」ボタンから全資料を対象に起動する。Host Job/CPU lease・5秒heartbeat・モデル固定・取消・保存済みからの再開・所有者分離を接続。request/lease IDは取得直後に0600の最大32件メタデータへ保存し、再起動後はHost解放/terminal照合が済むまで新規実行を止める。完了照合失敗は未同期として保持。履歴除外は索引を削除しない。モデル変更後は旧ジョブ再開を拒否し、新規構築を要求する。

進捗メタデータの書込みは最大5秒に1回と状態遷移時。本文/ベクトル/資格情報はジョブファイルに含めない。この書込みは再開と資源解放・Host終了照合に必要。新しいvector保存先は作らない。実ControlDeckブラウザ1280pxで合成2文のBGE索引構築・Host終了同期、320pxで再実行0チャンク、横溢れ/JS例外なしを確認。スクリーンショットでは構築ボタンを目視確認し、完了状態はDOM/API照合で確認した。チャートのvector/graph/rerank結合は引き続き未接続。
