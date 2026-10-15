# -*- coding: utf-8 -*-
"""mts5.47: M27の字数上限とM30のプロフィール個別化を回帰固定する。"""
import json
import tempfile
import unittest
from pathlib import Path

from fortunelib.batch import build_profile_facts
from fortunelib.pipeline import PipelineContext, _build_fix_instruction, run_divination
from fortunelib.profile import normalize_input
from tests.fixtures.consultation import CONSULTATION, CONSULTATION_ALT
from fortunelib.prompt import build_system_prompt, build_user_prompt


class _ConstantBackend:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def generate(self, system_prompt, user_prompt, **kwargs):
        self.calls.append((system_prompt, user_prompt, kwargs))
        return self.text


def _context(tmp, *, consultation=CONSULTATION):
    raw = {
        "birth": {"date": "1994-09-29", "time": "06:18", "place": "千葉県"},
        "gender": "F", "blood_type": "O",
        "name_kanji": "水城 栞", "name_kana": "みずき しおり",
        "partner": {"date": "1992-03-12", "time": "20:45", "place": "東京都"},
        "consultation": consultation,
    }
    ni = normalize_input(raw)
    root = Path(tmp)
    return PipelineContext(
        inputs=ni,
        profile_facts=build_profile_facts(ni),
        calc_results={},
        consultation=consultation,
        results_dir=root / "results",
        summary_path=root / "profile_summary.json",
        seed=7,
    )


class TestTarotHardCharacterLimit(unittest.TestCase):
    def test_overlong_tarot_is_rewritten_then_trimmed_at_sentence_boundary(self):
        sentence = "カードの象徴を手掛かりに、今できる選択を穏やかに見直しましょう。"
        text = sentence
        while len(text) <= 700:
            text += sentence
        backend = _ConstantBackend(text)
        with tempfile.TemporaryDirectory() as td:
            ctx = _context(td)
            result = run_divination("tarot", ctx, backend=backend)
            raw = json.loads((ctx.results_dir / "M27_tarot_raw.json").read_text(
                encoding="utf-8"))

        final_text = raw["result"]["text"]
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(backend.calls), 2)  # QC指示つき再生成を行う
        self.assertGreaterEqual(len(final_text), 400)
        self.assertLessEqual(len(final_text), 700)
        self.assertTrue(final_text.endswith("。"))
        self.assertEqual(result["issues"], [])
        self.assertTrue(raw["result"]["quality_adjustments"])
        self.assertEqual(raw["notes"], [])

        # 文末が一つも上限内にない応答でも、絶対上限を超えたまま残さない。
        unit = "カードの象徴を手掛かりに今できる選択を穏やかに見直しましょう"
        one_sentence = unit * 25 + "。"
        self.assertGreater(len(one_sentence), 700)
        backend2 = _ConstantBackend(one_sentence)
        with tempfile.TemporaryDirectory() as td:
            ctx2 = _context(td)
            result2 = run_divination("tarot", ctx2, backend=backend2)
            raw2 = json.loads((ctx2.results_dir / "M27_tarot_raw.json").read_text(
                encoding="utf-8"))
        final2 = raw2["result"]["text"]
        self.assertEqual(result2["status"], "ok")
        self.assertLessEqual(len(final2), 700)
        self.assertGreaterEqual(len(final2), 400)
        self.assertTrue(final2.endswith("。"))
        self.assertEqual(result2["issues"], [])


class TestTalismanProfileFact(unittest.TestCase):
    def test_prompt_selects_and_explains_the_exact_solar_sign(self):
        facts = {"太陽星座": "天秤座", "血液型": "O型"}
        system = build_system_prompt("P55")
        user = build_user_prompt("P55", facts, consultation=CONSULTATION)
        self.assertIn("個別化の必須条件", system)
        self.assertIn("太陽星座: 天秤座", user)
        self.assertIn("図案や使い方", user)

    def test_fix_instruction_names_the_required_fact(self):
        instruction = _build_fix_instruction(
            ["事実整合: プロファイル事実（天秤座 等）が1つも織り込まれていない"],
            {"id": "P55", "profile_fact_key": "太陽星座"}, 350,
            must_mention=["天秤座"],
        )
        self.assertIn("太陽星座", instruction)
        self.assertIn("天秤座", instruction)
        self.assertIn("タリスマンの意匠", instruction)

    def test_missing_fact_gets_a_deterministic_personalized_design_clause(self):
        generic = "お守りは小さな円形に整え、落ち着いた色と細い線を添える案です。" * 10
        backend = _ConstantBackend(generic)
        with tempfile.TemporaryDirectory() as td:
            ctx = _context(td)
            result = run_divination("talisman", ctx, backend=backend)
            raw = json.loads((ctx.results_dir / "M30_talisman_raw.json").read_text(
                encoding="utf-8"))

        final_text = raw["result"]["text"]
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(backend.calls), 2)
        self.assertIn("天秤座", final_text)
        self.assertIn("風のイメージ", final_text)
        self.assertIn("薄桃色", final_text)
        self.assertEqual(result["issues"], [])
        self.assertIn("不足していた太陽星座の個別化文を補足",
                      raw["result"]["quality_adjustments"])
        self.assertEqual(raw["notes"], [])

    def test_existing_fact_is_not_duplicated(self):
        from fortunelib.pipeline import _ensure_talisman_fact
        text = "プロフィールの天秤座を意匠の手掛かりにします。" + "説明です。" * 70
        result, changed = _ensure_talisman_fact(
            text, {"太陽星座": "天秤座"}, ["天秤座"], 300, 600)
        self.assertFalse(changed)
        self.assertEqual(result, text)


if __name__ == "__main__":
    unittest.main()
