# -*- coding: utf-8 -*-
"""[要検証]データ確定分のテスト（六星・プリンボン・パリミチャム・ジーンキーズ・日命星）"""
import unittest
from datetime import date

from fortunelib.calc.rokusei import rokusei_calc, year_unnsu, cycle_for_year
from fortunelib.calc.primbon import primbon_calc, neptu_of
from fortunelib.calc.parimicham import parimicham_calc


class TestRokuseiDetermined(unittest.TestCase):
    """六星占術（確定・masanosuke.net照合）"""

    def test_public_examples(self):
        cases = [
            (1990, 8, 15, 53, "水星人", "プラス"),
            (1998, 5, 20, 19, "金星人", "プラス"),
            (2004, 8, 28, 40, "天王星人", "プラス"),
        ]
        for y, m, d, exp_no, exp_star, exp_pm in cases:
            r = rokusei_calc(y, m, d)
            self.assertEqual(r["unmei_number"], exp_no)
            self.assertEqual(r["star"], exp_star)
            self.assertEqual(r["plus_minus"], exp_pm)

    def test_daissakai_2026(self):
        """2026年の大殺界3タイプ（masanosuke.net）"""
        for ftype in ("火星人プラス", "火星人マイナス", "天王星人マイナス"):
            self.assertTrue(cycle_for_year(ftype, 2026)["is_daissakai"], ftype)
        for ftype in ("水星人プラス", "土星人プラス", "金星人プラス"):
            self.assertFalse(cycle_for_year(ftype, 2026)["is_daissakai"], ftype)

    def test_year_unnsu_outside_rule(self):
        self.assertEqual(year_unnsu(1959), 4)
        self.assertEqual(year_unnsu(2005), 6)


class TestPrimbonDetermined(unittest.TestCase):
    """プリンボン・ジャワ（確定・ネプツヌ体系）"""

    def test_neptu_1990_01_15(self):
        """1990-01-15 = 月曜・Pon → ネプツヌ 4+7=11"""
        n = neptu_of(date(1990, 1, 15))
        self.assertEqual(n["weton"], "月曜・Pon")
        self.assertEqual(n["neptu_total"], 11)

    def test_primbon_calc(self):
        r = primbon_calc(date(1990, 1, 15))
        self.assertIn("neptu_profile", r)
        self.assertIn("pasaran_profile", r)
        self.assertIn("individual_profile", r)
        # 月曜・Pon は個別プロファイル収録済み
        self.assertTrue(r["has_individual"])

    def test_neptu_range(self):
        """ネプツヌは7〜21の範囲（曜日3〜9 + パサラン4〜9）"""
        for d in [date(2026, 1, 1), date(2026, 6, 15), date(2026, 12, 31)]:
            n = neptu_of(d)
            self.assertGreaterEqual(n["neptu_total"], 7)
            self.assertLessEqual(n["neptu_total"], 21)


class TestParimichamDetermined(unittest.TestCase):
    """パリミチャム（確定・タミルPorutham簡易）"""

    def test_calc_structure(self):
        r = parimicham_calc({"date": "1990-01-15"}, {"date": "1991-07-03"})
        self.assertIn("本人", r)
        self.assertIn("相手", r)
        self.assertIn("nakshatra_count", r)
        self.assertIn("verdict", r)
        self.assertIn("checks", r)
        # ナクシャトラが正しく計算される（1990-01-15 月=プールヴァ・ファルグニー）
        self.assertEqual(r["本人"]["nakshatra"], "プールヴァ・ファルグニー")

    def test_dina_count(self):
        """ナクシャトラ数えは1〜27"""
        r = parimicham_calc({"date": "1990-01-15"}, {"date": "1990-02-15"})
        self.assertIn(r["nakshatra_count"], range(1, 28))

    def test_same_nakshatra_ng(self):
        """禁忌ナクシャトラの定義を確認"""
        from fortunelib.calc.parimicham import SAME_NIYAZHA
        self.assertIn("ムーラ", SAME_NIYAZHA)
        self.assertIn("バラニー", SAME_NIYAZHA)


class TestGenekeysDetermined(unittest.TestCase):
    """ジーンキーズ（確定・簡易版）"""

    def test_data_64(self):
        from fortunelib.data import load_json
        d = load_json("genekeys_64.json")
        self.assertEqual(len(d["keys"]), 64)
        self.assertEqual(d["keys"][0]["gate"], 1)
        self.assertEqual(d["keys"][-1]["gate"], 64)


class TestKyuseiDayDetermined(unittest.TestCase):
    """日命星（確定・甲子起算方式）"""

    def test_method_in_batch(self):
        from fortunelib.batch import build_calc_results
        from fortunelib.profile import normalize_input
        from datetime import datetime, timezone, timedelta
        JST = timezone(timedelta(hours=9))
        RAW = {"birth": {"date": "1990-01-15", "time": "", "place": ""}}
        ni = normalize_input(RAW)
        R = build_calc_results(ni, session_id="x", consultation="", now=datetime(2026, 8, 15, 12, 0, tzinfo=JST))
        r = R["target_kyusei_day"]
        self.assertIn("method", r)
        self.assertIn("甲子起算方式", r["method"])
        self.assertIn("day_star", r)


if __name__ == "__main__":
    unittest.main()
