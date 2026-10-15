# -*- coding: utf-8 -*-
"""
M28 おみくじ・籤占（アストラガロイ）
仕様：計算ロジック仕様書 §4.19（M28）
- おみくじ: data/omikuji_12.json（12段階）から抽選。和歌はLLM生成（データ未収録）
- アストラガロイ: 古代ギリシャの骨籤。5個の4面ダイス（目: 1,3,4,6）
"""
from __future__ import annotations

from ..data import load_json
from ..rng import FortuneRNG

# アストラガロイの目（羊の距骨の4面）
ASTRAGALOI_FACES = [1, 3, 4, 6]


def draw_omikuji(seed: int | None = None, mode: str = "random",
                 weights: list | None = None) -> dict:
    """
    おみくじ抽選（12段階）。

    Args:
        seed: RNGシード
        mode: "reproducible" / "random"
        weights: 段階ごとの重み（省略時は等確率。神社により異なるため注記）

    Returns:
        dict: 籤レベル・キーワード
    """
    levels = load_json("omikuji_12.json")
    rng = FortuneRNG(seed, mode)
    if weights is None:
        level = rng.choice(levels)
    else:
        if len(weights) != len(levels):
            raise ValueError("weights の長さは段階数と一致させる必要があります")
        level = rng.choices(levels, weights=weights, k=1)[0]
    return {
        "level": level["level"],
        "keyword": level["keyword"],
        "note": level.get("note", ""),
        "waka": None,   # 和歌はLLM生成（データ定義書D12の拡張待ち）
        "references": ["data/omikuji_12.json"],
        "notes": ["段階構成・確率は神社により異なります（本実装は等確率・一般化表）"],
    }


def throw_astragaloi(n: int = 5, seed: int | None = None,
                     mode: str = "random") -> dict:
    """
    アストラガロイ（骨籤）投擲。

    Args:
        n: 投げる骨の数（伝統的には5個）
        seed: RNGシード
        mode: "reproducible" / "random"

    Returns:
        dict: 出目・合計・判定（アフロディーテの目/犬の目など）
    """
    rng = FortuneRNG(seed, mode)
    throws = [rng.choice(ASTRAGALOI_FACES) for _ in range(n)]
    total = sum(throws)

    # 伝統的な判定
    if len(set(throws)) == 1:
        judgment = "犬の目（最悪の目）"
    elif len(set(throws)) == len(throws):
        judgment = "アフロディーテの目（最上の目）"
    else:
        judgment = "通常の目"

    return {
        "throws": throws,
        "total": total,
        "judgment": judgment,
        "references": ["古代ギリシャの骨籤（アストラガロイ）の一般知識"],
        "notes": ["各骨は4面（1・3・4・6）で、特定の目の組合せに神話的意味が付与される"],
    }
