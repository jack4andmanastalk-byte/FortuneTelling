# -*- coding: utf-8 -*-
"""Kaggle Notebook のセル源（kaggle/cell*.py）を**実行の観点**で検査する。

背景（v1.0.0 公開前の実機 2 回目・2026-10-15）: Cell 0.1 から `import time` を消した結果、
疎通 OK の直後の `t0 = time.time()` が NameError になり、Save & Run が止まった。
`compile()` は構文しか見ないので、未定義名は見つからない。ここでは 2 段で塞ぐ。

  1. 静的検査: 4 セルを実行順に見て、使われる名前が「そのセルまでに束縛された名前」
     （import・代入・def・引数…）か組み込みかを確かめる（セルは同じ名前空間を共有する）。
  2. 実行検査: Cell 0.1 のソースを実際に exec して最後まで通す。ネットワーク（疎通）と
     1,100 件超のテスト実行だけ偽物に差し替える（それ以外は本物のコードが動く）。
"""
from __future__ import annotations

import ast
import builtins
import contextlib
import io
import os
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

PKG = Path(__file__).resolve().parent.parent
KAGGLE = PKG / "kaggle"
CELLS = ("cell0_bootstrap.py", "cell0_selftest.py",
         "cell1_csv_input.py", "cellN2_synthesis.py")
# Notebook 環境が用意する名前・モジュールの暗黙の名前
NOTEBOOK_NAMES = {"display", "get_ipython", "__name__", "__doc__", "__builtins__",
                  "__spec__", "__loader__", "__package__"}


def _bound_used_optional(tree: ast.AST):
    """(束縛される名前, 読まれる名前, globals().get("X") で任意参照される名前)。"""
    bound, used, optional = set(), set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                bound.add(node.id)
            else:
                used.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                if a.name != "*":
                    bound.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr == "get" and isinstance(node.func.value, ast.Call)
              and isinstance(node.func.value.func, ast.Name)
              and node.func.value.func.id == "globals" and node.args
              and isinstance(node.args[0], ast.Constant)
              and isinstance(node.args[0].value, str)):
            optional.add(node.args[0].value)       # globals().get("CTX") の形で守られた参照
    return bound, used, optional


class NotebookCellNamesTests(unittest.TestCase):
    """セル源に未定義名が無い（import を消した・名前を変えた、を実行前に捕まえる）。"""

    def test_every_used_name_is_bound_by_then(self):
        known = set(dir(builtins)) | NOTEBOOK_NAMES
        for name in CELLS:
            tree = ast.parse((KAGGLE / name).read_text(encoding="utf-8"), filename=name)
            bound, used, optional = _bound_used_optional(tree)
            undefined = used - bound - known - optional
            self.assertEqual(sorted(undefined), [],
                             f"{name}: このセルまでに束縛されていない名前があります "
                             f"（import 漏れ？）: {sorted(undefined)}")
            known |= bound

    def test_selftest_cell_imports_time_for_its_stopwatch(self):
        """回帰の固定: Cell 0.1 は time.time() でテスト時間を測るので import time が要る。"""
        src = (KAGGLE / "cell0_selftest.py").read_text(encoding="utf-8")
        self.assertTrue("time.time()" in src, "計時に time.time() を使う前提が変わった")
        self.assertTrue("\nimport time\n" in src, "Cell 0.1 に import time が無い")


class _FakeRunner:
    """unittest.TextTestRunner の代役。1,100 件超のテストは回さず、結果だけ返す。

    Cell 0.1 は「100 件超が 5 秒未満で終わる＝import 崩壊」と判定するので、
    本物らしく 5 秒だけ掛ける（time を偽装しない＝本物の time を使う経路を検査する）。
    """
    instances: list = []

    def __init__(self, *a, **k):
        _FakeRunner.instances.append(self)
        self.ran_suite = None

    def run(self, suite):
        self.ran_suite = suite
        time.sleep(5.2)
        n = _FakeRunner.tests_run
        return SimpleNamespace(testsRun=n, failures=[], errors=[], skipped=[],
                               wasSuccessful=lambda: True)


class SelftestCellExecTests(unittest.TestCase):
    """Cell 0.1 を exec して「✅ セルフテスト合格」まで通す（疎通とテスト実行だけ偽物）。"""

    @classmethod
    def setUpClass(cls):
        import json
        ver = json.loads((PKG / "data" / "dataset_version.json").read_text(encoding="utf-8"))
        cls.expected_tests = int(ver["expected"]["tests"])
        cls.src = (KAGGLE / "cell0_selftest.py").read_text(encoding="utf-8")

    def _run_cell(self, ping_result):
        from fortunelib import backend as B
        _FakeRunner.instances = []
        _FakeRunner.tests_run = self.expected_tests
        out = io.StringIO()
        env = {"FORTUNE_DATA_DIR": str(PKG / "data"), "GOOGLE_API_KEY": "dummy-for-exec-test"}
        ns = {"__name__": "__selftest_cell__"}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(B, "ping_gemini", lambda *a, **k: ping_result), \
                mock.patch.object(unittest.TestLoader, "discover",
                                  lambda self, *a, **k: unittest.TestSuite()), \
                mock.patch.object(unittest, "TextTestRunner", _FakeRunner), \
                contextlib.redirect_stdout(out):
            code = None
            try:
                exec(compile(self.src, "cell0_selftest.py", "exec"), ns)
            except SystemExit as e:  # セルの _selftest_fail
                code = e.code
        return code, out.getvalue(), ns

    def test_cell_runs_to_the_end_when_ping_is_ok(self):
        from fortunelib import backend as B
        ok = B.PingResult("ok", model="gemini-3.5-flash-lite", reply="API OK", seconds=1.2)
        ok.tried = [("gemini-3.1-flash-lite", "混雑: 503"), ("gemini-3.5-flash-lite", "OK")]
        code, out, ns = self._run_cell(ok)
        self.assertIsNone(code, f"SystemExit({code}) で止まった:\n{out[-2000:]}")
        self.assertIn("✅ Gemini API 疎通 OK（model=gemini-3.5-flash-lite", out)
        self.assertIn("gemini-3.1-flash-lite は混雑中", out)
        self.assertIn(f"期待テスト数: {self.expected_tests}", out)
        self.assertIn(f"テスト {self.expected_tests} 件", out)
        self.assertIn("✅ セルフテスト合格", out)
        self.assertEqual(len(_FakeRunner.instances), 1, "テストランナーを 1 回だけ起動する")
        self.assertGreaterEqual(ns["elapsed"], 5.0, "計時（time.time）が動いている")

    def test_cell_stops_before_tests_when_all_models_are_congested(self):
        from fortunelib import backend as B
        busy = B.PingResult("congested", error="全部混雑")
        busy.tried = [(m, "混雑: 503") for m in B.PING_MODELS]
        code, out, _ns = self._run_cell(busy)
        self.assertEqual(code, 1)
        self.assertIn("Gemini 側の一時的な混雑で、API キー・Dataset・Notebook は正常です", out)
        self.assertEqual(_FakeRunner.instances, [], "混雑で止まるときはテストを回さない")


if __name__ == "__main__":
    unittest.main()
