# -*- coding: utf-8 -*-
"""
ヘボン式（パスポート式）ローマ字変換
仕様：プロンプト設計書付録A（仕様設計メモ §3.3）
- かな（ひらがな・カタカナ）→ ヘボン式ローマ字（大文字）
- 長音は母音単独表記に正規化（おう→O / うう→U / えい→E / いい→I / おお→O）
- 促音「っ」は後続子音の重ね（かった→KATTA）
- ん→N（後続に関わらずN）
"""
from __future__ import annotations

import re

# 清音
SEION = {
    "あ": "A", "い": "I", "う": "U", "え": "E", "お": "O",
    "か": "KA", "き": "KI", "く": "KU", "け": "KE", "こ": "KO",
    "さ": "SA", "し": "SHI", "す": "SU", "せ": "SE", "そ": "SO",
    "た": "TA", "ち": "CHI", "つ": "TSU", "て": "TE", "と": "TO",
    "な": "NA", "に": "NI", "ぬ": "NU", "ね": "NE", "の": "NO",
    "は": "HA", "ひ": "HI", "ふ": "FU", "へ": "HE", "ほ": "HO",
    "ま": "MA", "み": "MI", "む": "MU", "め": "ME", "も": "MO",
    "や": "YA", "ゆ": "YU", "よ": "YO",
    "ら": "RA", "り": "RI", "る": "RU", "れ": "RE", "ろ": "RO",
    "わ": "WA", "を": "O", "ん": "N",
}

# 濁音・半濁音
DAKUON = {
    "が": "GA", "ぎ": "GI", "ぐ": "GU", "げ": "GE", "ご": "GO",
    "ざ": "ZA", "じ": "JI", "ず": "ZU", "ぜ": "ZE", "ぞ": "ZO",
    "だ": "DA", "ぢ": "JI", "づ": "ZU", "で": "DE", "ど": "DO",
    "ば": "BA", "び": "BI", "ぶ": "BU", "べ": "BE", "ぼ": "BO",
    "ぱ": "PA", "ぴ": "PI", "ぷ": "PU", "ぺ": "PE", "ぽ": "PO",
}

# 拗音（小書き ゃゅょ）
YOON = {
    "きゃ": "KYA", "きゅ": "KYU", "きょ": "KYO",
    "しゃ": "SHA", "しゅ": "SHU", "しょ": "SHO",
    "ちゃ": "CHA", "ちゅ": "CHU", "ちょ": "CHO",
    "にゃ": "NYA", "にゅ": "NYU", "にょ": "NYO",
    "ひゃ": "HYA", "ひゅ": "HYU", "ひょ": "HYO",
    "みゃ": "MYA", "みゅ": "MYU", "みょ": "MYO",
    "りゃ": "RYA", "りゅ": "RYU", "りょ": "RYO",
    "ぎゃ": "GYA", "ぎゅ": "GYU", "ぎょ": "GYO",
    "じゃ": "JA", "じゅ": "JU", "じょ": "JO",
    "びゃ": "BYA", "びゅ": "BYU", "びょ": "BYO",
    "ぴゃ": "PYA", "ぴゅ": "PYU", "ぴょ": "PYO",
    "しぇ": "SHE", "じぇ": "JE", "ちぇ": "CHE", "でぃ": "DI",
    "ふぁ": "FA", "ふぃ": "FI", "ふぇ": "FE", "ふぉ": "FO",
    "うぃ": "WI", "うぇ": "WE", "つぁ": "TSA", "つぃ": "TSI",
    "つぇ": "TSE", "つぉ": "TSO", "ヴぁ": "VA", "ヴぃ": "VI",
    "ヴぇ": "VE", "ヴぉ": "VO",
}

_KANA = {**SEION, **DAKUON}
_LONG = {"う": "U", "い": "I", "え": "E", "お": "O"}  # 長音化する後続かな
_SOKUON_NEXT = {"ち": "T", "つ": "T", "し": "S", "ふ": "F", "か": "K", "き": "K",
                "く": "K", "け": "K", "こ": "K", "さ": "S", "す": "S", "せ": "S",
                "そ": "S", "た": "T", "て": "T", "と": "T", "ぱ": "P", "ぴ": "P",
                "ぷ": "P", "ぺ": "P", "ぽ": "P", "ば": "B", "び": "B", "ぶ": "B",
                "べ": "B", "ぼ": "B", "が": "G", "ぎ": "G", "ぐ": "G", "げ": "G",
                "ご": "G", "ざ": "Z", "じ": "J", "ず": "Z", "ぜ": "Z", "ぞ": "Z",
                "だ": "D", "ぢ": "J", "づ": "Z", "で": "D", "ど": "D", "ま": "M",
                "み": "M", "む": "M", "め": "M", "も": "M", "な": "N", "に": "N",
                "ぬ": "N", "ね": "N", "の": "N", "ら": "R", "り": "R", "る": "R",
                "れ": "R", "ろ": "R", "は": "H", "ひ": "H", "へ": "H", "ほ": "H",
                "や": "Y", "ゆ": "Y", "よ": "Y", "わ": "W"}


def _to_romaji_one(ch: str) -> str:
    """1かな（ひらがな）→ ローマ字（清音・濁音・単独）"""
    return _KANA.get(ch)


def _normalize_long(s: str) -> str:
    """長音の正規化（母音単独表記）"""
    s = s.replace("OU", "O").replace("UU", "U").replace("EI", "E") \
         .replace("II", "I").replace("OO", "O")
    return s


def kana_to_hepburn(text: str) -> str:
    """
    かな（ひらがな・カタカナ混合可）→ ヘボン式ローマ字（大文字）

    例:
      "やまだたろう"     -> "YAMADATARO"
      "やまだ たろう"    -> "YAMADA TARO"
      "とうきょう"       -> "TOKYO"
      "がっこう"         -> "GAKKO"
      "しんじゅく"       -> "SHINJUKU"
    """
    # カタカナ→ひらがな
    text = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)
    text = text.replace("ー", "・")  # 長音符号は後段で「前母音重ね」処理（プレースホルダ）

    out = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            out.append(" ")
            i += 1
            continue
        if ch == "・":  # 長音符号：直前の母音を重ねる
            if out and out[-1][-1] in "AEIOU":
                out[-1] = out[-1] + out[-1][-1]
            i += 1
            continue
        # 拗音（2文字）
        if i + 1 < n and text[i + 1] in "ゃゅょぁぃぅぇぉ" and (ch + text[i + 1]) in YOON:
            out.append(YOON[ch + text[i + 1]])
            i += 2
            continue
        # 促音「っ」
        if ch == "っ":
            if i + 1 < n:
                nxt = text[i + 1]
                if nxt == "・":
                    # っー（無音長音）: TTSU 扱いはせず「T」とする
                    out.append("T")
                    i += 1
                elif nxt in _SOKUON_NEXT:
                    out.append(_SOKUON_NEXT[nxt])
                else:
                    out.append("T")  # 次が母音等（通常起きない）
            else:
                out.append("TSU")
            i += 1
            continue
        # 基本変換
        rom = _to_romaji_one(ch)
        if rom is None:
            out.append(ch)  # 変換不能文字はそのまま
        else:
            out.append(rom)
        i += 1

    joined = "".join(out)
    joined = _normalize_long(joined)
    return joined.upper()
