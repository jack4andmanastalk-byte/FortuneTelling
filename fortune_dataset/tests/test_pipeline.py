# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

from fortunelib.backend import MockBackend
from fortunelib.pipeline import PipelineContext, run_divination
from fortunelib.profile import normalize_input
from fortunelib.registry import REGISTRY, all_slugs, availability_reason, is_available

from tests.fixtures.consultation import CONSULTATION, CONSULTATION_ALT


def make_ctx(backend=None, raw=None):
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
        backend=backend or MockBackend(),
        seed=42,
    )


class TestRegistry(unittest.TestCase):
    """占術レジストリ"""

    def test_count_53(self):
        # 65実行単位（数秘術は生年月日/氏名の2モード）＋ 御縁のある神さま(M31) = 66
        self.assertEqual(len(REGISTRY), 53)
        self.assertEqual(len(all_slugs()), 53)
        self.assertEqual(len(set(all_slugs())), 53)  # スラグの一意性

    def test_groups(self):
        from collections import Counter
        c = Counter(e["group"] for e in REGISTRY.values())
        self.assertEqual(c["G1"], 14)
        self.assertEqual(c["G2"], 4)
        self.assertEqual(c["G3"], 8)
        self.assertEqual(c["G4"], 13)
        self.assertEqual(c["G5"], 2)
        self.assertEqual(c["G6"], 12)  # 疑似体験系の整理後

    def test_prompt_ids_unique_per_entry(self):
        # 66実行単位それぞれが固有のプロンプトIDを持つ（P01〜P66）
        pids = [e["prompt_id"] for e in REGISTRY.values()]
        self.assertEqual(len(pids), 53)
        self.assertEqual(len(set(pids)), 53)

    def test_availability(self):
        ctx = make_ctx()
        # 全入力あり → すべて利用可能
        for slug in all_slugs():
            self.assertTrue(is_available(slug, ctx.inputs), slug)

        # 血液型なし → 血液型占いのみ不可
        raw = {"birth": {"date": "1990-01-15"}, "consultation": CONSULTATION}
        ni = normalize_input(raw)
        self.assertFalse(is_available("blood", ni))
        self.assertEqual(availability_reason("blood", ni), "血液型が未入力")
        self.assertTrue(is_available("seiza", ni))

        # 相手なし → シナストリー・パリミチャム不可
        raw2 = {"birth": {"date": "1990-01-15"}, "blood_type": "A",
                "name_kanji": "山田 太郎", "name_kana": "やまだ たろう"}
        ni2 = normalize_input(raw2)
        self.assertFalse(is_available("synastry", ni2))
        self.assertFalse(is_available("parimicham", ni2))

    def test_calc_key_none_for_g6(self):
        for slug, e in REGISTRY.items():
            if e["group"] == "G6":
                # 抽選・選定をコードで行うG6は calc_key を持つ（deities は M31 で追加）
                if slug in ("pendulum", "african", "astragaloi", "deities",
                            "meso", "christian"):
                    self.assertIsNotNone(e["calc_key"], slug)
                else:
                    self.assertIsNone(e["calc_key"], slug)


class TestPipeline(unittest.TestCase):
    """パイプライン実行"""

    def test_run_ok(self):
        ctx = make_ctx()
        res = run_divination("kyusei", ctx)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["issues"], [])
        md = Path(res["file"])
        self.assertTrue(md.exists())
        content = md.read_text(encoding="utf-8")
        self.assertIn("# 九星気学", content)
        self.assertIn("[近似]", content)          # 近似バッジ（時刻・出生地不明）
        self.assertIn("二黒土星", content)         # 計算結果
        self.assertIn("※ 本結果はエンターテインメント目的", content)  # 共通フッター
        # raw json
        raw_path = md.with_name(md.stem + "_raw.json")
        self.assertTrue(raw_path.exists())
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        self.assertEqual(raw["module"], "M03")
        self.assertEqual(raw["divination"], "九星気学")

    def test_skip_guard(self):
        ctx = make_ctx()
        run_divination("seiza", ctx)
        backend_calls_before = len(ctx.backend.calls)
        res = run_divination("seiza", ctx)   # 2回目
        self.assertEqual(res["status"], "skipped")
        self.assertEqual(len(ctx.backend.calls), backend_calls_before)  # 生成されない

    def test_unavailable(self):
        raw = {"birth": {"date": "1990-01-15"}, "consultation": CONSULTATION}
        ctx = make_ctx(raw=raw)
        res = run_divination("blood", ctx)
        self.assertEqual(res["status"], "unavailable")
        self.assertEqual(res["reason"], "血液型が未入力")

    def test_g6_must_mention(self):
        """G6: プロファイル事実が織り込まれていない応答 → 再生成
        ★2026-08-27: 空テキスト防止ガード（<50字は error）導入に伴い、
          フィクスチャは50字以上の実長に近い文にしている"""
        bad = ("誰にでも当てはまる抽象的なメッセージであり、具体的な事実には"
               "一切触れない文章です。読んでも何も得られないでしょう。"
               "このような応答は再生成されるべきです。")
        good = ("あなたの本命星は二黒土星です。土の性質を持つこの星は、"
                "着実な積み重ねを大切にする運勢を示します。今年は足元を固める"
                "ことで信頼を得られるでしょう。慢心せず育てる年です。")
        backend = MockBackend(responses=[bad, good])
        ctx = make_ctx(backend=backend)
        res = run_divination("delphi", ctx)
        self.assertEqual(res["status"], "ok")
        # 再生成され、保存テキストは good
        raw = json.loads(Path(res["file"]).with_name(Path(res["file"]).stem + "_raw.json")
                         .read_text(encoding="utf-8"))
        self.assertIn("二黒土星", raw["result"]["text"])
        self.assertGreaterEqual(len(backend.calls), 2)

    def test_summary_appended(self):
        ctx = make_ctx()
        run_divination("kyusei", ctx)
        run_divination("seiza", ctx)
        summary = json.loads(ctx.summary_path.read_text(encoding="utf-8"))
        self.assertIn("themes", summary)
        self.assertEqual(len(summary["themes"]), 2)
        self.assertTrue(any("九星気学" in t for t in summary["themes"]))
        self.assertTrue(any("星座占い" in t for t in summary["themes"]))

    def test_no_calc_key(self):
        """G6（計算不要）で calc_result なしでも実行できる"""
        ctx = make_ctx()
        res = run_divination("delphi", ctx)
        self.assertEqual(res["status"], "ok")

    def test_g6_not_in_summary(self):
        """クロスチェック指摘: 創作系（G6）の出力はサマリーに追記しない（事実としての伝播防止）"""
        ctx = make_ctx()
        run_divination("kyusei", ctx)   # G1 → サマリーに入る
        run_divination("delphi", ctx)   # G6 → サマリーに入らない
        summary = json.loads(ctx.summary_path.read_text(encoding="utf-8"))
        self.assertTrue(any("九星気学" in t for t in summary["themes"]))
        self.assertFalse(any("デルポイ" in t for t in summary["themes"]))

    def test_empty_consultation_today_mode(self):
        """⑦クロスチェック拡張: 空の相談内容 → 今日の運勢モード（自動判定）"""
        raw = {"birth": {"date": "1990-01-15"}}
        ctx = make_ctx(raw=raw)
        res = run_divination("tarot", ctx)
        self.assertEqual(res["status"], "ok")
        # todayモード: 相談内容が置換され、システムにtoday指示が入る
        user_prompt = ctx.backend.calls[-1]["user"]
        sys_prompt = ctx.backend.calls[-1]["system"]
        self.assertIn("（なし・今日の運勢モード）", user_prompt)
        self.assertIn("【今日の運勢モード】", sys_prompt)


if __name__ == "__main__":
    unittest.main()


class TestEmptyTextGuard(unittest.TestCase):
    """空の生成テキストはファイル化しない。

    md を保存すると auto-skip で空の結果が恒久化するため、error にする。
    """

    def test_empty_text_returns_error_without_saving(self):
        ctx = make_ctx(backend=MockBackend(responses=["", ""]))
        # eto は計算も入力も揃っている slug
        res = run_divination("eto", ctx)
        self.assertEqual(res["status"], "error")
        self.assertIn("空", res["reason"])
        # ファイルが書かれていない（再実行で生成し直せる）
        mds = list(Path(ctx.results_dir).glob("*.md")) if Path(ctx.results_dir).exists() else []
        self.assertEqual(mds, [])

    def test_short_text_returns_error_without_saving(self):
        ctx = make_ctx(backend=MockBackend(responses=["短い", "短い"]))
        res = run_divination("eto", ctx)
        self.assertEqual(res["status"], "error")
        mds = list(Path(ctx.results_dir).glob("*.md")) if Path(ctx.results_dir).exists() else []
        self.assertEqual(mds, [])

    def test_normal_text_still_saves(self):
        """通常テキストは従来どおり保存される（回帰確認）"""
        ctx = make_ctx()
        res = run_divination("eto", ctx)
        self.assertEqual(res["status"], "ok")
        self.assertTrue(Path(res["file"]).exists())
