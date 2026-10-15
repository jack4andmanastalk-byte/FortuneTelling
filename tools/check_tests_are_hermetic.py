# -*- coding: utf-8 -*-
"""Kaggle の実機（Secrets にキーがあり、CWD から画像が見つかる）を模して、
**テストが環境に依存していない**ことを確かめる。

背景: 過去にセルフテストが Kaggle だけで失敗したことがある。原因は 2 つとも
「テストが環境に依存していた」こと＝(1) 環境の API キーの有無で結果が変わる、
(2) CWD から `assets/images` が見つかるかどうかで結果が変わる。
この道具は**同じ状況をローカルで再現**し、テスト側の問題と製品側の問題を切り分ける。

    python3 tools/check_tests_are_hermetic.py [--all]

やること:
  1. [キーの制御] `fortunelib.backend._resolve_gemini_api_key` を「キーがある」状態にし、
     `google.genai` を**ネットワークへ出たら必ず失敗する偽物**に差し替えて、API に触れる
     テスト群を実行する → 期待 **0 件失敗**（本物の API を呼ぼうとすれば必ず落ちる）。
     既定は代表的なモジュールのみ、`--all` で tests/ 全体。
  2. [画像探索の制御] 一時ディレクトリに `assets/images/M27_tarot` を置いて CWD をそこへ移し、
     画像探索に関わるテストを走らせる → 期待 **0 件失敗**。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "fortune_dataset"

#: API キーの解決・バックエンド・Kaggle セルに触れる代表的なテスト（既定の対象）
KEY_SENSITIVE_TESTS = (
    "tests/test_merged_integration.py",
    "tests/test_model_migration.py",
    "tests/test_guards.py",
    "tests/test_batch.py",
    "tests/test_intro_video.py",
    "tests/test_notebook_sync.py",
)


def _dedent4(text: str) -> str:
    """4スペースぶんの共通インデントを外す（`textwrap.dedent` は空行の扱いで揺れるため自前で）。"""
    return "\n".join(l[4:] if l.startswith("    ") else l for l in text.splitlines())


DRIVER = _dedent4('''
    import json, os, sys, types, unittest
    from pathlib import Path
    sys.path.insert(0, {pkg!r})
    sys.path.insert(0, {root!r})

    from fortunelib import backend as B
    os.environ["GOOGLE_API_KEY"] = "AQ.fake-kaggle-secret"          # Kaggle 相当（Secrets にキー）

    # --- google-genai の偽物（ネットワークへ出ようとしたら必ず失敗する） ---
    class _Models:
        def generate_content(self, *a, **k):
            raise RuntimeError("TEST CALLED THE REAL API (generate_content)")
        def list(self, *a, **k):
            raise RuntimeError("TEST CALLED THE REAL API (models.list)")
    class _Client:
        def __init__(self, api_key=None, **k):
            if not api_key:
                raise ValueError("No API key was provided.")      # 本物と同じ挙動
            self.models = _Models()
    try:
        import google.genai as _genai                       # 本物があれば Client だけ差し替える
        _genai.Client = _Client
    except Exception:                                       # 無ければ最小限の偽モジュール
        tmod = types.ModuleType("google.genai.types")
        for _name in ("GenerateContentConfig", "ThinkingConfig", "HttpOptions"):
            setattr(tmod, _name, type(_name, (), {{"__init__": lambda self, **k: self.__dict__.update(k)}}))
        emod = types.ModuleType("google.genai.errors")
        class APIError(Exception):
            def __init__(self, code=0, message="", *a, **k):
                super().__init__(message); self.code = code; self.message = message
        class ClientError(APIError): pass
        class ServerError(APIError): pass
        emod.APIError, emod.ClientError, emod.ServerError = APIError, ClientError, ServerError
        mod = types.ModuleType("google.genai"); mod.Client = _Client; mod.types = tmod; mod.errors = emod
        pkg = types.ModuleType("google"); pkg.genai = mod
        sys.modules["google"], sys.modules["google.genai"] = pkg, mod
        sys.modules["google.genai.types"], sys.modules["google.genai.errors"] = tmod, emod

    files = sys.argv[1:]
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    for f in files:
        suite.addTests(loader.discover(str(Path(f).parent), pattern=Path(f).name,
                                       top_level_dir={pkg!r}))
    res = unittest.TextTestRunner(verbosity=1).run(suite)
    txt = "".join(m for _t, m in (res.failures + res.errors))
    for t, m in (res.failures + res.errors):
        print("FAILED-TEST:", t.id(), "|", m.strip().splitlines()[-1][:200])
    print(json.dumps({{"run": res.testsRun, "failures": len(res.failures) + len(res.errors),
                      "called_real_api": "TEST CALLED THE REAL API" in txt,
                      "key_after": B._resolve_gemini_api_key()}}))
''')


def key_control(all_tests: bool) -> dict:
    """キーがある環境でテストを走らせ、本物の API に触れず 0 件失敗であることを確かめる。"""
    if all_tests:
        files = sorted(str(p) for p in (PKG / "tests").glob("test_*.py"))
    else:
        files = [str(PKG / rel) for rel in KEY_SENSITIVE_TESTS if (PKG / rel).is_file()]
    code = DRIVER.format(pkg=str(PKG), root=str(ROOT))
    compile(code, "<driver>", "exec")            # 生成したコードの構文をここで確かめる
    out = subprocess.run([sys.executable, "-c", code, *files],
                         capture_output=True, text=True, cwd=str(PKG))
    line = [l for l in out.stdout.splitlines() if l.startswith("{")]
    if not line:
        print(out.stdout[-2000:], out.stderr[-2000:])
        raise SystemExit("ドライバが結果を返しませんでした")
    d = json.loads(line[-1])
    d["files"] = len(files)
    d["failed_tests"] = [l[len("FAILED-TEST: "):] for l in out.stdout.splitlines()
                         if l.startswith("FAILED-TEST: ")]
    return d


def discovery_control() -> dict:
    """「画像が CWD から見つかる」Kaggle 相当の環境でも、テストが通ることを確かめる。

    `build_html` には画像ディレクトリの自動探索（候補に `Path("assets/images")` があり、
    Kaggle では `/kaggle/input/**/assets/images` も走査する）があるため、
    「画像を拾わない」前提のテストは実機でだけ落ちる。ここでは一時ディレクトリに
    `assets/images/M27_tarot` を置いて CWD をそこへ移し、同じテストを走らせる。
    """
    test_file = PKG / "tests" / "test_guards.py"
    deck = PKG / "assets" / "images" / "M27_tarot"
    if not test_file.is_file() or not deck.is_dir():
        return {"skipped": True, "reason": "テストまたは納品画像が無い"}
    tmp = Path(tempfile.mkdtemp())
    target = tmp / "assets" / "images" / "M27_tarot"
    target.mkdir(parents=True)
    files = sorted(f for f in deck.iterdir() if f.is_file())[:3]
    for f in files:
        shutil.copy(f, target / f.name)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(PKG), str(ROOT)])
    out = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(PKG / "tests"),
         "-t", str(PKG), "-p", test_file.name],
        capture_output=True, text=True, cwd=str(tmp), env=env)
    tail = (out.stderr or out.stdout).strip().splitlines()
    ran = next((l for l in reversed(tail) if l.startswith("Ran ")), "")
    failures = sum(1 for l in tail if l.startswith(("FAIL:", "ERROR:")))
    shutil.rmtree(tmp, ignore_errors=True)
    return {"ran": ran, "failures": failures, "returncode": out.returncode,
            "tail": tail[-1] if tail else ""}


def main() -> int:
    all_tests = "--all" in sys.argv[1:]
    k = key_control(all_tests)
    print(f"[キーの制御] キーあり・偽 google.genai で {k['files']} ファイルを実行: "
          f"実行 {k['run']} / 失敗 {k['failures']} 件 / 本物のAPIを呼んだ {k['called_real_api']}"
          f" / 実行後のキー解決 = {k['key_after']}")
    ok1 = k["failures"] == 0 and not k["called_real_api"] and k["key_after"] == "AQ.fake-kaggle-secret"
    print("   判定:", "OK（キーの有無に依存していない）" if ok1 else
          "NG（テストがキーに依存＝Kaggle で落ちる可能性）")
    for t in k.get("failed_tests", []):
        print("     -", t)

    d = discovery_control()
    if d.get("skipped"):
        print(f"\n[画像探索の制御] スキップ（{d.get('reason')}）")
        ok2 = True
    else:
        print(f"\n[画像探索の制御] CWD に assets/images を置いて実行（Kaggle 相当）: "
              f"{d['ran']} / 失敗 {d['failures']} 件 → {d['tail']}")
        ok2 = d["failures"] == 0 and d["returncode"] == 0
        print("   判定:", "OK（環境に依存していない）" if ok2 else
              "NG（テストが環境依存＝Kaggle で落ちる可能性）")
    print("\n=== 総合判定:", "OK" if (ok1 and ok2) else "NG")
    return 0 if (ok1 and ok2) else 1


if __name__ == "__main__":
    raise SystemExit(main())
