# 画像の構成と追加方法（images）

レポートに入る画像は 3 つの型に分かれます。共通の原則は **「絵と文字の分離」**です。
絵は生成 AI やスキャンで用意し、番号・名前・記号などの文字は Pillow で確定的に描きます
（画像生成 AI に文字を書かせない。誤字・フォント欠けを作らないため）。

| 型 | 内容 | 例 |
|---|---|---|
| 型 A デッキ | 1 枚の結果 → デッキの中の 1 枚（または 2 枚）を表示 | タロット・ルーン・干支・おみくじ・ジーンキーズ |
| 型 B 固定 | 計算結果に依らない 1 枚、または結果と無関係に 1 枚を選ぶ | 水晶玉・タリスマン・鳥占・デルポイ |
| 型 C 実行時描画 | 文字なしのベース画像に、計算結果を Pillow で描き込む | 四柱推命の命式・西洋占星術のホロスコープ・姓名判断の画数 |

## 1. ディレクトリと命名

```
fortune_dataset/assets/images/<Mxx_slug>/        デッキごとのディレクトリ（48 個）
  NN_<NameEn>.webp                                 型 A/B: 番号 2 桁 ＋ 英名（空白なし）
  <name>_base.webp                                 型 C: 文字なしベース画像
fortune_dataset/data/image_mapping.json            占術 → デッキ・ファイル名パターン・ライセンスの対応表
verify/asset_checksums.sha256                      画像 4 種とフォント 4 本の SHA-256
```

- サイズの目安は 288×432（カード）または 300×400、WebP 品質 80、1 枚 45 KB 以下。
  タロット（JPG 300×528）とマルセイユ（WebP 320×618）はスキャン素材のためサイズが異なります。
- ファイル名の番号・英名は `data/*.json` の `no` / `name_en` から機械的に作ります
  （例: `lenormand_36.json` の 27 番 "Letter" → `M27_lenormand/27_Letter.webp`）。
- 画像の解決は `fortunelib/html_report.py` が行い、拡張子には依存しません。見つからなければその占術の
  画像を省くだけで、レポート生成は失敗しません。

## 2. 対応表 `image_mapping.json`

デッキごとに次の項目を持ちます。

| 項目 | 意味 |
|---|---|
| `slug` | 占術の slug（`registry.py`） |
| `pattern` | ファイル名のパターン（例 `M27_kipper/{no:02d}_{NameEnNoSpaces}.webp`） |
| `count` | 枚数 |
| `license` / `source` | ライセンスと出どころ（`docs/data_sources.md` と一致させる） |
| `resolve` | 計算結果のどの値からファイルを決めるか（例 `calc.sign` → 番号＋英名） |
| `shared_deck` | 他のデッキを共用する場合（六爻 → 易、誕生石 → クリスタル、現代タロット → タロット） |
| `filenames` / `ids` / `naming` | 枚数の多いデッキの一覧や命名規則 |

## 3. 型 C: 実行時チャート描画

`fortunelib/chartdraw.py` の `render_for_slug(slug, calc, extra)` が、占術ごとのベース画像
（`assets/images/<Mxx_slug>/<name>_base.webp`）に計算結果を描き込みます。対象は 22 占術
（九星気学・数秘術 4 種・カバラ・六星占術・ウェトン・プリンボン・姓名判断・四柱推命・算命学・
西洋占星術 4 種・ヴェーダ・紫微斗数・奇門遁甲・ヒューマンデザイン・パリミチャム）。

- 文字は同梱フォント（`assets/fonts/`）で描きます。一次フォントは小さなサブセット、
  欠けるグリフがあれば広い日本語フォールバック `jp_cjk_fallback.ttf` に切り替え、それにも無い字は警告します。
- 描画は決定論的で、同じ `calc` なら同じ画像になります。テスト（`tests/test_chartdraw.py`、
  `tests/test_chart_font_coverage.py`）が描画の成立とフォント被覆を検査します。
- 描画パラメータ（配置・色・フォントサイズ）はコード内の定数で、変更するとテストの期待値も変わります。

## 4. デッキを追加・差し替えるとき

1. **原画を用意する**: 文字なし・縦長（3:4 前後）。自作の生成画像か、ライセンス上再配布できる素材だけを使う
   （個人利用のみ許諾された無料素材は不可）。
2. **合成する**: `tools/make_lenormand_deck.py` を参考に、番号・和名・英名・枠を Pillow で描いて
   `NN_<NameEn>.webp` を書き出す（`--check` で枚数・サイズ・容量を確認）。
3. **対応表を更新する**: `data/image_mapping.json` にデッキを追加し、`license` / `source` を正しく書く。
   `html_report.py` の解決関数（結果 → ファイル名）を追加し、`tests/test_html_report_images.py` にテストを足す。
4. **チェックサムを更新する**: `fortune_dataset/assets/images` で
   `find . -type f \( -name '*.webp' -o -name '*.jpg' \) | sort | xargs sha256sum` を取り直し、
   フォント 4 本の行と合わせて `verify/asset_checksums.sha256` を書き換える。
   `sha256sum -c ../../../verify/asset_checksums.sha256` が全件 OK になること。
5. **検証する**: `python3 verify/asset_matching_audit.py`（結果 → 画像の突合）、pytest、
   `python3 tools/build_dataset_zip.py --dry-run`（容量と同梱物）。
6. **文書を更新する**: `docs/data_sources.md`・`LICENSE-ASSETS`・`THIRD_PARTY_NOTICES.md` の該当行。
   `dataset_version.json` の `expected.image_decks` はデッキ数が変わったときだけ更新する。

## 5. 冒頭動画カード

`assets/video/intro_video.json` に MP4・ポスター・表示設定があり、Cell N2 の `EMBED_INTRO_VIDEO` で
埋め込みの ON/OFF を切り替えます。HTML には同梱 MP4 の再生と、外部動画サイトへのリンクの両方を置きます。
