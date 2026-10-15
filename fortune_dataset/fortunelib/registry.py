# -*- coding: utf-8 -*-
"""
占術レジストリ（64種）— プロンプトID・計算モジュール・入力要件の定義
- 対応: 仕様設計メモ §4（対象64種）／プロンプト設計書 付録A（P01〜P65）
- needs: 実行に必須の入力項目（血液型・氏名・かな・相手情報）
"""
from __future__ import annotations

# (slug, name_ja, mcode, group, prompt_id, needs, calc_key)
#   needs: set of {"blood", "name_kanji", "name_kana", "partner"}
#   calc_key: Cell2 計算結果（calc_results 辞書）のキー（None なら計算不要）
_REGISTRY = [
    # ---- G1 基本プロファイル（14） ----
    ("seiza",       "星座占い",              "M02", "G1", "P01", set(),              "zodiac"),
    ("eto",         "干支",                  "M01", "G1", "P02", set(),              "eto"),
    ("kyusei",      "九星気学",              "M03", "G1", "P03", set(),              "kyusei"),
    ("numerology_birth", "数秘術（生年月日）", "M04", "G1", "P04", set(),            "numerology_birth"),
    ("tantra",      "タントラ数秘術",        "M04", "G1", "P05", set(),              "tantra"),
    ("anka",        "アンカ・シャーストラ",  "M04", "G1", "P06", set(),              "anka"),
    ("blood",       "血液型占い",            "M08", "G1", "P07", {"blood"},          "blood"),
    ("animal",      "動物占い",              "M09", "G1", "P08", set(),              "animal"),
    ("rokusei",     "六星占術",              "M10", "G1", "P09", set(),              "rokusei"),
    ("weton",       "ウェトン",              "M14", "G1", "P10", set(),              "weton"),
    ("primbon",     "プリンボン・ジャワ",    "M13", "G1", "P11", set(),              "primbon"),
    ("stone",       "パワーストーン",        "M12", "G1", "P12", set(),              "stones"),
    ("omikuji",     "おみくじ",              "M28", "G1", "P13", set(),              "omikuji"),
    ("genekeys",    "ジーンキーズ",          "M11", "G1", "P14", set(),              "genekeys"),
    # ---- G2 氏名系（4） ----
    ("seimei",      "姓名判断",              "M16", "G2", "P15", {"name_kanji"},     "seimei"),
    ("numerology_name", "数秘術（氏名）",    "M05", "G2", "P16", {"name_kana"},      "numerology_name"),
    ("kabbalah",    "数秘術・カバラ",        "M06", "G2", "P17", {"name_kana"},      "kabbalah"),
    ("chaldean",    "カルデア数秘術",        "M07", "G2", "P18", {"name_kana"},      "chaldean"),
    # ---- G3 命盤系（8） ----
    ("bazi",        "四柱推命",              "M17", "G3", "P19", set(),              "bazi"),
    ("western",     "西洋占星術",            "M18", "G3", "P20", set(),              "western"),
    ("natal",       "ネイタル占星術",        "M18", "G3", "P21", set(),              "natal"),
    ("transit",     "トランジット分析",      "M18", "G3", "P22", set(),              "transit"),
    ("vedic",       "ヴェーダ占星術",        "M19", "G3", "P23", set(),              "vedic"),
    ("ziwei",       "紫微斗数",              "M20", "G3", "P24", set(),              "ziwei"),
    ("sanmei",      "算命学",                "M21", "G3", "P25", set(),              "sanmei"),
    ("hd",          "ヒューマンデザイン",    "M25", "G3", "P26", set(),              "hd"),
    # ---- G4 相談・抽選系（13） ----
    ("iching",      "易",                    "M26", "G4", "P27", set(),              "iching"),
    ("liuyao",      "六爻",                  "M22", "G4", "P28", set(),              "liuyao"),
    ("meihua",      "梅花易数",              "M23", "G4", "P29", set(),              "meihua"),
    ("qimen",       "奇門遁甲",              "M24", "G4", "P30", set(),              "qimen"),
    ("tarot",       "タロット",              "M27", "G4", "P31", set(),              "tarot"),
    ("marseille",   "タロット・ド・マルセイユ", "M27", "G4", "P32", set(),          "marseille"),
    ("lenormand",   "レノルマン",            "M27", "G4", "P33", set(),              "lenormand"),
    ("kipper",      "キッパー",              "M27", "G4", "P34", set(),              "kipper"),
    ("oracle",      "オラクル",              "M27", "G4", "P35", set(),              "oracle"),
    ("angel",       "エンジェル",            "M27", "G4", "P36", set(),              "angel"),
    ("cartomancy",  "カルトマンシー",        "M27", "G4", "P37", set(),              "cartomancy"),
    ("urbantarot",  "現代タロット・占星術",  "M27", "G4", "P38", set(),              "urbantarot"),
    ("runes",       "ルーン",                "M27", "G4", "P39", set(),              "runes"),
    # ---- G5 相性系（2） ----
    ("synastry",    "シナストリー",          "M18", "G5", "P40", {"partner"},        "synastry"),
    ("parimicham",  "パリミチャム",          "M15", "G5", "P41", {"partner"},        "parimicham"),
    # ---- G6 創作系（24） ----
    ("christian",   "キリスト教的黙想（聖句）",      "M30", "G6", "P49", set(),              "bible_verse"),
    ("crystal",     "クリスタル・ヒーリング", "M30", "G6", "P50", set(),             None),
    ("crystalball", "水晶玉占い",            "M30", "G6", "P53", set(),              None),
    ("pendulum",    "ペンデュラム",          "M29", "G6", "P54", set(),              "pendulum"),
    ("talisman",    "タリスマン・お守り",    "M30", "G6", "P55", set(),              None),
    ("african",     "伝統的アフリカ占い",    "M29", "G6", "P56", set(),              "cowrie"),
    ("haruspex",    "肝占（バールートゥ）",  "M30", "G6", "P61", set(),              None),
    ("meso",        "メソポタミア天体オーメン", "M30", "G6", "P62", set(),          "meso_omen"),
    ("delphi",      "デルポイの託宣",        "M30", "G6", "P63", set(),              None),
    ("ornith",      "鳥占",                  "M30", "G6", "P64", set(),              None),
    ("astragaloi",  "籤占（アストラガロイ）", "M28", "G6", "P65", set(),            "astragaloi"),
    # ---- 新機能: 御縁のある神さま Top10（疑似オラクル） ----
    ("deities",     "御縁のある神さま Top10", "M31", "G6", "P66", set(),           "deities"),
]

REGISTRY = {slug: {
    "slug": slug, "name": name, "mcode": mcode, "group": group,
    "prompt_id": pid, "needs": needs, "calc_key": calc_key,
} for slug, name, mcode, group, pid, needs, calc_key in _REGISTRY}


def all_slugs() -> list:
    return [e["slug"] for e in REGISTRY.values()]


def availability_reason(slug: str, inputs) -> str | None:
    """
    入力充足チェック。不足がある場合は理由文字列、OKなら None。
    inputs は NormalizedInput（profile.py）を想定。
    """
    entry = REGISTRY[slug]
    for need in entry["needs"]:
        if need == "blood" and inputs.blood_type == "unknown":
            return "血液型が未入力"
        if need == "name_kanji" and not inputs.name_kanji:
            return "氏名（漢字）が未入力"
        if need == "name_kana" and not inputs.name_kana:
            return "氏名（かな）が未入力"
        if need == "partner" and inputs.partner is None:
            return "相手情報が未入力"
    return None


def is_available(slug: str, inputs) -> bool:
    return availability_reason(slug, inputs) is None

# ---------------------------------------------------------------
# 遅延実行（統合レポート完成後に実行する占術）
# ---------------------------------------------------------------
# 「御縁のある神さま」は全占術＋統合レポートの総意を踏まえて選定するため、
# 通常の順次実行からは外し、synthesis の後に実行する。
DEFERRED_SLUGS = {"deities"}


def is_deferred(slug: str) -> bool:
    return slug in DEFERRED_SLUGS


def main_slugs() -> list:
    """通常フェーズで実行するスラグ（遅延実行分を除く）"""
    return [s for s in all_slugs() if s not in DEFERRED_SLUGS]