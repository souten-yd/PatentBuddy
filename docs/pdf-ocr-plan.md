# PDF取り込み・OCR（実装中、未提供）

ユーザー要求: ダウンロード済みの特許PDFに加え、文字がないPDFも必要時に読み取る。

- PC側PatentBuddyで実行。ControlDeck Filesの読取grantから選択した原本だけを取得し、Host JobとCPU資源leaseを使用する。任意path/command APIは作らない。
- Popplerのページ単位テキスト抽出を先に使う。空白/少量のページだけローカルTesseract（jpn+eng）へ回し、ページ指定の強制OCRも許可する。図面ページが文章に化けたと推定せず、OCR結果を未確認として表示する。
- 原本SHA-256、ページ番号、抽出方法、tool版、OCR単語信頼度/低信頼箇所を保存する。原本とページ画像/図の表示から確認できること。LLMに画像の読み取りを黙って代替させない。
- PDFサイズ/ページ数/描画画素数/文字数/同時実行/時間/一時ファイル容量に上限を設ける。パスワード付き・破損・tool未導入は明示エラー。途中失敗を成功扱いせず、キャンセルで子processを止める。
- 原本と抽出結果の正本はResearchDataHubだけ。Addonの一時コピーはジョブ終了で破棄。書込専用の狭い取込認証を設計し、既存ro/analysis権限から一般rwへ広げない。
- 保存は原本hashにより冪等化し、原本/ページ根拠のsnapshot復元まで確認する。追加ディスク容量/I/Oを測定して記録する。
- 原本から抽出した内容を、Hostのlocal_only対応LLMで要約・請求項確認へつなぐ。既存の公開専用権限/機密境界を維持する。

現在: Linuxにpdfinfo/pdftotext/pdftoppm/tesseract、jpn/eng/osdあり。個別PDF処理は実施済みだが、アプリの取込UI/Host grant/Job/保存は未実装。この文書を実装完了と扱わない。
