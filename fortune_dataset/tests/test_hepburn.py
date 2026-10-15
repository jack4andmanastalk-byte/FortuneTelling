# -*- coding: utf-8 -*-
import unittest

from fortunelib.hepburn import kana_to_hepburn


class TestHepburn(unittest.TestCase):
    """ヘボン式（パスポート式）変換（仕様設計メモ §3.3 / プロンプト設計書付録A）"""

    def test_yamada_taro(self):
        self.assertEqual(kana_to_hepburn("やまだたろう"), "YAMADATARO")

    def test_yamada_taro_space(self):
        self.assertEqual(kana_to_hepburn("やまだ たろう"), "YAMADA TARO")

    def test_tokyo(self):
        """とうきょう → TOKYO（長音正規化）"""
        self.assertEqual(kana_to_hepburn("とうきょう"), "TOKYO")

    def test_gakko(self):
        """がっこう → GAKKO（促音＋長音）"""
        self.assertEqual(kana_to_hepburn("がっこう"), "GAKKO")

    def test_shinjuku(self):
        """しんじゅく → SHINJUKU（拗音＋ん）"""
        self.assertEqual(kana_to_hepburn("しんじゅく"), "SHINJUKU")

    def test_nihon(self):
        self.assertEqual(kana_to_hepburn("にほん"), "NIHON")

    def test_fuji(self):
        self.assertEqual(kana_to_hepburn("ふじ"), "FUJI")

    def test_katakana(self):
        self.assertEqual(kana_to_hepburn("タロウ"), "TARO")
        self.assertEqual(kana_to_hepburn("チャン"), "CHAN")

    def test_osaka(self):
        """おおさか → OSAKA（長音正規化）"""
        self.assertEqual(kana_to_hepburn("おおさか"), "OSAKA")

    def test_kyoto(self):
        """きょうと → KYOTO（拗音＋長音）"""
        self.assertEqual(kana_to_hepburn("きょうと"), "KYOTO")

    def test_sato(self):
        """さとう → SATO（長音）"""
        self.assertEqual(kana_to_hepburn("さとう"), "SATO")

    def test_ikeda(self):
        """いけだ → IKEDA（えい→E の対象外ケース確認）"""
        self.assertEqual(kana_to_hepburn("いけだ"), "IKEDA")


if __name__ == "__main__":
    unittest.main()
