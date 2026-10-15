# -*- coding: utf-8 -*-
"""
占術クラスター定義（中間レポートの単位）

2つの切り口を用意する。用途に応じて選べる。

  axis="method"  … 手法軸（決定論的計算 → 命盤 → 抽選 → 相性 → 疑似）
                   「どこまでが計算に基づく話か」が読者に伝わる並び。
  axis="culture" … 文化圏軸（東アジア／インド／西洋／オリエント・地中海／
                   東南アジア・アフリカ／現代・その他）
                   同じ文化圏の体系が何を言っているかを比べられる。

いずれも全66種を過不足なく分割する（テストで保証）。
"""
from __future__ import annotations

from .registry import all_slugs

# ---------------------------------------------------------------
# 手法軸（5クラスタ）
# ---------------------------------------------------------------
METHOD_CLUSTERS = [
    {
        "id": "M-A", "title": "基礎プロファイル（暦・数の決定論的計算）",
        "desc": "生年月日から暦法・数理で一意に定まる体系。ぶれない土台。",
        "slugs": ["seiza", "eto", "kyusei", "numerology_birth", "tantra",
                  "anka", "blood", "animal", "rokusei", "weton", "primbon",
                  "stone", "omikuji", "genekeys",
                  "seimei", "numerology_name", "kabbalah", "chaldean"],
    },
    {
        "id": "M-B", "title": "命盤・星位（天体と干支の精密計算）",
        "desc": "出生時刻・出生地まで用いて命盤や星位を排出する体系。",
        "slugs": ["bazi", "western", "natal", "transit", "vedic",
                  "ziwei", "sanmei", "hd"],
    },
    {
        "id": "M-C", "title": "抽選・卜占（その時の引き）",
        "desc": "カード・卦・ルーン等をその場で引いて読む体系。相談内容に直接応答する。",
        "slugs": ["iching", "liuyao", "meihua", "qimen", "tarot", "marseille",
                  "lenormand", "kipper", "oracle", "angel", "cartomancy",
                  "urbantarot", "runes"],
    },
    {
        "id": "M-D", "title": "相性（二者の関係）",
        "desc": "本人と相手の二者関係を見る体系。",
        "slugs": ["synastry", "parimicham"],
    },
    {
        "id": "M-E", "title": "象徴・霊性（疑似体験モード）",
        "desc": "体系の語彙と形式を模した創作。事実ではなく象徴として読む領域。",
        "slugs": ["christian", "crystal", "crystalball", "pendulum", "talisman", "african",
                  "haruspex",
                  "meso", "delphi", "ornith", "astragaloi", "deities"],
    }
]

# ---------------------------------------------------------------
# 文化圏軸（6クラスタ）
# ---------------------------------------------------------------
CULTURE_CLUSTERS = [
    {
        "id": "C-EA", "title": "東アジア（中国・日本）",
        "desc": "陰陽五行・干支を共通言語とする体系群。",
        "slugs": ["eto", "kyusei", "bazi", "ziwei", "sanmei", "rokusei",
                  "animal", "seimei", "iching", "liuyao", "meihua", "qimen",
                  "omikuji"],
    },
    {
        "id": "C-IN", "title": "インド（ヴェーダ系）",
        "desc": "ナクシャトラ・数理・チャクラを軸とする体系群。",
        "slugs": ["vedic", "tantra", "anka", "parimicham", "genekeys", "hd"],
    },
    {
        "id": "C-WE", "title": "西洋（占星術・数秘・カード）",
        "desc": "黄道十二宮とアルファベット数理を基盤とする体系群。",
        "slugs": ["seiza", "western", "natal", "transit", "synastry",
                  "numerology_birth", "numerology_name", "chaldean",
                  "tarot", "marseille", "lenormand", "kipper", "oracle",
                  "angel", "cartomancy", "urbantarot", "runes"],
    },
    {
        "id": "C-OR", "title": "オリエント・地中海（古代の卜占）",
        "desc": "メソポタミア・エジプト・ギリシャに連なる古代の占術と神秘思想。",
        "slugs": ["kabbalah", "haruspex", "meso", "delphi", "ornith",
                  "astragaloi", "christian", "deities"],
    },
    {
        "id": "C-SA", "title": "東南アジア・アフリカ（民俗）",
        "desc": "ジャワ暦や地域の伝統的治療者に連なる民俗知。",
        "slugs": ["weton", "primbon", "african" ],
    },
    {
        "id": "C-MO", "title": "現代スピリチュアル・その他",
        "desc": "20世紀以降に成立した象徴体系と、分類外の体系。",
        "slugs": ["blood", "stone", "crystal", "crystalball", "pendulum", "talisman"],
    }
]

AXES = {"method": METHOD_CLUSTERS, "culture": CULTURE_CLUSTERS}


def get_clusters(axis: str = "method") -> list:
    """軸名 → クラスタ定義のリスト"""
    if axis not in AXES:
        raise ValueError(f"未知の軸: {axis}（method / culture）")
    return AXES[axis]


def validate_axis(axis: str) -> None:
    """その軸が全66種を過不足なく覆っているか検証する（重複・欠落の検出）"""
    clusters = get_clusters(axis)
    seen = []
    for c in clusters:
        seen.extend(c["slugs"])
    known = set(all_slugs())
    dup = {s for s in seen if seen.count(s) > 1}
    missing = known - set(seen)
    unknown = set(seen) - known
    if dup or missing or unknown:
        raise AssertionError(
            f"軸 {axis} の定義に不備: 重複={sorted(dup)} "
            f"欠落={sorted(missing)} 未知={sorted(unknown)}")


def cluster_of(slug: str, axis: str = "method") -> dict | None:
    for c in get_clusters(axis):
        if slug in c["slugs"]:
            return c
    return None
