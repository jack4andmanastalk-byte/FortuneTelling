# fortune_dataset パッケージ

このディレクトリが Kaggle Dataset として配布される本体です（Notebook は `kaggle/`、計算と生成は `fortunelib/`、
データは `data/`、画像・フォント・動画は `assets/`）。プロジェクト全体の説明はリポジトリ直下の
[README.md](../README.md)、設計は [docs/architecture.md](../docs/architecture.md) を参照してください。

## 版印と数値の正本

- build ID・占術件数・神格件数・テスト件数・Notebook セル数・デッキ数は **`data/dataset_version.json`** の
  `build_id` / `expected.*` が正本です。文書に数値を直書きせず、必要ならこのファイルから読みます。
- モデル割当（レーン・fallback・打ち切り秒数）は **`data/model_plan.json`** が唯一の正本です。

## 構成

| パス | 内容 |
|---|---|
| `fortunelib/` | 占術の計算（`calc/`）・レジストリ・プロンプト組み立て・MTS（Stage A/B/C）・Stage D 口調変換・HTML レポート・型 C チャート描画 |
| `data/` | 占術データ・`prompts.json`・`model_plan.json`・`dataset_version.json`・`image_mapping.json` |
| `kaggle/` | `fortune_notebook.ipynb`・セル源（`cell0_bootstrap.py` `cell0_selftest.py` `cell1_csv_input.py` `cellN2_synthesis.py`）・`build_notebook.py`・`people_sample.csv` |
| `assets/` | `images/`（48 デッキ）・`fonts/`（OFL 1.1 のサブセット 4 本）・`video/`（冒頭動画） |
| `tests/` | pytest 一式（Kaggle のセルフテストと共通。依存する数値は `dataset_version.json` から読む） |
| `dataset-metadata.json` | Kaggle CLI 用のメタデータ（`id` を自分のユーザー名に書き換えて使う） |

## 実行の流れ

**入力は `kaggle/people_sample.csv`（または `/kaggle/working/people.csv`）だけ**です。人物の追加・差し替えは
CSV の書き換えで完結します（複数人可）。同梱サンプルは架空の人物で、`partner_*` 列に相性確認用の情報を含みます。

Notebook は **Cell 0（ブートストラップ）→ Cell 0.1（セルフテスト）→ Cell 1（CSV 入力＋Stage A）→
Cell N2（Stage B/C/D と HTML）** の順に実行します。必要な Secret は `GOOGLE_API_KEY` だけです。
成果物は `/kaggle/working/output/<person_id>/` に出ます。詳細は [docs/kaggle_setup.md](../docs/kaggle_setup.md)。

## 変更するときの約束

1. **入力は CSV のみ**。人物を固定したセルを追加しない
2. **モデル割当は `data/model_plan.json` だけで変える**。Stage B が全クラスタ完走しない限り Stage C へ進まない設計を崩さない
3. **字数制限・検証規則・`INSTRUCT_MARGIN` を変えるときはテストも更新する**
4. `data/*.json` の旧字体・簡体字・部首名は**誤字ではない**（古典用語）。日本語化してよいのはコメントと文書だけ
5. **対象日の表示ゲート**（相談あり＋`target` 空欄なら対象日を出さない）は `pipeline.py`・`mts.py`・`cellN2` の
   3 箇所で同じ判定を使う。1 箇所だけ変えない
6. 秘密情報（API キーなど）をログ・成果物・コードに出さない

## 検証（変更後は必ず全項目）

```bash
python3 -m pytest -q tests                 # expected.tests と同数が collect され、すべて合格（数件は意図的 skip）
python3 -m compileall -q fortunelib kaggle tests
python3 kaggle/build_notebook.py --check   # セル源を変えていなければ Notebook と一致する
```

リポジトリ直下では `tools/build_dataset_zip.py --dry-run` / `--verify` と `verify/` の各ツールも実行します
（[CONTRIBUTING.md](../CONTRIBUTING.md)）。

依存パッケージ: `sxtwl` `pyswisseph` `iztro-py`（import 名 `iztro_py`）`divicast` `lunar_python`
`kinqimen`（`--no-deps` で入れ、`ephem==4.2.1` を別途導入）`timezonefinder` `google-genai`。
導入スクリプトは `verify/env_setup.sh` です。
