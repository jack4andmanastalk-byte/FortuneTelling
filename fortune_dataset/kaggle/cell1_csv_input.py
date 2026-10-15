# ============================================================
# Cell 1: 入力（people_sample.csv を読んで MTS Stage A を実行）
# ------------------------------------------------------------
# 入力は people_sample.csv だけです。このセルを実行すると、CSV の
# 全員分の Stage A（個別占術 52 種）を生成します。
# Stage B/C（統合レポート・御縁のある神さま）は Cell N2 で実行します。
# ============================================================
from pathlib import Path  # noqa: E402

from fortunelib.batch_runner import load_csv  # noqa: E402

# ---- 設定 ---------------------------------------------------
# CSV の置き場所（Dataset に同梱 / /kaggle/working に自分でアップロード のいずれか）
CSV_CANDIDATES = [
    "/kaggle/working/people.csv",                              # 自分でアップロードした場合
    "/kaggle/input/fortune_dataset/kaggle/people_sample.csv",  # 最新 Dataset 配布名
    "/kaggle/input/fortune_dataset/people_sample.csv",          # 旧パス互換
    "/kaggle/input/fortune-dataset/kaggle/people_sample.csv",  # ハイフン名
    "/kaggle/input/fortune-dataset/people_sample.csv",          # ハイフン名互換
    "kaggle/people_sample.csv",                                # ローカル実行
    "people_sample.csv",                                       # ローカル互換
]
OUT_ROOT = "/kaggle/working/output"   # 出力先（person_id ごとにサブフォルダ）
LIMIT = None                          # 先頭N人だけ試す場合は数値（例: 2）
#   ※ 統合レポート＋神々＋HTMLまで含めると1人あたり約67回のAPI呼び出し
#      （所要20〜30分・無料枠の日次上限に収まるのは1〜3人程度）。

# ---- CSV を探す ---------------------------------------------
CSV_PATH = None
for _c in CSV_CANDIDATES:
    if Path(_c).exists():
        CSV_PATH = _c
        break
if CSV_PATH is None:
    # Dataset 配下を再帰探索（マウントパスの違いを吸収）
    for _p in Path("/kaggle/input").rglob("*.csv"):
        if "people" in _p.name:
            CSV_PATH = str(_p)
            break

if CSV_PATH is None:
    _csv_error = (
        "CSVが見つかりません。/kaggle/working/people.csv にアップロードするか、\n"
        "Dataset に people_sample.csv を含めてください。\n"
        "列: person_id, birth_date, birth_time, birth_place, gender, blood_type,\n"
        "    name_kanji, name_kana, partner_date, partner_time, partner_place,\n"
        "    consultation, target"
    )
    raise FileNotFoundError(_csv_error)

print("CSV:", CSV_PATH)
_rows = load_csv(CSV_PATH)
print(f"対象 {len(_rows)}名")
for _r in _rows:
    _mode = "今日の運勢モード" if not (_r.get("consultation") or "").strip() else "相談あり"
    _pt = "相手あり" if (_r.get("partner_date") or "").strip() else "相手なし"
    print(f"  - {_r.get('person_id') or '(自動採番)':16s} {_r['birth_date']}  {_mode} / {_pt}")

# ---- 実行 ---------------------------------------------------
# mts5.54: 前のセル（セルフテスト）の警告を持ち越さない。このセルの警告だけを数える。
# mts5.55: 再利用の内訳（SKIP_STATS）も同じくプロセス共通なので、ここで0に戻す
#          （セルフテストで起きた再利用が「本番で再利用した」ように見える誤表示を防ぐ）。
try:
    from fortunelib.runcheck import clear as _warn_clear
    from fortunelib.pipeline import reset_skip_stats as _skip_reset
    _warn_clear()
    _skip_reset()
except Exception:
    pass
# MTS Stage A のみをここで実行し、Stage B/C は Cell N2 が担当する。
# 新しいCSV実行として、前回の通知エラーを持ち越さない。
RUN_ERRORS = []
from fortunelib.mts import run_person_mts  # noqa: E402
_rows2 = _rows[:LIMIT] if LIMIT else _rows
RESULTS = []
_be = get_mts_backends()
for _row in _rows2:
    RESULTS.append(run_person_mts(
        _row, _be, Path(OUT_ROOT), stages="A", verbose=True))

# Stage A の未解決エラーは、Cell N2 の最終通知にも引き継ぐ。
_run_errors = globals().setdefault("RUN_ERRORS", [])
for _r in RESULTS:
    if _r.error:
        _run_errors.append({
            "stage": "A", "target": _r.person_id,
            "message": f"個別占術の失敗 {_r.error} 件: {_r.failed[:12]}",
        })

# ★統合レポート（Cell N2）が、このCSVバッチの結果を対象に選べるよう
#   フラグを立てる（Cell N2 の出力先判定に使用）。
CSV_BATCH_DONE = True

# mts5.53（P-10）: 段階Aの警告（再利用・照合の欠落・フォントなど）を1か所にまとめる。
# 既定は警告のみで実行は続く。RUN_STRICT=1 のときだけ不合格（SystemExit(1)）にする。
try:
    from fortunelib.runcheck import WARNINGS as _A_WARNINGS, enforce as _a_enforce, report as _a_report
    if _A_WARNINGS:
        print("\n■ 警告（既定では合否に影響しません）")
    _a_report(prefix="  ⚠")
    _a_enforce()
except SystemExit:
    raise
except Exception as _a_e:
    print(f"  ⚠ 警告の集約に失敗（{type(_a_e).__name__}: {_a_e}）")

print("\n" + "=" * 56)
print("■ バッチ完了")
for _r in RESULTS:
    print(f"  {_r.person_id:16s} 生成{_r.ok:3d} / 対象外{_r.unavailable} / 失敗{_r.error}")
print(f"\n→ 出力: {OUT_ROOT}/  （人ごとのフォルダに結果一式。一覧の index.md はありません）")

print("\n※ 統合レポート（Cell N2）は各 person フォルダに対して生成されます")
print("※ 中断・再開する場合は、Cell N2 完了時に保存される Dataset チェックポイントを")
print("   次回 Add Input に追加してください（結果はスキップガードで再利用されます）")
