# -*- coding: utf-8 -*-
import unittest
from datetime import date

from fortunelib.profile import normalize_input, to_dict
from fortunelib.schema import build_result

from tests.fixtures.consultation import CONSULTATION, CONSULTATION_ALT


class TestProfile(unittest.TestCase):
    """入力正規化・近似モード"""

    def test_full_input(self):
        raw = {
            "birth": {"date": "1990-01-15", "time": "14:30", "place": "千葉県"},
            "gender": "M",
            "blood_type": "A",
            "name_kanji": "山田 太郎",
            "name_kana": "やまだ たろう",
            "partner": {"date": "1991-07-03", "time": "", "place": ""},
            "consultation": CONSULTATION,
        }
        ni = normalize_input(raw)
        self.assertFalse(ni.birth.time_unknown)
        self.assertFalse(ni.birth.place_unknown)
        self.assertTrue(ni.partner.time_unknown)
        self.assertTrue(ni.partner.place_unknown)
        self.assertEqual(ni.name_romaji, "YAMADA TARO")
        self.assertEqual(ni.approx_flags, ["partner_time_unknown", "partner_place_unknown"])

    def test_min_input(self):
        """生年月日のみ → 近似モード（正午・東京）"""
        raw = {"birth": {"date": "1990-01-15", "time": "", "place": ""}}
        ni = normalize_input(raw)
        self.assertTrue(ni.birth.time_unknown)
        self.assertTrue(ni.birth.place_unknown)
        self.assertEqual(ni.birth.time, "12:00")
        self.assertEqual(ni.birth.place_name, "東京")
        self.assertEqual(ni.approx_flags, ["time_unknown", "place_unknown"])

    def test_blood_invalid(self):
        raw = {"birth": {"date": "1990-01-15"}, "blood_type": "x"}
        ni = normalize_input(raw)
        self.assertEqual(ni.blood_type, "unknown")

    def test_to_dict(self):
        raw = {"birth": {"date": "1990-01-15"}}
        ni = normalize_input(raw)
        d = to_dict(ni)
        self.assertEqual(d["birth"]["date"], "1990-01-15")
        self.assertEqual(d["birth"]["time"], "12:00")
        self.assertEqual(d["birth"]["place"]["name"], "東京")
        self.assertIn("time_unknown", d["approx_flags"])


class TestSchema(unittest.TestCase):
    """共通出力JSONスキーマ"""

    def test_build_result(self):
        r = build_result(
            module="M03",
            divination="九星気学",
            inputs={"birth": {"date": "1990-01-15"}},
            approx_flags=["time_unknown"],
            result={"honmei": "二黒土星"},
            references=["データ定義書 v1.0"],
            warnings=["出生時刻不明のため正午扱い"],
        )
        self.assertEqual(r["module"], "M03")
        self.assertEqual(r["result"]["honmei"], "二黒土星")
        self.assertIn("generated_at", r)
        self.assertIn("schema_version", r)
        self.assertEqual(r["approx_flags"], ["time_unknown"])


if __name__ == "__main__":
    unittest.main()
