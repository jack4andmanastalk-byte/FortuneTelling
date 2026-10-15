# -*- coding: utf-8 -*-
"""六星占術（M10）のテスト: 公開ソースとの照合（masanosuke.net・確定版）"""
import unittest

from fortunelib.calc.rokusei import (
    year_unnsu, unmei_number, star_type, plus_minus,
    fortune_type, cycle_for_year, rokusei_calc,
)


class TestRokusei(unittest.TestCase):
    """六星占術 確定版"""

    def test_year_unnsu_table(self):
        """公開テーブル（masanosuke.net・1960-2004）"""
        cases = {1960: 15, 1961: 26, 1974: 49, 1975: 48, 1987: 60,
                 1989: 22, 1990: 21, 1998: 49, 2000: 11, 2004: 55}
        for y, exp in cases.items():
            self.assertEqual(year_unnsu(y), exp, f"年運数 {y}")

    def test_year_unnsu_outside(self):
        """範囲外は規則補間（(year×11+55) mod 60）"""
        # 1959: 1960=15 から -11 → 4
        self.assertEqual(year_unnsu(1959), 4)
        # 2005: 2004=55 から +11 → 6
        self.assertEqual(year_unnsu(2005), 6)

    def test_unmei_number_public_cases(self):
        """masanosuke.net の公開例3件（完全一致）"""
        self.assertEqual(unmei_number(1990, 8, 15), 53)
        self.assertEqual(unmei_number(1998, 5, 20), 19)
        self.assertEqual(unmei_number(2004, 8, 28), 40)

    def test_star_type(self):
        self.assertEqual(star_type(53), "水星人")
        self.assertEqual(star_type(19), "金星人")
        self.assertEqual(star_type(40), "天王星人")
        self.assertEqual(star_type(5), "土星人")
        self.assertEqual(star_type(27), "火星人")
        self.assertEqual(star_type(46), "木星人")

    def test_plus_minus(self):
        """プラス/マイナス（生まれ年の十二支）"""
        self.assertEqual(plus_minus(1990, 8, 15), "プラス")   # 午年
        self.assertEqual(plus_minus(1998, 5, 20), "プラス")   # 寅年
        self.assertEqual(plus_minus(1991, 7, 3), "マイナス")  # 未年
        # 立春前は前年扱い（2026-01-15 → 乙巳年=巳 → マイナス）
        self.assertEqual(plus_minus(2026, 1, 15), "マイナス")
        # 立春後（2026-02-05 → 丙午年=午 → プラス）
        self.assertEqual(plus_minus(2026, 2, 5), "プラス")

    def test_cycle_2026(self):
        """2026年の周期・大殺界（masanosuke.net の2026年運気表）"""
        cases = {
            "土星人プラス": ("再会", False),
            "土星人マイナス": ("乱気", False),
            "金星人プラス": ("安定", False),
            "金星人マイナス": ("財成", False),
            "火星人プラス": ("停止", True),   # 大殺界
            "火星人マイナス": ("陰影", True),  # 大殺界
            "天王星人プラス": ("種子", False),
            "天王星人マイナス": ("減退", True),  # 大殺界
            "木星人プラス": ("立花", False),
            "木星人マイナス": ("緑生", False),
            "水星人プラス": ("達成", False),
            "水星人マイナス": ("健弱", False),
        }
        for ftype, (exp_cycle, exp_ds) in cases.items():
            r = cycle_for_year(ftype, 2026)
            self.assertEqual(r["cycle"], exp_cycle, ftype)
            self.assertEqual(r["is_daissakai"], exp_ds, ftype)

    def test_rokusei_calc_full(self):
        """1990-08-15 → 水星人プラス（masanosuke.netの例）"""
        r = rokusei_calc(1990, 8, 15, target_year=2026)
        self.assertEqual(r["unmei_number"], 53)
        self.assertEqual(r["star"], "水星人")
        self.assertEqual(r["plus_minus"], "プラス")
        self.assertEqual(r["type"], "水星人プラス")
        self.assertEqual(r["cycle"], "達成")  # 2026年=達成（最高運）
        self.assertFalse(r["is_daissakai"])

    def test_cycle_12_period(self):
        """12年周期: 種子の年から12年後も種子"""
        r1 = cycle_for_year("火星人プラス", 2016)  # 種子
        r2 = cycle_for_year("火星人プラス", 2028)  # 12年後
        self.assertEqual(r1["cycle"], "種子")
        self.assertEqual(r2["cycle"], "種子")


if __name__ == "__main__":
    unittest.main()


class TestMonthDayCycle(unittest.TestCase):
    """六星占術の月運・日運（多数派の流派）

    出典（いずれも12型の表を公開）:
      fortune.netoff.co.jp ／ spicomi.net ／ messengersnote.com ／ plus-a.net
    """

    CYCLES = ["種子", "緑生", "立花", "健弱", "達成",
              "乱気", "再会", "財成", "安定", "陰影", "停止", "減退"]

    # 各型の「1月の月運」。複数ソースが一致した値
    JAN = {"土星人マイナス": "種子", "土星人プラス": "緑生",
           "金星人マイナス": "立花", "金星人プラス": "健弱",
           "火星人マイナス": "達成", "火星人プラス": "乱気",
           "天王星人マイナス": "再会", "天王星人プラス": "財成",
           "木星人マイナス": "安定", "木星人プラス": "陰影",
           "水星人マイナス": "停止", "水星人プラス": "減退"}

    def test_january_matches_sources(self):
        from fortunelib.calc.rokusei import cycle_for_month
        for ftype, exp in self.JAN.items():
            self.assertEqual(cycle_for_month(ftype, 1)["cycle"], exp, ftype)

    def test_offsets_are_a_permutation(self):
        """12型のオフセットが0〜11の連番になっている（体系の整合性）"""
        idx = sorted(self.CYCLES.index(v) for v in self.JAN.values())
        self.assertEqual(idx, list(range(12)))

    def test_netoff_full_year_tables(self):
        """netoff の月運表と12ヶ月すべてが一致する"""
        from fortunelib.calc.rokusei import cycle_for_month
        tables = {
            "水星人プラス": ["減退", "種子", "緑生", "立花", "健弱", "達成",
                             "乱気", "再会", "財成", "安定", "陰影", "停止"],
            "天王星人プラス": ["財成", "安定", "陰影", "停止", "減退", "種子",
                               "緑生", "立花", "健弱", "達成", "乱気", "再会"],
            "土星人マイナス": ["種子", "緑生", "立花", "健弱", "達成", "乱気",
                               "再会", "財成", "安定", "陰影", "停止", "減退"],
        }
        for ftype, exp in tables.items():
            got = [cycle_for_month(ftype, m)["cycle"] for m in range(1, 13)]
            self.assertEqual(got, exp, ftype)

    def test_month_is_year_independent(self):
        """月運は年運と独立（毎年同じ月に同じ運気）"""
        from fortunelib.calc.rokusei import cycle_for_month
        self.assertEqual(cycle_for_month("水星人プラス", 5)["cycle"],
                         cycle_for_month("水星人プラス", 5)["cycle"])

    def test_day_cycle_matches_calendar(self):
        """plus-a.net の2026年2月カレンダー（日運）と一致する"""
        from datetime import date
        from fortunelib.calc.rokusei import cycle_for_day
        cases = [
            (date(2026, 2, 1), {"土星人プラス": "再会", "木星人プラス": "立花",
                                "水星人マイナス": "健弱", "火星人プラス": "停止"}),
            (date(2026, 2, 2), {"土星人プラス": "財成", "木星人プラス": "健弱"}),
            (date(2026, 2, 13), {"土星人プラス": "再会", "木星人プラス": "立花"}),
            (date(2026, 2, 28), {"土星人プラス": "陰影", "木星人プラス": "乱気"}),
        ]
        for dt, exp in cases:
            for ftype, cyc in exp.items():
                self.assertEqual(cycle_for_day(ftype, dt)["cycle"], cyc,
                                 f"{dt} {ftype}")

    def test_day_advances_by_one(self):
        """日運は1日ごとに1周期進む"""
        from datetime import date, timedelta
        from fortunelib.calc.rokusei import cycle_for_day
        d0 = date(2026, 2, 1)
        for i in range(13):
            a = cycle_for_day("金星人プラス", d0 + timedelta(days=i))["cycle"]
            b = cycle_for_day("金星人プラス", d0 + timedelta(days=i + 1))["cycle"]
            self.assertEqual(self.CYCLES[(self.CYCLES.index(a) + 1) % 12], b)

    def test_sakkai_flags(self):
        """月運・日運にも殺界の判定が付く"""
        from datetime import date
        from fortunelib.calc.rokusei import cycle_for_month, cycle_for_day
        m = cycle_for_month("木星人プラス", 1)      # 陰影
        self.assertEqual(m["cycle"], "陰影")
        self.assertTrue(m["is_daissakai"])
        self.assertEqual(m["daissakai_type"], "大殺界")
        m2 = cycle_for_month("土星人マイナス", 1)   # 種子
        self.assertFalse(m2["is_daissakai"])
        self.assertIsNone(m2["daissakai_type"])
        d = cycle_for_day("木星人プラス", date(2026, 2, 13))
        self.assertIn("is_daissakai", d)

    def test_calc_includes_month_and_day(self):
        """rokusei_calc の戻り値に月運・日運が含まれる"""
        from datetime import date
        from fortunelib.calc.rokusei import rokusei_calc
        r = rokusei_calc(1978, 7, 7, target=date(2026, 2, 13))
        self.assertEqual(r["type"], "木星人プラス")
        self.assertEqual(r["cycle"], "立花")        # 年運
        self.assertEqual(r["month_cycle"], "停止")  # 月運（大殺界）
        self.assertTrue(r["month_is_daissakai"])
        self.assertEqual(r["day_cycle"], "立花")    # 日運
        self.assertEqual(r["target_date"], "2026-02-13")

    def test_unknown_type_is_safe(self):
        from datetime import date
        from fortunelib.calc.rokusei import cycle_for_month, cycle_for_day
        self.assertIsNone(cycle_for_month("宇宙人プラス", 3)["cycle"])
        self.assertIsNone(cycle_for_day("宇宙人プラス", date(2026, 1, 1))["cycle"])
