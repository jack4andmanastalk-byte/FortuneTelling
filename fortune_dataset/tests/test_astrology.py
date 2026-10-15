# -*- coding: utf-8 -*-
import unittest

from fortunelib.calc.astrology import (
    to_jd, planet_longitudes, houses, aspects, natal_chart,
    transit_chart, vedic_sidereal, human_design,
)


class TestAstrology(unittest.TestCase):
    """西洋占星術（pyswisseph）"""

    @classmethod
    def setUpClass(cls):
        cls.chart = natal_chart(1990, 1, 15, 12.0, 35.6895, 139.6917)

    def test_planets_count(self):
        self.assertEqual(len(self.chart["planets"]), 10)

    def test_sun_capricorn(self):
        # 1990-01-15 の太陽は山羊座（境界 1/20 前）
        self.assertEqual(self.chart["planets"]["太陽"]["sign"], "山羊座")

    def test_lon_range(self):
        for name, p in self.chart["planets"].items():
            self.assertGreaterEqual(p["lon"], 0)
            self.assertLess(p["lon"], 360)

    def test_houses(self):
        self.assertEqual(len(self.chart["houses"]["cusps"]), 12)
        asc = self.chart["houses"]["asc"]
        self.assertGreaterEqual(asc, 0)
        self.assertLess(asc, 360)

    def test_aspects_structure(self):
        for a in self.chart["aspects"]:
            self.assertIn("aspect", a)
            self.assertIn("p1", a)
            self.assertIn("orb", a)
            self.assertLessEqual(a["orb"], 8.0)

    def test_transit(self):
        t = transit_chart(self.chart)
        self.assertEqual(len(t["transit_planets"]), 10)
        self.assertIn("aspects_to_natal", t)

    def test_vedic(self):
        v = vedic_sidereal(to_jd(1990, 1, 15, 12.0))
        self.assertIn("ayanamsa", v)
        self.assertIn("lagna", v)
        self.assertEqual(len(v["planets"]), 10)
        for name, p in v["planets"].items():
            self.assertIn("nakshatra", p)

    def test_human_design(self):
        hd = human_design(1990, 1, 15, 12.0, 35.6895, 139.6917)
        self.assertIn("sun", hd)
        self.assertIn("earth", hd)
        gate = hd["sun"]["gate"]
        self.assertGreaterEqual(gate, 1)
        self.assertLessEqual(gate, 64)
        line = hd["sun"]["line"]
        self.assertGreaterEqual(line, 1)
        self.assertLessEqual(line, 6)


if __name__ == "__main__":
    unittest.main()
