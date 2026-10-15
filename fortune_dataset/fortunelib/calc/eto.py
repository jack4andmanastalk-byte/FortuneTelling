# -*- coding: utf-8 -*-
"""
M01 干支（年柱）／十干・十二支テーブル
仕様：計算ロジック仕様書 §4.1（✓検証済み）
※ 立春境界の判定は sxtwl 委譲（Kaggle側）。本モジュールは年単位の写像のみ。
"""
from __future__ import annotations

JIKKAN = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
JIKKAN_YOMI = ["きのえ", "きのと", "ひのえ", "ひのと", "つちのえ", "つちのと",
               "かのえ", "かのと", "みずのえ", "みずのと"]
JUNISHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]
JUNISHI_YOMI = ["ね", "うし", "とら", "う", "たつ", "み", "うま", "ひつじ",
                "さる", "とり", "いぬ", "い"]
JUNISHI_ANIMAL = ["鼠", "牛", "虎", "兎", "龍", "蛇", "馬", "羊", "猿", "鶏", "犬", "猪"]


def jikkan(year: int) -> str:
    """西暦年 → 十干（立春補正は呼び出し側で実施済みの年を渡すこと）"""
    return JIKKAN[(year - 4) % 10]


def junishi(year: int) -> str:
    """西暦年 → 十二支"""
    return JUNISHI[(year - 4) % 12]


def year_ganzhi(year: int) -> str:
    """西暦年 → 年柱（例: 2026 → 丙午）"""
    return jikkan(year) + junishi(year)


def year_ganzhi_detailed(year: int) -> dict:
    """詳細情報付き（例: {"kan": "丙", "kan_yomi": "ひのえ", "shi": "午", ...}）"""
    k = (year - 4) % 10
    s = (year - 4) % 12
    return {
        "year": year,
        "ganzhi": JIKKAN[k] + JUNISHI[s],
        "kan": JIKKAN[k],
        "kan_yomi": JIKKAN_YOMI[k],
        "shi": JUNISHI[s],
        "shi_yomi": JUNISHI_YOMI[s],
        "animal": JUNISHI_ANIMAL[s],
    }
