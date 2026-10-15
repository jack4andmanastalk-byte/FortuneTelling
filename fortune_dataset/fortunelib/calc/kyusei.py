# -*- coding: utf-8 -*-
"""
M03 九星気学（本命星）
仕様：計算ロジック仕様書 §4.3（✓検証済み）
  数字根 s = 1 + ((Y-1) mod 9)、本命星 n = 11 - s（n>9 なら n-9）
※ 立春補正：立春（2/3〜5）前生まれは前年扱い。立春日は sxtwl で取得（Kaggle側）。
"""
from __future__ import annotations

STAR_NAMES = [
    "一白水星", "二黒土星", "三碧木星", "四緑木星", "五黄土星",
    "六白金星", "七赤金星", "八白土星", "九紫火星",
]


def honmei_no(year: int) -> int:
    """西暦年（立春補正済み）→ 本命星番号 1-9"""
    digital_root = (year - 1) % 9 + 1
    n = 11 - digital_root
    if n > 9:
        n -= 9
    return n


def honmei_name(year: int) -> str:
    return STAR_NAMES[honmei_no(year) - 1]


def honmei_detail(year: int) -> dict:
    no = honmei_no(year)
    return {"year": year, "honmei_no": no, "honmei": STAR_NAMES[no - 1]}
