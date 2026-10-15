# -*- coding: utf-8 -*-
"""
mts5.22 Stage D（トーン化リライト）の回帰テスト
（mts5.24: データ部そのまま＋本文セグメント方式に更新）
  - トーン定義・フォールバック規則
  - ユニット収集・**セグメント分割**（データ部/本文）
  - セグメントプロンプト（最低文字数・数値リスト）・プレーンパース・検証
  - run_stage_d_tones: 正常 / リトライ / 移譲 / フォールバック / レジューム
    / 生応答の記録 / HTML 再構築
  - build_html のタブ UI（tonebar / tone-data / data-unit）
（mts5.26: 口調タブが実 DOM で機能することを検証する回帰テストを追加）
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from fortunelib import runcheck

from fortunelib.backend import LLMBackend, MockBackend
from fortunelib.tone import (
    NARRATIVE_KINDS, OMAKE_MIN_RATIO, OMAKE_UNIT_ID, TONE_DEFS, TONE_IDS,
    TONE_PAIR_SIM_MAX, TONE_RULES, TONE_SCOPES, TONE_SPECS, assemble_unit,
    build_omake_prompt, build_segment_prompt, collect_units,
    alt_lite_model, discrimination_report, discrimination_summary,
    feedback_for_retry, filter_units, omake_ratio_range, omake_style_block,
    pairwise_similarity,
    parse_plain, run_stage_d_tones, stage_d_chain, split_unit, tone_from_prompt,
    tone_model, tone_scope, tone_spec, validate_tone_segment,
)

FAST_PLAN = {
    "reliability": {"backoff_503_s": 0.01},
    "stage_d": {
        "model": "gemini-3.5-flash-lite",
        "fallback": ["gemini-3.1-flash-lite"],
    },
}
LITE = "gemini-3.5-flash-lite"
LITE2 = "gemini-3.1-flash-lite"

SYN_MD = (
    "# 統合鑑定レポート\n\n"
    "**生成**: 2026-09-26T20:12:24+09:00／**分類軸**: method\n\n"
    "**ご相談**: 独立すべきか\n\n"
    "## あなたのプロファイル\n"
    "- 数秘術（ライフパス）: 3\n"
    "- 血液型: O型\n\n"
    "---\n"
    "## 総括\n"
    "あなたの総合得点は7点中5点で、大運は4期目に移行しています。\n\n"
    "能力は高いがタイミングが課題です。\n\n"
    "## これからの過ごし方\n"
    "1978年生まれのあなたは、2026年の今、準備期間にいます。\n\n"
    # mts5.27: 実物の統合レポートと同じ「見出しの直後に見出し（本文なし）」構造
    "## 軸サマリー\n"
    "- **手法軸（テスト軸）**（429字）: `cluster_reports/AXIS_method.md`\n\n"
    "## 分野別の中間レポート\n"
    "### 手法軸（テスト軸）\n"
    "- **基礎プロファイル**（18種・429字）: `cluster_reports/M-A_method.md`\n\n"
    "---\n"
    "※ 本レポートはエンターテインメント目的のシミュレーションであり、"
    "事実を表すものではありません。\n"
)
CLUSTER_MD = (
    "# 中間レポート: テスト分野\n\n"
    "**対象**: 2種\n"
    "**生成**: 2026-09-26T20:09:54+09:00\n\n"
    "テストクラスタでは2系統が共通しています。得点は4点です。\n\n"
    "第二段階では1つの傾向が見られます。\n"
)
AXIS_MD = (
    "# 軸サマリー: 手法軸\n\n"
    "**対象**: 中間1本\n"
    "**生成**: 2026-09-26T20:11:15+09:00\n\n"
    "手法軸では3つの傾向が見られます。信頼度は8割です。\n"
)
TOOL_MD = (
    "# タロット\n\n"
    "**体系**：ライダー・ウェイト版。／**グループ**：G1／"
    "**実行**：2026-09-26T20:06:57+09:00\n\n"
    "## ■ 使用した入力\n"
    "- 生年月日：1978-07-07／時刻：05:20\n"
    "- 氏名：高橋 蓮\n\n"
    "## ■ 計算結果（事実）\n"
    "```json\n"
    "{\n"
    " \"draw\": 4,\n"
    " \"position\": 1\n"
    "}\n"
    "```\n\n"
    "## ■ 鑑定文\n"
    "抽出は11枚目と3枚目でした。47の数字に注意です。\n\n"
    "## ■ この占術について\n"
    "- 体系：ライダー・ウェイト版78枚。\n"
    "- 出力構成：カード解釈（300〜500字）\n"
)


def _make_person(d: Path) -> None:
    (d / "results").mkdir(parents=True, exist_ok=True)
    (d / "cluster_reports").mkdir(parents=True, exist_ok=True)
    (d / "synthesis_report.md").write_text(SYN_MD, encoding="utf-8")
    (d / "cluster_reports" / "AXIS_method.md").write_text(AXIS_MD, encoding="utf-8")
    (d / "cluster_reports" / "M-A_method.md").write_text(CLUSTER_MD, encoding="utf-8")
    (d / "results" / "M27_tarot.md").write_text(TOOL_MD, encoding="utf-8")
    (d / "results" / "M27_tarot_raw.json").write_text("{}", encoding="utf-8")


class _RewriteBackend(MockBackend):
    """user prompt に埋め込まれたセグメント本文を決定論的に口調化して返す。

    mode:
      ok        → 「（口調化）」+ 原文（数値保持・比率≈1.0）
      short     → 冒頭10字だけ（長さ比で不合格）
      no_num    → 数値を全て「●」に置換（数値不一致で不合格）
      fail_api  → 例外を送出
      drop47    → 「47」を落として返す（タロット鑑定文のみ不合格になる）
    """

    def __init__(self, mode: str = "ok"):
        super().__init__(responses=[])
        self.mode = mode

    def generate(self, system_prompt, user_prompt, temperature=0.7,
                 max_tokens=1000, seed=None):
        self.calls.append({"system": system_prompt, "user": user_prompt,
                           "temperature": temperature, "max_tokens": max_tokens,
                           "seed": seed})
        if self.mode == "fail_api":
            raise RuntimeError("503 high demand (giveup)")
        seg = user_prompt.split("===\n", 1)[1]
        if "【再実行の注意】" in seg:
            seg = seg.split("【再実行の注意】", 1)[0].strip()
        if self.mode == "short":
            return seg[:10]
        if self.mode == "no_num":
            return re.sub(r"\d+", "●", seg)
        if self.mode == "drop47":
            return seg.replace("47", "")
        if self.mode == "omake_short":
            return "短い読み物版です。"
        if self.mode == "tagged":
            # トーンごとに違う本文を返す（DOM で切替の差を検証する用）。
            # mts5.56: 読み物版のプロンプトは style ⑤ を外して書き換えるため、
            # 元の style 全文では照合できない。トーン固有の数値（平均文長）で見分ける。
            tid = tone_from_prompt(system_prompt) or "?"
            return f"（{tid}版）" + seg
        if isinstance(self.mode, float):        # omake: 元の ratio 倍に伸縮
            cut = max(1, int(len(seg) * self.mode))
            return seg[:cut]
        return "（口調化）" + seg


class TestToneDefs(unittest.TestCase):
    def test_batch1_tones(self):
        # mts5.65: obaa（おばあちゃん占い師）を削除＝standard / easy / spiritual の3種
        self.assertEqual(TONE_IDS, ["standard", "easy", "spiritual"])
        by_id = {t["id"]: t for t in TONE_DEFS}
        self.assertFalse(by_id["standard"]["rewrite"])
        for tid in ("easy", "spiritual"):
            self.assertTrue(by_id[tid]["rewrite"], tid)
            self.assertTrue(by_id[tid]["style"].strip(), tid)
            self.assertIn("要約・省略・短縮は禁止", by_id[tid]["style"], tid)

    def test_fallback_rules_exist(self):
        for tid in ("easy", "spiritual"):
            rules = TONE_RULES[tid]
            self.assertTrue(rules.get("subs"), tid)
            for pair in rules["subs"]:
                self.assertEqual(len(pair), 2)


class TestCollectUnits(unittest.TestCase):
    def test_collect(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _make_person(d)
            units = collect_units(d)
        ids = [u["id"] for u in units]
        self.assertEqual(ids, ["synthesis", "axis_method",
                               "cluster_M-A_method", "M27_tarot"])
        by_id = {u["id"]: u for u in units}
        self.assertEqual(by_id["synthesis"]["kind"], "synthesis")
        self.assertEqual(by_id["axis_method"]["kind"], "axis")
        self.assertEqual(by_id["cluster_M-A_method"]["kind"], "cluster")
        self.assertEqual(by_id["M27_tarot"]["kind"], "tool")
        self.assertNotIn("# 統合鑑定レポート", by_id["synthesis"]["text"])
        self.assertNotIn("※ 本レポートは", by_id["synthesis"]["text"])
        self.assertIn("## ■ 鑑定文", by_id["M27_tarot"]["text"])

    def test_collect_empty(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(collect_units(Path(td)), [])


class TestSplitUnit(unittest.TestCase):
    def _units(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _make_person(d)
            return {u["id"]: u for u in collect_units(d)}

    def test_tool_split(self):
        u = self._units()["M27_tarot"]
        sp = split_unit(u)
        # データ部: 使用した入力＋計算結果JSON＋この占術について
        self.assertIn("## ■ 使用した入力", sp["data_pre"])
        self.assertIn('"draw": 4', sp["data_pre"])
        self.assertIn("## ■ この占術について", sp["data_post"])
        # 本文: 鑑定文のみ
        self.assertEqual(sp["prose_heading"], "## ■ 鑑定文")
        self.assertEqual(len(sp["segments"]), 1)
        self.assertEqual(sp["segments"][0]["text"],
                         "抽出は11枚目と3枚目でした。47の数字に注意です。")
        self.assertNotIn("鑑定文", sp["data_pre"])

    def test_synthesis_split(self):
        u = self._units()["synthesis"]
        sp = split_unit(u)
        self.assertIn("## あなたのプロファイル", sp["data_pre"])
        self.assertIn("ライフパス）: 3", sp["data_pre"])
        self.assertNotIn("## 総括", sp["data_pre"])
        heads = [s["heading"] for s in sp["segments"]]
        self.assertEqual(heads[:2], ["## 総括", "## これからの過ごし方"])
        # mts5.27: 本文を持たない見出しは次の見出しへ連結して保持する
        # （以前は `## 分野別の中間レポート` が無言で消え、トーン化タブだけ
        #   見出しが欠落していた）
        self.assertIn("## 分野別の中間レポート\n\n### 手法軸（テスト軸）", heads)
        self.assertIn("総合得点は7点中5点", sp["segments"][0]["text"])
        self.assertEqual(sp["data_post"], "")
        # 見出しは本文セグメントに混入しない（口調化の対象は本文だけ）
        for seg in sp["segments"]:
            self.assertIsNone(re.search(r"(?m)^\s*#", seg["text"]), seg["id"])

    def test_axis_cluster_split(self):
        u = self._units()["axis_method"]
        sp = split_unit(u)
        self.assertTrue(sp["data_pre"].startswith("**対象**"), sp["data_pre"])
        self.assertIn("3つの傾向", sp["segments"][0]["text"])
        self.assertIsNone(sp["prose_heading"])
        self.assertEqual(sp["data_post"], "")

    def test_reassembly_covers_original(self):
        """data＋segs で元の本文を全部カバーする（漏れなし）"""
        for uid, u in self._units().items():
            sp = split_unit(u)
            recon = assemble_unit(u, sp, {s["id"]: s["text"] for s in sp["segments"]})
            # 原文の全数値が再構築済みにも存在
            nums_orig = sorted(re.findall(r"\d+", u["text"]))
            nums_recon = sorted(re.findall(r"\d+", recon))
            self.assertEqual(nums_orig, nums_recon, uid)
            # 本文セグメントのテキストが再構築済みに含まれる
            for s in sp["segments"]:
                self.assertIn(s["text"], recon, uid)
            # mts5.27: 見出し（##/###）が再構築後に欠落しない
            for h in re.findall(r"(?m)^(#{2,3}\s+.+)$", u["text"]):
                self.assertIn(h.strip(), recon, f"{uid}: 見出し欠落 {h!r}")


class TestSegmentPrompt(unittest.TestCase):
    def test_explicit_target_and_numbers(self):
        u = {"id": "M27_tarot", "kind": "tool", "title": "タロット", "text": ""}
        seg = {"id": "M27_tarot#s0", "heading": None,
               "text": "抽出は1枚目と3枚目でした。4の数字に注意です。"}
        tone = next(t for t in TONE_DEFS if t["id"] == "spiritual")
        sys_p, usr_p = build_segment_prompt(tone, u, seg)
        self.assertIn("スピリチュアル系の占い師", sys_p)
        self.assertIn("要約・省略・短縮は禁止", sys_p)
        self.assertIn("最低", usr_p)
        n = len(seg["text"])
        self.assertIn(f"最低 {int(n * 0.45) + 1} 字", usr_p)
        self.assertIn("1, 3, 4", usr_p)
        self.assertIn(seg["text"], usr_p)
        self.assertIn("タロット", usr_p)

    def test_no_numbers_omits_list(self):
        u = {"id": "x", "kind": "cluster", "title": "X", "text": ""}
        seg = {"id": "x#s0", "heading": None, "text": "数値のない本文です。"}
        tone = TONE_DEFS[1]
        _sys, usr = build_segment_prompt(tone, u, seg)
        self.assertNotIn("必ず含める数値", usr)

    def test_plain_output_instruction(self):
        u = {"id": "x", "kind": "cluster", "title": "X", "text": ""}
        seg = {"id": "x#s0", "heading": None, "text": "本文です。"}
        tone = TONE_DEFS[1]
        sys_p, usr_p = build_segment_prompt(tone, u, seg)
        # JSON 出力を要求しない（プレーンテキストのみ）
        self.assertNotIn("JSONオブジェクトのみ", sys_p)
        self.assertNotIn("JSONオブジェクトのみ", usr_p)
        self.assertIn("本文のみ", sys_p)
        self.assertIn("書き直し本文のみを出力", usr_p)


class TestParsePlain(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(parse_plain("  本文です。\n"), "本文です。")

    def test_fenced(self):
        self.assertEqual(parse_plain("```text\n本文です。\n```"), "本文です。")

    def test_json_wrapped(self):
        self.assertEqual(parse_plain('{"a": "本文です。"}'), "本文です。")

    def test_empty(self):
        self.assertEqual(parse_plain(""), "")
        self.assertEqual(parse_plain("   "), "")


class TestValidateSegment(unittest.TestCase):
    def test_ok(self):
        ok, why = validate_tone_segment("4の数字に注意です。", "4の数字に注意してね。")
        self.assertTrue(ok, why)

    def test_empty(self):
        self.assertFalse(validate_tone_segment("本文", "   ")[0])

    def test_too_short(self):
        self.assertFalse(validate_tone_segment("x" * 200, "短い")[0])

    def test_numbers_changed(self):
        self.assertFalse(validate_tone_segment(
            "総合得点は7点中5点です。", "総合得点は7点中6点です。")[0])

    def test_numbers_added(self):
        self.assertFalse(validate_tone_segment(
            "3つの傾向が見られます。", "3つと5つの傾向が見られます。")[0])

    def test_heading_injected(self):
        self.assertFalse(validate_tone_segment(
            "本文です。", "# 見出し\n本文です。")[0])

    def test_footer_injected(self):
        self.assertFalse(validate_tone_segment(
            "本文です。", "本文です。\n※ 本レポートはエンターテインメント")[0])


class _FailBackend(MockBackend):
    def generate(self, system_prompt, user_prompt, temperature=0.7,
                 max_tokens=1000, seed=None):
        self.calls.append({"system": system_prompt, "user": user_prompt})
        raise RuntimeError("503 high demand (giveup)")


class TestRunStageD(unittest.TestCase):
    def _run(self, td, backends, **kw):
        return run_stage_d_tones(
            Path(td) / "results", Path(td), backends,
            plan=FAST_PLAN, verbose=False, workers=2, **kw)

    def _n_segments(self, td):
        units = collect_units(Path(td))
        return sum(len(split_unit(u)["segments"]) for u in units)

    def test_ok_full_pipeline(self):
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            n_seg = self._n_segments(td)
            be = _RewriteBackend("ok")
            man = self._run(td, {LITE: be})
            for tid in ("easy", "spiritual"):
                t = man["tones"][tid]
                self.assertEqual(t["status"], "ok", tid)
                self.assertEqual(t["n_ok"], 4, tid)
                self.assertEqual(t["n_seg_ok"], n_seg, tid)
            # 呼び出し数 = セグメント数×3トーン
            self.assertEqual(len(be.calls), n_seg * 2)   # mts5.65: 口調は2トーン
            # units.json（HTML）と segments.json が書かれる
            up = Path(td) / "tone_reports" / "easy" / "units.json"
            uj = json.loads(up.read_text(encoding="utf-8"))
            self.assertEqual(set(uj), {"synthesis", "axis_method",
                                       "cluster_M-A_method", "M27_tarot"})
            # データ部の数値（使用した入力・計算結果JSON）が HTML に存在
            self.assertIn("1978", uj["M27_tarot"])
            self.assertIn("05:20", uj["M27_tarot"])
            self.assertIn("draw", uj["M27_tarot"])
            # 鑑定文の見出しと口調化マーカーが HTML に存在
            self.assertIn("鑑定文", uj["M27_tarot"])
            self.assertIn("（口調化）抽出は11枚目と3枚目", uj["M27_tarot"])
            # この占術について（data_post）もそのまま
            self.assertIn("この占術について", uj["M27_tarot"])
            # segments.json のデータ部は原文のまま
            sj = json.loads(
                (Path(td) / "tone_reports" / "easy" / "segments.json")
                .read_text(encoding="utf-8"))
            self.assertIn("## ■ 使用した入力", sj["M27_tarot"]["data_pre"])
            self.assertIn("## ■ この占術について", sj["M27_tarot"]["data_post"])
            self.assertEqual(
                set(sj["M27_tarot"]["segments"]),
                {"M27_tarot#s0"})
            # 生応答の記録
            raws = list((Path(td) / "tone_reports" / "easy" / "raw").glob("*.txt"))
            self.assertEqual(len(raws), n_seg)
            self.assertIn("attempt 1", raws[0].read_text(encoding="utf-8"))
            # レジューム: 2回目は再呼び出ししない
            be2 = _RewriteBackend("ok")
            man2 = self._run(td, {LITE: be2})
            self.assertEqual(be2.calls, [])
            self.assertEqual(man2["tones"]["easy"]["status"], "ok")

    def test_fallback_on_api_error(self):
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            be = _FailBackend()
            man = self._run(td, {LITE: be})
            for tid in ("easy", "spiritual"):
                t = man["tones"][tid]
                self.assertEqual(t["status"], "fallback", tid)
                self.assertEqual(t["n_ok"], 0, tid)
            # エラー理由が記録される
            self.assertTrue(man["tones"]["easy"]["errors"], "errors 非空")
            # フォールバック後、正常な backend で再実行 → 復帰する
            be2 = _RewriteBackend("ok")
            man2 = self._run(td, {LITE: be2})
            for tid in ("easy", "spiritual"):
                self.assertEqual(man2["tones"][tid]["status"], "ok", tid)

    def test_unit_level_fallback_partial(self):
        """数値が壊れるセグメントを持つユニットだけフォールバック（partial）"""
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            be = _RewriteBackend("drop47")
            man = self._run(td, {LITE: be})
            t = man["tones"]["easy"]
            self.assertEqual(t["status"], "partial")
            self.assertEqual(t["units"]["M27_tarot"], "fallback")
            self.assertEqual(t["units"]["synthesis"], "ok")
            up = json.loads(
                (Path(td) / "tone_reports" / "easy" / "units.json")
                .read_text(encoding="utf-8"))
            self.assertNotIn("M27_tarot", up)
            self.assertIn("synthesis", up)
            # 数値不一致が errors に残る
            self.assertTrue(any("数値不一致" in e for e in t["errors"]), t["errors"])

    def test_retry_with_feedback(self):
        """最初は短すぎ→理由付きリトライで成功（2試行）"""
        calls = {"n": 0}

        class _ShortThenOk(MockBackend):
            def generate(self, system_prompt, user_prompt, temperature=0.7,
                         max_tokens=1000, seed=None):
                self.calls.append({"user": user_prompt})
                seg = user_prompt.split("===\n", 1)[1]
                if "【再実行の注意】" in seg:
                    seg = seg.split("【再実行の注意】", 1)[0].strip()
                    return "（口調化）" + seg
                return "短い"

        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            be = _ShortThenOk()
            man = self._run(td, {LITE: be})
            t = man["tones"]["easy"]
            self.assertEqual(t["status"], "ok")
            n_seg = self._n_segments(td)
            # 全セグメント（×2トーン）が 2 試行で成功（mts5.65）
            self.assertEqual(len(be.calls), n_seg * 2 * 2)

    def test_model_failover(self):
        """主担当が API 失敗→別 lite へ移譲して成功"""
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            fail = _FailBackend()
            good = _RewriteBackend("ok")
            man = self._run(td, {LITE: fail, LITE2: good})
            for tid in ("easy", "spiritual"):
                self.assertEqual(man["tones"][tid]["status"], "ok", tid)
            # 全セグメント成功。good は全セグメント分（最後尾の試行が必ず成功）
            # fail は LITE 開始のセグメント分だけ 2 回ずつ（偶数）
            n_seg = self._n_segments(td)
            self.assertEqual(len(good.calls), n_seg * 2)   # mts5.65: 口調は2トーン
            self.assertEqual(len(fail.calls) % 2, 0)
            self.assertLessEqual(len(fail.calls), n_seg * 2 * 2)

    def test_resume_partial_segments(self):
        """ユニットが partial の場合、前回失敗したセグメントだけ再実行する"""
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            be = _RewriteBackend("drop47")  # M27_tarot のセグメントのみ失敗
            self._run(td, {LITE: be})
            # 2回目: 正常 backend。失敗したのは M27_tarot の1セグメント×2トーン（mts5.65）
            be2 = _RewriteBackend("ok")
            man2 = self._run(td, {LITE: be2})
            self.assertEqual(len(be2.calls), 2)
            self.assertEqual(man2["tones"]["easy"]["status"], "ok")
            up = json.loads(
                (Path(td) / "tone_reports" / "easy" / "units.json")
                .read_text(encoding="utf-8"))
            self.assertIn("M27_tarot", up)


class TestStageDChain(unittest.TestCase):
    def test_lite_only_by_default(self):
        chain = stage_d_chain(FAST_PLAN)
        self.assertEqual(chain, ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"])

    def test_non_lite_filtered(self):
        plan = {"stage_d": {"model": "gemini-3.5-flash",
                            "fallback": ["gemini-3.1-flash-lite"]}}
        chain = stage_d_chain(plan)
        self.assertNotIn("gemini-3.5-flash", chain)
        self.assertTrue(any("lite" in m for m in chain))

    def test_real_plan_has_stage_d(self):
        from fortunelib.mts import load_model_plan
        chain = stage_d_chain(load_model_plan())
        self.assertTrue(all("lite" in m for m in chain), chain)
        self.assertLessEqual(len(chain), 2)


UNIT_HTML = {
    "synthesis": "<p>あなたの総合得点は7点中5点だよ。</p>",
    "axis_method": "<p>手法軸では3つの傾向が見えるよ。</p>",
    "cluster_M-A_method": "<p>テストクラスタでは2系統が共通しているよ。</p>",
    "M27_tarot": "<p>抽出は1枚目と3枚目だったよ。4の数字に注意してね。</p>",
}


def person_with_tones(td):
    """Stage D 成功済みの人物ディレクトリを作る（HTML 系テストの共通フィクスチャ）"""
    d = Path(td)
    _make_person(d)
    tr = d / "tone_reports"
    man = {"tones": {}}
    for tid in ("easy", "spiritual"):
        (tr / tid).mkdir(parents=True)
        (tr / tid / "units.json").write_text(
            json.dumps(UNIT_HTML, ensure_ascii=False), encoding="utf-8")
        man["tones"][tid] = {
            "label": tid, "status": "ok",
            "units": {u: "ok" for u in UNIT_HTML},
            "n_ok": 4, "n_total": 4,
        }
    (tr / "tone_manifest.json").write_text(
        json.dumps(man, ensure_ascii=False), encoding="utf-8")
    return d


# 口調タブの実 DOM テスト（jsdom）で使う探索パス。
# 依存は verify/env_setup.sh が導入する（無い場合はテストを skip）。
_TESTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parent


def _find_node_and_jsdom():
    """(node 実行パス, jsdom の NODE_PATH) を返す。見つからなければ (node, None)。"""
    node = shutil.which("node")
    if not node:
        return None, None
    cands = []
    env_path = os.environ.get("TONE_JSDOM_NODE_PATH")
    if env_path:
        cands.append(Path(env_path))
    cands.append(_REPO_ROOT / "node_modules")
    cands.append(Path("/tmp/tone_jsdom/node_modules"))
    for c in cands:
        if (c / "jsdom" / "package.json").is_file():
            return node, str(c)
    try:
        out = subprocess.run(["npm", "root", "-g"], capture_output=True,
                             text=True, timeout=30)
        g = Path(out.stdout.strip())
        if (g / "jsdom" / "package.json").is_file():
            return node, str(g)
    except Exception:  # noqa: BLE001 - npm が無い環境では skip に落ちる
        pass
    return node, None


class TestToneUiDomBehaviour(unittest.TestCase):
    """mts5.26 / BUG-23: 口調切替タブが「実 DOM で実際に切り替わる」ことを検証する。

    背景（mts5.25 の教訓）: 実行 JS（IIFE）が body 直後＝本文の .tone-text より前に
    置かれていたため、パース時点で querySelectorAll('.tone-text') が 0 件になり、
    タブは出るがクリックしても何も変わらなかった。既存テストは文字列アサーション
    のみで JS を実行しないため検出できず、Node での DOM モックも
    「.tone-text を先に用意していた」ため順序の問題を隠蔽していた。
    """

    def _build(self, td):
        from fortunelib.html_report import build_html
        d = person_with_tones(td)
        out = build_html(d, person_id="test")
        return out, out.read_text(encoding="utf-8")

    def test_tone_ui_block_precedes_body_text(self):
        """前提の明示: tone UI（＝実行 JS）は本文 .tone-text より前に出る。

        この順序自体は意図どおり（タブをヘッダー直下に固定表示するため）。
        だからこそ JS 側の遅延初期化が必須であり、この前提が崩れたら
        テストを見直すべき＝前提を固定するためのアサーション。
        """
        with tempfile.TemporaryDirectory() as td:
            _, html_text = self._build(td)
        ui_at = html_text.find('id="tone-data"')
        text_at = html_text.find('class="tone-text"')
        self.assertGreater(ui_at, -1)
        self.assertGreater(text_at, -1)
        self.assertLess(ui_at, text_at,
                        "tone UI が本文より後ろにある（テストの前提が変化）")

    def test_tone_js_defers_until_dom_ready(self):
        """JS が DOMContentLoaded / readyState で遅延初期化している（実装の契約）。"""
        from fortunelib.html_report import _TONE_JS
        self.assertIn("DOMContentLoaded", _TONE_JS)
        self.assertIn("readyState", _TONE_JS)
        self.assertIn("function boot", _TONE_JS)
        # 遅延収集（収集前に setTone が呼ばれても取り直す）保険
        self.assertIn("if(!texts.length) collect();", _TONE_JS)

    def test_tone_data_json_is_not_double_escaped(self):
        """mts5.25 回帰: 埋め込まれた HTML 値が二重エスケープされていない。"""
        with tempfile.TemporaryDirectory() as td:
            _, html_text = self._build(td)
        m = re.search(
            r'<script type="application/json" id="tone-data">(.*?)</script>',
            html_text, re.S)
        self.assertIsNotNone(m)
        payload = json.loads(m.group(1).replace("<\\/", "</"))
        easy_syn = payload["tones"]["easy"]["units"]["synthesis"]
        self.assertEqual(easy_syn, UNIT_HTML["synthesis"])
        self.assertNotIn("&lt;", easy_syn)

    def test_click_switches_tone_in_real_dom(self):
        """jsdom（実 HTML パーサ＋文書順での script 実行）でクリック検証。

        修正前の実測: has_bar=True / n_buttons=4 なのに changed_on_easy=False
        （＝ユーザー報告と同一症状）。修正後: True かつ標準へ戻すと元に戻る。
        """
        node, node_path = _find_node_and_jsdom()
        if not node:
            self.skipTest("node が無いため実 DOM テストを skip")
        if not node_path:
            self.skipTest("jsdom が無い（verify/env_setup.sh で導入）")
        script = _TESTS_DIR / "tone_ui_domtest.js"
        self.assertTrue(script.is_file(), script)
        with tempfile.TemporaryDirectory() as td:
            out, _ = self._build(td)
            env = dict(os.environ)
            env["NODE_PATH"] = node_path
            cp = subprocess.run([node, str(script), str(out)],
                                capture_output=True, text=True,
                                timeout=180, env=env)
            self.assertEqual(cp.returncode, 0,
                             (cp.stdout[-2000:], cp.stderr[-2000:]))
            res = json.loads(cp.stdout.strip().splitlines()[-1])
        self.assertTrue(res.get("ok"), res)
        self.assertTrue(res.get("has_bar"), res)
        self.assertEqual(res.get("n_buttons"), 3)   # mts5.65: 3トーン
        self.assertFalse(res.get("errors"), res)
        # 切替対象が実在する（修正前は IIFE 実行時に 0 件だった）
        self.assertGreater(res.get("n_tone_text", 0), 0, res)
        self.assertTrue(res.get("all_units_present"), res)
        # クリックで口調が変わり、標準へ戻すと元に戻る（BUG-23 の本質）
        self.assertTrue(res.get("changed_on_easy"), res)
        self.assertTrue(res.get("restored_on_standard"), res)
        self.assertFalse(res.get("broken_on_easy"),
                         "二重エスケープ（mts5.25 回帰）")
        self.assertEqual(res.get("saved_tone"), "standard")

    def test_out_of_scope_units_stay_standard_in_real_dom(self):
        """mts5.27: scope=narrative で、個別占術の節はクリックしても標準のまま。

        （tone_units に対象ユニットを埋め込み、JS が対象外を orig に固定する）
        """
        node, node_path = _find_node_and_jsdom()
        if not node:
            self.skipTest("node が無いため実 DOM テストを skip")
        if not node_path:
            self.skipTest("jsdom が無い（verify/env_setup.sh で導入）")
        script = _TESTS_DIR / "tone_ui_domtest.js"
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))          # 標準成果物（results/ ほか）を用意
            plan = {"stage_d": {"model": LITE, "fallback": [LITE2],
                                "scope": "narrative"}}
            be = _RewriteBackend("ok")
            run_stage_d_tones(Path(td) / "results", Path(td), {LITE: be},
                              plan=plan, verbose=False, workers=2)
            from fortunelib.html_report import build_html
            out = build_html(Path(td), person_id="test")
            env = dict(os.environ)
            env["NODE_PATH"] = node_path
            cp = subprocess.run([node, str(script), str(out)],
                                capture_output=True, text=True,
                                timeout=180, env=env)
            self.assertEqual(cp.returncode, 0,
                             (cp.stdout[-2000:], cp.stderr[-2000:]))
            res = json.loads(cp.stdout.strip().splitlines()[-1])
        self.assertEqual(res.get("scope_units"), 3, res)   # tool を除く3ユニット
        self.assertGreaterEqual(res.get("n_out_of_scope", 0), 1, res)
        self.assertEqual(res.get("out_of_scope_unit"), "M27_tarot", res)
        self.assertTrue(res.get("out_of_scope_unchanged"),
                        "対象外ユニットが切り替わってしまった")
        self.assertTrue(res.get("in_scope_changed"),
                        "対象ユニットが切り替わっていない")


class TestToneScope(unittest.TestCase):
    """mts5.27: 口調化の対象範囲（scope=narrative で物語系のみ）

    背景: 全ユニット（67）を口調化すると 77セグメント/トーン＝231呼び出し/3トーン。
    無料枠（lite RPM15/RPD500×2レーン）では 2バッチ目（9トーン）で 693呼び出しに
    達し RPD をほぼ使い切る。→ 物語系（統合＋軸＋中間＝14ユニット）に限定する。
    """

    def test_scope_helpers(self):
        plan_narrative = {"stage_d": {"scope": "narrative"}}
        plan_all = {"stage_d": {"scope": "all"}}
        self.assertEqual(tone_scope(plan_narrative), "narrative")
        self.assertEqual(tone_scope(plan_all), "all")
        # 未指定は後方互換で "all"（既存テスト・旧プランが壊れない）
        self.assertEqual(tone_scope({}), "all")
        self.assertEqual(tone_scope({"stage_d": {"scope": "???"}}), "all")
        self.assertEqual(set(TONE_SCOPES), {"all", "narrative", "synthesis"})

    def test_filter_units(self):
        units = [{"id": "synthesis", "kind": "synthesis"},
                 {"id": "axis_method", "kind": "axis"},
                 {"id": "cluster_M-A_method", "kind": "cluster"},
                 {"id": "M27_tarot", "kind": "tool"}]
        self.assertEqual([u["id"] for u in filter_units(units, "narrative")],
                         ["synthesis", "axis_method", "cluster_M-A_method"])
        self.assertEqual(len(filter_units(units, "all")), 4)
        self.assertEqual(NARRATIVE_KINDS, ("synthesis", "axis", "cluster"))

    def test_narrative_scope_skips_tool_units(self):
        """scope=narrative: 個別占術は呼び出しゼロ・マニフェストにも記録される"""
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            be = _RewriteBackend("ok")
            man = run_stage_d_tones(
                Path(td) / "results", Path(td), {LITE: be},
                plan={**FAST_PLAN, "stage_d": {"model": LITE,
                                               "fallback": [LITE2],
                                               "scope": "narrative"}},
                verbose=False, workers=2)
            self.assertEqual(man["scope"], "narrative")
            self.assertNotIn("M27_tarot", man["target_units"])
            self.assertIn("synthesis", man["target_units"])
            for tid in ("easy", "spiritual"):
                t = man["tones"][tid]
                self.assertEqual(t["status"], "ok", tid)
                self.assertEqual(t["n_ok"], 3, tid)          # 4 → 3（tool 除外）
                self.assertNotIn("M27_tarot", t["units"])
                self.assertIn("synthesis", t["units"])
            # units.json に個別占術が入らない（＝HTML 側も標準のまま）
            up = json.loads((Path(td) / "tone_reports" / "easy"
                             / "units.json").read_text(encoding="utf-8"))
            self.assertNotIn("M27_tarot", up)
            self.assertIn("synthesis", up)

    def test_scope_all_keeps_previous_behaviour(self):
        """scope=all: mts5.22〜5.26 と同じく全ユニットを対象にする"""
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            be = _RewriteBackend("ok")
            man = run_stage_d_tones(
                Path(td) / "results", Path(td), {LITE: be},
                plan={**FAST_PLAN, "stage_d": {"model": LITE,
                                               "fallback": [LITE2],
                                               "scope": "all"}},
                verbose=False, workers=2)
            self.assertEqual(man["scope"], "all")
            self.assertIn("M27_tarot", man["target_units"])
            self.assertEqual(man["tones"]["easy"]["n_ok"], 4)

    def test_scope_switch_prunes_previous_results(self):
        """all で作った後に narrative で再実行すると、個別占術の成果は削除される

        （残すと HTML の tone-data に載り続け、呼び出し削減の意味が無くなる）
        """
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            plan_all = {**FAST_PLAN, "stage_d": {"model": LITE,
                                                 "fallback": [LITE2],
                                                 "scope": "all"}}
            run_stage_d_tones(Path(td) / "results", Path(td), {LITE: _RewriteBackend("ok")},
                              plan=plan_all, verbose=False, workers=2)
            up = json.loads((Path(td) / "tone_reports" / "easy"
                             / "units.json").read_text(encoding="utf-8"))
            self.assertIn("M27_tarot", up)
            # narrative へ切替（backend は何も呼ばれない＝レジュームで足りる）
            be2 = _RewriteBackend("ok")
            man = run_stage_d_tones(
                Path(td) / "results", Path(td), {LITE: be2},
                plan={**FAST_PLAN, "stage_d": {"model": LITE,
                                               "fallback": [LITE2],
                                               "scope": "narrative"}},
                verbose=False, workers=2)
            self.assertEqual(be2.calls, [])                 # 再生成なし
            self.assertEqual(man["scope"], "narrative")
            up2 = json.loads((Path(td) / "tone_reports" / "easy"
                              / "units.json").read_text(encoding="utf-8"))
            seg2 = json.loads((Path(td) / "tone_reports" / "easy"
                               / "segments.json").read_text(encoding="utf-8"))
            self.assertNotIn("M27_tarot", up2)               # 削除された
            self.assertNotIn("M27_tarot", seg2)
            self.assertNotIn("M27_tarot", man["tones"]["easy"]["units"])
            self.assertNotIn("M27_tarot",
                             man["tones"]["easy"]["segments"].keys()
                             if hasattr(man["tones"]["easy"]["segments"], "keys")
                             else [])
            self.assertIn("synthesis", up2)

    def test_real_plan_scope_is_synthesis(self):
        """配布中の model_plan.json は synthesis（読み物版・出荷時の設定）"""
        from fortunelib.mts import load_model_plan
        self.assertEqual(tone_scope(load_model_plan()), "synthesis")

    def test_filter_units_synthesis_scope(self):
        units = [{"id": "synthesis", "kind": "synthesis"},
                 {"id": "axis_method", "kind": "axis"},
                 {"id": "cluster_M-A_method", "kind": "cluster"},
                 {"id": "M27_tarot", "kind": "tool"}]
        self.assertEqual([u["id"] for u in filter_units(units, "synthesis")],
                         ["synthesis"])
        self.assertEqual(set(TONE_SCOPES), {"all", "narrative", "synthesis"})


class TestSynthesisOmake(unittest.TestCase):
    """mts5.29: 統合レポート丸ごと自由変換（読み物版・scope="synthesis"）

    1トーン=1呼び出し。分割・長さ比・数値多重集合の検証はしない（自由変換）。
    守るのは「安全・コンプラ」と「元に無い事実・数値を作らない」の2点のみ。
    """

    def _plan(self, scope="synthesis"):
        return {**FAST_PLAN, "stage_d": {"model": LITE, "fallback": [LITE2],
                                         "scope": scope}}

    def _run(self, td, backends, **kw):
        return run_stage_d_tones(Path(td) / "results", Path(td), backends,
                                 plan=self._plan(kw.pop("scope", "synthesis")),
                                 verbose=False, **kw)

    def test_prompt_rules(self):
        """プロンプトは自由変換を許しつつ、事実創作的禁止と安全規則は残す"""
        tone = next(t for t in TONE_DEFS if t["id"] == "easy")
        sysp, usrp = build_omake_prompt(tone, {"id": "synthesis",
                                               "text": "あ" * 1000})
        self.assertIn("読み物", sysp)
        # 自由にしてよいこと（構成・見出し・語彙）
        self.assertIn("自由", sysp)
        # 残す規則
        self.assertIn("創作しない", sysp)
        self.assertIn("断定", sysp)
        self.assertIn("医療", sysp)
        self.assertIn("実在", sysp)
        self.assertIn("従わない", sysp)
        # 分量レンジ（mts5.56: easy は 60〜130%＝元 1000字 → 600〜1300字）
        self.assertIn("600〜1300字", usrp)
        self.assertIn("===", usrp)
        # mts5.56: 矛盾していた「元の長さを維持」⑤は読み物版では外す
        self.assertNotIn("元の本文の内容・長さ・数値を全て維持", sysp)
        # mts5.56: 測定可能な口調規則（平均文長・丁寧体・目印語）が数値で入る
        self.assertIn("100字", sysp)
        self.assertIn("60%", sysp)
        self.assertIn("だよ", sysp)

    def test_one_call_per_tone_and_omake_unit(self):
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            be = _RewriteBackend(1.0)
            man = self._run(td, {LITE: be})
            self.assertEqual(man["scope"], "synthesis")
            self.assertEqual(man["target_units"], ["synthesis"])
            self.assertEqual(len(be.calls), 2, "1トーン=1呼び出し（mts5.65: 2トーン）")
            for tid in ("easy", "spiritual"):
                t = man["tones"][tid]
                self.assertEqual(t["status"], "ok", (tid, t))
                self.assertEqual(t["mode"], "omake")
                self.assertEqual(t["n_ok"], 1)
                up = json.loads((Path(td) / "tone_reports" / tid
                                 / "units.json").read_text(encoding="utf-8"))
                self.assertEqual(list(up), [OMAKE_UNIT_ID])
                self.assertIn("総括", up[OMAKE_UNIT_ID])     # 本文が入っている
                seg = json.loads((Path(td) / "tone_reports" / tid
                                  / "segments.json").read_text(encoding="utf-8"))
                self.assertIn(OMAKE_UNIT_ID, seg)
            # 個別占術・軸・中間の成果は作らない（標準のまま）
            up = json.loads((Path(td) / "tone_reports" / "easy"
                             / "units.json").read_text(encoding="utf-8"))
            for banned in ("M27_tarot", "axis_method", "cluster_M-A_method"):
                self.assertNotIn(banned, up)

    def test_short_output_retries_then_omits_tone(self):
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            be = _RewriteBackend("omake_short")
            man = self._run(td, {LITE: be})
            # 2トーン × 最大2試行（mts5.65）
            self.assertEqual(len(be.calls), 4)
            for tid in ("easy", "spiritual"):
                t = man["tones"][tid]
                self.assertEqual(t["status"], "fallback", tid)
                self.assertTrue(t["errors"], tid)
                up = json.loads((Path(td) / "tone_reports" / tid
                                 / "units.json").read_text(encoding="utf-8"))
                self.assertEqual(up, {})
            # 全トーン失敗 → HTML 側はカードを出さない（標準のみ）
            from fortunelib.html_report import load_tone_data
            self.assertIsNone(load_tone_data(Path(td)))

    def test_ratio_range_gate(self):
        """元の 50% 未満は不合格・50%以上は合格（分量レンジ）"""
        self.assertEqual(OMAKE_MIN_RATIO, 0.5)
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            be = _RewriteBackend(0.9)
            man = self._run(td, {LITE: be})
            self.assertEqual(man["tones"]["easy"]["status"], "ok")
            self.assertGreaterEqual(man["tones"]["easy"]["ratio"], OMAKE_MIN_RATIO)

    def test_resume_keeps_omake(self):
        """2回目の実行では ok 済みトーンを再生成しない（呼び出し0）"""
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            self._run(td, {LITE: _RewriteBackend(1.0)})
            be2 = _RewriteBackend(1.0)
            man = self._run(td, {LITE: be2})
            self.assertEqual(be2.calls, [])
            self.assertEqual(man["tones"]["easy"]["status"], "ok")

    def test_numbers_new_is_recorded_but_not_blocking(self):
        """元に無い数値を足しても生成は止めない（診断のみ・ユーザー決定）"""
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            be = _RewriteBackend(1.0)
            man = self._run(td, {LITE: be})
            self.assertEqual(man["tones"]["easy"]["numbers_new"], [])

    def test_switch_from_narrative_prunes_units(self):
        """narrative → synthesis へ切替えると、前回のユニット成果は消える"""
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            self._run(td, {LITE: _RewriteBackend(1.0)}, scope="narrative")
            up = json.loads((Path(td) / "tone_reports" / "easy"
                             / "units.json").read_text(encoding="utf-8"))
            self.assertIn("synthesis", up)
            self.assertIn("axis_method", up)
            self._run(td, {LITE: _RewriteBackend(1.0)}, scope="synthesis")
            up2 = json.loads((Path(td) / "tone_reports" / "easy"
                              / "units.json").read_text(encoding="utf-8"))
            self.assertEqual(list(up2), [OMAKE_UNIT_ID])


    def test_synthesis_view_switches_in_real_dom(self):
        """mts5.46: 標準が初期表示で、読み物版が同じ本文枠を切り替える。"""
        node, node_path = _find_node_and_jsdom()
        if not node:
            self.skipTest("node が無いため実 DOM テストを skip")
        if not node_path:
            self.skipTest("jsdom が無い（verify/env_setup.sh で導入）")
        script = _TESTS_DIR / "tone_ui_domtest.js"
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            plan = {"reliability": {"backoff_503_s": 0.01},
                    "stage_d": {"model": LITE, "fallback": [LITE2],
                                "scope": "synthesis"}}
            run_stage_d_tones(Path(td) / "results", Path(td),
                              {LITE: _RewriteBackend("tagged")},
                              plan=plan, verbose=False, workers=2)
            from fortunelib.html_report import build_html
            out = build_html(Path(td), person_id="test")
            env = dict(os.environ)
            env["NODE_PATH"] = node_path
            cp = subprocess.run([node, str(script), str(out)],
                                capture_output=True, text=True,
                                timeout=180, env=env)
            self.assertEqual(cp.returncode, 0,
                             (cp.stdout[-2000:], cp.stderr[-2000:]))
            res = json.loads(cp.stdout.strip().splitlines()[-1])
        self.assertEqual(res.get("errors"), [], res)
        self.assertTrue(res.get("synthesis_variants_json_present"), res)
        self.assertTrue(res.get("synthesis_switcher_present"), res)
        self.assertEqual(res.get("synthesis_buttons"), 3, res)   # mts5.65: 3トーン
        self.assertEqual(res.get("synthesis_tones"),
                         ["easy", "spiritual"], res)   # mts5.65: obaa を削除
        self.assertTrue(res.get("standard_default"), res)
        self.assertTrue(res.get("old_preference_ignored"), res)
        self.assertTrue(res.get("synthesis_note_present"), res)
        self.assertTrue(res.get("reading_version_changed"), res)
        self.assertTrue(res.get("reading_versions_differ"), res)
        self.assertTrue(res.get("standard_restored"), res)
        self.assertTrue(res.get("legacy_omake_card_absent"), res)
        self.assertTrue(res.get("no_extra_reading_card"), res)
        self.assertTrue(res.get("no_broken_escape"), res)

class TestHtmlToneUI(unittest.TestCase):
    def _person_with_tones(self, td):
        return person_with_tones(td)

    def test_tabs_rendered(self):
        from fortunelib.html_report import build_html
        with tempfile.TemporaryDirectory() as td:
            d = self._person_with_tones(td)
            out = build_html(d, person_id="test")
            html_text = out.read_text(encoding="utf-8")
        self.assertIn('class="tonebar"', html_text)
        self.assertEqual(html_text.count('class="tb-btn"'), 3)   # mts5.65: 3トーン
        self.assertIn('data-tone="standard"', html_text)
        self.assertIn('data-tone="spiritual"', html_text)
        self.assertIn('data-unit="synthesis"', html_text)
        self.assertIn('data-unit="M27_tarot"', html_text)
        self.assertIn('data-unit="axis_method"', html_text)
        self.assertIn('data-unit="cluster_M-A_method"', html_text)
        m = re.search(
            r'<script type="application/json" id="tone-data">'
            r'(.*?)</script>', html_text, re.S)
        self.assertIsNotNone(m)
        payload = json.loads(m.group(1).replace("<\\/", "</"))
        self.assertEqual(set(payload["tones"]),
                         {"standard", "easy", "spiritual"})
        self.assertEqual(set(payload["tones"]["easy"]["units"]),
                         set(UNIT_HTML))
        # mts5.25 回帰: units.json の値は HTML そのままで埋め込まれる
        # （md_to_html 再適用による二重エスケープ &lt;p&gt; は禁止）
        self.assertEqual(payload["tones"]["easy"]["units"]["synthesis"],
                         UNIT_HTML["synthesis"])
        self.assertNotIn("&lt;", payload["tones"]["easy"]["units"]["synthesis"])
        self.assertIn('<div class="tone-text" data-unit="M27_tarot">',
                      html_text)
        self.assertIn("localStorage.getItem('fortune_tone')", html_text)

    def test_no_tonebar_without_stage_d(self):
        from fortunelib.html_report import build_html
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _make_person(d)
            out = build_html(d, person_id="test")
            html_text = out.read_text(encoding="utf-8")
        self.assertNotIn('class="tonebar"', html_text)
        self.assertNotIn('id="tone-data"', html_text)
        self.assertIn('data-unit="synthesis"', html_text)

    def test_legacy_plain_units_json_still_rendered(self):
        """mts5.22/5.23 形式（プレーン Markdown の値）は md_to_html される"""
        from fortunelib.html_report import build_html
        with tempfile.TemporaryDirectory() as td:
            d = self._person_with_tones(td)
            plain = {"synthesis": "大運は4期目に移行しています。",
                     "axis_method": "3つの傾向が見えます。",
                     "cluster_M-A_method": "2系統が共通しています。",
                     "M27_tarot": "1枚目と3枚目です。"}
            p = d / "tone_reports" / "easy" / "units.json"
            p.write_text(json.dumps(plain, ensure_ascii=False), encoding="utf-8")
            out = build_html(d, person_id="test")
            html_text = out.read_text(encoding="utf-8")
        m = re.search(
            r'<script type="application/json" id="tone-data">'
            r'(.*?)</script>', html_text, re.S)
        payload = json.loads(m.group(1).replace("<\\/", "</"))
        self.assertIn("<p>大運は4期目に移行しています。</p>",
                      payload["tones"]["easy"]["units"]["synthesis"])

    def test_partial_tone_still_tabbed(self):
        """units.json が1ユニット欠けてもタブは出る（JS規則で代替）"""
        from fortunelib.html_report import build_html
        with tempfile.TemporaryDirectory() as td:
            d = self._person_with_tones(td)
            partial = {u: t for u, t in UNIT_HTML.items() if u != "M27_tarot"}
            p = d / "tone_reports" / "easy" / "units.json"
            p.write_text(json.dumps(partial, ensure_ascii=False),
                         encoding="utf-8")
            out = build_html(d, person_id="test")
            html_text = out.read_text(encoding="utf-8")
        self.assertIn('data-tone="easy"', html_text)
        m = re.search(
            r'<script type="application/json" id="tone-data">'
            r'(.*?)</script>', html_text, re.S)
        payload = json.loads(m.group(1).replace("<\\/", "</"))
        self.assertNotIn("M27_tarot", payload["tones"]["easy"]["units"])
        self.assertIn("synthesis", payload["tones"]["easy"]["units"])


# ---------------------------------------------------------------- mts5.56
# 口調の弁別（案1〜3）: 固定割当・測定可能な規則・事後検証と1回だけの再試行
# ----------------------------------------------------------------
class _LiveBackend(LLMBackend):
    """is_mock=False のスタブ（再試行・警告・移譲の検証用・mts5.56/5.57）。

    本物の API は呼ばないが「モックではない」ため、弁別の再試行と警告が有効になる。
    replies は呼び出し順に消費（尽きたら最後の要素を使い続ける）。
    `fail_first` は最初の N 回を例外にする（API 一時エラーの再現・mts5.57）。
    """

    is_mock = False

    def __init__(self, replies: list[str] | None = None, fail_first: int = 0,
                 exc: str = "503 UNAVAILABLE"):
        self.replies = list(replies or [])
        self.calls: list[dict] = []
        self.fail_first = int(fail_first)
        self.exc = exc

    def generate(self, system_prompt, user_prompt, temperature=0.7,
                 max_tokens=1000, seed=None):
        self.calls.append({"system": system_prompt, "user": user_prompt})
        if len(self.calls) <= self.fail_first:
            raise RuntimeError(self.exc)
        idx = min(len(self.calls) - 1, len(self.replies) - 1)
        return self.replies[idx] if self.replies else ""


_EASY_ON_SPEC_SENTS = [
    "きょうは少し特別な日だよ。", "気分が軽くなるといいね。",
    "あせらなくて大丈夫だよ。", "あなたのペースで進めばいいと思う。",
    "小さな一歩が力になるんだよ。", "空を見上げるだけで気分が変わるみたい。",
    "だれかに話すとすっきりするね。", "今夜はゆっくり休もう。",
]
_EASY_OFF_SPEC_SENTS = [
    # 標準の文体のまま（丁寧体・長文・目印語なし）＝弁別の全項目で未達になる文
    "あなたの運気はとても穏やかに流れており、これからの時期は焦らずに準備を"
    "整えることが何よりも大切だと考えられますので、日々の暮らしの中で小さな"
    "変化を見落とさないようにしてください。",
]


def _repeat_until(sents: list[str], n: int) -> str:
    out = ""
    while len(out) < n:
        out += "".join(sents)
    return out


class TestToneDiscrimination(unittest.TestCase):
    """mts5.56: トーン別仕様・固定割当・弁別指標・再試行と警告"""

    def _plan(self):
        return {"reliability": {"backoff_503_s": 0.01},
                "stage_d": {"model": LITE, "fallback": [LITE2],
                            "scope": "synthesis"}}

    def _run(self, td, backends, **kw):
        return run_stage_d_tones(Path(td) / "results", Path(td), backends,
                                 plan=self._plan(), verbose=False, **kw)

    def _spec_off(self):
        return _repeat_until(_EASY_OFF_SPEC_SENTS, int(len(SYN_MD) * 0.9))

    def _spec_on(self):
        return _repeat_until(_EASY_ON_SPEC_SENTS, int(len(SYN_MD) * 1.0))

    # --- 案2: 測定可能な規則 ------------------------------------------------
    def test_specs_are_measurable(self):
        self.assertEqual(set(TONE_SPECS), {"easy", "spiritual"})
        for tid, sp in TONE_SPECS.items():
            self.assertLess(sp["ratio_min"], sp["ratio_max"], tid)
            self.assertGreaterEqual(sp["ratio_min"], OMAKE_MIN_RATIO, tid)
            self.assertGreater(sp["marker_min"], 0, tid)
            self.assertTrue(sp["markers"], tid)
            self.assertLessEqual(float(sp["polite_max"]), 1.0, tid)
            self.assertTrue(sp["howto"].strip(), tid)
        # 未知トーンは安全側（硬い下限・制限なし）
        d = tone_spec("unknown")
        self.assertEqual(d["ratio_min"], OMAKE_MIN_RATIO)
        self.assertEqual(d["polite_max"], 1.0)

    def test_omake_ratio_range_is_tone_specific(self):
        self.assertEqual(omake_ratio_range("easy", 1000), (600, 1300))
        self.assertEqual(omake_ratio_range("spiritual", 1000), (800, 1400))
        self.assertEqual(omake_ratio_range("unknown", 1000)[0], 500)

    def test_omake_style_block_drops_keep_rule(self):
        """⑤「元の長さを維持」を外し、数値つきの規則に置き換える"""
        for tid, expect in (("easy", "100字"), ("spiritual", "95字")):
            tone = next(t for t in TONE_DEFS if t["id"] == tid)
            blk = omake_style_block(tone)
            self.assertNotIn("⑤ ※", blk, tid)
            self.assertNotIn("長さ・数値を全て維持", blk, tid)
            self.assertIn(expect, blk, tid)
            self.assertIn("⑦", blk, tid)          # 数値・固有名詞の凍結は残す
        sysp, usrp = build_omake_prompt(
            next(t for t in TONE_DEFS if t["id"] == "spiritual"),
            {"id": "synthesis", "text": "あ" * 1000})
        self.assertIn("800〜1400字", usrp)
        self.assertIn("エネルギー", sysp)

    def test_tone_from_prompt(self):
        """demo・テスト用のトーン判定（読み物版でも効く・mts5.56）"""
        for tid in ("easy", "spiritual"):
            tone = next(t for t in TONE_DEFS if t["id"] == tid)
            sysp, _ = build_omake_prompt(tone, {"id": "synthesis",
                                                "text": "あ" * 1000})
            self.assertEqual(tone_from_prompt(sysp), tid, tid)
        self.assertIsNone(tone_from_prompt("ふつうのプロンプト"))

    # --- 案1: 固定割当 ------------------------------------------------------
    def test_tone_model_lane_assignment(self):
        chain = [LITE, LITE2]
        self.assertEqual(tone_model("easy", chain), LITE2)
        self.assertEqual(tone_model("spiritual", chain), LITE)
        # かつて同一モデルだった easy と spiritual は必ず別レーン
        self.assertNotEqual(tone_model("easy", chain),
                            tone_model("spiritual", chain))
        # chain が1本でも落ちない
        self.assertEqual(tone_model("easy", [LITE]), LITE)

    def test_tone_model_plan_override(self):
        chain = [LITE, LITE2]
        plan = {"stage_d": {"tone_models": {"easy": LITE, "spiritual": LITE2}}}
        self.assertEqual(tone_model("easy", chain, plan), LITE)
        self.assertEqual(tone_model("spiritual", chain, plan), LITE2)
        bad = {"stage_d": {"tone_models": {"easy": "gemini-9-nope"}}}
        self.assertEqual(tone_model("easy", chain, bad), LITE)     # chain 外→chain[0]

    def test_fixed_assignment_used_by_runner(self):
        """1回目の担当は固定割当どおり（レーン1）。3試行目だけが別レーンに出る（mts5.62）"""
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            be0, be1 = _LiveBackend([self._spec_on()]), _LiveBackend([self._spec_on()])
            man = self._run(td, {LITE: be0, LITE2: be1}, tone_ids=["easy", "spiritual"])
            e, o = man["tones"]["easy"], man["tones"]["spiritual"]
            # mts5.65: easy はレーン1（LITE2）・spiritual はレーン0（LITE）が一次担当
            # easy は1試行で通る＝レーン1だけ
            self.assertEqual(e["models_tried"], [LITE2])
            self.assertEqual(e["model"], LITE2)
            self.assertEqual(len(be1.calls), 2, "easy 1回＋spiritual の3試行目1回")
            # spiritual は easy 向けの本文では口調を満たせない
            # → 同じレーンで2試行 → **別レーン**（mts5.62）
            self.assertEqual(o["models_tried"], [LITE, LITE, LITE2])
            self.assertEqual(len(be0.calls), 2, "spiritual の1・2試行目")
            self.assertEqual(o["chosen_attempt"], 1, "同点なら先の試行を採る")
            self.assertEqual(o["model"], LITE, "採用した本文はレーン0のもの")
            self.assertTrue(o["discrimination"]["problems"])

    # --- 案3: 弁別指標 ------------------------------------------------------
    def test_discrimination_report(self):
        on = self._spec_on()
        rep = discrimination_report(SYN_MD, on, "easy")
        self.assertEqual(rep["problems"], [], rep)
        self.assertEqual(rep["limits"]["avg_sentence_max"], 100)
        self.assertGreaterEqual(rep["marker_total"], 6)
        self.assertIn("丁寧体", discrimination_summary(rep))
        # 丁寧体のまま・目印語なし → 未達として説明が付く
        off = self._spec_off()
        rep2 = discrimination_report(SYN_MD, off, "easy")
        self.assertTrue(rep2["problems"])
        joined = "／".join(rep2["problems"])
        self.assertIn("丁寧体", joined)
        self.assertIn("目印語", joined)
        # 標準と同一なら類似度で落ちる
        rep3 = discrimination_report(SYN_MD, SYN_MD, "easy")
        self.assertTrue(any("類似度" in p for p in rep3["problems"]), rep3)
        # 短すぎる文（指標のしきい値に届かない分量でも例外にしない）
        self.assertIsInstance(discrimination_report(SYN_MD, "", "easy")["problems"], list)

    def test_feedback_for_retry_names_targets(self):
        rep = discrimination_report(SYN_MD, self._spec_off(), "easy")
        fb = feedback_for_retry(next(t for t in TONE_DEFS if t["id"] == "easy"),
                                rep, 600, 1000)
        self.assertIn("【再実行の注意】", fb)
        self.assertIn("6 回以上", fb)
        # 平均が閾値以内なら、再試行指示に平均文長の未達は出さない。
        long_text = "長い文" + "あ" * 150 + "。"
        long_rep = discrimination_report(SYN_MD, long_text, "easy")
        long_fb = feedback_for_retry(next(t for t in TONE_DEFS if t["id"] == "easy"),
                                     long_rep, 600, 1000, text=long_text)
        self.assertIn("100 字以内", long_fb)
        self.assertIn("600〜1300字", fb)
        self.assertIn("丁寧体", fb)

    # --- 案3: 再試行（非モックのみ） ----------------------------------------
    def test_live_retry_recovers(self):
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            be = _LiveBackend([self._spec_off(), self._spec_on()])
            man = self._run(td, {LITE: _LiveBackend(), LITE2: be},
                            tone_ids=["easy"])
            self.assertEqual(len(be.calls), 2, "1回だけ再試行する")
            self.assertIn("【再実行の注意】", be.calls[1]["user"])
            t = man["tones"]["easy"]
            self.assertEqual(t["status"], "ok")
            self.assertEqual(t["attempts"], 2)
            self.assertEqual(t["discrimination"]["problems"], [])
            self.assertTrue(t["discrimination"]["enforced"])

    def test_live_off_spec_is_accepted_with_warning(self):
        """再試行しても外れたら**採用**し、警告に残す（生成は止めない）"""
        runcheck.clear()
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            be = _LiveBackend([self._spec_off()])       # 何度でも同じ（外れ）
            be_alt = _LiveBackend()                     # 別レーンは空応答（作り直しに失敗）
            man = self._run(td, {LITE: be_alt, LITE2: be},
                            tone_ids=["easy"])
            self.assertEqual(len(be.calls), 2, "同じレーンは最大2試行（mts5.62）")
            self.assertEqual(len(be_alt.calls), 1, "3試行目は別レーン（mts5.62）")
            t = man["tones"]["easy"]
            self.assertEqual(t["status"], "ok")
            self.assertEqual(t["attempts"], 3)
            self.assertEqual(t["models_tried"], [LITE2, LITE2, LITE])
            self.assertEqual(t["chosen_attempt"], 1)   # 同点なら先の試行・空応答は候補外
            self.assertEqual([a["outcome"] for a in t["attempt_log"]],
                             ["style", "style", "empty"])
            self.assertTrue(t["discrimination"]["problems"])
            self.assertEqual(
                json.loads((Path(td) / "tone_reports" / "easy" / "units.json")
                           .read_text(encoding="utf-8")).keys(),
                {OMAKE_UNIT_ID})
        self.assertTrue(any("口調の指定に未達" in w for w in runcheck.WARNINGS),
                        runcheck.WARNINGS)
        runcheck.clear()

    def test_mock_records_but_does_not_retry_or_warn(self):
        """モック（demo・単体テスト）は指標を記録するだけ（再試行・警告なし）"""
        runcheck.clear()
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            be = _RewriteBackend(1.0)                   # 標準のまま（外れ）
            man = self._run(td, {LITE: be}, tone_ids=["easy"])
            self.assertEqual(len(be.calls), 1)
            t = man["tones"]["easy"]
            self.assertEqual(t["status"], "ok")
            self.assertEqual(t["attempts"], 1)
            self.assertFalse(t["discrimination"]["enforced"])
            self.assertTrue(t["discrimination"]["problems"])   # 記録はする
            self.assertIsNotNone(t["discrimination"]["polite_ratio"])
        self.assertEqual(runcheck.WARNINGS, [], runcheck.WARNINGS)
        runcheck.clear()

    def test_pairwise_similarity_helper(self):
        sims = pairwise_similarity({"easy": "あ" * 100, "spiritual": "あ" * 100})
        self.assertAlmostEqual(sims["easy|spiritual"], 1.0, places=2)
        self.assertEqual(pairwise_similarity({"easy": "あ" * 10}), {})

    def test_pair_warning_when_tones_are_too_similar(self):
        """トーン同士が似すぎなら警告（非モックのみ）・manifest にも残す"""
        runcheck.clear()
        same = self._spec_on()
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            be = _LiveBackend([same])
            man = self._run(td, {LITE: _LiveBackend([same]), LITE2: be},
                            tone_ids=["easy", "spiritual"])
            pairs = man["discrimination"]["pairwise"]
            self.assertIn("easy|spiritual", pairs)
            self.assertGreaterEqual(pairs["easy|spiritual"], TONE_PAIR_SIM_MAX)
            warnings = list(runcheck.WARNINGS)
        self.assertTrue(any("似すぎ" in w for w in warnings), warnings)
        runcheck.clear()

    def test_pair_warning_suppressed_for_mock(self):
        runcheck.clear()
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            man = self._run(td, {LITE: _RewriteBackend("tagged")})
            self.assertTrue(man["discrimination"]["pairwise"])
        self.assertEqual(runcheck.WARNINGS, [], runcheck.WARNINGS)
        runcheck.clear()


class TestOmakeFailoverAndNotes(unittest.TestCase):
    """読み物版の移譲・分量規則・欠けたトーンの注記（mts5.57）。

    実機（mts5.56）で「かんたん」が表示されなかった原因は2つ:
      ①読み物版が**短く要約された**（元の24%）ため、2回目も同じモデルを叩き直して
        503 に当たりトーンごと欠けた（回答本文も捨てていた）
      ②その欠落が HTML に**何も出なかった**（タブが1つ減るだけ）
    """

    def _plan(self):
        return {"reliability": {"backoff_503_s": 0.01},
                "stage_d": {"model": LITE, "fallback": [LITE2],
                            "scope": "synthesis"}}

    def _run(self, td, backends, **kw):
        return run_stage_d_tones(Path(td) / "results", Path(td), backends,
                                 plan=self._plan(), verbose=False, **kw)

    def _spec_on(self):
        return _repeat_until(_EASY_ON_SPEC_SENTS, int(len(SYN_MD) * 1.0))

    # --- 分量の規則をプロンプトにも入れる（原因①の一次対策） ---------------
    def test_style_block_states_volume_and_forbids_summary(self):
        # mts5.65: obaa を削除（元 6,761字＝easy 4,056字／spiritual 5,408字）
        for tid, notes in (("easy", "4056"), ("spiritual", "5408")):
            tone = next(t for t in TONE_DEFS if t["id"] == tid)
            blk = omake_style_block(tone, 6761)
            self.assertIn("要約", blk, tid)              # 要約禁止を明示
            self.assertIn("⑧", blk, tid)
            self.assertIn(notes, blk, tid)               # トーン別の分量（字）
        # 分量の指定を外した場合は「おおよそ…字」だけ落ちる（後方互換）
        blk0 = omake_style_block(next(t for t in TONE_DEFS if t["id"] == "easy"))
        self.assertIn("⑧", blk0)
        sysp, _ = build_omake_prompt(next(t for t in TONE_DEFS if t["id"] == "easy"),
                                     {"id": "synthesis", "text": "あ" * 6761})
        self.assertIn("要約", sysp)
        self.assertIn("4056〜8789字", sysp)

    # --- 移送（別レーンへ移譲・原因①の二次対策） --------------------------
    def test_alt_lite_model_picks_other_lane(self):
        self.assertEqual(alt_lite_model(LITE, [LITE, LITE2]), LITE2)
        self.assertEqual(alt_lite_model(LITE2, [LITE, LITE2]), LITE)
        self.assertEqual(alt_lite_model(LITE, [LITE]), LITE)   # 1本しか無い

    def test_api_error_fails_over_to_the_other_model(self):
        """1回目が API 一時エラー → 同じモデルを叩き直さず別レーンで成功する"""
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            # easy の担当はレーン1（LITE2）。1回目だけ 503 で落ちる。
            be_primary = _LiveBackend([self._spec_on()], fail_first=1)
            be_alt = _LiveBackend([self._spec_on()])
            man = self._run(td, {LITE: be_alt, LITE2: be_primary}, tone_ids=["easy"])
            t = man["tones"]["easy"]
            self.assertEqual(t["status"], "ok", t)
            self.assertEqual(t["attempts"], 2)
            self.assertEqual(t["models_tried"], [LITE2, LITE])   # 移譲の記録
            self.assertEqual(t["reason"], None)
            self.assertEqual(len(be_primary.calls), 1)
            self.assertEqual(len(be_alt.calls), 1)
            self.assertEqual(t["model"], LITE)
            # HTML 側も「かんたん」が出る（欠落しない）
            from fortunelib.html_report import load_tone_data
            td_ = load_tone_data(Path(td))
            self.assertIn("easy", td_["omake"])
            self.assertEqual(td_["missing"], [])

    def test_both_lanes_failing_records_reason_and_note(self):
        """両レーンとも落ちたら理由を記録し、HTML に欠落の注記を出す"""
        runcheck.clear()
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            be_primary = _LiveBackend([], fail_first=9)
            be_alt = _LiveBackend([], fail_first=9)
            man = self._run(td, {LITE: be_alt, LITE2: be_primary}, tone_ids=["easy"])
        t = man["tones"]["easy"]
        self.assertEqual(t["status"], "fallback")
        self.assertEqual(t["reason"], "api")
        # mts5.62: 3試行目は**別レーンのもう一度**（両レーンを交互に使う）
        self.assertEqual(t["models_tried"], [LITE2, LITE, LITE2])
        self.assertEqual(len(be_alt.calls), 1)                   # 別レーンは1回だけ
        self.assertEqual([a["outcome"] for a in t["attempt_log"]],
                         ["api", "api", "api"])
        # mts5.57: 警告台帳にも残る（既定では止めない・RUN_STRICT=1 で不合格）
        self.assertTrue(any("読み物版を作れませんでした" in w for w in runcheck.WARNINGS),
                        runcheck.WARNINGS)
        runcheck.clear()

    def test_short_output_retries_same_model(self):
        """短すぎ（分量不足）は同じモデルで作り直す（移譲ではない）"""
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            be_primary = _LiveBackend(["短いです。", self._spec_on()])  # 1回目だけ短い
            man = self._run(td, {LITE: _LiveBackend([self._spec_on()]),
                                 LITE2: be_primary}, tone_ids=["easy"])
            t = man["tones"]["easy"]
            self.assertEqual(t["status"], "ok", t)
            self.assertEqual(t["models_tried"], [LITE2, LITE2])   # 移譲しない
            self.assertEqual(len(be_primary.calls), 2)
            # 2回目のプロンプトに分量の注意が入る
            self.assertIn("【再実行の注意】", be_primary.calls[1]["user"])
            self.assertIn("字", be_primary.calls[1]["user"])

    def test_third_attempt_on_the_other_lane_fixes_the_tone(self):
        """2回続けて外れたら**別レーンで3試行目**を作り、通った方を採用する（mts5.62）"""
        runcheck.clear()
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            off = _repeat_until(_EASY_OFF_SPEC_SENTS, int(len(SYN_MD) * 0.9))
            be_off = _LiveBackend([off])
            be_fix = _LiveBackend([self._spec_on()])
            man = self._run(td, {LITE: be_fix, LITE2: be_off}, tone_ids=["easy"])
            t = man["tones"]["easy"]
        self.assertEqual(t["status"], "ok")
        self.assertEqual(t["reason"], None)          # 採用したので失敗理由は無い
        self.assertEqual(t["models_tried"], [LITE2, LITE2, LITE])
        self.assertEqual(t["model"], LITE, "通った3試行目を採用")
        self.assertEqual(t["discrimination"]["problems"], [])
        self.assertEqual(len(be_off.calls), 2)
        self.assertEqual(len(be_fix.calls), 1)
        runcheck.clear()

    def test_off_spec_on_both_lanes_is_accepted_with_warning(self):
        """両レーンとも外れたら、**良い方**を採用して警告に残す（生成は止めない）"""
        runcheck.clear()
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            off = _repeat_until(_EASY_OFF_SPEC_SENTS, int(len(SYN_MD) * 0.9))
            man = self._run(td, {LITE: _LiveBackend([off]), LITE2: _LiveBackend([off])},
                            tone_ids=["easy"])
            t = man["tones"]["easy"]
        self.assertEqual(t["status"], "ok")
        self.assertEqual(t["attempts"], 3)
        self.assertTrue(t["discrimination"]["problems"])
        self.assertTrue(any("口調の指定に未達" in w for w in runcheck.WARNINGS),
                        runcheck.WARNINGS)
        runcheck.clear()
        runcheck.clear()

    # --- HTML の注記（原因②） --------------------------------------------
    def test_html_note_lists_missing_tones_with_reason(self):
        from fortunelib.html_report import build_html, load_tone_data
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            self._run(td, {LITE: _LiveBackend([self._spec_on()]),
                           LITE2: _LiveBackend([self._spec_on()])},
                      tone_ids=["spiritual"])   # easy だけ欠けた状態を作る
            man = json.loads((Path(td) / "tone_reports" / "tone_manifest.json")
                             .read_text(encoding="utf-8"))
            man["tones"]["easy"] = {"label": "かんたん（中学生向け）",
                                    "status": "fallback", "mode": "omake",
                                    "reason": "api", "model": LITE2,
                                    "units": {}, "n_ok": 0, "n_total": 1,
                                    "chars": 0, "ratio": 0.24, "attempts": 2,
                                    "models_tried": [LITE2, LITE],
                                    "errors": ["RuntimeError: 503"]}
            (Path(td) / "tone_reports" / "tone_manifest.json").write_text(
                json.dumps(man, ensure_ascii=False), encoding="utf-8")
            out = build_html(Path(td), person_id="test")
            html = out.read_text(encoding="utf-8")
            td_data = load_tone_data(Path(td))
        self.assertIn("synthesis-missing-note", html)
        self.assertIn("かんたん（中学生向け）", html)
        self.assertIn("AIの一時的な混雑・接続エラー", html)
        self.assertNotIn("スピリチュアル風）", html)        # 成功したトーンは注記に出ない
        self.assertEqual([m["id"] for m in td_data["missing"]], ["easy"])
        self.assertEqual(set(td_data["omake"]), {"spiritual"})

    def test_html_note_is_absent_when_all_tones_exist(self):
        from fortunelib.html_report import build_html
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            self._run(td, {LITE: _LiveBackend([self._spec_on()])})
            html = build_html(Path(td), person_id="test").read_text(encoding="utf-8")
        self.assertNotIn("synthesis-missing-note", html)

    def test_verbose_summary_lists_missing_tone(self):
        """実行ログにも「作れなかったトーン」を理由つきで出す（原因②の再発防止）"""
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as td:
            _make_person(Path(td))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                run_stage_d_tones(
                    Path(td) / "results", Path(td),
                    {LITE: _LiveBackend([], fail_first=9),
                     LITE2: _LiveBackend([], fail_first=9)},
                    plan=self._plan(), verbose=True, tone_ids=["easy"])
            log = buf.getvalue()
        self.assertIn("読み物版を作れなかったトーン", log)
        self.assertIn("かんたん（中学生向け）", log)
        self.assertIn("AIの一時的な混雑・接続エラー", log)


if __name__ == "__main__":
    unittest.main()
