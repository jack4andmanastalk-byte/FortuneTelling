# -*- coding: utf-8 -*-
import unittest

from fortunelib.validate import (
    validate_output, char_count, japanese_ratio, check_format,
)

GOOD = (
    "あなたは静かな力強い性質を持ち、物事を着実に進める傾向があります。"
    "今年はこれまでの努力が形になり始める時期です。"
    "焦らず、一歩ずつ歩むことが大切でしょう。"
)


class TestValidate(unittest.TestCase):
    """出力バリデーション"""

    def test_good_text(self):
        issues = validate_output(GOOD, min_chars=10, max_chars=200)
        self.assertEqual(issues, [])

    def test_too_short(self):
        issues = validate_output("短い", min_chars=100, max_chars=200)
        self.assertTrue(any("文字数" in i for i in issues))

    def test_too_long(self):
        issues = validate_output(GOOD * 10, min_chars=10, max_chars=100)
        self.assertTrue(any("文字数" in i for i in issues))

    def test_forbidden_words(self):
        """単純禁止語（文脈によらず違反）"""
        for w in ["※", "占いです", "当たる"]:
            issues = validate_output(f"これは{GOOD}{w}", min_chars=1, max_chars=500)
            self.assertTrue(any("禁止語句" in i and w in i for i in issues), w)

    def test_forbidden_assertive_patterns(self):
        """断定表現は述語と結びつく場合のみ違反（BUG-06）

        「静かに、しかし確実に」のような副詞用法まで拾わないよう、
        FORBIDDEN_PATTERNS で文脈を限定している。
        """
        for phrase in ["絶対に", "必ず成功します", "確実に叶います"]:
            issues = validate_output(f"{GOOD}あなたには{phrase}", min_chars=1, max_chars=500)
            self.assertTrue(any("禁止語句" in i for i in issues), phrase)

    def test_adverbial_confident_use_allowed(self):
        """副詞用法（断定的予言ではない）は許容する"""
        text = GOOD + "静かに、しかし確実に前へ進む姿勢が大切です。"
        issues = validate_output(text, min_chars=1, max_chars=500)
        self.assertFalse([i for i in issues if "禁止語句" in i])

    def test_markdown_heading(self):
        issues = validate_output("# 見出し\n" + GOOD, min_chars=1, max_chars=500)
        self.assertTrue(any("見出し" in i for i in issues))

    def test_table(self):
        issues = validate_output("| a | b |\n" + GOOD, min_chars=1, max_chars=500)
        self.assertTrue(any("テーブル" in i for i in issues))

    def test_codeblock(self):
        issues = validate_output("```python\nx=1\n```\n" + GOOD, min_chars=1, max_chars=500)
        self.assertTrue(any("コードブロック" in i for i in issues))

    def test_low_japanese_ratio(self):
        issues = validate_output("Hello world this is English text only.", min_chars=1, max_chars=500)
        self.assertTrue(any("日本語率" in i for i in issues))

    def test_must_mention(self):
        text = "あなたの本命星は二黒土星です。"
        issues = validate_output(text, min_chars=1, max_chars=500,
                                 must_mention=["二黒土星", "丙午"])
        self.assertEqual(issues, [])
        issues2 = validate_output(text, min_chars=1, max_chars=500,
                                  must_mention=["ライフパス9"])
        self.assertTrue(any("織り込まれていない" in i for i in issues2))

    def test_char_count(self):
        self.assertEqual(char_count("  あいうえお  "), 5)

    def test_japanese_ratio(self):
        self.assertGreater(japanese_ratio("日本語の文章です。"), 0.8)
        self.assertLess(japanese_ratio("English text"), 0.1)


if __name__ == "__main__":
    unittest.main()
