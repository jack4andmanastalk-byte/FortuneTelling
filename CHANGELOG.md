# Changelog

このファイルは公開版の変更履歴です。形式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に、
版番号は [Semantic Versioning](https://semver.org/lang/ja/) に従います。

## [1.0.1] - 2026-10-15

文書と Git の設定だけの更新です。コード・データ・画像・Notebook に変更はなく、版印（`fortune_dataset/data/dataset_version.json` の
`build_id`）・配布 ZIP（`fortune_dataset_kaggle_v1.0.0.zip`・SHA-256 `c483dce9…`）・Kaggle Dataset（Version 1）は v1.0.0 のままです。

### 追加

- `.gitattributes`: 改行コードを LF に固定（`* text=auto eol=lf`、画像・動画・フォント・ZIP は `binary`）。Windows で clone しても
  `fortune_notebook.ipynb` などのバイト列が変わらず、`tests/test_notebook_sync.py` の SHA-256 検査がローカルでも通ります
- README／README.en／`docs/kaggle_setup.md`: 公開済みの Kaggle Dataset と Notebook（実行例）へのリンクと、Copy & Edit で始める手順

## [1.0.0] - 2026-10-14

最初の公開版。内部開発版（2026 年 8 月〜10 月）の成果を整理し、公開できる形にまとめました。

### 含まれるもの

- 53 占術の決定論的な計算エンジン `fortunelib/`（暦・天体・数秘・姓名・卜占・象徴系）
- Gemini API による鑑定文生成パイプライン: Stage A（個別占術）→ B（クラスタ中間レポート）→ C（軸サマリー・最終統合・御縁のある神さま Top10）→ D（読み物版 3 トーン）
- モデル割当・fallback・応答打ち切り・503 待ちを 1 つの JSON（`data/model_plan.json`）で管理するマルチモデル実行（MTS）
- 画像つき 1 枚 HTML レポート（48 デッキの画像を Base64 で埋め込み、型 C は実行時に Pillow で描画、口調切替、冒頭動画カード）
- Kaggle Notebook（8 セル: ブートストラップ／セルフテスト／CSV 入力＋Stage A／統合＋HTML）
- 入力 CSV 1 枚による複数人処理と、相性占い用の相手情報
- pytest 一式（Kaggle のセルフテストと共通）・配布 ZIP の生成と検査・実行結果の検証ツール・画像突合監査
- セルフテストの Gemini 疎通は軽量モデル 3 本を順に試し、混雑（503/408）と致命エラー（キー不正・モデル名違い・日次枠切れ）を区別して案内（`fortunelib.backend.ping_gemini`）

### 公開にあたっての整理

- ライセンスを明確化: コード AGPL-3.0、画像・自作データ・プロンプト CC BY 4.0、第三者データは `THIRD_PARTY_NOTICES.md`
- 姓名判断の画数辞書を KANJIDIC2（CC BY-SA 4.0）＋ Unihan（Unicode License）から再生成し、生成スクリプトを同梱
- 画像ディレクトリを自動探索に変更（環境変数 `FORTUNE_ASSETS_DIR` → Dataset ルート → `/kaggle/input/**/assets/images`）。特定アカウントのパスへの依存を除去
- 再配布できない素材を置き換え: レノルマン 36 枚を本プロジェクトの水彩調オリジナルに差し替え、ジーンキーズ 64 枚の題字と 3 層の語を独自表記に塗り替え
- 画像の出どころを `docs/data_sources.md` に明記（タロット・マルセイユはパブリックドメインのスキャン、カルトマンシーは CC0、他は本プロジェクト作成）
- 開発中のみ使った機能（音声つきハイライト動画、メール通知、実験用スクリプト）と開発履歴の文書を公開版から除外
