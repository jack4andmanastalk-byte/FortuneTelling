# -*- coding: utf-8 -*-
"""
系譜フィルタ（プロファイル事実の出し分け）

■ 解決する問題
  すべての占術に同じ profile_facts（太陽星座・干支・九星・ライフパス…）を
  渡していたため、系譜の異なる体系にまで語彙が流入していた。
  実機（66種）では 30種で系譜外の語彙が混入していた。

    ドゥクン（ジャワの民俗）→「二黒土星（中国の九星）を持つあなたは…」
    デルポイの託宣（古代ギリシャ）→「ライフパス8（西洋近代数秘）が…」

  各体系は固有の宇宙観・語彙を持つので、他系譜の術語をそのまま
  持ち込むと世界観が壊れる。

■ 方針
  占術ごとに「参照してよい事実」を系譜で絞る。加えて、生の術語を
  出さずに済むよう、体系に馴染む言い換え（中立表現）も用意する。
"""
from __future__ import annotations

# 事実キー → その事実が属する系譜タグ
FACT_LINEAGE = {
    "太陽星座": "western",
    "干支（年柱・立春基準）": "eastasia",
    "十二支の動物": "eastasia",
    "九星気学（本命星）": "eastasia",
    "数秘術（ライフパス）": "western",
    "ウェトン": "seasia",
    "血液型": "modern",
    "氏名（ヘボン式）": "neutral",
    "氏名（漢字）": "neutral",
    "氏名（かな）": "neutral",
    "相手の生年月日": "neutral",
}

# 占術スラグ → 参照を許す系譜タグ
#   "neutral"（氏名・生年月日）は常に許可される
LINEAGE_OF = {
    # ---- 東アジア ----
    **{s: {"eastasia"} for s in [
        "eto", "kyusei", "bazi", "ziwei", "sanmei", "rokusei", "animal",
        "seimei", "iching", "liuyao", "meihua", "qimen", "omikuji"]},
    # ---- インド（ヴェーダ） ----
    **{s: {"india"} for s in [
        "vedic", "tantra", "anka", "parimicham", "genekeys", "hd"]},
    # ---- 西洋 ----
    **{s: {"western"} for s in [
        "seiza", "western", "natal", "transit", "synastry",
        "numerology_birth", "numerology_name", "chaldean", "kabbalah",
        "tarot", "marseille", "lenormand", "kipper", "oracle", "angel",
        "cartomancy", "urbantarot", "runes"]},
    # ---- オリエント・地中海（古代） ----
    **{s: set() for s in [
        "haruspex", "meso", "delphi", "ornith", "astragaloi", "christian"]},
    # ---- 東南アジア・アフリカ（民俗） ----
    "weton": {"seasia"}, "primbon": {"seasia"},
    **{s: set() for s in ["african", "dukun", "mganga", "witchdoctor", "sangoma"]},
    # ---- 現代スピリチュアル ----
    **{s: {"western", "modern"} for s in [
        "psychic", "reikan", "channeling", "aura", "akashic", "paranormal",
        "prophecy", "crystal", "hado", "geist", "crystalball", "pendulum",
        "talisman"]},
    "blood": {"modern"}, "stone": {"western", "modern"},
    # ---- 横断（複数文明の神々を扱うので制限しない） ----
    "deities": None,
}

# 生年月日から誰でも導ける中立的な言い換え
#   系譜外の術語を使えない体系向けに、同じ内容を体系に馴染む形で渡す
NEUTRAL_HINTS = {
    "太陽星座": ("生まれた季節", {
        "牡羊座": "春の初め", "牡牛座": "春の盛り", "双子座": "春の終わり",
        "蟹座": "夏の初め", "獅子座": "夏の盛り", "乙女座": "夏の終わり",
        "天秤座": "秋の初め", "蠍座": "秋の盛り", "射手座": "秋の終わり",
        "山羊座": "冬の初め", "水瓶座": "冬の盛り", "魚座": "冬の終わり"}),
}


def allowed_facts(slug: str, facts: dict) -> dict:
    """占術の系譜に合う事実だけを残す。

    Args:
        slug: 占術スラグ
        facts: build_profile_facts の戻り値

    Returns:
        絞り込み後の事実（生年月日・氏名などの中立情報は常に残る）
    """
    allow = LINEAGE_OF.get(slug, None)
    if allow is None:          # 制限なし（deities・未登録）
        return dict(facts)

    out = {}
    for k, v in facts.items():
        if k.startswith("_"):
            out[k] = v
            continue
        tag = FACT_LINEAGE.get(k, "neutral")
        if tag == "neutral" or tag in allow:
            out[k] = v
    return out


def neutral_context(facts: dict) -> dict:
    """系譜を問わず使える中立的な手がかり（季節など）を作る"""
    out = {}
    for key, (label, table) in NEUTRAL_HINTS.items():
        v = facts.get(key)
        if isinstance(v, str) and v in table:
            out[label] = table[v]
    return out


def lineage_note(slug: str) -> str:
    """系譜外語彙の使用を禁じる指示文（system プロンプトへ追記）"""
    allow = LINEAGE_OF.get(slug, None)
    if allow is None:
        return ""
    forbidden = []
    if "eastasia" not in allow:
        forbidden.append("九星（二黒土星など）・干支・十二支・五行")
    if "western" not in allow:
        forbidden.append("十二星座・ライフパス／数秘術の番号")
    if "india" not in allow:
        forbidden.append("ナクシャトラ・チャクラ")
    if not forbidden:
        return ""
    return ("\n【語彙の制約】この体系は上記の宇宙観に属さないため、"
            + "／".join(forbidden)
            + " といった他系譜の術語は使わないこと。"
              "この体系が本来用いる語彙と世界観だけで記述すること。")
