# -*- coding: utf-8 -*-
"""
M29 ペンデュラム・アフリカ占い（貝殻・骨）
仕様：計算ロジック仕様書 §4.19（M29）
- ペンデュラム: Yes/No/中立 の3値判定（物理的振動の代わりにRNG）
- アフリカ占い: 貝殻8枚（表=開き/裏）のパターン生成（イファのコラナット風）
"""
from __future__ import annotations

from ..rng import FortuneRNG

# ペンデュラムの既定確率（Yes:No:中立）
PENDULUM_WEIGHTS = {"yes": 0.45, "no": 0.45, "neutral": 0.10}


def swing(seed: int | None = None, mode: str = "random",
          weights: dict | None = None) -> dict:
    """
    ペンデュラム判定。

    Args:
        seed: RNGシード
        mode: "reproducible" / "random"
        weights: {"yes": x, "no": y, "neutral": z} の確率（省略時は既定）

    Returns:
        dict: 判定（yes/no/neutral）
    """
    w = weights or PENDULUM_WEIGHTS
    rng = FortuneRNG(seed, mode)
    r = rng.random()
    if r < w.get("yes", 0.45):
        answer = "yes"
    elif r < w.get("yes", 0.45) + w.get("no", 0.45):
        answer = "no"
    else:
        answer = "neutral"
    return {
        "answer": answer,
        "interpretation": {"yes": "肯定", "no": "否定", "neutral": "中立・保留"}[answer],
        "weights": w,
        "references": [],
        "notes": ["物理的振り子の代わりにRNGで判定するシミュレーション"],
    }


def throw_cowrie(n: int = 8, seed: int | None = None,
                 mode: str = "random") -> dict:
    """
    アフリカ占い（貝殻投擲）。

    Args:
        n: 貝殻の数（伝統的には4枚=16パターン or 8枚。既定8枚）
        seed: RNGシード
        mode: "reproducible" / "random"

    Returns:
        dict: パターンID・開きの数・各貝の状態
    """
    rng = FortuneRNG(seed, mode)
    shells = [1 if rng.random() < 0.5 else 0 for _ in range(n)]
    open_count = sum(shells)
    # パターンID: 二進（先頭=最上位ビット）
    pattern_id = 0
    for s in shells:
        pattern_id = (pattern_id << 1) | s

    return {
        "shell_count": n,
        "open_count": open_count,
        "shells": shells,          # 1=開き（口が上）/ 0=閉じ
        "pattern_id": pattern_id,
        "pattern_total": 2 ** n,
        "references": ["西アフリカの伝統的占い（イファのコラナット等）の一般知識"],
        "notes": ["パターン解釈はLLMが体系の語彙で生成（データ定義書Dでの拡張待ち）"],
    }
