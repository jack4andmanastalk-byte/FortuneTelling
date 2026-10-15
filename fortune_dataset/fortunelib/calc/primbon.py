# -*- coding: utf-8 -*-
"""
M13 プリンボン・ジャワ — 計算モジュール（確定版）
仕様: data/primbon_data.json（ネプツヌ体系・確定）
- ネプツヌ = 曜日値 + パサラン値（7〜21）
- ネプツヌ合計 → 性格区分（5区分）
- パサラン → 性格プロファイル
- 35ウェトン → 個別性格（収録済みのみ・未収録はネプツヌ+パサランから合成）
出典: suaramerdeka.com／hamzahbatik.co.id／detik.com（ジャワの伝統プリンボン）
"""
from __future__ import annotations

from datetime import date

from ..data import load_json
from .weton import weton_detail

_DATA = None


def _data():
    global _DATA
    if _DATA is None:
        _DATA = load_json("primbon_data.json")
    return _DATA


def neptu_of(d: date) -> dict:
    """対象日のネプツヌ値（曜日+パサラン）"""
    data = _data()
    w = weton_detail(d)  # day_ja: 月曜 等 / pasaran: Legi 等
    day_neptu = data["day_neptu"][w["day_ja"]]
    pas_neptu = data["pasaran_neptu"][w["pasaran"]]
    total = day_neptu + pas_neptu
    return {
        "date": d.isoformat(),
        "weton": w["weton_name"],
        "day_ja": w["day_ja"],
        "pasaran": w["pasaran"],
        "day_neptu": day_neptu,
        "pasaran_neptu": pas_neptu,
        "neptu_total": total,
    }


def profile_by_neptu(total: int) -> str:
    """ネプツヌ合計 → 性格区分"""
    data = _data()
    for r in data["neptu_ranges"]:
        if r["min"] <= total <= r["max"]:
            return r["profile"]
    return ""


def pasaran_profile(pasaran: str) -> str:
    """パサラン → 性格"""
    data = _data()
    return data["pasaran_profile"].get(pasaran, "")


def weton_profile(weton_name: str) -> str | None:
    """35ウェトン個別性格（収録済みのみ）"""
    data = _data()
    return data["weton_35_profiles"].get(weton_name)


def primbon_calc(d: date, birth: bool = True) -> dict:
    """
    プリンボン・ジャワの計算。

    Args:
        d: 対象日（出生日 or 対象日）
        birth: True=出生日の性格鑑定 / False=対象日の吉凶

    Returns:
        dict: ネプツヌ・性格・プロファイル
    """
    n = neptu_of(d)
    w_name = n["weton"]
    individual = weton_profile(w_name)
    return {
        **n,
        "neptu_profile": profile_by_neptu(n["neptu_total"]),
        "pasaran_profile": pasaran_profile(n["pasaran"]),
        "individual_profile": individual,
        "has_individual": individual is not None,
        "is_birth": birth,
        "references": ["data/primbon_data.json"],
        "notes": [
            "プリンボンはジャワの伝統的信仰体系に基づく（科学的根拠なし）",
            "35ウェトンの個別性格は収録済み20件のみ。未収録はネプツヌ合計＋パサラン性格から解釈",
        ],
    }
