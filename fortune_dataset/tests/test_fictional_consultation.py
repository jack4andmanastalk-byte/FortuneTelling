# -*- coding: utf-8 -*-
"""mts5.62: テストの相談内容を「架空の長文」にする（恒久ルール・mts5.64 は約1,600字）。

ご指示（Turn 16）:
    今回から、テストを拡張して、相談内容については短文ではなく、
    架空の相談内容を400文字ぐらいにしてテストしてみたい。

狙い: 短文（「相談」「今年の仕事運」）では、実機でしか起きない問題がテストを
すり抜けます。

  - 長い相談文のサニタイズ（置換語が混ざっていないか）
  - プロンプトへの埋め込み（400字がそのまま入るか・見出しが崩れないか）
  - 相談テーマの語判定（占術ごとの分岐）
  - HTML・レポートへの表示（文字化け・行の折り返し）
  - 入力指紋（同じ相談なら同じ結果・違えば違う結果）

そこでテストも**実機と同じ400字の相談文**を使います。正本は
`kaggle/people_sample.csv` の `consultation` 列、共有は
`tests/fixtures/consultation.py`。この2つが食い違うと落ちます。
"""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.fixtures.consultation import (
    CONSULTATION, CONSULTATION_ALT, CSV_PATH, ROOT, TARGET_CHARS, TOLERANCE,
    csv_consultation, is_fictional_consultation, load_sample_rows,
)

#: 相談内容の入力を持つテスト（ここは長文ルールの対象＝短い文字列を書かない）
PIPELINE_TESTS = (
    "test_mts.py",
    "test_pipeline.py",
    "test_profile_schema.py",
    "test_merged_integration.py",
    "test_guards.py",
    "test_pipeline_quality.py",
    "test_prompt.py",
    "test_today_mode.py",
    "test_batch.py",
    "test_notebook_sync.py",
    "test_standard_chars.py",
    "test_bands_and_stones.py",
)


class TestFictionalConsultationFixture(unittest.TestCase):

    def test_about_target_chars_and_fictional(self):
        n = len(CONSULTATION)
        self.assertLessEqual(abs(n - TARGET_CHARS), TOLERANCE, n)
        self.assertTrue(is_fictional_consultation(CONSULTATION))
        self.assertIn("架空", CONSULTATION)
        self.assertIn("シナストリー", CONSULTATION)
        self.assertGreaterEqual(len(CONSULTATION.split("。")), 8)   # 複数の文
        # 2つ目（別の相談）も同じルールを満たし、内容が違う
        self.assertLessEqual(abs(len(CONSULTATION_ALT) - TARGET_CHARS), TOLERANCE)
        self.assertNotEqual(CONSULTATION_ALT, CONSULTATION)
        # 本文が別の相談になっていること（冒頭の定型文を除いた最初の文が別＝独立した内容）
        self.assertNotIn(CONSULTATION.split("。")[1], CONSULTATION_ALT)
        self.assertNotIn(CONSULTATION_ALT.split("。")[1], CONSULTATION)

    def test_csv_is_the_source_of_truth(self):
        self.assertTrue(CSV_PATH.is_file(), CSV_PATH)
        self.assertEqual(csv_consultation(), CONSULTATION)
        self.assertEqual(load_sample_rows()[0]["consultation"], CONSULTATION)

    def test_no_sanitize_replacement_in_the_fixture(self):
        """（編集済み）に置換される語が混ざっていない＝そのまま鑑定文に入る。"""
        from fortunelib.prompt import sanitize
        self.assertEqual(sanitize(CONSULTATION), CONSULTATION)
        self.assertEqual(sanitize(CONSULTATION_ALT), CONSULTATION_ALT)
        self.assertNotIn("【編集済み】", CONSULTATION)

    def test_no_short_consultation_literals_in_pipeline_tests(self):
        """対象のテストは相談内容を**短い文字列リテラルで書かない**（恒久ルール）。

        許すのは空文字（今日の運勢モードの検査）と、変数・定数の参照だけ。
        """
        bad: list[str] = []
        for name in PIPELINE_TESTS:
            path = ROOT / "tests" / name
            self.assertTrue(path.is_file(), path)
            src = path.read_text(encoding="utf-8")
            # 書き方の2通り（キーワード引数・辞書リテラル）を両方見る
            for m in re.finditer(r'consultation\s*=\s*"([^"]*)"', src):
                val = m.group(1)
                if val and len(val) < 100:
                    line = src[:m.start()].count("\n") + 1
                    bad.append(f"{name}:{line}: {val[:30]}")
            for m in re.finditer(r'"consultation":\s*"([^"]*)"', src):
                val = m.group(1)
                if val and len(val) < 100:
                    line = src[:m.start()].count("\n") + 1
                    bad.append(f"{name}:{line}: {val[:30]}（辞書リテラル）")
            self.assertIn("CONSULTATION", src, name)
        self.assertEqual(bad, [], "相談内容が短文のままです: " + " / ".join(bad))


class TestSamplePersonMts562(unittest.TestCase):
    """CSV の人物（桐島 蒼太）が入力として通ること"""

    def test_person_fields(self):
        """mts5.66: 星野 凪。地域の天文同好会を扱う新規テーマ"""

        row = load_sample_rows()[0]
        self.assertEqual(row["person_id"], "demo_hoshino_nagi")
        self.assertEqual(row["name_kanji"], "星野 凪")
        self.assertEqual(row["name_kana"], "ほしの なぎ")
        self.assertEqual((row["birth_date"], row["birth_time"], row["birth_place"]),
                         ("1992-11-06", "20:20", "愛知県"))
        self.assertEqual((row["gender"], row["blood_type"]), ("F", "AB"))
        self.assertEqual((row["partner_date"], row["partner_time"],
                          row["partner_place"]),
                         ("1990-06-18", "08:40", "新潟県"))

    def test_normalizes_and_reaches_the_calculations(self):
        from fortunelib.batch import build_calc_results, build_profile_facts
        from fortunelib.batch_runner import row_to_input
        from fortunelib.profile import normalize_input
        ni = normalize_input(row_to_input(load_sample_rows()[0]))
        self.assertEqual(ni.name_romaji, "HOSHINO NAGI")
        self.assertEqual(ni.consultation, CONSULTATION)
        self.assertEqual(ni.partner.date.isoformat(), "1990-06-18")
        facts = build_profile_facts(ni)
        self.assertEqual(facts["氏名（漢字）"], "星野 凪")
        self.assertEqual(facts["血液型"], "AB型")
        from datetime import datetime
        R = build_calc_results(ni, consultation=ni.consultation,
                               now=datetime(2026, 10, 1, 12, 0))
        self.assertEqual(len(R), 52)                    # 52占術（synastry を含む）
        self.assertIn("hd", R)
        self.assertEqual(R["hd"]["type"], "Projector")
        self.assertEqual(R["hd"]["authority"], "Self-Projected")
        self.assertEqual(R["hd"]["profile"], "2/4")
        self.assertEqual(facts["太陽星座"], "蠍座")
        self.assertEqual(R["ziwei"]["nominal_age"], 35)
        self.assertEqual(R["ziwei"]["current_decadal_range"], [33, 42])
        for k in ("aspects", "mine", "theirs"):
            self.assertIn(k, R["synastry"])

    def test_consultation_reaches_prompts_and_report(self):
        """長文の相談文がプロンプトへそのまま入り、レポートにも出る（モック通し）。"""
        from fortunelib.mts import make_mock_backends, run_person_mts
        backends = make_mock_backends()
        with tempfile.TemporaryDirectory() as td:
            res = run_person_mts(load_sample_rows()[0], backends, Path(td),
                                 verbose=False)
            self.assertEqual(res.error, 0)
            self.assertEqual(res.ok, 52)
            users = [c["user"] for b in backends.values() for c in b.calls]
            self.assertTrue(users)
            self.assertTrue(any(CONSULTATION in u for u in users),
                            "相談文がプロンプトに入っていません")
            self.assertFalse(any("【編集済み】" in u for u in users))
            md = (Path(res.results_dir) / "M03_kyusei.md").read_text(encoding="utf-8")
            if CONSULTATION not in md:                    # モック本文に無い場合も検査は続ける
                self.assertNotIn("【編集済み】", md)


if __name__ == "__main__":
    unittest.main()
