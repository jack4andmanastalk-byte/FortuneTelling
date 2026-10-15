# -*- coding: utf-8 -*-
"""mts5.66: 星野 凪へ人物・相談文を更新し、紫微斗数の現行大限表示を安全化。

- 紫微斗数は数え年と現在大限レンジをcalc JSONに明示し、プロンプトで別年代の
  レンジを「現在」と誤認しないルールを追加。
- easyの平均文長上限を100字へ。
- spiritualは見出しごとの再構成、象徴→相談への接続→小さな一歩の型、非丁寧体の
  余韻、目印語20回の数値条件を明示し、事実断定を避けつつ表現差を広げる。
- 実機用の架空人物は星野 凪。地域の天文同好会の企画運営・市民科学イベントが相談テーマ。
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from tests.fixtures.consultation import (
    CONSULTATION, CONSULTATION_ALT, TARGET_CHARS, TOLERANCE,
    csv_consultation, load_sample_rows,
)

ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "verify_run_output_mts564", ROOT.parent / "verify" / "verify_run_output.py")
vro = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(vro)

TABLES = vro.build_name_tables(ROOT)
ASSETS = ROOT / "assets" / "images"


class TestZodiacTableMts564(unittest.TestCase):
    """星座の対応表（和名 → 番号・英名）が実装側の正本と一致すること"""

    def test_table_is_built_from_the_product_source(self):
        table = TABLES["seiza"]
        self.assertGreaterEqual(len(table), 12)
        # 実装側の正本（zodiac.py / html_report.py）と同じ並びであること
        from fortunelib.calc.zodiac import SIGNS, SIGNS_EN
        for ja, en in SIGNS_EN.items():
            self.assertIn(ja, table, ja)
            self.assertEqual(table[ja][1], en, ja)
        # 番号は牡羊座＝1 … 魚座＝12（画像ファイル名の番号と一致）
        self.assertEqual(table["牡羊座"], (1, "Aries"))
        self.assertEqual(table["獅子座"], (5, "Leo"))
        self.assertEqual(table["魚座"], (12, "Pisces"))
        # 正本が読めない環境でも検証が止まらない（同梱の予備表）
        self.assertGreaterEqual(len(vro.ZODIAC_FALLBACK), 12)
        self.assertEqual(vro.ZODIAC_FALLBACK["獅子座"], (5, "Leo"))

    def test_three_letter_sign_name_is_verified(self):
        """英名が3文字（Leo）でも照合できる＝mts5.63 の実機の誤報が消えること"""

        def verdict(caption, asset):
            return vro.verify_caption(caption, Path("/x") / asset, TABLES)

        # 正しい対応（mts5.63 の実機で「不一致」と誤報されたもの）
        self.assertEqual(verdict("【星座占い】獅子座（Leo）7/23 - 8/22", "05_Leo.webp")[0], "ok")
        # 6文字の星座（従来から通っていた経路）も変わらず通る
        self.assertEqual(verdict("【星座占い】牡牛座（Taurus）4/20 - 5/20", "02_Taurus.webp")[0], "ok")
        self.assertEqual(verdict("【星座占い】射手座（Sagittarius）11/23 - 12/21",
                                 "09_Sagittarius.webp")[0], "ok")
        # 英名なし（和名だけ）でも番号＋英名で照合できる
        self.assertEqual(verdict("【星座占い】魚座 2/19 - 3/20", "12_Pisces.webp")[0], "ok")

    def test_wrong_sign_is_still_detected(self):
        """誤充当の検出は**維持**（緩めていない）＝別の星座の画像は不一致"""

        def verdict(caption, asset):
            return vro.verify_caption(caption, Path("/x") / asset, TABLES)

        bad = verdict("【星座占い】獅子座（Leo）7/23 - 8/22", "09_Sagittarius.webp")
        self.assertEqual(bad[0], "bad")
        self.assertIn("05_Leo", bad[1])                     # 正しいファイル名を示す
        self.assertEqual(verdict("【星座占い】牡牛座（Taurus）4/20 - 5/20",
                                 "03_Gemini.webp")[0], "bad")

    def test_inconsistent_english_name_is_detected(self):
        """和名と英名が食い違うキャプションも不一致として検出する（新しい検出力）"""
        got, detail = vro.verify_caption("【星座占い】牡牛座（Leo）4/20 - 5/20",
                                         Path("/x") / "05_Leo.webp", TABLES)
        self.assertEqual(got, "bad")
        self.assertIn("Leo", detail)


class TestNewSamplePersonMts564(unittest.TestCase):
    """新しい架空の人物・相手・相談がCSVから計算経路に届くこと"""

    @classmethod
    def setUpClass(cls):
        row = load_sample_rows()[0]
        from fortunelib.batch import build_calc_results, build_profile_facts
        from fortunelib.batch_runner import row_to_input
        from fortunelib.profile import normalize_input
        cls.row = row
        cls.ni = normalize_input(row_to_input(row))
        cls.facts = build_profile_facts(cls.ni)
        from datetime import datetime
        cls.R = build_calc_results(cls.ni, consultation=cls.ni.consultation,
                                   now=datetime(2026, 10, 1, 12, 0))

    def test_person_and_partner_fields(self):
        r = self.row
        self.assertEqual(r["person_id"], "demo_hoshino_nagi")
        self.assertEqual(r["name_kanji"], "星野 凪")
        self.assertEqual(r["name_kana"], "ほしの なぎ")
        self.assertEqual((r["birth_date"], r["birth_time"], r["birth_place"]),
                         ("1992-11-06", "20:20", "愛知県"))
        self.assertEqual((r["gender"], r["blood_type"]), ("F", "AB"))
        self.assertEqual((r["partner_date"], r["partner_time"], r["partner_place"]),
                         ("1990-06-18", "08:40", "新潟県"))
        self.assertEqual(self.ni.name_romaji, "HOSHINO NAGI")

    def test_partner_reaches_synastry(self):
        self.assertEqual(len(self.R), 52)
        syn = self.R["synastry"]
        for k in ("aspects", "mine", "theirs"):
            self.assertIn(k, syn)
        self.assertGreaterEqual(len(syn.get("aspects") or []), 1, syn.get("aspects"))

    def test_exercises_the_three_fixed_paths(self):
        # 現行サンプルのプロファイルと十二支盤データを確認
        self.assertEqual(self.facts["太陽星座"], "蠍座")
        self.assertEqual(self.R["hd"]["type"], "Projector")
        self.assertEqual(self.R["hd"]["authority"], "Self-Projected")
        self.assertEqual(self.R["hd"]["profile"], "2/4")
        self.assertIn("lunar_date", self.R["ziwei"])
        self.assertEqual(self.R["ziwei"]["nominal_age"], 35)
        self.assertEqual(self.R["ziwei"]["current_decadal_range"], [33, 42])

    def test_captions_of_this_person_verify_against_the_deck(self):
        """この人物の星座のキャプションが、検証器で「一致」と判定されること"""
        sign = self.facts["太陽星座"]
        no, en = TABLES["seiza"][sign]
        caption = f"【星座占い】{sign}（{en}）"
        got, detail = vro.verify_caption(caption, Path("/x") / f"{no:02d}_{en}.webp", TABLES)
        self.assertEqual(got, "ok", detail)


class TestConsultation1600Mts564(unittest.TestCase):
    """③ 相談内容が約1,600字（±160）で、CSV と一致し、そのまま鑑定へ入ること"""

    def test_length_and_rule(self):
        for text in (CONSULTATION, CONSULTATION_ALT):
            self.assertLessEqual(abs(len(text) - TARGET_CHARS), TOLERANCE, len(text))
            self.assertGreaterEqual(len(text), 1440)
            self.assertIn("架空", text)
            self.assertIn("シナストリー", text)
            self.assertGreaterEqual(len(text.split("。")), 20)
        self.assertNotEqual(CONSULTATION, CONSULTATION_ALT)
        self.assertEqual(TARGET_CHARS, 1600)

    def test_csv_matches_the_fixture(self):
        self.assertEqual(csv_consultation(), CONSULTATION)
        self.assertEqual(load_sample_rows()[0]["consultation"], CONSULTATION)

    def test_no_sanitize_replacement(self):
        from fortunelib.prompt import sanitize
        self.assertEqual(sanitize(CONSULTATION), CONSULTATION)
        self.assertEqual(sanitize(CONSULTATION_ALT), CONSULTATION_ALT)

    def test_1600_chars_survive_the_prompt_path(self):
        """1,600字がプロンプトへ**そのまま**入る（見出し・改行が崩れない）"""
        from fortunelib.batch import build_calc_results
        from fortunelib.batch_runner import row_to_input
        from fortunelib.profile import normalize_input
        from fortunelib.prompt import build_user_prompt
        row = load_sample_rows()[0]
        ni = normalize_input(row_to_input(row))
        self.assertEqual(len(ni.consultation), len(CONSULTATION))
        from datetime import datetime
        R = build_calc_results(ni, consultation=ni.consultation,
                               now=datetime(2026, 10, 1, 12, 0))
        usr = build_user_prompt("P50", {"氏名（漢字）": "星野 凪"}, None,
                                ni.consultation)
        self.assertIn(CONSULTATION, usr)          # 1,600字が丸ごと入る
        self.assertNotIn("【編集済み】", usr)


if __name__ == "__main__":
    unittest.main()
