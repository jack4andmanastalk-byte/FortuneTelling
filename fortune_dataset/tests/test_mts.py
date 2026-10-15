# -*- coding: utf-8 -*-
"""MTS Phase 1–3: モデル計画・並列・進捗監視・段階 B/C（lite / 最上位 flash）。"""
from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from fortunelib.backend import MockBackend, ResponseTimeoutError
from fortunelib.batch_runner import load_csv
from fortunelib.mts import (
    Progress, ProgressMonitor, group_slugs_by_model,
    load_model_plan, make_mock_backends, model_for_slug, rpm_for_model,
    backoff_503_s, make_gemini_backend, run_person_mts, run_slugs_mts,
    run_stage_b_mts, run_stage_c_mts, stage_a_response_timeout,
    scan_results_dir, stage_b_assignment, stage_c_model,
    verify_stage_a_files, verify_stage_b_files,
)
from fortunelib.pipeline import PipelineContext, run_divination
from fortunelib.profile import normalize_input
from fortunelib.registry import REGISTRY, all_slugs, main_slugs
from tests.fixtures.consultation import CONSULTATION
from tests.fixtures.consultation import CONSULTATION, CONSULTATION_ALT


def _make_ctx(backend=None, raw=None) -> PipelineContext:
    raw = raw or {
        "birth": {"date": "1990-01-15", "time": "", "place": ""},
        "gender": "M", "blood_type": "A",
        "name_kanji": "山田 太郎", "name_kana": "やまだ たろう",
        "partner": {"date": "1991-07-03", "time": "", "place": ""},
        "consultation": CONSULTATION,
    }
    ni = normalize_input(raw)
    facts = {"太陽星座": "山羊座", "ライフパス": 8, "本命星": "二黒土星"}
    calc = {
        "zodiac": {"sign": "山羊座"},
        "kyusei": {"honmei": "二黒土星"},
        "blood": {"type": "A"},
        "weton": {"weton_name": "月曜・Pahing"},
        "tarot": {"spread": "three", "cards": [{"name_ja": "節制"}]},
    }
    tmp = Path(tempfile.mkdtemp())
    return PipelineContext(
        inputs=ni, profile_facts=facts, calc_results=calc,
        consultation=raw.get("consultation", ""),
        results_dir=tmp / "results",
        summary_path=tmp / "profile_summary.json",
        backend=backend,
        seed=42,
        summary_lock=threading.Lock(),
    )


class TestModelPlan(unittest.TestCase):
    def test_covers_main_52_exactly_once(self):
        plan = load_model_plan()
        mapped = set(plan["slug_to_model"])
        self.assertEqual(mapped, set(main_slugs()))
        self.assertEqual(len(mapped), 52)
        self.assertEqual(plan["deferred"], ["deities"])
        self.assertIn("deities", all_slugs())
        self.assertNotIn("deities", mapped)

    def test_no_duplicate_slugs_in_models(self):
        plan = load_model_plan()
        seen = []
        for spec in plan["models"].values():
            seen.extend(spec["slugs"])
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(set(seen), set(main_slugs()))

    def test_counts_match_plan(self):
        """配分は model_plan.json が正本（**mts5.65 で 20/32 → 26/26 の等分に再配分**）

        経緯: mts5.6 は 2026-09-24 の実測（3.1-lite は 27件中14件が 503＝成功率48%、
        3.5-lite は 23件が失敗0）で 3.5-lite 寄りの 18/32 にし、mts5.34 で 20/32。
        mts5.65（2026-10-01）は mts5.34 の間隔調整（12/分・5.0秒）後の mts5.64 実機で
        **両レーンの 503 が 0件・打ち切りが 8対8** だったため、優劣の根拠が消えた
        （むしろ片側だけ混雑したときに全体が待たされる）として **26/26** へ戻した。
        """
        plan = load_model_plan()
        n = {m: len(s["slugs"]) for m, s in plan["models"].items()}
        self.assertNotIn("gemma-4-26b-a4b-it", n)
        self.assertNotIn("gemma-4-31b-it", n)
        # mts5.65: lite 2レーンを等分（26/26）。上位レーンは Stage C 専用で 0。
        self.assertEqual(n["gemini-3.1-flash-lite"], 26)
        self.assertEqual(n["gemini-3.5-flash-lite"], 26)
        # mts5.67: 上位レーンは 3.8-flash／3.6-flash／3-flash-preview の3本（非推奨の 3.5-flash は撤去）
        self.assertEqual(n["gemini-3.8-flash"], 0)
        self.assertEqual(n["gemini-3.6-flash"], 0)
        self.assertEqual(n["gemini-3-flash-preview"], 0)
        self.assertNotIn("gemini-3.5-flash", n)
        self.assertNotIn("gemini-3.7-flash", n)
        self.assertNotIn("gemini-3-flash", n)

    def test_stage_b_axis_defaults(self):
        """mts5.65: **クラスタ単位の上書きを外し**、軸の既定（method→3.1-lite／culture→3.5-lite）だけにする

        経緯: mts5.8 は mts5.7 の1回の 503 で M-A を 3.5-lite へ移した。mts5.65 では
        mts5.64 実機（lite レーン 503 0件・打ち切り 8対8）で優劣が無く、上書きのままだと
        **単位数が 21/83 に偏る**（method 5クラスタ＝52単位・culture 6クラスタ＝52単位）ため、
        既定へ戻して **52単位ずつ**に揃えた。`cluster_to_model` を足せば元に戻せる。
        """
        plan = load_model_plan()
        asg = stage_b_assignment(plan)
        self.assertEqual(len([j for v in asg.values() for j in v]), 11)
        self.assertNotIn("cluster_to_model", plan["stage_b"])
        # method の5クラスタは 3.1-lite、culture の6クラスタは 3.5-lite（既定）
        self.assertEqual(sorted(j[1] for j in asg["gemini-3.1-flash-lite"]),
                         ["M-A", "M-B", "M-C", "M-D", "M-E"])
        self.assertEqual(len(asg["gemini-3.5-flash-lite"]), 6)
        self.assertTrue(all(a == "culture" for a, _ in asg["gemini-3.5-flash-lite"]))

    def test_stage_b_cluster_override_still_supported(self):
        """上書きの機構そのものは残す（戻すときは `cluster_to_model` を足すだけ）"""
        plan = load_model_plan()
        patched = dict(plan)
        patched["stage_b"] = dict(plan["stage_b"])
        patched["stage_b"]["cluster_to_model"] = {
            "M-A": "gemini-3.5-flash-lite", "M-D": "gemini-3.5-flash-lite",
            "M-E": "gemini-3.5-flash-lite"}
        asg = stage_b_assignment(patched)
        for cid in ("M-A", "M-D", "M-E"):
            self.assertIn(("method", cid), asg["gemini-3.5-flash-lite"])
        self.assertEqual(sorted(j[1] for j in asg["gemini-3.1-flash-lite"]),
                         ["M-B", "M-C"])
        self.assertEqual(len(asg["gemini-3.5-flash-lite"]), 9)

    def test_synastry_model(self):
        """mts5.34（案B）: 相性系2占術は lite レーンへ（上位レーンは Stage C 用に温存）。"""
        self.assertEqual(model_for_slug("synastry"), "gemini-3.1-flash-lite")
        self.assertEqual(model_for_slug("parimicham"), "gemini-3.1-flash-lite")
        self.assertIsNone(model_for_slug("deities"))

    def test_rpm(self):
        # mts5.34（案B）: lite は 12/分＝5.0秒間隔（上限15/分に対して約20%の余裕）
        self.assertEqual(rpm_for_model("gemini-3.1-flash-lite"), 12)
        self.assertEqual(rpm_for_model("gemini-3.5-flash-lite"), 12)
        # mts5.67: 上位3レーンは旧 3.5-flash と同じ 5/分（無料枠の実数が未確認のため保守的に）
        self.assertEqual(rpm_for_model("gemini-3.8-flash"), 5)
        self.assertEqual(rpm_for_model("gemini-3.6-flash"), 5)
        self.assertEqual(rpm_for_model("gemini-3-flash-preview"), 5)

    def test_group_skips_deferred(self):
        g = group_slugs_by_model(list(all_slugs()))
        flat = [s for v in g.values() for s in v]
        self.assertNotIn("deities", flat)
        self.assertEqual(len(flat), 52)


class TestStageAPacingPolicy(unittest.TestCase):
    """mts5.34（案B・2026-09-27 ユーザー決定）: Stage A のペースと割当の方針を固定する。

    根拠（mts5.32 の実機）: **429 は 0件**で、`（RPM制限待ち）` は上限に達しないよう手前で
    調整していたもの（64回・合計118秒・平均1.8秒）。上位レーン（5 RPM＝12秒間隔）は
    2占術（synastry/parimicham）の1件あたり25.6秒の支配要因で、しかも 404 の切替も起きた。
    そのため ①lite の間隔を 5.0秒（12/分）に広げ、②相性系2占術を lite へ移した。
    戻すときは model_plan.json の rpm 2行と slug_to_model 2行だけ（このテストが検知する）。
    """

    def test_stage_a_lanes_have_sufficient_interval(self):
        """Stage A の全レーンが 5秒以上の間隔（＝12/分以下）で回っていること。"""
        plan = load_model_plan()
        for lane in set(plan["slug_to_model"].values()):
            interval = 60.0 / rpm_for_model(lane, plan)
            self.assertGreaterEqual(
                interval, 5.0,
                f"{lane} の間隔が 5秒未満です（mts5.34 で 12/分へ落とした）")

    def test_no_divination_on_five_rpm_lane(self):
        """5 RPM（12秒間隔）の上位レーンに Stage A の占術を割り当てない。"""
        plan = load_model_plan()
        slow = [m for m, spec in plan["models"].items()
                if float(spec.get("rpm", 99)) <= 5]
        self.assertEqual(
            sorted(s for m in slow for s in plan["models"][m]["slugs"]), [],
            "5 RPM のレーンに Stage A の占術が載っています（mts5.34 で外した）")
        # 上位モデル自体は Stage C / 神々 / フォールバック用に残す（mts5.67: 3.8-flash）
        self.assertEqual(stage_c_model(plan), "gemini-3.8-flash")

    def test_every_slug_can_escalate_to_premium(self):
        """品質の逃げ道: 各占術のフォールバック連鎖が上位モデルへ届くこと。

        lite の出力が字数・必須事項の検証に落ちた場合、backend は同じモデルを
        再試行したうえで連鎖の次（mts5.67: gemini-3.8-flash → gemini-3.6-flash →
        gemini-3-flash-preview）へ移る。
        """
        plan = load_model_plan()
        premium = {"gemini-3.8-flash", "gemini-3.6-flash", "gemini-3-flash-preview"}
        for slug, lane in plan["slug_to_model"].items():
            chain = list(plan["models"][lane].get("fallback", []))
            self.assertTrue(
                premium & set(chain),
                f"{slug}（{lane}）のフォールバックに上位モデルがありません: {chain}")
            # 上位への逃げ道はご指定の順（3.8 → 3.6 → 3-flash-preview）
            self.assertEqual([m for m in chain if m in premium],
                             ["gemini-3.8-flash", "gemini-3.6-flash",
                              "gemini-3-flash-preview"], f"{slug}（{lane}）: {chain}")

    def test_pair_divinations_stay_on_lite(self):
        """相性系2占術（2人分の入力）が lite のままであること。"""
        for slug in ("synastry", "parimicham"):
            lane = model_for_slug(slug)
            self.assertTrue(lane.endswith("-lite"),
                            f"{slug} が lite 以外に戻っています: {lane}")


class _LaneBackend(MockBackend):
    """速度を制御できる MockBackend（アイドル・スティールの検証用）。"""

    def __init__(self, delay: float = 0.0, fail_calls: set[int] | None = None):
        super().__init__()
        self.delay = delay
        self.fail_calls = set(fail_calls or ())
        self.call_no = 0
        self.started: list[float] = []

    def generate(self, *a, **k):
        self.call_no += 1
        self.started.append(time.monotonic())
        if self.call_no in self.fail_calls:
            e = RuntimeError("503 UNAVAILABLE. high demand")
            e.code = 503
            raise e
        if self.delay:
            time.sleep(self.delay)
        return super().generate(*a, **k)


def _lane_plan(assign: dict, *, pull_min: int | None = 3) -> dict:
    """slug→モデルの割当を差し替えたプラン（stage_a.pull の有無も切り替える）。"""
    base = load_model_plan()
    plan = {k: v for k, v in base.items()}
    plan["models"] = {m: dict(spec) for m, spec in base["models"].items()}
    plan["slug_to_model"] = dict(assign)
    if pull_min is None:
        plan.pop("stage_a", None)
    else:
        plan["stage_a"] = {"pull": {"models": ["gemini-3.1-flash-lite",
                                               "gemini-3.5-flash-lite"],
                                    "min_backlog": pull_min}}
    return plan


def _no_pull_plan() -> dict:
    """アイドル・スティール（mts5.8）を切ったプラン。

    レーンごとの件数・呼び出し回数を検証するテストは、引き取りが入ると本来の
    意図（担当どおりに処理される）が揺れるため、明示的に切って基準を固定する。
    引き取り自体は TestStageAIdleSteal と、既定プランを使う統合テストで確認する。
    """
    plan = json.loads(json.dumps(load_model_plan()))
    plan.pop("stage_a", None)
    return plan


class TestStageAIdleSteal(unittest.TestCase):
    """mts5.8: 空いたレーンが他レーンの残りを引き取る（アイドル・スティール）。

    根拠: mts5.7 の実測で 3.1-lite レーンが 503 の待機で 371.8 秒かかる間、
    3.5-lite レーンは 389.4 秒で自分の 32 件を終えて約177秒アイドルだった。
    """

    SLOW = ["seiza", "eto", "kyusei", "numerology_birth", "tantra", "anka",
            "blood", "animal"]
    FAST = ["rokusei", "weton"]

    def _setup(self, *, pull_min=3, fast_delay=0.0, slow_delay=0.25,
               fast_fail: set[int] | None = None):
        assign = {s: "gemini-3.1-flash-lite" for s in self.SLOW}
        assign.update({s: "gemini-3.5-flash-lite" for s in self.FAST})
        plan = _lane_plan(assign, pull_min=pull_min)
        backends = make_mock_backends(plan)
        backends["gemini-3.1-flash-lite"] = _LaneBackend(delay=slow_delay)
        backends["gemini-3.5-flash-lite"] = _LaneBackend(delay=fast_delay,
                                                        fail_calls=fast_fail)
        prog = Progress()
        ctx = _make_ctx()
        items = run_slugs_mts(self.SLOW + self.FAST, ctx, backends, plan=plan,
                              progress=prog, verbose=False)
        return plan, backends, prog, items

    def test_idle_lane_pulls_backlog_from_slow_lane(self):
        plan, backends, prog, items = self._setup()
        fast = backends["gemini-3.5-flash-lite"]
        snap = prog.snapshot()
        # 速いレーンは自分の2件だけでなく、遅いレーンの残りも引き取っている
        self.assertGreater(len(fast.calls), len(self.FAST))
        pulls = snap["pulls"]
        self.assertTrue(pulls)
        self.assertTrue(all(p["from_model"] == "gemini-3.1-flash-lite"
                            and p["by_model"] == "gemini-3.5-flash-lite"
                            for p in pulls))
        self.assertEqual(snap["workers"]["gemini-3.5-flash-lite"]["pulled"],
                         len(pulls))
        # 引き取り1件ずつの所要秒が記録される（mts5.8: 次回以降の分析用）
        self.assertTrue(all(isinstance(p["sec"], (int, float)) and p["sec"] >= 0
                            for p in pulls), pulls[:2])
        # 元レーンの履歴にも「引き取った側」が残る（担当の内訳を後から追える）
        hist = snap["workers"]["gemini-3.1-flash-lite"]["history"]
        self.assertTrue(any(h.get("pulled_by") == "gemini-3.5-flash-lite"
                            for h in hist))
        # 集計は元レーンへ（二重計上しない）: 各レーンの done は担当件数どおり
        self.assertEqual(snap["workers"]["gemini-3.1-flash-lite"]["done"],
                         len(self.SLOW))
        self.assertEqual(snap["workers"]["gemini-3.5-flash-lite"]["done"],
                         len(self.FAST))
        self.assertEqual(snap["totals"]["done"], len(self.SLOW) + len(self.FAST))
        # 全 slug が1回ずつ完走し、成功している
        slugs = sorted(r["slug"] for r in items)
        self.assertEqual(slugs, sorted(self.SLOW + self.FAST))
        self.assertEqual([r["status"] for r in items],
                         ["ok"] * len(self.SLOW + self.FAST))
        # 引き取り分はどのモデルが実行したかが結果に残る
        pulled = [r for r in items if r.get("pulled_from")]
        self.assertEqual(len(pulled), len(pulls))

    def test_pull_is_disabled_without_config(self):
        plan, backends, prog, items = self._setup(pull_min=None)
        fast = backends["gemini-3.5-flash-lite"]
        self.assertEqual(len(fast.calls), len(self.FAST))
        self.assertEqual(prog.snapshot()["pulls"], [])
        self.assertEqual(sorted(r["slug"] for r in items),
                         sorted(self.SLOW + self.FAST))

    def test_pull_requires_min_backlog(self):
        """残りが閾値未満なら引き取らない（終わり際の取り合いを防ぐ）。"""
        plan, backends, prog, items = self._setup(pull_min=99)
        fast = backends["gemini-3.5-flash-lite"]
        self.assertEqual(len(fast.calls), len(self.FAST))
        self.assertEqual(prog.snapshot()["pulls"], [])

    def test_premium_lane_never_pulls(self):
        """引き取り手は stage_a.pull.models の lite レーンだけ（プレミアムは関与しない）。"""
        assign = {s: "gemini-3.1-flash-lite" for s in self.SLOW}
        assign.update({s: "gemini-3.5-flash-lite" for s in self.FAST})
        plan = _lane_plan(assign)
        backends = make_mock_backends(plan)
        backends["gemini-3.1-flash-lite"] = _LaneBackend(delay=0.25)
        backends["gemini-3.5-flash-lite"] = _LaneBackend(delay=0.0)
        prog = Progress()
        run_slugs_mts(self.SLOW + self.FAST, _make_ctx(), backends, plan=plan,
                      progress=prog, verbose=False)
        for m in ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3-flash-preview"):
            self.assertEqual(len(backends[m].calls), 0, m)
        self.assertTrue(prog.snapshot()["pulls"])

    def test_pulled_item_503_goes_to_premium_without_bounce(self):
        """引き取った仕事が 503 でも、同じ2モデルを往復せず次のモデルへ渡る。"""
        # 速いレーンの呼び出し1・2は自分の担当（FAST の2件）。3回目＝最初の引き取りを 503 にする。
        plan, backends, prog, items = self._setup(fast_fail={3})
        premium = backends["gemini-3.8-flash"]
        self.assertGreaterEqual(len(premium.calls), 1)
        snap = prog.snapshot()
        self.assertTrue(any(p["status"] == "stolen" and not p["final"]
                            for p in snap["pulls"]))
        self.assertEqual(sorted(r["slug"] for r in items),
                         sorted(self.SLOW + self.FAST))
        self.assertTrue(all(r["status"] == "ok" for r in items))
        owner = snap["workers"]["gemini-3.1-flash-lite"]
        self.assertEqual(owner["done"], len(self.SLOW))
        self.assertEqual(owner["ok"], len(self.SLOW))
        self.assertEqual(owner["failed"], 0)
        totals = snap["totals"]
        self.assertEqual(totals["done"], totals["ok"] + totals["failed"]
                         + totals["skipped"] + totals["unavailable"])
        self.assertEqual(snap["all_done"], True)


class _TimeoutAwareBackend(MockBackend):
    """`response_timeout_s` を守る MockBackend（応答の打ち切りの検証用）。

    実物（GeminiBackend）と同じ契約にする: 生成が制限時間を超えたら
    `ResponseTimeoutError` を送出する（このバックエンドでは再試行しない）。
    ここで見たいのは**スケジューラ側**（打ち切りを503と同じ経路で別レーンへ回し、
    進捗と結果に残す）なので、時間は待たずに条件だけで判定する。
    """

    def __init__(self, slow_calls: set[int] | None = None,
                 slow_sec: float = 5.0, delay: float = 0.0):
        super().__init__()
        self.response_timeout_s = None
        self.slow_calls = set(slow_calls or ())
        self.slow_sec = slow_sec
        self.delay = delay
        self.call_no = 0

    def generate(self, *a, **k):
        self.call_no += 1
        sec = self.slow_sec if self.call_no in self.slow_calls else self.delay
        limit = getattr(self, "response_timeout_s", None)
        if limit and sec > limit:
            raise ResponseTimeoutError(
                f"応答が{limit:.0f}秒を超えました（打ち切り・別モデルへ回します）")
        if sec:
            time.sleep(sec)
        return super().generate(*a, **k)


def _timeout_plan(assign: dict, *, seconds: float | None = 0.1,
                  models: list[str] | None = None,
                  pull_min: int | None = None) -> dict:
    """slug→モデル割当＋応答の打ち切り設定を差し替えたプラン（mts5.11）。

    打ち切りの検証では**アイドル・スティールを切る**（引き取りが先に走ると、
    どのレーンで切ったかが揺れてテストが不安定になるため）。
    """
    base = load_model_plan()
    plan = {k: v for k, v in base.items()}
    plan["models"] = {m: dict(spec) for m, spec in base["models"].items()}
    plan["slug_to_model"] = dict(assign)
    sa: dict = {}
    if pull_min is not None:
        sa["pull"] = {"models": ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite"],
                      "min_backlog": pull_min}
    if seconds is not None:
        sa["response_timeout"] = {
            "models": models or ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite"],
            "seconds": seconds,
        }
    if sa:
        plan["stage_a"] = sa
    else:
        plan.pop("stage_a", None)
    return plan


class TestStageAResponseTimeout(unittest.TestCase):
    """mts5.11: 応答が制限時間を超えたら打ち切り、503と同じ経路で別レーンへ回す。

    根拠: mts5.9 の実測で、3.1-lite の 18件のうち5件が 26.9〜78.2秒（計220.1秒＝
    レーンの83%）を占め、最長の78.2秒は 503 を伴わないサーバ側の遅延だった
    （docs/architecture.md「信頼性の仕組み」）。
    """

    SLOW = ["seiza", "eto"]          # 3.1-lite レーンに置く slug
    FAST = ["rokusei"]               # 3.5-lite レーンに置く slug

    def _setup(self, *, slow_calls=(1,), seconds=0.1, models=None,
               assign=None, slow_sec=5.0):
        assign = assign or {**{s: "gemini-3.1-flash-lite" for s in self.SLOW},
                            **{s: "gemini-3.5-flash-lite" for s in self.FAST}}
        plan = _timeout_plan(assign, seconds=seconds, models=models)
        backends = make_mock_backends(plan)
        backends["gemini-3.1-flash-lite"] = _TimeoutAwareBackend(
            slow_calls=slow_calls, slow_sec=slow_sec)
        backends["gemini-3.5-flash-lite"] = _TimeoutAwareBackend()
        prog = Progress()
        ctx = _make_ctx()
        items = run_slugs_mts(self.SLOW + self.FAST, ctx, backends, plan=plan,
                              progress=prog, verbose=False)
        return plan, backends, prog, items

    def test_slow_response_is_cut_and_handed_to_other_lane(self):
        plan, backends, prog, items = self._setup(slow_calls=(1,))
        snap = prog.snapshot()
        # 打ち切りが記録され、実行者は別レーンになっている
        self.assertEqual(len(snap["timeouts"]), 1)
        cut = snap["timeouts"][0]
        self.assertEqual(cut["from_model"], "gemini-3.1-flash-lite")
        self.assertIn(cut["slug"], self.SLOW)
        done = [r for r in items if r.get("slug") == cut["slug"]][0]
        self.assertTrue(done.get("timed_out"))
        self.assertEqual(done.get("status"), "ok")
        self.assertEqual(done.get("stolen_from"), "gemini-3.1-flash-lite")
        self.assertEqual(done.get("run_model"), "gemini-3.5-flash-lite")
        # 元レーンへ計上され、**失敗扱いにはしない**（打ち切り＝予定どおりの移譲）
        w = snap["workers"]["gemini-3.1-flash-lite"]
        self.assertEqual(w["failed"], 0)
        self.assertEqual(w["handed_over"], 1)  # 移譲イベントは結果数と別枠
        self.assertEqual(w["done"], w["ok"] + w["skipped"] + w["unavailable"]
                         + w["failed"])
        self.assertEqual(w["done"], 2)   # 担当2件（1件は打ち切り→別レーンで成功）
        self.assertEqual(w["ok"], 2)
        totals = snap["totals"]
        self.assertEqual(totals["done"], totals["ok"] + totals["failed"]
                         + totals["skipped"] + totals["unavailable"])
        self.assertEqual(snap["handover_events"], 1)

    def test_timeout_setting_is_restored_after_run(self):
        """段階 A の制限時間は実行後に必ず戻す（段階 B/C へ漏らさない）。"""
        plan, backends, prog, items = self._setup(slow_calls=(1,))
        for be in backends.values():
            self.assertIsNone(be.response_timeout_s)

    def test_timeout_is_ignored_when_only_one_lane(self):
        """回し先が無い（対象レーンが1本）ときは効かせない＝従来どおり完走する。"""
        plan, backends, prog, items = self._setup(
            slow_calls=(1,), models=["gemini-3.1-flash-lite"], slow_sec=0.05)
        self.assertEqual(prog.snapshot()["timeouts"], [])
        self.assertTrue(all(not r.get("timed_out") for r in items))
        # 遅い呼び出しは打ち切られず、そのまま完走している（再生成の分だけ回る）
        self.assertGreaterEqual(backends["gemini-3.1-flash-lite"].call_no, 1)

    def test_disabled_without_config(self):
        """設定が無ければ従来どおり（応答が返るまで待つ）。"""
        plan, backends, prog, items = self._setup(slow_calls=(1,), seconds=None,
                                                  slow_sec=0.05)
        self.assertEqual(prog.snapshot()["timeouts"], [])
        self.assertEqual(prog.snapshot()["pulls"], [])   # 引き取りも起きない
        self.assertGreaterEqual(backends["gemini-3.1-flash-lite"].call_no, 1)

    def test_non_target_lane_is_not_cut(self):
        """対象外のレーン（プレミアム等）は打ち切らない（正当に20〜30秒かかる）。"""
        assign = {"eto": "gemini-3.8-flash", "seiza": "gemini-3-flash-preview"}
        plan = _timeout_plan(assign, seconds=0.1,
                             models=["gemini-3.1-flash-lite",
                                     "gemini-3.5-flash-lite"])
        backends = make_mock_backends(plan)
        backends["gemini-3.8-flash"] = _TimeoutAwareBackend(slow_calls=())
        backends["gemini-3-flash-preview"] = _TimeoutAwareBackend(slow_calls=(1,),
                                                                 slow_sec=0.05)
        prog = Progress()
        items = run_slugs_mts(["eto", "seiza"], _make_ctx(), backends,
                              plan=plan, progress=prog, verbose=False)
        self.assertEqual(prog.snapshot()["timeouts"], [])
        self.assertTrue(all(r.get("status") == "ok" for r in items))

    def test_503_wait_defaults_to_plan_value(self):
        """503 の待機は model_plan.json の reliability が正（mts5.11 で 5秒）。"""
        plan = _lane_plan({s: "gemini-3.1-flash-lite" for s in self.SLOW})
        self.assertEqual(backoff_503_s(plan), 5.0)
        be = make_gemini_backend("gemini-3.1-flash-lite", plan=plan,
                                 api_key="test-key", verbose=False)
        self.assertEqual(be.backoff_base_s, 5.0)
        plan.pop("reliability", None)
        self.assertEqual(backoff_503_s(plan), 20.0)      # 設定を消すと従来へ戻る
        self.assertIsNone(stage_a_response_timeout(plan)[1])


class TestProgressFinalAccounting(unittest.TestCase):
    """移譲・引き取りは中間イベントで、done/結果カウンタは最終状態のみ数える。"""

    def _assert_final_counters_match(self, snapshot):
        totals = snapshot["totals"]
        self.assertEqual(totals["done"], totals["ok"] + totals["failed"]
                         + totals["skipped"] + totals["unavailable"])
        for worker in snapshot["workers"].values():
            self.assertEqual(worker["done"], worker["ok"] + worker["failed"]
                             + worker["skipped"] + worker["unavailable"])

    def test_handover_waits_for_fallback_final_result(self):
        progress = Progress()
        progress.register("owner", 1)
        progress.register("fallback", 0)
        progress.start_slug("owner", "seiza")
        progress.steal_enqueued()
        progress.handover_finished("owner", "seiza", error="timeout")

        mid = progress.snapshot()
        self.assertEqual(mid["workers"]["owner"]["done"], 0)
        self.assertEqual(mid["workers"]["owner"]["handed_over"], 1)
        self.assertFalse(mid["all_done"])

        progress.finish_task("owner", "fallback", "seiza", "ok")
        progress.steal_finished()
        final = progress.snapshot()
        self.assertTrue(final["all_done"])
        self.assertEqual(final["workers"]["owner"]["ok"], 1)
        self.assertEqual(final["workers"]["owner"]["failed"], 0)
        self.assertEqual(final["handover_events"], 1)
        self._assert_final_counters_match(final)

    def test_pulled_timeout_is_not_a_final_failure(self):
        progress = Progress()
        progress.register("origin", 1)
        progress.register("puller", 0)
        progress.register("fallback", 0)
        progress.steal_enqueued()
        progress.pull_started("origin", "puller", "tarot")
        progress.pull_finished("origin", "puller", "tarot", "stolen",
                               error="timeout", owner_model="origin")

        mid = progress.snapshot()
        self.assertEqual(mid["workers"]["origin"]["done"], 0)
        self.assertEqual(mid["workers"]["origin"]["failed"], 0)
        self.assertEqual(mid["pull_open"], 0)
        self.assertEqual(mid["pulls"][0]["status"], "stolen")
        self.assertFalse(mid["pulls"][0]["final"])

        progress.finish_task("origin", "fallback", "tarot", "ok",
                             pulled_by="puller")
        progress.steal_finished()
        final = progress.snapshot()
        self.assertTrue(final["all_done"])
        self.assertEqual(final["workers"]["origin"]["ok"], 1)
        self.assertEqual(final["workers"]["origin"]["failed"], 0)
        self.assertEqual(final["workers"]["puller"]["pulled"], 1)
        self._assert_final_counters_match(final)


class TestRunSlugsMts(unittest.TestCase):
    def test_parallel_writes_distinct_files(self):
        backends = make_mock_backends()
        ctx = _make_ctx()
        slugs = ["eto", "seiza", "tarot", "synastry", "pendulum"]
        items = run_slugs_mts(slugs, ctx, backends, plan=_no_pull_plan(), verbose=False)
        self.assertEqual(len(items), 5)
        statuses = {r["slug"]: r["status"] for r in items}
        self.assertEqual(statuses["eto"], "ok")
        self.assertEqual(statuses["seiza"], "ok")
        self.assertEqual(statuses["tarot"], "ok")
        self.assertEqual(statuses["synastry"], "ok")
        self.assertEqual(statuses["pendulum"], "ok")
        mds = list(ctx.results_dir.glob("*.md"))
        self.assertEqual(len(mds), 5)
        # モデルごとに独立 backend（呼び出しが混線しない）
        self.assertGreater(len(backends["gemini-3.1-flash-lite"].calls), 0)  # eto, seiza
        self.assertGreater(len(backends["gemini-3.5-flash-lite"].calls), 0)  # tarot
        # mts5.34: synastry は 3.1-lite（相性系を lite へ移した）
        self.assertGreaterEqual(len(backends["gemini-3.1-flash-lite"].calls), 2)
        self.assertEqual(len(backends["gemini-3-flash-preview"].calls), 0)

    def test_backends_are_not_shared_across_models(self):
        backends = make_mock_backends()
        ids = {id(b) for b in backends.values()}
        self.assertEqual(len(ids), len(backends))

    def test_skip_guard_still_works(self):
        backends = make_mock_backends()
        ctx = _make_ctx()
        run_slugs_mts(["eto"], ctx, backends, plan=_no_pull_plan(),
                      verbose=False)
        n1 = len(backends["gemini-3.5-flash-lite"].calls)
        items = run_slugs_mts(["eto"], ctx, backends, plan=_no_pull_plan(),
                              verbose=False)
        self.assertEqual(items[0]["status"], "skipped")
        self.assertEqual(len(backends["gemini-3.5-flash-lite"].calls), n1)

    def test_one_slug_error_does_not_stop_others(self):
        class Boom(MockBackend):
            def generate(self, *a, **k):
                raise RuntimeError("boom")

        backends = make_mock_backends()
        backends["gemini-3.1-flash-lite"] = Boom()
        ctx = _make_ctx()
        # mts5.6 の割当では blood が 3.1-lite・tarot が 3.5-lite。
        # 片方のレーンが全滅しても、もう片方は完走すること。
        items = run_slugs_mts(["blood", "tarot"], ctx, backends,
                              plan=_no_pull_plan(), verbose=False)
        by = {r["slug"]: r["status"] for r in items}
        self.assertEqual(by["blood"], "error")
        self.assertEqual(by["tarot"], "ok")

    def test_503_is_stolen_to_fallback_model(self):
        class Boom503(MockBackend):
            def generate(self, *a, **k):
                self.calls.append({"stolen": True})
                e = RuntimeError("503 UNAVAILABLE. high demand")
                e.code = 503
                raise e

        backends = make_mock_backends()
        # mts5.34: synastry の担当は 3.1-lite。最初のレーンを 503 にして
        #            フォールバック連鎖（→3.5-lite→…）へ移譲されることを見る。
        backends["gemini-3.1-flash-lite"] = Boom503()
        ctx = _make_ctx()
        items = run_slugs_mts(["synastry", "seiza"], ctx, backends,
                              plan=_no_pull_plan(), verbose=False)
        by = {r["slug"]: r["status"] for r in items}
        self.assertEqual(by["seiza"], "ok")
        self.assertEqual(by["synastry"], "ok")
        self.assertGreater(len(backends["gemini-3.1-flash-lite"].calls), 0)
        self.assertGreater(len(backends["gemini-3.5-flash-lite"].calls), 0)

    def test_503_both_lites_fall_back_to_premium_no_bounce(self):
        class Boom503(MockBackend):
            def generate(self, *a, **k):
                self.calls.append({"503": True})
                e = RuntimeError("503 UNAVAILABLE. high demand")
                e.code = 503
                raise e

        backends = make_mock_backends()
        backends["gemini-3.1-flash-lite"] = Boom503()
        backends["gemini-3.5-flash-lite"] = Boom503()
        ctx = _make_ctx()
        items = run_slugs_mts(["blood"], ctx, backends,
                              plan=_no_pull_plan(), verbose=False)
        by = {r["slug"]: r["status"] for r in items}
        # blood は 3.1-lite 担当 → 3.5-lite → 3.8-flash（mts5.67）と進み完走する。
        self.assertEqual(by["blood"], "ok")
        self.assertGreater(len(backends["gemini-3.8-flash"].calls), 0)
        # 循環せず、各 lite は元の担当分のみ試行（blood 1件ずつ＋αなし）
        self.assertLessEqual(len(backends["gemini-3.1-flash-lite"].calls), 2)
        self.assertLessEqual(len(backends["gemini-3.5-flash-lite"].calls), 2)

    def test_progress_counts(self):
        backends = make_mock_backends()
        ctx = _make_ctx()
        prog = Progress()
        run_slugs_mts(["eto", "seiza"], ctx, backends, plan=_no_pull_plan(),
                      progress=prog, verbose=False)
        snap = prog.snapshot()
        # mts5.65: eto は 3.1-lite、seiza は 3.5-lite（配分 26/26 の両レーンを踏む）。
        lane1, lane2 = model_for_slug("eto"), model_for_slug("seiza")
        self.assertEqual(snap["workers"][lane1]["done"], 1)
        self.assertEqual(snap["workers"][lane2]["done"], 1)
        self.assertEqual(snap["workers"][lane2]["failed"], 0)
        self.assertEqual(snap["totals"]["done"], 2)

    def test_summary_no_lost_themes_under_parallel(self):
        """G1 を並列実行しても themes が欠けない（summary_lock）。"""
        backends = make_mock_backends()
        ctx = _make_ctx()
        g1 = [s for s in main_slugs() if REGISTRY[s]["group"] == "G1"]
        run_slugs_mts(g1, ctx, backends, plan=_no_pull_plan(), verbose=False)
        data = json.loads(ctx.summary_path.read_text(encoding="utf-8"))
        self.assertEqual(len(data["themes"]), len(g1))

    def test_backend_override_does_not_use_ctx_backend(self):
        ctx_be = MockBackend()
        other = MockBackend()
        ctx = _make_ctx(backend=ctx_be)
        run_divination("eto", ctx, backend=other)
        self.assertEqual(len(ctx_be.calls), 0)
        self.assertGreaterEqual(len(other.calls), 1)


class TestRunPersonMts(unittest.TestCase):
    def test_full_person_mock(self):
        """Kaggle の既定CSV（架空の人物・**400字の相談文**）で Stage A を通しで回す。

        mts5.62（恒久ルール）: 相談内容は短文ではなく約400字の架空の相談文にする。
        短い相談では実機の「長い相談文のサニタイズ・プロンプト埋め込み・表示」が
        テストをすり抜けるため、`kaggle/people_sample.csv` をそのまま入力にする。
        """
        from tests.fixtures.consultation import is_fictional_consultation
        backends = make_mock_backends()
        tmp = Path(tempfile.mkdtemp())
        row = load_csv(Path(__file__).resolve().parent.parent
                       / "kaggle" / "people_sample.csv")[0]
        self.assertTrue(is_fictional_consultation(row["consultation"]),
                        "相談文が400字前後の架空文ではありません")
        res = run_person_mts(row, backends, tmp, verbose=False)
        # 52 種すべて入力充足 → ok（Mock は十分長い本文）
        self.assertEqual(res.error, 0)
        self.assertEqual(res.ok, 52)
        self.assertTrue(Path(res.report).exists())
        mds = list(Path(res.results_dir).glob("*.md"))
        self.assertEqual(len(mds), 52)
        # deities は走っていない
        self.assertFalse(any("deities" in p.name for p in mds))
        prog_path = tmp / row["person_id"] / "progress.json"
        self.assertTrue(prog_path.exists())
        snap = json.loads(prog_path.read_text(encoding="utf-8"))
        self.assertTrue(snap["all_done"])
        self.assertEqual(snap["totals"]["done"], 52)
        check = verify_stage_a_files(res.results_dir)
        self.assertTrue(check["complete"])
        self.assertEqual(check["found"], 52)


class TestSummaryLockSerial(unittest.TestCase):
    def test_lock_serializes_appends(self):
        """summary_lock 無しだと落ちうる競合を、有りなら件数一致。"""
        from fortunelib.pipeline import _append_summary

        ctx = _make_ctx()
        ctx.summary_lock = threading.Lock()
        entry = {"name": "テスト占術", "group": "G1", "slug": "eto"}
        n = 40

        def _go():
            _append_summary(ctx, entry, "abcdefghij" * 10)

        ts = [threading.Thread(target=_go) for _ in range(n)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        data = json.loads(ctx.summary_path.read_text(encoding="utf-8"))
        self.assertEqual(len(data["themes"]), n)


class TestProgressPhase2(unittest.TestCase):
    def test_unavailable_is_not_failed(self):
        backends = make_mock_backends()
        raw = {"birth": {"date": "1990-01-15"}, "consultation": CONSULTATION}
        ctx = _make_ctx(raw=raw)
        prog = Progress()
        items = run_slugs_mts(["blood", "seiza"], ctx, backends, plan=_no_pull_plan(),
                              progress=prog, verbose=False)
        by = {r["slug"]: r["status"] for r in items}
        self.assertEqual(by["blood"], "unavailable")
        self.assertEqual(by["seiza"], "ok")
        # blood は 3.1-lite、seiza は 3.5-lite（mts5.65 の配分 26/26）。
        # eto は mts5.65 で 3.5-lite から 3.1-lite へ戻った（干支レーン参照）。
        w = prog.snapshot()["workers"][model_for_slug("blood")]
        self.assertEqual(w["unavailable"], 1)
        self.assertEqual(w["failed"], 0)
        self.assertEqual(w["ok"], 0)
        w35 = prog.snapshot()["workers"][model_for_slug("seiza")]
        self.assertEqual(w35["ok"], 1)
        self.assertEqual(w35["failed"], 0)

    def test_wait_all_and_format(self):
        backends = make_mock_backends()
        ctx = _make_ctx()
        prog = Progress(stage="A")
        run_slugs_mts(["eto", "seiza"], ctx, backends, plan=_no_pull_plan(),
                      progress=prog, verbose=False)
        self.assertTrue(prog.wait_all(timeout=1.0))
        self.assertTrue(prog.all_done())
        text = prog.format_status()
        self.assertIn("[MTS A]", text)
        self.assertIn("2/2", text)
        tot = prog.totals()
        self.assertEqual(tot["ok"], 2)
        self.assertGreaterEqual(prog.snapshot()["elapsed_s"], 0)

    def test_heartbeat_writes_progress_json(self):
        backends = make_mock_backends()
        ctx = _make_ctx()
        tmp = Path(tempfile.mkdtemp()) / "progress.json"
        prog = Progress()
        run_slugs_mts(
            ["eto", "seiza", "tarot"], ctx, backends, plan=_no_pull_plan(),
            progress=prog, verbose=False, monitor_path=tmp, heartbeat_s=0.05)
        self.assertTrue(tmp.exists())
        snap = json.loads(tmp.read_text(encoding="utf-8"))
        self.assertTrue(snap["all_done"])
        self.assertEqual(snap["totals"]["done"], 3)
        self.assertEqual(snap["stage"], "A")

    def test_monitor_context_manager(self):
        prog = Progress()
        prog.register("m", 1)
        tmp = Path(tempfile.mkdtemp()) / "p.json"
        with ProgressMonitor(prog, path=tmp, interval_s=0.05, verbose=False):
            prog.start_slug("m", "eto")
            time.sleep(0.12)
            prog.finish_slug_named("m", "eto", "ok")
        self.assertTrue(tmp.exists())

    def test_scan_and_verify_folder(self):
        backends = make_mock_backends()
        ctx = _make_ctx()
        slugs = ["eto", "seiza"]
        run_slugs_mts(slugs, ctx, backends, plan=_no_pull_plan(), verbose=False)
        scan = scan_results_dir(ctx.results_dir)
        self.assertEqual(scan["n"], 2)
        check = verify_stage_a_files(ctx.results_dir, slugs)
        self.assertTrue(check["complete"])
        check2 = verify_stage_a_files(ctx.results_dir, slugs + ["tarot"])
        self.assertEqual(check2["missing"], ["tarot"])
        self.assertFalse(check2["complete"])

    def test_history_keeps_slug_names(self):
        backends = make_mock_backends()
        ctx = _make_ctx()
        prog = Progress()
        run_slugs_mts(["eto"], ctx, backends, plan=_no_pull_plan(),
                      progress=prog, verbose=False)
        hist = prog.snapshot()["workers"][model_for_slug("eto")]["history"]
        self.assertEqual(hist[-1]["slug"], "eto")
        self.assertEqual(hist[-1]["status"], "ok")



def _fake_all_raw(td, chars=400) -> Path:
    from fortunelib.registry import REGISTRY
    rd = Path(td) / "results"
    rd.mkdir(parents=True, exist_ok=True)
    for slug, e in REGISTRY.items():
        (rd / f"{e['mcode']}_{slug}_raw.json").write_text(
            json.dumps({"result": {"text": "あ" * chars}}, ensure_ascii=False),
            encoding="utf-8")
    return rd


class TestStageBPlan(unittest.TestCase):
    def test_eleven_jobs_on_two_lites(self):
        asg = stage_b_assignment()
        self.assertEqual(set(asg), {
            "gemini-3.1-flash-lite", "gemini-3.5-flash-lite"})
        jobs = [j for v in asg.values() for j in v]
        self.assertEqual(len(jobs), 11)
        self.assertEqual(len(set(jobs)), 11)
        method = {cid for ax, cid in jobs if ax == "method"}
        culture = {cid for ax, cid in jobs if ax == "culture"}
        self.assertEqual(len(method), 5)
        self.assertEqual(len(culture), 6)
        for m in asg:
            self.assertNotIn("gemma", m)
            self.assertNotIn("3.7", m)

    def test_stage_c_is_top_flash(self):
        """mts5.67（ユーザー決定）: 軸・最終＝3.8-flash（→3.6→3-flash-preview→3.5-lite）、
        神々＝3-flash-preview（旧 gemini-3-flash はこのキーで常に 404 → preview だった実働IDを直書き）。"""
        from fortunelib.mts import stage_c_chain
        m = stage_c_model()
        self.assertEqual(m, "gemini-3.8-flash")
        self.assertNotIn("lite", m)
        self.assertNotIn("gemma", m)
        self.assertEqual(stage_c_chain(), ["gemini-3.8-flash", "gemini-3.6-flash",
                                           "gemini-3-flash-preview",
                                           "gemini-3.5-flash-lite"])
        from fortunelib.mts import (deities_model, deities_chain,
                                   stage_c_deities_model, stage_c_deities_chain)
        self.assertEqual(deities_model(), "gemini-3-flash-preview")
        self.assertEqual(stage_c_deities_model(), "gemini-3-flash-preview")
        self.assertEqual(deities_chain(), ["gemini-3-flash-preview", "gemini-3.8-flash",
                                           "gemini-3.6-flash", "gemini-3.5-flash-lite"])
        self.assertEqual(stage_c_deities_chain()[0], "gemini-3-flash-preview")
        # 非推奨（2026-10）の 3.5-flash／3.7-flash はどの連鎖にも現れない
        for chain in (stage_c_chain(), deities_chain()):
            self.assertNotIn("gemini-3.5-flash", chain)
            self.assertNotIn("gemini-3.7-flash", chain)


class TestStageBMTS(unittest.TestCase):
    FACTS = {"太陽星座": "山羊座", "数秘術（ライフパス）": 8}

    def test_parallel_writes_eleven_cluster_files(self):
        backends = make_mock_backends()
        with tempfile.TemporaryDirectory() as td:
            rd = _fake_all_raw(td)
            out = Path(td)
            r = run_stage_b_mts(rd, out, backends, self.FACTS, "転職",
                                verbose=False)
            self.assertEqual(set(r["axes"]), {"method", "culture"})
            self.assertEqual(sum(len(v) for v in r["per_axis"].values()), 11)
            cd = out / "cluster_reports"
            mid = [p for p in cd.glob("*.md") if not p.name.startswith("AXIS_")]
            self.assertEqual(len(mid), 11)
            self.assertEqual(len(list(cd.glob("*_method.md"))), 5)
            self.assertEqual(len(list(cd.glob("*_culture.md"))), 6)
            check = verify_stage_b_files(out)
            self.assertTrue(check["complete"])
            self.assertGreater(len(backends["gemini-3.1-flash-lite"].calls), 0)
            self.assertGreater(len(backends["gemini-3.5-flash-lite"].calls), 0)
            self.assertEqual(len(backends["gemini-3.8-flash"].calls), 0)

    def test_one_cluster_error_does_not_stop_other_model(self):
        class Boom(MockBackend):
            def generate(self, *a, **k):
                raise RuntimeError("boom")

        backends = make_mock_backends()
        backends["gemini-3.1-flash-lite"] = Boom()
        with tempfile.TemporaryDirectory() as td:
            rd = _fake_all_raw(td)
            with self.assertRaisesRegex(RuntimeError, "段階Bのクラスタ中間レポートが不足"):
                run_stage_b_mts(rd, Path(td), backends, self.FACTS,
                                verbose=False)
            # 生きている 3.5-lite は完走する（culture 6本＝mts5.65 で上書きを外した既定）。
            # Stage C は 3.1-lite 担当の method 5本（M-A〜M-E）が欠けるためブロックされる。
            cd = Path(td) / "cluster_reports"
            self.assertTrue(list(cd.glob("*_culture.md")))
            self.assertEqual(sorted(p.name for p in cd.glob("*_method.md")), [])
            self.assertFalse(verify_stage_b_files(Path(td))["complete"])

    def test_503_cluster_is_transferred_to_fallback_worker(self):
        class Boom503(MockBackend):
            def generate(self, *a, **k):
                self.calls.append({"503": True})
                e = RuntimeError("503 UNAVAILABLE. high demand")
                e.code = 503
                raise e

        backends = make_mock_backends()
        # mts5.65: 3.5-lite の担当は culture 6本（クラスタ上書きを外したため）。
        # いずれもまず 3.5-lite が試行し、503 なら独立した 3.1-lite が引き取る。
        backends["gemini-3.5-flash-lite"] = Boom503()
        with tempfile.TemporaryDirectory() as td:
            rd = _fake_all_raw(td)
            r = run_stage_b_mts(rd, Path(td), backends, self.FACTS,
                                verbose=False)
            self.assertTrue(r["complete"])
            self.assertTrue(r["verification"]["complete"])
            self.assertEqual(sum(len(v) for v in r["per_axis"].values()), 11)
            self.assertEqual(len(r["fallbacks"]), 6)      # mts5.65: culture 6本
            self.assertTrue(all(x["from_model"] == "gemini-3.5-flash-lite"
                                and x["to_model"] == "gemini-3.1-flash-lite"
                                for x in r["fallbacks"]))
            self.assertTrue(all(x["fallback"]
                                for reps in r["per_axis"].values()
                                for x in reps if x["model"] == "gemini-3.1-flash-lite"
                                and x["original_model"] == "gemini-3.5-flash-lite"))
            self.assertEqual(len(backends["gemini-3.5-flash-lite"].calls), 6)

    def test_empty_cluster_response_is_transferred(self):
        backends = make_mock_backends()
        # The two empty responses exercise the initial generation and the
        # length/QC regeneration path before the Stage B fallback catches it.
        backends["gemini-3.5-flash-lite"] = MockBackend(responses=["", ""])
        with tempfile.TemporaryDirectory() as td:
            rd = _fake_all_raw(td)
            r = run_stage_b_mts(rd, Path(td), backends, self.FACTS,
                                verbose=False)
            self.assertTrue(r["complete"])
            self.assertEqual(len(r["fallbacks"]), 6)      # mts5.65: culture 6本
            self.assertEqual(sum(len(v) for v in r["per_axis"].values()), 11)

    def test_503_does_not_bounce_between_fallback_workers(self):
        class Boom503(MockBackend):
            def generate(self, *a, **k):
                self.calls.append({"503": True})
                e = RuntimeError("503 UNAVAILABLE. high demand")
                e.code = 503
                raise e

        backends = make_mock_backends()
        backends["gemini-3.1-flash-lite"] = Boom503()
        backends["gemini-3.5-flash-lite"] = Boom503()
        # 全モデルが 503 のときは、lite 間を往復せず premium も一度だけ
        # 試したうえで、段階B未完了として失敗させる。
        backends["gemini-3.8-flash"] = Boom503()
        backends["gemini-3.6-flash"] = Boom503()
        backends["gemini-3-flash-preview"] = Boom503()
        with tempfile.TemporaryDirectory() as td:
            rd = _fake_all_raw(td)
            with self.assertRaisesRegex(RuntimeError, "段階Bのクラスタ中間レポートが不足"):
                run_stage_b_mts(rd, Path(td), backends, self.FACTS,
                                verbose=False)
            # 各ジョブは各モデルで高々1回ずつ試行され、循環的な移譲嵐は起きない。
            for m in ("gemini-3.1-flash-lite", "gemini-3.5-flash-lite",
                      "gemini-3.8-flash", "gemini-3.6-flash", "gemini-3-flash-preview"):
                self.assertLessEqual(len(backends[m].calls), 11)

    def test_503_lite_falls_back_to_premium(self):
        """両 lite が 503 のとき、段階Bは上位（mts5.67: 3.8-flash → 3.6 → 3-flash-preview）へ移譲して完走する。"""
        class Boom503(MockBackend):
            def generate(self, *a, **k):
                self.calls.append({"503": True})
                e = RuntimeError("503 UNAVAILABLE. high demand")
                e.code = 503
                raise e

        backends = make_mock_backends()
        backends["gemini-3.1-flash-lite"] = Boom503()
        backends["gemini-3.5-flash-lite"] = Boom503()
        with tempfile.TemporaryDirectory() as td:
            rd = _fake_all_raw(td)
            r = run_stage_b_mts(rd, Path(td), backends, self.FACTS,
                                verbose=False)
            self.assertTrue(r["complete"])
            self.assertEqual(sum(len(v) for v in r["per_axis"].values()), 11)
            # 両 lite が 503 でも 3.8-flash へ移譲して全 11 クラスタが完走する。
            self.assertGreater(len(backends["gemini-3.8-flash"].calls), 0)
            # 3.6-flash／3-flash-preview は 3.8 のさらに後続なので、今回は使われない。
            self.assertEqual(len(backends["gemini-3.6-flash"].calls), 0)
            self.assertEqual(len(backends["gemini-3-flash-preview"].calls), 0)

    def test_503_all_lite_and_38flash_falls_back_to_36flash(self):
        """lite 両方と 3.8-flash が 503 でも、3.6-flash（次点）が完走させる。"""
        class Boom503(MockBackend):
            def generate(self, *a, **k):
                self.calls.append({"503": True})
                e = RuntimeError("503 UNAVAILABLE. high demand")
                e.code = 503
                raise e

        backends = make_mock_backends()
        backends["gemini-3.1-flash-lite"] = Boom503()
        backends["gemini-3.5-flash-lite"] = Boom503()
        backends["gemini-3.8-flash"] = Boom503()
        with tempfile.TemporaryDirectory() as td:
            rd = _fake_all_raw(td)
            r = run_stage_b_mts(rd, Path(td), backends, self.FACTS,
                                verbose=False)
            self.assertTrue(r["complete"])
            self.assertEqual(sum(len(v) for v in r["per_axis"].values()), 11)
            self.assertGreater(len(backends["gemini-3.6-flash"].calls), 0)
            self.assertEqual(len(backends["gemini-3-flash-preview"].calls), 0)

    def test_503_all_but_last_upper_lane_falls_back_to_3flash_preview(self):
        """lite 両方と 3.8／3.6 が 503 でも、3-flash-preview が最終手段として完走させる。"""
        class Boom503(MockBackend):
            def generate(self, *a, **k):
                self.calls.append({"503": True})
                e = RuntimeError("503 UNAVAILABLE. high demand")
                e.code = 503
                raise e

        backends = make_mock_backends()
        for m in ("gemini-3.1-flash-lite", "gemini-3.5-flash-lite",
                  "gemini-3.8-flash", "gemini-3.6-flash"):
            backends[m] = Boom503()
        with tempfile.TemporaryDirectory() as td:
            rd = _fake_all_raw(td)
            r = run_stage_b_mts(rd, Path(td), backends, self.FACTS,
                                verbose=False)
            self.assertTrue(r["complete"])
            self.assertEqual(sum(len(v) for v in r["per_axis"].values()), 11)
            self.assertGreater(len(backends["gemini-3-flash-preview"].calls), 0)

    def test_stage_b_reuses_existing_cluster(self):
        """再開時: 既存のクラスタ md は再利用し、残りだけ再生成する。"""
        backends = make_mock_backends()
        with tempfile.TemporaryDirectory() as td:
            rd = _fake_all_raw(td)
            out = Path(td)
            cd = out / "cluster_reports"
            cd.mkdir(parents=True, exist_ok=True)
            jobs = [j for v in stage_b_assignment().values() for j in v]
            method_job = next((a, c) for a, c in jobs if a == "method")
            (cd / f"{method_job[1]}_method.md").write_text(
                "# 中間レポート: 再利用テスト\n\n本文\n", encoding="utf-8")

            r = run_stage_b_mts(rd, out, backends, self.FACTS, verbose=False)

            self.assertTrue(r["complete"])
            total = sum(len(v) for v in r["per_axis"].values())
            self.assertEqual(total, 11)
            reused = [x for reps in r["per_axis"].values() for x in reps
                      if x.get("reused")]
            self.assertEqual(len(reused), 1)
            self.assertEqual(reused[0]["id"], method_job[1])
            # method 軸5本のうち1本は再利用 → 新規生成は4本
            method_fresh = [x for x in r["per_axis"].get("method", [])
                            if not x.get("reused")]
            self.assertEqual(len(method_fresh), 4)
            # 検証も再開後のファイルを「完全」とみなす
            self.assertTrue(r["verification"]["complete"])

    def test_empty_results_raise(self):
        backends = make_mock_backends()
        with tempfile.TemporaryDirectory() as td:
            empty = Path(td) / "results"
            empty.mkdir()
            with self.assertRaises(RuntimeError):
                run_stage_b_mts(empty, Path(td), backends, self.FACTS,
                                verbose=False)

    def test_progress_stage_b(self):
        backends = make_mock_backends()
        prog = Progress(stage="B")
        with tempfile.TemporaryDirectory() as td:
            rd = _fake_all_raw(td)
            run_stage_b_mts(rd, Path(td), backends, self.FACTS,
                            verbose=False, progress=prog)
            snap = prog.snapshot()
            self.assertEqual(snap["stage"], "B")
            self.assertTrue(snap["all_done"])
            self.assertEqual(snap["totals"]["done"], 11)


class TestStageCMTS(unittest.TestCase):
    FACTS = {"太陽星座": "山羊座", "数秘術（ライフパス）": 8}

    def test_final_uses_top_flash_not_lite(self):
        backends = make_mock_backends()
        with tempfile.TemporaryDirectory() as td:
            rd = _fake_all_raw(td)
            out = Path(td)
            b = run_stage_b_mts(rd, out, backends, self.FACTS, "転職",
                                verbose=False)
            n_lite31 = len(backends["gemini-3.1-flash-lite"].calls)
            n_lite35 = len(backends["gemini-3.5-flash-lite"].calls)
            n_flash = len(backends["gemini-3.8-flash"].calls)
            c = run_stage_c_mts(rd, out, backends, self.FACTS, "転職",
                                verbose=False, per_axis=b["per_axis"])
            self.assertTrue(Path(c["file"]).exists())
            self.assertEqual(len(c["axis_summaries"]), 2)
            self.assertIn("統合鑑定レポート",
                          Path(c["file"]).read_text(encoding="utf-8")[:80])
            self.assertEqual(len(backends["gemini-3.1-flash-lite"].calls), n_lite31)
            self.assertEqual(len(backends["gemini-3.5-flash-lite"].calls), n_lite35)
            self.assertGreater(len(backends["gemini-3.8-flash"].calls), n_flash)
            cd = out / "cluster_reports"
            self.assertEqual(len(list(cd.glob("AXIS_*.md"))), 2)

    def test_rejects_lite_as_stage_c_model(self):
        backends = make_mock_backends()
        plan = load_model_plan()
        bad = dict(plan)
        bad["stage_c"] = {"model": "gemini-3.5-flash-lite"}
        with tempfile.TemporaryDirectory() as td:
            rd = _fake_all_raw(td)
            out = Path(td)
            b = run_stage_b_mts(rd, out, backends, self.FACTS, verbose=False)
            with self.assertRaises(RuntimeError):
                run_stage_c_mts(rd, out, backends, self.FACTS,
                                verbose=False, per_axis=b["per_axis"],
                                plan=bad)

    def test_stage_c_rejects_partial_stage_b(self):
        backends = make_mock_backends()
        with tempfile.TemporaryDirectory() as td:
            rd = _fake_all_raw(td)
            out = Path(td)
            cd = out / "cluster_reports"
            cd.mkdir(parents=True)
            jobs = [j for v in stage_b_assignment().values() for j in v]
            for axis, cid in jobs[:-1]:
                (cd / f"{cid}_{axis}.md").write_text("partial", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "段階Cを開始できません"):
                run_stage_c_mts(rd, out, backends, self.FACTS,
                                verbose=False)
            self.assertEqual(len(backends["gemini-3.8-flash"].calls), 0)

    def test_deities_after_final(self):
        backends = make_mock_backends()
        ctx = _make_ctx()
        with tempfile.TemporaryDirectory() as td:
            rd = _fake_all_raw(td)
            ctx.results_dir = rd
            out = Path(td)
            b = run_stage_b_mts(rd, out, backends, self.FACTS, "転職",
                                verbose=False)
            c = run_stage_c_mts(rd, out, backends, ctx.profile_facts, "転職",
                                verbose=False, ctx=ctx, per_axis=b["per_axis"])
            self.assertEqual((c["deities"] or {}).get("status"), "ok")
            self.assertTrue(any(p.name.endswith("deities.md")
                                for p in rd.glob("*.md")))
            self.assertGreater(len(backends["gemini-3-flash-preview"].calls), 0)
            t = Path(c["file"]).read_text(encoding="utf-8")
            self.assertIn("御縁のある神さま", t)

    def test_stage_c_explicit_skip_when_ctx_is_none(self):
        backends = make_mock_backends()
        with tempfile.TemporaryDirectory() as td:
            rd = _fake_all_raw(td)
            out = Path(td)
            b = run_stage_b_mts(rd, out, backends, self.FACTS, "転職",
                                verbose=False)
            c = run_stage_c_mts(rd, out, backends, self.FACTS, "転職",
                                verbose=False, ctx=None, per_axis=b["per_axis"])
            self.assertEqual((c["deities"] or {}).get("status"), "skipped")
            self.assertEqual((c["deities"] or {}).get("reason"), "ctx is None")


class TestPersonABC(unittest.TestCase):
    """Stage A〜C の通し（相談は**400字の架空文**＝mts5.62 の恒久ルール）。"""

    ROW = {
        "person_id": "demo_kirishima_souta",
        "birth_date": "1993-05-17",
        "birth_time": "07:45",
        "birth_place": "北海道",
        "gender": "M",
        "blood_type": "B",
        "name_kanji": "桐島 蒼太",
        "name_kana": "きりしま そうた",
        "partner_date": "1990-02-14",
        "consultation": CONSULTATION,
        "_index": 1,
    }

    def test_default_stays_stage_a_only(self):
        backends = make_mock_backends()
        tmp = Path(tempfile.mkdtemp())
        res = run_person_mts(self.ROW, backends, tmp, verbose=False)
        self.assertEqual(res.ok, 52)
        self.assertFalse((tmp / "demo_kirishima_souta"
                          / "cluster_reports").exists())
        self.assertFalse((tmp / "demo_kirishima_souta"
                          / "synthesis_report.md").exists())
        self.assertFalse(any("deities" in p.name
                             for p in Path(res.results_dir).glob("*.md")))

    def test_abc_writes_synthesis_and_deities(self):
        backends = make_mock_backends()
        tmp = Path(tempfile.mkdtemp())
        res = run_person_mts(self.ROW, backends, tmp, verbose=False, stages="ABC")
        self.assertEqual(res.error, 0, res.failed)
        self.assertEqual(res.ok, 53)  # 52 + deities
        out = tmp / "demo_kirishima_souta"
        self.assertTrue((out / "synthesis_report.md").exists())
        self.assertTrue(verify_stage_b_files(out)["complete"])
        self.assertTrue(any("deities" in p.name
                            for p in Path(res.results_dir).glob("*.md")))
        self.assertGreater(len(backends["gemini-3.1-flash-lite"].calls), 0)
        self.assertGreater(len(backends["gemini-3.8-flash"].calls), 0)
        self.assertGreater(len(backends["gemini-3-flash-preview"].calls), 0)


if __name__ == "__main__":
    unittest.main()
