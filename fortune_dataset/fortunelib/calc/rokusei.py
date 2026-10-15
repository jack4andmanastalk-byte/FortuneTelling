# -*- coding: utf-8 -*-
"""
M10 六星占術 — 計算モジュール（確定版）
仕様: データ定義書（rokusei_data.json）
- 運命数 = 年運数 + 月オフセット + 日（61以上は60を引く）
- 星人 = 運命数の区分（1-10土星人〜51-60水星人）
- プラス/マイナス = 生まれ年の十二支（陽支=+・陰支=−・立春前は前年扱い）
- 12周期 + 大殺界（陰影・停止・減退の3年）= 種子の年（基準年）から12年周期
出典: masanosuke.net（年運数表・計算式・2026年運気表）／izumotaisha.or.jp／note.com
※ 細木数子氏の六星占術は商標体系のため、本実装は公開情報に基づく近似（出典明記）
"""
from __future__ import annotations

from datetime import date

from ..data import load_json
from .jieqi import effective_year_for_lichun

_DATA = None


def _data():
    global _DATA
    if _DATA is None:
        _DATA = load_json("rokusei_data.json")
    return _DATA


def year_unnsu(year: int) -> int:
    """年運数（公開テーブル1960-2004優先・範囲外は両端から±11で補間）"""
    d = _data()
    key = str(year)
    if key in d["year_unnsu"]:
        return d["year_unnsu"][key]
    if year < 1960:
        v = (15 - 11 * (1960 - year)) % 60
    else:
        v = (55 + 11 * (year - 2004)) % 60
    return 60 if v == 0 else v


def unmei_number(y: int, m: int, d: int) -> int:
    """運命数（1〜60）"""
    data = _data()
    total = year_unnsu(y) + data["month_offset"][str(m)] + d
    if total > 60:
        total -= 60
    return total


def star_type(unmei_no: int) -> str:
    """運命数 → 星人"""
    d = _data()
    for r in d["star_ranges"]:
        if r["min"] <= unmei_no <= r["max"]:
            return r["star"]
    raise ValueError(f"運命数が範囲外: {unmei_no}")


def plus_minus(y: int, m: int, d: int) -> str:
    """プラス/マイナス（生まれ年の十二支・立春前は前年）"""
    eff_year = effective_year_for_lichun(date(y, m, d))
    zhi = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"][(eff_year - 4) % 12]
    d = _data()
    if zhi in d["plus_branches"]:
        return "プラス"
    return "マイナス"


def fortune_type(unmei_no: int, pm: str) -> str:
    """星人+± → タイプ名（例: 水星人プラス）"""
    return f"{star_type(unmei_no)}{pm}"


def cycle_for_year(ftype: str, target_year: int) -> dict:
    """
    対象年の12周期と大殺界判定。

    Args:
        ftype: タイプ名（例: 水星人プラス）
        target_year: 対象年（西暦）

    Returns:
        {"cycle": 周期名, "is_daissakai": bool, "daissakai_type": "大殺界"/"中殺界"/"小殺界"/None}
    """
    d = _data()
    seed = d["seed_year"].get(ftype)
    if seed is None:
        return {"cycle": None, "is_daissakai": False, "daissakai_type": None}
    idx = (target_year - seed) % 12
    cycle = d["cycles"][idx]
    is_ds = cycle in d["daissakai_cycles"]
    ds_type = None
    if is_ds:
        if cycle == "停止":
            ds_type = "大殺界"
        elif cycle == "陰影":
            ds_type = "中殺界"  # 大殺界の入口
        else:  # 減退
            ds_type = "小殺界"  # 大殺界の出口
    return {"cycle": cycle, "is_daissakai": is_ds, "daissakai_type": ds_type}


def _sakkai_of(cycle: str) -> dict:
    """周期名 → 殺界の種別（年運・月運・日運で共通）。"""
    d = _data()
    if cycle in d["daissakai_cycles"]:
        return {"is_daissakai": True,
                "daissakai_type": {"陰影": "大殺界", "停止": "大殺界",
                                   "減退": "大殺界"}[cycle]}
    return {"is_daissakai": False, "daissakai_type": None}


def cycle_for_month(ftype: str, month: int) -> dict:
    """
    対象月の12周期。月運は暦月で巡り、毎年同じ月に同じ運気が来る
    （年運とは独立したサイクル）。

    Args:
        ftype: タイプ名（例: 水星人プラス）
        month: 対象月（1-12）

    Returns:
        {"cycle": 周期名, "is_daissakai": bool, "daissakai_type": str|None}
    """
    d = _data()
    off = d["month_cycle_offset"].get(ftype)
    if off is None:
        return {"cycle": None, "is_daissakai": False, "daissakai_type": None}
    cycle = d["cycles"][(off + (month - 1)) % 12]
    return {"cycle": cycle, **_sakkai_of(cycle)}


def cycle_for_day(ftype: str, target: date) -> dict:
    """
    対象日の12周期。日運はグレゴリオ通日で1日ずつ進む。

    Args:
        ftype: タイプ名（例: 水星人プラス）
        target: 対象日

    Returns:
        {"cycle": 周期名, "is_daissakai": bool, "daissakai_type": str|None}
    """
    d = _data()
    off = d["month_cycle_offset"].get(ftype)
    if off is None:
        return {"cycle": None, "is_daissakai": False, "daissakai_type": None}
    k = d.get("day_ordinal_k", 1)
    cycle = d["cycles"][(off + target.toordinal() + k) % 12]
    return {"cycle": cycle, **_sakkai_of(cycle)}


def rokusei_calc(y: int, m: int, d: int, target_year: int | None = None,
                 target: date | None = None) -> dict:
    """
    六星占術の総合計算。

    Returns:
        dict: 運命数・星人・±・タイプ・対象年の周期・大殺界
    """
    un = unmei_number(y, m, d)
    pm = plus_minus(y, m, d)
    ftype = fortune_type(un, pm)
    target = target or date.today()
    target_year = target_year or target.year
    cyc = cycle_for_year(ftype, target_year)
    mon = cycle_for_month(ftype, target.month)
    day = cycle_for_day(ftype, target)
    return {
        "unmei_number": un,
        "star": star_type(un),
        "plus_minus": pm,
        "type": ftype,
        "target_year": target_year,
        "target_date": target.isoformat(),
        **cyc,
        "month_cycle": mon["cycle"],
        "month_is_daissakai": mon["is_daissakai"],
        "month_daissakai_type": mon["daissakai_type"],
        "day_cycle": day["cycle"],
        "day_is_daissakai": day["is_daissakai"],
        "day_daissakai_type": day["daissakai_type"],
        "references": ["data/rokusei_data.json"],
        "notes": [
            "細木数子氏の六星占術は商標体系のため、公開情報（masanosuke.net等）に基づく近似実装",
            "年運数は1960-2004の公開テーブル・範囲外は規則補間（1975/1990は公開値）",
            "大殺界の3年は陰影（入口）→停止（最中）→減退（出口）の順",
            "月運は暦月で巡り毎年同じ月に同じ運気が来る（年運とは独立）",
            "日運はグレゴリオ通日で1日ずつ進む",
            "月運・日運は複数の公開表（netoff・spicomi・messengersnote・plus-a）と照合済み",
        ],
    }
