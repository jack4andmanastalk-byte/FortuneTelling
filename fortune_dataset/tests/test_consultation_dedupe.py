# -*- coding: utf-8 -*-
"""mts5.68（2026-10-14・ユーザー決定 4 件）の回帰テスト。

mts5.67 の実機（`uploads/fortunetell.log`・`uploads/results.zip.txt`）で見つかった
UX と計測の問題への対処を固定する。

 1. HTML の相談内容は**最初の 1 回だけ全文**（統合レポート冒頭の「ご相談」）。
    個別占術の「■ 使用した入力」の「相談内容：…」は 1 行の参照に置き換える
    （実機では 1,703 字の相談文が HTML に 54 回＝約 9 万字の重複）。.md は不変。
 2. 読み物版（Stage D）の元テキストから「ご相談の引用」と「目次（ファイル一覧）」を外し、
    分量の基準も同じ元で測る（実機では元 8,276 字のうち 2,600 字が書き直し対象外で、
    spiritual の下限 6,620 字が構造的に届きにくかった）。検証器も同じ規則で数える。
 3. 段階 C の上位 Flash（3.8/3.6）に応答の打ち切り（60 秒）。終わったら元に戻す。
 4. 408（Request Timeout）は 503 と同じく **1 回だけ待って再試行し、2 回目で別モデルへ**
    （実機では指数バックオフで同じ混雑モデルを叩き直し、約 100 秒の無応答を繰り返した）。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fortunelib import html_report as H
from fortunelib import tone as T
from fortunelib.backend import MockBackend, ResponseTimeoutError
from fortunelib.mts import (
    _is_stealable, _stealable_label, load_model_plan, make_mock_backends,
    run_stage_b_mts, run_stage_c_mts, stage_c_response_timeout,
)
from tests.fixtures.consultation import CONSULTATION

ROOT = Path(__file__).resolve().parent.parent          # fortune_dataset/fortune_dataset
REPO = ROOT.parent                                      # リポジトリ直下（verify/ がある）

SYN_MD = (
    "# 統合鑑定レポート\n\n"
    "**生成**: 2026-10-14T16:49:12+09:00／**分類軸**: culture + method／**参照**: 52種\n\n"
    f"**ご相談**: {CONSULTATION}\n\n"
    "## あなたのプロファイル\n\n"
    "- 太陽星座: 蠍座\n"
    "- 血液型: AB型\n\n"
    "---\n\n"
    "## 総括\n\n"
    "あなたの総合得点は7点中5点です。\n\n"
    "## これからの過ごし方\n\n"
    "2026年の今、準備期間にいます。\n\n"
    "---\n\n"
    "## 軸サマリー\n\n"
    "- **文化圏軸**（1567字）: `cluster_reports/AXIS_culture.md`\n"
    "- **手法軸**（1557字）: `cluster_reports/AXIS_method.md`\n\n"
    "## 分野別の中間レポート\n\n"
    "### 文化圏軸\n"
    "- **東アジア**（12種・1354字）: `cluster_reports/C-EA_culture.md`\n"
    "### 手法軸\n"
    "- **基礎プロファイル**（18種・1508字）: `cluster_reports/M-A_method.md`\n\n"
    "---\n\n"
    "## 御縁のある神さま Top10\n\n"
    "*全占術と統合レポートの内容を踏まえて選定*\n\n"
    "1. **アヌ**（メソポタミア）— 天の神。\n\n"
    "---\n"
    "※ 本レポートはエンターテインメント目的のシミュレーションであり、"
    "事実を表すものではありません。\n"
)


def _tool_md(title: str, consultation: str, extra_inputs: str = "") -> str:
    return (
        f"# {title}\n\n"
        "**体系**：テスト体系。／**グループ**：G1／**実行**：2026-10-14T16:38:12+09:00\n\n"
        "## ■ 使用した入力\n"
        "- 生年月日：1992-11-06／時刻：20:20（実入力）／出生地：愛知県（実入力）\n"
        "- 氏名：星野 凪（ほしの なぎ → HOSHINO NAGI）\n"
        f"{extra_inputs}"
        f"- 相談内容：{consultation}\n\n"
        "## ■ 計算結果（事実）\n"
        "```json\n{\n \"x\": 1\n}\n```\n\n"
        "## ■ 鑑定文\n\n"
        "鑑定文の本文です。\n\n"
        "---\n"
        "※ 本結果はエンターテインメント目的のシミュレーションであり、事実を表すものではありません。\n"
    )


def _make_person(d: Path, *, with_synthesis: bool = True, consultation: str = CONSULTATION,
                 n_tools: int = 3) -> None:
    (d / "results").mkdir(parents=True, exist_ok=True)
    if with_synthesis:
        (d / "synthesis_report.md").write_text(SYN_MD, encoding="utf-8")
    for i in range(n_tools):
        slug = f"M0{i + 1}_tool{i + 1}"
        (d / "results" / f"{slug}.md").write_text(
            _tool_md(f"占術{i + 1}", consultation), encoding="utf-8")
        (d / "results" / f"{slug}_raw.json").write_text("{}", encoding="utf-8")


# ===============================================================
# 1. HTML: 相談内容は最初の 1 回だけ
# ===============================================================
class TestDedupeConsultationMd(unittest.TestCase):
    def test_first_kept_then_replaced(self):
        seen = {"shown": False}
        a = _tool_md("A", CONSULTATION)
        b = _tool_md("B", CONSULTATION)
        a2 = H.dedupe_consultation_md(a, seen)
        self.assertEqual(a2, a, "最初の 1 回は全文を残す")
        self.assertTrue(seen["shown"])
        b2 = H.dedupe_consultation_md(b, seen)
        self.assertNotIn(CONSULTATION, b2)
        self.assertIn("- " + H.CONSULT_REF_TEXT, b2)
        self.assertEqual(seen["replaced"], 1)
        self.assertEqual(seen["saved"], len(CONSULTATION))
        # 前後（氏名の行・計算結果）は壊れない
        self.assertIn("- 氏名：星野 凪", b2)
        self.assertIn("## ■ 計算結果（事実）", b2)
        self.assertIn("## ■ 鑑定文", b2)

    def test_placeholder_and_missing_untouched(self):
        seen = {"shown": True}
        today = _tool_md("A", "（なし・全般的な運勢）")
        self.assertEqual(H.dedupe_consultation_md(today, seen), today)
        plain = "# x\n\n本文だけ。\n"
        self.assertEqual(H.dedupe_consultation_md(plain, seen), plain)
        self.assertEqual(seen.get("replaced", 0), 0)

    def test_multiline_consultation_is_replaced_whole(self):
        seen = {"shown": True}
        md = _tool_md("A", "一行目。\n二行目はつづき。")
        out = H.dedupe_consultation_md(md, seen)
        self.assertNotIn("二行目はつづき", out)
        self.assertIn(H.CONSULT_REF_TEXT, out)
        self.assertIn("## ■ 計算結果（事実）", out)

    def test_synthesis_marks_shown(self):
        seen = {"shown": False}
        H.note_consultation_in_synthesis(SYN_MD, seen)
        self.assertTrue(seen["shown"])
        seen = {"shown": False}
        H.note_consultation_in_synthesis("# 統合鑑定レポート\n\n**対象日**: 2026-10-14\n", seen)
        self.assertFalse(seen["shown"])

    def test_linkify(self):
        frag = H.md_to_html("- " + H.CONSULT_REF_TEXT)
        out = H._linkify_consult_ref(frag)
        self.assertIn('<li class="consult-ref">', out)
        self.assertIn('href="#synthesis"', out)
        self.assertIn("全文は省略", out)
        # 参照行が無い断片は不変
        other = H.md_to_html("- 相談内容：短い相談")
        self.assertEqual(H._linkify_consult_ref(other), other)


class TestBuildHtmlConsultationOnce(unittest.TestCase):
    def _build(self, d: Path) -> str:
        out = H.build_html(d, person_id="t", images_dir=None)
        return out.read_text(encoding="utf-8")

    def test_shown_once_with_synthesis(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _make_person(d, n_tools=3)
            html = self._build(d)
            self.assertEqual(html.count(CONSULTATION[:40]), 1,
                             "相談文は統合レポート冒頭の 1 回だけ")
            self.assertEqual(html.count('<li class="consult-ref">'), 3)
            self.assertIn('href="#synthesis"', html)
            self.assertEqual(H.IMAGE_AUDIT["consultation"],
                             {"shown_once": True, "replaced": 3,
                              "saved_chars": 3 * len(CONSULTATION)})
            # .md の原本は書き換えない
            for p in (d / "results").glob("*.md"):
                self.assertIn(CONSULTATION, p.read_text(encoding="utf-8"))
            self.assertIn(CONSULTATION, (d / "synthesis_report.md").read_text(encoding="utf-8"))

    def test_without_synthesis_first_tool_keeps_full_text(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _make_person(d, with_synthesis=False, n_tools=3)
            html = self._build(d)
            self.assertEqual(html.count(CONSULTATION[:40]), 1)
            self.assertEqual(html.count('<li class="consult-ref">'), 2)

    def test_today_mode_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _make_person(d, with_synthesis=False,
                         consultation="（なし・全般的な運勢）", n_tools=2)
            html = self._build(d)
            self.assertEqual(html.count("（なし・全般的な運勢）"), 2)
            self.assertNotIn("consult-ref", html.split("</style>", 1)[1])
            self.assertEqual(H.IMAGE_AUDIT["consultation"]["replaced"], 0)

    def test_real_run_shape(self):
        """mts5.67 の実機と同じ形（52 占術＋神々＋統合）で 54 → 1 になる。"""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _make_person(d, n_tools=53)
            html = self._build(d)
            self.assertEqual(html.count(CONSULTATION[:40]), 1)
            self.assertEqual(H.IMAGE_AUDIT["consultation"]["replaced"], 53)


# ===============================================================
# 2. 読み物版の元テキスト（ご相談・目次を外す）
# ===============================================================
class TestOmakeSourceText(unittest.TestCase):
    def _unit_text(self) -> str:
        md = H._strip_footer(SYN_MD)
        return H._drop_h1(md).strip()

    def test_trims_consultation_and_toc(self):
        text = self._unit_text()
        src, info = T.omake_source_text(text)
        self.assertEqual(info["full"], len(text))
        self.assertNotIn("**ご相談**", src)
        self.assertNotIn(CONSULTATION[:40], src)
        self.assertNotIn("## 軸サマリー", src)
        self.assertNotIn("## 分野別の中間レポート", src)
        self.assertNotIn("cluster_reports/", src)
        # 残すもの: プロファイル・本文・神々
        for keep in ("## あなたのプロファイル", "## 総括", "## これからの過ごし方",
                     "## 御縁のある神さま Top10", "アヌ"):
            self.assertIn(keep, src)
        self.assertEqual(info["chars"], len(src))
        self.assertGreater(info["consultation"], len(CONSULTATION))
        self.assertGreater(info["toc"], 100)
        self.assertLess(info["chars"], info["full"] - info["consultation"] - info["toc"] + 20)
        # 区切りが連続しない・冪等
        self.assertNotIn("---\n\n---", src)
        src2, info2 = T.omake_source_text(src)
        self.assertEqual(src2, src)
        self.assertEqual((info2["consultation"], info2["toc"]), (0, 0))

    def test_text_without_those_parts_unchanged(self):
        plain = "## 総括\n\n本文です。\n\n## これから\n\n続きです。"
        src, info = T.omake_source_text(plain)
        self.assertEqual(src, plain)
        self.assertEqual(info, {"full": len(plain), "consultation": 0, "toc": 0,
                                "chars": len(plain)})

    def test_lower_bound_uses_trimmed_source(self):
        """実機 mts5.67 の数字: 元 8,276 → ご相談 1,702・目次 915 を外すと 5,653 字。
        spiritual の下限は 6,620 → 4,522 字（当日の 5,490 字は下限の内側）。"""
        n = 5653                                  # 実測（区切りの正規化で −6 字）
        lo, _hi = T.omake_ratio_range("spiritual", n)
        self.assertEqual(lo, 4522)
        self.assertLess(lo, 5490)
        self.assertEqual(T.omake_ratio_range("spiritual", 8276)[0], 6620)

    def test_stage_d_manifest_records_source(self):
        """Stage D（読み物版）はトリム後の元で分量を測り、manifest に内訳を残す。"""
        from tests.test_tones import FAST_PLAN, LITE, LITE2, _RewriteBackend
        plan = {**FAST_PLAN, "stage_d": {"model": LITE, "fallback": [LITE2],
                                         "scope": "synthesis"}}
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _make_person(d, n_tools=1)
            be = _RewriteBackend(1.0)
            man = T.run_stage_d_tones(d / "results", d, {LITE: be},
                                      plan=plan, verbose=False)
            text = self._unit_text()
            src, info = T.omake_source_text(text)
            self.assertEqual(man["source_chars"], len(src))
            self.assertEqual(man["source_trim"],
                             {"full": info["full"], "consultation": info["consultation"],
                              "toc": info["toc"]})
            # プロンプトに渡した元テキストにも相談文・目次は入っていない
            user = be.calls[0]["user"]
            self.assertNotIn(CONSULTATION[:40], user)
            self.assertNotIn("cluster_reports/", user)
            self.assertIn(f"（{len(src)}字）", user)
            for tid in ("easy", "spiritual"):
                self.assertEqual(man["tones"][tid]["status"], "ok")

    def test_verifier_counts_the_same_way(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "vro568", REPO / "verify" / "verify_run_output.py")
        vro = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vro)
        text = self._unit_text()
        b = vro.std_chars_breakdown(text)
        src, info = T.omake_source_text(text)
        self.assertEqual(b["omake_source"], len(src))
        self.assertEqual(b["consultation"], info["consultation"])
        # 目次の字数は境界（先頭の改行・末尾の区切り）の取り方が違うので数字は近似で見る
        self.assertLessEqual(abs(b["toc"] - info["toc"]), 8)
        # 検証器の表示文言（毎回出る）
        v_src = (REPO / "verify" / "verify_run_output.py").read_text(encoding="utf-8")
        self.assertIn("読み物版の元テキスト ", v_src)
        self.assertIn("manifest_source_chars", v_src)


# ===============================================================
# 3. 段階 C の応答の打ち切り
# ===============================================================
class TestStageCResponseTimeout(unittest.TestCase):
    FACTS = {"太陽星座": "山羊座", "数秘術（ライフパス）": 8}

    def test_plan_has_timeout_for_upper_flash_only(self):
        plan = load_model_plan()
        models, sec = stage_c_response_timeout(plan)
        self.assertEqual(models, {"gemini-3.8-flash", "gemini-3.6-flash"})
        self.assertEqual(sec, 60.0)
        # 最後の受け皿（preview・lite）には掛けない
        self.assertNotIn("gemini-3-flash-preview", models)
        self.assertNotIn("gemini-3.5-flash-lite", models)
        self.assertEqual(plan["version"], "2026-10-14-B6")

    def test_absent_or_zero_means_no_timeout(self):
        self.assertEqual(stage_c_response_timeout({"stage_c": {}}), (set(), None))
        self.assertEqual(stage_c_response_timeout(
            {"stage_c": {"response_timeout": {"models": ["x"], "seconds": 0}}}),
            (set(), None))
        self.assertEqual(stage_c_response_timeout(
            {"stage_c": {"response_timeout": {"models": [], "seconds": 30}}}),
            (set(), None))

    def test_applied_during_stage_c_and_restored(self):
        from tests.test_mts import _fake_all_raw
        seen: dict[str, set] = {}

        class _Rec(MockBackend):
            def generate(self, system_prompt, user_prompt, temperature=0.7,
                         max_tokens=1000, seed=None):
                seen.setdefault(self.tag, set()).add(self.response_timeout_s)
                return super().generate(system_prompt, user_prompt, temperature,
                                        max_tokens, seed)

        plan = load_model_plan()
        backends = {m: _Rec() for m in plan["models"]}
        for m, be in backends.items():
            be.tag = m
        with tempfile.TemporaryDirectory() as td:
            rd = _fake_all_raw(td)
            out = Path(td)
            b = run_stage_b_mts(rd, out, backends, self.FACTS, CONSULTATION, verbose=False)
            run_stage_c_mts(rd, out, backends, self.FACTS, CONSULTATION,
                            verbose=False, per_axis=b["per_axis"])
        self.assertEqual(seen["gemini-3.8-flash"], {60.0}, "段階Cの間は 60 秒で打ち切る")
        for m, be in backends.items():
            self.assertIsNone(be.response_timeout_s, f"{m}: 終わったら元（None）に戻す")
        # lite レーン（段階B）は打ち切りなし
        self.assertEqual(seen.get("gemini-3.5-flash-lite", {None}), {None})

    def test_timeout_hands_over_to_next_model(self):
        from tests.test_mts import _fake_all_raw

        class _Hang(MockBackend):
            def generate(self, *a, **k):
                self.calls.append(a)
                raise ResponseTimeoutError("応答が60秒を超えました（打ち切り・別モデルへ回します）")

        backends = make_mock_backends()
        backends["gemini-3.8-flash"] = _Hang()
        with tempfile.TemporaryDirectory() as td:
            rd = _fake_all_raw(td)
            out = Path(td)
            b = run_stage_b_mts(rd, out, backends, self.FACTS, CONSULTATION, verbose=False)
            c = run_stage_c_mts(rd, out, backends, self.FACTS, CONSULTATION,
                                verbose=False, per_axis=b["per_axis"])
            self.assertTrue(Path(c["file"]).exists())
        self.assertGreater(len(backends["gemini-3.6-flash"].calls), 0, "次のモデルへ移譲")
        self.assertEqual(_stealable_label(ResponseTimeoutError("x")), "応答の打ち切り")


# ===============================================================
# 4. 408 は 503 と同じ（1 回だけ待って別モデルへ）
# ===============================================================
class Test408LikeOverload(unittest.TestCase):
    def _make_backend(self, **kw):
        from fortunelib.backend import GeminiBackend
        kw.setdefault("api_key", "test-key")
        kw.setdefault("verbose", False)
        kw.setdefault("backoff_base_s", 0.0)
        kw.setdefault("requests_per_minute", 600.0)
        return GeminiBackend(**kw)

    def test_408_twice_gives_up_after_one_wait(self):
        be = self._make_backend(max_retries=5)
        backoffs = []
        be._backoff_sleep = lambda s: backoffs.append(s)
        calls = {"n": 0}

        class Fake408(Exception):
            code = 408

        def fake_gen(*a, **k):
            calls["n"] += 1
            raise Fake408("408 Request Timeout")

        be._generate_once = fake_gen
        with self.assertRaises(RuntimeError) as cm:
            be.generate("sys", "usr")
        self.assertEqual(len(backoffs), 1, "指数バックオフで粘らない（mts5.67 実機: 約100秒×複数回）")
        self.assertEqual(calls["n"], 2)
        msg = str(cm.exception)
        self.assertIn("408", msg)
        self.assertIn("混雑", msg)
        # MTS は 408 の諦めを移譲対象（stealable）として扱う
        self.assertTrue(_is_stealable(None, cm.exception))
        self.assertEqual(_stealable_label(cm.exception), "408（無応答）")

    def test_408_once_then_success_still_works(self):
        be = self._make_backend(max_retries=5)
        backoffs = []
        be._backoff_sleep = lambda s: backoffs.append(s)
        calls = {"n": 0}

        class Fake408(Exception):
            code = 408

        def fake_gen(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise Fake408("Request Timeout")
            return "回復"

        be._generate_once = fake_gen
        self.assertEqual(be.generate("sys", "usr"), "回復")
        self.assertEqual(len(backoffs), 1)

    def test_503_unchanged_and_429_still_backs_off(self):
        be = self._make_backend(max_retries=3)
        backoffs = []
        be._backoff_sleep = lambda s: backoffs.append(s)

        class Fake429(Exception):
            code = 429

        calls = {"n": 0}

        def fake_gen(*a, **k):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise Fake429("429 rate limit")
            return "ok"

        be._generate_once = fake_gen
        self.assertEqual(be.generate("sys", "usr"), "ok")
        self.assertEqual(len(backoffs), 2, "429 は従来どおり指数バックオフ")

    def test_is_stealable_recognises_408_code_and_text(self):
        class E408(Exception):
            code = 408
        self.assertTrue(_is_stealable(None, E408("x")))
        self.assertTrue(_is_stealable({"status": "error", "reason": "RuntimeError: 408 Request Timeout"}))
        self.assertFalse(_is_stealable({"status": "error", "reason": "RuntimeError: 400 invalid"}))
        self.assertFalse(_is_stealable({"status": "ok"}))


# ===============================================================
# 版印・ドキュメントの整合
# ===============================================================


if __name__ == "__main__":
    unittest.main()
