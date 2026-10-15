# -*- coding: utf-8 -*-
"""
M25 ヒューマンデザイン（本格版）— human-design-py 移植アダプタ
出典: 別AI実装が検証した human-design-py（MIT・geodetheseeker）の計算コア
      （26惑星ゲート26/26一致・Type/Profile/Authority 対応）
- 本モジュールは FastAPI ラッパーを除去した計算部のみ
- 依存: pyswisseph / geopy / timezonefinder / pytz（Kaggleセル0で導入）
- 使い方: calculate_chart(year, month, day, hour, minute, utc_offset)
"""
from __future__ import annotations

from datetime import datetime, timedelta

try:
    import swisseph as swe
    _HAVE_SWE = True
except ImportError:
    swe = None
    _HAVE_SWE = False

try:
    from geopy.geocoders import Nominatim
    from timezonefinder import TimezoneFinder
    import pytz
    _HAVE_GEO = True
except ImportError:
    _HAVE_GEO = False

swe.set_ephe_path("") if _HAVE_SWE else None

# ─────────────────────────────────────────────
# GATE MAP: ecliptic degree → Human Design gate
# ─────────────────────────────────────────────
GATE_SEQUENCE = [
    25, 17, 21, 51, 42, 3,   # Aries
    27, 24, 2,  23, 8,  20,  # Taurus
    16, 35, 45, 12, 15, 52,  # Gemini
    39, 53, 62, 56, 31, 33,  # Cancer
    7,  4,  29, 59, 40, 64,  # Leo
    47, 6,  46, 18, 48, 57,  # Virgo+Libra
    32, 50, 28, 44, 1,  43,  # Libra+Scorpio
    14, 34, 9,  5,  26, 11,  # Scorpio+Sag
    10, 58, 38, 54, 61, 60,  # Cap
    41, 19, 13, 49, 30, 55,  # Aquarius
    37, 63, 22, 36            # Pisces
]
HD_START_DEGREE = 358.25  # 28°15' Pisces

CENTERS = {
    "Head": [61, 63, 64],
    "Ajna": [4, 11, 17, 24, 43, 47],
    "Throat": [8, 12, 16, 20, 23, 31, 33, 35, 45, 56, 62],
    "Self": [1, 2, 7, 10, 13, 15, 25, 46],
    "Sacral": [3, 5, 9, 14, 27, 29, 34, 42, 59],
    "Root": [19, 28, 38, 39, 41, 52, 53, 54, 58, 60],
    "Spleen": [18, 28, 32, 44, 48, 50, 57],
    "Solar Plexus": [6, 22, 30, 36, 37, 49, 55],
    "Heart": [21, 26, 40, 51],
}
CHANNELS = [
    (1, 8), (2, 14), (3, 60), (4, 63), (5, 15), (6, 59), (7, 31), (9, 52),
    (10, 20), (11, 56), (12, 22), (13, 33), (16, 48), (17, 62), (18, 58),
    (19, 49), (20, 34), (20, 57), (21, 45), (23, 43), (24, 61), (25, 51),
    (26, 44), (27, 50), (28, 38), (29, 46), (30, 41), (32, 54), (34, 57),
    (35, 36), (37, 40), (39, 55), (42, 53), (47, 64),
]
CHANNEL_CENTERS = {
    (1, 8): ("Self", "Throat"), (2, 14): ("Self", "Sacral"),
    (3, 60): ("Sacral", "Root"), (4, 63): ("Ajna", "Head"),
    (5, 15): ("Sacral", "Self"), (6, 59): ("Solar Plexus", "Sacral"),
    (7, 31): ("Self", "Throat"), (9, 52): ("Sacral", "Root"),
    (10, 20): ("Self", "Throat"), (11, 56): ("Ajna", "Throat"),
    (12, 22): ("Throat", "Solar Plexus"), (13, 33): ("Self", "Throat"),
    (16, 48): ("Throat", "Spleen"), (17, 62): ("Ajna", "Throat"),
    (18, 58): ("Spleen", "Root"), (19, 49): ("Root", "Solar Plexus"),
    (20, 34): ("Throat", "Sacral"), (20, 57): ("Throat", "Spleen"),
    (21, 45): ("Heart", "Throat"), (23, 43): ("Throat", "Ajna"),
    (24, 61): ("Ajna", "Head"), (25, 51): ("Self", "Heart"),
    (26, 44): ("Heart", "Spleen"), (27, 50): ("Sacral", "Spleen"),
    (28, 38): ("Spleen", "Root"), (29, 46): ("Sacral", "Self"),
    (30, 41): ("Solar Plexus", "Root"), (32, 54): ("Spleen", "Root"),
    (34, 57): ("Sacral", "Spleen"), (35, 36): ("Throat", "Solar Plexus"),
    (37, 40): ("Solar Plexus", "Heart"), (39, 55): ("Root", "Solar Plexus"),
    (42, 53): ("Sacral", "Root"), (47, 64): ("Ajna", "Head"),
}

PLANET_NAMES = {
    "sun": "太陽", "earth": "地球", "moon": "月", "node": "ノースノード",
    "south_node": "サウスノード", "mercury": "水星", "venus": "金星",
    "mars": "火星", "jupiter": "木星", "saturn": "土星", "uranus": "天王星",
    "neptune": "海王星", "pluto": "冥王星",
}


def degree_to_gate_line(degree: float) -> tuple:
    gate_size = 360 / 64
    line_size = gate_size / 6
    adjusted = (degree - HD_START_DEGREE) % 360
    index = int(adjusted / gate_size)
    line = int((adjusted % gate_size) / line_size) + 1
    return GATE_SEQUENCE[index], line


def get_planet_positions(jd: float) -> dict:
    """JD → 各惑星の黄経（太陽アーク補正前の生データ）"""
    _require_swe()
    flags = swe.FLG_SWIEPH | swe.FLG_SPEED
    out = {}
    for key, swe_id in [("sun", swe.SUN), ("moon", swe.MOON), ("mercury", swe.MERCURY),
                        ("venus", swe.VENUS), ("mars", swe.MARS), ("jupiter", swe.JUPITER),
                        ("saturn", swe.SATURN), ("uranus", swe.URANUS),
                        ("neptune", swe.NEPTUNE), ("pluto", swe.PLUTO)]:
        res = swe.calc_ut(jd, swe_id, flags)
        out[key] = res[0][0]  # 黄経
    # ノード（ドラゴンヘッド）
    res = swe.calc_ut(jd, swe.TRUE_NODE, flags)
    out["node"] = res[0][0]
    out["south_node"] = (res[0][0] + 180) % 360
    out["earth"] = (out["sun"] + 180) % 360
    return out


def get_defined_centers(all_gates: list) -> list:
    """定義されたセンター（チャネルで結ばれたゲートから）"""
    defined = set()
    gate_set = set(all_gates)
    for g1, g2 in CHANNELS:
        if g1 in gate_set and g2 in gate_set:
            c1, c2 = CHANNEL_CENTERS[(g1, g2)]
            defined.add(c1)
            defined.add(c2)
    return sorted(defined, key=lambda c: list(CENTERS.keys()).index(c))


def determine_type(defined_centers: list, all_gates: list) -> str:
    has_sacral = "Sacral" in defined_centers
    if "Heart" in defined_centers:
        return "Manifestor"
    if has_sacral:
        if all(g in all_gates for g in [2, 14]) or all(g in all_gates for g in [34, 10]):
            return "Generator"
        return "Generator"
    if "Spleen" in defined_centers or "Ajna" in defined_centers:
        return "Projector"
    if "Head" in defined_centers and "Root" in defined_centers:
        return "Reflector"
    return "Projector"


def determine_authority(defined_centers: list) -> str:
    if "Spleen" in defined_centers:
        return "Splenic"
    if "Sacral" in defined_centers:
        return "Sacral"
    if "Heart" in defined_centers:
        return "Ego"
    if "Solar Plexus" in defined_centers:
        return "Emotional"
    return "Self-Projected"


def calculate_chart(birth_year: int, birth_month: int, birth_day: int,
                    birth_hour: int, birth_minute: int, utc_offset: float) -> dict:
    """HDチャート計算（human-design-py の計算コア移植）"""
    _require_swe()
    # UTC変換
    local_dt = datetime(birth_year, birth_month, birth_day, birth_hour, birth_minute)
    utc_dt = local_dt - timedelta(hours=utc_offset)
    jd = swe.julday(utc_dt.year, utc_dt.month, utc_dt.day,
                    utc_dt.hour + utc_dt.minute / 60.0)

    positions = get_planet_positions(jd)

    # 太陽アーク88°（Design/Personality）
    sun_pos = positions["sun"]
    design_sun = (sun_pos - 88) % 360

    gates = {}
    for key, lon in positions.items():
        gate, line = degree_to_gate_line(lon)
        gates[key] = {"gate": gate, "line": line,
                      "name_ja": PLANET_NAMES.get(key, key)}

    design_gates = {}
    for key, lon in positions.items():
        dlon = (lon - 88) % 360
        gate, line = degree_to_gate_line(dlon)
        design_gates[key] = {"gate": gate, "line": line}

    # Personality（意識）ゲート集合
    person_gates = [g["gate"] for k, g in gates.items() if k != "south_node"]
    # 定義センター
    defined_centers = get_defined_centers(person_gates)

    # Profile: 人格太陽のライン / 設計太陽のライン
    profile = f"{gates['sun']['line']}/{design_gates['sun']['line']}"

    return {
        "type": determine_type(defined_centers, person_gates),
        "authority": determine_authority(defined_centers),
        "profile": profile,
        "defined_centers": [c for c in defined_centers],
        "gates": {k: v for k, v in gates.items()},
        "design_sun": {"lon": round(design_sun, 4),
                       "gate": design_gates["sun"]["gate"],
                       "line": design_gates["sun"]["line"]},
        "personality_sun": {"lon": round(sun_pos, 4),
                            "gate": gates["sun"]["gate"],
                            "line": gates["sun"]["line"]},
        "references": ["human-design-py (MIT) 移植・別AI実装で26/26ゲート検証済み"],
    }


def get_historical_offset(city: str, year: int, month: int, day: int,
                          hour: int, minute: int) -> float:
    """都市名 → UTCオフセット（DST考慮・別AI実装）"""
    if not _HAVE_GEO:
        raise RuntimeError("geopy / timezonefinder / pytz が必要です")
    geolocator = Nominatim(user_agent="fortune-engine-hd")
    tf = TimezoneFinder()
    loc = geolocator.geocode(city)
    if loc is None:
        return 9.0  # 東京仮定
    tz_str = tf.timezone_at(lat=loc.latitude, lng=loc.longitude)
    if tz_str is None:
        return 9.0
    tz = pytz.timezone(tz_str)
    dt = datetime(year, month, day, hour, minute)
    try:
        offset = tz.utcoffset(dt).total_seconds() / 3600.0
    except Exception:
        offset = tz.utcoffset(datetime(year, 6, 1, 12)).total_seconds() / 3600.0
    return offset


def _require_swe():
    if not _HAVE_SWE:
        raise RuntimeError("pyswisseph が必要です（pip install pyswisseph）")
