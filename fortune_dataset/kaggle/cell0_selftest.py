# ============================================================
# Cell 0.1: セルフテスト（CI相当）
# ------------------------------------------------------------
# Add Input した Dataset に対してユニットテストを実行する。
# GPU は不要（約1分＋API疎通1回）。Cell 0（ブートストラップ）の後に実行すること。
#
# 目的:
#   1. Dataset のアップロード漏れ・バージョン取り違えを即座に検出する
#   2. 依存パッケージの導入失敗を検出する
#      （import に失敗するとテストが「0.2秒で大量エラー」になる既知の罠）
#   3. Gemini API への疎通（APIキー・モデル名・レート制限）を確認する
#
# ここで失敗したら、以降のセル（本番実行・約20〜30分）は流さないこと。
# ============================================================
import os
import sys
import time
import unittest
from pathlib import Path

# --- ROOT の解決 --------------------------------------------
# ★BUG-20: ノートブックのセルには __file__ が存在しないため、
#   以前の実装は NameError で即死していた。
#   Cell 0 が確定させた情報（sys.path / FORTUNE_DATA_DIR）を第一に使い、
#   無ければ /kaggle/input を再帰探索する（Dataset の階層は環境で変わる）。
def _is_valid(b):
    b = Path(b)
    return (b / "fortunelib" / "__init__.py").is_file() and (b / "data").is_dir()


def _resolve_root():
    # 1) Cell 0 が sys.path に入れた場所
    for p in sys.path:
        if p and _is_valid(p):
            return Path(p)
    # 2) Cell 0 が設定した FORTUNE_DATA_DIR の親
    dd = os.environ.get("FORTUNE_DATA_DIR")
    if dd and _is_valid(Path(dd).parent):
        return Path(dd).parent
    # 3) 定番の場所
    for p in (Path("/kaggle/working"), Path.cwd(), *Path.cwd().parents):
        if _is_valid(p):
            return Path(p)
    # 4) /kaggle/input を再帰探索（深さ優先・浅いものを採用）
    inp = Path("/kaggle/input")
    if inp.exists():
        found, stack = [], [(inp, 0)]
        while stack:
            cur, d = stack.pop()
            if d > 6:
                continue
            try:
                for c in sorted(cur.iterdir()):
                    if not c.is_dir():
                        continue
                    if _is_valid(c):
                        found.append((d + 1, c))
                    else:
                        stack.append((c, d + 1))
            except PermissionError:
                continue
        if found:
            found.sort(key=lambda x: x[0])
            return found[0][1]
    return None


def _selftest_fail(message, details=""):
    """セルフテストを停止する（以降のセルを流さないため SystemExit）。"""
    if details:
        print(details)
    raise SystemExit(1)


ROOT = _resolve_root()
if ROOT is None:
    print("❌ fortunelib が見つかりません。先に Cell 0 を実行し、")
    print("   Add Input で Dataset を追加しているか確認してください。")
    _selftest_fail("fortunelib が見つかりません。Dataset と Add Input を確認してください。")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("FORTUNE_DATA_DIR", str(ROOT / "data"))
print(f"ROOT: {ROOT}")

# --- テストディレクトリの確認 --------------------------------
TESTS = ROOT / "tests"
if not TESTS.is_dir():
    print(f"⚠ tests/ が Dataset に含まれていません（{TESTS}）")
    print("  build_dataset.py に tests を含めて再アップロードすると")
    print("  このセルで回帰検査ができます。以降のセルは実行可能です。")
    raise SystemExit(0)

# --- 1. 依存パッケージの健全性 -------------------------------
# ★ここが肝。import に失敗したままテストを走らせると、
#   「0.2秒で全部エラー」という偽の失敗になり原因を見失う。
REQUIRED = ["sxtwl", "swisseph", "kinqimen", "lunar_python", "ephem",
            "google.genai"]
missing = []
for mod in REQUIRED:
    try:
        __import__(mod)
    except ImportError:
        missing.append(mod)
if missing:
    print(f"❌ 依存パッケージが未導入: {missing}")
    print("   → Cell 0（ブートストラップ）を先に実行してください。")
    print('   pip install sxtwl pyswisseph iztro-py divicast lunar_python "ephem==4.2.1"')
    print("   pip install --no-deps kinqimen")
    print("   pip install google-genai   ← Gemini API 用")
    _selftest_fail(f"依存パッケージが未導入: {missing}")
print(f"✅ 依存パッケージ {len(REQUIRED)} 件 OK")

# --- 1b. Gemini API 疎通（軽量モデルで 1〜3 リクエスト）--------------
# ★ 本番（約67呼び出し）の前に、キー・モデル名・レート制限を少ない呼び出しで
#   検証しておく。上位 flash（gemini-3.8-flash・日次20回枠を仮定）を疎通で消費
#   しないよう、枠に余裕のある軽量モデルを使う。
# ★ v1.0.0（2026-10-15 実機）: 疎通専用だった gemini-3.1-flash-lite が Gemini 側の
#   混雑（503 "high demand"）を 3 回連続で返し、ここで止まって本番に進めなかった。
#   503/408 はキー・Dataset・Notebook の異常ではない（キー不正は 400/403、モデル名
#   違いは 404、日次枠切れは 429）。本番の MTS が混雑モデルを別モデルへ移譲するのと
#   同じ思想で、疎通も軽量モデル 3 本（backend.PING_MODELS）を順に試す。
#   判定ロジックは fortunelib.backend.ping_gemini（単体テストあり）に置く。
from fortunelib.backend import PING_MODELS, ping_gemini  # noqa: E402
_ping = ping_gemini()
if _ping.status == "no_key":
    print("⚠ GOOGLE_API_KEY が未設定のため API 疎通検査をスキップします")
    print("   （本番には必須です。Cell 0 の表示に従って Secrets を登録してください）")
elif _ping.ok:
    print(f"✅ Gemini API 疎通 OK（model={_ping.model}・"
          f"{_ping.seconds:.1f}秒・応答: {_ping.reply[:20]}）")
    if len(_ping.tried) > 1:
        _busy = "・".join(m for m, _r in _ping.tried[:-1])
        print(f"   ※ {_busy} は混雑中（503/408）でした。本番では混雑したモデルを"
              "自動で別モデルへ移譲しますが、混雑が続くと所要時間が延びます")
    print("   ※ MTS実行では各段階の担当モデル（3.1-lite/3.5-lite/3.8-flash/3.6-flash/3-flash-preview）が並列稼働します")
elif _ping.status == "empty":
    print(f"❌ Gemini API が空の応答を返しました（model={_ping.model}）")
    print("   考えられる原因:")
    print("   ・セーフティフィルタ（プロンプトを見直す）")
    print("   ・thinkingトークンが出力枠を使い切った")
    print("      可能性 → このログを開発側に報告してください")
elif _ping.status == "congested":
    print("❌ Gemini API が混雑しています（503/408）。本番セルは実行しないでください:")
    print(f"   軽量モデル {len(PING_MODELS)} 本（{'・'.join(PING_MODELS)}）がすべて混雑でした。")
    print("   これは Gemini 側の一時的な混雑で、API キー・Dataset・Notebook は正常です")
    print("   （キー不正なら 400/403、モデル名違いなら 404、日次枠切れなら 429 になります）。")
    print("   対処: 30〜60 分ほど待ってから、Cell 0 からやり直してください。")
    for _m, _r in _ping.tried:
        print(f"     - {_m}: {_r}")
else:
    print("❌ Gemini API 疎通に失敗しました。本番セルは実行しないでください:")
    print("  ", _ping.error)
# SystemExit は except ブロックの外で上げる（例外の連鎖で IPython の表示が崩れないように）
if _ping.status == "empty":
    _selftest_fail("Gemini API が空の応答を返しました")
elif _ping.status == "congested":
    _selftest_fail("Gemini API が混雑中（503/408）のため中断しました。時間をおいて再実行してください")
elif _ping.status == "fatal":
    _selftest_fail("Gemini API 疎通に失敗しました")

# --- 2. Dataset の中身が期待どおりか --------------------------
from fortunelib.registry import all_slugs                      # noqa: E402
from fortunelib.calc.deities import all_deities                # noqa: E402
from fortunelib.tone import TONE_DEFS                          # noqa: E402

n_slugs, n_deities = len(all_slugs()), len(all_deities())
n_tones = len(TONE_DEFS)
print(f"   占術数: {n_slugs} / 神格: {n_deities}柱 / トーン: {n_tones}種")
problems = []
if n_slugs != 53:
    problems.append(f"占術数が {n_slugs}（期待 53）")
if n_deities != 138:
    problems.append(f"神格数が {n_deities}（期待 138）")
# mts5.65: トーンの数は**版の印（dataset_version.json の expected.tones）を正本**にする
# （obaa の削除などでトーンを増減しても、Notebook 側の書き換えが要らないように）。
# 印が無い古い Dataset では、この版の実数（3＝standard/easy/spiritual）を期待値にする。
_TONES_DEFAULT = 3
# --- 2b. バージョン印との照合（古い Dataset の検出）-------------
# ★BUG-22: Dataset を更新せずに実行すると、古いコードで本番が走ってしまう。
#   テストの合否より前に、Dataset の鮮度そのものを検査する。
import json as _json                                            # noqa: E402
_expected_tests = None          # mts5.52: expected.tests を「実行件数」と突合する
vf = ROOT / "data" / "dataset_version.json"
if not vf.is_file():
    problems.append("dataset_version.json が無い（Dataset が古い可能性）")
else:
    v = _json.loads(vf.read_text(encoding="utf-8"))
    print(f"   build_id: {v.get('build_id', '?')}")
    exp = v.get("expected", {})
    if exp.get("slugs") != n_slugs:
        problems.append(f"占術数が印と不一致（印{exp.get('slugs')}／実{n_slugs}）")
    if exp.get("deities") != n_deities:
        problems.append(
            f"神格数が印と不一致（印{exp.get('deities')}／実{n_deities}）")
    _exp_tones = int(exp.get("tones", _TONES_DEFAULT))
    if _exp_tones != n_tones:
        problems.append(f"トーン数が印と不一致（印{_exp_tones}／実{n_tones}）")
    # mts5.52（F-5）: 期待テスト数（dataset_version.json の expected.tests）を控えておき、
    # 実行後の件数と突合する。従来は**どのコードもこの値を読んでおらず**、
    # テストが減っていても「実行できた分が全部成功」なら合格していた。
    _expected_tests = exp.get("tests")
    if isinstance(_expected_tests, int):
        print(f"   期待テスト数: {_expected_tests}（実行後に件数を照合します）")
    # 入力は people_sample.csv のみ（cell1_input のハードコードは廃止）。
    # CSV が同梱されていることを確認する。
    csv_path = ROOT / "kaggle" / "people_sample.csv"
    if not csv_path.is_file():
        problems.append("people_sample.csv が Dataset に含まれていません")

if problems:
    print("❌ Dataset が最新版ではない可能性があります:")
    for x in problems:
        print(f"   - {x}")
    print("   → build_dataset.py --zip で作り直し、Dataset を更新（New Version）し、")
    print("     ノートブックの Add Input を最新バージョンに切り替えてください。")
    _selftest_fail("Dataset のバージョン／内容の照合に失敗しました", "\\n".join(problems))

# --- 3. ユニットテスト --------------------------------------
t0 = time.time()
suite = unittest.TestLoader().discover(str(TESTS), top_level_dir=str(ROOT))
result = unittest.TextTestRunner(verbosity=1).run(suite)
elapsed = time.time() - t0

n = result.testsRun
print("\n" + "=" * 56)
print(f"テスト {n} 件 / {elapsed:.1f}秒 "
      f"（失敗 {len(result.failures)} / エラー {len(result.errors)}）")

# mts5.54: テストが積んだ警告を**ここで消す**。
# 実機（mts5.53）では、テストが製品コードを呼ぶため「⚠ 画像を埋め込めなかった占術: …」などの
# 警告が台帳（fortunelib.runcheck）に残り、**本番セル（Cell 1・N2）の警告に混ざる**状態でした
# （`RUN_STRICT=1` なら本番セルがテスト由来の警告で不合格になってしまう）。セルごとに独立させます。
try:
    from fortunelib.runcheck import clear as _warn_clear
    _warn_clear()
    print("※ 警告台帳をリセットしました（テスト由来の警告を本番セルへ持ち越しません）")
except Exception:
    pass

# 0.2秒台で終わるのは import 崩壊のサイン（実行時間そのものを検査する）
if n > 100 and elapsed < 5:
    print("❌ 実行が速すぎます。import 崩壊の可能性が高いです")
    _selftest_fail("セルフテストの実行が速すぎます（import 崩壊の可能性）")

# mts5.52（F-5）: 実行件数が期待値に足りなければ不合格（テストが黙って減る事故の防止）
if isinstance(_expected_tests, int) and n < _expected_tests:
    print(f"❌ テスト実行数が期待より少ない: 実行 {n} < 期待 {_expected_tests}")
    print("   → Dataset の tests/ が古い（テストが減った）可能性があります。")
    print("      build_dataset_zip.py で作り直し、Dataset を New Version に更新してください。")
    _selftest_fail(
        f"セルフテストの実行件数が期待値に足りません（実行 {n} / 期待 {_expected_tests}）",
        "tests/ の不足・収集エラーの可能性。Dataset を作り直してください。")

if not result.wasSuccessful():
    print("❌ テスト失敗。本番セルは実行しないでください")
    _selftest_fail(
        f"セルフテスト失敗: failures={len(result.failures)}, errors={len(result.errors)}",
        "\\n".join(str(x[0]) for x in result.failures + result.errors)[:4000],
    )

print("✅ セルフテスト合格。以降のセルを実行して問題ありません")
print("=" * 56)
