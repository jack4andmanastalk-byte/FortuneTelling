# -*- coding: utf-8 -*-
"""
M16 姓名判断 — 統合画数辞書（約 103,000 字）アダプタ
出典: data/kanji_kakusu_combined.json（KANJIDIC2［EDRDG・CC BY-SA 4.0］の新字体画数を主とし、
      JIS 外の漢字は Unihan kTotalStrokes［Unicode License］で補完。かなは標準の筆順画数。
      生成は tools/build_kakusu_dict.py・出典の詳細は data/kanji_kakusu_license.json）
- 5格（天格・人格・地格・外格・総格）＋三才五行を算出
- 姓・名の分割は「全角スペース or 入力の区切り」を前提（呼び出し側で分割）
"""
from __future__ import annotations

from ..data import load_json

_DICT = None

# 五行（画数の1の位 → 五行）※ 姓名判断の一般的な対応
NUM_WUXING = {1: "木", 2: "木", 3: "火", 4: "火", 5: "土", 6: "土", 7: "金", 8: "金", 9: "水", 0: "水"}


def _dict():
    global _DICT
    if _DICT is None:
        _DICT = load_json("kanji_kakusu_combined.json")
    return _DICT


def strokes_of(kanji: str):
    """1文字の画数（辞書になければ None）"""
    d = _dict()
    rec = d.get(kanji)
    if rec is None:
        return None
    return rec.get("strokes")


def _sum_strokes(s: str) -> int:
    total = 0
    missing = []
    for ch in s:
        v = strokes_of(ch)
        if v is None:
            missing.append(ch)
        else:
            total += v
    return total, missing


def seimei_calc(surname: str, given: str) -> dict:
    """
    姓名判断（五格剖象法系）の計算。

    Args:
        surname: 姓（例: 山田）
        given: 名（例: 太郎）

    Returns:
        dict: 5格・三才・五行・辞書外文字
    """
    s_total, s_missing = _sum_strokes(surname)
    g_total, g_missing = _sum_strokes(given)
    all_missing = s_missing + g_missing

    tenkaku = s_total + 1          # 天格 = 姓の画数 + 1
    jinkaku = s_total + g_total    # 人格 = 姓＋名の合計（姓の最後＋名の最初）
    # より正確には: 人格 = 姓の最後の字 + 名の最初の字。姓1字なら 姓+名頭
    if len(surname) >= 1 and len(given) >= 1:
        last_s = strokes_of(surname[-1]) or 0
        first_g = strokes_of(given[0]) or 0
        jinkaku = last_s + first_g
    chikaku = g_total + 1          # 地格 = 名の画数 + 1
    gaikaku = tenkaku + chikaku - jinkaku  # 外格 = 天格＋地格−人格
    sokaku = s_total + g_total     # 総格 = 姓＋名の合計

    five = {"天格": tenkaku, "人格": jinkaku, "地格": chikaku,
            "外格": gaikaku, "総格": sokaku}
    san_sai = {k: NUM_WUXING[v % 10] for k, v in five.items()}

    return {
        "surname": surname, "given": given,
        "strokes": {"姓": s_total, "名": g_total},
        "five_grilles": five,
        "san_sai": san_sai,
        "missing_chars": all_missing,
        "references": ["data/kanji_kakusu_combined.json（KANJIDIC2 新字体画数＋Unihan 補完・約103,000字）"],
        "notes": ["画数は新字体の標準画数（KANJIDIC2＝常用漢字表準拠）を主とし、康熙字典体の流派では異なる場合があります",
                  "※ 海=9画（新字体）/10画（康熙字典体）等の流派差あり"],
    }
