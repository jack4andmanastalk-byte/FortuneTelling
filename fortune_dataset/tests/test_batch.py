# -*- coding: utf-8 -*-
import unittest
from datetime import datetime, timezone, timedelta

from fortunelib.batch import build_profile_facts, build_calc_results, resolve_place

from tests.fixtures.consultation import CONSULTATION, CONSULTATION_ALT
from fortunelib.profile import normalize_input
from fortunelib.registry import REGISTRY

JST = timezone(timedelta(hours=9))

RAW = {
    "birth": {"date": "1990-01-15", "time": "14:30", "place": "千葉県"},
    "gender": "M", "blood_type": "A",
    "name_kanji": "山田 太郎", "name_kana": "やまだ たろう",
    "partner": {"date": "1991-07-03", "time": "", "place": ""},
    "consultation": CONSULTATION,
}
FIXED_NOW = datetime(2026, 8, 15, 12, 0, tzinfo=JST)


class TestResolvePlace(unittest.TestCase):
    """都道府県座標解決"""

    def test_chiba(self):
        lat, lon, note = resolve_place(normalize_input(RAW).birth)
        self.assertAlmostEqual(lat, 35.605, places=2)
        self.assertAlmostEqual(lon, 140.123, places=2)
        self.assertEqual(note, "")

    def test_tokyo_unknown(self):
        ni = normalize_input({"birth": {"date": "1990-01-15", "time": "", "place": ""}})
        lat, lon, note = resolve_place(ni.birth)
        self.assertAlmostEqual(lat, 35.6895, places=3)
        self.assertIn("東京扱い", note)

    def test_unknown_place_fallback(self):
        ni = normalize_input({"birth": {"date": "1990-01-15", "time": "", "place": "パリ"}})
        lat, lon, note = resolve_place(ni.birth)
        self.assertAlmostEqual(lat, 35.6895, places=3)
        self.assertIn("東京扱い", note)


class TestProfileFacts(unittest.TestCase):
    """プロファイル事実"""

    def test_keys(self):
        ni = normalize_input(RAW)
        facts = build_profile_facts(ni)
        self.assertEqual(facts["太陽星座"], "山羊座")
        self.assertEqual(facts["干支（年柱・立春基準）"], "己巳")  # 1990-01-15 は立春前
        self.assertEqual(facts["九星気学（本命星）"], "二黒土星")
        self.assertEqual(facts["数秘術（ライフパス）"], 8)
        self.assertEqual(facts["血液型"], "A型")
        self.assertEqual(facts["氏名（ヘボン式）"], "YAMADA TARO")
        self.assertEqual(facts["氏名（漢字）"], "山田 太郎")
        self.assertEqual(facts["氏名（かな）"], "やまだ たろう")
        self.assertIn("相手の生年月日", facts)


class TestCalcResults(unittest.TestCase):
    """計算バッチ（全 calc_key の生成・再現性）"""

    @classmethod
    def setUpClass(cls):
        cls.ni = normalize_input(RAW)
        cls.results = build_calc_results(cls.ni, session_id="test",
                                         consultation=CONSULTATION,
                                         now=FIXED_NOW, rng_mode="reproducible")

    def test_all_registry_keys_present(self):
        registry_keys = {e["calc_key"] for e in REGISTRY.values() if e["calc_key"]}
        missing = registry_keys - set(self.results.keys())
        self.assertEqual(missing, set(), f"未生成のcalc_key: {missing}")

    def test_no_error_for_core(self):
        # 主要な計算はエラーなく完了している
        for key in ("zodiac", "eto", "kyusei", "numerology_birth", "weton",
                    "bazi", "western", "vedic", "ziwei", "hd",
                    "tarot", "iching", "omikuji", "synastry", "pendulum",
                    "cowrie", "astragaloi", "kabbalah", "chaldean", "seimei"):
            self.assertNotIn("error", self.results[key], key)

    def test_bazi_1990(self):
        r = self.results["bazi"]
        self.assertEqual(r["pillars"]["year"], "己巳")
        self.assertEqual(r["pillars"]["day"], "庚辰")

    def test_ziwei_gender(self):
        r = self.results["ziwei"]
        self.assertEqual(len(r["palaces"]), 12)

    def test_synastry(self):
        r = self.results["synastry"]
        self.assertIn("aspects", r)
        self.assertIn("mine", r)
        self.assertIn("theirs", r)

    def test_reproducible_rng(self):
        r1 = build_calc_results(self.ni, session_id="s", consultation=CONSULTATION, now=FIXED_NOW, rng_mode="reproducible")
        r2 = build_calc_results(self.ni, session_id="s", consultation=CONSULTATION, now=FIXED_NOW, rng_mode="reproducible")
        self.assertEqual([c["name_ja"] for c in r1["tarot"]["cards"]],
                         [c["name_ja"] for c in r2["tarot"]["cards"]])
        self.assertEqual(r1["iching"]["yao"], r2["iching"]["yao"])
        self.assertEqual(r1["omikuji"]["level"], r2["omikuji"]["level"])

    def test_consultation_changes_rng(self):
        # 相談内容が変われば結果も変わる（どちらも400字前後の架空の相談文・mts5.62）
        r1 = build_calc_results(self.ni, session_id="s", consultation=CONSULTATION, now=FIXED_NOW, rng_mode="reproducible")
        r2 = build_calc_results(self.ni, session_id="s", consultation=CONSULTATION_ALT, now=FIXED_NOW, rng_mode="reproducible")
        self.assertNotEqual(r1["iching"]["yao"], r2["iching"]["yao"])

    def test_template_keys_flagged(self):
        # 確定後: テンプレートは残っていない（rokusei/primbon/parimichamは実データ化済み）
        for key in ("rokusei", "primbon", "parimicham"):
            self.assertEqual(self.results[key]["status"], "ok", key)

    def test_integrated_keys_ok(self):
        # 別AIデータ資産の取り込み後: animal / sanmei / seimei / hd は実データ（ok）
        for key in ("animal", "sanmei", "seimei", "hd"):
            self.assertEqual(self.results[key].get("status", "ok"), "ok", key)


if __name__ == "__main__":
    unittest.main()
