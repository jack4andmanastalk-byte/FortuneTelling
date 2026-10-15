# -*- coding: utf-8 -*-
"""
M04〜M07 数秘術（生年月日・氏名・カバラ・カルデア）
仕様：計算ロジック仕様書 §4.4〜4.6（✓検証済み）
- ライフパス：生年月日の各桁合計 → 数字根（11/22/33はマスターとして保持）
- ピタゴラス式（氏名）：A=1..I=9, J=1..R=9, S=1..Z=8 の1-9巡回 → 合計 → 数字根
  ★BUG-08（2026-08-17 クロス検証）: 旧実装は A=1〜Z=26 の素の序数だった。
    ピタゴラス式は「9を超えたら1に戻る」1-9巡回が正しい（ProjectA 実装が正）。
    例) JOHN = J1+O6+H8+N5 = 20 → 2（旧実装は 10+15+8+14=47 → 11 と誤判定）
    出典: checkmynumerology.com / calculatorsheaven.com / astrosight.ai（相互一致）
- カバラ方式A：ピタゴラス式と同じアルファベット数値（既定）
- カルデア：固定対応表（1-8）
"""
from __future__ import annotations

from datetime import date

MASTER_NUMBERS = (11, 22, 33)

CHALDEAN_TABLE = {
    "A": 1, "I": 1, "J": 1, "Q": 1, "Y": 1,
    "B": 2, "K": 2, "R": 2,
    "C": 3, "G": 3, "L": 3, "S": 3,
    "D": 4, "M": 4, "T": 4,
    "E": 5, "H": 5, "N": 5, "X": 5,
    "U": 6, "V": 6, "W": 6,
    "O": 7, "Z": 7,
    "F": 8, "P": 8,
}


def digital_root(n: int, keep_master: bool = True) -> int:
    """数字根。keep_master=True のとき 11/22/33 を還元しない"""
    while n > 9 and not (keep_master and n in MASTER_NUMBERS):
        n = sum(int(d) for d in str(n))
    return n


def life_path(d: date) -> int:
    """生年月日 → ライフパスナンバー（YYYYMMDDの各桁合計 → 数字根）"""
    s = d.strftime("%Y%m%d")
    total = sum(int(c) for c in s)
    return digital_root(total)


# ピタゴラス式の文字対応（1-9 巡回・A=1, J=1, S=1 …）
PYTHAGOREAN_TABLE = {
    c: (i % 9) + 1 for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
}


def letter_values_pythagorean(romaji: str) -> int:
    """ヘボン式ローマ字 → ピタゴラス式（1-9巡回）の合計

    A=1 B=2 … I=9 / J=1 K=2 … R=9 / S=1 T=2 … Z=8
    """
    total = 0
    for c in romaji.upper():
        if c in PYTHAGOREAN_TABLE:
            total += PYTHAGOREAN_TABLE[c]
    return total


def name_number_pythagorean(romaji: str) -> int:
    """ピタゴラス式（氏名）→ 数字根"""
    return digital_root(letter_values_pythagorean(romaji))


def kabbalah_value(romaji: str) -> int:
    """カバラ方式A（既定）＝ ピタゴラス式と同じアルファベット数値 → 数字根"""
    return digital_root(letter_values_pythagorean(romaji))


def chaldean_value(romaji: str) -> int:
    """カルデア数秘術：対応表 → 合計 → 数字根"""
    total = 0
    for c in romaji.upper():
        if c in CHALDEAN_TABLE:
            total += CHALDEAN_TABLE[c]
    return digital_root(total)
