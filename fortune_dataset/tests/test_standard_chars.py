# -*- coding: utf-8 -*-
"""mts5.58: 標準本文の下限引き上げ（毎回 4,000字前後へ）と検証器の字数表示。

ご依頼（Turn 13）:
  ①標準本文の帯の見直し＝**下限を上げて毎回 4,000字前後に揃える**
  ②検証器に**標準タブの字数**を毎回表示する

方針（実測にもとづく）:
  - 実機4回の標準本文は 3,434／3,471／3,978／4,745字（旧レンジ 3,400〜4,800・
    指示下限 4,148字）で、**指示に対する下振れ（実測比 0.83〜0.96）**のぶん
    小さめに出ていた。
  - そこで ①検証下限を 4,000 に上げ（割ったら1回だけ再生成）、
    ②プロンプトの【分量】は比例マージンではなく**明示レンジ**、
    ③出力構成の章予算も合計を指示下限へ引き上げ（章の足し上げと全体指示を一致）。
  - ※実数のピン留めは版ごとのテスト（mts5.60 で下限を 4,800 へ）に移した。
  - 占術の計算・プロファイル事実・画像は不変（プロンプトと検証だけの変更）。
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from tests.fixtures.consultation import CONSULTATION, CONSULTATION_ALT

ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "verify_run_output", ROOT.parent / "verify" / "verify_run_output.py")
vro = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(vro)


class TestFinalBandMts558(unittest.TestCase):
    """①標準本文の帯（fortunelib/synthesis.py）"""

    def test_band_and_instruct(self):
        """mts5.58 の水準（下限 4,000）が保たれていること。

        実数のピン留めは版ごとのテスト（mts5.60）側で行う。ここでは
        「下限が 4,000 以上」「指示が検証より上」という**関係**を守る。
        """
        from fortunelib.synthesis import FINAL_CHARS, FINAL_INSTRUCT_CHARS
        self.assertGreaterEqual(FINAL_CHARS[0], 4000)
        self.assertLess(FINAL_CHARS[0], FINAL_CHARS[1])
        self.assertLess(FINAL_INSTRUCT_CHARS[0], FINAL_INSTRUCT_CHARS[1])

    def test_instruct_is_above_validate(self):
        from fortunelib.synthesis import FINAL_CHARS, FINAL_INSTRUCT_CHARS
        self.assertGreater(FINAL_INSTRUCT_CHARS[0], FINAL_CHARS[0])   # 下振れの上乗せ
        # 指示の上限は検証の上限の内側（帯の外を指示しない）
        self.assertLessEqual(FINAL_INSTRUCT_CHARS[1], FINAL_CHARS[1])

    def test_prompt_uses_explicit_instruct_range(self):
        import re
        from fortunelib.synthesis import (FINAL_INSTRUCT_CHARS,
                                          build_crossaxis_final_prompt)
        sysp, _ = build_crossaxis_final_prompt(
            [{"axis": "method", "text": "あ" * 50},
             {"axis": "culture", "text": "い" * 50}], {"a": 1}, CONSULTATION)
        m = re.search(r"【分量】全体で(\d+)〜(\d+)字", sysp)
        self.assertIsNotNone(m)
        self.assertEqual((int(m.group(1)), int(m.group(2))),
                         FINAL_INSTRUCT_CHARS)

    def test_section_budgets_sum_to_the_instructed_floor(self):
        """章の足し上げ（◯字程度）＝指示下限。両者の一致を許さない（不一致は下振れの一因）。"""
        import re
        from fortunelib.synthesis import (FINAL_INSTRUCT_CHARS,
                                          build_crossaxis_final_prompt)
        sysp, _ = build_crossaxis_final_prompt(
            [{"axis": "method", "text": "あ" * 50}], {"a": 1}, CONSULTATION)
        budgets = [int(x) for x in re.findall(r"(\d+)字程度", sysp)]
        self.assertEqual(len(budgets), 6)                     # 出力構成は6章
        self.assertEqual(sum(budgets), FINAL_INSTRUCT_CHARS[0])

    def test_retry_uses_the_same_target(self):
        """再生成の指示も明示レンジ（FINAL_INSTRUCT_CHARS）を使う。"""
        from fortunelib import mts
        from fortunelib.synthesis import FINAL_CHARS, FINAL_INSTRUCT_CHARS

        class _Be:
            def __init__(self):
                self.calls = []

            def generate(self, sys_p, usr_p, temperature=0.7, max_tokens=1000,
                         seed=None):
                self.calls.append(usr_p)
                return "あ" * (3000 if len(self.calls) == 1 else 4500)

        mid = (FINAL_INSTRUCT_CHARS[0] + FINAL_INSTRUCT_CHARS[1]) // 2
        be = _Be()
        out = mts._gen_with_retry(
            be, "SYS", "USER", temp=0.65, temp2=0.45, max_tokens=6400,
            seed=1, band=FINAL_CHARS, target_mid=mid,
            instruct_band=FINAL_INSTRUCT_CHARS)
        self.assertEqual(len(be.calls), 2)                    # 1回目 3,000字 → 再生成
        self.assertIn(f"{FINAL_INSTRUCT_CHARS[0]}〜{FINAL_INSTRUCT_CHARS[1]}字",
                      be.calls[1])
        self.assertEqual(len(out), 4500)                      # 帯の中央に近い方を採用

    def test_in_band_text_is_not_regenerated(self):
        from fortunelib import mts
        from fortunelib.synthesis import FINAL_CHARS, FINAL_INSTRUCT_CHARS

        class _Be:
            def __init__(self):
                self.calls = 0

            def generate(self, sys_p, usr_p, temperature=0.7, max_tokens=1000,
                         seed=None):
                self.calls += 1
                return "あ" * 4300

        be = _Be()
        mts._gen_with_retry(be, "SYS", "USER", temp=0.65, temp2=0.45,
                            max_tokens=6400, seed=1, band=FINAL_CHARS,
                            target_mid=5000, instruct_band=FINAL_INSTRUCT_CHARS)
        self.assertEqual(be.calls, 1)

    def test_stage_c_passes_them(self):
        import inspect
        from fortunelib import mts
        src = inspect.getsource(mts.run_stage_c_mts)
        self.assertIn("FINAL_INSTRUCT_CHARS", src)
        self.assertIn("instruct_band=FINAL_INSTRUCT_CHARS", src)


class TestVerifierStdChars(unittest.TestCase):
    """②検証器: 標準タブ（口調の元テキスト）の字数表示"""

    MD = ("# 統合鑑定レポート\n\n**生成**: 2026-09-30T11:11:05+09:00／**分類軸**: method + culture"
          "／**参照**: 52種\n\n**ご相談**: テスト\n\n## あなたのプロファイル\n\n"
          "- 太陽星座: 牡羊座\n- 干支（年柱・立春基準）: 辛未\n\n---\n"
          + "あ" * 4400 +
          "\n\n---\n\n## 軸サマリー\n\n- **手法軸**（1643字）: `cluster_reports/AXIS_method.md`\n\n"
          "## 分野別の中間レポート\n\n### 手法軸\n\n- x\n\n"
          "---\n\n## 御縁のある神さま Top10\n\n*全占術と統合レポートの内容を踏まえて選定しています。*\n\n"
          "1. **ヘルメス**（ギリシャ・伝達） — 理由\n\n本文です。\n\n"
          "---\n※ 本レポートはエンターテインメントです。\n")

    def test_breakdown_counts(self):
        b = vro.std_chars_breakdown(self.MD)
        self.assertEqual(b["flash"], 4400)              # Flash 本文（このテスト用の固定値）
        self.assertGreater(b["profile"], 0)             # ヘッダ＋プロファイル
        self.assertGreater(b["toc"], 0)                 # 軸サマリー＋目次
        self.assertGreater(b["deities"], 0)             # 御縁のある神さま
        self.assertEqual(b["total"], len(self.MD.strip()))

    def test_band_is_in_sync_with_the_package(self):
        from fortunelib.synthesis import FINAL_CHARS, FINAL_INSTRUCT_CHARS
        self.assertEqual(tuple(vro.STD_BAND), FINAL_CHARS)
        self.assertEqual(tuple(vro.STD_INSTRUCT_BAND), FINAL_INSTRUCT_CHARS)

    def test_warns_when_outside_the_band(self):
        short = self.MD.replace("あ" * 4400, "あ" * 3000)
        warns = vro.check_std_chars(short)
        self.assertEqual(len(warns), 1)
        self.assertIn("3000字", warns[0]["detail"])
        self.assertEqual(vro.check_std_chars(self.MD), [])

    def test_html_std_chars(self):
        self.assertEqual(vro.html_std_chars(
            '<div id="synthesis-body" class="tone-text"><p>ああ</p>'
            '<div>い</div></div><p>外</p>'), 3)
        self.assertEqual(vro.html_std_chars(""), 0)
        self.assertEqual(vro.html_std_chars("<p>no body</p>"), 0)

    def test_report_shows_the_line(self):
        """表示そのものを守る（毎回出る＝検証レポートで見える）。"""
        src = (Path(__file__).resolve().parent.parent.parent
               / "verify" / "verify_run_output.py").read_text(encoding="utf-8")
        self.assertIn("標準本文 :", src)
        self.assertIn("標準タブ全体 ", src)
        # mts5.68: 読み物版の分量基準（標準タブ全体 − ご相談 − 目次）も毎回出す
        self.assertIn("読み物版の元テキスト ", src)
        self.assertIn("std_warnings", src)      # 帯の外は警告として残す
