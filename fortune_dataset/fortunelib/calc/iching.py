# -*- coding: utf-8 -*-
"""
M26 易（I Ching）— 起卦
仕様：計算ロジック仕様書 §4.19（M26）
- コイン法: 3枚×6回（表=3・裏=2、合計 6=老陰/7=少陽/8=少陰/9=老陽）
- 筮竹法: 大衍の数（49本・三変）シミュレーション
- 本卦・之卦・動爻を出力（卦名は data/iching_64.json から参照）
"""
from __future__ import annotations

from ..data import load_json
from ..rng import FortuneRNG

# 八卦の二進表現（下から上・陽=1・陰=0）
TRIGRAM_BITS = {"乾": 0b111, "兌": 0b110, "離": 0b101, "震": 0b100,
                "巽": 0b011, "坎": 0b010, "艮": 0b001, "坤": 0b000}
BITS_TRIGRAM = {v: k for k, v in TRIGRAM_BITS.items()}
# 五行（体用・断卦用）
TRIGRAM_WUXING = {"乾": "金", "兌": "金", "離": "火", "震": "木",
                  "巽": "木", "坎": "水", "艮": "土", "坤": "土"}

_ICHING = None


def _hexagram_table():
    """(上卦, 下卦) → {no, name_ja} のルックアップ（data/iching_64.json）"""
    global _ICHING
    if _ICHING is None:
        table = {}
        for rec in load_json("iching_64.json"):
            table[(rec["upper"], rec["lower"])] = {
                "no": rec["kingwen_no"],
                "name_ja": rec["name_ja"],
                "reading": rec["reading"],
            }
        _ICHING = table
    return _ICHING


def lines_to_hexagram(lines: list) -> dict:
    """6爻（下から上・1=陽/0=陰）→ 本卦情報"""
    lower = lines[0] * 4 + lines[1] * 2 + lines[2]       # 下卦（初爻〜3爻）
    upper = lines[3] * 4 + lines[4] * 2 + lines[5]       # 上卦（4爻〜6爻）
    lt, ut = BITS_TRIGRAM[lower], BITS_TRIGRAM[upper]
    table = _hexagram_table()
    info = table.get((ut, lt))
    return {
        "upper_trigram": ut,
        "lower_trigram": lt,
        "upper_wuxing": TRIGRAM_WUXING[ut],
        "lower_wuxing": TRIGRAM_WUXING[lt],
        "kingwen_no": info["no"] if info else None,
        "name_ja": info["name_ja"] if info else f"{ut}{lt}",
        "reading": info["reading"] if info else "",
    }


def coin_throw(rng: FortuneRNG) -> list:
    """コイン法: 6爻（下から上）を 6/7/8/9 で返す"""
    result = []
    for _ in range(6):
        total = sum(3 if rng.random() < 0.5 else 2 for _ in range(3))
        result.append(total)  # 6,7,8,9
    return result


def yarrow_throw(rng: FortuneRNG) -> list:
    """筮竹法（大衍の数）: 6爻を 6/7/8/9 で返す（伝統的分布に近似）"""
    result = []
    for _ in range(6):
        total = 49
        for _change in range(3):
            left = rng.randint(1, total - 1)   # 分二
            right = total - left
            right -= 1                         # 掛一
            held = 1
            for pile in (left, right):
                rem = pile % 4
                if rem == 0:
                    rem = 4
                held += rem
            total = total - 1 - (left % 4 or 4) - (right % 4 or 4)
        result.append(total // 4)
    return result


def cast(method: str = "coin", seed: int | None = None,
         mode: str = "random", manual: list | None = None) -> dict:
    """
    易の起卦。

    Args:
        method: "coin"（コイン法・既定）/ "yarrow"（筮竹法）
        seed: RNGシード
        mode: "reproducible" / "random"
        manual: 手動の爻値（6/7/8/9 × 6、下から上）

    Returns:
        dict: 爻値・本卦・之卦・動爻
    """
    rng = FortuneRNG(seed, mode)
    if manual is not None:
        if len(manual) != 6 or not all(v in (6, 7, 8, 9) for v in manual):
            raise ValueError("manual は 6/7/8/9 の6要素（下から上）で指定してください")
        yao = manual
    else:
        yao = coin_throw(rng) if method == "coin" else yarrow_throw(rng)

    lines = [1 if v in (7, 9) else 0 for v in yao]      # 陽=1/陰=0
    moving = [i + 1 for i, v in enumerate(yao) if v in (6, 9)]

    ben = lines_to_hexagram(lines)
    # 之卦: 動爻を反転
    if moving:
        lines_hen = lines[:]
        for i in moving:
            lines_hen[i - 1] = 1 - lines_hen[i - 1]
        hen = lines_to_hexagram(lines_hen)
    else:
        hen = ben

    return {
        "method": method,
        "yao": yao,                 # 6/7/8/9（下から上）
        "lines": lines,             # 1=陽/0=陰（下から上）
        "moving": moving,           # 動爻位置（1-6、空なら静的）
        "ben_hexagram": ben,        # 本卦
        "derived_hexagram": hen,    # 之卦
        "references": ["data/iching_64.json"],
        "notes": ["卦辞・爻辞の本文はデータ定義書D07の拡張待ち（現状はLLM知識で解釈）"],
    }
