# Fortune Dataset — 53 占術の計算エンジン ＋ Gemini 鑑定レポート生成

[English](README.en.md)

生年月日・出生時刻・出生地・氏名などの入力から **53 種類の占術**を決定論的に計算し、
Google Gemini API で鑑定文を生成して、**画像つきの 1 枚 HTML レポート**にまとめる
Python パッケージと Kaggle Notebook です。計算部分は LLM を使わず、再現性があります。

- 計算エンジン `fortunelib/`（四柱推命・西洋占星術・紫微斗数・易・数秘術・姓名判断 ほか）
- 鑑定文生成パイプライン（Stage A 個別占術 → Stage B クラスタ中間レポート → Stage C 軸サマリーと最終統合 → Stage D 読み物版 3 トーン）
- 画像デッキ（タロット・ルーン・おみくじ・干支など、データセット同梱）と実行時チャート描画
- Kaggle Notebook（8 セル）と CPU だけで動くセルフテスト一式
- 入力は CSV 1 枚（複数人可・相性占い用の相手情報つき）

> **占いは娯楽・自己省察のための参考情報です。** 生成される鑑定文は医療・法律・投資などの
> 専門的助言ではなく、結果の正確性や将来の出来事を保証するものではありません。

## ライセンス

| 対象 | ライセンス |
|---|---|
| Python コード・Notebook・テスト・スクリプト | [GNU AGPL-3.0](LICENSE) |
| 画像デッキ（本プロジェクト作成分）・冒頭動画・プロンプト・自作データ | [CC BY 4.0](LICENSE-ASSETS) |
| 第三者データ（KANJIDIC2 CC BY-SA 4.0、Unihan、口語訳聖書、フォント OFL 1.1、パブリックドメインのタロット画像 ほか） | [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) |

コードが AGPL なのは、依存ライブラリ pyswisseph（Swiss Ephemeris）が AGPL-3.0 であるためです。

**商標について**: 「ジーンキーズ／Gene Keys」「ヒューマンデザイン」「動物占い」「六星占術」などは
各権利者の商標または登録商標です。本プロジェクトはこれらの権利者と提携・承認関係になく、
名称は占術の種類を示す目的でのみ使っています。計算・解釈はすべて本プロジェクト独自の実装です。

## 占術一覧（53 種）

| グループ | 占術 |
|---|---|
| G1 生年月日系（14） | 星座占い・干支・九星気学・数秘術（生年月日）・タントラ数秘術・アンカ・シャーストラ・血液型占い・動物占い・六星占術・ウェトン・プリンボン（ジャワ）・パワーストーン・おみくじ・ジーンキーズ |
| G2 氏名系（4） | 姓名判断・数秘術（氏名）・数秘術・カバラ・カルデア数秘術 |
| G3 命盤系（8） | 四柱推命・西洋占星術・ネイタル占星術・トランジット分析・ヴェーダ占星術・紫微斗数・算命学・ヒューマンデザイン |
| G4 卜占・カード系（13） | 易・六爻・梅花易数・奇門遁甲・タロット・タロット・ド・マルセイユ・レノルマン・キッパー・オラクル・エンジェル・カルトマンシー・現代タロット・占星術・ルーン |
| G5 相性（2） | シナストリー・パリミチャム |
| G6 象徴・古代占術（12） | キリスト教的黙想（聖句）・クリスタル・ヒーリング・水晶玉占い・ペンデュラム・タリスマン・伝統的アフリカ占い・肝占・メソポタミア天体オーメン・デルポイの託宣・鳥占・籤占（アストラガロイ）・御縁のある神さま Top10 |

定義は `fortune_dataset/fortunelib/registry.py`（slug・プロンプト ID・必要入力）にあります。
血液型占いは血液型、氏名系は氏名、相性 2 種は相手の情報が CSV にあるときだけ実行されます。

## 仕組み（概要）

```
people.csv ──▶ Stage A  個別占術 52 件（計算 → プロンプト → Gemini Flash-Lite 2 レーン）
               Stage B  クラスタ中間レポート 11 本（method 軸 5 ＋ culture 軸 6）
               Stage C  軸サマリー 2 本 → 最終統合レポート → 御縁のある神さま Top10
               Stage D  読み物版（標準／やさしい／スピリチュアルの 3 トーン）
           ──▶ output/<person_id>/  Markdown・JSON・画像を埋め込んだ 1 枚 HTML
```

モデル割当は `fortune_dataset/data/model_plan.json` が唯一の正本です（レーン・fallback・
打ち切り秒数）。詳しくは [docs/architecture.md](docs/architecture.md)。

## クイックスタート（Kaggle）

1. このリポジトリを ZIP にして Kaggle Dataset として追加するか、公開済みの Dataset を Notebook に Add Input する
2. `fortune_dataset/kaggle/fortune_notebook.ipynb` を Notebook として取り込む（アクセラレータ **None**）
3. **Add-ons → Secrets** に `GOOGLE_API_KEY`（Gemini API キー）を登録する。必要な Secret はこれだけ
4. セルを **Cell 0（ブートストラップ）→ Cell 0.1（セルフテスト）→ Cell 1（CSV 入力＋Stage A）→ Cell N2（Stage B/C/D と HTML）** の順に実行する
5. 成果物は `/kaggle/working/output/<person_id>/` に出力される（`<person_id>_report.html` ほか）

手順の詳細と入力 CSV の列は [docs/kaggle_setup.md](docs/kaggle_setup.md)。

## ローカルで動かす

```bash
git clone https://github.com/jack4andmanastalk-byte/FortuneTelling.git
cd FortuneTelling
bash verify/env_setup.sh            # 依存ライブラリの導入（sxtwl, pyswisseph, iztro-py, ... ）
cd fortune_dataset && python3 -m pytest -q tests && cd ..
python3 tools/demo_local_html.py --out demo_out   # API を使わないダミー文章で HTML の形を確認
```

実際に Gemini を呼ぶローカル実行は環境変数 `GOOGLE_API_KEY` を設定して
`fortunelib.mts.run_person_mts` を使います（Notebook の Cell 1／N2 がその参考実装です）。
API キーをコードやログに書かないでください。

## リポジトリ構成

| パス | 内容 |
|---|---|
| `fortune_dataset/fortunelib/` | 占術の計算・プロンプト組み立て・MTS パイプライン・トーン変換・HTML レポート |
| `fortune_dataset/data/` | 占術データ・プロンプト（`prompts.json`）・モデル割当（`model_plan.json`）・版印（`dataset_version.json`）・画像対応表（`image_mapping.json`） |
| `fortune_dataset/kaggle/` | Notebook（`fortune_notebook.ipynb`）とそのセル源・`build_notebook.py`・入力サンプル `people_sample.csv` |
| `fortune_dataset/assets/` | 画像デッキ（`images/`）・サブセットフォント（`fonts/`）・冒頭動画（`video/`） |
| `fortune_dataset/tests/` | pytest 一式（Kaggle のセルフテストでも同じものを実行） |
| `tools/` | 配布 ZIP の生成と検査・Notebook 再生成・辞書とフォントのビルド・ローカルデモ・文章検査 |
| `verify/` | 依存導入スクリプト・画像チェックサム・画像突合監査・実行結果の検証ツール |
| `docs/` | [設計](docs/architecture.md)・[Kaggle 手順](docs/kaggle_setup.md)・[データの出どころ](docs/data_sources.md)・[画像](docs/images.md) |

版・件数（占術数・テスト数・デッキ数・Notebook セル数）の正本は `fortune_dataset/data/dataset_version.json` です。

## 開発

変更後は [CONTRIBUTING.md](CONTRIBUTING.md) の検証（pytest・compileall・Notebook の同期確認・配布 ZIP の検査）を
すべて通してください。変更履歴は [CHANGELOG.md](CHANGELOG.md)。

## 謝辞

Swiss Ephemeris（pyswisseph）、sxtwl、lunar-python、iztro、divicast、kinqimen、timezonefinder、
Noto フォント、KANJIDIC2（EDRDG）、Unicode Unihan、パブリックドメインのタロット画像を公開している
各プロジェクトに感謝します。詳細は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
