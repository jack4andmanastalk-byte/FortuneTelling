# -*- coding: utf-8 -*-
"""
M02 太陽星座
仕様：計算ロジック仕様書 §4.2（✓テーブル検証済み）
※ 境界日（±1日）は年により変動するため、厳密判定は太陽黄経（pyswisseph）で行う。
  本モジュールはテーブル判定（境界日±1日は近似）。
"""
from __future__ import annotations

from datetime import date

# (開始月, 開始日, 星座名) — この日以降次の境界まで
SIGNS = [
    (1, 20, "水瓶座"),
    (2, 19, "魚座"),
    (3, 21, "牡羊座"),
    (4, 20, "牡牛座"),
    (5, 21, "双子座"),
    (6, 22, "蟹座"),
    (7, 23, "獅子座"),
    (8, 23, "乙女座"),
    (9, 23, "天秤座"),
    (10, 24, "蠍座"),
    (11, 23, "射手座"),
    (12, 22, "山羊座"),
]

SIGNS_EN = {
    "牡羊座": "Aries", "牡牛座": "Taurus", "双子座": "Gemini", "蟹座": "Cancer",
    "獅子座": "Leo", "乙女座": "Virgo", "天秤座": "Libra", "蠍座": "Scorpio",
    "射手座": "Sagittarius", "山羊座": "Capricorn", "水瓶座": "Aquarius", "魚座": "Pisces",
}


def sun_sign(month: int, day: int) -> str:
    """月日 → 太陽星座（テーブル判定）"""
    md = month * 100 + day
    prev = "山羊座"  # 12/22〜1/19
    for m, d, sign in SIGNS:
        if md < m * 100 + d:
            return prev
        prev = sign
    return prev  # 12/22以降


def sun_sign_of(d: date) -> str:
    return sun_sign(d.month, d.day)


def sun_sign_en(month: int, day: int) -> str:
    return SIGNS_EN[sun_sign(month, day)]
