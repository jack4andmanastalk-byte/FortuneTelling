# -*- coding: utf-8 -*-
"""
節気（二十四節気）・立春判定 — sxtwl 委譲アダプタ
仕様：計算ロジック仕様書 §4.1（立春境界）・§2.3（節気基準）
- 九星気学・干支（年柱）・六星占術・動物占いの「年」は立春（2/3〜5）基準
"""
from __future__ import annotations

from datetime import date

try:
    import sxtwl
    _HAVE_SXTWL = True
except ImportError:
    sxtwl = None
    _HAVE_SXTWL = False

# 節気コード（sxtwl）: 0=冬至,1=小寒,2=大寒,3=立春,4=雨水,5=啓蟄,6=春分,7=清明,
#                      8=穀雨,9=立夏,10=小満,11=芒種,12=夏至,13=小暑,14=大暑,15=立秋,
#                      16=処暑,17=白露,18=秋分,19=寒露,20=霜降,21=立冬,22=小雪,23=大雪
JIEQI_NAMES = ["冬至", "小寒", "大寒", "立春", "雨水", "啓蟄", "春分", "清明",
               "穀雨", "立夏", "小満", "芒種", "夏至", "小暑", "大暑", "立秋",
               "処暑", "白露", "秋分", "寒露", "霜降", "立冬", "小雪", "大雪"]
NO_JIEQI = 255  # sxtwl: 節気なし


def _require_sxtwl():
    if not _HAVE_SXTWL:
        raise RuntimeError("sxtwl が必要です（pip install sxtwl）")


def jieqi_on(d: date):
    """指定日の節気コード（なければ None）"""
    _require_sxtwl()
    day = sxtwl.fromSolar(d.year, d.month, d.day)
    code = day.getJieQi()
    if code == NO_JIEQI or not day.hasJieQi():
        return None
    return int(code)


def jieqi_name_on(d: date):
    """指定日の節気名（なければ None）"""
    code = jieqi_on(d)
    return JIEQI_NAMES[code] if code is not None else None


def lichun_date(year: int) -> date:
    """その年の立春の日付（節分の翌日）"""
    _require_sxtwl()
    # 2/1〜2/10 を走査して立春(3)を探す
    for day in range(1, 11):
        d = date(year, 2, day)
        if jieqi_on(d) == 3:
            return d
    raise ValueError(f"立春が見つかりません: {year}")


def effective_year_for_lichun(d: date) -> int:
    """
    立春基準の「占い上の年」。
    立春前（1/1〜立春前日）は前年扱い。
    """
    lc = lichun_date(d.year)
    return d.year if d >= lc else d.year - 1
