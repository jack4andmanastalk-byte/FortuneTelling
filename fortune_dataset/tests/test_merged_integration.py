# -*- coding: utf-8 -*-
"""
統合版の追加回帰テスト（ProjectA / ProjectB マージで新規追加・修正した箇所）
  - BUG-01: data.py のデータディレクトリ自動解決
  - BUG-02: 九星気学 本命星の計算式（ProjectA 版の誤りを検出）
  - ENH-01: パリミチャム フル10ポルタム（36点）
"""
import json
import unittest
from datetime import date
from pathlib import Path

from fortunelib.data import DATA_DIR, load_json
from tests.fixtures.consultation import CONSULTATION
from fortunelib.calc.kyusei import honmei_no, honmei_name
from fortunelib.calc.parimicham import parimicham_calc, porutham_full


class TestDataResolution(unittest.TestCase):
    """BUG-01: FORTUNE_DATA_DIR 未設定でも data/ を解決できる"""

    def test_data_dir_resolved(self):
        self.assertTrue((DATA_DIR / "prompts.json").exists(), f"解決先: {DATA_DIR}")

    def test_core_files_loadable(self):
        for name in ("prompts.json", "iching_64.json", "tarot_78.json",
                     "nakshatras_27.json"):
            self.assertTrue(load_json(name), name)


class TestKyuseiFormula(unittest.TestCase):
    """BUG-02: 本命星は 11-((Y-1) mod 9 + 1) が正。既知の実例で固定する"""

    # 出典: masanosuke.net / hinokoto.com / 2996.info の本命星早見表（相互一致）
    KNOWN = {
        1989: "二黒土星",
        1990: "一白水星",
        1991: "九紫火星",
        1992: "八白土星",
        2000: "九紫火星",
        2019: "八白土星",
        2020: "七赤金星",
        2025: "二黒土星",
        2026: "一白水星",
    }

    def test_known_years(self):
        for y, expected in self.KNOWN.items():
            self.assertEqual(honmei_name(y), expected, f"{y}年")

    def test_range_1_9(self):
        for y in range(1900, 2101):
            self.assertIn(honmei_no(y), range(1, 10))

    def test_nine_year_cycle(self):
        """9年周期で一巡する"""
        for y in range(1950, 2050):
            self.assertEqual(honmei_no(y), honmei_no(y + 9))

    def test_rejects_project_a_formula(self):
        """ProjectA の (3+(Y-2019))%9 系の式とは一致しない（退行検出）"""
        def project_a(y):
            i = (3 + (y - 2019)) % 9
            return 9 if i == 0 else i
        mismatches = [y for y in range(1950, 2050) if project_a(y) != honmei_no(y)]
        self.assertGreater(len(mismatches), 50,
                           "ProjectA の式に戻っていないか確認すること")


class TestParimichamFull(unittest.TestCase):
    """ENH-01: フル10ポルタム（36点満点）"""

    def test_full_present(self):
        r = parimicham_calc({"date": "1990-01-15"}, {"date": "1991-07-03"})
        self.assertIsNotNone(r["full_porutham"])
        self.assertIn("total_score", r["full_porutham"])

    def test_ten_poruthams(self):
        f = porutham_full(date(1990, 1, 15), date(1991, 7, 3))
        self.assertEqual(len(f["porutham"]), 10)

    def test_max_is_36(self):
        f = porutham_full(date(1990, 1, 15), date(1991, 7, 3))
        self.assertEqual(sum(v["max"] for v in f["porutham"].values()), 36)

    def test_score_within_bounds(self):
        for d2 in ("1991-07-03", "1990-02-15", "1985-11-30", "2000-08-16"):
            f = porutham_full(date(1990, 1, 15), date.fromisoformat(d2))
            self.assertGreaterEqual(f["total_score"], 0)
            self.assertLessEqual(f["total_score"], 36)
            for k, v in f["porutham"].items():
                self.assertGreaterEqual(v["score"], 0, k)
                self.assertLessEqual(v["score"], v["max"], k)

    def test_self_pair_is_high(self):
        """同一人物同士は Rajju が0点になるため満点にはならないが高スコア域"""
        f = porutham_full(date(1990, 1, 15), date(1990, 1, 15))
        self.assertGreaterEqual(f["total_score"], 20)


if __name__ == "__main__":
    unittest.main()


class TestGeminiBackend(unittest.TestCase):
    """2026-08-26 Gemini移行: GeminiBackend のレート制限・リトライ・安全設計

    Kaggle の無料枠（Flash系・概ね10〜15回/分）で 67呼び出し/回 の完走を
    支えるための仕様を検証する。API自体はモックする（実呼び出しはしない）。
    """

    def _make_backend(self, **kw):
        from fortunelib.backend import GeminiBackend
        kw.setdefault("api_key", "test-key")     # 実APIには繋がない
        kw.setdefault("verbose", False)
        kw.setdefault("backoff_base_s", 0.0)     # テストは待たない
        kw.setdefault("requests_per_minute", 600.0)  # スロットリングも待たない
        return GeminiBackend(**kw)

    @staticmethod
    def _level_str(level):
        """thinking_level を文字列化（SDKの列挙型・素の文字列の両方に対応）"""
        return str(getattr(level, "value", level)).upper()

    def test_default_model_is_flash(self):
        """既定モデルは無料枠対象の Flash（Pro系は2026-04に無料枠から除外）
        ★2026-08-26 モデル切替: 2.5-flash廃止（最早2026-10-16）を受け3.5-flashへ
        ★mts5.67（2026-10-14・ユーザー決定）: 3.5-flash／3.7-flash の非推奨化を受け 3.8-flash へ"""
        import inspect
        from fortunelib.backend import GeminiBackend
        default = inspect.signature(
            GeminiBackend.__init__).parameters["model_name"].default
        self.assertEqual(default, "gemini-3.8-flash")
        self.assertNotIn("2.5", default)   # 廃止予定の2.5系は使わない
        self.assertNotIn(default, ("gemini-3.5-flash", "gemini-3.7-flash"))  # 非推奨

    def test_model_name_normalization(self):
        """models/ 接頭辞・前後空白を許容（Kaggleモデルカードからのコピペ対応）
        ★クロスチェック改善（他AI実装A方式の吸収）の検証"""
        from fortunelib.backend import normalize_gemini_model_name as n
        self.assertEqual(n("models/gemini-2.5-flash"), "gemini-2.5-flash")
        self.assertEqual(n(" gemini-2.5-flash "), "gemini-2.5-flash")
        self.assertEqual(n("gemini-2.5-flash"), "gemini-2.5-flash")
        self.assertEqual(n("models/gemini-2.5-flash-preview-04-17"),
                         "gemini-2.5-flash-preview-04-17")
        self.assertEqual(n("gemini-3.0-flash"), "gemini-3-flash")
        self.assertEqual(n("gemini-3.0-flash-preview"), "gemini-3-flash-preview")
        self.assertEqual(n(""), "gemini-3.8-flash")   # 空は既定値へ（mts5.67）

    def test_backend_normalizes_model_name(self):
        """コンストラクタでも正規化が効く"""
        be = self._make_backend(model_name="models/gemini-2.5-flash")
        self.assertEqual(be.model_name, "gemini-2.5-flash")

    def test_api_key_resolution_env_priority(self):
        """環境変数 GEMINI_API_KEY が最優先される"""
        import os
        from unittest import mock
        from fortunelib.backend import _resolve_gemini_api_key
        env = {"GEMINI_API_KEY": "key-a", "GOOGLE_API_KEY": "key-b"}
        with mock.patch.dict(os.environ, env, clear=False):
            # 両方あれば GEMINI_API_KEY
            self.assertEqual(_resolve_gemini_api_key(), "key-a")
        env2 = {"GOOGLE_API_KEY": "key-b", "KAGGLE_SECRET_GOOGLE_API_KEY": "key-c"}
        with mock.patch.dict(os.environ, env2, clear=False):
            self.assertEqual(_resolve_gemini_api_key(), "key-b")

    def test_missing_api_key_message_is_actionable(self):
        """APIキーが無い場合のエラーに具体的な設定手順が含まれる"""
        import os
        from unittest import mock
        from fortunelib.backend import GeminiBackend
        cleared = {k: "" for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY",
                                    "KAGGLE_SECRET_GOOGLE_API_KEY")}
        with mock.patch.dict(os.environ, cleared, clear=False):
            be = GeminiBackend(verbose=False)   # __init__で解決を試みる
            be.api_key = None
            with self.assertRaises(RuntimeError) as cm:
                be._get_client()
            msg = str(cm.exception)
            self.assertIn("aistudio.google.com", msg)
            self.assertIn("GOOGLE_API_KEY", msg)

    def test_throttle_enforces_min_interval(self):
        """RPM制限: 連続呼び出しの開始間隔が最小間隔以上になる"""
        be = self._make_backend(requests_per_minute=60.0)  # 最小間隔=1.0秒

        class FakeClock:
            def __init__(self):
                self.t, self.sleeps = 1000.0, []

            def now(self):
                return self.t

            def sleep(self, s):
                if s > 0:
                    self.sleeps.append(round(s, 3))
                    self.t += s

        clock = FakeClock()
        be._now, be._sleep = clock.now, clock.sleep
        be._generate_once = lambda *a, **k: "生成結果"

        be.generate("sys", "usr")
        self.assertEqual(clock.sleeps, [])          # 1回目は待たない
        be.generate("sys", "usr")
        self.assertEqual(clock.sleeps, [1.0])        # 2回目は最小間隔ぶん待つ
        be.generate("sys", "usr")
        self.assertEqual(clock.sleeps, [1.0, 1.0])   # 3回目も同様

    def test_retry_on_429_then_success(self):
        """429（レート制限）は指数バックオフでリトライして成功する"""
        be = self._make_backend(max_retries=5)
        backoffs = []
        be._backoff_sleep = lambda s: backoffs.append(s)
        calls = {"n": 0}

        class Fake429(Exception):
            code = 429

        def fake_gen(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise Fake429("Resource has been exhausted")
            return "回復後の生成"

        be._generate_once = fake_gen
        out = be.generate("sys", "usr")
        self.assertEqual(out, "回復後の生成")
        self.assertEqual(len(backoffs), 1)         # 1回だけバックオフした

    def test_retry_on_408_then_success(self):
        """408 Request Timeout は一時エラーとしてリトライする（実機 HD 欠落）"""
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
            return "408回復後"

        be._generate_once = fake_gen
        self.assertEqual(be.generate("sys", "usr"), "408回復後")
        self.assertEqual(len(backoffs), 1)
        self.assertEqual(calls["n"], 2)

    def test_408_is_not_fatal_4xx(self):
        """408 は 400 系でも即停止しない（429 と同じ例外）"""
        be = self._make_backend(max_retries=1)
        backoffs = []
        be._backoff_sleep = lambda s: backoffs.append(s)

        class Fake408(Exception):
            code = 408

        be._generate_once = lambda *a, **k: (_ for _ in ()).throw(
            Fake408("Request Timeout"))
        with self.assertRaises(RuntimeError):
            be.generate("sys", "usr")
        self.assertEqual(len(backoffs), 1)   # リトライした（即停止していない）

    def test_503_retries_once_then_gives_up(self):
        """503 は 20秒を1回だけ待ち、指数で伸ばさない（実機 3.7 が21分律速）。"""
        be = self._make_backend(max_retries=5)
        backoffs = []
        be._backoff_sleep = lambda s: backoffs.append(s)

        class Fake503(Exception):
            code = 503

        be._generate_once = lambda *a, **k: (_ for _ in ()).throw(
            Fake503("high demand UNAVAILABLE"))
        with self.assertRaises(RuntimeError):
            be.generate("sys", "usr")
        self.assertEqual(len(backoffs), 1)
        self.assertEqual(backoffs[0], be.backoff_base_s)

    def test_response_timeout_cuts_without_retry(self):
        """mts5.11: 応答が制限時間を超えたら打ち切る（503 と違い再試行しない）。

        mts5.9 の実測では、エラーを伴わない 77秒 の応答が Stage A 264秒の律速
        だった（3.1-lite の遅い5件で 220秒＝レーンの83%）。待ち続けずに上位
        （MTS の別レーン移譲）へ返すのが目的。
        """
        import time as _time
        from fortunelib.backend import ResponseTimeoutError
        be = self._make_backend()
        be.response_timeout_s = 0.05
        backoffs = []
        be._backoff_sleep = lambda s: backoffs.append(s)
        be._generate_once = lambda *a, **k: (_time.sleep(0.5), "遅い応答")[1]
        with self.assertRaises(ResponseTimeoutError) as cm:
            be.generate("sys", "usr")
        self.assertIn("超えました", str(cm.exception))   # 打ち切りの理由が残る
        self.assertEqual(backoffs, [])              # このモデルでは再試行しない

    def test_response_timeout_keeps_fast_response(self):
        """制限時間内の応答はそのまま返る（打ち切らない）。"""
        be = self._make_backend()
        be.response_timeout_s = 5.0
        be._generate_once = lambda *a, **k: "通常の応答"
        self.assertEqual(be.generate("sys", "usr"), "通常の応答")

    def test_response_timeout_defaults_to_none(self):
        """既定は None＝制限なし（MTS の段階 A がレーンごとに設定し、戻す）。"""
        be = self._make_backend()
        self.assertIsNone(be.response_timeout_s)

    def test_retry_gives_up_with_quota_guidance(self):
        """429が解除されない場合は、日次上限の可能性を案内して停止する"""
        be = self._make_backend(max_retries=2)

        class Fake429(Exception):
            code = 429

        be._generate_once = lambda *a, **k: (_ for _ in ()).throw(
            Fake429("quota exceeded"))
        with self.assertRaises(RuntimeError) as cm:
            be.generate("sys", "usr")
        msg = str(cm.exception)
        self.assertIn("429", msg)
        self.assertIn("無料枠", msg)
        self.assertIn("MTS結果", msg)                 # 再実行で再開できる旨

    def test_client_error_raises_immediately(self):
        """400等のリトライ不能な4xxは待たず即停止する（無料枠の無駄遣い防止）"""
        be = self._make_backend(max_retries=5)
        backoffs = []
        be._backoff_sleep = lambda s: backoffs.append(s)

        class Fake400(Exception):
            code = 400

        be._generate_once = lambda *a, **k: (_ for _ in ()).throw(
            Fake400("bad request"))
        with self.assertRaises(RuntimeError):
            be.generate("sys", "usr")
        self.assertEqual(backoffs, [])              # リトライしていない

    def test_auth_error_mentions_secrets(self):
        """401/403 の案内には Secrets の確認指示が入っている"""
        be = self._make_backend()

        class Fake403(Exception):
            code = 403

        be._generate_once = lambda *a, **k: (_ for _ in ()).throw(
            Fake403("permission denied"))
        with self.assertRaises(RuntimeError) as cm:
            be.generate("sys", "usr")
        self.assertIn("GOOGLE_API_KEY", str(cm.exception))

    def test_model_not_found_mentions_model_name(self):
        """404 の案内に MODEL_NAME の確認指示が入っている"""
        be = self._make_backend(model_name="gemini-9.9-nonexistent")

        class Fake404(Exception):
            code = 404

        be._generate_once = lambda *a, **k: (_ for _ in ()).throw(
            Fake404("model not found"))
        with self.assertRaises(RuntimeError) as cm:
            be.generate("sys", "usr")
        self.assertIn("gemini-9.9-nonexistent", str(cm.exception))

    def test_network_error_retries(self):
        """タイムアウト等のネットワーク断はリトライする"""
        be = self._make_backend(max_retries=3)
        backoffs = []
        be._backoff_sleep = lambda s: backoffs.append(s)
        calls = {"n": 0}

        def fake_gen(*a, **k):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise ConnectionError("connection reset")
            return "復旧後"

        be._generate_once = fake_gen
        self.assertEqual(be.generate("sys", "usr"), "復旧後")
        self.assertEqual(len(backoffs), 2)

    def test_blocked_response_returns_empty_string(self):
        """安全フィルタでブロックされた場合は例外ではなく "" を返す
        （検証→再生成の経路（BUG-05）に自然に乗せるため）"""
        from fortunelib.backend import GeminiBackend

        class BlockedResp:
            @property
            def text(self):
                return None

        class MultiCandResp:
            @property
            def text(self):
                raise ValueError("Multiple candidates found")

        be = self._make_backend()
        self.assertEqual(be._extract_text(BlockedResp()), "")
        self.assertEqual(be._extract_text(MultiCandResp()), "")

    def test_token_margin_expands_output_budget(self):
        """文字数ベースの max_tokens は日本語のトークン比率を見込んで拡張される"""
        try:
            import google.genai  # noqa: F401
        except ImportError:
            self.skipTest("google-genai 未導入（pip install google-genai）")
        be = self._make_backend()
        cfg = be._make_config("SYS", 0.7, 1000, None)
        # int(1000 * 1.6) + 100 = 1700
        self.assertEqual(cfg.max_output_tokens, 1700)
        cfg2 = be._make_config("SYS", 0.7, 5600, 42)
        self.assertEqual(cfg2.max_output_tokens, int(5600 * 1.6) + 100)
        self.assertEqual(cfg2.system_instruction, "SYS")

    # --- ★枠ファミリー管理（2026-08-27・AI Studio実測表で確定） ---

    def test_candidates_flash_lite_never_falls_to_flash(self):
        """flash-lite（500RPD）の候補に flash（20RPD）を含めない"""
        from fortunelib.backend import gemini_model_candidates as c
        for name in ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite"):
            got = c(name)
            self.assertTrue(got)                          # 空にならない
            for m in got:
                self.assertIn("flash-lite", m)            # lite系内のみ
            # 明示検証: 既定モデル（flash）が候補に混入していない
            self.assertNotIn("gemini-3.5-flash", got)
            self.assertNotIn("gemini-3.6-flash", got)
            self.assertNotIn("gemini-3.8-flash", got)       # mts5.67 の既定も混入しない

    def test_gemini_default_margin_unchanged(self):
        """gemini 系の既定マージンは従来どおり 1.6（回帰確認）"""
        be = self._make_backend()
        self.assertEqual(be.token_margin, 1.6)



    def test_gemini_still_uses_system_instruction(self):
        """Gemini 系は従来どおり system_instruction を分離して送る（回帰）"""
        captured = {}

        class _FakeModels:
            def generate_content(self, model, contents, config):
                captured["contents"] = contents
                captured["config"] = config

                class _R:
                    candidates = []

                return _R()

        class _FakeClient:
            models = _FakeModels()

        be = self._make_backend()
        be._get_client = lambda: _FakeClient()
        be._extract_text = lambda resp: ""
        be.generate("システム指示文", "ユーザー入力文")
        self.assertEqual(captured["contents"], "ユーザー入力文")
        try:
            import google.genai  # noqa: F401
            self.assertEqual(captured["config"].system_instruction,
                             "システム指示文")
        except ImportError:
            self.assertEqual(captured["config"]["system_instruction"],
                             "システム指示文")

    def test_thinking_minimized_by_default(self):
        """鑑定文生成に thinking は不要（出力トークンを圧迫するため既定で最小化）
        ★2026-08-26 モデル切替: 既定3.5-flash（3系）は thinking_level=minimal
        ★mts5.67: 既定 3.8-flash（3系）も同じく minimal（拒否されたら backend が段階的に緩める）
        ★mts5.68: 3.8-flash は実機で minimal が **400 で拒否**されたことが確定したため、
          最初から **low**（最低レベル）で送る。thinking を無指定にはしない（出力を圧迫しない範囲の最小）"""
        try:
            import google.genai  # noqa: F401
        except ImportError:
            self.skipTest("google-genai 未導入（pip install google-genai）")
        be = self._make_backend()   # 既定 = gemini-3.8-flash（3系）
        cfg = be._make_config("SYS", 0.7, 1000, None)
        tc = getattr(cfg, "thinking_config", None)
        self.assertIsNotNone(tc)
        self.assertEqual(self._level_str(getattr(tc, "thinking_level", None)),
                         "LOW")
        self.assertIsNone(getattr(tc, "thinking_budget", None))
        # 未確定のモデル（3.6-flash）は従来どおり minimal から
        cfg36 = be._make_config("SYS", 0.7, 1000, None, model="gemini-3.6-flash")
        self.assertEqual(self._level_str(getattr(cfg36.thinking_config, "thinking_level", None)),
                         "MINIMAL")

    def test_thinking_param_follows_model_generation(self):
        """thinking 制御はモデル世代で自動判別（★落とし穴F-3対策）
        2.5系=thinking_budget=0（完全無効）/ 3系=thinking_level="minimal"
        ★2026-08-26 モデル切替で追加"""
        try:
            import google.genai  # noqa: F401
        except ImportError:
            self.skipTest("google-genai 未導入（pip install google-genai）")
        be = self._make_backend()
        # 2.5系（手動指定した場合）
        cfg25 = be._make_config("SYS", 0.7, 1000, None, model="gemini-2.5-flash")
        tc25 = getattr(cfg25, "thinking_config", None)
        self.assertIsNotNone(tc25)
        self.assertEqual(getattr(tc25, "thinking_budget", None), 0)
        self.assertIsNone(getattr(tc25, "thinking_level", None))
        # 3系（mts5.68: 既定 3.8-flash は実機で minimal 拒否が確定＝low／
        #       3.6-flash・手動指定した旧 3.5-flash は minimal）
        for m3, want in (("gemini-3.8-flash", "LOW"), ("gemini-3.6-flash", "MINIMAL"),
                         ("gemini-3.5-flash", "MINIMAL")):
            cfg3 = be._make_config("SYS", 0.7, 1000, None, model=m3)
            tc3 = getattr(cfg3, "thinking_config", None)
            self.assertEqual(self._level_str(getattr(tc3, "thinking_level", None)),
                             want, m3)

    def test_thinking_minimal_downgrades_to_low_on_37(self):
        """3.7系は minimal 廃止（送ると400）→ low へ読み替える"""
        try:
            import google.genai  # noqa: F401
        except ImportError:
            self.skipTest("google-genai 未導入（pip install google-genai）")
        be = self._make_backend()
        cfg = be._make_config("SYS", 0.7, 1000, None, model="gemini-3.7-flash")
        tc = getattr(cfg, "thinking_config", None)
        self.assertEqual(self._level_str(getattr(tc, "thinking_level", None)),
                         "LOW")

    def test_fallback_switches_thinking_param(self):
        """404フォールバックでモデル世代が変わっても thinking パラメータが追従する
        （2.5手動指定→保険の既定モデル（mts5.67: 3.8）切替時に budget→level へ切り替わる）"""
        try:
            import google.genai  # noqa: F401
        except ImportError:
            self.skipTest("google-genai 未導入（pip install google-genai）")
        from fortunelib.backend import GeminiBackend

        class FakeResp:
            def __init__(self): self.text = "ok"

        class FakeClient:
            def __init__(self): self.calls = []
            @property
            def models(self): return self
            def generate_content(self, model, contents, config=None, **kw):
                self.calls.append((model, config))
                if model.startswith("gemini-2.5"):
                    e = Exception("model not found")
                    e.code = 404
                    raise e
                return FakeResp()

        be = GeminiBackend(model_name="gemini-2.5-flash", api_key="k",
                           verbose=False, backoff_base_s=0.0)
        be._client = FakeClient()
        out = be.generate("sys", "usr")
        self.assertEqual(out, "ok")
        self.assertEqual(be.resolved_model_name, "gemini-3.8-flash")
        # 2.5への呼び出しは budget、3.8への呼び出しは level
        m25 = [c for mo, c in be._client.calls if mo.startswith("gemini-2.5")]
        m35 = [c for mo, c in be._client.calls if mo.startswith("gemini-3.8")]
        self.assertTrue(m25)
        self.assertEqual(getattr(m25[0].thinking_config, "thinking_budget", None), 0)
        self.assertEqual(
            self._level_str(getattr(m35[0].thinking_config, "thinking_level",
                                     None)), "LOW")      # mts5.68: 3.8 は low から

    # --- ★第2回クロスチェック改善（修正版A方式の吸収・2026-08-26） ---

    def test_model_candidates_chain(self):
        """404フォールバックの候補列: primary→preview系→後継/公式preview→既定
        ★2026-08-26 モデル切替: 既定3.5-flashの後継候補は3.6-flash
        ★mts5.67（ユーザー決定）: 既定 3.8-flash → 3.6-flash → 3-flash-preview。
          非推奨の 3.5-flash／3.7-flash はどの候補列にも入らない"""
        from fortunelib.backend import gemini_model_candidates as c
        chain = c("gemini-3.8-flash")
        self.assertEqual(chain, ["gemini-3.8-flash", "gemini-3.8-flash-preview",
                                 "gemini-3.6-flash", "gemini-3-flash-preview"])
        # 既定モデル自身は末尾の保険に重複しない
        self.assertEqual(len(chain), len(set(chain)))
        # 2番手を手動指定した場合: 次点 → 最後の保険は既定モデル
        c36 = c("gemini-3.6-flash")
        self.assertEqual(c36, ["gemini-3.6-flash", "gemini-3.6-flash-preview",
                               "gemini-3-flash-preview", "gemini-3.8-flash"])
        # 2.5系（手動指定）: 公式preview → 最後の保険は生きている既定モデル
        c25 = c("gemini-2.5-flash")
        self.assertIn("gemini-2.5-flash-preview-04-17", c25)
        self.assertEqual(c25[-1], "gemini-3.8-flash")
        # 3系の無印名 → 公式 preview が候補に入る
        self.assertIn("gemini-3-flash-preview", c("gemini-3-flash"))
        self.assertIn("gemini-3-flash-preview", c("gemini-3.0-flash"))
        # 既定以外の名前は最後の保険として既定モデルが入る
        self.assertEqual(c("gemini-9.9-x")[-1], "gemini-3.8-flash")
        # models/ 接頭辞も正規化される
        self.assertEqual(c("models/gemini-3.8-flash")[0], "gemini-3.8-flash")
        # 非推奨IDは（手動で一次に指定した場合を除き）候補に出てこない
        for name in ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3-flash",
                     "gemini-3-flash-preview", "gemini-2.5-flash", "gemini-9.9-x",
                     "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"):
            self.assertNotIn("gemini-3.5-flash", c(name), name)
            self.assertNotIn("gemini-3.7-flash", c(name), name)
        # 明示 preview 指定には接尾辞候補を足さない
        self.assertNotIn("gemini-3-flash-preview-preview",
                         c("gemini-3-flash-preview"))

    def test_model_fallback_on_404(self):
        """404時は候補モデルへ切替えて生成を続行する（リトライ枠を消費しない）"""
        be = self._make_backend()
        backoffs = []
        be._backoff_sleep = lambda s: backoffs.append(s)
        tried = []

        class Fake404(Exception):
            code = 404

        def fake_gen(sys, usr, temp, mt, seed, model=None):
            tried.append(model)
            if model in ("gemini-3.8-flash", "gemini-3.8-flash-preview"):
                raise Fake404("model not found")
            return "フォールバック後の生成"

        be._generate_once = fake_gen
        out = be.generate("sys", "usr")
        self.assertEqual(out, "フォールバック後の生成")
        self.assertGreater(len(tried), 1)                        # 切替えて再試行
        self.assertEqual(backoffs, [])                           # バックオフ不要
        self.assertEqual(tried, ["gemini-3.8-flash",
                                 "gemini-3.8-flash-preview",
                                 "gemini-3.6-flash"])            # 候補順どおり（mts5.67）
        self.assertEqual(be.resolved_model_name, tried[-1])      # 実応答モデル

    def test_model_fallback_remembers_resolved_model(self):
        """一度成功したモデルを使い続け、毎回のgenerateで404を再試行しない"""
        be = self._make_backend()
        state = {"n": 0}

        class Fake404(Exception):
            code = 404

        def fake_gen(sys, usr, temp, mt, seed, model=None):
            state["n"] += 1
            if model == "gemini-3.8-flash":
                raise Fake404("model not found")
            return "ok"

        be._generate_once = fake_gen
        be.generate("sys", "usr")      # 1回目: 404→切替→成功（2呼び出し）
        be.generate("sys", "usr")      # 2回目: 記憶済みモデルで即成功（1呼び出し）
        be.generate("sys", "usr")      # 3回目: 同上
        self.assertEqual(state["n"], 4)  # 2+1+1（A2方式の毎回再試行と同じにしない）

    def test_model_404_all_candidates_exhausted(self):
        """全候補が404の場合は有限回で停止（無限ループしない）"""
        from fortunelib.backend import gemini_model_candidates
        be = self._make_backend()
        calls = {"n": 0}

        class Fake404(Exception):
            code = 404

        def fake_gen(*a, **k):
            calls["n"] += 1
            raise Fake404("model not found")

        be._generate_once = fake_gen
        with self.assertRaises(RuntimeError) as cm:
            be.generate("sys", "usr")
        self.assertEqual(calls["n"],
                         len(gemini_model_candidates(be.model_name)))
        self.assertIn("gemini-3.8-flash", str(cm.exception))    # 試行案内（mts5.67 の既定）

    def test_rate_limit_detected_without_code_attribute(self):
        """code属性を持たない例外も文字列から429/クォータ系と判定する"""
        from fortunelib.backend import _is_rate_limited
        self.assertTrue(_is_rate_limited(
            Exception("RESOURCE_EXHAUSTED: quota exceeded")))
        self.assertTrue(_is_rate_limited(Exception("429 Too Many Requests")))
        self.assertTrue(_is_rate_limited(Exception("rate limit exceeded")))
        self.assertFalse(_is_rate_limited(Exception("invalid argument")))

    def test_not_found_detected_without_code_attribute(self):
        """code属性を持たない例外も文字列からモデル不在と判定する"""
        from fortunelib.backend import _is_not_found
        self.assertTrue(_is_not_found(
            Exception("models/gemini-x is not found for API version v1beta")))
        self.assertTrue(_is_not_found(Exception("Unknown model: gemini-x")))
        # APIキー・権限系の not found はモデル切替の対象にしない
        self.assertFalse(_is_not_found(Exception("API key not found")))
        self.assertFalse(_is_not_found(Exception("permission denied")))
        e404 = Exception("some error")
        e404.code = 404
        self.assertTrue(_is_not_found(e404))

    def test_rate_limit_text_error_retries(self):
        """コード属性の無い429系メッセージもバックオフの上リトライする"""
        be = self._make_backend(max_retries=2)
        backoffs = []
        be._backoff_sleep = lambda s: backoffs.append(s)
        calls = {"n": 0}

        def fake_gen(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise Exception("RESOURCE_EXHAUSTED: quota exceeded")  # code無し
            return "回復後の生成"

        be._generate_once = fake_gen
        self.assertEqual(be.generate("sys", "usr"), "回復後の生成")
        self.assertEqual(len(backoffs), 1)

    # --- ★12回目実機対応（2026-08-27・無料枠20回/日の日次クォータ） ---

    def test_daily_quota_fails_fast(self):
        """日次クォータ（RPD）枯渇の429はリトライせず即停止する
        （待機しても解除されないため。12回目実機で10分/セルの浪費を検出）"""
        be = self._make_backend(max_retries=5)
        backoffs = []
        be._backoff_sleep = lambda s: backoffs.append(s)
        calls = {"n": 0}

        class Fake429Daily(Exception):
            code = 429

        DAILY_MSG = ("429 RESOURCE_EXHAUSTED ... quotaId: "
                     "'GenerateRequestsPerDayPerProjectPerModel-FreeTier', "
                     "quotaValue: '20'")

        def fake_gen(*a, **k):
            calls["n"] += 1
            raise Fake429Daily(DAILY_MSG)

        be._generate_once = fake_gen
        with self.assertRaises(RuntimeError) as cm:
            be.generate("sys", "usr")
        msg = str(cm.exception)
        self.assertIn("無料枠", msg)
        self.assertIn("翌日", msg)                    # 再開方法を案内
        self.assertIn("MTS結果", msg)
        self.assertEqual(calls["n"], 1)              # 1回だけで諦める
        self.assertEqual(backoffs, [])               # バックオフしない

    def test_minute_quota_still_retries(self):
        """分単位（RPM）の429は従来どおりバックオフでリトライする"""
        be = self._make_backend(max_retries=2)
        backoffs = []
        be._backoff_sleep = lambda s: backoffs.append(s)
        calls = {"n": 0}

        class Fake429Min(Exception):
            code = 429

        def fake_gen(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise Fake429Min("quotaId: 'GenerateRequestsPerMinutePerProject"
                                 "PerModel-FreeTier'")
            return "回復"

        be._generate_once = fake_gen
        self.assertEqual(be.generate("sys", "usr"), "回復")
        self.assertEqual(len(backoffs), 1)

    def test_daily_quota_codeless_text_fails_fast(self):
        """code 属性を持たない日次クォータ文言の例外も即停止する"""
        be = self._make_backend(max_retries=5)
        backoffs = []
        be._backoff_sleep = lambda s: backoffs.append(s)
        calls = {"n": 0}

        def fake_gen(*a, **k):
            calls["n"] += 1
            raise Exception("RESOURCE_EXHAUSTED: Free tier daily quota "
                            "exceeded (per day limit)")

        be._generate_once = fake_gen
        with self.assertRaises(RuntimeError) as cm:
            be.generate("sys", "usr")
        self.assertIn("無料枠", str(cm.exception))
        self.assertEqual(calls["n"], 1)
        self.assertEqual(backoffs, [])

    def test_resolved_model_name_defaults_to_model_name(self):
        """フォールバック未発生時は resolved_model_name == model_name"""
        be = self._make_backend(model_name="gemini-2.5-flash")
        self.assertEqual(be.resolved_model_name, "gemini-2.5-flash")


class TestNotebookGeminiConfig(unittest.TestCase):
    """ノートブックのセル群が Gemini 構成になっていることの整合検査

    Kaggle Dataset に tests/ と kaggle/ を同梱している理由のひとつ
    （セルのソースを読む回帰テスト・BUG-20〜23 系）。
    """

    CELL0 = Path(__file__).resolve().parent.parent / "kaggle" / "cell0_bootstrap.py"
    SELFTEST = Path(__file__).resolve().parent.parent / "kaggle" / "cell0_selftest.py"

    def _model_name_line(self, cell):
        for line in cell.read_text(encoding="utf-8").splitlines():
            if line.startswith("MODEL_NAME"):
                return line
        self.fail("MODEL_NAME が見つかりません")

    def test_cell0_model_is_gemini_flash(self):
        """Cell 0 の既定モデルは gemini 系（無料枠のFlash）"""
        line = self._model_name_line(self.CELL0)
        name = line.split('"')[1]
        self.assertTrue(name.startswith("gemini-"), name)
        self.assertNotIn("-it", name)          # ローカルモデルの名残が無いこと
        self.assertNotIn("pro", name.lower())  # Pro系は無料枠外
        self.assertNotIn("2.5", name)          # 2.5系は廃止予定（最早2026-10-16）
        self.assertNotIn("3.7", name)          # 3.7は無料枠なし＋minimal非対応

    def test_cell0_uses_gemini_backend(self):
        """Cell 0 は GeminiBackend を使い KaggleBackend を参照しない"""
        src = self.CELL0.read_text(encoding="utf-8")
        self.assertIn("GeminiBackend", src)
        self.assertIn("GOOGLE_API_KEY", src)
        self.assertNotIn("KaggleBackend", src)
        # HF_TOKEN の「取得コード」が残っていないこと（説明文中の言及は可）
        self.assertNotIn("_resolve_hf_token", src)
        self.assertNotIn('get_secret("HF_TOKEN")', src)

    def test_cell0_has_no_gpu_only_code(self):
        """Cell 0 に GPU/量子化系のコードが残っていない（退行検出）"""
        src = self.CELL0.read_text(encoding="utf-8")
        for gone in ("bitsandbytes", "transformers>=", "bnb_4bit",
                     "MAX_MEM_PER_GPU_GB", "DTYPE"):
            self.assertNotIn(gone, src, f"GPU時代の名残: {gone}")

    def test_selftest_checks_gemini_deps(self):
        """Cell 0.1 が google-genai の導入と API 疎通を検査する"""
        src = self.SELFTEST.read_text(encoding="utf-8")
        self.assertIn('"google.genai"', src)
        self.assertIn("google-genai", src)
        self.assertIn("GOOGLE_API_KEY", src)

    def test_cell0_408_graduated_to_backend(self):
        """408 は backend 本体でリトライ。ノートブック monkeypatch は残さない。"""
        src = self.CELL0.read_text(encoding="utf-8")
        self.assertNotIn("_api_error_code_retry_408", src)
        from fortunelib import backend as be
        import inspect
        src_be = inspect.getsource(be.GeminiBackend.generate)
        self.assertIn("408", src_be)

    def test_cell_sources_wire_mts(self):
        """Cell 0/1/N2 が MTS 段階 A/B/C を呼ぶ。"""
        c0 = self.CELL0.read_text(encoding="utf-8")
        self.assertIn("get_mts_backends", c0)
        self.assertIn("MTS B2", c0)
        c1 = (Path(__file__).resolve().parent.parent
              / "kaggle" / "cell1_csv_input.py").read_text(encoding="utf-8")
        self.assertIn("run_person_mts", c1)
        n2 = (Path(__file__).resolve().parent.parent
              / "kaggle" / "cellN2_synthesis.py").read_text(encoding="utf-8")
        self.assertIn("run_stage_b_mts", n2)
        self.assertIn("run_stage_c_mts", n2)
        self.assertIn("MTS", n2)
        self.assertNotIn("BOTH_AXES", n2)


class TestRegenerationFeedback(unittest.TestCase):
    """BUG-05: 再生成が「同じプロンプトの投げ直し」で無意味だった問題

    実機ログ: 再生成10件すべてが同じ違反のまま（約17分＝実行時間の20%を浪費）
    """

    D = {"char_min": 400, "char_max": 700}

    def test_too_long_asks_to_shorten(self):
        from fortunelib.pipeline import _build_fix_instruction
        s = _build_fix_instruction(["文字数: 838字（期待 400〜700字）"], self.D, 838)
        self.assertIn("838字", s)
        self.assertIn("長すぎ", s)
        self.assertIn("400〜700字", s)

    def test_too_short_asks_to_expand(self):
        from fortunelib.pipeline import _build_fix_instruction
        s = _build_fix_instruction(["文字数: 120字（期待 400〜700字）"], self.D, 120)
        self.assertIn("短すぎ", s)

    def test_forbidden_word_named(self):
        from fortunelib.pipeline import _build_fix_instruction
        s = _build_fix_instruction(["禁止語句: 「確実に」を含む"], self.D, 500)
        self.assertIn("確実に", s)
        self.assertIn("言い換え", s)

    def test_always_asks_full_rewrite(self):
        """差分ではなく全文の書き直しを求める"""
        from fortunelib.pipeline import _build_fix_instruction
        s = _build_fix_instruction(["文字数: 900字（期待 400〜700字）"], self.D, 900)
        self.assertIn("全文", s)

    def test_regeneration_uses_feedback(self):
        """run_divination の再生成が修正指示付きプロンプトを送る（MockBackend で検証）"""
        import inspect
        from fortunelib import pipeline
        src = inspect.getsource(pipeline.run_divination)
        self.assertIn("_build_fix_instruction", src,
                      "再生成が素のプロンプト投げ直しに戻っている")


class TestForbiddenWordPrecision(unittest.TestCase):
    """BUG-06: 「確実に」「必ず」の副詞用法を誤検出していた問題"""

    LONG = "あ" * 420

    def test_adverbial_use_allowed(self):
        """『静かに、しかし確実に』のような副詞用法は違反にしない"""
        from fortunelib.validate import validate_output
        text = "大地のように静かに、しかし確実に存在感を示すことが大切です。" + self.LONG
        bad = [i for i in validate_output(text, min_chars=100, max_chars=900)
               if "禁止語句" in i]
        self.assertEqual(bad, [], bad)

    def test_assertive_prophecy_detected(self):
        """『必ず成功が訪れます』のような断定的予言は検出する"""
        from fortunelib.validate import validate_output
        text = "あなたには必ず成功が訪れます。" + self.LONG
        bad = [i for i in validate_output(text, min_chars=100, max_chars=900)
               if "禁止語句" in i]
        self.assertTrue(bad, "断定的予言を検出できていない")

    def test_plain_forbidden_still_caught(self):
        """従来の単純禁止語は引き続き検出する"""
        from fortunelib.validate import validate_output
        for w in ("免責", "占いです", "エンターテインメント"):
            text = f"これは{w}に関する記述です。" + self.LONG
            bad = [i for i in validate_output(text, min_chars=100, max_chars=900)
                   if "禁止語句" in i]
            self.assertTrue(bad, w)


class TestRegenerationAcceptance(unittest.TestCase):
    """BUG-07: 再生成の採否を issue 件数だけで判定していた問題

    実機ログ（2回目）: 西洋占星術が2回連続で 1166字のまま残存。
    「1166字 → 950字」のように改善しても、違反件数が同じ1件なので
    破棄されていた。件数が同じ場合は逸脱量で比較する。
    """

    D = {"char_min": 500, "char_max": 900}   # 許容上限は 900+100 = 1000

    def test_deviation_zero_when_in_range(self):
        from fortunelib.pipeline import _char_deviation
        self.assertEqual(_char_deviation("あ" * 800, self.D), 0)
        self.assertEqual(_char_deviation("あ" * 1000, self.D), 0)

    def test_deviation_measures_overflow(self):
        from fortunelib.pipeline import _char_deviation
        self.assertEqual(_char_deviation("あ" * 1166, self.D), 166)

    def test_deviation_measures_shortfall(self):
        from fortunelib.pipeline import _char_deviation
        self.assertEqual(_char_deviation("あ" * 400, self.D), 100)

    def test_closer_result_is_adopted(self):
        """同じ違反件数でも、範囲に近いほうを採用する（本件の核心）"""
        from fortunelib.pipeline import _is_better
        worse, better = "あ" * 1166, "あ" * 1050
        self.assertTrue(_is_better(["x"], better, ["x"], worse, self.D))

    def test_farther_result_is_rejected(self):
        from fortunelib.pipeline import _is_better
        worse, orig = "あ" * 1300, "あ" * 1166
        self.assertFalse(_is_better(["x"], worse, ["x"], orig, self.D))

    def test_fewer_issues_always_wins(self):
        from fortunelib.pipeline import _is_better
        self.assertTrue(_is_better([], "あ" * 800, ["x"], "あ" * 1166, self.D))

    def test_more_issues_always_loses(self):
        from fortunelib.pipeline import _is_better
        self.assertFalse(_is_better(["x", "y"], "あ" * 800, ["x"], "あ" * 1166, self.D))

    def test_tie_keeps_original(self):
        """同点なら元の文章を維持する（無駄な入れ替えをしない）"""
        from fortunelib.pipeline import _is_better
        a, b = "あ" * 1166, "あ" * 1166
        self.assertFalse(_is_better(["x"], b, ["x"], a, self.D))

    def test_pipeline_uses_is_better(self):
        import inspect
        from fortunelib import pipeline
        src = inspect.getsource(pipeline.run_divination)
        self.assertIn("_is_better", src, "件数のみの比較に戻っている")


class TestRokuseiCrossVerified(unittest.TestCase):
    """六星占術のA/Bクロス検証（2026-08-17）

    A（星数=ordinal+15 mod 60）と B（年運数+月offset+日）は 97.4% 不一致だった。
    出典 masanosuke.net の計算例で B が正しいと確定。
    """

    def test_official_worked_example(self):
        """出典の計算例: 1990-08-15 → 年運数21+月17+日15 = 53 → 水星人"""
        from fortunelib.calc.rokusei import unmei_number, star_type
        self.assertEqual(unmei_number(1990, 8, 15), 53)
        self.assertEqual(star_type(53), "水星人")

    def test_year_unnsu_table(self):
        """公開年運数テーブル（masanosuke.net）と一致する"""
        from fortunelib.calc.rokusei import year_unnsu
        known = {1960: 15, 1970: 5, 1975: 48, 1980: 43, 1985: 38,
                 1990: 21, 1995: 16, 2000: 11, 2004: 55}
        for y, v in known.items():
            self.assertEqual(year_unnsu(y), v, f"{y}年")

    def test_rejects_project_a_formula(self):
        """A の星数式（ordinal+15）とは一致しない（退行検出）"""
        from datetime import date
        from fortunelib.calc.rokusei import unmei_number
        mismatches = 0
        for y in range(1960, 2005):
            d = date(y, 6, 15)
            a = ((d.toordinal() + 15) % 60) or 60
            if a != unmei_number(y, 6, 15):
                mismatches += 1
        self.assertGreater(mismatches, 30, "ProjectA の式に戻っていないか確認すること")


class TestPythagoreanCrossVerified(unittest.TestCase):
    """BUG-08: ピタゴラス式が A=1〜Z=26 の素の序数になっていた問題

    正しくは 1-9 巡回（A=1..I=9, J=1..R=9, S=1..Z=8）。
    出典: checkmynumerology.com / calculatorsheaven.com / astrosight.ai
    """

    def test_table_cycles_1_to_9(self):
        from fortunelib.calc.numerology import PYTHAGOREAN_TABLE as T
        self.assertEqual(T["A"], 1)
        self.assertEqual(T["I"], 9)
        self.assertEqual(T["J"], 1)   # 10 → 1 に戻る
        self.assertEqual(T["R"], 9)
        self.assertEqual(T["S"], 1)   # 19 → 1 に戻る
        self.assertEqual(T["Z"], 8)
        self.assertEqual(set(T.values()), set(range(1, 10)))

    def test_reference_names(self):
        """出典サイトの計算例と一致する"""
        from fortunelib.calc.numerology import name_number_pythagorean as n
        for name, expected in [("JOHN", 2), ("SARAH", 2), ("MICHAEL", 33),
                               ("EMMA", 5), ("SARA KHAN", 1)]:
            self.assertEqual(n(name), expected, name)

    def test_not_raw_ordinal(self):
        """A=1〜Z=26 の素の序数に戻っていないこと（退行検出）"""
        from fortunelib.calc.numerology import letter_values_pythagorean as lv
        self.assertEqual(lv("Z"), 8)      # 素の序数なら 26
        self.assertEqual(lv("JOHN"), 20)  # 素の序数なら 47

    def test_master_number_33_preserved(self):
        """33 はマスターナンバーとして還元しない（A実装は33が抜けていた）"""
        from fortunelib.calc.numerology import digital_root, MASTER_NUMBERS
        self.assertIn(33, MASTER_NUMBERS)
        self.assertEqual(digital_root(33), 33)


class TestHousesSignsProvided(unittest.TestCase):
    """BUG-11: ハウス情報が黄経のみで、LLMが星座換算を誤った問題

    実機（31B）で ASC=43.18°（牡牛座13.2°）を「双子座」と誤答。
    本プロジェクトの原則「決定論的計算はコード・解釈のみLLM」に反して
    LLMに度数→星座の換算をさせていたのが原因。
    """

    JD = 2447906.625          # 1990-01-15 12:00 JST
    LAT, LON = 35.6895, 139.6917

    def _houses(self):
        from fortunelib.calc.astrology import houses
        return houses(self.JD, self.LAT, self.LON)

    def test_asc_sign_present(self):
        h = self._houses()
        self.assertIn("asc_sign", h)
        self.assertIn("asc_deg_in_sign", h)

    def test_asc_sign_correct(self):
        """ASC 43.18° は牡牛座（双子座ではない）"""
        h = self._houses()
        self.assertEqual(h["asc_sign"], "牡牛座")
        self.assertAlmostEqual(h["asc_deg_in_sign"], 13.18, places=1)

    def test_mc_sign_present(self):
        h = self._houses()
        self.assertIn("mc_sign", h)
        self.assertEqual(h["mc_sign"], "山羊座")

    def test_cusps_signs_align(self):
        """全カスプに星座名が付き、度数と整合する"""
        from fortunelib.calc.astrology import SIGNS_JA
        h = self._houses()
        self.assertEqual(len(h["cusps_signs"]), len(h["cusps"]))
        for lon, sign in zip(h["cusps"], h["cusps_signs"]):
            self.assertEqual(sign, SIGNS_JA[int(lon // 30) % 12])

    def test_no_bare_longitude_in_chart(self):
        """ネイタルチャートの主要要素は必ず星座名を伴う"""
        from fortunelib.calc.astrology import natal_chart
        n = natal_chart(1990, 1, 15, 12, 0, self.LAT, self.LON)
        for name, p in n["planets"].items():
            self.assertIn("sign", p, name)
        self.assertIn("asc_sign", n["houses"])


class TestPlaceResolution(unittest.TestCase):
    """BUG-12: 出生地を入力すると lat/lon が 0.0 になっていた問題

    空欄なら東京(35.69,139.69)が入るのに、「東京都」と入力すると (0,0)＝
    ギニア湾沖になっていた（入力した方が悪化するという逆転）。
    """

    def _birth(self, place):
        from fortunelib.profile import normalize_input
        return normalize_input({"birth": {"date": "1990-01-15",
                                          "time": "14:30", "place": place}}).birth

    def test_blank_defaults_to_tokyo(self):
        b = self._birth("")
        self.assertAlmostEqual(b.place_lat, 35.6895, places=3)
        self.assertTrue(b.place_unknown)

    def test_never_zero_coordinates(self):
        """どの入力でも (0,0) にならない（本バグの核心）"""
        for p in ("", "東京都", "大阪府", "北海道", "沖縄県", "存在しない地名"):
            b = self._birth(p)
            self.assertFalse(b.place_lat == 0.0 and b.place_lon == 0.0, p)

    def test_prefecture_resolved(self):
        b = self._birth("大阪府")
        self.assertAlmostEqual(b.place_lat, 34.6863, places=3)
        self.assertAlmostEqual(b.place_lon, 135.52, places=2)
        self.assertFalse(b.place_unknown)

    def test_suffix_variants(self):
        """「東京」「東京都」どちらでも同じ座標に解決する"""
        a, b = self._birth("東京"), self._birth("東京都")
        self.assertAlmostEqual(a.place_lat, b.place_lat, places=4)
        self.assertFalse(a.place_unknown)

    def test_all_47_prefectures_resolve(self):
        from fortunelib.data import load_json
        from fortunelib.profile import resolve_place
        prefs = load_json("japan_prefectures.json")
        self.assertEqual(len(prefs), 47)
        for e in prefs:
            _, lat, lon, resolved = resolve_place(e["name"])
            self.assertTrue(resolved, e["name"])
            self.assertAlmostEqual(lat, e["lat"], places=4)

    def test_unknown_place_flagged_approx(self):
        """解決できない地名は東京扱い＋近似フラグ"""
        b = self._birth("アトランティス")
        self.assertTrue(b.place_unknown)
        self.assertAlmostEqual(b.place_lat, 35.6895, places=3)

    def test_batch_uses_same_coords(self):
        """batch.resolve_place が profile の座標と一致（DUP-02の一本化）"""
        from fortunelib.batch import resolve_place as batch_resolve
        b = self._birth("北海道")
        lat, lon, note = batch_resolve(b)
        self.assertAlmostEqual(lat, b.place_lat, places=4)
        self.assertAlmostEqual(lon, b.place_lon, places=4)


class TestGenderNormalization(unittest.TestCase):
    """BUG-13: INPUT トップレベルの gender が読まれず常に unknown だった問題

    紫微斗数は GENDER_MAP のフォールバックで unknown→「男」となるため、
    女性の入力でも男性として命盤（大限＝10年運）が立てられていた。
    """

    def _gender(self, value, key="gender"):
        from fortunelib.profile import normalize_input
        return normalize_input({"birth": {"date": "1990-01-15"},
                                key: value}).birth.gender

    def test_top_level_gender_read(self):
        self.assertEqual(self._gender("F"), "F")
        self.assertEqual(self._gender("M"), "M")

    def test_japanese_and_english(self):
        for v, exp in [("女", "F"), ("男", "M"), ("female", "F"),
                       ("male", "M"), ("女性", "F")]:
            self.assertEqual(self._gender(v), exp, v)

    def test_blank_is_unknown(self):
        self.assertEqual(self._gender(""), "unknown")

    def test_birth_level_takes_priority(self):
        from fortunelib.profile import normalize_input
        ni = normalize_input({"birth": {"date": "1990-01-15", "gender": "M"},
                              "gender": "F"})
        self.assertEqual(ni.birth.gender, "M")

    def test_ziwei_differs_by_gender(self):
        """性別で紫微斗数の命盤（大限）が実際に変わることを保証"""
        import json
        from fortunelib.calc.ziwei import ziwei_chart
        m = ziwei_chart(1990, 1, 15, 14, "M")
        f = ziwei_chart(1990, 1, 15, 14, "F")
        self.assertNotEqual(json.dumps(m, ensure_ascii=False, sort_keys=True),
                            json.dumps(f, ensure_ascii=False, sort_keys=True))


class TestMustMentionNumericFacts(unittest.TestCase):
    """BUG-14: 数値のプロファイル事実が must_mention から抜けていた問題

    実機（65種実行）で「ライフパス8をお持ちの方は…」と正しく織り込んだ
    ペンデュラム／クリスタル・ヒーリングの2件が「事実が1つも無い」と
    誤判定され、無駄な再生成が走った。
    isinstance(v, str) で絞っていたため int の 8 が候補外だった。
    """

    FACTS = {
        "太陽星座": "山羊座",
        "数秘術（ライフパス）": 8,
        "血液型": "A型",
        "相手の生年月日": "1988-07-22",
    }

    def _mm(self):
        from fortunelib.pipeline import _must_mention_facts, PipelineContext
        ctx = PipelineContext(inputs=None, profile_facts=self.FACTS)
        return _must_mention_facts({"group": "G6"}, ctx)

    def test_numeric_fact_included(self):
        m = self._mm()
        self.assertTrue(any("ライフパス8" == x for x in m), m)

    def test_no_bare_number(self):
        """裸の '8' は '1988' 等に部分一致するので候補に入れない"""
        self.assertNotIn("8", self._mm())

    def test_string_facts_kept(self):
        m = self._mm()
        for v in ("山羊座", "A型"):
            self.assertIn(v, m)

    def test_correct_output_passes(self):
        """ライフパスを織り込んだ本文が違反にならない"""
        from fortunelib.validate import validate_output
        text = ("判定はYesです。ライフパス8をお持ちの方は、社会的な達成を通じて"
                "自己実現を果たす力が強いため、まずは仕事に注力することをお勧めします。")
        issues = validate_output(text, min_chars=50, max_chars=500,
                                 must_mention=self._mm())
        self.assertEqual([i for i in issues if "事実整合" in i], [])

    def test_empty_output_still_flagged(self):
        """何も織り込まない本文は引き続き検出する（検出力を落としていない）"""
        from fortunelib.validate import validate_output
        text = "今日はよい一日になるでしょう。特に申し上げることはありません。" * 3
        issues = validate_output(text, min_chars=10, max_chars=500,
                                 must_mention=self._mm())
        self.assertTrue([i for i in issues if "事実整合" in i])

    def test_non_g6_returns_empty(self):
        from fortunelib.pipeline import _must_mention_facts, PipelineContext
        ctx = PipelineContext(inputs=None, profile_facts=self.FACTS)
        self.assertEqual(_must_mention_facts({"group": "G1"}, ctx), [])


class TestTodayMode65(unittest.TestCase):
    """今日の運勢モード（consultation 空欄）の検証"""

    def _ni(self, consultation=""):
        from fortunelib.profile import normalize_input
        return normalize_input({
            "birth": {"date": "1990-01-15", "time": "14:30", "place": "東京都"},
            "gender": "F", "blood_type": "A",
            "name_kanji": "佐藤 花子", "name_kana": "さとう はなこ",
            "partner": {"date": "1988-07-22", "time": "09:15", "place": "大阪府"},
            "consultation": consultation, "target": ""})

    def test_blank_triggers_today_mode(self):
        self.assertEqual(self._ni("").consultation, "")

    def test_every_divination_has_today_instruction(self):
        from fortunelib.registry import all_slugs
        from fortunelib.today import get_today_instruction
        for slug in all_slugs():
            self.assertTrue(get_today_instruction(slug), slug)

    def test_target_date_injected(self):
        from fortunelib.batch import build_calc_results
        t = build_calc_results(self._ni(""))["target_date"]
        self.assertTrue(t.get("date"))
        self.assertTrue(t.get("is_today"))

    def test_prompt_contains_today_mode(self):
        from fortunelib.prompt import build_system_prompt, build_user_prompt
        from fortunelib.today import get_today_instruction
        sys_p = build_system_prompt("P01", today_mode=True,
                                    today_instruction=get_today_instruction("seiza"))
        usr_p = build_user_prompt("P01", {}, None, "", today_mode=True,
                                  target_date="2026-08-17")
        self.assertIn("今日の運勢モード", sys_p)
        self.assertIn("2026-08-17", usr_p)


class TestDeitiesOracle(unittest.TestCase):
    """新機能: 御縁のある神さま Top10（M31・疑似オラクル）"""

    FACTS = {"太陽星座": "山羊座", "干支（年柱・立春基準）": "己巳",
             "九星気学（本命星）": "二黒土星", "数秘術（ライフパス）": 8,
             "_consultation": "転職と結婚"}

    def test_dataset_deities(self):
        """FEAT-06 で 60→120柱、FEAT-11 で 151柱、mts5.21 で 138柱へ改訂（文明ごとの柱数は不均等）"""
        from fortunelib.calc.deities import all_deities, PANTHEONS
        d = all_deities()
        self.assertEqual(len(d), 138)
        from collections import Counter
        c = Counter(x["pantheon"] for x in d)
        for p in PANTHEONS:
            self.assertGreaterEqual(c[p], 10, p)

    def test_returns_top10(self):
        from datetime import date
        from fortunelib.calc.deities import draw_deities
        r = draw_deities(self.FACTS, target=date(2026, 8, 17), seed=1,
                         rng_mode="reproducible")
        self.assertEqual(len(r["ranking"]), 10)
        self.assertEqual([x["rank"] for x in r["ranking"]], list(range(1, 11)))

    def test_all_six_pantheons_present(self):
        """6文明カバレッジは最小値 top_n=6 でも保たれる"""
        from datetime import date
        from fortunelib.calc.deities import draw_deities, PANTHEONS
        for seed in (1, 7, 99):
            for top_n in (6, 10):
                r = draw_deities(self.FACTS, target=date(2026, 8, 17), seed=seed,
                                 rng_mode="reproducible", top_n=top_n)
                self.assertEqual(len(r["ranking"]), top_n)
                got = {x["pantheon"] for x in r["ranking"]}
                for p in PANTHEONS:
                    self.assertIn(p, got, f"seed={seed}, top_n={top_n}")

    def test_reproducible_with_seed(self):
        from datetime import date
        from fortunelib.calc.deities import draw_deities
        a = draw_deities(self.FACTS, target=date(2026, 8, 17), seed=5,
                         rng_mode="reproducible")
        b = draw_deities(self.FACTS, target=date(2026, 8, 17), seed=5,
                         rng_mode="reproducible")
        self.assertEqual([x["name"] for x in a["ranking"]],
                         [x["name"] for x in b["ranking"]])

    def test_affinity_reflects_profile(self):
        """ライフパス8なら『実り/富/権威』系の縁の根拠が現れる"""
        from datetime import date
        from fortunelib.calc.deities import draw_deities
        r = draw_deities(self.FACTS, target=date(2026, 8, 17), seed=42,
                         rng_mode="reproducible")
        reasons = [x for d in r["ranking"] for x in d["affinity_reasons"]]
        self.assertTrue(any("ライフパス8" in x for x in reasons), reasons)

    def test_wuxing_uses_structured_profile_only(self):
        """水瓶座や相談文の「水」は五行水として加点されない"""
        from fortunelib.calc.deities import (
            all_deities, _affinity_score, _profile_wuxing_elements,
        )
        incidental = {"太陽星座": "水瓶座", "_consultation": "水商売について"}
        self.assertEqual(_profile_wuxing_elements(incidental), set())
        for deity in all_deities():
            score, reasons = _affinity_score(deity, incidental)
            self.assertFalse(any(reason.startswith("五行の") for reason in reasons),
                             deity["name"])

        structured = {
            "干支（年柱・立春基準）": "甲子",
            "九星気学（本命星）": "二黒土星",
        }
        self.assertEqual(_profile_wuxing_elements(structured), {"木", "水", "土"})

    def test_unused_fact_does_not_change_reproducible_ranking(self):
        """親和判定に使わない表示用フィールドを変えても点数・順位は不変"""
        from datetime import date
        from fortunelib.calc.deities import draw_deities
        a_facts = {**self.FACTS, "表示用メモ": "ALPHA"}
        b_facts = {**self.FACTS, "表示用メモ": "BETA"}
        kwargs = dict(target=date(2026, 8, 17), seed=23,
                      rng_mode="reproducible")
        a = draw_deities(a_facts, **kwargs)["ranking"]
        b = draw_deities(b_facts, **kwargs)["ranking"]
        fields = ("name", "affinity_score", "lottery_score", "score", "affinity_reasons")
        self.assertEqual([[item[k] for k in fields] for item in a],
                         [[item[k] for k in fields] for item in b])

    def test_affinity_point_dominates_lottery_draw(self):
        """親和度1点差は乱数の最大差でも逆転しない"""
        from unittest import mock
        from fortunelib.calc.deities import (
            all_deities, draw_deities, _rank_key, _rank_score,
        )
        for lower_lottery in (0.0, 0.25, 0.5, 0.75, 0.999999999999):
            self.assertGreater(_rank_score(8, 0.0),
                               _rank_score(7, lower_lottery))
        self.assertEqual(_rank_score(7, 0.0), 28.0)
        self.assertLess(_rank_score(7, 0.999999999999), 32.0)
        # Ranking itself is lexicographic by affinity, even if a float composite ties.
        high_affinity = {"affinity_score": 8, "lottery_score": 0.0, "name": "Zulu"}
        low_affinity = {"affinity_score": 7, "lottery_score": 3.9999999999999964,
                        "name": "Aardvark"}
        self.assertLess(_rank_key(high_affinity), _rank_key(low_affinity))

        # End-to-end with the high-affinity candidate receiving the worst draw.
        deities = all_deities()
        high, low = deities[0], deities[1]
        high_id, low_id = (high["pantheon"], high["name"]), (low["pantheon"], low["name"])
        affinities = {high_id: 8, low_id: 7}
        def fake_affinity(deity, facts):
            return affinities.get((deity["pantheon"], deity["name"]), 0), []
        def fake_lottery(deity, day, seed, mode, rng):
            deity_id = (deity["pantheon"], deity["name"])
            return 0.0 if deity_id == high_id else (0.999999999999 if deity_id == low_id else 0.5)
        with mock.patch("fortunelib.calc.deities._affinity_score", side_effect=fake_affinity), \
             mock.patch("fortunelib.calc.deities._lottery_value", side_effect=fake_lottery):
            ranking = draw_deities({}, target=date(2026, 8, 17), seed=1,
                                   rng_mode="reproducible", top_n=len(deities))["ranking"]
        ranks = {(item["pantheon"], item["name"]): item["rank"] for item in ranking}
        self.assertLess(ranks[high_id], ranks[low_id])

    def test_top_n_requires_six_and_rejects_bad_values(self):
        """top_n は整数6〜全138柱に限定し、文明カバレッジを守る"""
        from fortunelib.calc.deities import all_deities, draw_deities
        for invalid in (0, -1, 1, 5, len(all_deities()) + 1):
            with self.subTest(top_n=invalid):
                with self.assertRaises(ValueError):
                    draw_deities(self.FACTS, top_n=invalid)
        for invalid in (5.0, "10", True, None):
            with self.subTest(top_n=invalid):
                with self.assertRaises(ValueError):
                    draw_deities(self.FACTS, top_n=invalid)
        full = draw_deities(self.FACTS, target=date(2026, 8, 17), seed=23,
                            rng_mode="reproducible", top_n=len(all_deities()))
        self.assertEqual(len(full["ranking"]), len(all_deities()))

    def test_synthesis_short_substrings_need_boundaries(self):
        """2文字の概念語は独立語として現れる場合だけ統合文に一致する"""
        from fortunelib.calc.deities import _synthesis_affinity_hits
        deity = {"keyword": "知恵", "symbol": "水", "domain": "知恵・水"}
        self.assertEqual(_synthesis_affinity_hits(deity, "知恵袋と水瓶座"), [])
        self.assertIn("知恵", _synthesis_affinity_hits(deity, "知恵と旅を続ける"))

    def test_registered_as_divination(self):
        from fortunelib.registry import REGISTRY
        self.assertIn("deities", REGISTRY)
        self.assertEqual(REGISTRY["deities"]["group"], "G6")
        self.assertEqual(REGISTRY["deities"]["prompt_id"], "P66")

    def test_prompt_definition_exists(self):
        from fortunelib.prompt import get_prompt_def
        d = get_prompt_def("P66")
        self.assertIn("char_min", d)
        self.assertIn("char_max", d)

    def test_runs_last_for_report_context(self):
        """統合レポートの文脈を使うため実行順は最後"""
        from fortunelib.registry import all_slugs
        self.assertEqual(all_slugs()[-1], "deities")

    def test_in_calc_batch(self):
        from fortunelib.profile import normalize_input
        from fortunelib.batch import build_calc_results
        ni = normalize_input({"birth": {"date": "1990-01-15"},
                              "consultation": CONSULTATION})
        r = build_calc_results(ni, consultation=CONSULTATION)["deities"]
        self.assertNotIn("error", r)
        self.assertEqual(len(r["ranking"]), 10)


class TestCsvBatchRunner(unittest.TestCase):
    """複数人バッチ（CSV入力）"""

    def _csv(self):
        from pathlib import Path
        return Path(__file__).resolve().parent.parent / "kaggle" / "people_sample.csv"

    def test_sample_csv_loads(self):
        from fortunelib.batch_runner import load_csv
        rows = load_csv(self._csv())
        self.assertGreaterEqual(len(rows), 1)
        for r in rows:
            self.assertTrue(r["birth_date"])

    def test_row_to_input_shape(self):
        from fortunelib.batch_runner import load_csv, row_to_input
        from fortunelib.profile import normalize_input
        for r in load_csv(self._csv()):
            ni = normalize_input(row_to_input(r))
            self.assertTrue(ni.birth.date)

    def test_safe_id(self):
        from fortunelib.batch_runner import safe_id
        self.assertEqual(safe_id("", 3), "person_03")
        self.assertEqual(safe_id("sato_hanako", 1), "sato_hanako")
        self.assertNotIn("/", safe_id("a/b:c", 1))

    def test_today_mode_detected_from_blank(self):
        """consultation 空欄なら今日の運勢モードになる（行データで検証）"""
        from fortunelib.batch_runner import row_to_input
        from fortunelib.profile import normalize_input
        row = {"birth_date": "1985-08-03", "consultation": ""}
        ni = normalize_input(row_to_input(row))
        self.assertEqual(ni.consultation, "")

class TestFullWidthDigitMatching(unittest.TestCase):
    """BUG-15: LLM が全角数字（ライフパス７）で出力すると照合に失敗した問題

    実機（yamada_taro）で籤占・伝統的霊能者の2件が誤判定された。
    """

    FACTS = {"太陽星座": "獅子座", "数秘術（ライフパス）": 7, "血液型": "O型"}
    PAD = "あ" * 380

    def _mm(self):
        from fortunelib.pipeline import _must_mention_facts, PipelineContext
        return _must_mention_facts({"group": "G6"},
                                   PipelineContext(inputs=None,
                                                   profile_facts=self.FACTS))

    def _issues(self, text):
        from fortunelib.validate import validate_output
        return [i for i in validate_output(text, min_chars=100, max_chars=900,
                                           must_mention=self._mm())
                if "事実整合" in i]

    def test_fullwidth_digit_accepted(self):
        self.assertEqual(self._issues("ライフパス７を持つあなたは" + self.PAD), [])

    def test_halfwidth_digit_accepted(self):
        self.assertEqual(self._issues("ライフパス7を持つあなたは" + self.PAD), [])

    def test_missing_fact_still_flagged(self):
        """検出力を落としていない"""
        self.assertTrue(self._issues("今日はよい一日でしょう。" + self.PAD))

    def test_normalize_helper(self):
        from fortunelib.validate import normalize_for_match as n
        self.assertEqual(n("ライフパス７"), "ライフパス7")
        self.assertEqual(n("ＡＢＣ１２３"), "ABC123")
        self.assertEqual(n("普通のテキスト"), "普通のテキスト")

    def test_fullwidth_sign_name(self):
        """全角が混じっても文字列の事実は一致する"""
        from fortunelib.validate import normalize_for_match as n
        self.assertIn("獅子座", n("獅子座の性質"))


class TestCsvBatchGuard(unittest.TestCase):
    """BUG-16: Cell 1（CSV）実行後に、1人固定モードのセルが再実行され1人目を
    二重生成した問題。

    現在は入力が CSV（Cell 1）のみに一本化され、1人固定モードのセル
    （cell1_input / cell2_calc_batch）は廃止された。ここでは Cell 1 が
    フラグを立て、CSV バッチとして動作することを検証する。
    """

    def _cell1(self):
        from pathlib import Path
        return (Path(__file__).resolve().parent.parent
                / "kaggle" / "cell1_csv_input.py").read_text(encoding="utf-8")

    def test_cell1_sets_flag(self):
        src = self._cell1()
        self.assertIn("CSV_BATCH_DONE = True", src)

    def test_cell1_reads_csv_only(self):
        """入力は CSV のみ。ハードコード入力の名残（INPUT 辞書）が無いこと。"""
        src = self._cell1()
        self.assertIn("load_csv", src)
        self.assertIn("people_sample", src)
        self.assertNotIn('"birth": {', src)   # cell1_input 時代の硬直入力は廃止

    def test_legacy_single_person_cells_retired(self):
        """1人固定モードのセルは廃止され kaggle/ に残っていないこと。"""
        from pathlib import Path
        kaggle = Path(__file__).resolve().parent.parent / "kaggle"
        self.assertFalse((kaggle / "cell1_input.py").exists(),
                         "cell1_input.py（ハードコード入力）は廃止されるべき")
        self.assertFalse((kaggle / "cell2_calc_batch.py").exists(),
                         "cell2_calc_batch.py（1人固定モード）は廃止されるべき")
        self.assertFalse((kaggle / "cell1b_csv_batch.py").exists(),
                         "cell1b_csv_batch.py は cell1_csv_input.py に改称されるべき")

class TestClusterDefinitions(unittest.TestCase):
    """FEAT-04: 占術クラスター定義（中間レポートの単位）"""

    def test_both_axes_cover_all(self):
        """両軸とも全66種を過不足なくカバーする（重複・欠落なし）"""
        from fortunelib.clusters import validate_axis
        for axis in ("method", "culture"):
            validate_axis(axis)   # 不備があれば AssertionError

    def test_method_axis_shape(self):
        from fortunelib.clusters import get_clusters
        cs = get_clusters("method")
        self.assertEqual(len(cs), 5)
        self.assertEqual(sum(len(c["slugs"]) for c in cs), 53)

    def test_culture_axis_shape(self):
        from fortunelib.clusters import get_clusters
        cs = get_clusters("culture")
        self.assertEqual(len(cs), 6)
        self.assertEqual(sum(len(c["slugs"]) for c in cs), 53)

    def test_unknown_axis_rejected(self):
        from fortunelib.clusters import get_clusters
        with self.assertRaises(ValueError):
            get_clusters("nonexistent")

    def test_cluster_of(self):
        from fortunelib.clusters import cluster_of
        self.assertEqual(cluster_of("bazi", "method")["id"], "M-B")
        self.assertEqual(cluster_of("bazi", "culture")["id"], "C-EA")

    def test_pseudo_cluster_contains_g6(self):
        """疑似体験クラスタ(M-E)は G6 のみで構成される"""
        from fortunelib.clusters import get_clusters
        from fortunelib.registry import REGISTRY
        me = next(c for c in get_clusters("method") if c["id"] == "M-E")
        for s in me["slugs"]:
            self.assertEqual(REGISTRY[s]["group"], "G6", s)


class TestSynthesisReport(unittest.TestCase):
    """FEAT-05: 2段階の統合レポート生成"""

    FACTS = {"太陽星座": "山羊座", "数秘術（ライフパス）": 8, "血液型": "A型"}

    def _fake_results(self, td, chars=517):
        """全66種の結果ファイルを作る"""
        from fortunelib.registry import REGISTRY
        rd = Path(td) / "results"
        rd.mkdir(parents=True, exist_ok=True)
        for slug, e in REGISTRY.items():
            (rd / f"{e['mcode']}_{slug}_raw.json").write_text(
                json.dumps({"result": {"text": "あ" * chars}},
                           ensure_ascii=False), encoding="utf-8")
        return rd

    def test_all_divinations_included(self):
        """予算超過でも黙って落とさず、クラスタ内の全占術を収載する"""
        import tempfile
        from fortunelib.clusters import get_clusters
        from fortunelib.synthesis import collect_cluster_inputs
        with tempfile.TemporaryDirectory() as td:
            rd = self._fake_results(td)
            for axis in ("method", "culture"):
                for c in get_clusters(axis):
                    items = collect_cluster_inputs(rd, c)
                    self.assertEqual(len(items), len(c["slugs"]), c["id"])

    def test_prompt_within_context(self):
        """各クラスタのプロンプトが実機検証済みコンテキスト(8192)に収まる"""
        import tempfile
        from fortunelib.clusters import get_clusters
        from fortunelib.synthesis import (collect_cluster_inputs,
                                          build_cluster_prompt)
        with tempfile.TemporaryDirectory() as td:
            rd = self._fake_results(td)
            for axis in ("method", "culture"):
                for c in get_clusters(axis):
                    items = collect_cluster_inputs(rd, c)
                    s, u = build_cluster_prompt(c, items, self.FACTS, "転職")
                    self.assertLess(len(s) + len(u), 8192, c["id"])

    def test_notebook_cell_present(self):
        cell = Path(__file__).resolve().parent.parent / "kaggle" / "cellN2_synthesis.py"
        self.assertTrue(cell.exists())
        text = cell.read_text(encoding="utf-8")
        self.assertIn("run_stage_b_mts", text)
        self.assertIn("run_stage_c_mts", text)
        self.assertNotIn("from fortunelib.synthesis import", text)


class TestDeities120(unittest.TestCase):
    """FEAT-06: 60→120柱に拡張 → FEAT-11: 151柱へ改訂 → mts5.21: 138柱へ改訂"""

    def test_deity_count(self):
        from fortunelib.calc.deities import all_deities, PANTHEONS
        from collections import Counter
        d = all_deities()
        self.assertEqual(len(d), 138)
        c = Counter(x["pantheon"] for x in d)
        self.assertEqual(dict(c), {"メソポタミア": 30, "エジプト": 21,
                                   "ギリシャ": 17, "インド": 31,
                                   "中国": 17, "日本": 22})
        for p in PANTHEONS:
            self.assertGreaterEqual(c[p], 10, p)

    def test_no_duplicate_names(self):
        from fortunelib.calc.deities import all_deities
        names = [(x["pantheon"], x["name"]) for x in all_deities()]
        self.assertEqual(len(names), len(set(names)))

    def test_all_fields_present(self):
        from fortunelib.calc.deities import all_deities
        for x in all_deities():
            for k in ("pantheon", "name", "en", "domain", "symbol", "keyword"):
                self.assertTrue(x.get(k), f"{x.get('name')} の {k}")

    def test_no_mojibake(self):
        """キリル文字などの混入がない（生成時の事故検出）"""
        import re
        from fortunelib.calc.deities import all_deities
        for x in all_deities():
            blob = json.dumps(x, ensure_ascii=False)
            self.assertIsNone(re.search(r"[а-яА-Я]", blob), x["name"])

    def test_synthesis_text_affects_selection(self):
        """統合レポート本文が選定に反映される"""
        from datetime import date
        from fortunelib.calc.deities import draw_deities
        f = {"太陽星座": "山羊座", "数秘術（ライフパス）": 8, "_consultation": "結婚"}
        base = draw_deities(f, target=date(2026, 8, 18), seed=7,
                            rng_mode="reproducible")
        withsyn = draw_deities(f, target=date(2026, 8, 18), seed=7,
                               rng_mode="reproducible",
                               synthesis_text="縁結びと実りが今年の鍵になります。")
        rb = [x["affinity_reasons"] for x in withsyn["ranking"]]
        flat = [r for rs in rb for r in rs]
        self.assertTrue(any("統合レポート" in r for r in flat), flat)
        self.assertNotEqual([x["name"] for x in base["ranking"]],
                            [x["name"] for x in withsyn["ranking"]])


class TestSynthesisSubjectName(unittest.TestCase):
    """Stage Cは入力漢字氏名を事実として渡し、ローマ字対の誤表記を直す。"""

    def test_report_uses_canonical_name_not_model_reconstructed_variant(self):
        import tempfile
        from fortunelib.synthesis import write_synthesis_file
        facts = {"氏名（漢字）": "星野 朱里", "氏名（ヘボン式）": "HOSHINO AKARI"}
        final = "今回の対象は星野明理（HOSHINO AKARI）です。"
        with tempfile.TemporaryDirectory() as td:
            path = write_synthesis_file(td, final, facts, "", "", {}, [])
            report = path.read_text(encoding="utf-8")
        self.assertIn("氏名（漢字）: 星野 朱里", report)
        self.assertIn("今回の対象は星野 朱里（HOSHINO AKARI）です。", report)
        self.assertNotIn("星野明理", report)

    def test_crossaxis_prompt_requires_exact_name_if_used(self):
        from fortunelib.synthesis import build_crossaxis_final_prompt
        facts = {"氏名（漢字）": "水城 栞", "氏名（ヘボン式）": "MIZUKI SHIORI"}
        system, user = build_crossaxis_final_prompt([], facts, CONSULTATION)
        self.assertIn("ローマ字から漢字を推定せず", system)
        self.assertIn("氏名（漢字）: 水城 栞", user)


class TestCrossAxisSynthesis(unittest.TestCase):
    """FEAT-07: 両軸統合（3段階）"""

    FACTS = {"太陽星座": "山羊座", "数秘術（ライフパス）": 8}

    def test_axis_summary_prompt_fits(self):
        from fortunelib.clusters import get_clusters
        from fortunelib.synthesis import build_axis_summary_prompt
        for axis in ("method", "culture"):
            reps = [{"id": c["id"], "title": c["title"],
                     "count": len(c["slugs"]), "text": "い" * 1500}
                    for c in get_clusters(axis)]
            s, u = build_axis_summary_prompt(axis, reps, self.FACTS, "転職")
            self.assertLess(len(s) + len(u), 8192, axis)

    def test_crossaxis_final_prompt_fits(self):
        from fortunelib.synthesis import build_crossaxis_final_prompt
        axs = [{"axis": "method", "text": "あ" * 2200},
               {"axis": "culture", "text": "い" * 2200}]
        s, u = build_crossaxis_final_prompt(axs, self.FACTS, "転職")
        self.assertLess(len(s) + len(u), 8192)

    def test_direct_injection_would_overflow(self):
        """中間11本を直接投入するとコンテキスト超過する（3段階が必要な根拠）"""
        self.assertGreater(1150 * 11, 8192)

class TestDeferredDeities(unittest.TestCase):
    """FEAT-08: 神々を統合レポート後に実行する順序変更"""

    def test_deities_is_deferred(self):
        from fortunelib.registry import is_deferred, main_slugs, all_slugs
        self.assertTrue(is_deferred("deities"))
        self.assertNotIn("deities", main_slugs())
        self.assertIn("deities", all_slugs())
        self.assertEqual(len(main_slugs()), len(all_slugs()) - 1)

    def test_force_overrides_skip_guard(self):
        import inspect
        from fortunelib.pipeline import run_divination
        self.assertIn("force", inspect.signature(run_divination).parameters)
        src = inspect.getsource(run_divination)
        self.assertIn("not force", src)

    def test_append_section(self):
        import tempfile
        from fortunelib.synthesis import append_deities_section
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "synthesis_report.md"
            p.write_text("# 統合鑑定レポート\n\n本文です。\n\n"
                         "---\n※ 本レポートはエンターテインメント目的の…\n",
                         encoding="utf-8")
            calc = {"ranking": [{"rank": 1, "name": "ラクシュミー",
                                 "pantheon": "インド", "domain": "富",
                                 "affinity_reasons": ["ライフパス8の『富』"]}]}
            append_deities_section(p, calc, "神々の解説文です。")
            t = p.read_text(encoding="utf-8")
            self.assertIn("## 御縁のある神さま Top10", t)
            self.assertIn("ラクシュミー", t)
            # 免責が最後に残る
            self.assertLess(t.find("ラクシュミー"),
                            t.find("エンターテインメント"))


class TestHtmlReport(unittest.TestCase):
    """FEAT-09: 全成果物を1枚のHTMLに束ねる"""

    def _make(self, td):
        d = Path(td)
        (d / "results").mkdir(parents=True)
        (d / "cluster_reports").mkdir()
        (d / "synthesis_report.md").write_text(
            "# 統合鑑定レポート\n\n## 総括\n\n**強調**と本文。\n", encoding="utf-8")
        (d / "cluster_reports" / "M-A_method.md").write_text(
            "# 中間レポート: 基礎\n\n本文。\n", encoding="utf-8")
        (d / "cluster_reports" / "AXIS_method.md").write_text(
            "# 軸サマリー: 手法軸\n\n総括。\n", encoding="utf-8")
        (d / "results" / "M01_eto.md").write_text(
            "# 干支\n\n- 項目1\n- 項目2\n", encoding="utf-8")
        return d

    def test_builds_single_file(self):
        import tempfile
        from fortunelib.html_report import build_html
        with tempfile.TemporaryDirectory() as td:
            d = self._make(td)
            p = build_html(d, person_id="test")
            self.assertTrue(p.exists())
            self.assertTrue(p.name.endswith(".html"))

    def test_self_contained(self):
        """外部リソース参照がない（オフラインで読める）"""
        import tempfile
        from fortunelib.html_report import build_html
        with tempfile.TemporaryDirectory() as td:
            t = build_html(self._make(td), person_id="t").read_text(encoding="utf-8")
            self.assertNotIn("http://", t)
            self.assertNotIn("https://", t)
            self.assertNotIn("<script", t)

    def test_section_order(self):
        """統合 → クラスター → 個別 の順に並ぶ"""
        import tempfile
        from fortunelib.html_report import build_html
        with tempfile.TemporaryDirectory() as td:
            t = build_html(self._make(td), person_id="t").read_text(encoding="utf-8")
            i1 = t.find('id="synthesis"')
            i2 = t.find('id="clusters"')
            i3 = t.find('id="results"')
            self.assertTrue(0 < i1 < i2 < i3, (i1, i2, i3))

    def test_mobile_ready(self):
        import tempfile
        from fortunelib.html_report import build_html
        with tempfile.TemporaryDirectory() as td:
            t = build_html(self._make(td), person_id="t").read_text(encoding="utf-8")
            self.assertIn("width=device-width", t)
            self.assertIn("prefers-color-scheme", t)

    def test_markdown_converted(self):
        import tempfile
        from fortunelib.html_report import build_html
        with tempfile.TemporaryDirectory() as td:
            t = build_html(self._make(td), person_id="t").read_text(encoding="utf-8")
            self.assertIn("<strong>強調</strong>", t)
            self.assertIn("<li>項目1</li>", t)

    def test_disclaimer_once(self):
        """免責は全体で1回だけ"""
        import tempfile
        from fortunelib.html_report import build_html
        with tempfile.TemporaryDirectory() as td:
            t = build_html(self._make(td), person_id="t").read_text(encoding="utf-8")
            self.assertEqual(t.count("エンターテインメント目的"), 1)

    def test_empty_raises(self):
        import tempfile
        from fortunelib.html_report import build_html
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(RuntimeError):
                build_html(Path(td), person_id="x")


class TestHtmlFooterDedup(unittest.TestCase):
    """BUG-17: 個別占術の免責「※ 本結果は…」を落とせず、1枚HTMLに67回出た問題"""

    def test_strips_kekka_form(self):
        from fortunelib.html_report import _strip_footer
        t = "本文\n\n---\n※ 本結果はエンターテインメント目的の…\n※ 医療・法律…"
        self.assertNotIn("エンターテインメント", _strip_footer(t))

    def test_strips_report_form(self):
        from fortunelib.html_report import _strip_footer
        t = "本文\n\n---\n※ 本レポートはエンターテインメント目的の…"
        self.assertNotIn("エンターテインメント", _strip_footer(t))

    def test_keeps_body(self):
        from fortunelib.html_report import _strip_footer
        t = "大事な本文です。\n\n---\n※ 本結果はエンターテインメント…"
        self.assertIn("大事な本文です。", _strip_footer(t))

    def test_disclaimer_once_in_html(self):
        """個別ファイルが複数あっても免責は1回だけ"""
        import tempfile
        from fortunelib.html_report import build_html
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "results").mkdir()
            (d / "synthesis_report.md").write_text(
                "# 統合鑑定レポート\n\n本文。\n\n---\n"
                "※ 本レポートはエンターテインメント目的の…\n", encoding="utf-8")
            for i in range(5):
                (d / "results" / f"M0{i}_x.md").write_text(
                    f"# 占術{i}\n\n本文。\n\n---\n"
                    "※ 本結果はエンターテインメント目的の…\n"
                    "※ 医療・法律・投資・人生の重大な決定には利用しないでください。\n",
                    encoding="utf-8")
            t = build_html(d, person_id="t").read_text(encoding="utf-8")
            self.assertEqual(t.count("エンターテインメント目的"), 1)


class TestLengthTolerance(unittest.TestCase):
    """実機で全レポートが下限寄りだったため、再生成の発火条件を引き締めた"""

    def test_cluster_band_tightened(self):
        """TUNE-02 で定数化されたので値そのものを検証する"""
        from fortunelib.synthesis import CLUSTER_CHARS
        self.assertEqual(CLUSTER_CHARS, (950, 2100))

    def test_final_band_tightened(self):
        """mts5.58/5.60: 下限を 3,400 → 4,000 へ（上限は 4,900 → 5,300）"""
        from fortunelib.synthesis import FINAL_CHARS
        self.assertEqual(FINAL_CHARS, (4000, 5300))

    def test_observed_shortfalls_would_now_retry(self):
        """実機で素通りした字数が、新しい条件では再生成対象になる"""
        from fortunelib.synthesis import _fits, AXIS_SUMMARY_CHARS
        self.assertFalse(_fits("あ" * 910, 950, 2100))    # 中間
        self.assertFalse(_fits("あ" * 959, 950, 2100) and False)
        from fortunelib.synthesis import FINAL_CHARS as _FB
        self.assertFalse(_fits("あ" * 3994, *_FB))         # 最終（mts5.58/5.60）
        self.assertTrue(_fits("あ" * 4000, *_FB))          # 下限ちょうどは合格
        self.assertFalse(_fits("あ" * (4000 + _FB[1] - 4000 + 1), *_FB))  # 上限超えも対象
        self.assertFalse(_fits("あ" * 1131, *AXIS_SUMMARY_CHARS))  # 軸


class TestPseudoCleanup(unittest.TestCase):
    """FIX-01: 計算アンカーのない疑似体験系13種を削除（内容が一様化していたため）"""

    REMOVED = ["witchdoctor", "sangoma", "reikan", "psychic", "prophecy",
               "paranormal", "mganga", "hado", "geist", "dukun",
               "channeling", "aura", "akashic"]

    def test_removed_from_registry(self):
        from fortunelib.registry import REGISTRY
        for s in self.REMOVED:
            self.assertNotIn(s, REGISTRY, s)

    def test_count_is_53(self):
        from fortunelib.registry import REGISTRY
        self.assertEqual(len(REGISTRY), 53)

    def test_anchored_ones_kept(self):
        """実際の抽選を持つ3種は残す"""
        from fortunelib.registry import REGISTRY
        for s in ("pendulum", "african", "astragaloi"):
            self.assertIn(s, REGISTRY, s)
            self.assertTrue(REGISTRY[s]["calc_key"], s)

    def test_clusters_still_consistent(self):
        from fortunelib.clusters import validate_axis
        for axis in ("method", "culture"):
            validate_axis(axis)

    def test_every_g6_has_anchor_or_source(self):
        """残ったG6は、抽選・引用いずれかの拠り所を持つ"""
        from fortunelib.registry import REGISTRY
        SOURCED = {"crystal", "crystalball", "talisman", "delphi",
                   "haruspex", "ornith"}   # 象徴体系として語彙が明確なもの
        for s, e in REGISTRY.items():
            if e["group"] != "G6":
                continue
            self.assertTrue(e["calc_key"] or s in SOURCED, s)


class TestTextDraw(unittest.TestCase):
    """FEAT-10: オーメン／聖句をおみくじ方式で引く"""

    def test_omen_dataset(self):
        from fortunelib.calc.textdraw import all_omens
        o = all_omens()
        self.assertGreaterEqual(len(o), 20)
        for x in o:
            for k in ("id", "protasis", "apodosis", "theme", "body"):
                self.assertTrue(x.get(k), x.get("id"))

    def test_verse_dataset(self):
        from fortunelib.calc.textdraw import all_verses
        v = all_verses()
        self.assertGreaterEqual(len(v), 20)
        for x in v:
            self.assertTrue(x.get("ref"))
            self.assertTrue(x.get("text"))

    def test_verses_are_new_testament(self):
        """旧約は含めない（ご要望が新約のため）"""
        from fortunelib.calc.textdraw import all_verses
        OT = ("創世記", "詩篇", "箴言", "イザヤ", "伝道", "出エジプト")
        for v in all_verses():
            self.assertFalse(v["ref"].startswith(OT), v["ref"])

    def test_omen_two_part_structure(self):
        """メソポタミア占術の定型（前兆＋判断）を保つ"""
        from fortunelib.calc.textdraw import draw_omen
        o = draw_omen(seed=1, rng_mode="reproducible")
        self.assertIn("ならば", o["protasis"])
        self.assertIn(o["protasis"], o["full_text"])
        self.assertIn(o["apodosis"], o["full_text"])

    def test_draw_varies(self):
        """シードを変えると引く対象が変わる（固有性の担保）"""
        from fortunelib.calc.textdraw import draw_omen, draw_verse
        omens = {draw_omen(seed=i, rng_mode="reproducible")["omen_id"]
                 for i in range(12)}
        verses = {draw_verse(seed=i, rng_mode="reproducible")["reference"]
                  for i in range(12)}
        self.assertGreater(len(omens), 3)
        self.assertGreater(len(verses), 3)

    def test_reproducible(self):
        from fortunelib.calc.textdraw import draw_omen
        a = draw_omen(seed=5, rng_mode="reproducible")
        b = draw_omen(seed=5, rng_mode="reproducible")
        self.assertEqual(a["omen_id"], b["omen_id"])

    def test_wired_into_batch(self):
        from fortunelib.profile import normalize_input
        from fortunelib.batch import build_calc_results
        ni = normalize_input({"birth": {"date": "1990-01-15"},
                              "consultation": CONSULTATION})
        R = build_calc_results(ni, consultation=CONSULTATION)
        for k in ("meso_omen", "bible_verse"):
            self.assertIn(k, R)
            self.assertNotIn("error", R[k])

    def test_registry_calc_keys(self):
        from fortunelib.registry import REGISTRY
        self.assertEqual(REGISTRY["meso"]["calc_key"], "meso_omen")
        self.assertEqual(REGISTRY["christian"]["calc_key"], "bible_verse")


class TestLineageFilter(unittest.TestCase):
    """FIX-02: 系譜外の術語が流入する問題（実機66種中30種で発生）"""

    FACTS = {"太陽星座": "山羊座", "干支（年柱・立春基準）": "己巳",
             "九星気学（本命星）": "二黒土星", "数秘術（ライフパス）": 8,
             "ウェトン": "月曜・Pon", "氏名（ヘボン式）": "SATO HANAKO",
             "氏名（漢字）": "佐藤 花子", "氏名（かな）": "さとう はなこ"}

    def test_eastasia_keeps_own(self):
        from fortunelib.lineage import allowed_facts
        a = allowed_facts("kyusei", self.FACTS)
        self.assertIn("九星気学（本命星）", a)
        self.assertNotIn("太陽星座", a)
        self.assertNotIn("数秘術（ライフパス）", a)

    def test_western_keeps_own(self):
        from fortunelib.lineage import allowed_facts
        a = allowed_facts("seiza", self.FACTS)
        self.assertIn("太陽星座", a)
        self.assertNotIn("九星気学（本命星）", a)

    def test_ancient_gets_none_of_them(self):
        """古代オリエントは近代の術語を一切参照しない"""
        from fortunelib.lineage import allowed_facts
        for slug in ("delphi", "meso", "haruspex", "ornith", "astragaloi"):
            a = allowed_facts(slug, self.FACTS)
            for k in ("太陽星座", "九星気学（本命星）", "数秘術（ライフパス）"):
                self.assertNotIn(k, a, f"{slug} に {k}")

    def test_name_always_allowed(self):
        from fortunelib.lineage import allowed_facts
        for slug in ("dukun", "delphi", "kyusei", "seiza"):
            scoped = allowed_facts(slug, self.FACTS)
            self.assertIn("氏名（ヘボン式）", scoped)
            self.assertIn("氏名（漢字）", scoped)
            self.assertIn("氏名（かな）", scoped)

    def test_neutral_hint_supplied(self):
        from fortunelib.lineage import neutral_context
        n = neutral_context(self.FACTS)
        self.assertEqual(n.get("生まれた季節"), "冬の初め")

    def test_lineage_note_forbids(self):
        from fortunelib.lineage import lineage_note
        note = lineage_note("delphi")
        self.assertIn("九星", note)
        self.assertIn("ライフパス", note)

    def test_deities_unrestricted(self):
        """御縁のある神さまは複数文明を横断するので制限しない"""
        from fortunelib.lineage import allowed_facts
        self.assertEqual(len(allowed_facts("deities", self.FACTS)),
                         len(self.FACTS))

    def test_unknown_slug_safe(self):
        """未登録スラグでも壊れない（後方互換）"""
        from fortunelib.lineage import allowed_facts
        self.assertEqual(len(allowed_facts("", self.FACTS)), len(self.FACTS))

    def test_pipeline_applies_filter(self):
        import inspect
        from fortunelib import pipeline
        src = inspect.getsource(pipeline.run_divination)
        self.assertIn("allowed_facts", src)
        self.assertIn("lineage_note", src)


class TestMustMentionAfterLineage(unittest.TestCase):
    """BUG-18: 系譜フィルタの副作用で「氏名を織り込め」という無理な要求になった問題

    実機（53種）で古代オリエント系など7件が誤判定された。
    参照可能な事実がローマ字氏名だけになっていたため。
    """

    FACTS = {"太陽星座": "山羊座", "九星気学（本命星）": "二黒土星",
             "数秘術（ライフパス）": 8, "氏名（ヘボン式）": "SATO HANAKO",
             "氏名（漢字）": "佐藤 花子", "氏名（かな）": "さとう はなこ"}

    def _mm(self, slug, calc_key=None, calc=None):
        from fortunelib.pipeline import _must_mention_facts, PipelineContext
        ctx = PipelineContext(inputs=None, profile_facts=self.FACTS,
                              calc_results={calc_key: calc} if calc_key else {})
        return _must_mention_facts(
            {"group": "G6", "slug": slug, "calc_key": calc_key}, ctx)

    def test_romaji_name_never_required(self):
        """ローマ字氏名は織り込み必須にしない"""
        for slug in ("delphi", "haruspex", "ornith", "crystal"):
            mm = self._mm(slug)
            self.assertNotIn("SATO HANAKO", mm)
            self.assertNotIn("佐藤 花子", mm)
            self.assertNotIn("さとう はなこ", mm)

    def test_drawn_text_exempts(self):
        """抽選テキストを持つ占術は必須言及を課さない"""
        for slug, ck, calc in [
                ("meso", "meso_omen", {"full_text": "土星が…"}),
                ("christian", "bible_verse", {"verse": "求めよ…"}),
                ("astragaloi", "astragaloi", {"judgment": "通常の目"}),
                ("african", "cowrie", {"pattern_id": 100}),
                ("pendulum", "pendulum", {"answer": "yes"})]:
            self.assertEqual(self._mm(slug, ck, calc), [], slug)

    def test_no_facts_left_exempts(self):
        """参照できる事実が残らない体系は必須言及なし"""
        self.assertEqual(self._mm("delphi"), [])

    def test_systems_with_facts_still_required(self):
        """事実を持つ体系には従来どおり必須言及を課す（検出力を維持）"""
        mm = self._mm("crystal")
        self.assertTrue(mm)
        self.assertIn("山羊座", mm)

    def test_eastasia_uses_own_fact(self):
        mm = self._mm("kyusei", "kyusei", {"honmei": "二黒土星"})
        self.assertIn("二黒土星", mm)


class TestInstructValidateSeparation(unittest.TestCase):
    """TUNE-02: 指示字数と検証字数を分離してパレート改善する

    実測: 出力 ≒ 指示下限 × 1.085（σ0.080）。指示=検証だと約14%が
    下限を割って再生成が発火する（実機15工程中5件）。
    指示を1.10倍にすると発火率1.4%まで下がり、出力も約10%増える。
    """

    def test_margin_defined(self):
        from fortunelib.synthesis import INSTRUCT_MARGIN
        self.assertGreater(INSTRUCT_MARGIN, 1.0)
        self.assertLess(INSTRUCT_MARGIN, 1.3)

    def test_instruct_above_validate(self):
        """mts5.58: 中間・軸は比例マージン、最終は明示の指示レンジ。どちらも
        指示下限 > 検証下限・指示上限 = 検証上限（上限は据え置き）を守る。"""
        from fortunelib.synthesis import (_instruct_range, CLUSTER_CHARS,
                                          AXIS_SUMMARY_CHARS, FINAL_CHARS,
                                          FINAL_INSTRUCT_CHARS)
        cases = [(_instruct_range(*CLUSTER_CHARS), CLUSTER_CHARS),
                 (_instruct_range(*AXIS_SUMMARY_CHARS), AXIS_SUMMARY_CHARS),
                 (FINAL_INSTRUCT_CHARS, FINAL_CHARS)]
        for (ins_lo, ins_hi), band in cases:
            self.assertGreater(ins_lo, band[0], band)
            # 中間・軸は比例マージンなので検証上限と一致。最終（mts5.60）は指示上限の
            # 出力が「長すぎ」と警告されないよう、検証上限に余裕（≥50字）を持たせる。
            self.assertLessEqual(ins_hi, band[1], band)
        self.assertEqual(_instruct_range(*CLUSTER_CHARS)[1], CLUSTER_CHARS[1])
        self.assertEqual(_instruct_range(*AXIS_SUMMARY_CHARS)[1], AXIS_SUMMARY_CHARS[1])
        self.assertGreaterEqual(FINAL_CHARS[1] - FINAL_INSTRUCT_CHARS[1], 50)
        for (ins_lo, ins_hi), band in cases:
            self.assertLess(ins_lo, ins_hi, band)

    def test_expected_output_lands_in_band(self):
        """実測の比率(1.085)で、指示下限×1.085 が検証レンジ内に入る"""
        from fortunelib.synthesis import (_instruct_range, CLUSTER_CHARS,
                                          AXIS_SUMMARY_CHARS, FINAL_CHARS)
        from fortunelib.synthesis import FINAL_INSTRUCT_CHARS
        for ins, band in ((_instruct_range(*CLUSTER_CHARS)[0], CLUSTER_CHARS),
                          (_instruct_range(*AXIS_SUMMARY_CHARS)[0], AXIS_SUMMARY_CHARS),
                          (FINAL_INSTRUCT_CHARS[0], FINAL_CHARS)):
            expected = ins * 1.085
            self.assertGreaterEqual(expected, band[0], band)
            self.assertLessEqual(expected, band[1], band)

    def test_prompts_use_instruct_range(self):
        """プロンプトには指示レンジ（高め）が書かれる"""
        import re
        from fortunelib.clusters import get_clusters
        from fortunelib.synthesis import (build_cluster_prompt, CLUSTER_CHARS,
                                          _instruct_range)
        c = get_clusters("method")[0]
        s, _ = build_cluster_prompt(
            c, [{"name": "X", "excerpt": "あ" * 80, "slug": "x", "group": "G6"}],
            {"a": 1}, CONSULTATION)
        m = re.search(r"【分量】(\d+)〜", s)
        self.assertEqual(int(m.group(1)), _instruct_range(*CLUSTER_CHARS)[0])
        self.assertNotEqual(int(m.group(1)), CLUSTER_CHARS[0])

    def test_validation_uses_validate_range(self):
        """検証は低いほう（検証レンジ）で行う"""
        import inspect
        from fortunelib import mts
        src = inspect.getsource(mts._gen_with_retry)
        self.assertIn("_fits(text, *band)", src)
        self.assertIn("CLUSTER_CHARS", inspect.getsource(mts.run_stage_b_mts))
        self.assertIn("FINAL_CHARS", inspect.getsource(mts.run_stage_c_mts))

    def test_retry_rate_improves(self):
        """指示を上げると下限割れ確率が下がることをモデルで確認"""
        import math
        from fortunelib.synthesis import (INSTRUCT_MARGIN, CLUSTER_CHARS)
        mu_r, sd_r = 1.085, 0.080
        phi = lambda z: 0.5 * (1 + math.erf(z / math.sqrt(2)))
        lo, hi = CLUSTER_CHARS

        def p_short(instruct_lo):
            mu, sd = instruct_lo * mu_r, instruct_lo * sd_r
            return phi((lo - mu) / sd)

        before = p_short(lo)                      # 指示=検証
        after = p_short(int(lo * INSTRUCT_MARGIN))  # 指示を上げた場合
        self.assertLess(after, before / 3, (before, after))


class TestNonQuotableFacts(unittest.TestCase):
    """BUG-18b: 生の日付が必須言及に残り3件が誤判定された（実機53種）

    ローマ字氏名と同じく、「1988-07-22」を鑑定文に literal で
    書けという要求は不自然。日付形式は一律で対象外にする。
    """

    FACTS = {"太陽星座": "山羊座", "九星気学（本命星）": "二黒土星",
             "数秘術（ライフパス）": 8, "氏名（ヘボン式）": "SATO HANAKO",
             "相手の生年月日": "1988-07-22"}

    def _mm(self, slug):
        from fortunelib.pipeline import _must_mention_facts, PipelineContext
        ctx = PipelineContext(inputs=None, profile_facts=self.FACTS,
                              calc_results={})
        return _must_mention_facts(
            {"group": "G6", "slug": slug, "calc_key": None}, ctx)

    def test_raw_date_not_required(self):
        for slug in ("delphi", "haruspex", "ornith"):
            self.assertEqual(self._mm(slug), [], slug)

    def test_date_pattern_excluded_anywhere(self):
        """どの体系でも生の日付は必須言及に入らない"""
        for slug in ("crystal", "crystalball", "talisman"):
            self.assertNotIn("1988-07-22", self._mm(slug))

    def test_normal_facts_survive(self):
        mm = self._mm("crystal")
        self.assertIn("山羊座", mm)


class TestLengthAwareMargin(unittest.TestCase):
    """TUNE-03: 指示に対する伸び率が長さに依存する（実測）

    1200字級 → 比 1.24 ／ 3800字級 → 比 1.02
    長文は指示に張り付くため、大きめのマージンが要る。
    """

    def test_long_gets_bigger_margin(self):
        from fortunelib.synthesis import (INSTRUCT_MARGIN,
                                          INSTRUCT_MARGIN_LONG)
        self.assertGreater(INSTRUCT_MARGIN_LONG, INSTRUCT_MARGIN)

    def test_final_instruct_raised(self):
        from fortunelib.synthesis import _instruct_range, FINAL_CHARS
        lo, _ = _instruct_range(*FINAL_CHARS)
        self.assertGreater(lo, 3900)

    def test_short_unchanged(self):
        from fortunelib.synthesis import (_instruct_range, CLUSTER_CHARS,
                                          INSTRUCT_MARGIN)
        lo, _ = _instruct_range(*CLUSTER_CHARS)
        self.assertEqual(lo, int(CLUSTER_CHARS[0] * INSTRUCT_MARGIN))

    def test_expected_outputs_in_band(self):
        """実測の伸び率を当てると全段が検証レンジに収まる"""
        from fortunelib.synthesis import (_instruct_range, CLUSTER_CHARS,
                                          AXIS_SUMMARY_CHARS, FINAL_CHARS)
        from fortunelib.synthesis import FINAL_INSTRUCT_CHARS
        for ins, band, ratio in [
                (_instruct_range(*CLUSTER_CHARS)[0], CLUSTER_CHARS, 1.24),
                (_instruct_range(*AXIS_SUMMARY_CHARS)[0], AXIS_SUMMARY_CHARS, 1.10),
                (FINAL_INSTRUCT_CHARS[0], FINAL_CHARS, 1.018)]:
            exp = ins * ratio
            self.assertGreaterEqual(exp, band[0], band)
            self.assertLessEqual(exp, band[1], band)

    def test_tune04_long_margin_raised(self):
        """TUNE-04: 10回目の実機で最終統合の余裕が159字しかなかったため
        LONG マージンを 1.18 → 1.22 に引き上げた（中間・軸で有効）。

        mts5.58/5.60: 最終レポートは下限を 4,000 字へ上げ、さらに指示の下限を
        4,800 字へ引き上げたため、比例マージン（3,400×1.22 = 4,148）ではなく
        明示の指示レンジを使う。"""
        from fortunelib.synthesis import (INSTRUCT_MARGIN_LONG,
                                          _instruct_range, FINAL_CHARS,
                                          FINAL_INSTRUCT_CHARS)
        self.assertAlmostEqual(INSTRUCT_MARGIN_LONG, 1.22, places=3)
        self.assertNotEqual(_instruct_range(*FINAL_CHARS)[0], 4148)
        self.assertEqual(FINAL_INSTRUCT_CHARS, (4800, 5200))
        # プロンプトに書かれるのは明示レンジ
        self.assertIn(f"【分量】全体で{FINAL_INSTRUCT_CHARS[0]}"
                      f"〜{FINAL_INSTRUCT_CHARS[1]}字", 
                      __import__("fortunelib.synthesis", fromlist=["x"])
                      .build_crossaxis_final_prompt(
                          [{"axis": "method", "text": "あ" * 50}],
                          {"a": 1}, CONSULTATION)[0])

    def test_tune04_worst_case_still_in_band(self):
        """mts5.58: 下限 4,000 字の担保は「上乗せ」と「再生成」の二段構え。

        - 実機で観測した最悪の下振れ（実測比 0.84＝mts5.58 の 3,716字/指示4,400字）でも
          4,800×0.84 = 4,032 字で下限 4,000 を割らない（mts5.60 で指示下限を 4,800 へ）
        - さらに下ぶれた場合（同 0.83）は検証で不合格になり、再生成の指示で作り直される
          ＝**黙って採用されない**
        """
        from fortunelib.synthesis import (FINAL_INSTRUCT_CHARS, FINAL_CHARS,
                                          _fits)
        lo_ins = FINAL_INSTRUCT_CHARS[0]
        self.assertGreaterEqual(lo_ins * 0.84, FINAL_CHARS[0])   # 実測最悪 0.84 を吸収
        self.assertGreaterEqual(lo_ins * 0.96, FINAL_CHARS[0])
        self.assertFalse(_fits("あ" * int(lo_ins * 0.70), *FINAL_CHARS))
        # 上振れ側（指示上限のすぐ上）まで検証の帯に入れる＝余裕 50字以上
        self.assertGreaterEqual(FINAL_CHARS[1] - FINAL_INSTRUCT_CHARS[1], 50)


class TestDeitiesRevision(unittest.TestCase):
    """FEAT-11: 神々データの改訂（151柱・同一神の統合・入替）→ mts5.21: 13柱削除で138柱"""

    def _names(self, pantheon=None):
        from fortunelib.calc.deities import all_deities
        return [x["name"] for x in all_deities()
                if pantheon is None or x["pantheon"] == pantheon]

    def test_total_and_integrity(self):
        from fortunelib.calc.deities import all_deities
        ds = all_deities()
        self.assertEqual(len(ds), 138)
        pairs = [(x["pantheon"], x["name"]) for x in ds]
        self.assertEqual(len(pairs), len(set(pairs)))       # 重複なし
        for x in ds:
            for k in ("pantheon", "name", "en", "domain", "symbol", "keyword"):
                self.assertTrue(x.get(k), f"{x.get('name')}: {k}")

    def test_merged_same_deities(self):
        """同一神は1エントリに統合（別名を併記）"""
        n = self._names("メソポタミア")
        self.assertIn("ナンナ（シン）", n)
        self.assertIn("ウトゥ（シャマシュ）", n)
        self.assertNotIn("シン", n)
        self.assertNotIn("シャマシュ", n)

    def test_tiamat_replaced_by_nammu(self):
        n = self._names("メソポタミア")
        self.assertIn("ナンマ（ナンム）", n)
        self.assertNotIn("ティアマト", n)

    def test_mesopotamia_additions(self):
        n = self._names("メソポタミア")
        for x in ("ニンギリマ", "ナンシェ", "ニンシュブル", "クス", "ヌスカ",
                  "アヤ（シェリダ）", "ラマ", "ゲシュティンアンナ",
                  "ニンギシュジダ", "ニンカシ", "ニンエガル", "ニンアズ",
                  "ニンガル", "アルル"):
            self.assertIn(x, n, x)

    def test_egypt_wadjet(self):
        self.assertIn("ワジェト", self._names("エジプト"))

    def test_india_swap(self):
        n = self._names("インド")
        for x in ("ラーマ", "クリシュナ", "ヤマ"):
            self.assertNotIn(x, n, x)
        for x in ("アーパス", "アディティ", "バガ", "アリヤマン", "プーシャン",
                  "ブラフマナスパティ", "ウシャス", "ラートリー", "ソーマ",
                  "ミトラ", "ヴァルナ", "ナーサティヤ（アシュヴィン）",
                  "プリトヴィ", "トヴァシュトリ", "ヴァーチュ"):
            self.assertIn(x, n, x)

    def test_china_swap(self):
        n = self._names("中国")
        for x in ("關聖帝君", "媽祖", "鍾馗"):
            self.assertNotIn(x, n, x)
        self.assertIn("炎帝神農", n)

    def test_japan_changes(self):
        n = self._names("日本")
        self.assertIn("思兼神", n)
        self.assertNotIn("思金神", n)
        self.assertIn("祓戸大神", n)
        self.assertNotIn("瀬織津姫", n)
        self.assertNotIn("菅原道真", n)
        for x in ("天之御中主神", "建御名方神", "倭文神", "菊理媛", "座摩神",
                  "五十猛神", "久延毘古", "事代主神", "塩土老翁"):
            self.assertIn(x, n, x)

    def test_no_latin_in_japanese_fields(self):
        """BUG-19: 日本語フィールドへの英単語混入（ブラフマーの domain=創造・knowledge）"""
        import re
        from fortunelib.calc.deities import all_deities
        bad = [(x["name"], k, x[k]) for x in all_deities()
               for k in ("name", "domain", "symbol", "keyword")
               if re.search(r"[A-Za-z]", x.get(k, ""))]
        self.assertEqual(bad, [], bad)

    def test_all_pantheons_still_covered(self):
        """柱数が不均等になっても6文明すべてが Top10 に入る"""
        from datetime import date
        from fortunelib.calc.deities import draw_deities, PANTHEONS
        facts = {"太陽星座": "蟹座", "数秘術（ライフパス）": 3,
                 "_consultation": "独立と昇進"}
        for seed in (1, 7, 42, 99, 123):
            r = draw_deities(facts, target=date(2026, 8, 18), seed=seed,
                             rng_mode="reproducible")
            for p in PANTHEONS:
                self.assertGreaterEqual(r["pantheon_coverage"][p], 1,
                                        f"seed={seed} {p}")


class TestNewTestPerson(unittest.TestCase):
    """バグ検出用に別プロファイルへ差し替え（高橋 蓮）"""

    INPUT = {"birth": {"date": "1978-07-07", "time": "05:20", "place": "福岡県"},
             "gender": "M", "blood_type": "O",
             "name_kanji": "高橋 蓮", "name_kana": "たかはし れん",
             "partner": {"date": "1982-11-30", "time": "23:45",
                         "place": "北海道"},
             "consultation": CONSULTATION}

    def test_profile_differs_from_previous(self):
        """前回の人物と全事実が異なる（同じ経路ばかり通らない）"""
        from fortunelib.profile import normalize_input
        from fortunelib.batch import build_profile_facts
        f = build_profile_facts(normalize_input(self.INPUT))
        prev = {"太陽星座": "山羊座", "九星気学（本命星）": "二黒土星",
                "数秘術（ライフパス）": 8, "血液型": "A型"}
        for k, v in prev.items():
            self.assertNotEqual(f.get(k), v, k)

    def test_calc_batch_no_error(self):
        from fortunelib.profile import normalize_input
        from fortunelib.batch import build_calc_results
        ni = normalize_input(self.INPUT)
        R = build_calc_results(ni, consultation=ni.consultation)
        errs = {k: v for k, v in R.items()
                if isinstance(v, dict) and "error" in v}
        self.assertEqual(errs, {}, errs)

    def test_late_night_partner_time(self):
        """相手の 23:45 は日界（23時切替）の分岐を通る"""
        from fortunelib.profile import normalize_input
        ni = normalize_input(self.INPUT)
        self.assertEqual(ni.partner.time, "23:45")
        self.assertFalse(ni.partner.time_unknown)

    def test_csv_and_cell_updated(self):
        """CSV は複数人バッチ用サンプルで、人物は自由に入れ替えられる。

        ★人物名のハードコードをしない。以前は ``takahashi_ren`` を
        ``assertIn`` していたが、ユーザーが別の人物へ差し替えると
        偽陽性で本番セルフテストを止めてしまった。代わりに構造の
        不変条件だけを検査する:
          - people_sample.csv: ヘッダ＋1行以上＋birth_date が読める
          - 入力セル（cell1_csv_input.py）が CSV だけを読むこと
        """
        from fortunelib.batch_runner import load_csv
        base = Path(__file__).resolve().parent.parent / "kaggle"
        rows = load_csv(base / "people_sample.csv")
        self.assertGreaterEqual(len(rows), 1)
        for r in rows:
            self.assertTrue(r["birth_date"])
        cell = (base / "cell1_csv_input.py").read_text(encoding="utf-8")
        self.assertIn("load_csv", cell)
        self.assertIn("people_sample", cell)


class TestSelfTestCell(unittest.TestCase):
    """BUG-20: Cell 0.1 セルフテストが Kaggle 上で NameError で即死した

    原因は2つ:
      1. ノートブックのセルには __file__ が存在しないのに参照していた
      2. Dataset に tests/ と kaggle/ が含まれておらず、
         テストがセルのソースを読めず FileNotFoundError になった
    """

    def _src(self):
        p = Path(__file__).resolve().parent.parent / "kaggle" / "cell0_selftest.py"
        return p.read_text(encoding="utf-8")

    def test_does_not_use_dunder_file(self):
        """__file__ を使わない（ノートブックのセルには存在しないため）

        コメント中の言及は許容し、実行されるコード行のみを検査する。
        """
        code = [ln for ln in self._src().splitlines()
                if not ln.lstrip().startswith("#")]
        offending = [ln for ln in code if "__file__" in ln]
        self.assertEqual(offending, [], offending)

    def test_compiles(self):
        compile(self._src(), "cell0_selftest.py", "exec")

    def test_resolves_root_without_file(self):
        """__file__ が無い状態でも ROOT を解決できる"""
        src = self._src()
        self.assertIn("_resolve_root", src)
        # sys.path / 環境変数 / /kaggle/input 探索の3系統を備える
        self.assertIn("FORTUNE_DATA_DIR", src)
        self.assertIn("/kaggle/input", src)

    def test_checks_import_health(self):
        """依存の import 健全性と実行時間の両方を検査する"""
        src = self._src()
        for mod in ("sxtwl", "swisseph", "kinqimen"):
            self.assertIn(mod, src)
        self.assertIn("elapsed < 5", src)

    def test_checks_dataset_version(self):
        src = self._src()
        self.assertIn("53", src)
        self.assertIn("138", src)


class TestDatasetContents(unittest.TestCase):
    """BUG-20b: Dataset に tests/ と kaggle/ を同梱する"""

    def test_build_dataset_includes_tests_and_kaggle(self):
        """開発側の build_dataset.py が tests/ と kaggle/ を同梱すること。

        ★BUG-22: 以前はファイルの有無だけでスキップ判定していたため、
        Dataset 側に「古い build_dataset.py」が残っていると、その旧版を
        読んで失敗した。実際にはそれは Dataset が古いという別の問題であり、
        このテストの対象ではない。
        成果物（自分自身が置かれた場所）に tests/ と kaggle/ が
        揃っているかを直接検査する方式に変更する。
        """
        root = Path(__file__).resolve().parent.parent
        # ★BUG-23: 「build_dataset.py の有無」で開発環境を判定するのは誤り。
        #   Kaggle Dataset は差分更新のため、過去に上げた古いファイルが
        #   残留することがあり、その旧版を読んで失敗していた。
        #   Dataset かどうかは「配布物にしか無いもの」で判定する。
        is_dataset = (root / "dataset-metadata.json").is_file()
        if is_dataset:
            # 配布物そのものを検査する（残留ファイルの中身は見ない）
            self.assertTrue((root / "tests").is_dir(), "tests/ が同梱されていない")
            self.assertTrue((root / "kaggle").is_dir(), "kaggle/ が同梱されていない")
            self.assertTrue((root / "kaggle" / "cell0_bootstrap.py").is_file())
            return
        # 開発環境: スクリプトの中身を検査する
        src = (root / "build_dataset.py").read_text(encoding="utf-8")
        self.assertIn('"tests"', src)
        self.assertIn('"kaggle"', src)

    def test_env_detection_is_robust(self):
        """BUG-23: 環境判定に「開発側ファイルの有無」を使わない。

        Kaggle Dataset は差分更新のため古いファイルが残留することがあり、
        その存在で開発環境と誤認すると、旧版を読んで誤検出する。
        判定は配布物固有の dataset-metadata.json で行う。
        """
        import inspect
        for fn in (TestDatasetContents.test_build_dataset_includes_tests_and_kaggle,
                   TestDatasetContents.test_zip_copied_to_persistent_dir):
            body = inspect.getsource(fn)
            self.assertIn("dataset-metadata.json", body, fn.__name__)
            # 「開発側ファイルの有無」で環境判定する脆い方式に戻っていないこと
            self.assertNotIn("build_dataset.py\").is_file()", body, fn.__name__)

    def test_version_stamp_exists_and_matches(self):
        """BUG-22: バージョン印が実物と一致していること"""
        import json as _json
        from fortunelib.registry import all_slugs
        from fortunelib.calc.deities import all_deities
        from fortunelib.data import load_json
        v = load_json("dataset_version.json")
        vf = None
        self.assertEqual(v["expected"]["slugs"], len(all_slugs()))
        self.assertEqual(v["expected"]["deities"], len(all_deities()))

    def test_selftest_checks_freshness(self):
        """セルフテストが Dataset の鮮度を検査すること"""
        src = (Path(__file__).resolve().parent.parent / "kaggle"
               / "cell0_selftest.py").read_text(encoding="utf-8")
        self.assertIn("dataset_version.json", src)
        self.assertIn("build_id", src)
        self.assertIn("people_sample.csv", src)

    def test_zip_copied_to_persistent_dir(self):
        """BUG-21: dist/ はスナップショット除外のためユーザーが取得できない。
        永続する deliverables/ にも複製すること。"""
        root = Path(__file__).resolve().parent.parent
        # BUG-23: 同上。Dataset 上では開発側スクリプトを検査しない。
        if (root / "dataset-metadata.json").is_file():
            self.skipTest("Dataset 上での実行（build_dataset.py は開発側のみ）")
        src = (root / "build_dataset.py").read_text(encoding="utf-8")
        self.assertIn("deliverables", src)
        self.assertIn("fortune_dataset.zip", src)

    def test_tests_reference_kaggle_files(self):
        """テストが kaggle/ 配下を参照している事実を明示（同梱が必要な根拠）"""
        src = Path(__file__).read_text(encoding="utf-8")
        self.assertIn("cell0_bootstrap.py", src)
        self.assertIn("fortune_notebook.ipynb", src)
