# HANDOFF — ResearchDataHub / PatentBuddy

**更新日**: 2026-11-10。中断後はまず `AGENTS.md` → `DEVELOPMENT_WORKFLOW.md` → 本ファイル → `docs/researchdatahub-plan.md` → `docs/CODEX_NEXT.md` を読む。

## 現在地（確認済み事実）

- GitHub: `souten-yd/QnapPatentBuddy`、default branch `main`。
- **公開済みの最新バージョンはv0.5.1**: https://github.com/souten-yd/QnapPatentBuddy/releases/tag/v0.5.1（2026-11-10）。バイナリは旧互換名 `QnapLibrary_0.5.1_x86_64.qpkg`, `qnaplibrary-0.5.1-linux.tar.gz`。QNAP実機での更新・パスキー・保存先継続の動作は未確認。
- PR #12（未公開発明をクラウドへ送らないガード）は**mainにマージ済み**。出入口のネットワーク境界は `docs/privacy-boundary.md` を参照。
- **このチェックポイント PR #16 はdocs-only**。新ブランドのLinux launcherやサービス名、Host本体との接続、NASへの移行は**まだ実装していない**。ソフトウェアのリリース不要。
- 既存v0.5.0 release workflowはPython 52件テスト成功＋Linux/QPKGビルド成功（当時）。今回のPR #16に関してローカル完全 `scripts/verify.sh`、Linux/QPKGビルド、ControlDeck実機、PC→QNAP移行テストを実施したとは主張しない。

## 2026-11-10に決定したアーキテクチャ（最優先）

| 区分 | 名称と役割 | 実行場所 |
|---|---|---|
| 汎用データ基盤 | **ResearchDataHub**: 特許・規格・学術/技術文献などを収集・保存・検索・版管理し、認証付きAPIを提供 | 今はControlDeck Linux PCのSSD、完成後はQNAPのローカルデータ領域 |
| 高度な特許利用 | **PatentBuddy**: ControlDeck Add-on v2、ローカルLLM、GraphRAG、請求項、調査・AI Jobs、特許向けUI | 今後もControlDeckのPC |
| 権限付き外部API | ResearchDataHubの**公開承認済みデータ専用API**。外部LLM本体へはユーザーの秘密プロンプトを送らない | ResearchDataHub側 |
| データの正本 | 唯一のSQLite/原本/案件/承認情報。検索キャッシュは正本でない | 開発中PC、完成後QNAP |

**既存実装の内部識別子を変更しない**: Python package `qnaplibrary`、QPKG `QnapLibrary`、旧データ/設定/パスキー、port 17871、Release資産名。ResearchDataHubはユーザー向け名称+新Linux起動別名として実装する予定（未実装）。

**重要な機密境界**: 未公開の発明・請求項を**ローカルLLM以外のLLMへ渡さない**。認証/TLS保護されたResearchDataHub⇔PatentBuddy/ControlDeckのデータ通信は許可。OpenRouter等の外部LLMは公開・承認・送信プレビュー済みの資料だけ、既存`privacy`のfail-closed制限を弱めずに別実装する。QNAP/PCを同時正本化しない。SMB/NFSで稼働中SQLite/WALを直接開かない。

## 未マージの開発PR（mainには入っていない）

| PR | 内容 | 状態/注意 |
|---|---|---|
| #10 | LLMによる根拠付きクレームチャート | Draft。PR #12の新しい機密ポリシーへ整合させてから再検証 |
| #11 | セッション保持/Face IDパスキー更新後問題/一時501 | Draft。main v0.5.1とのバージョン競合・実機再現を確認 |
| #13 | 大量文献の一括冪等/低書込/カーソルAPI | Draft。実データ100万件の速度は未実測 |
| #14 | ControlDeck Add-on v2 A0/Feature bundle | Draft。**旧設計からの経緯あり**。新しいResearchDataHub API正本方針を優先し、PC上の別SQLite正本を作らない |
| #15 | 外部AI向け公開資料の承認・限定検索API | Draft。公開専用トークンの権限分離/出典・タイトル・抜粋の確認など要再テスト。外部LLMへ自動送信する機能ではない |
| #16 | ResearchDataHubとPatentBuddyの分離・PC→QNAP移行・Codex引継ぎ | 本docs-onlyチェックポイント。Linux CLI等は**次のPR** |

## Codexの次の作業（優先順）
1. **mainを取得、上記PRの実diffを読む**。`docs/CODEX_NEXT.md`記載のPR-Aから実装する。基本は1PR=1目的、早期Draft作成。
2. Linux PCで `python3 -m researchdatahub` と `./rdh.sh doctor|serve|test` を既存サーバーの**薄い別名入口**として実装する。ResearchDataHub表示/API health/管理Webのブランディング、Linux tar.gz同梱とテストを同じPRで扱う。旧package/DB/QPKG/port/cookie/パスキーRP IDの互換を守る。
3. PR #11を更新後認証/保持/501修正として検証し、PR #15の公開専用API、PR #13の高速化、PR #14のControlDeck接続を**新しい設計に合わせて**順次取り込む。PR #10のAIはローカルLLMだけで処理。
4. 特許/規格の文献実体とAPIの境界を整理し、GraphRAGは確定した引用/ファミリー等の関係から導入。出典/改版と推測関係の区別を必須にする。
5. **最後に**PC側のSQLite正本/原本/設定/秘密/パスキーをQNAPへdry-run→backup→hash/quick_check/件数照合→ロールバック可能な停止・切替を実施する。QNAP既存データを上書き・削除しない。

## マージ前に必ず確認する内容

- 前回指示のscope/Allowed/Do NOT/expected final stateと、**mainの実ファイル**、diff、docs、manifest、tests、runtimeの一致
- `bash scripts/verify.sh`、`bash scripts/build-linux.sh dist`、Linux非root実起動/API・セッション/パスキー回帰、必要なQPKGビルド/検査（実施できなければ未実施と記録）
- 機密用トークン/公開資料専用トークンのスコープ漏れ、外部AIへ流れるデータのリクエスト本文、プロキシ経路、秘密ログ、無断Web公開の有無
- 認証・Cookie・CSRF・RP ID・旧データの後方互換、不要な自動実行/npm build/外部依存/過剰機能追加の有無
- 低ディスクI/O・書込負荷、バックアップ復元、1000/10000/100000レコードのベンチ、iPhone UIと既存管理Webの動作
- docs-only PRなら **バージョンを上げずRelease不要**。コード変更をマージする場合はバージョン・CHANGELOG・QPKG設定整合とRelease、更新確認を行う。

## 既存の未解決事項
- iPhoneのパスキーが更新後に登録なし表示されること、ログイン保持、更新確認の一時501：PR #11の**未マージの修正候補**。解決したと主張しない。
- QNAP TS-253Beでの本番動作/自動更新/HTTPS・WebAuthn、各公的APIの実キー疎通、Host Feature署名・publisher登録は未検証。
- 古い自己更新クライアントはリポジトリ改名前のURLを使う場合がある。Release assetと手動導入手順を確認。
- 規格(JIS/ISO/IEC)の全文はライセンスに制約があり得る。APIから公開する前に権利確認が必要。

これまでの詳細な旧版の検証・変更履歴は各GitHub Release、PR #6/#8/#9/#12と`CHANGELOG.md`を参照。**今後のCodexの実装完了条件を満たしたものだけこのファイルの完了欄へ移す。**
