# Kaggle での実行手順（kaggle_setup）

Notebook は CPU だけで動きます。必要なものは **Gemini API キー 1 つ**と、このリポジトリを
Dataset として Notebook に接続することだけです。

## 1. Dataset を用意する

どちらかを選びます。

**A. 公開済みの Dataset を使う** — Notebook の *Add Input* で Dataset を追加します。

**B. 自分で Dataset を作る**

```bash
# リポジトリ直下で: 画像・冒頭動画込みの配布 ZIP を作り、検査する
python3 tools/build_dataset_zip.py --with-images --out build/zips/fortune_dataset_kaggle_v1.0.0.zip
python3 tools/build_dataset_zip.py --verify build/zips/fortune_dataset_kaggle_v1.0.0.zip
```

できた ZIP を Kaggle の *Datasets → New Dataset* でアップロードします（Kaggle が自動で展開します）。
Kaggle CLI を使う場合は `fortune_dataset/dataset-metadata.json` の `id` を自分のユーザー名に書き換えて
`kaggle datasets create` / `kaggle datasets version` を実行します。Dataset のライセンス欄は AGPL-3.0 です
（画像・自作データは CC BY 4.0、詳細は `LICENSE-ASSETS`）。

Dataset の階層は Notebook 側が自動で探索するので（`/kaggle/input/**/fortunelib`）、フォルダ名やスラッグが
違っても動きます。画像ディレクトリも同様に自動探索します（環境変数 `FORTUNE_ASSETS_DIR` で明示も可能）。

## 2. Notebook を作る

1. *Code → New Notebook* → *File → Import Notebook* で `fortune_dataset/kaggle/fortune_notebook.ipynb` を取り込む
2. 右側の *Input* に 1. の Dataset を追加する
3. *Settings → Accelerator* は **None**（GPU 不要）。インターネットは pip 導入と Gemini API のために **On**
4. *Add-ons → Secrets* で `GOOGLE_API_KEY` を追加し、**Attached** をオンにする。必要な Secret はこれだけ
   （コードや CSV に API キーを書かないでください）

## 3. セルの実行順

| セル | 役割 |
|---|---|
| Cell 0 ブートストラップ | 不足ライブラリの pip 導入、`fortunelib` の自動検出、`FORTUNE_DATA_DIR` の設定、API キーの読み込み |
| Cell 0.1 セルフテスト | 同梱テストの実行と Gemini API の疎通確認（数分）。**失敗したら先へ進まない** |
| Cell 1 入力 ＋ Stage A | CSV を読み、人物ごとに 52 件の個別占術を計算・生成する |
| Cell N2 統合 ＋ HTML | Stage B（中間 11 本）→ Stage C（軸 2 本・最終統合・神々）→ Stage D（3 トーン）→ 1 枚 HTML |

Cell 1 と N2 を合わせた所要時間は 1 人あたり数十分で、無料枠のレート制限（モデルごとの RPM/RPD）と
混雑状況に左右されます。Cell N2 の末尾にエラーがまとまって表示されるので、実行後に確認してください。

### セルフテストの読み方

- 「Ran N tests」の N が `fortune_dataset/data/dataset_version.json` の `expected.tests` と一致し、
  FAILED が無ければ合格です（意図的な skip は数件あります）。
- 0.2 秒で大量に ERROR になるときは依存ライブラリの import 失敗です。Cell 0 の出力で pip の結果を確認し、
  Notebook を再起動して Cell 0 からやり直します。
- API 疎通で 429 が出るときは無料枠の日次上限に達しています。翌日に再実行するか、`model_plan.json` の
  レーン設定を見直します。
- API 疎通が「混雑しています（503/408）」で止まるのは **Gemini 側の一時的な混雑**で、API キー・Dataset・
  Notebook の異常ではありません（キー不正なら 400/403、モデル名違いなら 404、日次枠切れなら 429 になります）。
  疎通は軽量モデル 3 本（`gemini-3.1-flash-lite` → `gemini-3.5-flash-lite` → `gemini-3-flash-preview`）を順に試し、
  どれか 1 本が応答すれば先へ進みます。3 本とも混雑のときだけ止まるので、30〜60 分ほど待って Cell 0 からやり直します。

## 4. 入力 CSV

既定では Dataset 同梱の `kaggle/people_sample.csv`（架空の人物 1 名・相手情報つき）を読みます。
自分のデータを使うときは **`/kaggle/working/people.csv`** にアップロードすると、そちらが優先されます。
文字コードは UTF-8（BOM 付きも可）、1 行 = 1 人、複数行可。

| 列 | 必須 | 形式・例 | 備考 |
|---|---|---|---|
| `person_id` | ○ | `demo_hoshino_nagi` | 出力フォルダ名になる（英数字・`_`・`-`・かな漢字） |
| `birth_date` | ○ | `1992-11-06` | 西暦 `YYYY-MM-DD` |
| `birth_time` | | `20:20` | 空欄なら正午として近似し、その旨を記録する |
| `birth_place` | | `愛知県` | 都道府県名（出生地の座標・時差の決定に使用） |
| `gender` | | `F` / `M` / `other` | 空欄は `unknown` |
| `blood_type` | | `A` / `B` / `O` / `AB` | 空欄なら血液型占いを省略 |
| `name_kanji` | | `星野 凪` | 空欄なら姓名判断を省略 |
| `name_kana` | | `ほしの なぎ` | 空欄なら氏名の数秘術 3 種を省略 |
| `partner_date` / `partner_time` / `partner_place` | | 本人と同じ形式 | 空欄なら相性 2 種（シナストリー・パリミチャム）を省略 |
| `consultation` | | 自由文 | 統合鑑定の冒頭に「ご相談」として表示し、各占術が参照する |
| `target` | | `2026-10-15` | 対象日。空欄かつ相談ありのときは対象日の行を出さない |

入力した個人情報は Notebook の出力（`/kaggle/working/output/`）にそのまま含まれます。実在の人物の
データを使うときは Notebook と出力を **Private** にしてください。

## 5. 成果物

```
/kaggle/working/output/<person_id>/
  <person_id>_report.html   画像を埋め込んだ 1 枚 HTML（ダウンロードしてブラウザで開く）
  synthesis_report.md       統合鑑定レポート
  final_report.md           最終統合（神々 Top10 を含む）
  cluster_reports/          クラスタ中間レポート・軸サマリー
  results/                  個別占術の Markdown と計算結果 JSON
  tone_reports/             読み物版（3 トーン）
```

HTML は PC の Chrome と Android の Chrome で確認しています（iPhone/iPad の Safari は未確認）。

## 6. うまくいかないとき

| 症状 | 見るところ |
|---|---|
| `CSVが見つかりません` | `/kaggle/working/people.csv` の名前・場所。Dataset に `kaggle/people_sample.csv` があるか |
| `fortunelib が見つかりません` | Input に Dataset が付いているか。Cell 0 の `/kaggle/input` 一覧 |
| `GOOGLE_API_KEY` が無い | Secrets の名前と *Attached* のチェック |
| 503 / 打ち切りが多い | 混雑時間帯。`model_plan.json` の fallback に従って自動で別モデルへ渡るので、完走するなら問題なし |
| Cell 0.1 が「混雑しています（503/408）」で止まる | Gemini 側の混雑（軽量モデル 3 本とも）。キー・Dataset・Notebook は正常。時間をおいて Cell 0 から再実行 |
| 画像がレポートに出ない | Cell N2 の出力に表示される画像ディレクトリ。`FORTUNE_ASSETS_DIR` で明示できる |

実行結果の機械的な検証は `verify/verify_run_output.py --results-zip <output の ZIP> --assets <images> --pkg fortune_dataset`
で行えます（問題 0 が合格）。
