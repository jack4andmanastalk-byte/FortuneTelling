# -*- coding: utf-8 -*-
"""
M27 カード系RNG — デッキ定義＋抽選
仕様：計算ロジック仕様書 §4.19（M27）
- デッキ定義: data/*.json（タロット78・レノルマン36・キッパー36・オラクル44・エンジェル44・カルトマンシー52・ルーン24）
- タロット系のみ正逆あり（upright/reversed）。他は正位置のみ
- シャッフル＋カット＋ドロー（再現モード対応）
"""
from __future__ import annotations

from ..data import load_json
from ..rng import FortuneRNG

# デッキ定義（マルセイユはタロットと同構成・寓意は解釈側で切替）
DECK_FILES = {
    "tarot": "tarot_78.json",
    "marseille": "tarot_78.json",      # マルセイユ版（78枚・同構造）
    "lenormand": "lenormand_36.json",
    "kipper": "kipper_36.json",
    "oracle": "oracle_44.json",
    "angel": "angel_44.json",
    "cartomancy": "cartomancy_52.json",
    "runes": "runes_24.json",
}
REVERSIBLE = {"tarot", "marseille", "oracle", "angel"}   # 正逆あり
# タロット系のスプレッド（位置名）
SPREADS = {
    "tarot": {
        "single": ["現在"],
        "three": ["過去", "現在", "未来"],
        "celtic_cross": ["現在の状況", "障害", "潜在意識", "過去", "理想", "近未来",
                         "自分自身", "周囲", "希望・恐れ", "最終結果"],
    },
    "lenormand": {
        "single": ["現在"],
        "three": ["過去", "現在", "未来"],
        "nine": [f"位置{i+1}" for i in range(9)],
    },
}


def _default_positions(deck_id: str, count: int) -> list:
    """位置名のフォールバック"""
    return [f"位置{i+1}" for i in range(count)]


def draw(deck_id: str, count: int = 3, spread: str | None = None,
         seed: int | None = None, mode: str = "random") -> dict:
    """
    デッキからカードを抽選。

    Args:
        deck_id: tarot / marseille / lenormand / kipper / oracle / angel /
                 cartomancy / runes
        count: ドロー枚数
        spread: スプレッド名（"single"/"three"/"celtic_cross"/"nine"）※タロット・レノルマン
        seed: RNGシード
        mode: "reproducible" / "random"

    Returns:
        dict: 抽選結果（カード配置JSON）
    """
    if deck_id not in DECK_FILES:
        raise ValueError(f"不明なデッキ: {deck_id}（{sorted(DECK_FILES)}）")
    deck = load_json(DECK_FILES[deck_id])

    rng = FortuneRNG(seed, mode)
    # シャッフル＋カット（再現モードでも決定論的）
    rng.shuffle(deck)
    cut = rng.randint(0, len(deck) - 1)
    deck = deck[cut:] + deck[:cut]
    drawn = deck[:count]

    # 位置名
    if spread and deck_id in SPREADS and spread in SPREADS[deck_id]:
        positions = SPREADS[deck_id][spread]
    else:
        positions = _default_positions(deck_id, count)
    if len(positions) < count:
        positions = _default_positions(deck_id, count)

    cards = []
    for i, c in enumerate(drawn):
        # mts4.8: card_id は「実カード番号」を優先（旧: or 結合のため no==0 の大アルカナ
        #         「愚者」が並び順に化け、画像の誤充当を招いていた）
        if c.get("no") is not None:
            _cid = c.get("no")
        elif c.get("kingwen_no") is not None:
            _cid = c.get("kingwen_no")
        else:
            _cid = i + 1
        card = {
            "position": positions[i],
            "card_id": _cid,
            "name_ja": c.get("name_ja", c.get("rank_name", "")),
            "name_en": c.get("name_en", ""),
        }
        # 補助フィールド（デッキ依存）
        for key in ("arcana", "suit", "suit_ja", "suit_meaning", "rank", "rank_meaning",
                    "keyword_ja", "meaning_ja", "element", "reading"):
            if key in c:
                card[key] = c[key]
        if deck_id in REVERSIBLE:
            card["upright"] = rng.random() < 0.5
        cards.append(card)

    return {
        "deck": deck_id,
        "count": count,
        "spread": spread,
        "cards": cards,
        "references": [f"data/{DECK_FILES[deck_id]}"],
        "notes": [] if deck_id != "kipper" else ["キッパーは版により36/39/52枚構成がある（本実装は伝統的36枚）"],
    }
