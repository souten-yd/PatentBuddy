# PatentBuddy 公式データソース運用台帳 — 2026-11-18

**利用方針**: アカウント登録は許容する。基本無料、短期の有料契約は別途ユーザー承認が必要。公式API/正式配布データ/ライセンス適合を優先する。**本番で実接続成功・取得制限・規約・継続性を検証できたソースだけ「利用可」と表示する**。コード存在やダミーテストPASSを利用可判定にしない。登録情報をGitHubに置かない。ユーザーが登録を完了するまで登録済みと表示しない。

## 特許情報：導入状況

| Source | Provider service status (not our app) | main | Draft #40 | Account | Required real test / blocker | Target use |
|---|---|---|---|---|---|---|
| EPO OPS 3.2 | free 4GB/rolling week, registered OAuth client | generic epo_search connector | fixed IPC+publication-office+publication-year+manual 25/page, receipts; modified X-OPS-Range/JSON | EPO developer registration + key/secret | real OAuth, one H02M JP 2020-2025 query, actual XML/JSON shape, bytes/quota, one-page retry/HTTP rate limit | worldwide bibliographic backbone, image/fulltext by separate approved API |
| JPO 特許情報取得API | official free API with personal/business application | jpo_progress (application number) experimental | unchanged | JPO free registration, issued ID/password | official token endpoint, app_progress response, field mapping, status transitions, quota; one real known application | JP legal/prosecution complement, not bulk worldwide search |
| USPTO Open Data Portal | registration at USPTO.gov required from 2026-06-18 | uspto_search experimental | unchanged | USPTO.gov + valid API credentials if provided | official current schema/key/header and login; one JP-independent US application result; limit+rate control | US patent applications/legal/prosecution complement |
| WIPO IPC 2026.01 | official free classification data download | no | official_ipc.py valid symbols, official_ipc_titles.py EN titles, manual section import, version/hash | no account for public export | **real official H-section HTTP retrieval, 66 title entries + 10,607 symbol records, SQLite import + H02M verified browse PASS in temporary CI SQLite**. QNAP/ControlDeck deployment untested | accurate classification suggestions, versioned lookups |
| EPO PATSTAT / TIP | free online analytics, EPO says bulk data distributed free via TIP | no | planned only | EPO TIP account as required | verify registration/export rights/schema; select limited IPC/date/country extract, do not load 125M applications on NAS | company/year/citation/family network analytics |
| PatentsView PatentSearch API | status operational but new API key grants temporarily suspended per API documentation | no | none | new key issuance not currently assured | defer until new key issuance resumes; if existing key, live verify without violating one-key policy | US analytic/citation enrichment |
| Google BigQuery patents public data | public dataset/query quota; billing account conditions to verify | no | planned only | Google Cloud project | inspect exact dataset fields and free tier; require cost guard and user spend authorization | large-scale bibliography statistics, no automatic unlimited export |
| OpenAlex | free academic metadata API; anonymous use is opportunistic; free account key recommended | no | OpenAlex official first-page bounded metadata connector, optional `openalex_api_key` setting, one-click connection probe, 1–25 works/request | free key to input during installation | **real public `inverter` work 1 record PASS once; anonymous HTTP 429 subsequently reproduced**. Validate key-authenticated use and license on installation; never send private patent text | scientific papers, authors/affiliations/technical knowledge links |
| JPO patent bulk official download | official data distribution, conditions/media may vary | no | planned manual data import only | per JPO request conditions | apply for covered product, inspect formats/backfile and cost | long-range JP corpora selected by technical domain |

References (official): https://www.epo.org/en/searching-for-patents/data/web-services/ops ; https://www.jpo.go.jp/system/laws/sesaku/data/api-provision.html ; https://data.uspto.gov/apis/getting-started ; https://www.wipo.int/classifications/ipc/en/ ; https://www.epo.org/en/about-us/observatory-patents-and-technology/observatory-tools/patstat ; https://help.openalex.org/access/pricing/ ; https://github.com/PatentsView/PatentSearch-API/blob/main/docs/docs/Search%20API/SearchAPIReference.md

## Auxiliary sources existing on main

- **GDELT**: connector for public news and technology/competitor monitoring, no account for read API; not patent full text.
- **RSS/Atom**: official feeds or allowed feeds only; no authentication except feed requirements; not full patent corpus.
- **e-Stat**: statistical data with free account/app ID; technical-market/industrial trends; not patents.
- **EDINET**: corporate filings with free API registration/key; company strategies/R&D contextual data; not patents.
- **SEC EDGAR**: US corporate filings with appropriate contact User-Agent; no API account for public submissions; not patents.

Existing connector does **not** demonstrate successful runtime API access. No project credentials have been inspected or exposed; whether user accounts/keys are already registered is unknown.

## Source activation policy and test gates

1. Source states: **not_integrated**, **implemented_unverified**, **account_pending**, **auth_verified**, **sample_verified**, **operational**, **temporarily_disabled**. Main vs Draft tracked separately. Never equate provider operational status with PatentBuddy operational status.
2. Each verified connector: register one legitimate account (no rotating proxies / duplicate identities); credentials through settings secret store, not repo. Authenticate, sample 1–10 representative documents, confirm response schema/identifiers/rights/metadata/last modified, then add idempotent/retry/normalization/quota handling.
3. Limit all requests by IPC/CPC, publication country and publication/priority period; show approximate result count and anticipated bytes, require human confirmation. Add batch import only with official licensing; do not crawl UI sites (J-PlatPat/PATENTSCOPE/Google Patents).
4. EPO search + WIPO classification first, JPO/USPTO second, PATSTAT/TIP and OpenAlex third. PatentsView deferred while keys cannot be issued. Use manual user-initiated data acquisition.
5. Preview/test/heartbeat should never transmit unpublished invention description or private claims. AI classification local-only. Conserve disk: first import biblio/short metadata, then selectively cache PDF/figure crops; enforce actual limit in all write paths before claiming hard quota.
6. K7a #40 depends on K6c Draft #39; do not merge/release until all Python unittest, existing verify-k6, official live samples and ControlDeck/QNAP/iOS tests pass. Preserve ui.html default; Vue read-only/not default; backend authoritative; level_0_manual_only; no execution capability; no startup npm build; no raw source serving/redirect/fallback.

## Next Codex acceptance checklist

- **WIPO H-section real-data API→parser→temporary SQLite→H02M labelled browse PASS.** Remaining: A–G coverage, schema version/change guards, WIPO attribution, UI/iOS/QNAP run.
- EPO OPS OAuth with one user registered free key, official X-OPS-Range response, token/error conditions, first and 26th result page, dedup and 4GB weekly quota.
- JPO auth and app_progress from official Swagger with one known public Japanese application; note its scope is not full patent search. USPTO ODP search with one public US record and validated 2026 auth.
- Compare actual source metrics, preserved origin/license, stop conditions, safe credential removal; expose provider-status not as 'working' until verified.
- Show in admin UI: source integration status, registration guidance, last successful fetch and failed reason, authorized quota/budget, no startup side effects.


## K7a 2026-11-18 — 実取得・認証ゲートの結果

- [実取得とCI検証ログ](source-smoke-evidence-2026-11-18.md)に実際のAPI経路・WIPOバイト数・OpenAlex429・Pythonテスト全件ログを記録。WIPOはタイトル66件、IPC有効記号10,607件、SQLiteへの原典保存とH02M名称付き照会が実成功。OpenAlexは無キー公開検索1件実成功後、別実行で429を実確認。**アプリからのOpenAlex継続運用は無料キーの入力後に再検証する。**
- ResearchDataHub管理者画面には固定的なソースリストと接続状況（キー設定の有無）を表示し、手動確認後の単発テスト機能を実装。キー未設定のEPO/JPO/USPTOについては「登録して導入時入力」と表示し、実接続成功扱いにしない。OpenAlexの匿名テストは無料キーなしでも試せるが正常を保証しない。
- 一時的なDraftブランチ用GitHub CIで対象29テストは2skip/0fail、全repo325テストは1fail（唯一、`release.yml`以外の一時CI追加に対するリポジトリの明示ルール）。検証後一時CIは削除。**削除後の全テストを再実行してはいないため全件PASSとは宣言しない。**
- EPO/JPO/USPTO OAuth/キー本番認証は導入時にユーザーが登録・設定するまで未実施。外部機密送信はしない。
