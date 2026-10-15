# -*- coding: utf-8 -*-
"""mts5.60: 標準本文の指示レンジ引き上げ（4,800〜5,200字）と、石名の候補リスト。

ご相談（Turn 14・mts5.58 の実機検証のあと）でご選択いただいた2件:

  ① 標準本文が 3,716字（対 指示下限 4,400字で実測比 0.84）で新しい下限 4,000字に
     届かなかった → **呼び出し回数は増やさず、指示の下限を 4,800字へ引き上げる**
     （4,800×0.84 = 4,032 で下限を上回る計算。章の足し上げも 4,800 に一致させる）。
  ② クリスタル・ヒーリング（P50）が素材に無い石（実機では「エンジェライト」）を
     名指しして画像が1枚欠けた → **画像のある21石を候補としてプロンプトに渡し、
     その和名を1つだけ書かせる**（石の表は `fortunelib/stones.py` が唯一の正本）。

占術の計算・プロファイル事実・画像そのものは不変（プロンプトと検証だけの変更）。
"""
from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path

from tests.fixtures.consultation import CONSULTATION, CONSULTATION_ALT

ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "verify_run_output", ROOT.parent / "verify" / "verify_run_output.py")
vro = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(vro)


class TestBandMts560(unittest.TestCase):
    """①指示レンジの引き上げ（4,800〜5,200字）"""

    def test_exact_values(self):
        from fortunelib.synthesis import FINAL_CHARS, FINAL_INSTRUCT_CHARS
        self.assertEqual(FINAL_INSTRUCT_CHARS, (4800, 5200))
        self.assertEqual(FINAL_CHARS, (4000, 5300))

    def test_observed_worst_undershoot_now_clears_the_floor(self):
        """実機で観測した最悪の下振れ（実測比 0.84）でも下限 4,000 を上回る。"""
        from fortunelib.synthesis import FINAL_CHARS, FINAL_INSTRUCT_CHARS
        self.assertGreater(FINAL_INSTRUCT_CHARS[0] * 0.84, FINAL_CHARS[0])

    def test_mts558_miss_is_explained(self):
        """mts5.58 の実機（3,716字）は旧指示 4,400 の 0.84 = 想定外の下振れだった。"""
        self.assertAlmostEqual(3716 / 4400, 0.845, places=3)
        self.assertLess(3716, 4000)          # 下限に届いていなかった
        self.assertGreater(4800 * (3716 / 4400), 4000)

    def test_chapter_budget_matches_the_instructed_floor(self):
        """章の足し上げ＝指示下限（4,800字）。不一致は下振れの一因なので許さない。"""
        from fortunelib.synthesis import (FINAL_INSTRUCT_CHARS,
                                          build_crossaxis_final_prompt)
        sysp, _ = build_crossaxis_final_prompt(
            [{"axis": "method", "text": "あ" * 50}], {"a": 1}, CONSULTATION)
        budgets = [int(x) for x in re.findall(r"(\d+)字程度", sysp)]
        self.assertEqual(len(budgets), 6)
        self.assertEqual(sum(budgets), FINAL_INSTRUCT_CHARS[0])

    def test_verifier_band_is_in_sync(self):
        from fortunelib.synthesis import FINAL_CHARS, FINAL_INSTRUCT_CHARS
        self.assertEqual(tuple(vro.STD_BAND), FINAL_CHARS)
        self.assertEqual(tuple(vro.STD_INSTRUCT_BAND), FINAL_INSTRUCT_CHARS)

    def test_stage_c_uses_the_new_target_and_headroom(self):
        """試行の選択は帯の中央（5,000字）／max_tokens は上限で切れない 6,400。"""
        import inspect
        from fortunelib import mts
        src = inspect.getsource(mts.run_stage_c_mts)
        self.assertIn("target_mid=5000", src)
        self.assertIn("max_tokens=6400", src)
        self.assertIn("instruct_band=FINAL_INSTRUCT_CHARS", src)

    def test_headroom_over_the_instructed_max(self):
        """指示上限の出力（5,200字）が「長すぎ」と警告されない余裕がある。"""
        from fortunelib.synthesis import FINAL_CHARS, FINAL_INSTRUCT_CHARS
        self.assertGreaterEqual(FINAL_CHARS[1] - FINAL_INSTRUCT_CHARS[1], 50)
        self.assertGreaterEqual(FINAL_CHARS[1], 5200)


class TestStoneChoicesMts560(unittest.TestCase):
    """②石の候補リスト（画像のある21石）をプロンプトへ渡す"""

    def test_pool_is_the_single_source_of_truth(self):
        """石の表は stones.py が正本で、HTML 側は同じ表を使う（別名で参照）。"""
        from fortunelib import html_report
        from fortunelib.stones import CRYSTAL_STONES
        self.assertEqual(len(CRYSTAL_STONES), 21)
        self.assertIs(html_report._CRYSTAL_STONES, CRYSTAL_STONES)

    def test_html_resolution_is_delegated(self):
        from fortunelib.html_report import _crystal_stone_in_text
        from fortunelib.stones import resolve_stone_in_text
        for text in ("ガーネットの次にシトリン", "アベンチュリン（Aventurine）", ""):
            self.assertEqual(_crystal_stone_in_text(text),
                             resolve_stone_in_text(text))

    def test_pool_matches_the_assets_on_disk(self):
        """候補21石のファイルが実際に素材ディレクトリにある（1〜21の連番）。"""
        from fortunelib.stones import CRYSTAL_STONES
        d = ROOT / "assets" / "images" / "M30_crystal"
        if not d.is_dir():
            self.skipTest("素材ディレクトリが無い環境（Kaggle模擬など）")
        files = {p.name for p in d.glob("*.webp")}
        self.assertEqual(len(files), 21)
        for no, _ja, en, _a in CRYSTAL_STONES:
            self.assertIn(f"{no:02d}_{en.replace(' ', '')}.webp", files)

    def test_unknown_stone_is_still_unresolvable(self):
        """一覧に無い石は画像解決できない＝候補リストで防ぐ必要がある。"""
        from fortunelib.stones import resolve_stone_in_text
        for name in ("エンジェライト", "セレナイト", "ラリマー"):
            self.assertEqual(resolve_stone_in_text(f"{name}を手に取って"), 0)

    def test_prompt_lists_the_pool_and_forbids_others(self):
        from fortunelib.prompt import build_user_prompt
        from fortunelib.stones import CRYSTAL_STONES
        user = build_user_prompt("P50", {"氏名（漢字）": "桐島 蒼太"}, None,
                                 CONSULTATION)
        self.assertIn("# 石の候補（この一覧から1つだけ選ぶ）", user)
        for _no, ja, en, _a in CRYSTAL_STONES:
            self.assertIn(ja, user)
            self.assertIn(en, user)
        self.assertIn("エンジェライト", user)      # 「書かない」例として明示
        self.assertIn("書かないでください", user)

    def test_other_prompts_are_untouched(self):
        from fortunelib.prompt import build_user_prompt
        for pid in ("P12", "P01", "P49"):
            try:
                user = build_user_prompt(pid, {"氏名（漢字）": "桐島 蒼太"},
                                         {"x": 1}, CONSULTATION)
            except Exception:
                continue
            self.assertNotIn("石の候補", user, pid)

    def test_all_birthstones_are_in_the_pool(self):
        """パワーストーン（M12_stone・計算で決まる）は必ず画像が解決できる。"""
        import json
        from fortunelib.stones import CRYSTAL_STONES
        names = {ja for _n, ja, _e, _a in CRYSTAL_STONES}
        data = json.loads((ROOT / "data" / "birthstones.json").read_text(encoding="utf-8"))
        for x in data["birthstones"]:
            self.assertIn(x["stone_ja"], names, x)

    def test_crystal_text_resolves_to_a_pool_stone(self):
        """候補から選んだ本文は必ず画像へ解決できる（画像が欠けない）。"""
        from fortunelib.stones import CRYSTAL_STONES, resolve_stone_in_text
        for no, ja, en, _a in CRYSTAL_STONES:
            self.assertEqual(resolve_stone_in_text(f"今回は{ja}を提案します。"), no)
            self.assertEqual(resolve_stone_in_text(f"Try {en} for you."), no)


if __name__ == "__main__":
    unittest.main()
