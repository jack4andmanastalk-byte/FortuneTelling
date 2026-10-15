# -*- coding: utf-8 -*-
import unittest

from fortunelib.calc.ziwei import ziwei_chart, _time_index
from fortunelib.calc.qimen import qimen_pan
from fortunelib.calc.liuyao import liuyao_paipan, throw_coins, YAO_TO_COINS
import random


class TestTimeIndex(unittest.TestCase):
    """時 → iztro time_index 変換"""

    def test_hours(self):
        self.assertEqual(_time_index(0), 0)   # 子
        self.assertEqual(_time_index(1), 0)   # 子
        self.assertEqual(_time_index(2), 1)   # 丑
        self.assertEqual(_time_index(12), 6)  # 午
        self.assertEqual(_time_index(22), 11)  # 亥
        self.assertEqual(_time_index(23), 12)  # 晚子


class TestZiwei(unittest.TestCase):
    """紫微斗数（iztro-py）"""

    def test_chart_structure(self):
        c = ziwei_chart(1990, 1, 15, 12, "M")
        self.assertEqual(len(c["palaces"]), 12)
        self.assertIn("five_elements_class", c)
        self.assertIn("transformations", c)
        self.assertIn("soul_palace", c)

    def test_palace_names_ja(self):
        c = ziwei_chart(1990, 1, 15, 12, "M")
        names = [p["name"] for p in c["palaces"]]
        self.assertIn("命宮", names)
        self.assertIn("夫妻", names)   # iztroの日本語訳は「夫妻」（宮なし）
        self.assertIn("官祿", names)   # 「官祿宮」→「官祿」

    def test_mutagen_1990(self):
        # 1990-01-15（立春前・己巳年）→ 武曲化禄・貪狼化権・天梁化科
        c = ziwei_chart(1990, 1, 15, 12, "M")
        mutagens = {(t["star"], t["mutagen"]) for t in c["transformations"]}
        self.assertIn(("武曲", "禄"), mutagens)
        self.assertIn(("貪狼", "権"), mutagens)   # mts5.31: 日本語表記（簡体字の「权」を出さない）
        self.assertIn(("天梁", "科"), mutagens)

    def test_decadal(self):
        c = ziwei_chart(1990, 1, 15, 12, "M")
        for p in c["palaces"]:
            if p["name"] == "命宮":
                self.assertIsNotNone(p["decadal"])
                self.assertEqual(p["decadal"]["range"][0], 5)  # 土五局 → 5-14

    def test_current_decadal_matches_nominal_age_as_of_date(self):
        """「現在の大限」は年齢に合うレンジだけを calc に渡す。"""
        from datetime import date
        c = ziwei_chart(1983, 1, 25, 16, "F", as_of=date(2026, 10, 1))
        self.assertEqual(c["nominal_age"], 45)
        self.assertIn("虚歳", c["age_basis"])
        self.assertEqual(c["current_decadal_range"], [36, 45])
        self.assertEqual(c["as_of_date"], "2026-10-01")
        matching = [p for p in c["palaces"] if p.get("decadal")
                    and p["decadal"]["range"] == c["current_decadal_range"]]
        self.assertEqual(len(matching), 1)
        from fortunelib.prompt import build_user_prompt
        user_prompt = build_user_prompt("P24", {}, c, "架空の相談です")
        self.assertIn('"nominal_age": 45', user_prompt)
        self.assertIn('"current_decadal_range": [36, 45]', user_prompt)


class TestQimen(unittest.TestCase):
    """奇門遁甲（kinqimen）"""

    def test_pan_2026_08_15(self):
        r = qimen_pan(2026, 8, 15, 12, 0)
        self.assertIn("ganzhi", r)
        self.assertIn("paiju", r)
        self.assertEqual(r["method"], "拆補")
        # 干支はsxtwlと一致（丙午年丙申月辛酉日甲午時）
        self.assertEqual(r["ganzhi"], "丙午年丙申月辛酉日甲午時")

    def test_pan_structure(self):
        r = qimen_pan(1990, 1, 15, 12, 0)
        self.assertIn("tianpan", r)
        self.assertIn("dipan", r)
        self.assertIn("men", r)
        self.assertIn("xing", r)
        self.assertIn("shen", r)
        self.assertIn("jieqi", r)

    def test_methods(self):
        r1 = qimen_pan(2026, 8, 15, 12, 0, method=1)
        r2 = qimen_pan(2026, 8, 15, 12, 0, method=2)
        self.assertEqual(r1["method"], "拆補")
        self.assertEqual(r2["method"], "置閏")


class TestQimenZhiFu(unittest.TestCase):
    """奇門遁甲 値符/値使の照合（クロスチェック・別AI検証の3ケース）
    - 排局（局数・元）: 別AI検証と3/3一致
    - 値符天干（旬首）: 時柱の旬（60甲子）から理論値を計算して照合
    - 値使門宮: 中宮（5宮）の扱いに流派差があるため「実験的扱い」（別AIも同様）
    """
    import sxtwl as _sxtwl
    _GAN = "甲乙丙丁戊己庚辛壬癸"
    _ZHI = "子丑寅卯辰巳午未申酉戌亥"
    _XUN = ["甲子", "甲戌", "甲申", "甲午", "甲辰", "甲寅"]

    def _xunshou(self, y, m, d, hh):
        """時柱の旬首（sxtwl で理論計算）"""
        day = self._sxtwl.fromSolar(y, m, d)
        hg, hz = day.getHourGZ(hh, True).tg, day.getHourGZ(hh, True).dz
        for n in range(60):
            if n % 10 == hg and n % 12 == hz:
                return self._XUN[n // 10]
        raise AssertionError("干支インデックス計算失敗")

    def test_paiju_and_zhifu(self):
        cases = [
            (2022, 6, 30, 9, "陰遁三局"),
            (2023, 8, 15, 10, "陰遁八局"),
            (2024, 1, 5, 10, "陽遁一局"),
        ]
        for y, m, d, hh, exp_paiju in cases:
            r = qimen_pan(y, m, d, hh, 0)
            # 排局の一致
            self.assertTrue(r["paiju"].startswith(exp_paiju),
                            f"{y}-{m}-{d}: {r['paiju']} != {exp_paiju}")
            # 値符天干（旬首）の一致
            zf = r.get("zhifu_zhishi") or {}
            zf_keys = list(zf.keys())
            self.assertTrue(any("天干" in k for k in zf_keys), f"値符天干キーなし: {zf_keys}")
            zf_gan_key = [k for k in zf_keys if "天干" in k][0]
            zf_gan = zf[zf_gan_key]
            self.assertTrue(zf_gan and zf_gan[0] == self._xunshou(y, m, d, hh),
                            f"{y}-{m}-{d}: 値符天干 {zf_gan} != 旬首 {self._xunshou(y, m, d, hh)}")
            # 値符星宮・値使門宮が出力に含まれる（値使門宮は実験的扱い）
            self.assertTrue(any("星宮" in k for k in zf_keys))
            self.assertTrue(any("門宮" in k for k in zf_keys))


class TestLiuyao(unittest.TestCase):
    """六爻（divicast）"""

    def test_manual_yao(self):
        # 手動爻値 [6,7,8,7,8,9]（下から上）→ 未濟→歸妹
        # mts5.31: divicast の簡体字は日本語表記（伝統字形）へ正規化して返す
        r = liuyao_paipan([6, 7, 8, 7, 8, 9])
        self.assertEqual(r["origin_hexagram"], "未濟")
        self.assertEqual(r["variant_hexagram"], "歸妹")

    def test_yao_to_coins(self):
        self.assertEqual(YAO_TO_COINS[6], 0)
        self.assertEqual(YAO_TO_COINS[7], 1)
        self.assertEqual(YAO_TO_COINS[8], 2)
        self.assertEqual(YAO_TO_COINS[9], 3)

    def test_throw_coins(self):
        rng = random.Random(42)
        yao = throw_coins(rng)
        self.assertEqual(len(yao), 6)
        for v in yao:
            self.assertIn(v, (6, 7, 8, 9))

    def test_seed_reproducible(self):
        r1 = liuyao_paipan(seed=42, rng_mode="reproducible")
        r2 = liuyao_paipan(seed=42, rng_mode="reproducible")
        self.assertEqual(r1["yao_values"], r2["yao_values"])
        self.assertEqual(r1["origin_hexagram"], r2["origin_hexagram"])

    def test_structure(self):
        r = liuyao_paipan(seed=1, rng_mode="reproducible")
        self.assertIn("lines", r)
        self.assertIn("bazi", r)
        self.assertIn("plain", r)
        self.assertEqual(len(r["lines"]), 6)
        # lines の各爻に六親・六神が含まれる
        for ln in r["lines"]:
            self.assertIn("relative", ln)
            self.assertIn("liushen", ln)


if __name__ == "__main__":
    unittest.main()

class TestZiweiMutagenJa(unittest.TestCase):
    """mts5.31: 四化（mutagen）を日本語表記で出す。

    iztro は簡体字の「权」を返すため、日本語表記テーブル
    （iztro_ja_names.json の mutagen）を適用していなかった＝日本語レポートに
    簡体字が混ざっていました（全コード再検証で発見）。
    """

    def test_mutagen_is_japanese(self):
        from fortunelib.calc.ziwei import ziwei_chart, _ja_mutagen
        self.assertEqual(_ja_mutagen("权"), "権")
        self.assertEqual(_ja_mutagen("禄"), "禄")     # 日本語の字形（日本語フォントに存在）
        self.assertEqual(_ja_mutagen("未知"), "未知")  # 未知の値は素通し
        c = ziwei_chart(1990, 5, 20, 10, gender="female")
        vals = {t["mutagen"] for t in c["transformations"]}
        self.assertTrue(vals.issubset({"禄", "権", "科", "忌"}), vals)
        self.assertNotIn("权", vals)
