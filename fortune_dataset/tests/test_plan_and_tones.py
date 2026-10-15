# -*- coding: utf-8 -*-
"""mts5.65: ①検証器の表示改善 ②新しい架空人物と相談の差し替え ③obaa の削除と
spiritual の誇張強化 ④Stage A/B の**モデル配分のリバランス**（ご指示4件）。

このファイルは ①③④ の機械的な固定を担当する（②は
`tests/test_chars_and_zodiac.py`・`tests/test_fictional_consultation.py`）。

① 検証器の表示（`verify/verify_run_output.py`）:
    標準本文の字数は、**帯の外のときだけ**「下限まで◯字／上限まで◯字」を出し、
    帯の内側では「＝内側・指示は…」とだけ出す（内側で「下限まで 0字」と
    出ていて紛らわしかったため）。判定は `std_chars_line()` に一本化し、
    results.zip の有無に関わらず同じ語順になる。

③ obaa（おばあちゃん占い師）の削除:
    読み物版は **standard / easy / spiritual の3種**へ（`TONE_IDS`・`TONE_SPECS`・
    `TONE_RULES`・`TONE_MODEL_LANE`・Notebook・版の印 `expected.tones`）。
    同時に spiritual は「標準側で安全性が担保されている」前提で**誇張表現を解禁**した
    （mts5.65では目印語10語・16回以上／丁寧体0.80以下、mts5.66では20回以上／0.70以下／標準の文の流用 0.12 以下・類似 0.75 以下）。
    ただし**安全側の規則は残す**（霊の実在の断定・恐怖の煽り・医療／金銭／法律の断定は書かない）。

④ 配分のリバランス（`data/model_plan.json` は version `2026-10-01-B4`）:
    - Stage A: 3.1-lite 20本／3.5-lite 32本 → **26／26**（mts5.34 の実測で 503 が
      0件になったため、片側だけ混雑したときに全体が待たされる配分を解消）。
    - Stage B: `cluster_to_model`（mts5.8 の M-A/M-D/M-E → 3.5-lite）を撤去し、
      **軸の既定**（method→3.1-lite・culture→3.5-lite＝対象53占術ずつ）へ戻す。
    どちらも `slug_to_model` / `cluster_to_model` を足せば元に戻せる（機構は残す）。
"""
from __future__ import annotations

import importlib.util
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from fortunelib.mts import (load_model_plan, model_for_slug, stage_b_assignment)
from fortunelib.tone import (TONE_DEFS, TONE_IDS, TONE_MODEL_LANE, TONE_RULES,
                             TONE_SPECS, build_omake_prompt, tone_model)

ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "verify_run_output", ROOT.parent / "verify" / "verify_run_output.py")
vro = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(vro)

LITE31 = "gemini-3.1-flash-lite"
LITE35 = "gemini-3.5-flash-lite"


class TestModelPlanBalanceMts565(unittest.TestCase):
    """④ Stage A の等分（26/26）と Stage B の軸既定（52/52 単位）"""

    def test_plan_version_and_counts(self):
        plan = load_model_plan()
        # mts5.67 で上位レーンを差し替えた（B4 → B5）。lite の等分（26/26）は不変。
        # mts5.68 で段階Cの応答打ち切り（response_timeout）を足して B6（レーン構成は不変）。
        self.assertEqual(plan["version"], "2026-10-14-B6")
        n = {m: len(s["slugs"]) for m, s in plan["models"].items()}
        self.assertEqual(n[LITE31], 26)
        self.assertEqual(n[LITE35], 26)
        for upper in ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3-flash-preview"):
            self.assertEqual(n[upper], 0, upper)
        self.assertEqual(sum(n.values()), 52)

    def test_moved_slugs_are_on_the_31_lane(self):
        """mts5.64 の実機で 3.5-lite が打ち切り→3.1-lite が完了した6占術を移した"""
        for slug in ("eto", "numerology_name", "talisman", "astragaloi",
                     "urbantarot", "vedic"):
            self.assertEqual(model_for_slug(slug), LITE31, slug)

    def test_stage_b_axis_defaults_balance_units(self):
        plan = load_model_plan()
        self.assertNotIn("cluster_to_model", plan["stage_b"])   # 上書きを撤去
        asg = stage_b_assignment(plan)
        self.assertEqual(sorted(j[1] for j in asg[LITE31]),
                         ["M-A", "M-B", "M-C", "M-D", "M-E"])
        self.assertEqual(len(asg[LITE35]), 6)
        self.assertTrue(all(ax == "culture" for ax, _ in asg[LITE35]))
        # 単位数（クラスタが覆う占術の本数＝神々を含む53）が釣り合う
        self.assertEqual(self._units(asg[LITE31]), 53)
        self.assertEqual(self._units(asg[LITE35]), 53)

    @staticmethod
    def _units(jobs) -> int:
        """その軸の担当クラスタが覆う占術の本数（＝単位数）"""
        from fortunelib.clusters import get_clusters
        sizes = {c["id"]: len(c["slugs"]) for c in get_clusters("method")}
        sizes.update({c["id"]: len(c["slugs"]) for c in get_clusters("culture")})
        return sum(sizes[cid] for _ax, cid in jobs)

    def test_override_mechanism_still_exists(self):
        """戻すための機構（cluster_to_model・slug の付け替え）は残っている"""
        plan = load_model_plan()
        patched = dict(plan)
        patched["stage_b"] = dict(plan["stage_b"])
        patched["stage_b"]["cluster_to_model"] = {"M-A": LITE35}
        asg = stage_b_assignment(patched)
        self.assertIn(("method", "M-A"), asg[LITE35])


class TestToneRemovalMts565(unittest.TestCase):
    """③ obaa の削除と spiritual の誇張強化"""

    def test_tone_ids_are_three(self):
        self.assertEqual(TONE_IDS, ["standard", "easy", "spiritual"])
        for tid in ("obaa",):
            self.assertNotIn(tid, TONE_IDS)
            self.assertNotIn(tid, TONE_SPECS)
            self.assertNotIn(tid, TONE_RULES)
            self.assertNotIn(tid, TONE_MODEL_LANE)
        self.assertFalse([t for t in TONE_DEFS if t["id"] == "obaa"])

    def test_lanes_keep_tones_apart(self):
        chain = [LITE35, LITE31]
        self.assertEqual(tone_model("easy", chain), LITE31)
        self.assertEqual(tone_model("spiritual", chain), LITE35)
        self.assertNotEqual(tone_model("easy", chain), tone_model("spiritual", chain))

    def test_expected_tones_marker_is_three(self):
        ver = json.loads((ROOT / "data" / "dataset_version.json").read_text(encoding="utf-8"))
        self.assertEqual(ver["expected"]["tones"], 3)

    def test_spiritual_is_exaggerated_but_safe(self):
        sp = TONE_SPECS["spiritual"]
        # 誇張方向の強化（mts5.65）
        self.assertGreaterEqual(len(sp["markers"]), 10)
        self.assertIn("チャクラ", sp["markers"])
        self.assertGreaterEqual(sp["marker_min"], 20)
        self.assertLessEqual(float(sp["polite_max"]), 0.70)
        self.assertLessEqual(float(sp["similarity_max"]), 0.75)
        self.assertLessEqual(float(sp["verbatim_max"]), 0.12)
        self.assertIn("誇張", sp["howto"])
        tone = next(t for t in TONE_DEFS if t["id"] == "spiritual")
        sysp, usrp = build_omake_prompt(tone, {"id": "synthesis", "text": "あ" * 1000})
        self.assertIn("誇張", sysp)
        self.assertIn("20回以上", sysp)
        # 安全側（標準が正本・断定しない）の規則は残る
        for must in ("霊的存在", "実在", "断定", "医療", "創作しない"):
            self.assertIn(must, sysp, must)
        self.assertIn("800〜1400字", usrp)

    def test_obaa_is_gone_from_notebook_and_version(self):
        nb = json.loads((ROOT / "kaggle" / "fortune_notebook.ipynb")
                        .read_text(encoding="utf-8"))
        src = "\n".join("".join(c["source"]) for c in nb["cells"])
        self.assertNotIn("おばあちゃん占い師", src)
        self.assertIn("_TONES_DEFAULT = 3", src)
        cell0 = (ROOT / "kaggle" / "cell0_selftest.py").read_text(encoding="utf-8")
        self.assertIn("_TONES_DEFAULT = 3", cell0)


class TestStdBandDisplayMts565(unittest.TestCase):
    """① 検証器の表示＝帯の外のときだけ「下限まで／上限まで」"""

    BAND = (4000, 5300)
    INSTRUCT = (4800, 5200)

    def _line(self, n: int) -> str:
        return vro.std_chars_line(n, self.BAND, self.INSTRUCT)

    def test_inside_band_has_no_gap_words(self):
        line = self._line(4617)
        self.assertIn("内側", line)
        self.assertNotIn("下限まで", line)
        self.assertNotIn("上限まで", line)
        self.assertIn("指示は 4800〜5200字", line)
        # 帯の端も「内側」（境界を含む）
        self.assertNotIn("下限まで", self._line(4000))
        self.assertNotIn("上限まで", self._line(5300))

    def test_below_lower_band_shows_the_gap(self):
        line = self._line(3716)
        self.assertIn("外", line)
        self.assertIn("下限まで 284字", line)
        self.assertNotIn("上限まで", line)

    def test_above_upper_band_shows_the_gap(self):
        line = self._line(5400)
        self.assertIn("上限まで 100字", line)
        self.assertNotIn("下限まで", line)

    def test_verify_uses_the_helper(self):
        """検証器の本文（main）が同じ関数を使っている（表示の二重実装を防ぐ）"""
        src = (ROOT.parent / "verify" / "verify_run_output.py").read_text(encoding="utf-8")
        self.assertIn("def std_chars_line(", src)
        self.assertEqual(src.count("std_chars_line("), 2)   # 定義1＋呼び出し1
        self.assertNotIn("下限まで {_lo - _n}字", src)      # 旧: 帯の内側でも出していた


class TestLaneSummaryMts565(unittest.TestCase):
    """④ ログの可視化＝レーン別の内訳（担当・引取・移譲・打切り）"""

    @staticmethod
    def _prog(workers, timeouts=(), done=None):
        class _P:
            def snapshot(self):
                return {"workers": workers, "timeouts": list(timeouts),
                        "totals": {"done": done if done is not None
                                   else sum(w["done"] for w in workers.values())}}
        return _P()

    def test_prints_both_lanes_with_breakdown(self):
        from fortunelib.mts import _print_lane_summary
        prog = self._prog({
            LITE31: {"done": 26, "total": 26, "pulled": 3, "handed_over": 8},
            LITE35: {"done": 26, "total": 26, "pulled": 22, "handed_over": 9},
        }, timeouts=[{"from_model": LITE31}, {"from_model": LITE35},
                     {"from_model": LITE35}])
        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_lane_summary(prog, load_model_plan())
        line = buf.getvalue().strip()
        self.assertIn("段階A レーン別", line)
        self.assertIn(f"{LITE31} 26件（担当26・引取3・移譲8・打切り1）", line)
        self.assertIn(f"{LITE35} 26件（担当26・引取22・移譲9・打切り2）", line)
        self.assertIn("合計52件", line)

    def test_silent_when_no_workers(self):
        from fortunelib.mts import _print_lane_summary
        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_lane_summary(self._prog({}), load_model_plan())
        self.assertEqual(buf.getvalue(), "")

    def test_wired_into_run_slugs_mts_with_verbose(self):
        """run_slugs_mts(verbose=True) で実際に出ること（呼び忘れの防止）"""
        import tempfile
        from tests.test_mts import _make_ctx, _no_pull_plan, make_mock_backends
        from fortunelib.mts import Progress, run_slugs_mts
        with tempfile.TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td))
            buf = io.StringIO()
            with redirect_stdout(buf):
                run_slugs_mts(["eto", "seiza"], ctx, make_mock_backends(),
                              plan=_no_pull_plan(), progress=Progress(),
                              verbose=True)
        self.assertIn("段階A レーン別", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
