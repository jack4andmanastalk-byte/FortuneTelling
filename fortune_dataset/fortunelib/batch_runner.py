# -*- coding: utf-8 -*-
"""
複数人バッチ入力・共有ユーティリティ

MTS実行器が利用するCSV読込、person_id正規化、結果索引の共通処理を提供する。

CSV 仕様（ヘッダ必須・列の順序は自由・不要な列は省略可）:
    person_id, birth_date, birth_time, birth_place, gender, blood_type,
    name_kanji, name_kana,
    partner_date, partner_time, partner_place,
    consultation, target

  ・birth_date のみ必須（YYYY-MM-DD）
  ・person_id 省略時は "person_01" のように自動採番
  ・consultation 空欄 → その人は「今日の運勢モード」で実行される
  ・target 空欄 → 内部では実行日基準（計算は行う）。相談ありモードでは
    レポート冒頭・Stage B/C に「対象日」を出さない（mts4.1表示層ゲート）
  ・partner_date 空欄 → 相性系2種はスキップ（63〜64種になる）

途中で中断しても、既に完了した人・占術はスキップして再開できる。
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path


CSV_COLUMNS = [
    "person_id", "birth_date", "birth_time", "birth_place", "gender",
    "blood_type", "name_kanji", "name_kana",
    "partner_date", "partner_time", "partner_place",
    "consultation", "target",
]

_SAFE = re.compile(r"[^0-9A-Za-z._\-\u3040-\u30ff\u4e00-\u9fff]+")


def safe_id(value: str, index: int) -> str:
    """person_id をディレクトリ名として安全な文字列にする"""
    v = (value or "").strip()
    if not v:
        return f"person_{index:02d}"
    v = _SAFE.sub("_", v).strip("_")
    return v or f"person_{index:02d}"


def row_to_input(row: dict) -> dict:
    """CSV の1行 → normalize_input が受け取る INPUT 辞書"""
    g = lambda k: (row.get(k) or "").strip()  # noqa: E731
    return {
        "birth": {"date": g("birth_date"), "time": g("birth_time"),
                  "place": g("birth_place")},
        "gender": g("gender"),
        "blood_type": g("blood_type"),
        "name_kanji": g("name_kanji"),
        "name_kana": g("name_kana"),
        "partner": {"date": g("partner_date"), "time": g("partner_time"),
                    "place": g("partner_place")},
        "consultation": g("consultation"),
        "target": g("target"),
    }


def load_csv(path) -> list:
    """CSV を読み込んで行の辞書リストを返す（BOM付きUTF-8にも対応）"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"CSVがありません: {p}")
    with open(p, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f)]
    out = []
    for i, r in enumerate(rows, 1):
        r = {(k or "").strip(): v for k, v in r.items()}
        if not (r.get("birth_date") or "").strip():
            continue          # 空行・見出し崩れはスキップ
        r["_index"] = i
        out.append(r)
    return out


@dataclass
class PersonResult:
    person_id: str
    ok: int = 0
    skipped: int = 0
    unavailable: int = 0
    error: int = 0
    today_mode: bool = False
    results_dir: str = ""
    report: str = ""
    failed: list = field(default_factory=list)


def _write_report(out_dir: Path, person_id: str, facts: dict,
                  summary_path: Path) -> Path:
    """1人分の統合レポート（final_report.md）を書き出す"""
    lines = [f"# 占術統合レポート（{person_id}）", ""]
    lines.append("## 入力プロファイル要約")
    for k, v in facts.items():
        if not k.startswith("_"):
            lines.append(f"- {k}: {v}")
    lines.append("")

    if summary_path.exists():
        s = json.loads(summary_path.read_text(encoding="utf-8"))
        if s.get("themes"):
            lines.append("## 各占術の要点（サマリー）")
            lines += [f"- {t}" for t in s["themes"]]
            lines.append("")
        if s.get("disagreements"):
            lines.append("## 体系間の不一致（無理に一致させずそのまま記載）")
            lines += [f"- {d}" for d in s["disagreements"]]
            lines.append("")

    lines.append("## 目次（結果ファイル）")
    for f in sorted((out_dir / "results").glob("*.md")):
        if "_raw" not in f.name:
            lines.append(f"- {f.stem}: `results/{f.name}`")
    lines += ["", "---",
              "※ 本レポートはエンターテインメント目的のシミュレーションであり、",
              "事実を表すものではありません。医療・法律・投資・人生の重大な決定には利用しないでください。"]

    path = out_dir / "final_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


