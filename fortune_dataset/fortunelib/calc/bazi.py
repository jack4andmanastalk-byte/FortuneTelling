# -*- coding: utf-8 -*-
"""
M17 四柱推命（八字命理）— sxtwl 委譲アダプタ
仕様：計算ロジック仕様書 §4.12
- 四柱（年・月・日・時柱）の干支：sxtwl（寿星天文暦）
- 蔵干・十神・十二運・空亡・納音・大運（順逆・起運年齢）：本モジュールで決定論的に算出
- 真太陽時補正（経度＋均時差）に対応
"""
from __future__ import annotations

from datetime import date, datetime

from .eto import JIKKAN, JUNISHI, year_ganzhi
from .jieqi import _HAVE_SXTWL, effective_year_for_lichun

GZ60 = [(JIKKAN[g] + JUNISHI[z]) for g in range(10) for z in range(12)]
# 60干支の番号辞書（甲子=0 ... 癸亥=59）
GZ60_IDX = {}
for _n in range(60):
    g, z = _n % 10, _n % 12
    GZ60_IDX[(g, z)] = _n

# 五行（十干）
GAN_WUXING = {
    "甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
    "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水",
}
GAN_YINYANG = {
    "甲": "陽", "乙": "陰", "丙": "陽", "丁": "陰", "戊": "陽",
    "己": "陰", "庚": "陽", "辛": "陰", "壬": "陽", "癸": "陰",
}
SHENG = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
KE = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}

# 蔵干（地支 → 本気・中気・余気）
CANG_GAN = {
    "子": ["癸"], "丑": ["己", "癸", "辛"], "寅": ["甲", "丙", "戊"],
    "卯": ["乙"], "辰": ["戊", "乙", "癸"], "巳": ["丙", "戊", "庚"],
    "午": ["丁", "己"], "未": ["己", "丁", "乙"], "申": ["庚", "壬", "戊"],
    "酉": ["辛"], "戌": ["戊", "辛", "丁"], "亥": ["壬", "甲"],
}

# 十二運（陽干順行表: 長生=1 から 地支順）※ 陰干は逆行（陽生陰死）
SHIER_YUN_NAMES = ["長生", "沐浴", "冠帯", "建禄", "帝旺", "衰", "病", "死", "墓", "絶", "胎", "養"]
_YANG_CHANGSHENG = {"甲": 11, "丙": 2, "戊": 2, "庚": 5, "壬": 8}  # 長生の地支 index（亥=11, 寅=2, 巳=5, 申=8）
_YIN_CHANGSHENG = {"乙": 6, "丁": 8, "己": 8, "辛": 0, "癸": 3}   # 陰干は陽干の逆行（長生: 午=6, 酉=8, 子=0, 卯=3）


def shier_yun(day_gan: str, zhi: str) -> str:
    """十二運（日干 vs 地支）"""
    z = JUNISHI.index(zhi)
    if day_gan in _YANG_CHANGSHENG:
        cs = _YANG_CHANGSHENG[day_gan]
        idx = (z - cs) % 12
    else:
        cs = _YIN_CHANGSHENG[day_gan]
        idx = (cs - z) % 12  # 陰干は逆行
    return SHIER_YUN_NAMES[idx]


def shishen(day_gan: str, other_gan: str) -> str:
    """十神（日干 vs 他干）"""
    if day_gan == other_gan:
        return "比肩"
    wx_d, wx_o = GAN_WUXING[day_gan], GAN_WUXING[other_gan]
    yy_d, yy_o = GAN_YINYANG[day_gan], GAN_YINYANG[other_gan]
    same_yy = (yy_d == yy_o)
    if wx_d == wx_o:             # 同五行（異干）
        return "比肩" if same_yy else "劫財"
    if SHENG[wx_d] == wx_o:      # 日干が生む
        return "食神" if same_yy else "傷官"
    if KE[wx_d] == wx_o:         # 日干が克つ
        return "偏財" if same_yy else "正財"
    if SHENG[wx_o] == wx_d:      # 日干を生む（印）
        return "偏印" if same_yy else "正印"
    if KE[wx_o] == wx_d:         # 日干を克す（官殺）
        return "七殺" if same_yy else "正官"
    return "比肩"  # 到達しない


# 納音30種（干支ペア → 納音）
#  mts5.63: 「白蠟金」は**同梱の日本語フォントに「蠟」が無く**、四柱推命（M17_bazi）の
#  型Cチャートで1文字欠けて描画されました（庚辰・辛巳の日柱のとき）。日本語の表記
#  「白蝋金」へ直しています（「蝋」は収録あり。mts5.62 の実機で見つけた「闰」と同種）。
NAYIN = {
    ("甲", "子"): "海中金", ("乙", "丑"): "海中金", ("丙", "寅"): "炉中火", ("丁", "卯"): "炉中火",
    ("戊", "辰"): "大林木", ("己", "巳"): "大林木", ("庚", "午"): "路旁土", ("辛", "未"): "路旁土",
    ("壬", "申"): "剣鋒金", ("癸", "酉"): "剣鋒金", ("甲", "戌"): "山頭火", ("乙", "亥"): "山頭火",
    ("丙", "子"): "澗下水", ("丁", "丑"): "澗下水", ("戊", "寅"): "城頭土", ("己", "卯"): "城頭土",
    ("庚", "辰"): "白蝋金", ("辛", "巳"): "白蝋金", ("壬", "午"): "楊柳木", ("癸", "未"): "楊柳木",
    ("甲", "申"): "泉中水", ("乙", "酉"): "泉中水", ("丙", "戌"): "屋上土", ("丁", "亥"): "屋上土",
    ("戊", "子"): "霹靂火", ("己", "丑"): "霹靂火", ("庚", "寅"): "松柏木", ("辛", "卯"): "松柏木",
    ("壬", "辰"): "長流水", ("癸", "巳"): "長流水", ("甲", "午"): "砂中金", ("乙", "未"): "砂中金",
    ("丙", "申"): "山下火", ("丁", "酉"): "山下火", ("戊", "戌"): "平地木", ("己", "亥"): "平地木",
    ("庚", "子"): "壁上土", ("辛", "丑"): "壁上土", ("壬", "寅"): "金箔金", ("癸", "卯"): "金箔金",
    ("甲", "辰"): "覆灯火", ("乙", "巳"): "覆灯火", ("丙", "午"): "天河水", ("丁", "未"): "天河水",
    ("戊", "申"): "大驛土", ("己", "酉"): "大驛土", ("庚", "戌"): "釵釧金", ("辛", "亥"): "釵釧金",
    ("壬", "子"): "桑柘木", ("癸", "丑"): "桑柘木", ("甲", "寅"): "大溪水", ("乙", "卯"): "大溪水",
    ("丙", "辰"): "沙中土", ("丁", "巳"): "沙中土", ("戊", "午"): "天上火", ("己", "未"): "天上火",
    ("庚", "申"): "石榴木", ("辛", "酉"): "石榴木", ("壬", "戌"): "大海水", ("癸", "亥"): "大海水",
}

# 空亡（旬 → 空亡の支）
KUBO_BY_XUN = {
    0: ["戌", "亥"], 1: ["申", "酉"], 2: ["午", "未"], 3: ["辰", "巳"], 4: ["寅", "卯"], 5: ["子", "丑"],
}


def nayin(gan: str, zhi: str) -> str:
    return NAYIN[(gan, zhi)]


def kubo(day_gan: str, day_zhi: str) -> list:
    """空亡（日柱）"""
    g, z = JIKKAN.index(day_gan), JUNISHI.index(day_zhi)
    n = GZ60_IDX[(g, z)]
    return KUBO_BY_XUN[n // 10]


def _hour_index(hh_mm: str) -> int:
    """時刻（HH:MM）→ 時辰 index（0=子, 1=丑, ...）"""
    h = int(hh_mm.split(":")[0])
    # 23時台は子(0)、0-1時は子、2-3時=丑... 12時=午(6)
    return ((h + 1) // 2) % 12


def true_solar_time(jd_ut: float, lon_east: float, std_meridian: float = 135.0) -> float:
    """
    真太陽時（UT基準）を計算し、現地太陽時（時）を返す。
    true_solar_hour = UT_hour + (std_meridian - lon)/15 + EoT(hour)
    EoT（均時差）は 太陽黄経−太陽赤経 から算出（pyswisseph）。
    ※ 呼び出し側でタイムゾーン変換後の標準時をもとにUTを渡すこと
    """
    try:
        import swisseph as swe
        res = swe.calc_ut(jd_ut, swe.SUN, swe.FLG_SWIEPH)
        lon = res[0][0]
        lat = res[0][1]
        # 黄道傾斜角（真黄道傾斜角）: ECL_NUT の第1要素
        try:
            e_res = swe.calc_ut(jd_ut, swe.ECL_NUT, swe.FLG_SWIEPH)
            eps = e_res[0][0]
        except Exception:
            eps = 23.4392911  # J2000 近似
        ra, _, _ = swe.cotrans((lon, lat, 1.0), eps)  # 黄道→赤道（pyswisseph 2.10は2引数）
        # 均時差（分）= 4 × (視黄経 − 赤経)。正規化して -180〜180 に
        diff = (lon - ra) % 360
        if diff > 180:
            diff -= 360
        eot_min = 4.0 * diff
    except ImportError:
        eot_min = 0.0
    return (jd_ut - int(jd_ut) - 0.5) * 24.0 + (std_meridian - lon_east) / 15.0 + eot_min / 60.0


def bazi_paipan(
    y: int, m: int, d: int,
    hour: int = 12, minute: int = 0,
    lon_east: float | None = None,
    std_meridian: float = 135.0,
    apply_true_solar: bool = True,
    day_boundary: str = "23h",
) -> dict:
    """
    四柱推命の排盤。

    Args:
        y, m, d: 生年月日（グレゴリオ暦）
        hour, minute: 出生時刻（ローカル標準時）
        lon_east: 出生地の東経（None なら真太陽時補正なし）
        std_meridian: 標準時子午線（日本=135°E）
        apply_true_solar: 真太陽時補正の適用有無
        day_boundary: 日界ルール
            - "23h"（既定・多数派）: 23時台は翌日の日柱＋早晚子時（時柱も翌日ベース）
            - "0h": 23時台も当日の日柱（sxtwl デフォルト相当）
      ※ クロスチェック（別AI検証）: sxtwl の getHourGZ はデフォルトで早晚子時=True のため、
         日柱を翌日にしないと「日柱=当日・時柱=翌日ベース」の不整合が生じる。

    Returns:
        dict: 四柱・蔵干・十神・十二運・空亡・納音・大運 など
    """
    _require = __import__("fortunelib.calc.jieqi", fromlist=["_HAVE_SXTWL"])._HAVE_SXTWL
    if not _require:
        raise RuntimeError("四柱推命には sxtwl が必要です（pip install sxtwl）")
    import sxtwl

    # 真太陽時補正
    hh = hour + minute / 60.0
    if apply_true_solar and lon_east is not None:
        import swisseph as swe
        jd_ut = swe.julday(y, m, d, hh - 9.0)  # JST→UT（簡易）
        tst = true_solar_time(jd_ut, lon_east, std_meridian)
        hour_calc = max(0, min(23.999, tst + 9.0))  # 真太陽時（JST系のまま）
    else:
        hour_calc = hh

    hh_calc = int(hour_calc)
    is_23h = (hh_calc == 23)

    # 日界の適用: 23時切替の場合は 23時台を翌日扱い
    use_next_day = (day_boundary == "23h" and is_23h)
    pillar_date = date(y, m, d)
    if use_next_day:
        from datetime import timedelta
        pillar_date = pillar_date + timedelta(days=1)

    day = sxtwl.fromSolar(y, m, d)
    day_p = sxtwl.fromSolar(pillar_date.year, pillar_date.month, pillar_date.day) if use_next_day else day

    # 年柱（元の日付・立春基準 ※ sxtwl は節気対応）
    y_gan, y_zhi = day.getYearGZ().tg, day.getYearGZ().dz
    # 月柱（元の日付・節入り基準）
    m_gan, m_zhi = day.getMonthGZ().tg, day.getMonthGZ().dz
    # 日柱（23時切替なら翌日）
    d_gan, d_zhi = day_p.getDayGZ().tg, day_p.getDayGZ().dz
    # 時柱（早晚子時: 23時切替なら True・0時切替なら False）
    zao_wan = (day_boundary == "23h")
    h_gan, h_zhi = day.getHourGZ(hh_calc, zao_wan).tg, day.getHourGZ(hh_calc, zao_wan).dz

    pillars = {
        "year": JIKKAN[y_gan] + JUNISHI[y_zhi],
        "month": JIKKAN[m_gan] + JUNISHI[m_zhi],
        "day": JIKKAN[d_gan] + JUNISHI[d_zhi],
        "hour": JIKKAN[h_gan] + JUNISHI[h_zhi],
    }
    day_gan = JIKKAN[d_gan]

    # 各柱の詳細
    def pillar_detail(gan_idx, zhi_idx):
        g, z = JIKKAN[gan_idx], JUNISHI[zhi_idx]
        return {
            "gan": g, "zhi": z,
            "gan_wuxing": GAN_WUXING[g],
            "gan_yinyang": GAN_YINYANG[g],
            "zhi_canggan": CANG_GAN[z],
            "shishen": shishen(day_gan, g),
            "shier_yun": shier_yun(day_gan, z),
            "nayin": nayin(g, z),
        }

    detail = {
        "year": pillar_detail(y_gan, y_zhi),
        "month": pillar_detail(m_gan, m_zhi),
        "day": pillar_detail(d_gan, d_zhi),
        "hour": pillar_detail(h_gan, h_zhi),
    }

    # 空亡（日柱）
    k = kubo(JIKKAN[d_gan], JUNISHI[d_zhi])

    # 大運：陽年男/陰年女=順行、陰年男/陽年女=逆行
    yang_year = GAN_YINYANG[JIKKAN[y_gan]] == "陽"
    male = True  # gender は呼び出し側で補正
    shun = (yang_year and male) or (not yang_year and not male)

    return {
        "pillars": pillars,
        "day_master": {"gan": day_gan, "wuxing": GAN_WUXING[day_gan], "yinyang": GAN_YINYANG[day_gan]},
        "detail": detail,
        "kubo": k,
        "true_solar_hour": round(hour_calc, 2) if apply_true_solar else None,
        "day_boundary": day_boundary,
        "daun_direction": "順行" if shun else "逆行",
        "daun": _daun_initial(m_gan, m_zhi, shun),
        "notes": ["大運の起運年齢は簡易計算（性別・正確な節気間日数で補正推奨）",
                  f"日界: {day_boundary}（23時台の日柱は{'翌日' if day_boundary=='23h' else '当日'}扱い）"],
    }


def _daun_initial(m_gan: int, m_zhi: int, shun: bool) -> list:
    """大運（月柱から10年ごと・初運〜5運を返す）"""
    g0, z0 = m_gan, m_zhi
    step = 1 if shun else -1
    res = []
    for i in range(1, 6):
        g = (g0 + step * i) % 10
        z = (z0 + step * i) % 12
        res.append(JIKKAN[g] + JUNISHI[z])
    return res
