# -*- coding: utf-8 -*-
"""
テキスト抽選型の占術（おみくじ方式）

■ 背景
  「メソポタミア天体オーメン」「キリスト教的預言」は計算アンカーを持たず、
  LLM が profile_facts だけを頼りに書くため、他の疑似体験系と内容が
  一様化していた（実機で確認）。

■ 方式
  おみくじと同じく、実在するテキストを1件ランダムに引き当て、
  それを起点に解釈を書かせる。
    - メソポタミア: Enūma Anu Enlil 系の実際のオーメン（前兆＋判断）
    - キリスト教的預言: 新約聖書の章句

  「引く」のはコード（RNG）、「読む」のが LLM という本プロジェクトの
  原則に沿う。引いた対象が毎回変わるため、出力の固有性が担保される。
"""
from __future__ import annotations

from ..data import load_json
from ..rng import FortuneRNG

_OMENS = None
_VERSES = None


def all_omens() -> list:
    global _OMENS
    if _OMENS is None:
        _OMENS = load_json("meso_omens.json")["omens"]
    return _OMENS


def all_verses() -> list:
    global _VERSES
    if _VERSES is None:
        _VERSES = load_json("bible_verses.json")["verses"]
    return _VERSES


def draw_omen(seed: int | None = None, rng_mode: str = "random") -> dict:
    """メソポタミア天体オーメンを1件引く（おみくじ方式）"""
    omens = all_omens()
    rng = FortuneRNG(seed=seed, mode=rng_mode)
    o = rng.choice(omens)
    return {
        "omen_id": o["id"],
        "protasis": o["protasis"],       # 前兆（もし〜ならば）
        "apodosis": o["apodosis"],       # 判断（〜であろう）
        "theme": o["theme"],
        "celestial_body": o["body"],
        "full_text": f"{o['protasis']}、{o['apodosis']}。",
        "drawn_from": f"全{len(omens)}件のオーメンより抽選",
        "references": ["data/meso_omens.json"],
        "notes": [
            "『エヌマ・アヌ・エンリル』系の定型オーメン（前兆＋判断の二部構成）",
            "実際のオーメンを1件抽選し、それを現代の相談に読み替える方式",
            "古代メソポタミアの占星術は本来、王と国家に関する公的な判断を"
            "扱うものであり、個人の運勢を占うものではなかった",
        ],
    }


def draw_verse(seed: int | None = None, rng_mode: str = "random") -> dict:
    """新約聖書の章句を1件引く（おみくじ方式）"""
    verses = all_verses()
    rng = FortuneRNG(seed=seed, mode=rng_mode)
    v = rng.choice(verses)
    return {
        "reference": v["ref"],
        "verse": v["text"],
        "theme": v["theme"],
        "full_text": f"「{v['text']}」（{v['ref']}）",
        "drawn_from": f"全{len(verses)}章句より抽選",
        "references": ["data/bible_verses.json"],
        "notes": [
            "新約聖書の章句を1件引き、黙想の手がかりとする方式",
            "キリスト教は本来、占いを未来予知の手段として用いない。"
            "本モードは聖句を読んで自らを省みる『黙想』の形式をとる",
            "特定の教派・翻訳を代表するものではない",
        ],
    }
