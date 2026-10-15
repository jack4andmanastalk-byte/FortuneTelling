# -*- coding: utf-8 -*-
import unittest

from fortunelib.rng import FortuneRNG, make_seed


class TestRNG(unittest.TestCase):
    """共通RNG"""

    def test_default_random(self):
        """クロスチェック決定: デフォルトはランダム（同一seedなしで毎回異なる）"""
        a = FortuneRNG()
        b = FortuneRNG()
        self.assertNotEqual([a.randint(1, 1000000) for _ in range(5)],
                            [b.randint(1, 1000000) for _ in range(5)])

    def test_reproducible_with_seed(self):
        a = FortuneRNG(seed=42, mode="reproducible")
        b = FortuneRNG(seed=42, mode="reproducible")
        self.assertEqual([a.randint(1, 100) for _ in range(10)],
                         [b.randint(1, 100) for _ in range(10)])

    def test_different_seed(self):
        a = FortuneRNG(seed=1)
        b = FortuneRNG(seed=2)
        self.assertNotEqual([a.randint(1, 1000000) for _ in range(5)],
                            [b.randint(1, 1000000) for _ in range(5)])

    def test_make_seed_stable(self):
        # 同一セッションID・相談内容・日時なら同一シード
        from datetime import datetime, timezone, timedelta
        JST = timezone(timedelta(hours=9))
        t = datetime(2026, 8, 15, 12, 0, tzinfo=JST)
        s1 = make_seed("sess1", "今年の運勢", when=t, salt="test")
        s2 = make_seed("sess1", "今年の運勢", when=t, salt="test")
        self.assertEqual(s1, s2)

    def test_make_seed_different(self):
        from datetime import datetime, timezone, timedelta
        JST = timezone(timedelta(hours=9))
        t = datetime(2026, 8, 15, 12, 0, tzinfo=JST)
        self.assertNotEqual(make_seed("a", "x", when=t), make_seed("a", "y", when=t))
        # 日時が違えばシードも変わる
        t2 = datetime(2026, 8, 15, 12, 1, tzinfo=JST)
        self.assertNotEqual(make_seed("a", "x", when=t), make_seed("a", "x", when=t2))

    def test_choice_choices_shuffle(self):
        rng = FortuneRNG(seed=7)
        self.assertIn(rng.choice([1, 2, 3]), [1, 2, 3])
        self.assertEqual(len(rng.choices(["a", "b"], k=5)), 5)
        seq = [1, 2, 3, 4]
        rng.shuffle(seq)
        self.assertEqual(sorted(seq), [1, 2, 3, 4])
        self.assertEqual(len(rng.sample(range(10), 3)), 3)


if __name__ == "__main__":
    unittest.main()
