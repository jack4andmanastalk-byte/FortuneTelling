# ============================================================
# Cell 0: ブートストラップ（環境設定・Gemini API バックエンド）
# ※ 初回実行は1〜3分です（計算ライブラリ導入のみ。モデルのダウンロードは無し）
# ============================================================
# ★ 2026-08-26 Gemini API（Flash系・無料枠）へ完全移行した。
#   - GPU アクセラレータは「None（CPU）」でOK（T4枠を消費しない）
#   - HF_TOKEN は不要 → GOOGLE_API_KEY（Kaggle Secrets）が必要
#   - ローカルモデルのロード・ダウンロードがなく、全体が軽量
import importlib.util
import json
import os
import sys
from pathlib import Path

# ============================================================
# STEP 1: 依存ライブラリの導入（すべて import より前に完了させる）
# ============================================================
# 存在確認は find_spec（モジュールをロードしない・安全）
_pip_targets = []  # 後で一括インストールする

# --- 占術計算ライブラリ ---
_calc_libs = {
    "sxtwl": "sxtwl",               # 暦（四柱・節気）
    "swisseph": "pyswisseph",       # 占星術・HD・真太陽時（import名≠pip名）
    "iztro_py": "iztro-py",         # 紫微斗数
    "divicast": "divicast",         # 六爻
    "ephem": "ephem",               # 奇門（kinqimen依存）
    "kinqimen": None,               # 奇門（--no-deps で別途）
    "lunar_python": "lunar_python", # 算命学
    "geopy": "geopy",               # HD（都市→座標）
    "timezonefinder": "timezonefinder",
    "pytz": "pytz",
}
for _mod, _pip in _calc_libs.items():
    if importlib.util.find_spec(_mod) is None:
        if _pip:
            _pip_targets.append(_pip)
        print("  不足:", _mod, "→ pip:", _pip)
if _pip_targets:
    print("ライブラリ導入:", _pip_targets)
    os.system("pip install -q " + " ".join(_pip_targets))
if importlib.util.find_spec("kinqimen") is None:
    print("  不足: kinqimen → pip (--no-deps)")
    os.system("pip install -q --no-deps kinqimen")

# --- Gemini API SDK（google-genai）---
# ★ pip名は google-genai・import名は google.genai（find_spec で判定）
if importlib.util.find_spec("google.genai") is None:
    print("  不足: google.genai → pip: google-genai")
    os.system("pip install -q google-genai")

# ============================================================
# STEP 2: fortunelib の読込（自動検出版・再帰）
# ============================================================
def _find_fortunelib(input_root="/kaggle/input", working_root="/kaggle/working",
                     max_depth=6):
    """fortunelib を含むベースディレクトリを探す（再帰・深さ制限付き）。"""
    def is_valid(base):
        b = Path(base)
        return ((b / "fortunelib" / "__init__.py").is_file()
                and (b / "data").is_dir())

    w = Path(working_root)
    if w.exists() and is_valid(w):
        return str(w)

    inp = Path(input_root)
    if not inp.exists():
        return None

    candidates = []
    stack = [(inp, 0)]
    while stack:
        cur, depth = stack.pop()
        if depth > max_depth:
            continue
        try:
            for child in sorted(cur.iterdir()):
                if not child.is_dir():
                    continue
                if is_valid(child):
                    candidates.append((depth + 1, str(child)))
                else:
                    stack.append((child, depth))
        except PermissionError:
            continue

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


BASE = _find_fortunelib()
if BASE is None:
    print("!! fortunelib が見つかりません。マウントされている入力を確認してください:")
    inp = Path("/kaggle/input")
    if inp.exists():
        for p in sorted(inp.iterdir()):
            print(f"   /kaggle/input/{p.name} （{'dir' if p.is_dir() else 'file'}）")
            if p.is_dir():
                for q in sorted(p.iterdir())[:10]:
                    print(f"      └ {q.name}")
    else:
        print("   /kaggle/input が存在しません（Add Input が行われていない可能性）")
    raise SystemExit("fortunelib が見つかりません（上記ツリーを確認してください）")

sys.path.insert(0, BASE)
os.environ.setdefault("FORTUNE_DATA_DIR", str(Path(BASE) / "data"))
print("✅ fortunelib を検出:", BASE)
print("   FORTUNE_DATA_DIR:", os.environ["FORTUNE_DATA_DIR"])

try:
    _version_path = Path(BASE) / "data" / "dataset_version.json"
    BUILD_ID = json.loads(_version_path.read_text(encoding="utf-8")).get(
        "build_id", "unknown")
except Exception:
    BUILD_ID = "unknown"

# ============================================================
# STEP 2.5: Notebook の版チェック（mts5.40）
# ============================================================
# ★mts5.35 の事故: cellN2_synthesis.py に動画カードを足したのに、手元の Kaggle
#   Notebook を取り込み直していなかったため、本番で**動画のコードが走らなかった**。
#   Dataset の New Version だけでは Notebook の中身は変わらない、という落とし穴。
#   ここで古さを検出する（見つからなければ黙っている・例外も出さない）。
try:
    from fortunelib.notebook_guard import check_notebook_freshness as _check_nb
    _check_nb(BASE)
except Exception as _e_nb:
    print(f"   （Notebook の版チェックはスキップ: {type(_e_nb).__name__}）")

RUN_ERRORS = []

# ============================================================
# STEP 3: Gemini API バックエンドの設定
# ============================================================
from fortunelib.backend import GeminiBackend, LazyBackend, _resolve_gemini_api_key  # noqa: E402

# ★ 2026-08-28: 408 Request Timeout は backend.py 本体でリトライ対象
#   （429/5xx と同じ指数バックオフ）。ノートブック側の monkeypatch は不要。

# ★ モデル（mts5.67・2026-10-14・ユーザー決定）: gemini-3.8-flash
#   Google が gemini-3.5-flash と gemini-3.7-flash を**非推奨**にしたため、既定を
#   gemini-3.8-flash へ変更。404・拒否のときの候補順は 3.8 → 3.6 → 3-flash-preview
#   （fortunelib/backend.py の gemini_model_candidates と model_plan.json が同じ順）。
#   非推奨の2モデルは一次・fallback・404候補のすべてから外してある（指定しないこと）。
#   thinking_level=minimal が 3.8 で拒否された場合は minimal → low → 除去 の順に
#   自動で緩めて再送する（backend.py）。
# ★ 本番の各段（Stage A〜D）のモデルは MODEL_NAME ではなく
#   fortunelib/data/model_plan.json（plan B5）で決まる（下の get_mts_backends()）。
#   MODEL_NAME は単体 GeminiBackend（セルフテスト・補助呼び出し）の既定。
# （履歴）2026-08-26: gemini-2.5-flash（2026-10-16 以降に廃止予定）→ gemini-3.5-flash。
#   2026-08-27: AI Studio 実測表＝3.5-flash は RPD 20/日、3.5-flash-lite は RPD 500/日。
#   ※ Pro 系は 2026-04 に無料枠から除外されたため指定しないこと。
#   ※ 404時は同一モデルファミリーの候補へ切替。実IDは Cell 0.1 の
#     疎通確認に表示される。Pro系・Gemini 2系・2.5系は一次モデルに指定しない。
MODEL_NAME = "gemini-3.8-flash"

# ★ 無料枠のレート制限は概ね 10〜15回/分。安全側の 10 に設定。
#   1回の完走は約67呼び出しなので、日次上限（250〜1,500回/日・モデルによる）
#   に対しても 1 日 1〜3 回は余裕で実行できる。
REQUESTS_PER_MINUTE = 10.0

# ============================================================
# GOOGLE_API_KEY の取得（3段階）
# ① 環境変数: Secrets を attach した編集モード実行で展開される
# ② kaggle_secrets: Save Version（Commit）実行でも動作する正攻法
# ③ None → ここで停止（キーが無いと何も動かないため、早期に止める）
# ============================================================
GOOGLE_API_KEY = _resolve_gemini_api_key()
if not GOOGLE_API_KEY:
    print("❌ GOOGLE_API_KEY が取得できません。以下の手順で設定してください:")
    print("   ① https://aistudio.google.com にアクセス →「Get API key」で無料発行")
    print("      （クレジットカード登録は不要）")
    print("   ② Kaggle 右側パネル → Add-ons → Secrets →「GOOGLE_API_KEY」の名前で登録")
    print("   ③ この Cell 0 を再実行")
    raise SystemExit("GOOGLE_API_KEY が未設定です（上記①〜③を実施してください）")
print("✅ GOOGLE_API_KEY を取得しました")


def load_backend():
    """MTS以前の単一モデル互換用（MTSでは get_mts_backends() を使用）。"""
    return GeminiBackend(model_name=MODEL_NAME, api_key=GOOGLE_API_KEY)


BACKEND = LazyBackend(load_backend)  # 後方互換用（MTS実行では get_mts_backends() を使用）

# ★ MTS B2: モデルごとに独立 backend。段階 A/B/C の実割り当ては
#   data/model_plan.json。既定 MODEL_NAME はセルフテストの疎通確認等にも使う。
MTS_BACKENDS = None


def get_mts_backends():
    """モデル計画の全モデル分 GeminiBackend を1つずつ作る（スレッド専有）。"""
    global MTS_BACKENDS
    if MTS_BACKENDS is None:
        from fortunelib.mts import load_model_plan, make_gemini_backend
        plan = load_model_plan()
        MTS_BACKENDS = {
            m: make_gemini_backend(m, api_key=GOOGLE_API_KEY, verbose=True)
            for m in plan["models"]
        }
        print("   MTS backends:", ", ".join(MTS_BACKENDS))
    return MTS_BACKENDS


print("✅ ブートストラップ完了")
print("   メインモデル: Gemini API /", MODEL_NAME)
print("   MTS: ON（model_plan.json B2割当: Stage A/B/C マルチモデル並列）")
print("   ※ アクセラレータは GPU 不要（None/CPU のままでOK）")
print("   ※ 1回の完走でおよそ67回の API 呼び出しを消費します")

