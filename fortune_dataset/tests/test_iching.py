# -*- coding: utf-8 -*-
import unittest

from fortunelib.calc.iching import cast, coin_throw, yarrow_throw, lines_to_hexagram
from fortunelib.rng import FortuneRNG


class TestIching(unittest.TestCase):
    """M26 易"""

    def test_manual_all_yang(self):
        """全部7（少陽）→ 乾為天・動爻なし"""
        r = cast(manual=[7, 7, 7, 7, 7, 7])
        self.assertEqual(r["ben_hexagram"]["name_ja"], "乾為天")
        self.assertEqual(r["moving"], [])
        self.assertEqual(r["derived_hexagram"]["name_ja"], "乾為天")

    def test_manual_all_yin(self):
        """全部8（少陰）→ 坤為地"""
        r = cast(manual=[8, 8, 8, 8, 8, 8])
        self.assertEqual(r["ben_hexagram"]["name_ja"], "坤為地")

    def test_manual_moving(self):
        """全部9（老陽）→ 乾為天・之卦は坤為地・動爻は1-6全部"""
        r = cast(manual=[9, 9, 9, 9, 9, 9])
        self.assertEqual(r["ben_hexagram"]["name_ja"], "乾為天")
        self.assertEqual(r["derived_hexagram"]["name_ja"], "坤為地")
        self.assertEqual(r["moving"], [1, 2, 3, 4, 5, 6])

    def test_manual_specific(self):
        """下=震(1,0,0: 7,8,8) 上=坎(0,1,0: 8,7,8) → 水雷屯"""
        r = cast(manual=[7, 8, 8, 8, 7, 8])
        self.assertEqual(r["ben_hexagram"]["name_ja"], "水雷屯")

    def test_coin_throw_values(self):
        rng = FortuneRNG(seed=1)
        for _ in range(20):
            yao = coin_throw(rng)
            self.assertEqual(len(yao), 6)
            for v in yao:
                self.assertIn(v, (6, 7, 8, 9))

    def test_yarrow_throw_values(self):
        rng = FortuneRNG(seed=2)
        for _ in range(10):
            yao = yarrow_throw(rng)
            self.assertEqual(len(yao), 6)
            for v in yao:
                self.assertIn(v, (6, 7, 8, 9))

    def test_seed_reproducible(self):
        r1 = cast(method="coin", seed=42, mode="reproducible")
        r2 = cast(method="coin", seed=42, mode="reproducible")
        self.assertEqual(r1["yao"], r2["yao"])
        self.assertEqual(r1["ben_hexagram"]["name_ja"], r2["ben_hexagram"]["name_ja"])

    def test_lines_to_hexagram(self):
        # 乾=111（下3）・坤=000（上3）→ 地天泰 (11)
        info = lines_to_hexagram([1, 1, 1, 0, 0, 0])
        self.assertEqual(info["name_ja"], "地天泰")

    def test_invalid_manual(self):
        with self.assertRaises(ValueError):
            cast(manual=[7, 7, 7, 7, 7])


if __name__ == "__main__":
    unittest.main()
