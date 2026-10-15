"""mts5.67（2026-10-14・ユーザー決定）: 非推奨モデルの差し替えを固定する。

背景: Google が gemini-3.5-flash と gemini-3.7-flash を非推奨にした。
決定（ask_user で確定）:
  ① 後継＝ **gemini-3.8-flash を既定**、予備は **gemini-3.6-flash → gemini-3-flash-preview** の順
  ② gemini-3.5-flash-lite は非推奨ではない → lite 2レーン（Stage A/B/D）は不変
  ③ 非推奨の2モデルは一次・fallback・404候補・動画台本カスケードの**すべてから除去**
  ④ Cell 0 の MODEL_NAME も更新し、Notebook を再生成（再Import 前提）

あわせて backend の潜在不具合（thinking 系パラメータを 400 で拒否されたとき、
「除去して再試行」と表示しながら同じ設定を再送していた）を修正し、
**minimal → low → 除去** の順に1段ずつ緩める動作を固定する。
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from fortunelib import backend as B                      # noqa: E402
from fortunelib.mts import (                             # noqa: E402
    load_model_plan, stage_c_chain, stage_c_model, deities_chain,
    deities_model, fallback_chain, stage_b_assignment)
from fortunelib.tone import stage_d_chain                # noqa: E402

DEPRECATED = ("gemini-3.5-flash", "gemini-3.7-flash")
UPPER = ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3-flash-preview")
LITE31, LITE35 = "gemini-3.1-flash-lite", "gemini-3.5-flash-lite"


def _strings(obj, skip_keys=("note", "notes", "scope_note")):
    """JSON の中の文字列を（注記を除いて）列挙する。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in skip_keys:
                continue
            yield from _strings(v, skip_keys)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _strings(v, skip_keys)
    elif isinstance(obj, str):
        yield obj


class TestPlanB5(unittest.TestCase):
    def test_version_and_lanes(self):
        plan = load_model_plan()
        # mts5.68: 段階Cの応答打ち切り（response_timeout）を足して B6 へ（レーン構成は B5 のまま）
        self.assertEqual(plan["version"], "2026-10-14-B6")
        self.assertEqual(plan["plan"], "B5")
        self.assertEqual(list(plan["models"]),
                         [LITE31, LITE35, *UPPER])

    def test_deprecated_ids_are_gone_from_the_plan(self):
        plan = load_model_plan()
        found = [s for s in _strings(plan) if s in DEPRECATED or s == "gemini-3-flash"]
        self.assertEqual(found, [], "非推奨ID／常に404だった gemini-3-flash が計画に残っています")

    def test_stage_c_and_deities_chains(self):
        self.assertEqual(stage_c_model(), "gemini-3.8-flash")
        self.assertEqual(stage_c_chain(), [*UPPER, LITE35])
        self.assertEqual(deities_model(), "gemini-3-flash-preview")
        self.assertEqual(deities_chain(), ["gemini-3-flash-preview", "gemini-3.8-flash",
                                           "gemini-3.6-flash", LITE35])

    def test_upper_lane_fallbacks_rotate_within_upper_then_lite(self):
        plan = load_model_plan()
        self.assertEqual(fallback_chain("gemini-3.8-flash", plan),
                         ["gemini-3.6-flash", "gemini-3-flash-preview", LITE35])
        self.assertEqual(fallback_chain("gemini-3.6-flash", plan),
                         ["gemini-3-flash-preview", "gemini-3.8-flash", LITE35])
        self.assertEqual(fallback_chain("gemini-3-flash-preview", plan),
                         ["gemini-3.8-flash", "gemini-3.6-flash", LITE35])
        for m in UPPER:
            spec = plan["models"][m]
            self.assertEqual(spec["slugs"], [], m)          # Stage A の占術は載せない
            self.assertEqual(spec["rpm"], 5, m)             # 無料枠は未確認 → 保守的に
            self.assertEqual(spec["rpd"], 20, m)

    def test_lite_lanes_unchanged_and_escalate_in_the_requested_order(self):
        plan = load_model_plan()
        self.assertEqual(fallback_chain(LITE31, plan), [LITE35, *UPPER])
        self.assertEqual(fallback_chain(LITE35, plan), [LITE31, *UPPER])
        n = {m: len(s["slugs"]) for m, s in plan["models"].items()}
        self.assertEqual((n[LITE31], n[LITE35]), (26, 26))
        # Stage B（軸の既定）と Stage D（口調）は lite のまま
        self.assertEqual(set(stage_b_assignment(plan)), {LITE31, LITE35})
        self.assertEqual(stage_d_chain(plan), [LITE35, LITE31])
        self.assertEqual(plan["stage_a"]["pull"]["models"], [LITE31, LITE35])


class TestBackendDefaults(unittest.TestCase):
    def test_default_and_order_constants(self):
        self.assertEqual(B.GeminiBackend.DEFAULT_MODEL, "gemini-3.8-flash")
        self.assertEqual(B.FLASH_UPPER_ORDER, UPPER)
        self.assertEqual(B.DEPRECATED_MODELS, DEPRECATED)

    def test_candidates_never_contain_deprecated_ids(self):
        names = [*UPPER, LITE31, LITE35, "gemini-3-flash", "gemini-3.0-flash",
                 "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-9.9-x", ""]
        for name in names:
            got = B.gemini_model_candidates(name)
            for bad in DEPRECATED:
                self.assertNotIn(bad, got, f"{name!r} → {got}")
        self.assertEqual(B.gemini_model_candidates("gemini-3.8-flash"),
                         ["gemini-3.8-flash", "gemini-3.8-flash-preview",
                          "gemini-3.6-flash", "gemini-3-flash-preview"])
        # 手動で非推奨IDを指定しても、候補の末尾は生きている既定モデル
        for bad in DEPRECATED:
            self.assertEqual(B.gemini_model_candidates(bad)[-1], "gemini-3.8-flash")

    def test_fatal_404_hint_names_the_current_default(self):
        be = B.GeminiBackend(model_name="gemini-3.8-flash", api_key="k",
                             verbose=False, backoff_base_s=0.0,
                             requests_per_minute=600.0)      # テストは待たない

        class Fake404(Exception):
            code = 404

        def fake_gen(*a, **k):
            raise Fake404("model not found")

        be._generate_once = fake_gen
        with self.assertRaises(RuntimeError) as cm:
            be.generate("sys", "usr")
        self.assertIn("'gemini-3.8-flash'", str(cm.exception))
        self.assertNotIn("3.5-flash'", str(cm.exception))


class TestThinkingRejectionIsRelaxedStepwise(unittest.TestCase):
    """400（thinking 拒否）→ minimal を low に下げる → それでも 400 なら除去 → それでも 400 なら致命。

    mts5.68: 3.8-flash は実機で minimal 拒否が確定し最初から low で送るため、
    段階動作の確認は **minimal 対応が未確定の gemini-3.6-flash** で行う
    （3.8 の「low から始まる」動作は TestThinking38StartsAtLow）。
    """

    class Fake400(Exception):
        code = 400

    def _backend(self, model="gemini-3.6-flash"):
        return B.GeminiBackend(model_name=model, api_key="k",
                               verbose=False, backoff_base_s=0.0,
                               requests_per_minute=600.0)    # テストは待たない

    def test_minimal_then_low_then_removed(self):
        be = self._backend()
        sent = []

        def fake_gen(sys_p, usr_p, temp, mt, seed, model=None):
            kw = be._thinking_kwargs(model)
            sent.append(dict(kw))
            if kw:                                    # thinking を付けている間は拒否
                raise self.Fake400("400 INVALID_ARGUMENT: thinking_level is not supported")
            return "ok"

        be._generate_once = fake_gen
        self.assertEqual(be.generate("sys", "usr"), "ok")
        self.assertEqual(sent, [{"thinking_level": "minimal"},
                                {"thinking_level": "low"},
                                {}])
        self.assertTrue(be._thinking_downgraded)
        self.assertTrue(be._thinking_unsupported)
        # 以後の呼び出しは thinking を付けずに送る（毎回 400 を踏み直さない）
        self.assertEqual(be.generate("sys", "usr"), "ok")
        self.assertEqual(sent[-1], {})
        self.assertEqual(len(sent), 4)

    def test_low_is_accepted_on_second_try(self):
        be = self._backend()
        sent = []

        def fake_gen(sys_p, usr_p, temp, mt, seed, model=None):
            kw = be._thinking_kwargs(model)
            sent.append(dict(kw))
            if kw.get("thinking_level") == "minimal":
                raise self.Fake400("400: thinking_level minimal not supported")
            return "ok"

        be._generate_once = fake_gen
        self.assertEqual(be.generate("sys", "usr"), "ok")
        self.assertEqual(sent, [{"thinking_level": "minimal"}, {"thinking_level": "low"}])
        self.assertFalse(be._thinking_unsupported)       # low が通ったので除去はしない

    def test_still_400_after_removal_is_fatal_and_finite(self):
        be = self._backend()
        calls = {"n": 0}

        def fake_gen(*a, **k):
            calls["n"] += 1
            raise self.Fake400("400: thinking is broken (test)")

        be._generate_once = fake_gen
        with self.assertRaises(RuntimeError):
            be.generate("sys", "usr")
        self.assertEqual(calls["n"], 3)                   # minimal / low / なし の3回で止まる

    def test_other_400_is_not_treated_as_thinking(self):
        be = self._backend()
        calls = {"n": 0}

        def fake_gen(*a, **k):
            calls["n"] += 1
            raise self.Fake400("400 INVALID_ARGUMENT: bad request body")

        be._generate_once = fake_gen
        with self.assertRaises(RuntimeError):
            be.generate("sys", "usr")
        self.assertEqual(calls["n"], 1)
        self.assertFalse(be._thinking_downgraded)
        self.assertFalse(be._thinking_unsupported)

    def test_make_config_honours_the_flags(self):
        try:
            import google.genai  # noqa: F401
        except ImportError:
            self.skipTest("google-genai 未導入（pip install google-genai）")
        be = self._backend()

        def level(cfg):
            tc = getattr(cfg, "thinking_config", None)
            lv = getattr(tc, "thinking_level", None) if tc is not None else None
            return str(getattr(lv, "value", lv)).upper() if lv is not None else None

        self.assertEqual(level(be._make_config("S", 0.7, 100, None)), "MINIMAL")
        be._thinking_downgraded = True
        self.assertEqual(level(be._make_config("S", 0.7, 100, None)), "LOW")
        be._thinking_unsupported = True
        self.assertIsNone(level(be._make_config("S", 0.7, 100, None)))


class TestKaggleCells(unittest.TestCase):
    KAGGLE = ROOT / "kaggle"

    def test_cell0_model_name(self):
        src = (self.KAGGLE / "cell0_bootstrap.py").read_text(encoding="utf-8")
        m = re.search(r'^MODEL_NAME = "([^"]+)"', src, re.M)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "gemini-3.8-flash")

    def test_no_deprecated_id_in_executable_code(self):
        """コメント・docstring の経緯説明は許すが、**文字列リテラルそのもの**として
        非推奨IDを置くのは backend.DEPRECATED_MODELS の定義だけ（候補列・既定・連鎖に残さない）。"""
        import ast
        targets = [ROOT / "fortunelib" / "backend.py", ROOT / "fortunelib" / "mts.py",
                   ROOT / "fortunelib" / "tone.py",
                   ROOT / "fortunelib" / "synthesis.py",
                   self.KAGGLE / "cell0_bootstrap.py", self.KAGGLE / "cell0_selftest.py",
                   self.KAGGLE / "cellN2_synthesis.py", self.KAGGLE / "cell1_csv_input.py"]
        offenders = []
        for p in targets:
            if not p.exists():
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and node.value in DEPRECATED:
                    offenders.append(f"{p.name}:{node.lineno}: {node.value!r}")
        allowed = {f"backend.py:{n.lineno}: {c.value!r}"
                   for n in ast.walk(ast.parse((ROOT / "fortunelib" / "backend.py")
                                               .read_text(encoding="utf-8")))
                   if isinstance(n, ast.Assign)
                   and any(getattr(t, "id", "") == "DEPRECATED_MODELS" for t in n.targets)
                   for c in ast.walk(n.value) if isinstance(c, ast.Constant)}
        self.assertTrue(allowed, "backend.DEPRECATED_MODELS の定義が見つかりません")
        self.assertEqual(sorted(set(offenders) - allowed), [])

    def test_notebook_cells_match_sources(self):
        nb = json.loads((self.KAGGLE / "fortune_notebook.ipynb").read_text(encoding="utf-8"))
        joined = "\n".join("".join(c.get("source", [])) for c in nb["cells"])
        self.assertIn('MODEL_NAME = "gemini-3.8-flash"', joined)
        self.assertIn("gemini-3-flash-preview", joined)
        self.assertNotIn('MODEL_NAME = "gemini-3.5-flash"', joined)
        self.assertNotIn("Stage Cは `gemini-3.5-flash`", joined)


class TestThinking38StartsAtLow(unittest.TestCase):
    """mts5.68: gemini-3.8-flash は実機（2026-10-14）で thinking_level=minimal が 400 で
    拒否された（「low に下げて再試行します」）。拒否された 400 も RPM 枠を消費するので、
    最初から low で送り、無駄な 1 往復を無くす。"""

    class Fake400(Exception):
        code = 400

    def _backend(self):
        return B.GeminiBackend(model_name="gemini-3.8-flash", api_key="k",
                               verbose=False, backoff_base_s=0.0,
                               requests_per_minute=600.0)

    def test_table(self):
        self.assertTrue(B.GeminiBackend._minimal_unsupported("gemini-3.8-flash"))
        self.assertTrue(B.GeminiBackend._minimal_unsupported("gemini-3.7-flash"))
        self.assertFalse(B.GeminiBackend._minimal_unsupported("gemini-3.6-flash"))
        self.assertFalse(B.GeminiBackend._minimal_unsupported("gemini-3-flash-preview"))
        self.assertFalse(B.GeminiBackend._minimal_unsupported("gemini-3.5-flash-lite"))

    def test_first_call_is_low_and_no_400_roundtrip(self):
        be = self._backend()
        sent = []

        def fake_gen(sys_p, usr_p, temp, mt, seed, model=None):
            kw = be._thinking_kwargs(model)
            sent.append(dict(kw))
            if kw.get("thinking_level") == "minimal":
                raise self.Fake400("400: thinking_level minimal not supported")
            return "ok"

        be._generate_once = fake_gen
        self.assertEqual(be.generate("sys", "usr"), "ok")
        self.assertEqual(sent, [{"thinking_level": "low"}], "1 往復目から low")
        self.assertFalse(be._thinking_downgraded)
        self.assertFalse(be._thinking_unsupported)

    def test_low_rejected_is_still_relaxed_to_removed(self):
        be = self._backend()
        sent = []

        def fake_gen(sys_p, usr_p, temp, mt, seed, model=None):
            kw = be._thinking_kwargs(model)
            sent.append(dict(kw))
            if kw:
                raise self.Fake400("400: thinking_level is not supported")
            return "ok"

        be._generate_once = fake_gen
        self.assertEqual(be.generate("sys", "usr"), "ok")
        self.assertEqual(sent, [{"thinking_level": "low"}, {}])
        self.assertTrue(be._thinking_unsupported)


if __name__ == "__main__":
    unittest.main()
