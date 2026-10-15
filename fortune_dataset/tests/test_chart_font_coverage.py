# -*- coding: utf-8 -*-
"""型Cチャートのフォント被覆テスト（mts5.32）

**このテストが必要な理由（2026-09-27 の実機で発生した不具合）**

型Cは Kaggle にフォントが無いため、同梱サブセットフォントで描きます。
ところが「フォントを作る側の手書き文字リスト」と「実際に描く文字」がずれ、
**デーヴァナーガリー数字（タントラ・アンカ）／漢字（乾赤・玄虎蛇・軍鈴鉞 等）／
惑星・星座記号／✓✗ が無言で消えて**いました（文字が1つ欠けても画像は正常に
生成されるため、例外も警告も出ません＝気づけない）。

ここでは **22占術ぶんの描画を実際に走らせて「描く文字」を採取**し、
**同梱フォントにその文字のグリフがあるか**を厳密に検証します
（値のバリエーション＝本命星1〜9・数秘1〜9/11/22/33・六星の全12タイプ×13年運・
ヴェーダ・四柱・西洋・紫微・HD・パリミチャムなども回します）。

増えた文字をフォントが持っていなければ**このテストが落ちます**。
その場合は `python3 tools/build_chart_fonts.py` でフォントを作り直してください。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # fortune_dataset/
REPO = ROOT.parent                                     # リポジトリ直下

for _p in (str(ROOT), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fortunelib import chartdraw                        # noqa: E402


def _load_sample_cases():
    """tools/build_chart_fonts.py のサンプル（値のバリエーション）を借りる"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "build_chart_fonts", REPO / "tools" / "build_chart_fonts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._sample_cases()


class TestBundledFontsExist(unittest.TestCase):
    """3つの同梱フォントがそろっている（Kaggle にはシステムフォントが無い）"""

    FONTS = ("typec_jp_subset.ttf", "typec_devanagari_subset.ttf",
             "typec_symbols_subset.ttf", "jp_cjk_fallback.ttf")

    def test_all_required_fonts_bundled(self):
        for name in self.FONTS:
            with self.subTest(font=name):
                p = ROOT / "assets" / "fonts" / name
                self.assertTrue(p.is_file(), f"同梱フォントがありません: {p}")
                self.assertGreater(p.stat().st_size, 2_000, f"{name} が小さすぎます")

    def test_font_getters_use_bundles(self):
        """F_DEV / F_SYM が本フォントへ落ちていない（＝フォールバックしていない）"""
        dev = chartdraw.F_DEV(14)
        sym = chartdraw.F_SYM(14)
        self.assertEqual(str(getattr(dev, "path", "")),
                         str(ROOT / "assets" / "fonts" / "typec_devanagari_subset.ttf"))
        self.assertEqual(str(getattr(sym, "path", "")),
                         str(ROOT / "assets" / "fonts" / "typec_symbols_subset.ttf"))
        self.assertTrue(chartdraw.uses_bundled_font())


class TestGlyphCoverage(unittest.TestCase):
    """22占術で「描く文字」がすべて同梱フォントにある"""

    @classmethod
    def setUpClass(cls):
        try:
            import PIL  # noqa: F401
        except ImportError:                              # pragma: no cover
            raise unittest.SkipTest("PIL が無い環境のためスキップ")
        cls.cases = _load_sample_cases()

    def test_no_missing_glyphs(self):
        missing: dict[str, list[tuple[str, str]]] = {}
        for slug, calc, extra in self.cases:
            try:
                miss = chartdraw.missing_glyphs_for(slug, calc, extra)
            except Exception:
                continue                                  # 入力が合わないケースは対象外
            if miss:
                missing.setdefault(slug, []).extend(miss)
        if missing:
            lines = [f"  {slug}: " + "、".join(f"{ch}（{role}）" for role, ch in dict.fromkeys(v))
                     for slug, v in sorted(missing.items())]
            self.fail("同梱フォントに無い文字を描いています（"
                      "tools/build_chart_fonts.py でフォントを作り直してください）:\n"
                      + "\n".join(lines))

    def test_known_key_glyphs(self):
        """実機で消えていた文字が確実に入っている（回帰の見張り）"""
        cases = {
            "cjk": "乾赤字玄虎蛇初役擎軍鈴鉞旁路えしなや不利当該",
            "dev": "०१२३४५६७८९",
            "sym": "☉☽☿♀♂♃♄♅♆♇♈♉♊♋♌♍♎♏♐♑♒♓✓✗",
        }
        for role, chars in cases.items():
            with self.subTest(role=role):
                self.assertEqual(chartdraw.missing_glyphs(chars, role), [])

    def test_japanese_fallback_covers_and_draws_missing_glyphs(self):
        """型Cの一次フォントに無い字は、同梱fallbackへ切り替えて描画する。"""
        from PIL import Image, ImageDraw

        chars = "ガ司庫栞"
        primary = chartdraw.F(18)
        fallback = chartdraw.F_JP_FALLBACK(18)
        self.assertIsNotNone(fallback)
        self.assertTrue(all(chartdraw._missing_in(primary, ch) for ch in chars))
        self.assertTrue(all(not chartdraw._missing_in(fallback, ch) for ch in chars))
        self.assertEqual(chartdraw.missing_glyphs(chars, "cjk"), [])
        import warnings
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            selected = chartdraw._select_cjk_font("栞𒁹", primary)
        self.assertEqual(str(selected.path), str(fallback.path))
        self.assertTrue(any("fallback" in str(w.message) for w in caught))

        used = []
        original = ImageDraw.ImageDraw.text

        def spy(self, xy, text, *args, **kwargs):
            used.append(str(getattr(kwargs.get("font"), "path", "")))
            return original(self, xy, text, *args, **kwargs)

        ImageDraw.ImageDraw.text = spy
        try:
            with chartdraw._cjk_fallback_scope():
                draw = ImageDraw.Draw(Image.new("RGB", (240, 40), "white"))
                draw.text((0, 0), chars, font=primary, fill="black")
        finally:
            ImageDraw.ImageDraw.text = original
        self.assertIn(str(chartdraw._BUNDLED_JP_FALLBACK), used)

    def test_missing_detection_works(self):
        """fallback後も未収録の文字は検出し、fallback収録字は欠け扱いしない。"""
        self.assertEqual(chartdraw.missing_glyphs("乾", "cjk"), [])        # 一次フォント
        self.assertNotEqual(chartdraw.missing_glyphs("𒁹", "cjk"), [])     # CJK fallback外
        self.assertTrue(chartdraw._missing_in(chartdraw.F(14), "Ａ"))      # 一次フォントでは不足
        self.assertEqual(chartdraw.missing_glyphs("Ａ", "cjk"), [])       # fallbackで描ける
        self.assertEqual(chartdraw.missing_glyphs(" ", "cjk"), [])         # 空白は対象外


if __name__ == "__main__":                               # pragma: no cover
    unittest.main()
