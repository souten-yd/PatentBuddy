# PatentBuddy — ControlDeck準拠 UI/UX契約

状態: **規範設計（2026-11-17）**。ユーザー指定: PatentBuddyのUI/UXはControlDeckを踏襲。ここにある画面はK3以降の計画で、K1aではまだ未実装。

## 参照するControlDeck mainの実ファイル
- [UI/UXガイド](https://github.com/souten-yd/ControlDeck/blob/main/docs/ui-ux-guidelines.md)
- [Add-on UXガイド](https://github.com/souten-yd/ControlDeck/blob/main/docs/addon-ux-guidelines.md)
- [モバイルレイアウト](https://github.com/souten-yd/ControlDeck/blob/main/docs/mobile-layout.md)
- [共通UI部品](https://github.com/souten-yd/ControlDeck/blob/main/frontend/src/components/ui.tsx)
- [ページヘッダー](https://github.com/souten-yd/ControlDeck/blob/main/frontend/src/components/PageHeader.tsx)
- [配色・テーマ・iOS対応CSS](https://github.com/souten-yd/ControlDeck/blob/main/frontend/src/styles/index.css)
- [Host/opaque iframe/Bridge設計](https://github.com/souten-yd/ControlDeck/blob/main/docs/design-addon-platform-v2.md)

実装前に最新のControlDeck mainとHost Bridgeの実装を再読すること。優先順位はHostのruntime契約・UX規範 > 本書 > PatentBuddy固有ビュー。

## シェル・見た目と所有権
- ControlDeckがグローバルナビ、サイドバー、モバイル下部ナビ、ユーザー認証、テーマ、接続状態、戻る/進むを所有。PatentBuddyは埋め込み領域の機能内容だけを描き、親のナビやログインUIを二重化しない。
- HostのReact/TailwindコンポーネントをPatentBuddyのopaque iframeから直接importしない。Host Bridgeで渡されたtheme/route/contextに追従し、Host準拠の色・余白・角丸・文字・状態表現を静的CSSで再現。Cookie/localStorageをHost認証やテーマの根拠にしない。
- ControlDeck共通のzinc中立面、accent変数、system/light/dark/OLEDを使用。固定の青色テーマや独立デザインシステムを追加しない。カード階層最大2段、余白を広く、細い枠と控えめな影。見出しをHostと二重表示しない。
- 無断で新UIライブラリ/CDN/外部アイコンを入れない。既存のasset allowlist/CSPを守り、サーバー起動時npm buildを禁止。アイコンはHost icon setと整合。

## 操作・アクセシビリティ
- 主要機能へ2操作以内、3階層以上のメニュー禁止。Knowledgeの機能は「調査 / 文献 / 知識 / アイデア / レビュー」を文脈リンクまたはSegmentedTabs型の小さな切替で提供。
- 1画面/1カードの主操作は1つ。追加操作は「⋯」やドロワー/ボトムシートへ。削除・破壊的操作のみ確認ダイアログ。抽出・採用・統合・再評価はそれぞれ明示操作を要する。
- 詳細は段階的に開示。PCで右インスペクタ、モバイルでBottomSheet/単一ペイン。各タップ領域は44×44px以上、iOSフォーム16px以上。focus-visible、Escape/戻る、キーボード移動、スクリーンリーダー、reduced-motionに対応。
- 赤は破壊的操作と重大エラーに限定。知識の推論/未確認/staleは色だけでなくアイコンと文言で識別。数値はtabular-nums、画面のjumpを避ける。

## Knowledge Map / Card / Idea Canvas
- **Knowledge Map**: 最初は選択した中心ノードからの1〜2hop限定展開。検索理由/関係方向/ラベル/件数上限・truncatedを表示し、無限の全件描画はしない。node→知識カード→根拠PDF/段落→戻るを深いリンク/履歴付きで実現。
- **Knowledge Card**: 上部には課題→解決原理→手段→効果→条件/限界を簡潔に。根拠・引用・モデルの推論状態・原文版・人間のreviewは展開で表示。source_fact/model_inference/ideaの分類を視覚的にも区別。
- **Idea Canvas**: 2〜3知識カードを選択→組合せ候補を表示→明示採用/編集→先行技術再調査へ。AI結果は自動保存・自動承認しない。重い処理はHost Jobを使う。
- 幅1280px以上: マップ＋右インスペクタ。768〜1279px: 空間に応じてペインを縮退。320〜767px: **グラフを無理に縮小せず**「関連知識一覧→詳細カード→根拠」の1カラムで使えるようにし、必要に応じ「デスクトップでマップを開く」。親Hostの下部ナビを二重作成しない。

## 待機・通信エラーの扱い
- 全ての非同期操作でIdle/Loading/Success/Error/Offline/Reconnectingを区別。処理中にはJobの段階、根拠ある進捗、待機理由、取消・再試行手段を出し、根拠のない残り時間は表示しない。
- 空状態は説明と次の主操作を示す。切断時は最後の情報を残し「再接続中」、再試行を提供。真っ白なiframe/永久spinner禁止。Hostの8秒状態画面の契約を阻害しない。
- degraded/unavailableでもHostのnavigationは消さない。setup/権限不足はHost所有の状態表示に従う。成功/失敗/取消は必要最小限のtoast、進捗はJobs表示へ。原文・アイデア・秘密をログ/通知に記録しない。

## 受入検証
1. 実ControlDeck Host embedded view、theme/route/Bridge、Browser back/forward、deep-link、CSP/opaque iframeを確認。親ヘッダー二重・FOUC・Cookie依存を禁止。
2. 1280/768/390/320px + iPhone Safari/WebKitでsafe area、タップ、キーボード、スクロール、sheet、横溢れ・JavaScript例外なしを検証。
3. empty/loading/error/offline/reconnect/setup/degraded状態で「原因＋次の操作」があること、Jobの取消・再実行・終端が一致すること。
4. 知識の根拠は版・引用位置に一致し、unreviewed/stale/推論/ユーザーアイデアの表示が誤認を招かないこと。
5. published-only権限、privacy exit gate、認証、Host grant、無断外部送信0件を回帰。Vue default化、ui.html default変更、runtime level_0_manual_only/no execution変更、raw source serving/fallback/redirect追加を禁止。

## 実装の現在地
K1aでは純粋な知識候補の厳格な検証モジュールと単体テストだけを追加。地図、カード、発明キャンバスはK3以降で実装する。UI実装PRのDo NOT/Expected final stateへ本書を参照追加する。

## K2レビューのControlDeck操作規範（2026-11-17）

[K2詳細設計](knowledge-k2-human-review.md)を追加。知識カードのレビューは**折りたたみ詳細にあるselectで承認/却下/差戻しを選び、独立した明示ボタンで保存**。無選択ではボタン無効。文献旧版・権限不足では決して自動的に採用せず原因と次の操作を表示。レビューステータスは色だけではなく「未確認」「人間確認済み」「却下」「差戻し」「旧版・失効」を文字で示す。最大30件の履歴は展開された時にのみ取得。Host theme/accent, 44px hit area, iPhone 1カラム、キーボード、reduced motion、元文献へ戻る導線を維持し、Hostシェルを二重描画しない。

## K3 Knowledge Map実装の追加UX契約（2026-11-17）

[K3実装設計](knowledge-k3-map.md)に沿い、選択した文献からの出典・承認済み知識を1〜2hop/36 nodes/52 edgesに限定表示する。DesktopはSVG接続図＋右Inspector＋アクセシブルな一覧、320px〜767pxは大きなGraphを縮小せず一覧→詳細→引用へ遷移。ControlDeck theme・accent/Hostのグローバルshell/44pxとreduced-motionを維持。空・取得失敗・件数上限(truncated)・版失効は次の操作を表示。線の`proposal_evidence_source`は引用元とのリンクだけで技術的因果を主張しない。AI推論は人が承認してもsource_factではない。

**重要:** 以前の「K1aの純粋validatorだけ、地図は未実装」という時点説明は歴史的記録。K1dにはカード、K2には人手レビュー、K3には今回のMap表示コードが追加済み。ただしいずれもstacked Draftであり、mainへマージ・全体テスト・リリースはしていない。
