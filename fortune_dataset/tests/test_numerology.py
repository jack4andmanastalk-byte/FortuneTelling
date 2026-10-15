# -*- coding: utf-8 -*-
import unittest
from datetime import date

from fortunelib.calc.numerology import (
    digital_root, life_path, name_number_pythagorean,
    kabbalah_value, chaldean_value, letter_values_pythagorean,
)


class TestNumerology(unittest.TestCase):
    """T07・T08 数秘術（ライフパス）"""

    def test_1990_01_15(self):
        """T07: 1990-01-15 → 8"""
        self.assertEqual(life_path(date(1990, 1, 15)), 8)

    def test_2026_08_15(self):
        """2026-08-15 → 6（各桁合計 2+0+2+6+0+8+1+5=24 → 6）"""
        self.assertEqual(life_path(date(2026, 8, 15)), 6)

    def test_1991_01_01_master22(self):
        """マスターナンバー例: 1991-01-01 → 1+9+9+1+0+1+0+1=22（保持）"""
        self.assertEqual(life_path(date(1991, 1, 1)), 22)

    def test_digital_root_master(self):
        self.assertEqual(digital_root(11), 11)
        self.assertEqual(digital_root(22), 22)
        self.assertEqual(digital_root(33), 33)
        self.assertEqual(digital_root(26), 8)

    def test_digital_root_no_master(self):
        # keep_master=False なら 11 → 2 に還元
        self.assertEqual(digital_root(11, keep_master=False), 2)


class TestNameNumerology(unittest.TestCase):
    """氏名系数秘（ヘボン式ローマ字）"""

    def test_pythagorean_yamada_taro(self):
        """T10（カバラ方式A）: YAMADA TARO → 99 → 9"""
        self.assertEqual(letter_values_pythagorean("YAMADA TARO"), 36)  # 1-9巡回（BUG-08）
        self.assertEqual(name_number_pythagorean("YAMADA TARO"), 9)

    def test_kabbalah(self):
        """T10: カバラ方式Aはピタゴラス式と同じ値"""
        self.assertEqual(kabbalah_value("YAMADA TARO"), 9)

    def test_chaldean(self):
        """T09: YAMADA TARO → 26 → 8"""
        self.assertEqual(chaldean_value("YAMADA TARO"), 8)

    def test_ignore_non_alpha(self):
        self.assertEqual(letter_values_pythagorean("YAMADA-TARO"), 36)  # 記号は無視


if __name__ == "__main__":
    unittest.main()
