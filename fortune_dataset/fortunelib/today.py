# -*- coding: utf-8 -*-
"""
今日の運勢モード（⑦・クロスチェック拡張）
- 別AI実装の divinations_other_ai.json（63種の today 指示）を本実装スラグにマッピング
- get_today_instruction(slug) → today指示文字列（なければ None）
- マッピング: 別AIキー → 本実装スラグ（カバラ・数秘術（氏名）は対象外のため None）
"""
from __future__ import annotations

from .data import load_json

# 別AIキー → 本実装スラグ
OTHER_AI_TO_SLUG = {
    "seiza": "seiza", "kanzashi": "eto", "kyusei": "kyusei",
    "numerology": "numerology_birth", "chaldean": "chaldean",
    "tantric": "tantra", "ank": "anka", "blood": "blood",
    "doubutsu": "animal", "stone": "stones", "seimei": "seimei",
    "primbon": "primbon", "weton": "weton",
    "western": "western", "natal": "natal", "transit": "transit",
    "vedic": "vedic", "genekeys": "genekeys", "bazi": "bazi",
    "shibi": "ziwei", "sanmeigaku": "sanmei", "humandesign": "hd",
    "qimen": "qimen", "rokusei": "rokusei",
    "tarot": "tarot", "tarot_marseille": "marseille",
    "lenormand": "lenormand", "oracle": "oracle", "angel": "angel",
    "cartomancie": "cartomancy", "urban_tarot": "urbantarot",
    "rune": "runes", "kipper": "kipper",
    "iching": "iching", "liuyao": "liuyao", "meihua": "meihua",
    "synastry": "synastry", "parimicham": "parimicham",
    "prophecy": "christian",
    "crystal_healing": "crystal", "crystal_ball": "crystalball",
    "pendulum": "pendulum", "talisman": "talisman",
    "african": "african", "omikuji": "omikuji", "baru": "haruspex",
    "mesopotamian": "meso", "delphi": "delphi",
    "ornithomancy": "ornith", "astragali": "astragaloi",
}

# 本実装で新規追加した占術の today 指示（別AI由来ではないため個別定義）
EXTRA_TODAY = {
    "deities": (
        "【今日の運勢モード】相談内容がないため『今日の縁』として読み解きます。"
        "対象日に縁の深い神々として選ばれた10柱について、①今日という日に"
        "この顔ぶれが集まった意味 ②特に縁の強い上位3柱からのメッセージ "
        "③今日の過ごし方（具体的な行動）④結びの一言、の順で述べてください。"
        "対象日を必ず明記してください。"
    ),
}

# 逆引き（スラグ → 別AIキー）
SLUG_TO_OTHER_AI = {v: k for k, v in OTHER_AI_TO_SLUG.items()}

# 今日の運勢モードの共通ベース（個別指示がない占術・カバラ/数秘術（氏名）用）
GENERIC_TODAY = (
    "【今日の運勢モード】相談内容がないため、『今日の運勢（総合）』を出力します。"
    "構成: ①今日の運気（シンボルの性質が今日の運気にどう現れるか） ②ラッキーな要素"
    "（色・数字・方位など該当する場合） ③今日の過ごし方（行動・心構えのアドバイス）"
    "④全体運の一言。対象日が指定されている場合はその日、なければ今日の日付を明記。"
)

_DATA = None


def _load() -> dict:
    global _DATA
    if _DATA is None:
        try:
            _DATA = load_json("divinations_other_ai.json")
        except Exception:
            _DATA = {}
    return _DATA


def get_today_instruction(slug: str) -> str | None:
    """スラグ → 今日の運勢モードの個別指示（なければ共通ベース）"""
    if slug in EXTRA_TODAY:
        return EXTRA_TODAY[slug]
    key = SLUG_TO_OTHER_AI.get(slug)
    if key is None:
        return GENERIC_TODAY  # カバラ・数秘術（氏名）等は共通ベース
    d = _load()
    rec = d.get(key)
    if rec and rec.get("today"):
        return rec["today"]
    return GENERIC_TODAY
