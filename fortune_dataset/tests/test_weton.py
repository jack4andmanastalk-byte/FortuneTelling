# -*- coding: utf-8 -*-
import unittest
from datetime import date

from fortunelib.calc.weton import pasaran, weton_name, weton_detail


class TestWeton(unittest.TestCase):
    """T11〜T13 ウェトン（パサラン暦）"""

    def test_1945_08_17_anchor(self):
        """T11: アンカー日 1945-08-17 = 金曜・Legi"""
        self.assertEqual(pasaran(date(1945, 8, 17)), "Legi")
        self.assertEqual(weton_name(date(1945, 8, 17)), "金曜・Legi")

    def test_1633_07_08(self):
        """T12: 学術論文の例 1633-07-08 = Legi"""
        self.assertEqual(pasaran(date(1633, 7, 8)), "Legi")

    def test_1968_12_03(self):
        """T13: MATLAB weton の例 1968-12-03 = 火曜・Kliwon"""
        self.assertEqual(weton_name(date(1968, 12, 3)), "火曜・Kliwon")
        self.assertEqual(pasaran(date(1968, 12, 3)), "Kliwon")

    def test_cycle5(self):
        # 5日周期の検証：5日後は同じパサラン
        d = date(1990, 1, 15)
        self.assertEqual(pasaran(d), pasaran(date(1990, 1, 20)))

    def test_detail(self):
        d = weton_detail(date(1945, 8, 17))
        self.assertEqual(d["weton_name"], "金曜・Legi")
        self.assertEqual(d["day_en"], "Friday")

    def test_all_35(self):
        # 7曜日 × 5パサラン = 35通りの組合せが過不足なく出現する
        import itertools
        combos = set()
        start = date(2026, 1, 1)
        for i in range(400):  # 400日あれば全35組合せが出現する
            combos.add((start.replace(year=start.year).toordinal() + i,))
        # 曜日×パサランの組合せを直接確認
        seen = set()
        d = date(2026, 1, 1)
        for _ in range(400):
            seen.add((d.weekday(), pasaran(d)))
            d = date.fromordinal(d.toordinal() + 1)
        self.assertEqual(len(seen), 35)


if __name__ == "__main__":
    unittest.main()
