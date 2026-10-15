# -*- coding: utf-8 -*-
"""中国語（簡体字）→ 日本語表記の変換テスト（mts5.31）

**背景**: 委譲している divicast は中国語の簡体字を返すため、六爻の
「計算結果（事実）」に簡体字がそのまま出ていました（全コード再検証で発見）。
方針は「表示用の文字だけ日本語表記へ寄せる（数値・構造は不変）」。

検証する内容:
  1. 変換表の文字が「本当に簡体字」（＝check_scripts の判定リストに入っている）
  2. 代表的な術語の変換結果
  3. **六爻の実出力に簡体字が1文字も残らないこと**（実データで確認）
  4. 易の64卦名が**両方の字形**（簡体字・伝統字形）で画像に解決すること
  5. **六爻の六神は起卦日の日干で決まる**（mts5.50 で発覚）ため、検証では
     起卦時刻を固定する。既定の起卦時刻はJST（コンテナのローカル時刻に依存しない）
"""
from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # fortune_dataset/
REPO = ROOT.parent                                     # リポジトリ直下

from fortunelib import text_ja                          # noqa: E402


def _load_simplified_list():
    """tools/check_scripts.py の簡体字リスト（検査用の正本）を読む"""
    spec = importlib.util.spec_from_file_location(
        "check_scripts", REPO / "tools" / "check_scripts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.load_simplified_only()


class TestTextJaTable(unittest.TestCase):
    # 日本語の標準字形だが、**卦名では伝統字形**を使う文字（表の分離理由を明示）
    GUA_ONLY_OK = {"随", "恒", "壮", "晋"}

    def test_only_simplified_chars_are_mapped(self):
        """術語表の左辺は「簡体字リストにある文字」だけ（日本語の漢字を書き換えない）"""
        simp = _load_simplified_list()
        wrong = sorted(ch for ch in text_ja.ZH_TO_JA_CHARS if ch not in simp)
        self.assertEqual(wrong, [], f"簡体字でない文字が表に入っています: {wrong}")

    def test_gua_table_is_limited_and_documented(self):
        """卦名専用表は、想定した4文字だけ（本文には適用しない）"""
        self.assertEqual(set(text_ja.ZH_TO_JA_GUA_CHARS),
                         self.GUA_ONLY_OK, "卦名専用表が想定外に増えています")
        # 本文（term）では書き換えない＝日本語の標準字形のまま
        for ch in self.GUA_ONLY_OK:
            self.assertEqual(text_ja.to_ja_text(f"これは{ch}です"),
                             f"これは{ch}です")
        # 卦名（name）では伝統字形へ
        for ch, ja in text_ja.ZH_TO_JA_GUA_CHARS.items():
            self.assertEqual(text_ja.to_ja_text(f"{ch}", "name"), ja)

    def test_targets_are_not_simplified(self):
        """変換先は簡体字ではない（置換後に簡体字が残らない）"""
        simp = _load_simplified_list()
        wrong = sorted({v for v in text_ja.ZH_TO_JA_CHARS.values() if v in simp})
        self.assertEqual(wrong, [], f"変換先が簡体字のままです: {wrong}")

    def test_representative_terms(self):
        cases = {
            "既济": "既濟", "未济": "未濟",            # 卦名＝伝統字形
            "青龙": "青龍", "勾陈": "勾陳", "腾蛇": "騰蛇",
            "驿马": "駅馬", "阳刃": "陽刃", "灾煞": "災煞",
            "天乙贵人": "天乙貴人", "谋星": "謀星", "华盖": "華蓋",
            "权": "権", "旧版编码": "旧版編碼",
            "父毋": "父毋",                             # 表に無い文字はそのまま
            "": "", "ABC123": "ABC123",
        }
        for src, want in cases.items():
            with self.subTest(src=src):
                self.assertEqual(text_ja.to_ja_text(src), want)

    def test_non_string_passthrough(self):
        for v in (None, 3, ["x"], {"a": 1}):
            self.assertIs(text_ja.to_ja_text(v), v)


class TestLiuyaoOutputIsJapanese(unittest.TestCase):
    """六爻の実出力（divicast）に簡体字が残らない"""

    @classmethod
    def setUpClass(cls):
        try:
            from fortunelib.calc.liuyao import liuyao_paipan
        except Exception as e:                       # pragma: no cover
            raise unittest.SkipTest(f"六爻の計算を読み込めません: {e}")
        cls._paipan = staticmethod(liuyao_paipan)

    CASES = [[6, 7, 8, 7, 8, 9], [7, 7, 7, 7, 7, 7], [8, 8, 8, 8, 8, 8],
             [9, 6, 9, 6, 9, 6], [6, 6, 6, 6, 6, 6]]

    def test_no_simplified_char_in_output(self):
        import json
        simp = _load_simplified_list()
        # 咸（咸池・澤山咸）は日本語の漢字なので除外（check_scripts 側の誤検出）
        allow = {"咸"}
        for yao in self.CASES:
            with self.subTest(yao=yao):
                try:
                    r = self._paipan(yao)
                except Exception as e:               # pragma: no cover
                    self.skipTest(f"計算できません: {e}")
                txt = json.dumps(r, ensure_ascii=False)
                bad = sorted({c for c in txt if c in simp and c not in allow})
                self.assertEqual(bad, [], f"簡体字が残っています: {''.join(bad)}")

    def test_fields_are_normalized(self):
        # mts5.50: 六神は起卦日の日干で決まる（甲・乙＝青龍、丙・丁＝朱雀…）。
        # 日時を固定しないと実行日で結果が変わるため、起卦時刻を明示する。
        when = datetime(2026, 9, 29, 12, 0, tzinfo=timezone(timedelta(hours=9)))  # 丙の日
        try:
            r = self._paipan([6, 7, 8, 7, 8, 9], when=when)
        except Exception as e:                       # pragma: no cover
            self.skipTest(f"計算できません: {e}")
        self.assertEqual(r["origin_hexagram"], "未濟")
        self.assertEqual(r["variant_hexagram"], "歸妹")
        self.assertEqual([l["liushen"] for l in r["lines"]][0], "朱雀")
        self.assertIn("駅馬", [s["name"] for s in r["shensha"]])
        self.assertTrue(any("日本語表記" in n for n in r["notes"]))


class TestLiuyaoTimeHandling(unittest.TestCase):
    """六爻の起卦時刻（mts5.50）: 日干で六神が決まる／既定はJST"""

    JST = timezone(timedelta(hours=9))

    @classmethod
    def setUpClass(cls):
        try:
            from fortunelib.calc import liuyao as liuyao_mod
        except Exception as e:                       # pragma: no cover
            raise unittest.SkipTest(f"六爻の計算を読み込めません: {e}")
        cls._mod = liuyao_mod
        cls._paipan = staticmethod(liuyao_mod.liuyao_paipan)

    def test_liushen_follows_the_day_stem(self):
        """起卦日の日干で初爻の六神が決まる（日本語表記へ正規化されている）"""
        # 日干: 甲/乙→青龍、丙/丁→朱雀、戊→勾陳、己→騰蛇、庚/辛→白虎、壬/癸→玄武
        cases = [("2026-09-27", "青龍"),   # 甲
                 ("2026-09-28", "青龍"),   # 乙
                 ("2026-09-29", "朱雀"),   # 丙
                 ("2026-09-30", "朱雀"),   # 丁
                 ("2026-10-01", "勾陳"),   # 戊
                 ("2026-10-02", "騰蛇"),   # 己
                 ("2026-10-03", "白虎"),   # 庚
                 ("2026-10-05", "玄武")]   # 壬
        for day, want in cases:
            with self.subTest(day=day):
                when = datetime.fromisoformat(f"{day}T12:00:00").replace(tzinfo=self.JST)
                r = self._paipan([6, 7, 8, 7, 8, 9], when=when)
                self.assertEqual(r["lines"][0]["liushen"], want)
                # 卦そのもの（爻の並び）は日付に依存しない
                self.assertEqual(r["origin_hexagram"], "未濟")
                self.assertEqual(r["variant_hexagram"], "歸妹")

    def test_default_time_is_jst(self):
        """`when` 省略時はJSTの現在時刻を使う（Kaggle＝UTC の影響を受けない）"""
        import unittest.mock as mock

        class _FakeDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                # 2026-09-29 00:30 JST（＝2026-09-28 15:30 UTC）
                if tz is None:
                    return datetime(2026, 9, 28, 15, 30)          # naive＝UTC相当
                return datetime(2026, 9, 29, 0, 30, tzinfo=tz)    # aware＝JST

        with mock.patch.object(self._mod, "datetime", _FakeDateTime):
            r = self._paipan([6, 7, 8, 7, 8, 9])
        # UTC（9/28＝乙）なら青龍、JST（9/29＝丙）なので朱雀
        self.assertEqual(r["lines"][0]["liushen"], "朱雀")


class TestHexagramMapAcceptsBothForms(unittest.TestCase):
    """易の64卦名は簡体字でも伝統字形でも画像に解決する"""

    def test_all_keys_resolve_after_conversion(self):
        from fortunelib.html_report import _LIUYAO_HEXAGRAM_MAP as M
        simp = _load_simplified_list()
        for key, val in list(M.items()):
            if key in simp or any(c in simp for c in key):
                with self.subTest(key=key):
                    # 旧形式（簡体字）と新形式（変換後）の両方が引ける
                    self.assertIn(text_ja.to_ja_text(key), M)
                    self.assertEqual(M[text_ja.to_ja_text(key)], val)

    def test_full_names_are_untouched(self):
        """キャプション用の正式名（水火既濟 等）は変換対象外＝そのまま"""
        from fortunelib.html_report import _LIUYAO_HEXAGRAM_MAP as M
        for _k, (_no, ja) in M.items():
            self.assertEqual(text_ja.to_ja_text(ja), ja, ja)


if __name__ == "__main__":                            # pragma: no cover
    unittest.main()
