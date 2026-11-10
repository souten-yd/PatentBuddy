# ResearchDataHub API性能の測定

PR-Dの計測コマンド（明示実行専用）。既存DBを開かず、指定ディレクトリ内に新しい一時DBを作り終了時に削除する。結果JSONだけを保持する。

```bash
python3 scripts/bench_datahub.py \
  --repo /path/to/baseline-checkout --documents 100000 \
  --idle-seconds 900 --workdir .data/bench \
  --output .data/bench/baseline-100000.json
# 同じスクリプトと設定で候補checkoutを指定し、直列に実行する。
```

1千・1万件は`--documents`を変更する。100万件は受け付けない。性能目標やNASでの性能保証とは別の合成データ測定である。

## 指標と限界

- 管理認証を通る実HTTP APIで登録、同一再投入、1%更新、先頭/深い一覧、タイトル絞込み、キーワード検索を測る。候補だけの新機能はカーソル/外部ID完全一致として分ける。
- バッチのP50/P95/P99、検索/一覧APIのP50/P95/P99、docs/s、原文MiB/sを記録。標本数を必ず併記し、30サンプルのP99を大規模運用の確約に使わない。
- CPUとRSSはクライアントとサーバースレッドを含む同一プロセス。SQL時間はexecute/fetch呼出しの計時で、SQLite内部プロファイラではない。executescriptと行イテレータは含まない。
- `/proc/self/io`は当該プロセスへのI/O計上、sysfsデバイス統計は同じパーティションの他プロセスのI/Oも含む。カウンタ差分とDB/WAL/SHMサイズを別々に記録する。OSキャッシュを消さず、同期設定も変えない。デバイス全体のゼロ書込みをプロセスのゼロから推定しない。
- 15分idleは収集/更新schedulerを起動しないAPIサーバーの測定。物理デバイスの他プロセス活動と区別する。
- `dbstat`で各表/索引の容量を記録する。ベクトルはこの試験では0件、ANN性能は未測定。
- バックアップAPI実装でsnapshotを作り、Storeを閉じて再open、別DBへコピーして復元。quick_check、全件のID/内容hashの逐次照合、検索結果一致を検証する。測定名にあるStore再openはOSプロセス起動時間ではない。サービス再起動は別受入が必要。

## 初期結果（2026-11-10、最終候補の採用判定前）

Ryzen 7 9700X / 31GiB級RAM / NVMe / SQLite3.45.1、変更前`b7816cf`、初期候補`723e41f`。一般コレクションに合成日本語本文、200件/batch。単位は秒、API一覧/検索は30回の合計。

| 件数・版 | 登録 | 同一再投入 | 再投入DB更新 | 再投入process write bytes | 深い一覧 | キーワード検索 |
|---|---:|---:|---:|---:|---:|---:|
| 1千・変更前 | 0.067 | 0.012 | 5 | 20,480 | 0.019 | 0.049 |
| 1千・初期候補 | 0.067 | 0.011 | 0 | 0 | 0.019 | 0.048 |
| 1万・変更前 | 0.768 | 0.132 | 50 | 204,800 | 0.033 | 0.284 |
| 1万・初期候補 | 0.771 | 0.108 | 0 | 0 | 0.032 | 0.274 |

この規模の速度差だけで高速化を断定しない。書込み回避は観測できた。候補の1万件登録process write bytesは128,733,184、変更前127,406,080で増加しており、追加索引の費用も評価対象とする。

原データは `.data/bench/{baseline,candidate}-{1000,10000}.json`。後から出典/明示セクション訂正の正確性修正を追加したため最終候補の再測定が必要。10万件・15分idleの比較は進行中。QNAP HDD・サービス再起動・実文献規模への一般化は未検証。

## OSプロセス再起動と復元の受入

`scripts/bench_datahub_restart.py`は別のtemp合成データを使い、`python3 -m researchdatahub`を実プロセスとして起動する。1千/1万/10万件それぞれで変更前/候補を比較できる。

```bash
python3 scripts/bench_datahub_restart.py --repo /path/to/checkout \
  --documents 100000 --workdir .data/bench \
  --output .data/bench/restart-candidate-100000.json
```

管理APIでsnapshot→プロセス停止→同じDB再起動→停止→別領域へsnapshot/config/secrets復元→新プロセス起動を直列に実施。古いCookie/CSRFでの読書き、件数・検索結果、snapshotのSHA-256、quick_checkを検証する。healthまでの時間は50ms間隔のポーリングで測るため、それ以下の差を性能差と解釈しない。書込み元は常に1プロセスだけ。一般Linuxでの受入であり、QTS上のサービス受入ではない。
