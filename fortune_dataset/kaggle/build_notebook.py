# -*- coding: utf-8 -*-
"""Kaggle ノートブック組み立てスクリプト
- Cell 0 / 0.1 / 1（CSV入力＋Stage A）/ N2（Stage B/C）を .ipynb に統合
- 出力: fortune_notebook.ipynb（Kaggle にアップロードして実行）
- `--check`: 生成せず、既存の .ipynb が cell*.py と一致しているかだけを見る

★mts5.40 の事故と対策: cellN2_synthesis.py に動画カードを追加した mts5.35 で
**このスクリプトの実行を忘れた**ため、配布した fortune_notebook.ipynb は動画ブロックの
無い古い内容のままで、本番では動画が作られなかった（＝テストでは気づけない二重管理）。
そのため `--check` と `tests/test_notebook_sync.py` で**一致を固定**する。
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "fortune_notebook.ipynb"


def code_cell(src: str) -> dict:
    return {"cell_type": "code", "execution_count": None,
            "metadata": {}, "outputs": [],
            "source": src.splitlines(keepends=True)}


def markdown_cell(src: str) -> dict:
    return {"cell_type": "markdown", "metadata": {},
            "source": src.splitlines(keepends=True)}


def sources() -> dict[str, str]:
    """ノートブックのコードセルに流し込む .py の内容（唯一の正本）。"""
    return {
        "cell0_bootstrap.py": (HERE / "cell0_bootstrap.py").read_text(encoding="utf-8"),
        "cell0_selftest.py": (HERE / "cell0_selftest.py").read_text(encoding="utf-8"),
        "cell1_csv_input.py": (HERE / "cell1_csv_input.py").read_text(encoding="utf-8"),
        "cellN2_synthesis.py": (HERE / "cellN2_synthesis.py").read_text(encoding="utf-8"),
    }


def check() -> tuple[bool, list[str]]:
    """既存の fortune_notebook.ipynb が .py と一致しているか。"""
    if not OUT.exists():
        return False, [f"{OUT.name} がありません（build_notebook.py を実行してください）"]
    nb = json.loads(OUT.read_text(encoding="utf-8"))
    code = ["".join(c["source"]) if isinstance(c["source"], list) else c["source"]
            for c in nb["cells"] if c["cell_type"] == "code"]
    want = list(sources().values())
    problems = []
    if len(code) != len(want):
        problems.append(f"コードセル数が {len(code)}（期待 {len(want)}）")
    for name, got, exp in zip(sorted(sources()), code, want):
        if got != exp:
            gl, el = got.splitlines(), exp.splitlines()
            diff = sum(1 for a, b in zip(gl, el) if a != b) + abs(len(gl) - len(el))
            problems.append(f"{name}: ノートブックの内容が .py と違います（差 {diff} 行）"
                            " ＝ build_notebook.py を実行し忘れています")
    return (not problems), problems


def build() -> Path:
    cells = []

    # タイトル
    cells.append(markdown_cell(
        "# 占術ノートブック（Gemini Flash × Kaggle）\n\n"
        "**実行手順**：① Cell 0 → ② Cell 0.1（セルフテスト）→ ③ Cell 1（CSV入力＋MTS Stage A）"
        "→ ④ Cell N2（MTS Stage B/C＋HTML）\n\n"
        "**注意**：\n"
        "- 入力は **people_sample.csv** だけです（複数人可・このセルで全員分を処理）。\n"
        "- アクセラレータは **None（CPU）** でOK（GPU不要・T4枠を消費しません）\n"
        "- 右パネル → Add-ons → Secrets に **GOOGLE_API_KEY** を登録してください"
        "（https://aistudio.google.com で無料発行）\n"
        "- fortune_dataset を Add Input で追加、または /kaggle/working に配置してください。"))

    # Cell 0
    cells.append(code_cell((HERE / "cell0_bootstrap.py").read_text(encoding="utf-8")))
    # Cell 0.1: セルフテスト（CI相当・約1分＋API疎通1回）
    cells.append(markdown_cell(
        "## ▶ セルフテスト（CI相当・推奨）\n\n"
        "Add Input した Dataset に対してユニットテストを実行します"
        "（GPU不要・約1分＋Gemini API 疎通1呼び出し）。\n"
        "**ここが失敗したら以降のセル（約20〜30分・約67回のAPI呼び出し）は流さないでください。**\n"
        "Dataset のアップロード漏れ・バージョン取り違え・依存パッケージの導入失敗・"
        "APIキー不備を検出します。"))
    cells.append(code_cell((HERE / "cell0_selftest.py").read_text(encoding="utf-8")))
    # Cell 1: CSV 入力（唯一の入力方式）
    cells.append(markdown_cell(
        "## ▶ 入力（CSV）＋ MTS Stage A\n\n"
        "**入力は people_sample.csv だけです。** このセルで CSV の全員分の "
        "Stage A（個別占術52種）を生成します。Stage B/C は Cell N2 で実行します。\n\n"
        "列: `person_id, birth_date, birth_time, birth_place, gender, blood_type, "
        "name_kanji, name_kana, partner_date, partner_time, partner_place, consultation, target`\n\n"
        "- `consultation` を空欄にすると、その人は「今日の運勢モード」で実行されます。\n"
        "- `partner_*` を埋めると相性系2種（シナストリー・パリミチャム）が実行されます。\n"
        "- 人物を追加・差し替えるときは CSV を書き換えるだけです。"))
    cells.append(code_cell((HERE / "cell1_csv_input.py").read_text(encoding="utf-8")))

    # Cell N2: 統合鑑定レポート（3段階・読み物）
    cells.append(markdown_cell(
        "## ▶ 統合鑑定レポート（3段階）\n\n"
        "Stage Aの全占術結果を **クラスタ単位で中間レポート（950〜2,100字×11本）** にまとめ、\n"
        "**軸サマリー2本** を経て **最終レポート（3,400〜4,800字）** を作成します。\n\n"
        "- `synthesis_report.md` … 読み物としての統合レポート\n"
        "- `cluster_reports/` … 分野別の中間レポート\n"
        "- `final_report.md` … 従来の索引（実行ログ的な一覧・そのまま残ります）\n\n"
        "冒頭の固定動画（Dataset 同梱 `assets/video/intro_video.json`）は Cell N2 の `EMBED_INTRO_VIDEO` でON/OFFできます（既定 `True`）。"
        "ON なら HTML の目次の直前に動画カード（Base64 埋め込み・自動再生なし・オンライン版 YouTube への案内つき）が入り、HTML は約 +10 MB になります。\n\n"
        "MTS B5の固定割当で処理し、Stage Cは `gemini-3.8-flash`（軸2本＋最終1本・予備 3.6-flash → 3-flash-preview）および `gemini-3-flash-preview`（御縁のある神さま Top10）で実行します（非推奨の 3.5-flash／3.7-flash は不使用）。\n"
        "所要時間の目安: Gemini Flash で約4〜7分（中間11本＋軸2本＋最終1本＋神格選定）。"))
    cells.append(code_cell((HERE / "cellN2_synthesis.py").read_text(encoding="utf-8")))

    nb = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.11"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    OUT.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
    return OUT


if __name__ == "__main__":
    import sys
    if "--check" in sys.argv:
        ok, problems = check()
        if ok:
            nb = json.loads(OUT.read_text(encoding="utf-8"))
            print(f"✅ 一致しています（{OUT.name} / セル数 {len(nb['cells'])}）")
            raise SystemExit(0)
        for p_ in problems:
            print(f"❌ {p_}")
        raise SystemExit(1)
    out = build()
    nb = json.loads(out.read_text(encoding="utf-8"))
    print(f"✅ {out} 生成（セル数: {len(nb['cells'])}）")
    ok, problems = check()
    print("✅ 生成物と .py の一致を確認" if ok else f"❌ 不一致: {problems}")
