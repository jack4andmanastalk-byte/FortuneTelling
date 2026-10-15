# -*- coding: utf-8 -*-
"""mts5.63: 型Cチャートの**文字欠け**（同梱フォントに無い字）と、その可視化。

見つかった不具合（2026-09-30・**mts5.62 の Kaggle 実機**）:
    人物 `demo_kirishima_souta`（1993-05-17）は旧暦が **一九九三年闰三月廿六**。
    iztro-py の `lunar_date` は簡体字で返るため、**同梱の日本語フォントに無い
    「闰」（U+95F0）**が混ざり、紫微斗数（M20_ziwei）の型Cチャートで
    **日付の1文字が欠けて描画**されました（＝豆腐）。

    検証器 `verify/verify_run_output.py` はこれを
      - `[typec] 同梱フォントに無い文字を描こうとしています（1件: 闰（cjk））`
      - `[bytes] 納品画像と一致しない（17.9KB）`（再生成画像と食い違う）
    の**2件の不合格**として検出し、デッキ数も 48→47 に減っていました
    （mts5.61 の修正と同じ「1つの原因が複数の症状になる」型）。

直し方:
  1. `fortunelib/calc/ziwei.py` で旧暦を**日本語の漢字**へ正規化する
     （闰→閏・腊→臘。どちらも同梱フォントに収録がある）。
     「腊」（臘月＝旧暦12月）も**同じ経路で欠ける**ため同時に直しています。
  2. 同じ調査で**四柱推命の納音「白蠟金」**（庚辰・辛巳の日柱）も「蠟」が無いと分かり、
     日本語表記の**「白蝋金」**へ直しました（1995-12-15・2001-09-15 の生まれで実測）。
  3. `fortunelib/chartdraw.py` の `_select_cjk_font()` は `RuntimeWarning` しか
     出しておらず、**実行の最後の「■ 警告」一覧に出ない**（実機のログにも
     警告台帳にも出ていませんでした）ので、同じ事象を**警告台帳**にも残します。

このファイルは「**描く文字がフォントにある**」ことをデータ側から固定します。
"""
from __future__ import annotations

import datetime
import unittest
from pathlib import Path

from fortunelib import chartdraw, runcheck
from fortunelib.calc.ziwei import _JA_KANJI_FIX, _ja_kanji, ziwei_chart

ROOT = Path(__file__).resolve().parents[1]

#: 型Cチャート（検証器と同じ一覧を持つ＝片方だけ増えると気づけるようにここでも固定）
TYPEC_SLUGS = (
    "M03_kyusei", "M06_kabbalah", "M05_numerology_name", "M07_chaldean",
    "M04_tantra", "M04_anka", "M10_rokusei", "M14_weton", "M13_primbon",
    "M16_seimei", "M17_bazi", "M19_vedic", "M21_sanmei", "M24_qimen",
    "M18_western", "M18_natal", "M18_transit", "M18_synastry",
    "M20_ziwei", "M25_hd", "M15_parimicham", "M04_numerology_birth",
)

#: 文字欠けが出ていた組み合わせ（旧暦の閏月）と、旧暦12月（臘月）の実例
LEAP_MONTH_DATES = ((1993, 5, 17), (1987, 8, 14), (1995, 9, 12))
LAST_MONTH_DATES = ((1992, 12, 24), (1995, 1, 30))


def _sample_person() -> dict:
    """実機CSVの人物（＝次回のKaggle実行で使う入力）。"""
    from tests.fixtures.consultation import load_sample_rows, csv_consultation
    row = load_sample_rows()[0]
    row["consultation"] = csv_consultation()
    return row


#: 表示スラグ（M20_ziwei 等＝デッキ名）→ calc のキー（ziwei 等）。
#: `TYPEC_DECKS` は slug → (ベース画像, 和名, 英名) なので、calc のキーは
#: `fortunelib.registry` の対応（M20_ziwei の calc_key は ziwei）を使う。
def _calc_key(slug: str) -> str | None:
    from fortunelib.registry import REGISTRY
    for entry in REGISTRY.values():
        if str(entry.get("calc_key") or "") and \
                str(entry.get("slug") or "").lower() in slug.lower():
            return entry["calc_key"]
    # デッキ名の後半（ziwei・hd・parimicham など）が calc のキーになっている
    tail = slug.split("_", 1)[1] if "_" in slug else slug
    for key in (f"M{slug}", tail):
        pass
    return tail


def _find_calc(R: dict, slug: str):
    """`build_calc_results` の結果からデッキ名（M20_ziwei）の calc を引く。

    キーは calc のキー（ziwei・hd…）なので、**デッキ名をそのまま引くと None** に
    なり「検査したつもり」で空振りする（mts5.63 の調査で実際に踏んだ罠）。
    """
    for key in (slug, slug.split("_", 1)[-1]):
        if isinstance(R.get(key), dict):
            return R[key]
    return None


def _calc_batch(row: dict) -> dict:
    from fortunelib.batch import build_calc_results
    from fortunelib.batch_runner import row_to_input
    from fortunelib.profile import normalize_input
    ni = normalize_input(row_to_input(row))
    return build_calc_results(ni, consultation=ni.consultation)


class TestJaKanjiNormalizationMts563(unittest.TestCase):
    """旧暦の簡体字を日本語の漢字へ直す"""

    def test_mapping_targets_exist_in_the_bundled_fonts(self):
        for zh, ja in _JA_KANJI_FIX.items():
            self.assertIn(zh, "闰腊", zh)
            self.assertIn(ja, "閏臘", ja)
            # 直した先の字が**同梱フォントで描ける**こと（直しても消えるなら意味がない）
            self.assertEqual(
                chartdraw.missing_glyphs([ja], "cjk"), [],
                f"{ja} が同梱フォントに無い（tools/build_chart_fonts.py で追加が必要）")
            # 直す前の字は（日本語フォントには）無い＝放っておくと欠ける
            self.assertNotEqual(chartdraw.missing_glyphs([zh], "cjk"), [])

    def test_lunar_date_uses_japanese_kanji(self):
        for (y, m, d) in LEAP_MONTH_DATES + LAST_MONTH_DATES:
            lunar = ziwei_chart(y, m, d, 9, "F")["lunar_date"]
            self.assertNotIn("闰", lunar, lunar)
            self.assertNotIn("腊", lunar, lunar)
            self.assertEqual(lunar, _ja_kanji(lunar))
            self.assertEqual(chartdraw.missing_glyphs(sorted(set(lunar)), "cjk"), [],
                             f"{y}-{m:02d}-{d:02d} の旧暦 {lunar}")

    def test_leap_month_and_last_month_are_actually_covered_by_the_samples(self):
        """標本が「閏月」「臘月」を実際に踏んでいること（テストが空振りしていない）"""
        leap = [ziwei_chart(*x, 9, "F")["lunar_date"] for x in LEAP_MONTH_DATES]
        last = [ziwei_chart(*x, 9, "F")["lunar_date"] for x in LAST_MONTH_DATES]
        self.assertTrue(any("閏" in x for x in leap), leap)
        self.assertTrue(any("臘" in x for x in last), last)

    def test_no_simplified_only_char_remains(self):
        """tools の簡体字一覧（正本）に載る字が旧暦に残っていない（網羅の確認）。"""
        table = ROOT.parent / "tools" / "simplified_only.txt"
        if not table.is_file():
            self.skipTest("簡体字の正本が無い環境")
        bad_chars = set(table.read_text(encoding="utf-8"))
        seen: set[str] = set()
        for y in range(1985, 2006):
            for m in (1, 3, 5, 8, 9, 11, 12):
                seen.update(ziwei_chart(y, m, 15, 9, "F")["lunar_date"])
        self.assertEqual(sorted(seen & bad_chars), [], "旧暦に簡体字が残っています")


class TestTypeCChartsAreDrawableMts563(unittest.TestCase):
    """描く文字がすべて同梱フォントにある（実機の入力で通しで確認）"""

    def test_typec_slugs_match_the_verifier(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "verify_run_output", ROOT.parent / "verify" / "verify_run_output.py")
        vro = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vro)
        self.assertEqual(tuple(s for _m, s in vro.TYPEC_CAPTION_SLUG), TYPEC_SLUGS)

    def test_sample_person_has_no_missing_glyphs(self):
        R = _calc_batch(_sample_person())
        checked = 0
        for slug in TYPEC_SLUGS:
            calc = _find_calc(R, slug)
            if not isinstance(calc, dict):
                continue
            checked += 1
            self.assertEqual(chartdraw.missing_glyphs_for(slug, calc, None), [], slug)
        self.assertGreaterEqual(checked, 20, "型Cの calc をほとんど見ていません")
        # 描く文字の集合が取れている（中身は人物しだい＝mts5.64 の人物は閏月生まれではない。
        # 「閏の経路を実際に通る」確認は、閏月・臘月の生まれを使う下のテストが担う）
        seen = chartdraw.drawn_chars("M20_ziwei", _find_calc(R, "M20_ziwei"), None)
        self.assertGreaterEqual(len(seen["cjk"]), 10, seen["cjk"])

    def test_other_birthdates_have_no_missing_glyphs(self):
        """閏月・臘月の生まれでも型Cが欠けない（不具合の再発防止の本体）"""
        from fortunelib.batch import build_calc_results
        from fortunelib.profile import normalize_input
        for (y, m, d) in LEAP_MONTH_DATES + LAST_MONTH_DATES:
            ni = normalize_input({
                "birth": {"date": f"{y:04d}-{m:02d}-{d:02d}", "time": "09:00",
                          "place": "東京都"},
                "gender": "F", "blood_type": "A",
                "name_kanji": "検証 花子", "name_kana": "けんしょう はなこ",
                "consultation": "検証",
            })
            R = build_calc_results(ni, consultation="検証")
            for slug in TYPEC_SLUGS:
                calc = _find_calc(R, slug)
                if not isinstance(calc, dict):
                    continue
                self.assertEqual(chartdraw.missing_glyphs_for(slug, calc, None),
                                 [], f"{y}-{m:02d}-{d:02d} {slug}")


class TestNayinCharsMts563(unittest.TestCase):
    """四柱推命の納音（白蝋金）も同じ理由で直した（蠟→蝋）

    同じ調査で **四柱推命（M17_bazi）の納音「白蠟金」**（庚辰・辛巳の日柱）が
    同梱フォントに無い「蠟」を使っており、型Cチャートで1文字欠けることを
    実測で確認しました（1995-12-15・2001-09-15 の生まれ）。日本語の表記
    「白蝋金」へ直しています。
    """

    def test_all_nayin_chars_are_drawable(self):
        from fortunelib.calc.bazi import NAYIN
        chars = sorted({ch for v in NAYIN.values() for ch in v})
        self.assertEqual(chartdraw.missing_glyphs(chars, "cjk"), [])
        self.assertEqual({NAYIN[("庚", "辰")], NAYIN[("辛", "巳")]}, {"白蝋金"})

    def test_bazi_chart_of_such_a_day_has_no_missing_glyphs(self):
        from fortunelib.batch import build_calc_results
        from fortunelib.profile import normalize_input
        for (y, m, d) in ((1995, 12, 15), (2001, 9, 15)):
            ni = normalize_input({
                "birth": {"date": f"{y:04d}-{m:02d}-{d:02d}", "time": "09:00",
                          "place": "東京都"},
                "gender": "F", "blood_type": "A",
                "name_kanji": "検証 花子", "name_kana": "けんしょう はなこ",
                "consultation": "検証",
            })
            R = build_calc_results(ni, consultation="検証")
            calc = _find_calc(R, "M17_bazi")
            self.assertIsNotNone(calc)
            self.assertEqual(chartdraw.missing_glyphs_for("M17_bazi", calc, None), [])
            # 直した字が**実際に描かれている**こと（旧暦の閏・臘）
            # ＝旧暦にその字が出る人物なら、描画側でも必ず拾えている
            zw = _find_calc(R, "M20_ziwei")
            drawn = chartdraw.drawn_chars("M20_ziwei", zw, None)["cjk"]
            lunar = str(zw.get("lunar_date", ""))
            for ch in ("閏", "臘"):
                if ch in lunar:
                    self.assertIn(ch, drawn, (y, m, d, lunar))


class TestMissingGlyphVisibilityMts563(unittest.TestCase):
    """欠けたら**実行の警告一覧**に出る（黙って欠けない）"""

    def setUp(self):
        runcheck.clear()
        self.addCleanup(runcheck.clear)

    def test_helper_records_a_warning(self):
        chartdraw._note_missing_glyphs(["闰", "腊"])
        self.assertTrue(any("同梱フォントに無く" in w for w in runcheck.WARNINGS),
                        runcheck.WARNINGS)
        self.assertIn("闰腊", runcheck.WARNINGS[0])
        # 同じ内容は畳まれる（描画のたびに増えない）
        chartdraw._note_missing_glyphs(["闰", "腊"])
        self.assertEqual(len(runcheck.WARNINGS), 1)

    def test_drawing_a_chart_with_a_missing_char_warns(self):
        """データ側に無い字が混ざったら（将来の別の字でも）台帳に残る"""
        import copy
        calc = copy.deepcopy(_find_calc(_calc_batch(_sample_person()), "M20_ziwei"))
        # 人物しだいで閏の有無が変わるため、**必ず欠ける字**（簡体字の 闰＝U+95F0）を足す
        calc["lunar_date"] = str(calc["lunar_date"]) + "闰"
        img, _cap = chartdraw.render_for_slug("M20_ziwei", calc, None)
        self.assertIsNotNone(img)
        self.assertTrue(any("同梱フォントに無く" in w for w in runcheck.WARNINGS),
                        runcheck.WARNINGS)

    def test_normal_drawing_adds_no_warning(self):
        calc = _find_calc(_calc_batch(_sample_person()), "M20_ziwei")
        chartdraw.render_for_slug("M20_ziwei", calc, None)
        self.assertEqual([w for w in runcheck.WARNINGS if "同梱フォント" in w], [])


if __name__ == "__main__":
    unittest.main()
