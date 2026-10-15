# 同梱フォント

Kaggle環境には日本語フォントが無い前提で、型Cチャート（画像）に必要なフォントを
このディレクトリへ同梱します。型Cの一次フォントは小さなサブセットですが、文字列に
欠落グリフがあれば、対応できる場合は `jp_cjk_fallback.ttf` へ切り替えます。

| ファイル | 内容 | 元フォント / ライセンス |
|---|---|---|
| `typec_jp_subset.ttf` | 日本語・漢字・英数（型Cチャート用の小型サブセット） | Noto Serif CJK JP Regular ／ **SIL OFL 1.1** |
| `typec_devanagari_subset.ttf` | デーヴァナーガリー数字 10字（タントラ数秘術・アンカ・シャーストラ） | Noto Sans Devanagari Regular ／ **SIL OFL 1.1** |
| `typec_symbols_subset.ttf` | 惑星記号 ☉☽☿♀♂♃♄♅♆♇・星座記号 ♈〜♓・✓✗ | Noto Sans Symbols ＋ Noto Sans Symbols 2 ／ **SIL OFL 1.1** |
| `jp_cjk_fallback.ttf` | JIS X 0208 第1・第2水準、かな・約物・全角文字、配布物の語彙（約8,000字） | Noto Serif CJK JP Regular ／ **SIL OFL 1.1** |

4点とも **SIL Open Font License 1.1** です。元フォントの著作権表示とライセンス全文は同じディレクトリの `OFL.txt` にあります
（再配布のときは `OFL.txt` を一緒に配布してください）。

一次フォント3点は `tools/build_chart_fonts.py`、広いfallbackは `tools/build_jp_fallback_font.py`（リポジトリ直下）で作ります。
型Cの描画を実際に走らせて必要文字を採取する既存手順に加え、fallbackはJIS X 0208第1・第2水準と配布物の語彙を含めます。

```bash
python3 tools/build_chart_fonts.py                 # 型C用3フォントを生成・検証
python3 tools/build_chart_fonts.py --check         # 型C用フォントの検査だけ
python3 tools/build_jp_fallback_font.py            # 広い日本語fallbackを生成・検証
python3 tools/build_jp_fallback_font.py --check    # fallbackの検査だけ
```

- 配布ZIPには一次フォント3点、広い日本語fallback1点の計4点を同梱します（元フォントは開発環境のみ）。
- 検査: `tools/build_dataset_zip.py --dry-run`（欠けがあればビルド中止）と
  `tests/test_chart_font_coverage.py`（22占術の値バリエーションとfallback経路を検証）。
- 経緯: 2026-09-27 の実機で、手書きリストから漏れていた**デーヴァナーガリー数字・惑星/星座記号・✓✗・一部の漢字
  （12占術・21文字）**が消えていた不具合を修正したものです。
