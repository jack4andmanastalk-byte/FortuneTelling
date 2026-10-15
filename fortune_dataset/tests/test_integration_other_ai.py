# -*- coding: utf-8 -*-
import unittest

from fortunelib.calc.doubutsu import doubutsu_number, is_leap, year_month_value
from fortunelib.calc.seimei import seimei_calc, strokes_of
from fortunelib.calc.sanmeigaku import human_star_chart, sanmeigaku_full, tenchusatsu
from fortunelib.calc.hd_full import degree_to_gate_line, calculate_chart


class TestDoubutsu(unittest.TestCase):
    """動物占い（別AI実装の数式・検証値の再現）"""

    def test_known_1980_03_10(self):
        self.assertEqual(doubutsu_number(1980, 3, 10), 19)  # さすらいの狼

    def test_known_2000_07_10(self):
        self.assertEqual(doubutsu_number(2000, 7, 10), 6)   # 愛にあふれるトラ

    def test_known_1995_04_25(self):
        # 【確定・公開ソース照合】
        # aoi-project.com 公式手順: 1995年4月=58 + 25日 = 83 → 60引いて 23
        # 4meee.com 早見表: 1995年の年×月値が全12ヶ月一致（28/59/27/58/28/59/29/60/31/1/32/2）
        # 23番 = 純粋無垢なひつじ（aoi-project 一覧と一致）
        # ※ 以前 spicomi の「18・傷つきやすいゾウ」と照合したのは誤読だった（確定済み）
        self.assertEqual(doubutsu_number(1995, 4, 25), 23)

    def test_year_month_table_1995(self):
        """4meee.com 公開早見表（1995年）との全12ヶ月照合"""
        expected = {1: 28, 2: 59, 3: 27, 4: 58, 5: 28, 6: 59,
                    7: 29, 8: 60, 9: 31, 10: 1, 11: 32, 12: 2}
        for m, exp in expected.items():
            got = year_month_value(1995, m)
            self.assertEqual(got if got != 0 else 60, exp, f"1995年{m}月")

    def test_range(self):
        for y in range(1950, 2030):
            for m in range(1, 13):
                n = doubutsu_number(y, m, 15)
                self.assertIn(n, range(1, 61))

    def test_leap(self):
        self.assertTrue(is_leap(2000))
        self.assertTrue(is_leap(2024))
        self.assertFalse(is_leap(1900))
        self.assertFalse(is_leap(2023))


class TestSeimei(unittest.TestCase):
    """姓名判断（統合画数辞書・約103,000字）"""

    def test_yamada_taro(self):
        r = seimei_calc("山田", "太郎")
        self.assertEqual(r["strokes"], {"姓": 8, "名": 13})  # 山=3 田=5 太=4 郎=9
        self.assertEqual(r["missing_chars"], [])
        self.assertEqual(r["five_grilles"]["総格"], 21)

    def test_strokes_of(self):
        self.assertEqual(strokes_of("山"), 3)
        self.assertEqual(strokes_of("田"), 5)
        self.assertEqual(strokes_of("海"), 9)  # 新字体（KANJIDIC2）

    def test_rare_kanji(self):
        # 人名用異体字（Unihan補完）
        self.assertIsNotNone(strokes_of("﨑"))
        self.assertIsNotNone(strokes_of("髙"))

    def test_unknown_char(self):
        # 「𠮷」（つちよし）はUnihan補完で6画として収録されていることを確認
        self.assertEqual(strokes_of("𠮷"), 6)


class TestSanmeigaku(unittest.TestCase):
    """算命学（別AI実装・高尾流・lmp.jp実機と17/17一致）"""

    def test_1980_03_10(self):
        s = human_star_chart(1980, 3, 10)
        self.assertEqual(s["陰占"]["年柱"], "庚申")
        self.assertEqual(s["中心星"], "調舒星")

    def test_tenchusatsu(self):
        t = tenchusatsu("丙午")
        self.assertEqual(t["天中殺"], ["寅", "卯"])
        self.assertEqual(t["旬"], "甲辰")

    def test_full_2000_08_16(self):
        full = sanmeigaku_full(2000, 8, 16)
        self.assertIn("天中殺", full)
        self.assertIn("大運", full)
        self.assertIn("中心星", full)

    def test_daiun(self):
        full = sanmeigaku_full(2000, 8, 16)
        self.assertGreaterEqual(len(full["大運"]), 5)


class TestHDFull(unittest.TestCase):
    """ヒューマンデザイン（本格版・human-design-py移植）"""

    def test_degree_to_gate(self):
        # 黄経0° → ゲート25（GATE_SEQUENCEの先頭）
        gate, line = degree_to_gate_line(0.0)
        self.assertEqual(gate, 25)
        self.assertIn(line, range(1, 7))

    def test_calculate_chart(self):
        r = calculate_chart(1988, 10, 9, 5, 30, utc_offset=-7)
        self.assertIn("type", r)
        self.assertIn("authority", r)
        self.assertIn("profile", r)
        self.assertIn("gates", r)
        self.assertGreaterEqual(len(r["gates"]), 10)  # 太陽・地球・月・惑星等

    def test_profile_format(self):
        r = calculate_chart(1990, 1, 15, 12, 0, utc_offset=9)
        self.assertRegex(r["profile"], r"^\d/\d$")


if __name__ == "__main__":
    unittest.main()
