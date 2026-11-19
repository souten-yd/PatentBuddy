# PatentBuddy ↔ ResearchDataHub リポジトリ分離（2026-11-19）

- 旧Repo: https://github.com/souten-yd/PatentBuddy（PatentBuddy ControlDeck Add-onの正本、旧v0.5.13更新ブリッジを提供）
- 新Repo: https://github.com/souten-yd/ResearchDataHub（QNAP/QTSとLinuxのサーバー、QPKG/LinuxのRelease正本）
- 旧v0.5.12以前はPatentBuddy Releasesからしか更新できない。旧Repoでv0.5.13を公開し、更新後のREPOをsouten-yd/ResearchDataHubに変更する。新Repoはv0.5.14から公開。
- QPKG ID QnapLibrary、port17871、データフォルダ QnapLibrary-data、設定/認証/パスキーRP IDを変更せず、旧NASデータを削除しない。新旧サーバーで共有SQLiteの同時writerを禁止。
- フル分離は未完。互換のため旧qnaplibraryコードを旧Repoに残す。ブリッジ公開とQNAP/Linux確認後、PatentBuddy専用ランタイムへの抽出・共通コード依存/同梱整理・旧RepoのQPKG Release停止を別PRで行う。
- 未公開の発明/請求項のクラウドLLM送信は禁止。新Repoの権限・CSRF・認証は緩めない。
