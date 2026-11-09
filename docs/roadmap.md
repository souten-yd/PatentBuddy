# ロードマップ

## v0.1（土台・特許支援優先） — 本PR
- API サーバー（REST + MCP）、LAN ペアリング、管理Web（パスワード＋パスキー）
- コレクション／文書／FTS5 日本語検索／RAM ベクトル／RRF ハイブリッド
- 特許案件ワークフロー（11段階、期限計算、請求項の版管理、構成要件分解、クレームチャート、AI 支援 12 タスク）
- AI チャット（QnapAssistant / OpenRouter 詳細設定 / OpenAI 互換、RAG、SSE）
- コネクタ: GDELT、RSS、EPO OPS、JPO API（実験的）、USPTO ODP（実験的）
- デバッグバンドル、GitHub Releases 自動更新、Linux tar.gz / QPKG

## v0.2（特許の網羅性）
- 特許ウォッチ（定期収集・差分・類似度で X/Y 候補提示）
- IPC/FI/Fターム辞書、審査基準コレクションの取り込み支援
- 期限通知（Webhook / メール）

## v0.3（スケールと品質）
- Qdrant アダプタ、外部リランカー、集計ダッシュボード
- PDF 取り込みクライアント（別PC）

## v0.4（市場・規格）
- 規格メタデータの整備支援（JIS/ISO/IEC 番号・ICS・対応関係）
- e-Stat / EDINET / SEC コネクタ、調査ジョブ
