# -*- coding: utf-8 -*-
import unittest

from fortunelib.calc.cards import draw


class TestCards(unittest.TestCase):
    """M27 カード系RNG"""

    def test_tarot_78(self):
        r = draw("tarot", count=3, spread="three", seed=1, mode="reproducible")
        self.assertEqual(r["deck"], "tarot")
        self.assertEqual(len(r["cards"]), 3)
        self.assertEqual(r["cards"][0]["position"], "過去")
        for c in r["cards"]:
            self.assertIn("upright", c)   # 正逆あり

    def test_tarot_celtic(self):
        r = draw("tarot", count=10, spread="celtic_cross", seed=2, mode="reproducible")
        self.assertEqual(len(r["cards"]), 10)
        self.assertEqual(r["cards"][-1]["position"], "最終結果")

    def test_lenormand_36(self):
        r = draw("lenormand", count=5, seed=3, mode="reproducible")
        self.assertEqual(len(r["cards"]), 5)
        for c in r["cards"]:
            self.assertNotIn("upright", c)  # 正逆なし

    def test_kipper_36(self):
        r = draw("kipper", count=5, seed=4, mode="reproducible")
        self.assertEqual(len(r["cards"]), 5)
        self.assertTrue(any("キッパー" in n for n in r["notes"]))

    def test_cartomancy_52(self):
        r = draw("cartomancy", count=5, seed=5, mode="reproducible")
        self.assertEqual(len(r["cards"]), 5)
        for c in r["cards"]:
            self.assertIn("suit_ja", c)
            self.assertIn("rank_meaning", c)

    def test_runes_24(self):
        r = draw("runes", count=3, seed=6, mode="reproducible")
        self.assertEqual(len(r["cards"]), 3)
        for c in r["cards"]:
            self.assertIn("meaning_ja", c)

    def test_seed_reproducible(self):
        r1 = draw("tarot", count=3, seed=99, mode="reproducible")
        r2 = draw("tarot", count=3, seed=99, mode="reproducible")
        self.assertEqual([c["name_ja"] for c in r1["cards"]],
                         [c["name_ja"] for c in r2["cards"]])
        self.assertEqual([c["upright"] for c in r1["cards"]],
                         [c["upright"] for c in r2["cards"]])

    def test_different_seed(self):
        r1 = draw("tarot", count=3, seed=100, mode="reproducible")
        r2 = draw("tarot", count=3, seed=101, mode="reproducible")
        # 完全一致はほぼない（稀に一致しうるため、カード列が異なることを確認）
        names1 = [c["name_ja"] for c in r1["cards"]]
        names2 = [c["name_ja"] for c in r2["cards"]]
        self.assertFalse(set(names1).isdisjoint(set(r2["cards"][0]["name_ja"])) and
                         names1 == names2)

    def test_no_duplicate(self):
        """同じデッキからcount枚ドローしたときに重複がない"""
        for deck in ("tarot", "lenormand", "kipper", "cartomancy", "runes"):
            r = draw(deck, count=min(5, 52), seed=10, mode="reproducible")
            names = [c["name_ja"] for c in r["cards"]]
            self.assertEqual(len(names), len(set(names)), deck)

    def test_invalid_deck(self):
        with self.assertRaises(ValueError):
            draw("unknown_deck", count=1)


if __name__ == "__main__":
    unittest.main()
