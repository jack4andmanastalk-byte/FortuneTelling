# -*- coding: utf-8 -*-
"""
M31 御縁のある神さま Top10（疑似オラクル・G6）

設計方針は本プロジェクトの原則どおり「選定＝コード／解釈＝LLM」。
  1. 構造化されたプロファイル事実と統合レポートの具体語から親和スコアを算出
  2. 抽選層は同じ親和スコア内だけで順位を揺らす（御神籤・オラクルカード的な体験）
  3. 138柱から上位 top_n 柱を選び、6文明が最低1柱ずつ入るよう調整
  4. LLM は選ばれた神々の「縁の解釈」だけを書く（選定はしない）

※ 神話事典レベルの公開情報に基づく創作的マッチング。
  特定の信仰・教義を代表するものではなく、エンターテインメント用途。
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date

from ..data import load_json
from ..rng import FortuneRNG, make_seed

_DATA = None

PANTHEONS = ["メソポタミア", "エジプト", "ギリシャ", "インド", "中国", "日本"]

# 五行 → 親和キーワード（干支・九星の構造化値から引く）
_WUXING_AFFINITY = {
    "木": ("学び", "成長", "創意", "表現"),
    "火": ("情熱", "光", "勝利", "変容"),
    "土": ("育み", "安定", "実り", "中心"),
    "金": ("裁定", "浄化", "武", "秩序"),
    "水": ("知恵", "流れ", "内省", "航海"),
}

# 十干・十二支の五行。自由文の文字検索で推測しない。
_STEM_ELEMENT = {
    "甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
    "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水",
}
_BRANCH_ELEMENT = {
    "寅": "木", "卯": "木", "巳": "火", "午": "火",
    "辰": "土", "戌": "土", "丑": "土", "未": "土",
    "申": "金", "酉": "金", "亥": "水", "子": "水",
}
_NINE_STAR_ELEMENT = {
    "一白水星": "水", "二黒土星": "土", "三碧木星": "木",
    "四緑木星": "木", "五黄土星": "土", "六白金星": "金",
    "七赤金星": "金", "八白土星": "土", "九紫火星": "火",
}

# 1 affinity point is four score units. The lottery draw is strictly <4,
# so it can only break ties and can never overtake a one-point affinity lead.
_AFFINITY_WEIGHT = 4.0
_SYNTHESIS_MAX_POINTS = 2
_SYNTHESIS_FIELD_SEPARATORS = re.compile(r"[・（）()\[\]【】、，,／/|;；:：\s]+")
_LOTTERY_NAMESPACE = "deities-lottery-mts5.45"

# Two-character phrases need word-like boundaries so e.g. 知恵 does not match
# the unrelated compound 知恵袋. Longer distinctive phrases are matched as
# normalized substrings because Japanese text does not use word spaces.
_SHORT_TERM_BOUNDARIES = set(" \t\r\n　、。・，,．.!！?？;；:：()（）[]【】「」『』/／—–…")
_SHORT_TERM_PARTICLES = set("はがをにへとでもやかねよ")

# ライフパス（1-9・11/22/33）→ 響き合うキーワード
_LIFEPATH_AFFINITY = {
    1: ("統率", "始まり", "勝利"), 2: ("絆", "調和", "守護"),
    3: ("表現", "歓び", "芸術"), 4: ("秩序", "形", "実直"),
    5: ("往来", "変化", "自由"), 6: ("育み", "愛", "家庭"),
    7: ("知恵", "内省", "静寂"), 8: ("富", "権威", "実り"),
    9: ("慈愛", "完成", "解放"),
    11: ("直感", "照らす", "予言"), 22: ("創造", "構想", "建設"),
    33: ("献身", "癒し", "母性"),
}


def _load() -> dict:
    global _DATA
    if _DATA is None:
        _DATA = load_json("deities.json")
    return _DATA


def all_deities() -> list:
    return list(_load()["deities"])


def _text_of(d: dict) -> str:
    return f"{d['domain']} {d['symbol']} {d['keyword']}"


def _profile_wuxing_elements(facts: dict) -> set[str]:
    """干支の十干・十二支と九星本命星の専用フィールドだけから五行を得る。"""
    elements: set[str] = set()
    ganzhi = str(facts.get("干支（年柱・立春基準）", "") or "").strip()
    if ganzhi:
        stem = ganzhi[0]
        if stem in _STEM_ELEMENT:
            elements.add(_STEM_ELEMENT[stem])
        if len(ganzhi) >= 2:
            branch = ganzhi[1]
            if branch in _BRANCH_ELEMENT:
                elements.add(_BRANCH_ELEMENT[branch])

    nine_star = str(facts.get("九星気学（本命星）", "") or "").strip()
    element = _NINE_STAR_ELEMENT.get(nine_star)
    if element:
        elements.add(element)
    return elements


def _affinity_score(d: dict, facts: dict) -> tuple[int, list[str]]:
    """構造化されたプロファイル事実との親和スコアと根拠を返す。"""
    score = 0
    reasons = []
    text = _text_of(d)

    # ライフパス
    lp = facts.get("数秘術（ライフパス）")
    if isinstance(lp, int) and not isinstance(lp, bool):
        for kw in _LIFEPATH_AFFINITY.get(lp, ()):
            if kw in text:
                score += 3
                reasons.append(f"ライフパス{lp}の『{kw}』と響き合う")
                break

    # 五行（干支の十干・十二支と九星本命星だけを参照）
    for elem in sorted(_profile_wuxing_elements(facts)):
        for kw in _WUXING_AFFINITY[elem]:
            if kw in text:
                score += 2
                reasons.append(f"五行の{elem}が示す『{kw}』に通じる")
                break

    # 相談内容のテーマ語（自由文はここでのみテーマ判定に使用）
    consultation = str(facts.get("_consultation", "") or "")
    for theme, kws in (("仕事", ("秩序", "統治", "実り", "商", "勝利", "武")),
                       ("恋愛", ("愛", "縁", "結", "美", "魅")),
                       ("結婚", ("結", "絆", "家庭", "婚", "誓")),
                       ("健康", ("癒", "医", "回復", "浄化", "治")),
                       ("学業", ("学", "知", "文", "書", "智"))):
        if theme in consultation:
            for kw in kws:
                if kw in text:
                    score += 2
                    reasons.append(f"ご相談の『{theme}』に関わる")
                    break
    return score, reasons


def _contains_short_phrase(text: str, phrase: str) -> bool:
    """2文字語は隣接が区切り／助詞のときだけ一致とみなす。"""
    start = 0
    while True:
        pos = text.find(phrase, start)
        if pos < 0:
            return False
        end = pos + len(phrase)
        left = text[pos - 1] if pos else ""
        right = text[end] if end < len(text) else ""
        left_ok = not left or left in _SHORT_TERM_BOUNDARIES or left in _SHORT_TERM_PARTICLES
        right_ok = not right or right in _SHORT_TERM_BOUNDARIES or right in _SHORT_TERM_PARTICLES
        if left_ok and right_ok:
            return True
        start = pos + 1


def _synthesis_affinity_hits(d: dict, synthesis_text: str) -> list[str]:
    """統合文に含まれる具体的な神格語を返す（短い部分文字列の誤一致を抑える）。"""
    text = unicodedata.normalize("NFKC", synthesis_text or "").casefold()
    phrases: set[str] = set()
    for field in (d.get("keyword", ""), d.get("symbol", ""), d.get("domain", "")):
        normalized = unicodedata.normalize("NFKC", str(field or "")).casefold()
        for part in _SYNTHESIS_FIELD_SEPARATORS.split(normalized):
            phrase = part.strip()
            if len(phrase) >= 2:
                phrases.add(phrase)

    hits = []
    for phrase in sorted(phrases):
        matched = phrase in text if len(phrase) >= 3 else _contains_short_phrase(text, phrase)
        if matched:
            hits.append(phrase)
    return hits


def _rank_score(affinity: int, lottery: float) -> float:
    """Return a readable composite score; lottery draw must be in [0,1)."""
    if not 0.0 <= lottery < 1.0:
        raise ValueError("lottery must be in [0, 1)")
    return affinity * _AFFINITY_WEIGHT + lottery * _AFFINITY_WEIGHT


def _rank_key(item: dict) -> tuple[int, float, str]:
    """Use affinity lexicographically so floating-point rounding cannot invert it."""
    return (-item["affinity_score"], -item["lottery_score"], item["name"])


def _lottery_value(d: dict, day: str, seed: int | None,
                   rng_mode: str, rng: FortuneRNG | None) -> float:
    """日付・神格IDで再現するか、randomモードでは独立した抽選値を返す。"""
    if rng_mode == "random":
        assert rng is not None
        return rng.random()
    assert seed is not None  # draw_deities が reproducible 用seedを確定済み
    key = f"{_LOTTERY_NAMESPACE}|{day}|{seed}|{d['pantheon']}|{d['en']}"
    # Use 53 bits so conversion to float is guaranteed to remain strictly < 1.
    value = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big") >> 11
    return value / 2**53


def draw_deities(facts: dict, target: date | None = None,
                 seed: int | None = None, rng_mode: str = "random",
                 top_n: int = 10, synthesis_text: str = "") -> dict:
    """御縁のある神さまを選定する（親和スコア主導＋小さな抽選）。

    Args:
        facts: プロファイル事実（build_profile_facts の戻り値＋_consultation）
        synthesis_text: 統合レポート本文。神々の具体的な領域・象徴・キーワード
            （3文字以上、または境界が明確な2文字語）の一致を親和スコアに加算する
        target: 対象日（reproducibleモードの抽選を日付で分ける）
        seed: 再現用シード。rng_mode='reproducible' で使用
        rng_mode: "random"（毎回変わる）/ "reproducible"（日付とseedで再現）
        top_n: 選定数。6文明の最低1柱を保証するため6〜全神格数に制限

    Returns:
        dict: ranking（順位つき）・pantheon_coverage・notes
    """
    if type(top_n) is not int:
        raise ValueError("top_n must be an integer")
    deities = all_deities()
    if not len(PANTHEONS) <= top_n <= len(deities):
        raise ValueError(f"top_n must be between {len(PANTHEONS)} and {len(deities)}")
    if rng_mode not in {"random", "reproducible"}:
        raise ValueError("rng_mode must be 'random' or 'reproducible'")

    day = (target or date.today()).isoformat()
    if rng_mode == "random":
        rng = FortuneRNG(mode="random")
        lottery_seed = None
    else:
        base_seed = seed if seed is not None else make_seed(salt=_LOTTERY_NAMESPACE)
        lottery_seed = int.from_bytes(
            hashlib.sha256(f"{_LOTTERY_NAMESPACE}|{day}|{base_seed}".encode("utf-8")).digest()[:8],
            "big",
        )
        rng = None

    syn = unicodedata.normalize("NFKC", (synthesis_text or "")[:6000]).casefold()

    scored = []
    for d in deities:
        aff, reasons = _affinity_score(d, facts)
        # 統合レポートとの具体語の共鳴。短い一般語の部分一致は避け、加点は最大2。
        hits = _synthesis_affinity_hits(d, syn) if syn else []
        if hits:
            aff += min(_SYNTHESIS_MAX_POINTS, len(hits))
            reasons.append(f"統合レポートの『{hits[0]}』に呼応する")

        lottery = _lottery_value(d, day, lottery_seed, rng_mode, rng)
        total = _rank_score(aff, lottery)
        scored.append({
            "pantheon": d["pantheon"], "name": d["name"], "en": d["en"],
            "domain": d["domain"], "symbol": d["symbol"], "keyword": d["keyword"],
            "affinity_score": aff, "lottery_score": lottery * _AFFINITY_WEIGHT,
            "score": total, "affinity_reasons": reasons,
        })

    scored.sort(key=_rank_key)

    # 6文明が最低1柱ずつ入るように、まず各文明の最上位を確保する。
    picked, seen = [], set()
    for item in scored:
        if item["pantheon"] not in seen:
            picked.append(item)
            seen.add(item["pantheon"])
        if len(seen) == len(PANTHEONS):
            break
    if len(seen) != len(PANTHEONS):
        raise RuntimeError("deities.json に必要な6文明がそろっていません")

    for item in scored:
        if len(picked) >= top_n:
            break
        if item not in picked:
            picked.append(item)
    picked = sorted(picked, key=_rank_key)[:top_n]

    for i, item in enumerate(picked, 1):
        item["rank"] = i

    coverage = {p: sum(1 for x in picked if x["pantheon"] == p) for p in PANTHEONS}
    return {
        "target_date": day,
        "ranking": picked,
        "pantheon_coverage": coverage,
        "references": ["data/deities.json"],
        "notes": [
            "6文明（メソポタミア・エジプト・ギリシャ・インド・中国・日本）各文明から選定（計138柱）",
            "正規化したプロファイル親和スコアを主軸とし、抽選（0以上4未満）は同じ親和点内のタイブレークに限定",
            "五行は干支（十干・十二支）と九星本命星の構造化値から判定。プロフィール内の自由文・表示用文字列は使用しない",
            "神話事典レベルの公開情報に基づく創作的マッチングであり、"
            "特定の信仰・教義を代表するものではありません",
        ],
    }
