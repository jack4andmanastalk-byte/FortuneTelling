# -*- coding: utf-8 -*-
"""
M18〜M19・M25 西洋占星術／ヴェーダ占星術／ヒューマンデザイン（簡易） — pyswisseph 委譲アダプタ
仕様：計算ロジック仕様書 §4.13〜4.14・4.18
- 惑星黄経・ハウスカスプ（プラシーダス）・アスペクト：pyswisseph
- ヴェーダ：アヤナムシャ（ラヒリ）でサイデリアル化＋ナクシャトラ
- HD（簡易）：太陽黄経 → 64ゲート
- 真太陽時：均時差（equation_of_time）
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta

try:
    import swisseph as swe
    _HAVE_SWE = True
except ImportError:
    swe = None
    _HAVE_SWE = False

JST = timezone(timedelta(hours=9))
FLG = None  # calc_ut 用フラグ（遅延初期化）

PLANETS = [
    ("太陽", swe.SUN), ("月", swe.MOON), ("水星", swe.MERCURY), ("金星", swe.VENUS),
    ("火星", swe.MARS), ("木星", swe.JUPITER), ("土星", swe.SATURN),
    ("天王星", swe.URANUS), ("海王星", swe.NEPTUNE), ("冥王星", swe.PLUTO),
] if _HAVE_SWE else []

SIGNS_JA = ["牡羊座", "牡牛座", "双子座", "蟹座", "獅子座", "乙女座",
            "天秤座", "蠍座", "射手座", "山羊座", "水瓶座", "魚座"]
SIGNS_EN = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
            "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]

NAKSHATRAS = [
    "アシュウィニー", "バラニー", "クリッティカー", "ローヒニー", "ムリガシラー", "アードラー",
    "プナルヴァスー", "プシュヤ", "アシュレーシャー", "マガー", "プールヴァ・ファルグニー",
    "ウッタラ・ファルグニー", "ハスタ", "チートラー", "スヴァーティー", "ヴィシャーカー",
    "アヌラーダー", "ジェーシュター", "ムーラ", "プールヴァ・アーシャーダー",
    "ウッタラ・アーシャーダー", "シュラヴァナ", "ダニシュター", "シャタビシャ",
    "プールヴァ・バードラパダー", "ウッタラ・バードラパダー", "レヴァティー",
]

ASPECTS = [(0, "コンジャンクション"), (60, "セクスタイル"), (90, "スクエア"),
           (120, "トライン"), (180, "オポジション")]
ORB = {swe.SUN: 8.0, swe.MOON: 8.0} if _HAVE_SWE else {}

HD_GATES = [  # 太陽黄経 → ゲート番号（簡易・黄経5.625°刻み）
    "自己表現", "方向性", "秩序", "答え", "タイミング", "摩擦", "役割", "貢献",
    "集中", "自己", "アイデア", "慎重", "協力", "力", "極端", "スキル",
    "意見", "修正", "欲求", "現状", "ハンター", "開かれる", "同化", "合理化",
    "無邪気", "自己変革", "思いやり", "ゲーム", "固執", "感情", "リーダー", "持続",
    "撤退", "偉大", "変化", "危機", "友情", "戦士", "妨害", "解放",
    "減少", "成長", "突破", "不寛容", "集合", "決定", "順応", "深み",
    "原理", "価値", "覚醒", "静止", "後退", "野心", "精神", "豊かさ",
    "直感", "完成", "親密", "現実", "詳細", "誠実", "疑い", "迷い",
]


def _flags():
    global FLG
    if FLG is None:
        FLG = swe.FLG_SWIEPH | swe.FLG_SPEED
    return FLG


def _require_swe():
    if not _HAVE_SWE:
        raise RuntimeError("pyswisseph が必要です（pip install pyswisseph）")


def to_jd(y: int, m: int, d: int, hour: float, tz_offset_h: float = 9.0) -> float:
    """ローカル標準時 → ユリウス日（UT）"""
    _require_swe()
    return swe.julday(y, m, d, hour - tz_offset_h)


def planet_longitudes(jd: float) -> dict:
    """JD → 各惑星の黄経（トロピカル）・サイン・度数"""
    _require_swe()
    out = {}
    for name, p in PLANETS:
        res = swe.calc_ut(jd, p, _flags())
        lon = res[0][0]
        sign_idx = int(lon // 30)
        out[name] = {
            "lon": round(lon, 4),
            "sign": SIGNS_JA[sign_idx],
            "sign_en": SIGNS_EN[sign_idx],
            "deg_in_sign": round(lon % 30, 4),
        }
    return out


def houses(jd: float, lat: float, lon: float, sys: bytes = b"P") -> dict:
    """ハウスカスプ（既定: プラシーダス）＋ASC・MC

    ★BUG-11（2026-08-17 実機で判明）: 従来は黄経（度数）しか返しておらず、
      ASC=43.18° を LLM が自力で星座に換算しようとして「双子座」と誤答した
      （正しくは牡牛座 13.2°）。本プロジェクトの原則は「計算はコード・
      解釈のみLLM」なので、星座名まで確定させて渡す。
    """
    _require_swe()
    cusps, ascmc = swe.houses_ex(jd, lat, lon, sys)
    asc_lon = round(ascmc[0], 4)
    mc_lon = round(ascmc[1], 4)
    return {
        "cusps": [round(c, 4) for c in cusps],
        "cusps_signs": [SIGNS_JA[int(c // 30) % 12] for c in cusps],
        "asc": asc_lon,
        "asc_sign": SIGNS_JA[int(asc_lon // 30) % 12],
        "asc_deg_in_sign": round(asc_lon % 30, 4),
        "mc": mc_lon,
        "mc_sign": SIGNS_JA[int(mc_lon // 30) % 12],
        "mc_deg_in_sign": round(mc_lon % 30, 4),
    }


def aspects(planets: dict, orb_sun_moon: float = 8.0, orb_other: float = 6.0) -> list:
    """惑星間アスペクト（orb 内のみ）"""
    _require_swe()
    names = list(planets.keys())
    res = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            d = abs(planets[a]["lon"] - planets[b]["lon"]) % 360
            d = min(d, 360 - d)
            p1, p2 = planets[a], planets[b]
            orb = orb_sun_moon if (a in ("太陽", "月") or b in ("太陽", "月")) else orb_other
            for angle, name in ASPECTS:
                if abs(d - angle) <= orb:
                    res.append({
                        "p1": a, "p2": b,
                        "aspect": name, "angle": angle,
                        "orb": round(abs(d - angle), 2),
                        "exact": round(d, 2),
                    })
    return res


def natal_chart(y: int, m: int, d: int, hour: float, lat: float, lon: float,
                tz_offset_h: float = 9.0) -> dict:
    """出生図（トロピカル・プラシーダス）"""
    jd = to_jd(y, m, d, hour, tz_offset_h)
    pl = planet_longitudes(jd)
    hs = houses(jd, lat, lon)
    return {
        "jd": round(jd, 6),
        "planets": pl,
        "houses": hs,
        "aspects": aspects(pl),
    }


def transit_chart(birth: dict, now: datetime | None = None) -> dict:
    """トランジット（現在の惑星位置と出生図の関係）"""
    now = now or datetime.now(JST)
    jd = swe.julday(now.year, now.month, now.day, now.hour + now.minute / 60 - 9.0)
    pl = planet_longitudes(jd)
    aspects_birth = []
    birth_pl = birth["planets"]
    for name, cur in pl.items():
        if name in birth_pl:
            d = abs(cur["lon"] - birth_pl[name]["lon"]) % 360
            d = min(d, 360 - d)
            for angle, aname in ASPECTS:
                orb = 8.0 if name in ("太陽", "月") else 6.0
                if abs(d - angle) <= orb:
                    aspects_birth.append({"planet": name, "aspect": aname,
                                          "angle": angle, "orb": round(abs(d - angle), 2)})
    return {"transit_jd": round(jd, 6), "transit_planets": pl,
            "aspects_to_natal": aspects_birth}


def ayanamsa_lahiri(jd: float) -> float:
    """Lahiri アヤナムシャ（明示的に設定。pyswisseph 2.10系のデフォルトは Fagan/Bradley のため）"""
    _require_swe()
    try:
        swe.set_sid_mode(swe.SIDM_LAHIRI)
    except Exception:
        pass
    return swe.get_ayanamsa_ut(jd)


def vedic_sidereal(jd: float) -> dict:
    """ヴェーダ（サイデリアル・ラヒリ）簡易：惑星サイデリアル黄経＋ナクシャトラ＋ラグナ"""
    _require_swe()
    aya = ayanamsa_lahiri(jd)
    pl = {}
    for name, p in PLANETS:
        res = swe.calc_ut(jd, p, _flags())
        lon_sid = (res[0][0] - aya) % 360
        sign_idx = int(lon_sid // 30)
        naks = int(lon_sid // (360 / 27))
        pl[name] = {
            "lon_sidereal": round(lon_sid, 4),
            "sign": SIGNS_JA[sign_idx],
            "nakshatra": NAKSHATRAS[naks],
            "nakshatra_pada": int((lon_sid % (360 / 27)) // (360 / 27 / 4)) + 1,
        }
    # ラグナ（ASC サイデリアル）
    cusps, ascmc = swe.houses_ex(jd, 35.6895, 139.6917, b"P")
    asc_sid = (ascmc[0] - aya) % 360
    return {"ayanamsa": round(aya, 4), "planets": pl,
            "lagna": {"lon": round(asc_sid, 4), "sign": SIGNS_JA[int(asc_sid // 30)]}}


def human_design(y: int, m: int, d: int, hour: float, lat: float, lon: float,
                 tz_offset_h: float = 9.0) -> dict:
    """ヒューマンデザイン（簡易）：太陽・地球の64ゲート＋ライン"""
    _require_swe()
    jd = to_jd(y, m, d, hour, tz_offset_h)
    res = swe.calc_ut(jd, swe.SUN, _flags())
    sun_lon = res[0][0]
    earth_lon = (sun_lon + 180) % 360

    def gate_of(lon):
        gate = int(lon // 5.625) + 1  # 1-64
        line = int((lon % 5.625) // (5.625 / 6)) + 1  # 1-6
        return gate, line

    sg, sl = gate_of(sun_lon)
    eg, el = gate_of(earth_lon)
    return {
        "sun": {"lon": round(sun_lon, 4), "gate": sg, "line": sl, "gate_name": HD_GATES[sg - 1]},
        "earth": {"lon": round(earth_lon, 4), "gate": eg, "line": el, "gate_name": HD_GATES[eg - 1]},
        "notes": ["簡易版（チャネル・タイプ・オーソリティの本格的計算はPhase 2後半で拡張）"],
    }
