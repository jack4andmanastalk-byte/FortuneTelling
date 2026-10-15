# -*- coding: utf-8 -*-
"""今日の運勢モード（⑦・クロスチェック拡張）のテスト"""
import json

from tests.fixtures.consultation import CONSULTATION, CONSULTATION_ALT
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fortunelib.backend import MockBackend
from fortunelib.batch import build_calc_results, build_profile_facts
from fortunelib.pipeline import PipelineContext, run_divination
from fortunelib.profile import normalize_input
from fortunelib.prompt import build_system_prompt, build_user_prompt, GENERIC_TODAY_TEXT
from fortunelib.today import get_today_instruction, SLUG_TO_OTHER_AI

JST = timezone(timedelta(hours=9))
RAW = {
    "birth": {"date": "1990-01-15", "time": "14:30", "place": "千葉県"},
    "gender": "M", "blood_type": "A",
    "name_kanji": "山田 太郎", "name_kana": "やまだ たろう",
    "consultation": "",  # 空 → 今日の運勢モード
    "target": "2026-08-15",
}
FIXED_NOW = datetime(2026, 8, 15, 12, 0, tzinfo=JST)


class TestTodayMapping(unittest.TestCase):
    """today指示のマッピング"""

    def test_all_slugs_have_instruction(self):
        """全スラグが today 指示を取得できる（個別 or 共通ベース）"""
        from fortunelib.registry import all_slugs
        for slug in all_slugs():
            inst = get_today_instruction(slug)
            self.assertTrue(inst and len(inst) > 10, slug)

    def test_specific_instruction(self):
        """代表的な占術は個別指示を持つ"""
        seiza = get_today_instruction("seiza")
        self.assertIn("今日の運気", seiza)
        omikuji = get_today_instruction("omikuji")
        self.assertIn("御神籤", omikuji)

    def test_mapping_coverage(self):
        """現存する全スラグが today 指示を得られる

        ※ 疑似体験系13種の削除（2026-08-18）により、別AI辞書側には
          対応先を失ったキーが残る。重要なのは「実装側の全スラグが
          today 指示を得られること」なので、そちらを検証する。
        """
        from fortunelib.registry import all_slugs
        from fortunelib.today import get_today_instruction
        missing = [s for s in all_slugs() if not get_today_instruction(s)]
        self.assertEqual(missing, [], f"today指示なし: {missing}")

    def test_generic_fallback(self):
        """カバラ（他AIに存在しない）は共通ベースにフォールバック"""
        inst = get_today_instruction("kabbalah")
        self.assertIn("今日の運勢（総合）", inst)


class TestPromptTodayMode(unittest.TestCase):
    """today_mode のプロンプト組み立て"""

    def test_system_today(self):
        p = build_system_prompt("P03", today_mode=True,
                                today_instruction=get_today_instruction("kyusei"))
        self.assertIn("【今日の運勢モード】", p)
        self.assertIn("対象日を出力の冒頭に必ず明記", p)

    def test_system_no_today(self):
        p = build_system_prompt("P03")
        self.assertNotIn("【今日の運勢モード】", p)

    def test_user_today(self):
        p = build_user_prompt("P03", today_mode=True, target_date="2026-08-15")
        self.assertIn("（なし・今日の運勢モード）", p)
        self.assertIn("対象日: 2026-08-15", p)

    def test_user_normal(self):
        p = build_user_prompt("P03", consultation=CONSULTATION)
        self.assertNotIn("今日の運勢モード", p)
        self.assertIn(CONSULTATION, p)


class TestPipelineTodayMode(unittest.TestCase):
    """パイプラインでの今日の運勢モード自動判定"""

    def setUp(self):
        self.ni = normalize_input(RAW)
        self.facts = build_profile_facts(self.ni)
        self.calc = build_calc_results(self.ni, session_id="today-test",
                                       consultation="", now=FIXED_NOW,
                                       rng_mode="reproducible")
        self.tmp = Path(tempfile.mkdtemp())
        self.ctx = PipelineContext(
            inputs=self.ni, profile_facts=self.facts, calc_results=self.calc,
            consultation="", results_dir=self.tmp / "results",
            summary_path=self.tmp / "profile_summary.json",
            backend=MockBackend(), seed=42,
        )

    def test_today_mode_auto(self):
        """相談内容が空 → システムにtoday指示・ユーザーに置換文が入る"""
        run_divination("kyusei", self.ctx)
        calls = self.ctx.backend.calls
        self.assertGreaterEqual(len(calls), 1)
        sys_p = calls[-1]["system"]
        usr_p = calls[-1]["user"]
        self.assertIn("【今日の運勢モード】", sys_p)
        self.assertIn("（なし・今日の運勢モード）", usr_p)

    def test_target_date_in_calc(self):
        """target_date・target_kanzashi・target_kyusei_day・target_weton が計算される"""
        self.assertEqual(self.calc["target_date"]["date"], "2026-08-15")
        self.assertTrue(self.calc["target_date"]["is_today"])
        self.assertIn("day", self.calc["target_kanzashi"])
        self.assertIn("day_star", self.calc["target_kyusei_day"])
        self.assertIn("weton_name", self.calc["target_weton"])
        self.assertEqual(self.calc["target_primbon"]["status"], "ok")

    def test_target_kanzashi_2026_08_15(self):
        """2026-08-15 の日干支（sxtwl: 辛酉）"""
        self.assertEqual(self.calc["target_kanzashi"]["day"], "辛酉")

    def test_markdown_contains_target(self):
        """出力Markdownに対象日が表示される"""
        run_divination("kyusei", self.ctx)
        md = (self.tmp / "results" / "M03_kyusei.md").read_text(encoding="utf-8")
        self.assertIn("対象日：2026-08-15", md)

    def test_normal_mode_no_today(self):
        """相談内容あり → todayモードにならない"""
        raw2 = dict(RAW)
        raw2["consultation"] = CONSULTATION
        raw2["target"] = ""  # 明示指定なし（実行日フォールバック）の状態を作る
        ni2 = normalize_input(raw2)
        calc2 = build_calc_results(ni2, session_id="x", consultation=CONSULTATION,
                                   now=FIXED_NOW, rng_mode="reproducible")
        ctx2 = PipelineContext(
            inputs=ni2, profile_facts=self.facts, calc_results=calc2,
            consultation=CONSULTATION,
            results_dir=self.tmp / "results2", summary_path=self.tmp / "s2.json",
            backend=MockBackend(), seed=42,
        )
        run_divination("kyusei", ctx2)
        sys_p = ctx2.backend.calls[-1]["system"]
        self.assertNotIn("【今日の運勢モード】", sys_p)
        # mts4.0表示層ゲート: 相談あり＋target空欄（実行日フォールバック）なら
        # 個別レポート冒頭に対象日行を出さない
        md2 = (self.tmp / "results2" / "M03_kyusei.md").read_text(encoding="utf-8")
        self.assertNotIn("対象日：", md2)


class TestTargetDisplayGate(unittest.TestCase):
    """対象日ディスプレイゲート（mts4.1・表示層）

    設計: 内部計算（target_* 4種・神々選定・seed）は常に実行日を保持したまま、
    「使用した入力」ヘッダと Stage B/C プロンプトの対象日行を次の条件で出す:
      今日の運勢モード（相談空欄） → 出す（仕様上、日付明記が必須）
      CSV target欄の明示指定あり   → 出す（相談が特定日を前提）
      相談あり＋target空欄         → 出さない（日付は紛らわしいため本文に混ぜない）
    明示指定の検出は inputs（ctx.inputs / ni）から導出し、calc_results の
    スキーマには手を入れない（B案統合・mts4.1）。
    """

    def _ni(self, consultation, target):
        raw = dict(RAW)
        raw["consultation"] = consultation
        raw["target"] = target
        return normalize_input(raw)

    def _calc(self, ni, consultation):
        return build_calc_results(ni, session_id="gate-test",
                                  consultation=consultation, now=FIXED_NOW,
                                  rng_mode="reproducible")

    def _md(self, ni, calc, consultation):
        tmp = Path(tempfile.mkdtemp())
        ctx = PipelineContext(
            inputs=ni, profile_facts=build_profile_facts(ni), calc_results=calc,
            consultation=consultation, results_dir=tmp / "results",
            summary_path=tmp / "profile_summary.json",
            backend=MockBackend(), seed=42,
        )
        run_divination("kyusei", ctx)
        return (tmp / "results" / "M03_kyusei.md").read_text(encoding="utf-8")

    def test_calc_schema_invariant_and_fallback(self):
        """calcスキーマ不変（date/is_todayのみ）＋明示・空欄フォールバックの意味論"""
        c_spec = self._calc(self._ni("仕事運", "2026-09-01"), "仕事運")
        self.assertEqual(set(c_spec["target_date"].keys()), {"date", "is_today"})
        self.assertEqual(c_spec["target_date"]["date"], "2026-09-01")
        self.assertFalse(c_spec["target_date"]["is_today"])
        c_blank = self._calc(self._ni("仕事運", ""), "仕事運")
        self.assertEqual(set(c_blank["target_date"].keys()), {"date", "is_today"})
        self.assertTrue(c_blank["target_date"]["is_today"])  # 実行日フォールバックは維持
        self.assertEqual(c_blank["target_date"]["date"], "2026-08-15")
        # 明示指定そのものは NormalizedInput 側にある（表示層の導出元）
        self.assertEqual(self._ni("仕事運", "2026-09-01").target_date.isoformat(),
                         "2026-09-01")
        self.assertIsNone(self._ni("仕事運", "").target_date)

    def test_consult_with_target_shown(self):
        """相談あり＋明示指定 → 対象日（指定日）を出す"""
        ni = self._ni("9月1日の契約、吉凶は？", "2026-09-01")
        md = self._md(ni, self._calc(ni, ni.consultation), ni.consultation)
        self.assertIn("対象日：2026-09-01（指定日）", md)

    def test_today_mode_blank_target_shown(self):
        """相談なし（今日の運勢モード）＋target空欄 → 実行日を今日として出す（仕様どおり必須）"""
        ni = self._ni("", "")
        md = self._md(ni, self._calc(ni, ""), "")
        self.assertIn("対象日：2026-08-15（今日）", md)

    def test_stage_bc_gate_sources(self):
        """構造チェック: mts.py と cellN2 が inputs 導出の対象日ゲートを持つこと"""
        mts = (Path(__file__).resolve().parent.parent
               / "fortunelib" / "mts.py").read_text(encoding="utf-8")
        self.assertIn("(today_mode or ni.target_date is not None)", mts)
        cell = (Path(__file__).resolve().parent.parent
                / "kaggle" / "cellN2_synthesis.py").read_text(encoding="utf-8")
        self.assertIn("not _consult.strip() or _explicit_t", cell)
        self.assertIn("_ni_for_target = _ni2", cell)
        # cellN2のinput_rawフォールバック（CTX経路で _ni2 が無い場合も明示指定を判定）
        self.assertIn('_s.get("input_raw")', cell)
        self.assertIn('explicit_t = bool', cell)


if __name__ == "__main__":
    unittest.main()
