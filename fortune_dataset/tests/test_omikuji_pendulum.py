# -*- coding: utf-8 -*-
import unittest

from fortunelib.calc.omikuji import draw_omikuji, throw_astragaloi
from fortunelib.calc.pendulum import swing, throw_cowrie


class TestOmikuji(unittest.TestCase):
    """M28 おみくじ"""

    def test_level_valid(self):
        for _ in range(30):
            r = draw_omikuji(seed=1, mode="reproducible")
            self.assertIn(r["level"],
                          ["大大吉", "大吉", "中吉", "小吉", "半吉", "末吉", "吉",
                           "凶", "小凶", "半凶", "末凶", "大凶"])

    def test_seed_reproducible(self):
        r1 = draw_omikuji(seed=5, mode="reproducible")
        r2 = draw_omikuji(seed=5, mode="reproducible")
        self.assertEqual(r1["level"], r2["level"])

    def test_weights(self):
        # 大凶に重みをつけると大凶が出やすくなる
        levels = ["大大吉", "大吉", "中吉", "小吉", "半吉", "末吉", "吉",
                  "凶", "小凶", "半凶", "末凶", "大凶"]
        weights = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1000]
        r = draw_omikuji(seed=3, weights=weights, mode="reproducible")
        self.assertEqual(r["level"], "大凶")


class TestAstragaloi(unittest.TestCase):
    """M28 籤占（アストラガロイ）"""

    def test_throws(self):
        r = throw_astragaloi(seed=1, mode="reproducible")
        self.assertEqual(len(r["throws"]), 5)
        for v in r["throws"]:
            self.assertIn(v, (1, 3, 4, 6))

    def test_total(self):
        r = throw_astragaloi(seed=2, mode="reproducible")
        self.assertEqual(r["total"], sum(r["throws"]))

    def test_judgment(self):
        r = throw_astragaloi(seed=3, mode="reproducible")
        self.assertIn(r["judgment"], ["犬の目（最悪の目）", "アフロディーテの目（最上の目）", "通常の目"])

    def test_reproducible(self):
        r1 = throw_astragaloi(seed=9, mode="reproducible")
        r2 = throw_astragaloi(seed=9, mode="reproducible")
        self.assertEqual(r1["throws"], r2["throws"])


class TestPendulum(unittest.TestCase):
    """M29 ペンデュラム"""

    def test_answer_valid(self):
        for _ in range(30):
            r = swing(seed=1, mode="reproducible")
            self.assertIn(r["answer"], ("yes", "no", "neutral"))

    def test_reproducible(self):
        r1 = swing(seed=7, mode="reproducible")
        r2 = swing(seed=7, mode="reproducible")
        self.assertEqual(r1["answer"], r2["answer"])


class TestCowrie(unittest.TestCase):
    """M29 アフリカ占い（貝殻）"""

    def test_structure(self):
        r = throw_cowrie(seed=1, mode="reproducible")
        self.assertEqual(len(r["shells"]), 8)
        self.assertEqual(r["open_count"], sum(r["shells"]))
        self.assertIn(r["pattern_id"], range(0, 256))

    def test_pattern_total(self):
        r = throw_cowrie(seed=2, mode="reproducible")
        self.assertEqual(r["pattern_total"], 256)

    def test_reproducible(self):
        r1 = throw_cowrie(seed=11, mode="reproducible")
        r2 = throw_cowrie(seed=11, mode="reproducible")
        self.assertEqual(r1["pattern_id"], r2["pattern_id"])


if __name__ == "__main__":
    unittest.main()
