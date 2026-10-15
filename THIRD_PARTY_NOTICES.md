# THIRD_PARTY_NOTICES — 第三者のソフトウェア・データ・商標

本プロジェクトのライセンスは次の 2 本立てです。

| 対象 | ライセンス | 全文 |
|---|---|---|
| Python コード・Notebook・スクリプト・テスト | GNU Affero General Public License v3.0（AGPL-3.0） | `LICENSE` |
| 画像（`assets/images`）・冒頭動画・プロンプト・自作データ・文書 | Creative Commons Attribution 4.0（CC BY 4.0） | `LICENSE-ASSETS` |

以下は、本プロジェクトが**利用・同梱・言及**している第三者の権利物と、その条件です。
（同梱＝リポジトリや配布 ZIP に含めているもの。利用＝実行時に pip で導入するもの。）

## 1. 同梱している第三者データ

### 1.1 KANJIDIC2（姓名判断の画数辞書の主ソース）

- ファイル: `fortune_dataset/data/kanji_kakusu_combined.json`（`tools/build_kakusu_dict.py` で生成。`source: "kanjidic2"` の 13,108 字）
- 権利者: Electronic Dictionary Research and Development Group（EDRDG）
- ライセンス: Creative Commons Attribution-ShareAlike 4.0（EDRDG General Dictionary Licence）
  https://www.edrdg.org/edrdg/licence.html
- 必要な表示（原文）:
  > This package uses the KANJIDIC2 dictionary file. This file is the property of the
  > Electronic Dictionary Research and Development Group, and is used in conformance with
  > the Group's licence.
- 本プロジェクトでの改変: `stroke_count` の先頭値と `grade` だけを抜き出し、Unihan・かなと統合した
  （KANJIDIC2 由来部分の再利用は CC BY-SA 4.0 の条件＝同じライセンスでの共有が必要）。

### 1.2 Unihan Database（KANJIDIC2 に無い漢字の画数）

- ファイル: 同上（`source: "unihan"` の約 89,900 字。`kTotalStrokes` の先頭値）
- 権利者: Unicode, Inc.（Unicode 18.0.0 の `Unihan_IRGSources.txt`）
- ライセンス: Unicode License v3 — https://www.unicode.org/license.txt（以下に原文を収録）

  > UNICODE LICENSE V3
  >
  > COPYRIGHT AND PERMISSION NOTICE
  >
  > Copyright © 1991-2026 Unicode, Inc.
  >
  > NOTICE TO USER: Carefully read the following legal agreement. BY
  > DOWNLOADING, INSTALLING, COPYING OR OTHERWISE USING DATA FILES, AND/OR
  > SOFTWARE, YOU UNEQUIVOCALLY ACCEPT, AND AGREE TO BE BOUND BY, ALL OF THE
  > TERMS AND CONDITIONS OF THIS AGREEMENT. IF YOU DO NOT AGREE, DO NOT
  > DOWNLOAD, INSTALL, COPY, DISTRIBUTE OR USE THE DATA FILES OR SOFTWARE.
  >
  > Permission is hereby granted, free of charge, to any person obtaining a
  > copy of data files and any associated documentation (the "Data Files") or
  > software and any associated documentation (the "Software") to deal in the
  > Data Files or Software without restriction, including without limitation
  > the rights to use, copy, modify, merge, publish, distribute, and/or sell
  > copies of the Data Files or Software, and to permit persons to whom the
  > Data Files or Software are furnished to do so, provided that either (a)
  > this copyright and permission notice appear with all copies of the Data
  > Files or Software, or (b) this copyright and permission notice appear in
  > associated Documentation.
  >
  > THE DATA FILES AND SOFTWARE ARE PROVIDED "AS IS", WITHOUT WARRANTY OF ANY
  > KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
  > MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT OF
  > THIRD PARTY RIGHTS.
  >
  > IN NO EVENT SHALL THE COPYRIGHT HOLDER OR HOLDERS INCLUDED IN THIS NOTICE
  > BE LIABLE FOR ANY CLAIM, OR ANY SPECIAL INDIRECT OR CONSEQUENTIAL DAMAGES,
  > OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS,
  > WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION,
  > ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THE DATA
  > FILES OR SOFTWARE.
  >
  > Except as contained in this notice, the name of a copyright holder shall
  > not be used in advertising or otherwise to promote the sale, use or other
  > dealings in these Data Files or Software without prior written
  > authorization of the copyright holder.

### 1.3 口語訳聖書（キリスト教的黙想モードの聖句）

- ファイル: `fortune_dataset/data/bible_verses.json`（24 節の短い抜粋）
- 出典: 日本聖書協会『口語訳聖書』（新約 1954 年・旧約 1955 年初版）。初版の訳文は日本では
  著作権の保護期間が満了しています（パブリックドメイン）。後年の訂正語句は含みません。
- 取り扱い: 訳文の文意は改変せず、表記の統一のみ行っています（著作者人格権への配慮）。
  再利用する方も文意の改変は避けてください。

### 1.4 フォント（型 C チャート描画用のサブセット）

- ファイル: `fortune_dataset/assets/fonts/*.ttf`（Noto Serif CJK JP / Noto Sans Devanagari /
  Noto Sans Symbols・Symbols 2 のサブセット）
- 権利者: Adobe（Noto Serif CJK）、The Noto Project Authors（Devanagari / Symbols）
- ライセンス: SIL Open Font License 1.1 — 全文と著作権表示は `fortune_dataset/assets/fonts/OFL.txt`

### 1.5 その他の自作データに含まれる公知の事実・固有名

- 占術の対応表（干支・九星・ナクシャトラ・ルーン・タロットの大アルカナ名など）は公知の体系で、
  本プロジェクトで表・解説文を作成しました（CC BY 4.0）。
- 動物占いの 60 キャラクター名（`doubutsu_60character.csv`）、ジーンキーズ／ヒューマンデザインの
  64 ゲート名（`genekeys_64.json`）は、各体系の**名称のみ**を参照用に収録しています。公式の
  解説文・図像・テキストは収録していません（§3 商標も参照）。
- ジーンキーズの画像デッキ（`M33_genekeys`）のアーキタイプ名は本プロジェクトの独自命名です
  （`genekeys_64_archetypes.json`）。
- メソポタミア天体オーメン（`meso_omens.json`）は学術翻訳で広く紹介されている定型句の代表例を
  日本語で要約したものです。

## 2. 実行時に利用する Python ライブラリ（同梱しない・pip で導入）

| ライブラリ | 用途 | ライセンス |
|---|---|---|
| pyswisseph（Swiss Ephemeris, Astrodienst AG） | 西洋占星術・ヒューマンデザインの天体位置 | AGPL-3.0（本プロジェクトのコードと同じ） |
| sxtwl | 干支・節気（四柱推命など） | BSD |
| lunar_python | 旧暦・算命学 | MIT |
| iztro-py（iztro の Python 移植） | 紫微斗数 | MIT |
| divicast | 六爻 | MIT |
| kinqimen | 奇門遁甲 | MIT |
| ephem（PyEphem） | 天文計算（kinqimen 依存） | MIT |
| timezonefinder / pytz | 出生地の時差 | MIT |
| geopy | 都市名 → 座標（ヒューマンデザイン、任意） | MIT |
| google-genai | Gemini API クライアント | Apache-2.0 |
| Pillow | チャート画像・画像処理 | MIT-CMU |
| fontTools | フォントのサブセット化（開発ツール） | MIT |
| numpy | 数値計算 | BSD-3-Clause |
| zhconv | 簡体字判定（開発ツール `tools/build_char_sets.py` のみ） | GPL-2.0-or-later |

Swiss Ephemeris は AGPL-3.0（または商用ライセンス）で提供されており、本プロジェクトのコードを
AGPL-3.0 とした理由の一つです。本プロジェクトは Swiss Ephemeris の天体暦ファイル（`*.se1`）を
同梱せず、pyswisseph 内蔵の Moshier 近似を使います。

## 3. 商標について（非提携の表明）

本プロジェクトは、各占術体系の名称を**その体系を指す一般的な呼称として**用いており、
いずれの権利者とも提携・承認・後援の関係にありません。

- **Gene Keys®（ジーンキーズ）** は Richard Rudd / Gene Keys Publishing の商標です。本プロジェクトは
  公式の文章・画像・「ギフト／シャドウ／シディ」の公式解説を一切収録せず、64 ゲート名から
  生成 AI が独自に解釈した文章を出力します。公式教材は https://genekeys.com/ を参照してください。
- **Human Design（ヒューマンデザイン）** は Jovian Archive Corporation の商標です。同上の扱いです。
- **動物占い®** は 株式会社ノラコム／個性心理學研究所 の登録商標です。本プロジェクトは
  生年月日 → 60 キャラクターの対応と名称のみを参照し、公式の性格解説文は収録していません。
- **六星占術®** は 細木数子事務所 の登録商標です。年運・月運の計算規則のみを実装しています。
- Google、Gemini は Google LLC の商標、Kaggle は Kaggle Inc. のサービス名です。

これらの名称を含む出力・画像・データを再配布する場合も、各権利者と無関係であることを
明示してください。権利者からの申し出があれば、該当部分を速やかに修正・削除します。

## 4. 画像について

`fortune_dataset/assets/images` の画像は、出どころにより次の 3 種類に分かれます
（デッキごとの一覧は `docs/data_sources.md` と `fortune_dataset/data/image_mapping.json`）。

| 区分 | デッキ | ライセンス |
|---|---|---|
| 本プロジェクトが新規に作成（生成 AI による原画 ＋ Pillow による枠・文字の合成。既存の市販デッキの図像は複製していない） | 上記以外のすべて（干支・星座・動物・ルーン・キッパー・レノルマン・オラクル・エンジェル・おみくじ・ジーンキーズ・クリスタル ほか） | CC BY 4.0（`LICENSE-ASSETS`） |
| 本プロジェクトが Pillow で描いた六十四卦の図 | `M23_meihua` `M26_iching`（`M22_liuyao` が共用） | CC0 1.0（図中の表記どおり） |
| 第三者のパブリックドメイン／CC0 素材 | `M27_tarot`（1909 年ライダー・ウェイト・スミス版のスキャン。原画 Pamela Colman Smith、1951 年没。sacred-texts.com のミラーから取得）／`M27_marseille`（1760 年ニコラ・コンヴェル版のスキャン。etteilla.org）／`M27_cartomancy`（AustinGabriel/Public-Domain-and-CC0-Playing-Cards） | パブリックドメイン／CC0 1.0 |

- ルーン文字の字形は Noto Sans Runic（SIL OFL 1.1）を Pillow で描画したものです。
- ジーンキーズのカード（`M33_genekeys`）に書かれた鍵番号・アーキタイプ名・3 層の語（開花／才能／影）は
  本プロジェクト独自の表記で、Gene Keys 公式のキーワード表やカードの図像は使用していません。
- 血液型占い（`M08_blood`）の画像は同梱していません（レポートにも埋め込みません）。
