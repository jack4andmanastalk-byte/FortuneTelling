# -*- coding: utf-8 -*-
import unittest
from datetime import date

from fortunelib.calc.eto import jikkan, junishi, year_ganzhi, year_ganzhi_detailed
from fortunelib.calc.zodiac import sun_sign, sun_sign_of, sun_sign_en
from fortunelib.calc.kyusei import honmei_no, honmei_name, honmei_detail


class TestEto(unittest.TestCase):
    """T01・T02 干支"""

    def test_1984_甲子(self):
        self.assertEqual(year_ganzhi(1984), "甲子")

    def test_1995_乙亥(self):
        self.assertEqual(year_ganzhi(1995), "乙亥")

    def test_2024_甲辰(self):
        self.assertEqual(year_ganzhi(2024), "甲辰")

    def test_2026_丙午(self):
        self.assertEqual(year_ganzhi(2026), "丙午")

    def test_detailed(self):
        d = year_ganzhi_detailed(2026)
        self.assertEqual(d["ganzhi"], "丙午")
        self.assertEqual(d["kan_yomi"], "ひのえ")
        self.assertEqual(d["animal"], "馬")

    def test_kan_shi_cycle(self):
        # 甲子（1984）から60年後は甲子に戻る
        self.assertEqual(year_ganzhi(1984), year_ganzhi(2044))
        # 干支の60周期：十干10×十二支12
        self.assertEqual(len(set(year_ganzhi(y) for y in range(1984, 2044))), 60)


class TestZodiac(unittest.TestCase):
    """M02 太陽星座（テーブル判定）"""

    def test_aries_start(self):
        self.assertEqual(sun_sign(3, 21), "牡羊座")

    def test_pisces_before(self):
        self.assertEqual(sun_sign(3, 20), "魚座")

    def test_1990_01_15_capricorn(self):
        self.assertEqual(sun_sign(1, 15), "山羊座")

    def test_leo_aug(self):
        self.assertEqual(sun_sign(8, 15), "獅子座")

    def test_sagittarius(self):
        self.assertEqual(sun_sign(12, 21), "射手座")

    def test_capricorn_dec22(self):
        self.assertEqual(sun_sign(12, 22), "山羊座")

    def test_of_date(self):
        self.assertEqual(sun_sign_of(date(1990, 1, 15)), "山羊座")

    def test_en(self):
        self.assertEqual(sun_sign_en(8, 15), "Leo")

    def test_all_dates(self):
        # 全12星座が1年に1回ずつ現れる（境界は簡易テーブルのため連続性のみ確認）
        signs = [sun_sign(m, 15) for m in range(1, 13)]
        self.assertEqual(len(set(signs)), 12)


class TestKyusei(unittest.TestCase):
    """T04〜T06 九星気学（本命星）"""

    def test_1980_nikoku(self):
        self.assertEqual(honmei_no(1980), 2)
        self.assertEqual(honmei_name(1980), "二黒土星")

    def test_2020_shichiseki(self):
        self.assertEqual(honmei_no(2020), 7)
        self.assertEqual(honmei_name(2020), "七赤金星")

    def test_2026_ippaku(self):
        self.assertEqual(honmei_no(2026), 1)
        self.assertEqual(honmei_name(2026), "一白水星")

    def test_range(self):
        for y in range(1900, 2100):
            n = honmei_no(y)
            self.assertIn(n, range(1, 10))

    def test_detail(self):
        d = honmei_detail(1980)
        self.assertEqual(d["honmei"], "二黒土星")


if __name__ == "__main__":
    unittest.main()
