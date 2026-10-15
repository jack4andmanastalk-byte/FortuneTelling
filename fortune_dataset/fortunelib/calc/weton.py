# -*- coding: utf-8 -*-
"""
M14 ウェトン（ジャワ暦・パサラン5日周期）
仕様：計算ロジック仕様書 §4.9（✓検証済み）
  アンカー: 1945-08-17 = 金曜（Jumat）・Legi
  パサラン = (対象日 - アンカー) mod 5
"""
from __future__ import annotations

from datetime import date

PASARAN = ["Legi", "Pahing", "Pon", "Wage", "Kliwon"]
ANCHOR = date(1945, 8, 17)  # 金曜・Legi（既知アンカー）

DOW_JA = ["月", "火", "水", "木", "金", "土", "日"]  # Python: Monday=0
DOW_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def pasaran(d: date) -> str:
    """対象日 → パサラン（5日周期）"""
    return PASARAN[(d - ANCHOR).days % 5]


def weton_name(d: date) -> str:
    """対象日 → ウェトン名（例: 金曜・Legi）"""
    return f"{DOW_JA[d.weekday()]}曜・{pasaran(d)}"


def weton_detail(d: date) -> dict:
    return {
        "date": d.isoformat(),
        "day_ja": f"{DOW_JA[d.weekday()]}曜",
        "day_en": DOW_EN[d.weekday()],
        "pasaran": pasaran(d),
        "weton_name": weton_name(d),
    }
