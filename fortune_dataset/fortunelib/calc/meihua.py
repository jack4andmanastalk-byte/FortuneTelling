# -*- coding: utf-8 -*-
"""
M23 梅花易数 — 数値起卦
仕様：計算ロジック仕様書 §4.16（M23）
- 上卦 = 数1 mod 8（1=乾,2=兌,3=離,4=震,5=巽,6=坎,7=艮,0=坤）
- 下卦 = 数2 mod 8
- 動爻 = (数1+数2) mod 6（0は6）
- 体卦/用卦: 動爻が下卦(1-3)なら下=用・上=体、上卦(4-6)なら上=用・下=体
- 互卦: 本卦の2・3・4爻を下卦、3・4・5爻を上卦にしたもの
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone, timedelta

from .iching import lines_to_hexagram, TRIGRAM_WUXING, BITS_TRIGRAM

JST = timezone(timedelta(hours=9))

# 八卦の二進表現（下から上・陽=1/陰=0）※iching と同じ
TRIGRAM_BITS = {"乾": 0b111, "兌": 0b110, "離": 0b101, "震": 0b100,
                "巽": 0b011, "坎": 0b010, "艮": 0b001, "坤": 0b000}
NUM_TO_TRIGRAM = {0: "坤", 1: "乾", 2: "兌", 3: "離", 4: "震", 5: "巽", 6: "坎", 7: "艮"}


def _num_to_trigram(n: int) -> str:
    """数値 → 八卦（1=乾,2=兌,3=離,4=震,5=巽,6=坎,7=艮,0/8=坤）"""
    r = n % 8
    return NUM_TO_TRIGRAM[r]


def numbers_to_hexagram(n1: int, n2: int) -> dict:
    """2つの数値 → 梅花易数の卦"""
    upper = _num_to_trigram(n1)   # 上卦
    lower = _num_to_trigram(n2)   # 下卦
    moving = (n1 + n2) % 6
    if moving == 0:
        moving = 6

    # 本卦の爻（下から上）を構成
    lines = []
    for t in (lower, upper):
        bits = TRIGRAM_BITS[t]
        lines.extend([(bits >> 2) & 1, (bits >> 1) & 1, bits & 1])
    ben = lines_to_hexagram(lines)

    # 之卦: 動爻を反転
    lines_hen = lines[:]
    lines_hen[moving - 1] = 1 - lines_hen[moving - 1]
    hen = lines_to_hexagram(lines_hen)

    # 互卦: 2・3・4爻 → 下卦、3・4・5爻 → 上卦
    lower_mut = lines[1] * 4 + lines[2] * 2 + lines[3]
    upper_mut = lines[2] * 4 + lines[3] * 2 + lines[4]
    lt_mut, ut_mut = BITS_TRIGRAM[lower_mut], BITS_TRIGRAM[upper_mut]
    mut = lines_to_hexagram([lines[1], lines[2], lines[3], lines[2], lines[3], lines[4]])
    mut["upper_trigram"] = ut_mut
    mut["lower_trigram"] = lt_mut

    # 体卦・用卦
    body_is_upper = moving <= 3   # 動爻が下卦 → 用=下・体=上
    body = upper if body_is_upper else lower
    yong = lower if body_is_upper else upper

    return {
        "numbers": [n1, n2],
        "upper_trigram": upper,
        "lower_trigram": lower,
        "moving": moving,
        "ben_hexagram": ben,
        "derived_hexagram": hen,
        "mutual_hexagram": mut,
        "body_trigram": {"name": body, "wuxing": TRIGRAM_WUXING[body], "role": "体卦"},
        "function_trigram": {"name": yong, "wuxing": TRIGRAM_WUXING[yong], "role": "用卦"},
        "notes": ["体用の生克関係（体が用を生む/克つ等）はLLM解釈で展開"],
    }


def numbers_from_time(when: datetime | None = None) -> list:
    """時刻から起卦数を生成（年支+月+日 → 上卦、+時辰 → 下卦）"""
    when = when or datetime.now(JST)
    zhi = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]
    year_zhi_idx = (when.year - 4) % 12          # 年支
    hour_idx = ((when.hour + 1) // 2) % 12       # 時辰
    n1 = year_zhi_idx + 1 + when.month + when.day
    n2 = n1 + hour_idx + 1
    return [n1, n2]


def numbers_from_text(text: str) -> list:
    """文字列から起卦数を生成（前半・後半のUnicode合計 mod 8 等）"""
    half = max(1, len(text) // 2)
    s1 = sum(ord(c) for c in text[:half])
    s2 = sum(ord(c) for c in text[half:])
    return [s1 % 8 or 8, s2 % 8 or 8]


def cast(numbers: list | None = None, source: str = "manual",
         when: datetime | None = None, text: str = "") -> dict:
    """
    梅花易数で起卦。

    Args:
        numbers: 2つの数値（source="manual" のとき必須）
        source: "manual"（数値指定）/ "time"（時刻）/ "text"（文字列）
        when: 時刻（source="time"）
        text: 文字列（source="text"）

    Returns:
        dict: 本卦・之卦・互卦・体用
    """
    if source == "manual":
        if not numbers or len(numbers) != 2:
            raise ValueError("source='manual' のとき numbers=[数1, 数2] を指定してください")
        return numbers_to_hexagram(numbers[0], numbers[1])
    if source == "time":
        nums = numbers_from_time(when)
        return numbers_to_hexagram(nums[0], nums[1])
    if source == "text":
        if not text:
            raise ValueError("source='text' のとき text を指定してください")
        nums = numbers_from_text(text)
        return numbers_to_hexagram(nums[0], nums[1])
    raise ValueError(f"不明な source: {source}")
