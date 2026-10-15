# -*- coding: utf-8 -*-
"""Cell 0.1 の Gemini API 疎通（fortunelib.backend.ping_gemini）の回帰テスト。

背景（v1.0.0 公開前の実機・2026-10-15）: 疎通専用だった gemini-3.1-flash-lite が
Gemini 側の混雑（503 "high demand"）を 3 回連続で返し、セルフテストが止まって本番に
進めなかった。本番の MTS は混雑したモデルを別モデルへ移譲するのに、疎通だけが
1 モデルで諦めていた。疎通も軽量モデルを順に試し、**混雑と致命エラーを区別**する。

ネットワークには出ない（偽のバックエンドを factory で注入する）。
"""
from __future__ import annotations

import os
import re
import unittest
from pathlib import Path
from unittest import mock

from fortunelib import backend as B

PKG = Path(__file__).resolve().parent.parent
SELFTEST = PKG / "kaggle" / "cell0_selftest.py"

CONGESTED_503 = ("Gemini API が混雑しています（503）。1回待っても回復しなかったため、"
                 "このモデルでは諦めます（別モデルへ移譲）。\n（詳細: 503 UNAVAILABLE. "
                 "{'error': {'code': 503, 'message': 'This model is currently experiencing "
                 "high demand. Spikes in demand are usually temporary.', "
                 "'status': 'UNAVAILABLE'}}）")
CONGESTED_408 = ("Gemini API が混雑しています（408）。1回待っても回復しなかったため、"
                 "このモデルでは諦めます（別モデルへ移譲）。\n（詳細: 408 Request Timeout）")
FATAL_400 = ("Gemini API がリクエストを拒否しました（400）。\n"
             "（詳細: 400 INVALID_ARGUMENT. API key not valid. Please pass a valid API key.）")
DAILY_429 = ("Gemini API の無料枠（1日あたりのリクエスト上限）を使い切りました。\n"
             "対処: 翌日にこのノートブックを再実行してください。")


class _FakeBackend:
    """generate() が台本どおりに返す/投げる偽バックエンド。"""

    def __init__(self, model: str, script: dict):
        self.model_name = model
        self.resolved_model_name = model
        self.script = script
        self.calls = 0

    def generate(self, system_prompt, user_prompt, temperature=0.7, max_tokens=1000,
                 seed=None):
        self.calls += 1
        action = self.script[self.model_name]
        if isinstance(action, BaseException):
            raise action
        return action


def _factory(script: dict, made: list):
    def make(model: str):
        be = _FakeBackend(model, script)
        made.append(be)
        return be
    return make


class IsCongestionErrorTests(unittest.TestCase):
    def test_giveup_message_503_and_408(self):
        self.assertTrue(B.is_congestion_error(RuntimeError(CONGESTED_503)))
        self.assertTrue(B.is_congestion_error(RuntimeError(CONGESTED_408)))

    def test_cause_code_503(self):
        class _Srv(Exception):
            code = 503
        err = RuntimeError("なにか")
        err.__cause__ = _Srv("boom")
        self.assertTrue(B.is_congestion_error(err))

    def test_response_timeout_is_congestion(self):
        self.assertTrue(B.is_congestion_error(B.ResponseTimeoutError("打ち切り")))

    def test_fatal_and_daily_quota_are_not_congestion(self):
        self.assertFalse(B.is_congestion_error(RuntimeError(FATAL_400)))
        self.assertFalse(B.is_congestion_error(RuntimeError(DAILY_429)))
        self.assertFalse(B.is_congestion_error(ValueError("other")))


class PingGeminiTests(unittest.TestCase):
    def test_first_model_congested_second_answers(self):
        made: list = []
        logs: list = []
        script = {"gemini-3.1-flash-lite": RuntimeError(CONGESTED_503),
                  "gemini-3.5-flash-lite": "API OK",
                  "gemini-3-flash-preview": "API OK"}
        res = B.ping_gemini(api_key="k", backend_factory=_factory(script, made),
                            log=logs.append)
        self.assertTrue(res.ok)
        self.assertEqual(res.status, "ok")
        self.assertEqual(res.model, "gemini-3.5-flash-lite")
        self.assertEqual(res.reply, "API OK")
        self.assertEqual([m for m, _r in res.tried],
                         ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite"])
        self.assertEqual(len(made), 2, "3 本目は呼ばない（成功したら止まる）")
        self.assertTrue(any("混雑中" in l for l in logs))

    def test_all_congested(self):
        made: list = []
        script = {m: RuntimeError(CONGESTED_503 if i != 1 else CONGESTED_408)
                  for i, m in enumerate(B.PING_MODELS)}
        res = B.ping_gemini(api_key="k", backend_factory=_factory(script, made),
                            log=lambda *_a: None)
        self.assertFalse(res.ok)
        self.assertEqual(res.status, "congested")
        self.assertEqual(len(res.tried), len(B.PING_MODELS))
        self.assertIn("混雑", res.error)
        self.assertIn("API キー・Dataset・Notebook は正常", res.error)

    def test_fatal_error_stops_immediately(self):
        """キー不正（400）などは別モデルでも直らない → その場で fatal（無駄打ちしない）。"""
        made: list = []
        script = {"gemini-3.1-flash-lite": RuntimeError(FATAL_400),
                  "gemini-3.5-flash-lite": "API OK",
                  "gemini-3-flash-preview": "API OK"}
        res = B.ping_gemini(api_key="k", backend_factory=_factory(script, made),
                            log=lambda *_a: None)
        self.assertEqual(res.status, "fatal")
        self.assertIn("400", res.error)
        self.assertEqual(len(made), 1)

    def test_daily_quota_is_fatal_not_congestion(self):
        made: list = []
        script = {m: RuntimeError(DAILY_429) for m in B.PING_MODELS}
        res = B.ping_gemini(api_key="k", backend_factory=_factory(script, made),
                            log=lambda *_a: None)
        self.assertEqual(res.status, "fatal")
        self.assertEqual(len(made), 1)

    def test_empty_reply(self):
        made: list = []
        script = {"gemini-3.1-flash-lite": "   "}
        res = B.ping_gemini(api_key="k", models=("gemini-3.1-flash-lite",),
                            backend_factory=_factory(script, made), log=lambda *_a: None)
        self.assertEqual(res.status, "empty")
        self.assertEqual(res.model, "gemini-3.1-flash-lite")

    def test_no_key(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "KAGGLE_SECRET_GOOGLE_API_KEY")}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.dict("sys.modules", {"kaggle_secrets": None}):
            res = B.ping_gemini(backend_factory=lambda m: self.fail("キー無しで生成してはいけない"))
        self.assertEqual(res.status, "no_key")
        self.assertFalse(res.ok)

    def test_never_raises_even_on_unexpected_exception(self):
        made: list = []
        script = {"gemini-3.1-flash-lite": ValueError("unexpected")}
        res = B.ping_gemini(api_key="k", models=("gemini-3.1-flash-lite",),
                            backend_factory=_factory(script, made), log=lambda *_a: None)
        self.assertEqual(res.status, "fatal")
        self.assertIn("unexpected", res.error)

    def test_default_factory_is_a_short_tempered_gemini_backend(self):
        """既定の factory は GeminiBackend（RPM 60・max_retries 2・verbose False）。
        generate をクラス側で差し替え、ネットワークには出ない。"""
        seen: list = []

        def fake_generate(self, system_prompt, user_prompt, temperature=0.7,
                          max_tokens=1000, seed=None):
            seen.append(self)
            raise RuntimeError(CONGESTED_503)

        with mock.patch.object(B.GeminiBackend, "generate", fake_generate):
            res = B.ping_gemini(api_key="k", models=("gemini-3.1-flash-lite",),
                                log=lambda *_a: None)
        self.assertEqual(res.status, "congested")
        self.assertEqual(len(seen), 1)
        be = seen[0]
        self.assertIsInstance(be, B.GeminiBackend)
        self.assertEqual(be.model_name, "gemini-3.1-flash-lite")
        self.assertEqual(be.max_retries, 2)
        self.assertEqual(be.requests_per_minute, 60.0)
        self.assertFalse(be.verbose)

    def test_ping_models_are_lightweight_and_not_deprecated(self):
        """疎通は上位 flash（日次枠が小さい）を使わない。非推奨 ID も使わない。"""
        for m in B.PING_MODELS:
            self.assertNotIn(m, B.DEPRECATED_MODELS)
            self.assertNotEqual(m, B.GeminiBackend.DEFAULT_MODEL)
        self.assertEqual(B.PING_MODELS[0], "gemini-3.1-flash-lite", "従来の疎通モデルを先頭に残す")
        self.assertEqual(len(B.PING_MODELS), len(set(B.PING_MODELS)))


class SelftestCellUsesPingTests(unittest.TestCase):
    """Cell 0.1 のソースが ping_gemini を使い、混雑を致命エラーと区別して案内すること。"""

    def _src(self) -> str:
        return SELFTEST.read_text(encoding="utf-8")

    def test_cell_calls_ping_gemini(self):
        src = self._src()
        self.assertIn("ping_gemini()", src)
        self.assertNotIn("_test_model", src, "旧・単一モデルの疎通コードが残っている")
        self.assertIn("congested", src)
        self.assertIn("API キー・Dataset・Notebook は正常", src)

    def test_system_exit_is_raised_outside_except(self):
        """SystemExit を except の中で上げない（例外連鎖で IPython の表示が崩れる・実機で確認）。"""
        src = self._src()
        block = src[src.index("# --- 1b."):src.index("# --- 2.")]
        self.assertNotIn("except RuntimeError", block)
        # _selftest_fail の呼び出し行はすべて if/elif の直下（except 節の中ではない）
        for m in re.finditer(r"^(\s*)_selftest_fail\(", block, flags=re.M):
            self.assertEqual(len(m.group(1)), 4, m.group(0))

    def test_cell_compiles(self):
        compile(self._src(), "cell0_selftest.py", "exec")


if __name__ == "__main__":
    unittest.main()
