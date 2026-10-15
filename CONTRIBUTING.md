# 開発に参加するには（CONTRIBUTING）

Issue と Pull Request を歓迎します。小さな修正でも、下記の検証を通してから送ってください。

## 準備

```bash
git clone https://github.com/jack4andmanastalk-byte/FortuneTelling.git
cd FortuneTelling
bash verify/env_setup.sh        # 依存ライブラリ（sxtwl, pyswisseph, iztro-py, divicast, kinqimen, google-genai ...）
```

Python 3.10 以上。Gemini API を呼ぶテストはありません（`MockBackend` を使います）。

## 変更後に必ず通す検証

```bash
# 1. テスト（件数は fortune_dataset/data/dataset_version.json の expected.tests と一致させる）
cd fortune_dataset && python3 -m pytest -q tests && cd ..

# 2. 構文チェック
python3 -m compileall -q fortune_dataset tools verify

# 3. Notebook とセル源の同期（kaggle/cell*.py を変えたら再生成する）
python3 fortune_dataset/kaggle/build_notebook.py --check     # 不一致なら --check なしで再生成

# 4. 配布 ZIP の生成と検査（画像・フォント・必須ファイル・秘密情報の混入）
python3 tools/build_dataset_zip.py --with-images --out build/zips/test.zip
python3 tools/build_dataset_zip.py --verify build/zips/test.zip

# 5. 画像やフォントを変えたとき
(cd fortune_dataset/assets/images && sha256sum -c ../../../verify/asset_checksums.sha256 | grep -vc ": OK")  # 0 なら OK
python3 verify/asset_matching_audit.py
python3 tools/build_chart_fonts.py --check && python3 tools/build_jp_fallback_font.py --check

# 6. 文書（Markdown）を変えたとき: 旧字体・簡体字・未定義語の混入チェック
python3 tools/check_scripts.py README.md docs/*.md
```

テストがネットワークに出ていないことは `python3 tools/check_tests_are_hermetic.py` で確認できます。

## 守ってほしいこと

- **秘密情報を書かない**: API キーはコード・CSV・ログ・テストに書かず、環境変数か Kaggle Secrets から読む。
- **版と件数の正本は `dataset_version.json`**: 占術数・テスト数・デッキ数・Notebook セル数を文書に直書きしない。
  テスト数が変わったら `expected.tests` を更新する。Notebook を再生成したら `notebook_sha256` も更新する。
- **モデル割当は `data/model_plan.json` だけで変える**: レーン・fallback・打ち切り秒数をコードに直書きしない。
  非推奨になったモデル ID は一次・fallback の全経路から外す。
- **入力は CSV だけ**: 人物を固定したセルやスクリプトを追加しない。
- **字数制限・検証規則・`INSTRUCT_MARGIN` を変えるときはテストも更新する**。
- **`data/*.json` の旧字体・簡体字は誤字ではない**: 古典用語として正しいので「日本語化」しない
  （日本語化してよいのはコメントと文書だけ）。
- **対象日の表示ゲート**（相談あり＋`target` 空欄なら対象日を出さない）は個別 Markdown（`pipeline.py`）・
  ローカル（`mts.py`）・Notebook（`cellN2`）の 3 箇所で同じ判定を使う。1 箇所だけ変えない。
- **画像を追加・差し替えるとき**は `docs/images.md` の手順どおりに、ライセンスを確認し、対応表とチェックサムを更新する。
  再配布が許されていない素材（個人利用のみの無料素材、商標ロゴ、他社デッキの図像）は入れない。
- **商標の名称**（ジーンキーズ・ヒューマンデザイン・動物占い・六星占術など）は占術の種類を示す目的でのみ使い、
  権利者の公式テキストやキーワード表を収録しない。

## Pull Request の書き方

- 何を・なぜ変えたかを本文に書く。挙動が変わるときは `CHANGELOG.md` の `Unreleased` に 1 行足す。
- 上記の検証結果（テスト件数・ZIP 検査の結果）を本文に貼る。
- コードは AGPL-3.0、画像・データは CC BY 4.0 で提供することに同意したものとみなします。
