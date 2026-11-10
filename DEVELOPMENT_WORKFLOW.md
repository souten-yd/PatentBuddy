# 開発ルール — QnapLibrary

このファイルは人間・AI を問わず全開発者が従う規則です。別の AI へ途中で引き継ぐ前提で書いています。
まず `AGENTS.md` → 本書 → `docs/HANDOFF.md`（現在地）の順に読んでください。

## 1. GitHub 運用（必須）

- **main へ直接 push しない**（空リポジトリ初期化コミットのみ例外）。作業は必ず `feat/…` `fix/…` `docs/…` ブランチで行う。
- **PR を先に作る**: ブランチを切ったら最初の小さなコミットで PR（Draft 可）を作成し、以後は**こまめに push しながら**開発する。
  トークン切れや中断が起きても、PR と push 済みコミットから別 AI が続きを再開できる状態を常に保つ。
- 1 PR = 1 つのまとまった目的。小さな修正は次の予定 PR に含めてよい（1 行 PR を量産しない）。
- マージ前に: 実際の diff を読む／`scripts/verify.sh` 合格／バージョン整合（`qnaplibrary/__init__.py`・`qpkg/qpkg.cfg`・CHANGELOG）を確認。
- マージ後に: main の実ファイルを読み直し、**アプリ変更ならリリースを公開**し、更新と動作確認ができる状態にする（§3）。
  ドキュメントのみの PR はリリース不要（PR 本文に明記）。
- 所有者はこのプロジェクトで PR のマージとリリース公開を確認なしで行うことを許可している（2026-11）。

## 2. GitHub Actions（費用最小化ルール）

- **PR / push での自動 CI は置かない**。テスト・ビルドはローカル（`scripts/verify.sh`、`scripts/build-linux.sh`）で行い、結果を PR に記録する。
- Actions で動くのは `release.yml` **1 本だけ**。起動条件は `v*` タグの push と手動実行のみ。中身は QPKG ビルド（QDK が必要なため）と
  リリース資産の添付だけで、10 分以内で終わる構成を保つ。
- 新しいワークフローの追加、トリガーの拡大、マトリクス化、キャッシュ肥大化は**所有者の明示許可なしに行わない**。
- 失敗した release ジョブの再実行は原因を直してから 1 回だけ。

## 3. リリース手順

1. PR 内でバージョンを上げる（3 箇所: `qnaplibrary/__init__.py` の `VERSION`、`qpkg/qpkg.cfg` の `QPKG_VER`、`CHANGELOG.md` 先頭）。
2. ローカルで `bash scripts/verify.sh` と `bash scripts/build-linux.sh dist` を実行。
3. PR をマージ → main を pull → `git tag vX.Y.Z && git push origin vX.Y.Z`。
4. `release.yml` が QPKG を作り、Linux tar.gz と合わせて Release に添付する（各資産の SHA-256 はGitHubの `digest` と `.sha256` ファイル）。
5. Release 公開後、旧バージョンを起動し管理 Web「更新」から更新して、`/api/health` の version が上がることを確認する。結果を HANDOFF に記録。

資産名は固定: `QnapLibrary_<X.Y.Z>_x86_64.qpkg`、`qnaplibrary-<X.Y.Z>-linux.tar.gz`（＋各 `.sha256`）。自動更新はこの名前と SHA-256 で検証する。

## 4. 実装ルール

- **Python 3.9+ 標準ライブラリのみ**（QNAP の Python3 QPKG / 一般 Linux でそのまま動かすため）。numpy などは「あれば使う」任意加速に限る。
- **root で動かさない**前提で書く。任意コマンド実行 API を作らない。ファイルパスは許可ルート配下か必ず検証。
- 秘密値（パスコード、APIキー、トークン）はログ・デバッグ出力・GET API に出さない（指紋のみ）。秘密は `secrets.json`（0600）に分離。
- **ディスク I/O 最小**: SQLite は WAL・`synchronous=NORMAL`・大きめ page cache・`temp_store=MEMORY`。取り込みはバッチトランザクション。
  アクセスログは RAM リングバッファのみ。ログ/デバッグのファイル出力は上限付きで、明示要求時か ERROR 時だけ。journal の無効化や fsync 無効化は禁止。
- 外部サイトへのアクセスは公式 API・RSS・利用規約上許される方法に限る。スクレイピングで規約違反になるサイト（J-PlatPat、JISC 閲覧画面等）は自動取得しない。
- UI は外部 CDN を読まない（オフライン LAN でも動く）。ビルド工程不要の素の JS/CSS。初回表示 100KB 以下（gzip 後）を目安。

## 5. ドキュメントルール（引き継ぎ可能性）

- `docs/HANDOFF.md`: **作業の区切りごとに更新**（現在のバージョン、完了/未完、次の一手、既知の問題、検証結果）。中断に備え、コミット前に更新する。
- `CHANGELOG.md`: バージョンごとに先頭へ 1 項目（日本語、利用者向け）。過去項目は書き換えない。
- `README.md`: 現在の製品の説明だけ（履歴・計画は書かない）。
- 設計は `docs/`、計画は `docs/roadmap.md`、提案は `docs/proposals.md`、実現性判断は `docs/feasibility.md`。
- 実現が難しい機能は早期に `docs/feasibility.md` へ判定（◎/○/△/×）と代替案を書き、所有者に提示する。
- テスト `tests/test_docs_rules.py` が最低限の文書規則（バージョン整合、HANDOFF 存在など）を検査する。

## 6. 完了の定義

コードを書いただけでは完了ではない。ローカルで実起動し API を叩いて確認、`scripts/verify.sh` 合格、HANDOFF 更新、
（アプリ変更なら）リリース公開と更新確認まで行って完了。実施できなかった工程は「未実施」と明記し、完了と言わない。
