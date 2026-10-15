# データと画像の出どころ（data_sources）

本プロジェクトが同梱するデータ・画像・フォントの由来とライセンスをまとめます。ライセンス本文は
`LICENSE`（コード・AGPL-3.0）、`LICENSE-ASSETS`（画像・自作データ・CC BY 4.0）、
`THIRD_PARTY_NOTICES.md`（第三者データ・商標）を参照してください。

## 1. 占術データ（`fortune_dataset/data/`）

| 種類 | ファイル | 由来 |
|---|---|---|
| 暦・干支・九星・節気 | `ganzhi.json` `kyusei.json` `time_index_table.json` | 公知の暦法。計算は sxtwl / lunar-python |
| 六十四卦 | `iching_64.json` | キングウェン番号・卦名（公知）。説明文は自作 |
| タロット・マルセイユ | `tarot_78.json` | ライダー・ウェイト版の一般的な札名と正逆の要点（自作の要約） |
| レノルマン・キッパー | `lenormand_36.json` `kipper_36.json` | 伝統的な 36 枚の札名と一般に流布する意味体系（自作の要約） |
| オラクル・エンジェル | `oracle_44.json` `angel_44.json` | 本プロジェクトが定義した汎用 44 枚（既存の市販デッキの文言は使用していない） |
| カルトマンシー・ルーン | `cartomancy_52.json` `runes_24.json` | トランプ占いの一般的対応表、エルダー・フサルク 24 文字の一般的意味 |
| 数秘術 | `numerology.json` `numerology_tables.json` `tantra_numerology.json` | ピタゴラス式・カルデア式・カバラ式の一般的な対応表 |
| 姓名判断の画数辞書 | `kanji_kakusu_combined.json` `kanji_kakusu_license.json` | **KANJIDIC2**（EDRDG・CC BY-SA 4.0）を主ソース、無い字は **Unihan**（Unicode License）で補完。`tools/build_kakusu_dict.py` で生成。かな・記号の画数は自作 |
| 動物占い・六星占術 | `doubutsu_*.csv` `animals_60_profiles.json` `rokusei_*` | 生年月日 → 分類の対応表と、本プロジェクト独自の性格プロファイル文。商標の名称は占術の種類を示す目的でのみ使用 |
| ジーンキーズ | `genekeys_64.json` `genekeys_64_archetypes.json` | 64 鍵の番号はヒューマンデザインの 64 ゲート＝六十四卦に対応（公知）。鍵ごとの「アーキタイプ名」と解説は本プロジェクト独自のもので、Gene Keys 公式の語彙・キーワード表は収録していない |
| ウェトン・プリンボン | `weton_35.json` `weton_35_extra.json` `primbon_*.json` | ジャワ暦の一般文化資料にもとづく自作の要約 |
| ヴェーダ | `nakshatras_27.json` | 27 ナクシャトラの名称と一般的な象意 |
| 紫微斗数の日本語名 | `iztro_ja_names.json` `iztro_ja_translations.json` | iztro の出力（中国語）→ 日本語の対応表（自作） |
| 聖句 | `bible_verses.json` | 日本聖書協会『口語訳聖書』（新約 1954 年・旧約 1955 年初版、日本ではパブリックドメイン）からの短い抜粋 24 節。改変しない |
| 神々・オーメン・誕生石 | `deities.json` `meso_omens.json` `birthstones.json` | 公知の神話・古代資料・誕生石表にもとづく自作の要約 |
| おみくじ | `omikuji_12.json` | 一般的な 12 段階表（神社により異なる） |
| 都道府県 | `japan_prefectures.json` | 都道府県庁所在地の座標（公知） |
| プロンプト・モデル割当・版印 | `prompts.json` `model_plan.json` `dataset_version.json` `image_mapping.json` | 本プロジェクト作成（CC BY 4.0） |

`divinations_a.json` / `divinations_other_ai.json` は各占術の説明・出力構成の定義（自作）です。

## 2. 画像（`fortune_dataset/assets/images/`、48 デッキ）

画像は 3 種類に分かれます。デッキごとの対応表は `fortune_dataset/data/image_mapping.json` です。

### 2.1 本プロジェクトが新規に作成した画像（CC BY 4.0）

生成 AI で「文字なし」の原画を作り、番号・和名・英名・枠などの文字は Pillow で合成しています。
既存の市販デッキやキャラクター商品の図像は複製していません。

| デッキ | 枚数 | 内容 |
|---|---|---|
| `M01_eto` | 12 | 干支 |
| `M02_seiza` | 12 | 12 星座 |
| `M09_animal` | 60 | 動物占い（12 動物 × 5 配色） |
| `M12_stone` | — | 誕生石（`M30_crystal` を共用） |
| `M27_runes` | 24 | アメシストの石にルーン字形（Noto Sans Runic・OFL 1.1）を描画 |
| `M27_kipper` | 36 | 動物キャラクターのキッパー |
| `M27_lenormand` | 36 | 水彩調のレノルマン（`tools/make_lenormand_deck.py` で合成） |
| `M27_oracle` / `M27_angel` | 44 / 44 | 汎用オラクル・エンジェル |
| `M28_omikuji` | 100 | 御神籤札（12 段階 × 8 ポーズ ＋ 特別柄 4） |
| `M28_astragaloi` | 4 | 距骨籤 |
| `M29_pendulum` / `M29_african` | 3 / 9 | ペンデュラム・コーリー貝 |
| `M30_crystal` / `M30_crystalball` / `M30_talisman` | 12 / 1 / 1 | クリスタル・水晶玉・タリスマン |
| `M30_meso` / `M30_christian` | 24 / 24 | メソポタミア天体オーメン・聖句の情景 |
| `M30_haruspex` / `M30_ornith` / `M30_delphi` | 1 / 5 / 5 | 肝占・鳥占・デルポイ |
| `M33_genekeys` | 64 | 3 パネル構成（開花／才能／影）。題字・アーキタイプ名・3 層の語は本プロジェクト独自の表記 |

### 2.2 本プロジェクトが Pillow で描いた図（CC0 1.0）

| デッキ | 枚数 | 内容 |
|---|---|---|
| `M23_meihua` / `M26_iching` | 64 / 64 | 六十四卦の図（卦名・読み・上下卦）。`M22_liuyao` が共用。図中の表記どおりパブリックドメインに提供 |

### 2.3 第三者のパブリックドメイン／CC0 素材

| デッキ | 枚数 | 出どころ | ライセンス |
|---|---|---|---|
| `M27_tarot` | 78 | 1909 年ライダー・ウェイト・スミス版タロットのスキャン（原画 Pamela Colman Smith、1951 年没）。sacred-texts.com のパブリックドメイン・ミラーから取得。JPG 300×528。`M27_urbantarot` が共用 | パブリックドメイン |
| `M27_marseille` | 78 | 1760 年ニコラ・コンヴェル版マルセイユ・タロットのスキャン（etteilla.org） | パブリックドメイン |
| `M27_cartomancy` | 52 | フランス式トランプ（AustinGabriel/Public-Domain-and-CC0-Playing-Cards） | CC0 1.0 |

血液型占い（`M08_blood`）の画像は同梱していません。

### 2.4 実行時に描くチャート（型 C）

九星気学・数秘術（生年月日）・カバラ数秘術のチャートは画像ファイルではなく、`fortunelib/chartdraw.py` が
計算結果から Pillow で描きます（`docs/images.md`）。

## 3. フォント（`fortune_dataset/assets/fonts/`、SIL OFL 1.1）

| ファイル | 元フォント | 用途 |
|---|---|---|
| `typec_jp_subset.ttf` | Noto Serif CJK JP | 型 C チャートの日本語 |
| `typec_devanagari_subset.ttf` | Noto Sans Devanagari | 型 C チャートの梵字 |
| `typec_symbols_subset.ttf` | Noto Sans Symbols ＋ Noto Sans Symbols 2 | 惑星・星座記号・✓✗ |
| `jp_cjk_fallback.ttf` | Noto Serif CJK JP | JIS X 0208 第 1・第 2 水準と配布物の語彙（約 8,000 字）の広いフォールバック |

サブセット化の手順は `tools/build_chart_fonts.py` / `tools/build_jp_fallback_font.py`、ライセンス本文は
`fortune_dataset/assets/fonts/OFL.txt` です。

## 4. 冒頭動画（`fortune_dataset/assets/video/`、CC BY 4.0）

レポート冒頭のカードで再生する固定の MP4 と、そのポスター画像・設定（`intro_video.json`）。
本プロジェクト作成です。

## 5. 実行時に使うライブラリ（同梱しない）

| ライブラリ | ライセンス | 用途 |
|---|---|---|
| pyswisseph | AGPL-3.0 | 天体暦（西洋・ヴェーダ占星術・ヒューマンデザイン） |
| sxtwl | BSD | 干支・節気 |
| lunar-python | MIT | 旧暦・干支 |
| iztro-py | MIT | 紫微斗数 |
| divicast | MIT | 六爻（排盤） |
| kinqimen | MIT | 奇門遁甲 |
| ephem | MIT | 天文計算 |
| timezonefinder / pytz | MIT | 時差 |
| google-genai | Apache-2.0 | Gemini API |
| Pillow | MIT-CMU | 画像合成・チャート描画 |
| fontTools | MIT | フォントのサブセット化（開発時） |
| zhconv | GPL-2.0+ | 簡体字 → 日本語字形の補助（開発時のみ） |

## 6. 商標

「ジーンキーズ／Gene Keys」「ヒューマンデザイン／Human Design」「動物占い」「六星占術」「Google」「Gemini」
「Kaggle」は各権利者の商標または登録商標です。本プロジェクトは各権利者と提携・承認関係になく、名称は
占術やサービスの種類を示す目的でのみ使っています。
