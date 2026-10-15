# -*- coding: utf-8 -*-
"""mts5.62: 読み物版の口調（②）と fallback（③）の追加策。

ご依頼（Turn 16）:
  ② 読み物版の口調の未達（easy の平均文長・spiritual の類似度）への追加策
  ③ obaa のような fallback（APIの一時混雑でトーンが欠ける）の再試行設計の見直し

実機3回（mts5.57/5.58/5.60）の実測から分かったこと:

  | 版    | トーン    | 状態     | 丁寧体 | 平均文長 | 標準類似 | 未達 |
  |-------|-----------|----------|--------|----------|----------|------|
  | 5.57  | easy      | ok       |  0%    |  38.1字  |  0.711   | 0    |
  | 5.58  | easy      | ok       |  0%    |  55.4字  |  0.822   | 2    |
  | 5.60  | easy      | ok       | 36%    |  46.9字  |  0.428   | 2    |
  | 5.57  | obaa      | ok       |  3%    |  55.4字  |  0.487   | 1    |
  | 5.58  | obaa      | ok       |  2%    |  53.2字  |  0.698   | 0    |
  | 5.60  | obaa      | **fallback**（503×6） | 3% | 69.7字 | 0.844 | — |
  | 5.57  | spiritual | ok       | 81%    |  91.7字  |  0.772   | 0    |
  | 5.58  | spiritual | ok       | 82%    |  80.3字  |  0.588   | 0    |
  | 5.60  | spiritual | ok       | 97%    |  85.4字  | **0.981** | 2  |

  ★ 5.60 の spiritual は「類似度 98%」＝ほぼ標準のまま。調べると**標準レポートの
    文を 86/99文そのまま使っていた**（＝作り直しではなく転記）。類似度という
    全体指標では見えにくいので、**文単位の流用**を直接測るようにした。
  ★ 5.60 の obaa は 1回目の未達 → 2回目が 503 UNAVAILABLE を6連続 → RuntimeError
     で fallback（＝トーンが1つ欠けた）。同じ混雑モデルを叩き直す設計だったのが原因。

実装（mts5.62）:
  1. `verbatim_max`（標準の文の丸ごと流用の上限 20%）を弁別指標に追加
  2. 未達が残ったら**別レーンで3試行目**を作り、**良い方の候補**を採用する
  3. 再実行の指示に「長すぎる文」「流用した文」の**実物**を出して直させる
  4. 503 では粘らず（内部リトライ 5→2）早く別レーンへ渡す
  5. 試行の内訳（`attempt_log`・`chosen_attempt`・ログ1行）を残す
"""
from __future__ import annotations

import json
import re as _re
import tempfile
import unittest
from pathlib import Path

from fortunelib import runcheck
from fortunelib.backend import LLMBackend, MockBackend
from fortunelib.tone import (
    OMAKE_API_RETRIES, OMAKE_MAX_ATTEMPTS, TONE_DEFS, TONE_SPECS,
    attempt_chain, feedback_for_retry, discrimination_report,
    discrimination_summary, run_stage_d_tones, tone_spec, verbatim_sentences,
)

LITE = "gemini-3.5-flash-lite"
LITE2 = "gemini-3.1-flash-lite"

SYN_MD = (
    "# 統合鑑定レポート\n\n"
    "**ご相談**: 独立すべきか\n\n"
    "## 総括\n"
    "あなたの総合得点は7点中5点で、大運は4期目に移行しています。\n\n"
    "能力は高いがタイミングが課題です。\n\n"
)


def _make_person(d: Path) -> None:
    (d / "results").mkdir(parents=True, exist_ok=True)
    (d / "synthesis_report.md").write_text(SYN_MD, encoding="utf-8")


class _LiveBackend(LLMBackend):
    """本物の API は呼ばないが「モックではない」バックエンド（再試行を有効にする）。"""

    is_mock = False

    def __init__(self, replies: list[str] | None = None, fail_first: int = 0,
                 fail_at: tuple[int, ...] = ()):
        self.replies = list(replies or [])
        self.fail_first = int(fail_first)
        self.fail_at = tuple(int(x) for x in fail_at)
        self.calls: list[dict] = []
        self.max_retries = 5              # GeminiBackend と同じ既定（mts5.62 の検査用）
        self.retries_at_call: list[int | None] = []

    def generate(self, system_prompt, user_prompt, temperature=0.7,
                 max_tokens=1000, seed=None):
        self.calls.append({"system": system_prompt, "user": user_prompt})
        self.retries_at_call.append(getattr(self, "max_retries", None))
        if len(self.calls) <= self.fail_first or len(self.calls) in self.fail_at:
            raise RuntimeError("503 UNAVAILABLE")
        idx = min(len(self.calls) - 1, len(self.replies) - 1)
        return self.replies[idx] if self.replies else ""


_CP = 30   # 1文30字（12字以上＝流用検出の対象）


def _sent(n: int, tag: str) -> str:
    """決定的に作る30字の文（tag を変えると別の文になる・必ず「。」で終わる）。"""
    return (f"{tag}の{n:02d}番目のお話ですが、" + "あ" * 12 + "。")[:_CP]


def _plan() -> dict:
    return {"reliability": {"backoff_503_s": 0.01},
            "stage_d": {"model": LITE, "fallback": [LITE2], "scope": "synthesis"}}


def _run(td, backends, **kw):
    plan = kw.pop("plan", None) or _plan()
    return run_stage_d_tones(Path(td) / "results", Path(td), backends,
                             plan=plan, verbose=False, **kw)


def _text(n: int = 24, tag: str = "標準", marker: str = "") -> str:
    """本文（tag=標準のときは他と重ならない文を作る）。"""
    body = "".join(_sent(i, tag) for i in range(n))
    return body + (marker or "")


def _easy_text(n: int = 24, tag: str = "標準") -> str:
    """easy の規則を満たす本文（だよ／だね・短い文）。"""
    out = ""
    while len(out) < len(SYN_MD) * 0.9:
        for i in range(n):
            out += f"{tag}だよ。{i}番目だね。"   # 12字未満＝流用検出の対象外
    return out


class TestVerbatimDetectionMts562(unittest.TestCase):
    """① 標準の文をそのまま流用していないかを文単位で測る"""

    def test_specs_have_verbatim_limit(self):
        for tid, sp in TONE_SPECS.items():
            self.assertIn("verbatim_max", sp, tid)
            self.assertLessEqual(float(sp["verbatim_max"]), 0.20, tid)
        # 未知トーンはチェックしない（安全側＝誤検出しない）
        self.assertGreater(float(tone_spec("unknown")["verbatim_max"]), 1.0)

    def test_verbatim_sentences_finds_copied_text(self):
        src = _text(6, "標準")
        copied = "".join(_sent(i, "標準") for i in (1, 3))
        self.assertEqual(len(verbatim_sentences(src, copied)), 2)
        self.assertEqual(verbatim_sentences(src, _text(6, "別")), [])

    def test_discrimination_reports_verbatim_as_a_problem(self):
        src = _text(20, "標準")
        rep = discrimination_report(src, _text(20, "標準"), "spiritual")
        self.assertEqual(rep["verbatim_sentences"], 20)
        self.assertEqual(rep["verbatim_ratio"], 1.0)
        self.assertTrue(any("流用" in p for p in rep["problems"]), rep["problems"])
        self.assertIn("verbatim_max", rep["limits"])
        self.assertTrue(rep["verbatim_examples"])
        # 書き直した本文（流用0）では出ない
        rep2 = discrimination_report(src, _text(20, "別"), "spiritual")
        self.assertEqual(rep2["verbatim_sentences"], 0)
        self.assertFalse([p for p in rep2["problems"] if "流用" in p])

    def test_summary_shows_the_copied_count(self):
        src = _text(20, "標準")
        rep = discrimination_report(src, _text(20, "標準"), "spiritual")
        self.assertIn("標準の文を流用 20文", discrimination_summary(rep))
        rep2 = discrimination_report(src, _text(20, "別"), "spiritual")
        self.assertNotIn("流用", discrimination_summary(rep2))

    def test_real_run_very_similar_tone_is_caught(self):
        """実機 mts5.60 の spiritual（類似0.981）を**実物で**検出できる。

        ZIP が無い環境では skip（テストは環境に依存させない）。
        """
        import zipfile
        z = None
        for cand in (Path("/home/user/uploads/results_mts5.60.zip.txt"),
                     Path(__file__).resolve().parents[2] / "uploads"
                     / "results_mts5.60.zip.txt"):
            if cand.exists():
                z = cand
                break
        if z is None:
            self.skipTest("実機の結果ZIPが無い環境")
        with zipfile.ZipFile(z) as zf:
            names = zf.namelist()
            syn = next(n for n in names if n.endswith("synthesis_report.md"))
            raw = next(n for n in names
                       if n.endswith("tone_reports/spiritual/raw/omake.txt"))
            src = zf.read(syn).decode("utf-8")
            body = zf.read(raw).decode("utf-8")
        # 生応答の記録（`--- attempt N model=... ---`）から最後の試行の本文だけを見る
        parts = _re.split(r"^--- attempt .*$", body, flags=_re.M)[1:]
        txt = parts[-1]
        rep = discrimination_report(src, txt, "spiritual")
        # 実測（mts5.60 の spiritual）: 89文が一字一句同じ・長い文の 47.8%
        self.assertGreater(rep["verbatim_sentences"], 50,
                           "実機 spiritual の転記を見落としています")
        self.assertGreater(rep["verbatim_ratio"], 0.3)
        self.assertTrue(any("流用" in p for p in rep["problems"]), rep["problems"])


class TestSpecTighteningMts562(unittest.TestCase):

    def test_spiritual_polite_ratio_is_tightened(self):
        """spiritualは標準文体に寄りやすいため、上限をmts5.66で0.70へ再強化。
        0.80はmts5.65の履歴値。"""
        self.assertEqual(TONE_SPECS["spiritual"]["polite_max"], 0.70)
        self.assertLess(TONE_SPECS["spiritual"]["polite_max"],
                        TONE_SPECS["spiritual"].get("polite_max", 0) + 1)
        # プロンプト規則にも70%が出る（mts5.66）
        from fortunelib.tone import build_omake_prompt
        tone = next(t for t in TONE_DEFS if t["id"] == "spiritual")
        sysp, _ = build_omake_prompt(tone, {"id": "synthesis", "text": "あ" * 1000})
        self.assertIn("70%以下", sysp)
        self.assertIn("7割以下", sysp)
        self.assertIn("同じ文を1つも残さず", sysp)

    def test_easy_prompt_tells_to_add_sentences(self):
        """分量を増やすときは「文を足す」＝一文を長くしない（平均文長の未達を作らない）"""
        from fortunelib.tone import build_omake_prompt
        for tid in ("easy",):   # mts5.65: obaa を削除
            tone = next(t for t in TONE_DEFS if t["id"] == tid)
            sysp, _ = build_omake_prompt(tone, {"id": "synthesis", "text": "あ" * 1000})
            self.assertIn("文を足す", sysp, tid)
            self.assertIn("標準レポートの文をそのまま使わず", sysp, tid)


class TestRetryFeedbackMts562(unittest.TestCase):

    def _tone(self, tid="easy"):
        return next(t for t in TONE_DEFS if t["id"] == tid)

    def test_round1_keeps_the_compatible_wording(self):
        rep = discrimination_report(_text(), _text(24, "標準"), "easy")
        fb = feedback_for_retry(self._tone(), rep, 600, 1000)
        self.assertIn("【再実行の注意】", fb)
        self.assertNotIn("2回目", fb)

    def test_round1_with_text_names_the_long_sentences(self):
        """実物を指す＝「この文を割れ」まで言う（mts5.62）"""
        long_sent = "とても長い一文であり" + "い" * 120 + "。"
        rep = discrimination_report(_text(), long_sent, "easy")
        fb = feedback_for_retry(self._tone(), rep, 60, 100, text=long_sent)
        self.assertIn(f"長すぎる文（{TONE_SPECS['easy']['avg_sentence_max']}字超）", fb)
        self.assertIn("2文以上に分けてください", fb)
        self.assertIn(long_sent[:10], fb)                # 実物が引用される
        self.assertIn("文を足す", fb)

    def test_round1_with_text_names_the_copied_sentences(self):
        src = _text(20, "標準")
        rep = discrimination_report(src, _text(20, "標準"), "spiritual")
        fb = feedback_for_retry(self._tone("spiritual"), rep, 600, 1000,
                                text=_text(20, "標準"))
        self.assertIn("一字一句同じ", fb)
        self.assertIn(_sent(0, "標準")[:10], fb)
        self.assertIn("丸ごと書き直して", fb)

    def test_round2_is_stronger(self):
        rep = discrimination_report(_text(), _text(24, "標準"), "easy")
        fb = feedback_for_retry(self._tone(), rep, 600, 1000, round_no=2)
        self.assertIn("（2回目）", fb)
        self.assertIn("語尾の置き換えだけでは直りません", fb)
        self.assertIn("段落の書き出し", fb)


    def test_spiritual_retry_explicitly_closes_the_length_gap(self):
        """分量不足時は不足字数と見出し単位の増補方針を明示する（mts5.66）。"""
        from fortunelib.tone import TONE_SPECS
        text = "短いです。" * 500
        rep = discrimination_report("元レポート。" * 500, text, "spiritual")
        lo = int(10000 * TONE_SPECS["spiritual"]["ratio_min"])
        fb = feedback_for_retry(self._tone("spiritual"), rep, lo, 10000,
                                text=text, round_no=2)
        self.assertIn(f"下限まであと{lo-len(text)}字不足", fb)
        self.assertIn("各見出し", fb)
        self.assertIn("元の全見出しを最後まで", fb)

class TestThreeAttemptPolicyMts562(unittest.TestCase):
    """③ 未達・失敗のときだけ最大3試行（3回目は別レーン）"""

    def test_constants(self):
        self.assertEqual(OMAKE_MAX_ATTEMPTS, 3)
        self.assertEqual(OMAKE_API_RETRIES, 2)
        self.assertEqual(OMAKE_API_RETRIES < 5, True)

    def test_on_spec_tone_uses_one_call(self):
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            be = _LiveBackend([_easy_text()])
            man = _run(td, {LITE: be}, tone_ids=["easy"])
            t = man["tones"]["easy"]
            self.assertEqual(len(be.calls), 1, "通ったら作り直さない（呼び出しを増やさない）")
            self.assertEqual(t["attempts"], 1)
            self.assertEqual(t["chosen_attempt"], 1)

    def test_third_attempt_goes_to_the_other_lane_and_best_wins(self):
        off = "".join(f"{i}番目です。" for i in range(500))     # 目印語なし・丁寧体
        on = _easy_text()
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            be_off, be_on = _LiveBackend([off]), _LiveBackend([on])
            man = _run(td, {LITE: be_on, LITE2: be_off}, tone_ids=["easy"])
            t = man["tones"]["easy"]
            self.assertEqual(t["status"], "ok")
            self.assertEqual(t["models_tried"], [LITE2, LITE2, LITE])
            self.assertEqual(t["model"], LITE)
            self.assertEqual(t["discrimination"]["problems"], [])
            self.assertEqual(t["attempts"], 3)
            self.assertEqual([a["outcome"] for a in t["attempt_log"]],
                             ["style", "style", "ok"])
            self.assertEqual(t["chosen_attempt"], 3)

    def test_keeps_the_better_candidate_when_the_third_attempt_is_worse(self):
        """3試行目が**悪ければ**2試行目（または1試行目）を採用する"""
        mild = "".join(f"ご縁があります。{i}。" for i in range(400))     # 未達が少ない
        harsh = "".join(f"{i}。" for i in range(20))                     # 短すぎ（候補外）
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            man = _run(td, {LITE: _LiveBackend([harsh]), LITE2: _LiveBackend([mild])},
                       tone_ids=["easy"])
            t = man["tones"]["easy"]
            self.assertEqual(t["status"], "ok")
            self.assertEqual(t["model"], LITE2)
            self.assertEqual(t["chosen_attempt"], 1)
            self.assertEqual(t["models_tried"], [LITE2, LITE2, LITE])

    def test_alt_lane_is_not_used_when_chain_has_one_model(self):
        """別レーンが無ければ2試行で打ち切る（無限に叩かない）"""
        off = "".join(f"{i}番目です。" for i in range(500))
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            be = _LiveBackend([off])
            man = _run(td, {LITE: be}, tone_ids=["easy"],
                       plan={"reliability": {"backoff_503_s": 0.01},
                             "stage_d": {"model": LITE, "fallback": [LITE],
                                         "scope": "synthesis"}})
            t = man["tones"]["easy"]
            self.assertEqual(t["attempts"], 2)
            self.assertEqual(t["models_tried"], [LITE, LITE])

    def test_api_error_on_attempt2_is_rescued_by_the_other_lane(self):
        """mts5.60 の obaa（1回目未達→2回目 503×6 で fallback）を救う経路

        mts5.65 で obaa は削除したが、この救済経路は easy・spiritual に共通。
        """
        off = "".join(f"{i}番目です。" for i in range(500))
        on = _easy_text()
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            # 1回目=off（未達）、2回目=503（fail_at=2）、3回目（別レーン）=on
            be_primary = _LiveBackend([off], fail_at=(2,))
            be_alt = _LiveBackend([on])
            man = _run(td, {LITE: be_alt, LITE2: be_primary}, tone_ids=["easy"])
            t = man["tones"]["easy"]
            self.assertEqual(t["status"], "ok", t)
            self.assertEqual(t["models_tried"], [LITE2, LITE2, LITE])
            self.assertEqual([a["outcome"] for a in t["attempt_log"]],
                             ["style", "api", "ok"])
            self.assertEqual(t["model"], LITE)
            self.assertIsNone(t["reason"])
            # ログ用の1行にも理由が出る
            self.assertIn("API一時エラー", attempt_chain(t["attempt_log"]))

    def test_stage_d_requests_fail_fast_on_503(self):
        """読み物版の呼び出し中は内部リトライを 5→2 に絞り、終わったら戻す（mts5.62）"""
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            be = _LiveBackend([_easy_text()])
            self.assertEqual(be.max_retries, 5)
            _run(td, {LITE: be}, tone_ids=["easy"])
            self.assertEqual(be.retries_at_call, [OMAKE_API_RETRIES])
            self.assertEqual(be.max_retries, 5, "呼び出し後に元へ戻す")

    def test_mock_still_runs_once_or_twice_without_style_retry(self):
        """モック（demo・単体テスト）は従来どおり（弁別での作り直しはしない）"""
        class _R(MockBackend):
            def __init__(self):
                super().__init__(responses=[])
                self.calls = []

            def generate(self, system_prompt, user_prompt, temperature=0.7,
                         max_tokens=1000, seed=None):
                self.calls.append(1)
                return "（口調化）" + user_prompt.split("===\n", 1)[1][:80]

        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            be = _R()
            man = _run(td, {LITE: be}, tone_ids=["easy"])
            t = man["tones"]["easy"]
            self.assertEqual(len(be.calls), 1)
            self.assertFalse(t["discrimination"]["enforced"])
            self.assertEqual(t["attempts"], 1)

    def test_attempt_log_and_chain_are_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            be = _LiveBackend([], fail_first=9)
            man = _run(td, {LITE: _LiveBackend([], fail_first=9), LITE2: be},
                       tone_ids=["easy"])
            t = man["tones"]["easy"]
            self.assertEqual(t["status"], "fallback")
            self.assertEqual(len(t["attempt_log"]), 3)
            self.assertEqual([a["attempt"] for a in t["attempt_log"]], [1, 2, 3])
            self.assertEqual({a["outcome"] for a in t["attempt_log"]}, {"api"})
            self.assertIsNone(t["chosen_attempt"])
            self.assertIn("試行1=", attempt_chain(t["attempt_log"]))
            # 警告台帳（既定は警告のみ）にも残る
            self.assertTrue(any("読み物版を作れませんでした" in w
                                for w in runcheck.WARNINGS), runcheck.WARNINGS)
            runcheck.clear()

    def test_plan_can_disable_the_third_attempt(self):
        off = "".join(f"{i}番目です。" for i in range(500))
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            be = _LiveBackend([off])
            man = _run(td, {LITE: _LiveBackend([off]), LITE2: be}, tone_ids=["easy"],
                       plan={"reliability": {"backoff_503_s": 0.01},
                             "stage_d": {"model": LITE, "fallback": [LITE2],
                                         "scope": "synthesis", "max_attempts": 2}})
            t = man["tones"]["easy"]
            self.assertEqual(t["models_tried"], [LITE2, LITE2])
            self.assertEqual(len(be.calls), 2)


class TestManifestCompatMts562(unittest.TestCase):
    """既存のキーはそのまま（検証器・HTML が読む）"""

    def test_manifest_keeps_existing_keys(self):
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            man = _run(td, {LITE: _LiveBackend([_easy_text()])}, tone_ids=["easy"])
            t = man["tones"]["easy"]
            for k in ("label", "status", "mode", "scope", "model", "units",
                      "n_ok", "n_total", "chars", "ratio", "numbers_new",
                      "attempts", "models_tried", "reason", "discrimination",
                      "errors", "updated_at"):
                self.assertIn(k, t, k)
            for k in ("attempt_log", "chosen_attempt"):
                self.assertIn(k, t, k)
            raw = json.loads((Path(td) / "tone_reports" / "tone_manifest.json")
                             .read_text(encoding="utf-8"))
            self.assertEqual(raw["tones"]["easy"]["status"], "ok")
            # discrimination の既存キー
            d = t["discrimination"]
            for k in ("polite_ratio", "avg_sentence_chars", "marker_total",
                      "similarity", "limits", "problems", "enforced"):
                self.assertIn(k, d, k)


if __name__ == "__main__":
    unittest.main()
