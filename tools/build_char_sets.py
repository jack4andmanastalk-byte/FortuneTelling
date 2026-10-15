# -*- coding: utf-8 -*-
"""簡体字専用字形セットの生成（開発側の一回作業）

- 日本語の常用・人名漢字（KANJIDIC2 の grade 1〜10＝2,999字）を「日本語で使う字」の正本とする
  （出典: fortune_dataset/data/kanji_kakusu_combined.json の grade つきの字）
- zhconv（簡体字→繁体字の変換表）で「字形が変わる字」を簡体字候補とし、
  日本語の字を除外したものを tools/simplified_only.txt に保存する
- ツール本体（check_scripts.py）はこの txt だけを読むため、実行時に zhconv は不要
"""
from __future__ import annotations
import json
from pathlib import Path

import zhconv

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "fortune_dataset"

combined = json.loads((PKG / "data" / "kanji_kakusu_combined.json").read_text(encoding="utf-8"))
jp = {ch for ch, v in combined.items() if v.get("grade")}
# 常用漢字一覧（文化庁告示準拠・Wikipedia 2026-09 時点の生データから抽出した tools/jp_kanji_whitelist.txt）を併合
wl = ROOT / "tools" / "jp_kanji_whitelist.txt"
if wl.exists():
    jp |= set(wl.read_text(encoding="utf-8"))

simp = set()
for cp in list(range(0x3400, 0xA000)) + list(range(0xF900, 0xFB00)):
    ch = chr(cp)
    try:
        if zhconv.convert(ch, "zh-tw") != ch:
            simp.add(ch)
    except Exception:
        pass

simp_only = sorted(simp - jp)
out = ROOT / "tools" / "simplified_only.txt"
out.write_text("".join(simp_only), encoding="utf-8")
print(f"JP(常用・人名)={len(jp)}  zhconv変化={len(simp)}  簡体字専用={len(simp_only)}  -> {out}")
print("例:", "".join(simp_only[:60]))
