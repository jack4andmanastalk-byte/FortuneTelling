# -*- coding: utf-8 -*-
import unittest
from datetime import date

from fortunelib.calc.jieqi import lichun_date, effective_year_for_lichun, jieqi_name_on


class TestJieqi(unittest.TestCase):
    """節気・立春判定（sxtwl 委譲）"""

    def test_lichun_1990(self):
        self.assertEqual(lichun_date(1990), date(1990, 2, 4))

    def test_lichun_2026(self):
        self.assertEqual(lichun_date(2026), date(2026, 2, 4))

    def test_lichun_variation(self):
        # 立春は年により2/3〜2/5の間
        for y in range(2000, 2030):
            lc = lichun_date(y)
            self.assertIn(lc.month, (2,))
            self.assertIn(lc.day, (3, 4, 5))

    def test_jieqi_name(self):
        self.assertEqual(jieqi_name_on(date(2026, 2, 4)), "立春")
        self.assertEqual(jieqi_name_on(date(1990, 1, 20)), "大寒")
        self.assertIsNone(jieqi_name_on(date(2026, 2, 5)))

    def test_effective_year(self):
        # 立春前（2/3）は前年扱い
        self.assertEqual(effective_year_for_lichun(date(2026, 2, 3)), 2025)
        self.assertEqual(effective_year_for_lichun(date(2026, 2, 4)), 2026)
        self.assertEqual(effective_year_for_lichun(date(1990, 1, 15)), 1989)
        self.assertEqual(effective_year_for_lichun(date(1990, 12, 31)), 1990)


if __name__ == "__main__":
    unittest.main()
