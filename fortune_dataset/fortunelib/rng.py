# -*- coding: utf-8 -*-
"""
共通RNG（計算ロジック仕様書 §4.19）
- 再現モード: random.Random(seed) — 同一シードで同一結果
- ランダムモード: secrets ベースで毎回異なる結果
- シード生成: SHA-256(セッションID + 相談内容 + 日時) の先頭8バイト
"""
from __future__ import annotations

import hashlib
import random
import secrets
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))


def make_seed(session_id: str = "", consultation: str = "",
              when: datetime | None = None, salt: str = "") -> int:
    """SHA-256(セッションID+相談内容+日時) の先頭8バイト → int（0〜2^64-1）"""
    when = when or datetime.now(JST)
    text = f"{session_id}|{consultation}|{when.isoformat()}|{salt}"
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


class FortuneRNG:
    """抽選系共通RNG

    Args:
        seed: 明示シード（None なら make_seed から自動生成）
        mode: "reproducible"（再現モード・テスト用）/ "random"（完全ランダム・既定）
    ※ クロスチェック決定: 実運用（本物の占い体験）では毎回ランダムが自然。
      再現モードはテスト・デバッグ用に seed 明示で利用する。
    """

    def __init__(self, seed: int | None = None, mode: str = "random"):
        if mode == "random":
            self._rng = random.Random(secrets.randbits(128))
        else:
            self._rng = random.Random(seed if seed is not None else make_seed())

    def random(self) -> float:
        return self._rng.random()

    def randint(self, a: int, b: int) -> int:
        return self._rng.randint(a, b)

    def choice(self, seq):
        return self._rng.choice(seq)

    def choices(self, population, weights=None, k=1):
        return self._rng.choices(population, weights=weights, k=k)

    def shuffle(self, seq):
        self._rng.shuffle(seq)

    def sample(self, population, k: int):
        return self._rng.sample(population, k)
