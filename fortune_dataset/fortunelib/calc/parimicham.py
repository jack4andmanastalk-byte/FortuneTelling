# -*- coding: utf-8 -*-
"""
M15 パリミチャム（タミルの結婚相性・Porutham）— フル10ポルタム版（統合版）
仕様: タミル占星術の Thirumana Porutham 体系（公開ルール）
- 2人の生年月日 → 月のナクシャトラ（27宿）とラシ（月星座）を計算
- Dina Porutham: 花嫁→新郎のナクシャトラ数え（2,4,6,8,9,11,13,15,18,20,24,26 = Uthamam）
- 同一ナクシャトラの禁忌（Bharani, Aslesha, Jyeshta, Moolam, Dhanishta, Shatabhisha, Poorvabhadra）
- Rasi 6/8（shashtashtama）の警告
出典: tamilsonline.com／astrology.tamilcube.com／lifehoroscope.in（公開ルール）
★ 統合（ProjectA 由来）: フル10ポルタム（36点満点）を porutham_full() として実装。
   Dina3/Gana4/Yoni4/Rasi7/Rasyadhipati5/Rajju5/Vedha2/Vashya2/Mahendra2/SthreeDeergha2
   出典: jyotishgher（Vashya）・saravali/cafeastrology（Yoni）・vedicmarga（Bhakoot）
   parimicham_calc() は後方互換のため簡易スコアを維持しつつ、full を同梱して返す。
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))

# ナクシャトラ27（astrology.py と同一順序）
NAKSHATRAS = [
    "アシュウィニー", "バラニー", "クリッティカー", "ローヒニー", "ムリガシラー", "アードラー",
    "プナルヴァスー", "プシュヤ", "アシュレーシャー", "マガー", "プールヴァ・ファルグニー",
    "ウッタラ・ファルグニー", "ハスタ", "チートラー", "スヴァーティー", "ヴィシャーカー",
    "アヌラーダー", "ジェーシュター", "ムーラ", "プールヴァ・アーシャーダー",
    "ウッタラ・アーシャーダー", "シュラヴァナ", "ダニシュター", "シャタビシャ",
    "プールヴァ・バードラパダー", "ウッタラ・バードラパダー", "レヴァティー",
]

# 同一ナクシャトラが禁忌とされるもの（lifehoroscope.in）
SAME_NIYAZHA = {"バラニー", "アシュレーシャー", "ジェーシュター", "ムーラ",
                "ダニシュター", "シャタビシャ", "プールヴァ・バードラパダー"}

# Dina Porutham で Uthamam となるナクシャトラ数え（lifehoroscope.in）
DINA_UTHAMAM = {2, 4, 6, 8, 9, 11, 13, 15, 18, 20, 24, 26}

# ラシ名（月星座）
RASI_NAMES = ["牡羊", "牡牛", "双子", "蟹", "獅子", "乙女",
              "天秤", "蠍", "射手", "山羊", "水瓶", "魚"]


def _moon_nakshatra_rasi(y: int, m: int, d: int) -> dict:
    """生年月日 → 月のナクシャトラ・ラシ（サイデリアル）"""
    import swisseph as swe
    swe.set_sid_mode(swe.SIDM_LAHIRI)
    jd = swe.julday(y, m, d, 12.0 - 9.0)  # 正午JST→UT
    res = swe.calc_ut(jd, swe.MOON, swe.FLG_SWIEPH)
    lon = res[0][0]
    aya = swe.get_ayanamsa_ut(jd)
    lon_sid = (lon - aya) % 360
    naks_idx = int(lon_sid // (360 / 27))
    rasi_idx = int(lon_sid // 30)
    return {
        "nakshatra": NAKSHATRAS[naks_idx],
        "nakshatra_no": naks_idx + 1,   # 1-27
        "rasi": RASI_NAMES[rasi_idx],
        "rasi_no": rasi_idx + 1,        # 1-12
        "moon_lon_sidereal": round(lon_sid, 4),
    }



# ============================================================
# フル10ポルタム（36点満点）— ProjectA 由来の実装を統合
# ============================================================
from ..data import load_json as _load_json

_NKS_CACHE = None


def _nakshatra_attrs():
    """nakshatras_27.json（gana/yoni/rajju/lord 属性）を読み込む"""
    global _NKS_CACHE
    if _NKS_CACHE is None:
        try:
            _NKS_CACHE = {x["no"]: x for x in _load_json("nakshatras_27.json")}
        except FileNotFoundError:
            _NKS_CACHE = {}
    return _NKS_CACHE


# ============ Vashya: 5カテゴリ（度数分割込み） ============
# Dwipad: 双子, 乙女, 天秤, 射手(0-15°), 水瓶
# Chatushpad: 牡羊, 牡牛, 射手(15-30°), 山羊(0-15°)
# Jalachar: 蟹, 山羊(15-30°), 魚
# Vanchar: 獅子
# Keet: 蠍
def vashya_category(rasi, deg):
    """ラーシ名 + ラーシ内度数 → Vashyaカテゴリ"""
    if rasi in ("双子", "乙女", "天秤", "水瓶"):
        return "Dwipad"
    if rasi == "射手":
        return "Dwipad" if deg < 15 else "Chatushpad"
    if rasi in ("牡羊", "牡牛"):
        return "Chatushpad"
    if rasi == "山羊":
        return "Chatushpad" if deg < 15 else "Jalachar"
    if rasi in ("蟹", "魚"):
        return "Jalachar"
    if rasi == "獅子":
        return "Vanchar"
    if rasi == "蠍":
        return "Keet"
    return "Dwipad"

# Vashya スコアマトリクス（girl × boy・jyotishgher.in 準拠・0.5点含む）
VASHYA_MATRIX = {
    ("Dwipad", "Dwipad"): 2.0, ("Dwipad", "Chatushpad"): 0.0, ("Dwipad", "Jalachar"): 0.0, ("Dwipad", "Vanchar"): 0.5, ("Dwipad", "Keet"): 0.0,
    ("Chatushpad", "Dwipad"): 1.0, ("Chatushpad", "Chatushpad"): 2.0, ("Chatushpad", "Jalachar"): 1.0, ("Chatushpad", "Vanchar"): 0.5, ("Chatushpad", "Keet"): 1.0,
    ("Jalachar", "Dwipad"): 0.5, ("Jalachar", "Chatushpad"): 1.0, ("Jalachar", "Jalachar"): 2.0, ("Jalachar", "Vanchar"): 1.0, ("Jalachar", "Keet"): 1.0,
    ("Vanchar", "Dwipad"): 0.0, ("Vanchar", "Chatushpad"): 0.0, ("Vanchar", "Jalachar"): 0.0, ("Vanchar", "Vanchar"): 2.0, ("Vanchar", "Keet"): 0.0,
    ("Keet", "Dwipad"): 1.0, ("Keet", "Chatushpad"): 1.0, ("Keet", "Jalachar"): 1.0, ("Keet", "Vanchar"): 0.0, ("Keet", "Keet"): 2.0,
}

# ============ Yoni: 14動物の友敵（saravali敵 + cafeastrology友） ============
# 敵ペア（相互・0点）: saravali 準拠（ソート済みタプルで正規化）
_YE = [("Horse","Buffalo"), ("Elephant","Lion"), ("Sheep","Monkey"),
       ("Serpent","Mongoose"), ("Dog","Deer"), ("Cat","Rat"), ("Cow","Tiger")]
YONI_ENEMY = {tuple(sorted(p)) for p in _YE}
# 友ペア（相互・3点）: cafeastrology の相互 friend より（ソート済みタプルで正規化）
_YF = [("Buffalo","Cow"), ("Buffalo","Elephant"), ("Buffalo","Sheep"),
       ("Cow","Deer"), ("Cow","Sheep"),
       ("Elephant","Monkey"), ("Elephant","Serpent"),
       ("Horse","Monkey"), ("Horse","Serpent"),
       ("Cat","Deer"), ("Cat","Monkey"), ("Cat","Mongoose"),
       ("Monkey","Mongoose"), ("Mongoose","Sheep")]
YONI_FRIEND = {tuple(sorted(p)) for p in _YF}

def _yoni_score(y1, y2):
    """Yoniスコア（同=4 / 友=3 / 敵=0 / 中立=2）"""
    if y1 == y2:
        return 4
    pair = tuple(sorted((y1, y2)))
    if pair in YONI_ENEMY:
        return 0
    if pair in YONI_FRIEND:
        return 3
    return 2

# ============ Bhakoot (Rasi): 距離ルール（vedicmarga 準拠） ============
def _bhakoot_score(rasi_dist):
    """花嫁ラーシ→花婿ラーシの距離（0-11）→ スコア（0-7）"""
    # 7-7: 最良 / 3-11, 4-10: 吉 / 5-9: 中（流派により吉凶）/ 2-12, 6-8: 凶 / 同(0): 吉 / 隣接(1): 中
    if rasi_dist == 7:
        return 7        # 7-7 最良
    if rasi_dist in (3, 9):
        return 7        # 3-11 吉
    if rasi_dist in (4, 8):
        return 6        # 4-10 吉
    if rasi_dist == 0:
        return 7        # 同ラーシ
    if rasi_dist in (5,):
        return 3        # 5-9 中（流派により吉）
    if rasi_dist in (2, 10):
        return 0        # 2-12 凶
    if rasi_dist in (6,):
        return 0        # 6-8 凶
    return 3            # 隣接(1) 中

# ============ 惑星永久友好（Naisargika Maitri・伝統的表） ============
PLANET_FRIEND = {
    "太陽": {"友": {"月", "火星", "木星"}, "中": {"水星"}, "敵": {"金星", "土星"}},
    "月":   {"友": {"太陽", "水星"}, "中": {"火星", "木星", "金星", "土星"}, "敵": set()},
    "火星": {"友": {"太陽", "月", "木星"}, "中": {"水星", "金星", "土星"}, "敵": set()},
    "水星": {"友": {"太陽", "金星"}, "中": {"火星", "木星", "土星"}, "敵": {"月"}},
    "木星": {"友": {"太陽", "月", "火星"}, "中": {"水星", "土星"}, "敵": {"金星"}},
    "金星": {"友": {"水星", "土星"}, "中": {"火星", "木星"}, "敵": {"太陽", "月"}},
    "土星": {"友": {"水星", "金星"}, "中": {"木星"}, "敵": {"太陽", "月", "火星"}},
}
RASI_LORD = {"牡羊": "火星", "牡牛": "金星", "双子": "水星", "蟹": "月", "獅子": "太陽",
             "乙女": "水星", "天秤": "金星", "蠍": "火星", "射手": "木星", "山羊": "土星",
             "水瓶": "土星", "魚": "木星"}

# ============ ヴェーダ反目ペア（findyourfate） ============
VEDHA_PAIRS = [(1, 18), (2, 17), (3, 16), (4, 5), (14, 23)]



def porutham_full(d1: date, d2: date) -> dict:
    """2人の生年月日 → フル10ポルタム（36点満点）。属性辞書が無い場合は None。"""
    attrs = _nakshatra_attrs()
    if not attrs:
        return None
    m1 = _moon_nakshatra_rasi(d1.year, d1.month, d1.day)
    m2 = _moon_nakshatra_rasi(d2.year, d2.month, d2.day)
    n1, n2 = m1["nakshatra_no"], m2["nakshatra_no"]
    a, b = attrs.get(n1), attrs.get(n2)
    if not a or not b:
        return None

    rasi1, rasi2 = m1["rasi"], m2["rasi"]
    deg1 = m1["moon_lon_sidereal"] % 30
    deg2 = m2["moon_lon_sidereal"] % 30
    vc1, vc2 = vashya_category(rasi1, deg1), vashya_category(rasi2, deg2)
    lord1, lord2 = RASI_LORD[rasi1], RASI_LORD[rasi2]

    dist_12 = (n2 - n1) % 27
    dina = 3 if (dist_12 % 9) not in (3, 5, 7) else 0

    gana_table = {("Deva", "Deva"): 4, ("Manushya", "Manushya"): 4,
                  ("Rakshasa", "Rakshasa"): 4, ("Deva", "Manushya"): 4,
                  ("Manushya", "Deva"): 4, ("Manushya", "Rakshasa"): 2,
                  ("Rakshasa", "Manushya"): 2, ("Deva", "Rakshasa"): 0,
                  ("Rakshasa", "Deva"): 0}
    gana = gana_table.get((a["gana"], b["gana"]), 2)
    yoni = _yoni_score(a["yoni_en"], b["yoni_en"])
    rasi_dist = (RASI_NAMES.index(rasi2) - RASI_NAMES.index(rasi1)) % 12
    rasi = _bhakoot_score(rasi_dist)

    if lord1 == lord2:
        rasyadhipati = 5
    else:
        rel1 = "友" if lord2 in PLANET_FRIEND[lord1]["友"] else ("敵" if lord2 in PLANET_FRIEND[lord1]["敵"] else "中")
        rel2 = "友" if lord1 in PLANET_FRIEND[lord2]["友"] else ("敵" if lord1 in PLANET_FRIEND[lord2]["敵"] else "中")
        if rel1 == "友" and rel2 == "友":
            rasyadhipati = 5
        elif rel1 == "友" or rel2 == "友":
            rasyadhipati = 3
        elif rel1 == "中" and rel2 == "中":
            rasyadhipati = 2
        else:
            rasyadhipati = 0

    rajju = 5 if a["rajju"] != b["rajju"] else 0
    vedha = 0 if (n1, n2) in VEDHA_PAIRS or (n2, n1) in VEDHA_PAIRS else 2
    vashya = VASHYA_MATRIX.get((vc1, vc2), 1.0)
    dist_21 = (n1 - n2) % 27
    mahendra = 2 if dist_21 == 4 else (1 if dist_21 == 7 else 0)
    sthree = 2 if dist_12 >= 13 else 0

    total = (dina + gana + yoni + rasi + rasyadhipati + rajju
             + vedha + vashya + mahendra + sthree)
    if total >= 24:
        verdict = "相性良好（推奨）"
    elif total >= 18:
        verdict = "相性は中程度"
    else:
        verdict = "相性は難しい"

    return {
        "person1": {"nakshatra": a["ja"], "nakshatra_no": n1, "rasi": rasi1,
                    "lord": lord1, "gana": a["gana"], "yoni": a["yoni"],
                    "rajju": a["rajju"], "vashya": vc1},
        "person2": {"nakshatra": b["ja"], "nakshatra_no": n2, "rasi": rasi2,
                    "lord": lord2, "gana": b["gana"], "yoni": b["yoni"],
                    "rajju": b["rajju"], "vashya": vc2},
        "porutham": {
            "Dina": {"score": dina, "max": 3},
            "Gana": {"score": gana, "max": 4, "desc": f"{a['gana']}-{b['gana']}"},
            "Yoni": {"score": yoni, "max": 4, "desc": f"{a['yoni']}-{b['yoni']}"},
            "Rasi(Bhakoot)": {"score": rasi, "max": 7, "desc": f"{rasi1}→{rasi2} 距離{rasi_dist}"},
            "Rasyadhipati": {"score": rasyadhipati, "max": 5, "desc": f"{lord1}-{lord2}"},
            "Rajju": {"score": rajju, "max": 5},
            "Vedha": {"score": vedha, "max": 2},
            "Vashya": {"score": vashya, "max": 2, "desc": f"{vc1}-{vc2}"},
            "Mahendra": {"score": mahendra, "max": 2},
            "SthreeDeergha": {"score": sthree, "max": 2},
        },
        "total_score": total,
        "total": f"{total}/36",
        "verdict": verdict,
        "note": "フル10ポルタム（36点）。Vashya=jyotishgher / Yoni=saravali+cafeastrology / Bhakoot=vedicmarga。",
    }


def parimicham_calc(birth1: dict, birth2: dict, role1: str = "本人",
                    role2: str = "相手") -> dict:
    """
    パリミチャム（結婚相性）の簡易計算。

    Args:
        birth1: 1人目の {"date": "YYYY-MM-DD"}（辞書）
        birth2: 2人目の {"date": "YYYY-MM-DD"}
        role1 / role2: 表示用ラベル

    Returns:
        dict: ナクシャトラ・Dina判定・スコア・総合判定
    """
    d1 = date.fromisoformat(birth1["date"])
    d2 = date.fromisoformat(birth2["date"])
    m1 = _moon_nakshatra_rasi(d1.year, d1.month, d1.day)
    m2 = _moon_nakshatra_rasi(d2.year, d2.month, d2.day)

    # Dina: 本人（花嫁側）→ 相手（新郎側）のナクシャトラ数え
    count = (m2["nakshatra_no"] - m1["nakshatra_no"]) % 27
    if count == 0:
        count = 27
    dina_uthamam = count in DINA_UTHAMAM

    # 同一ナクシャトラの禁忌
    same_ng = (m1["nakshatra"] == m2["nakshatra"]) and (m1["nakshatra"] in SAME_NIYAZHA)

    # Rasi 6/8（shashtashtama）: ラシ番号の差が6または8（mod 12で±6 or ±8）
    rasi_diff = (m2["rasi_no"] - m1["rasi_no"]) % 12
    rasi_68 = rasi_diff in (6, 8)

    # 簡易スコア（10点満点・公開ルールの近似）
    score = 0.0
    checks = []
    if dina_uthamam:
        score += 2.0
        checks.append(("Dina（ナクシャトラ数え）", "Uthamam（良）", True))
    else:
        checks.append(("Dina（ナクシャトラ数え）", "Adhamam（やや不利）", False))
    if not same_ng:
        score += 2.0
        checks.append(("同一ナクシャトラ禁忌", "なし（良）", True))
    else:
        checks.append(("同一ナクシャトラ禁忌", "あり（要注意）", False))
    if not rasi_68:
        score += 2.0
        checks.append(("Rasi 6/8（shashtashtama）", "該当なし（良）", True))
    else:
        checks.append(("Rasi 6/8（shashtashtama）", "該当（要相談）", False))
    # ナクシャトラ同系（相性が良い組み合わせ・公開ルールの一部）
    if m1["nakshatra"] == m2["nakshatra"] and m1["nakshatra"] in {"アードラー", "ローヒニー", "ハスタ", "プシュヤ", "マガー", "シュラヴァナ"}:
        score += 1.0
        checks.append(("同一ナクシャトラ（良相性）", "Uthamam", True))
    # 星座の同エレメント補正（簡易）
    if (m1["rasi_no"] - 1) % 4 == (m2["rasi_no"] - 1) % 4:
        score += 1.0
        checks.append(("ラシのエレメント", "同系統（良）", True))

    # 総合判定（tamilcube の基準に準拠: 6.5+=Excellent, 4.5+=Good, 3.0+=Average）
    if score >= 6.5:
        verdict = "Excellent（非常に良い相性）"
    elif score >= 4.5:
        verdict = "Good（良い相性）"
    elif score >= 3.0:
        verdict = "Average（まずまず）"
    else:
        verdict = "Low（相性は要検討）"

    _full = porutham_full(d1, d2)

    return {
        f"{role1}": m1,
        f"{role2}": m2,
        "nakshatra_count": count,
        "dina_uthamam": dina_uthamam,
        "same_nakshatra_ng": same_ng,
        "rasi_68": rasi_68,
        "checks": checks,
        "score": score,
        "score_max": 8.0,
        "verdict": verdict,
        "references": [
            "tamilsonline.com（Natchathira Porutham）",
            "astrology.tamilcube.com（10 Porutham）",
            "lifehoroscope.in（Dina数え・同一ナクシャトラ禁忌）",
        ],
        "full_porutham": _full,
        "notes": [
            "タミル占星術のThirumana Porutham体系。簡易スコア（8点）とフル10ポルタム（36点）を併記",
            "full_porutham に Dina/Gana/Yoni/Rasi/Rasyadhipati/Rajju/Vedha/Vashya/Mahendra/SthreeDeergha の内訳",
            "正式な結婚判断には専門家の鑑定が必要",
        ],
    }
