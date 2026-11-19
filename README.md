# PatentBuddy

PatentBuddy は [ControlDeck](https://github.com/souten-yd/ControlDeck) 向けの**特許調査・発明/請求項分析アドオン**です。文献正本と汎用APIを管理する独立サーバーは [ResearchDataHub](https://github.com/souten-yd/ResearchDataHub) に移管しました。

## サービス分担

- **PatentBuddy（このRepo）**: ControlDeck Add-on v2、Host AI/Jobs経由のローカルLLM解析、PDF/請求項確認、特許用UI、今後のGraphRAG。
- **ResearchDataHub（新Repo）**: QNAP NAS（QTS）/Linux共通の文献DB・規格/論文/特許/ニュース保存・検索・REST/MCP・認証・バックアップ。最新版のQPKG/Linuxインストール説明とReleaseは [ResearchDataHub README](https://github.com/souten-yd/ResearchDataHub#readme) を参照。

PatentBuddyはResearchDataHubの認証付きAPIを利用し、文献正本SQLiteを別途作成しません。未公開の発明/請求項を外部LLMに送信せず、ControlDeck管理の検証済みローカルLLMだけを利用します。

## PatentBuddyを開発・起動する

開発PCはLinux、Python 3.9以降、ControlDeck Add-on Host v2契約が必要です。

```sh
./pb.sh doctor
./pb.sh serve
bash scripts/verify.sh
```

起動時は127.0.0.1:9150でアドオンのhealth/UIを提供し、ResearchDataHubのAPI接続が必要です。アドオンの管理情報は [addon.json](addon.json)、Host連携仕様は [docs/controldeck-addon-plan.md](docs/controldeck-addon-plan.md)、機密境界は [docs/privacy-boundary.md](docs/privacy-boundary.md) を参照。

## 旧QNAP/Linuxアプリの更新ブリッジ

このRepoに残る qnaplibrary/・qpkg/・researchdatahub/ は**移管期の互換実装**です。旧ResearchDataHub（旧QnapLibrary）の起動・保存データ・QPKG ID・Port17871・認証・パスキーを維持するため、すぐには削除しません。

v0.5.12以前のQPKG/Linux版はこのRepoのReleaseしか確認できません。**このRepoから旧形式のv0.5.13更新ブリッジを公開**し、インストール後は新RepoのReleaseを確認できるようにします。その後、ResearchDataHubのv0.5.14以降へ更新してください。ブリッジの公開・動作確認前には移行済みとは扱いません。

QNAP上の既存アプリをアンインストールせず、元の QnapLibrary-data を削除・初期化しないでください。ブリッジが利用できない場合は[新RepoのReleases](https://github.com/souten-yd/ResearchDataHub/releases) からQPKGを手動上書きします。移管契約は[docs/repository-migration.md](docs/repository-migration.md)を参照。

## 開発ルール

[AGENTS.md](AGENTS.md)、[DEVELOPMENT_WORKFLOW.md](DEVELOPMENT_WORKFLOW.md)、[docs/HANDOFF.md](docs/HANDOFF.md)、[docs/knowledge-graph-design.md](docs/knowledge-graph-design.md)を参照。新しいQNAP/Linuxサーバーの改善はPatentBuddyではなくResearchDataHubへPRを出してください。
