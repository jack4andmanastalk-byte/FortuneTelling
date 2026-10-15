# -*- coding: utf-8 -*-
import unittest

from fortunelib.calc.meihua import numbers_to_hexagram, cast, numbers_from_time, numbers_from_text


class TestMeihua(unittest.TestCase):
    """M23 梅花易数"""

    def test_known_example(self):
        """34, 43 → 上卦=兌(34%8=2) 下卦=離(43%8=3) → 澤火革 (49)・動爻5"""
        r = numbers_to_hexagram(34, 43)
        self.assertEqual(r["upper_trigram"], "兌")
        self.assertEqual(r["lower_trigram"], "離")
        self.assertEqual(r["ben_hexagram"]["name_ja"], "澤火革")
        self.assertEqual(r["moving"], 5)
        # 動爻5（上卦）→ 体=下(離)・用=上(兌)
        self.assertEqual(r["body_trigram"]["name"], "離")
        self.assertEqual(r["function_trigram"]["name"], "兌")

    def test_moving_lower(self):
        """動爻が下卦(1-3) → 体=上・用=下"""
        r = numbers_to_hexagram(1, 1)  # 上=乾(1%8=1) 下=乾 → 乾為天・動爻=(1+1)%6=2
        self.assertEqual(r["moving"], 2)
        self.assertEqual(r["body_trigram"]["name"], "乾")
        self.assertEqual(r["function_trigram"]["name"], "乾")

    def test_moving_six(self):
        """(n1+n2)%6==0 → 動爻=6"""
        r = numbers_to_hexagram(6, 6)  # (6+6)%6=0 → 6
        self.assertEqual(r["moving"], 6)

    def test_zero_mod8(self):
        """n%8==0 → 坤"""
        r = numbers_to_hexagram(8, 16)
        self.assertEqual(r["upper_trigram"], "坤")
        self.assertEqual(r["lower_trigram"], "坤")

    def test_mutual_hexagram(self):
        r = numbers_to_hexagram(34, 43)
        self.assertIn("mutual_hexagram", r)
        self.assertIsNotNone(r["mutual_hexagram"]["kingwen_no"])

    def test_cast_manual(self):
        r = cast(numbers=[34, 43], source="manual")
        self.assertEqual(r["ben_hexagram"]["name_ja"], "澤火革")

    def test_cast_time(self):
        r = cast(source="time")
        self.assertIn("ben_hexagram", r)

    def test_cast_text(self):
        r = cast(source="text", text="今年の仕事運")
        self.assertIn("ben_hexagram", r)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            cast(numbers=[1], source="manual")
        with self.assertRaises(ValueError):
            cast(source="text", text="")
        with self.assertRaises(ValueError):
            cast(source="unknown")


if __name__ == "__main__":
    unittest.main()
