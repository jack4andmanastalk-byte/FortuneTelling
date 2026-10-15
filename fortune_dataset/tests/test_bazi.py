# -*- coding: utf-8 -*-
import unittest

from fortunelib.calc.bazi import (
    shishen, shier_yun, nayin, kubo, bazi_paipan, _hour_index,
)


class TestShishen(unittest.TestCase):
    """十神（日干 vs 他干）"""

    def test_same_gan(self):
        self.assertEqual(shishen("甲", "甲"), "比肩")
        self.assertEqual(shishen("甲", "乙"), "劫財")

    def test_sheng(self):
        # 甲(木) が生む: 丙(火・陽)=食神, 丁(火・陰)=傷官
        self.assertEqual(shishen("甲", "丙"), "食神")
        self.assertEqual(shishen("甲", "丁"), "傷官")

    def test_ke(self):
        # 甲(木) が克つ: 戊(土・陽)=偏財, 己(土・陰)=正財
        self.assertEqual(shishen("甲", "戊"), "偏財")
        self.assertEqual(shishen("甲", "己"), "正財")

    def test_sheng_me(self):
        # 甲を生む: 壬(水・陽)=偏印, 癸(水・陰)=正印
        self.assertEqual(shishen("甲", "壬"), "偏印")
        self.assertEqual(shishen("甲", "癸"), "正印")

    def test_ke_me(self):
        # 甲を克す: 庚(金・陽)=七殺, 辛(金・陰)=正官
        self.assertEqual(shishen("甲", "庚"), "七殺")
        self.assertEqual(shishen("甲", "辛"), "正官")

    def test_yin_day_master(self):
        self.assertEqual(shishen("乙", "甲"), "劫財")
        self.assertEqual(shishen("乙", "丙"), "傷官")


class TestShierYun(unittest.TestCase):
    """十二運（日干 vs 地支）"""

    def test_jia(self):
        # 甲(陽木): 長生=亥(11), 沐浴=子(0), 冠帯=丑(1), 建禄=寅(2), 帝旺=卯(3)
        self.assertEqual(shier_yun("甲", "亥"), "長生")
        self.assertEqual(shier_yun("甲", "子"), "沐浴")
        self.assertEqual(shier_yun("甲", "丑"), "冠帯")
        self.assertEqual(shier_yun("甲", "寅"), "建禄")
        self.assertEqual(shier_yun("甲", "卯"), "帝旺")
        self.assertEqual(shier_yun("甲", "辰"), "衰")
        self.assertEqual(shier_yun("甲", "午"), "死")
        self.assertEqual(shier_yun("甲", "未"), "墓")

    def test_yi(self):
        # 乙(陰木): 長生=午(6), 逆行
        self.assertEqual(shier_yun("乙", "午"), "長生")
        self.assertEqual(shier_yun("乙", "巳"), "沐浴")
        self.assertEqual(shier_yun("乙", "卯"), "建禄")
        self.assertEqual(shier_yun("乙", "寅"), "帝旺")


class TestNayin(unittest.TestCase):
    """納音"""

    def test_known(self):
        self.assertEqual(nayin("甲", "子"), "海中金")
        self.assertEqual(nayin("乙", "丑"), "海中金")
        self.assertEqual(nayin("丙", "寅"), "炉中火")
        self.assertEqual(nayin("壬", "戌"), "大海水")

    def test_all_60(self):
        # 60干支（実在する組合せのみ）すべてに納音がある
        for n in range(60):
            gan = "甲乙丙丁戊己庚辛壬癸"[n % 10]
            zhi = "子丑寅卯辰巳午未申酉戌亥"[n % 12]
            res = nayin(gan, zhi)
            self.assertTrue(res.endswith(("金", "木", "水", "火", "土")))


class TestKubo(unittest.TestCase):
    """空亡（日柱）"""

    def test_jiazi(self):
        self.assertEqual(kubo("甲", "子"), ["戌", "亥"])
        self.assertEqual(kubo("乙", "丑"), ["戌", "亥"])

    def test_jiaxu(self):
        self.assertEqual(kubo("甲", "戌"), ["申", "酉"])

    def test_jiashen(self):
        self.assertEqual(kubo("甲", "申"), ["午", "未"])


class TestHourIndex(unittest.TestCase):
    """時辰 index"""

    def test_hours(self):
        self.assertEqual(_hour_index("23:00"), 0)  # 子
        self.assertEqual(_hour_index("00:30"), 0)  # 子
        self.assertEqual(_hour_index("02:00"), 1)  # 丑
        self.assertEqual(_hour_index("12:00"), 6)  # 午
        self.assertEqual(_hour_index("13:00"), 7)  # 未（13-15時）
        self.assertEqual(_hour_index("14:00"), 7)  # 未


class TestBaziPaipan(unittest.TestCase):
    """四柱推命 排盤（sxtwl）"""

    def test_1990_01_15_noon(self):
        # 1990-01-15 12:00（立春前 → 己巳年・丁丑月・庚辰日・壬午時）
        r = bazi_paipan(1990, 1, 15, 12, 0, apply_true_solar=False)
        self.assertEqual(r["pillars"]["year"], "己巳")
        self.assertEqual(r["pillars"]["month"], "丁丑")  # 小寒(1/6)〜立春 → 丁丑月
        self.assertEqual(r["pillars"]["day"], "庚辰")
        self.assertEqual(r["pillars"]["hour"], "壬午")
        self.assertEqual(r["day_master"]["gan"], "庚")    # 日主=庚（陽金）
        self.assertEqual(r["kubo"], ["申", "酉"])          # 庚辰日 → 申酉空亡
        self.assertEqual(r["daun_direction"], "逆行")      # 己巳=陰年・男 → 逆行
        self.assertEqual(r["daun"][0], "丙子")             # 月柱丁丑から逆行して初運
        self.assertIn("detail", r)

    def test_2026_02_04_lichun(self):
        # 2026-02-04（立春当日）→ 年柱は丙午
        r = bazi_paipan(2026, 2, 4, 12, 0, apply_true_solar=False)
        self.assertEqual(r["pillars"]["year"], "丙午")

    def test_2026_02_03_before(self):
        # 2026-02-03（立春前日）→ 年柱は乙巳
        r = bazi_paipan(2026, 2, 3, 12, 0, apply_true_solar=False)
        self.assertEqual(r["pillars"]["year"], "乙巳")


class TestDayBoundary(unittest.TestCase):
    """日界ルール（クロスチェックで検証・別AI実装の検証値と照合）"""

    def test_2000_08_16_2330_23h(self):
        """23時切替: 日柱=丁未（翌日）・時柱=庚子（翌日子時・早晚子時）"""
        r = bazi_paipan(2000, 8, 16, 23, 30, apply_true_solar=False, day_boundary="23h")
        self.assertEqual(r["pillars"]["day"], "丁未")
        self.assertEqual(r["pillars"]["hour"], "庚子")
        self.assertEqual(r["day_boundary"], "23h")

    def test_2000_08_16_2330_0h(self):
        """0時切替: 日柱=丙午（当日）・時柱=戊子（当日子時）"""
        r = bazi_paipan(2000, 8, 16, 23, 30, apply_true_solar=False, day_boundary="0h")
        self.assertEqual(r["pillars"]["day"], "丙午")
        self.assertEqual(r["pillars"]["hour"], "戊子")
        self.assertEqual(r["day_boundary"], "0h")

    def test_day_boundary_consistency(self):
        """23時切替の四柱は「日柱・時柱の整合」が取れる（五鼠遁）:
           丁未日の子時 → 時干は 庚（丁壬庚子居）"""
        r = bazi_paipan(2000, 8, 16, 23, 30, apply_true_solar=False, day_boundary="23h")
        self.assertEqual(r["pillars"]["day"], "丁未")
        self.assertEqual(r["pillars"]["hour"], "庚子")
        # 0時切替: 丙午日の子時 → 時干は 戊（丙辛從戊起）
        r0 = bazi_paipan(2000, 8, 16, 23, 30, apply_true_solar=False, day_boundary="0h")
        self.assertEqual(r0["pillars"]["hour"], "戊子")

    def test_year_crossing_2020_12_31(self):
        """年またぎ: 2020-12-31 23:30（23時切替）→ 日柱=己酉（翌日2021-01-01）"""
        r = bazi_paipan(2020, 12, 31, 23, 30, apply_true_solar=False, day_boundary="23h")
        self.assertEqual(r["pillars"]["day"], "己酉")
        # 年柱は立春基準（2021-01-01は立春前 → 庚子年のまま）
        self.assertEqual(r["pillars"]["year"], "庚子")

    def test_23h_noon_unchanged(self):
        """正午は日界の影響を受けない"""
        r = bazi_paipan(2000, 8, 16, 12, 0, apply_true_solar=False, day_boundary="23h")
        self.assertEqual(r["pillars"]["day"], "丙午")


if __name__ == "__main__":
    unittest.main()
