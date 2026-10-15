# -*- coding: utf-8 -*-
"""Build the bundled broad Japanese fallback face.

Coverage: JIS X 0208 level 1 and 2, Japanese kana/punctuation/fullwidth forms,
the chart-font coverage, and non-dictionary project vocabulary. This is a
fallback for common Japanese output, not a promise to cover every Unicode code
point. The source Noto Serif CJK JP font is installed only in development
images; Kaggle receives this generated subset in assets/fonts/.

Usage from the repository root::

    python3 tools/build_jp_fallback_font.py
    python3 tools/build_jp_fallback_font.py --check
"""
from __future__ import annotations

import argparse
import glob
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "fortune_dataset"
FONTS = PKG / "assets" / "fonts"
SRC = Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc")
OUT = FONTS / "jp_cjk_fallback.ttf"
REQUIRED = "ガ司庫栞髙﨑神邊邉"


def _jis_kanji(rows) -> set[str]:
    """Extract JIS X 0208 Kanji for the requested rows from EUC-JP."""
    chars: set[str] = set()
    for row in rows:
        for cell in range(1, 95):
            try:
                ch = bytes([row + 0xA0, cell + 0xA0]).decode("euc_jp")
            except UnicodeDecodeError:
                continue
            if len(ch) == 1 and 0x4E00 <= ord(ch) <= 0x9FFF:
                chars.add(ch)
    return chars


VOCAB_SKIP_FILES = {"dataset_version.json", "ChatLog.md", "README.md"}
# 漢字をこれより多く含むファイルは辞書（字形表・読み表）とみなし語彙から除く
VOCAB_CJK_LIMIT = 1000


def _vocab_from_bundle() -> set[str]:
    """同梱データ（data/・prompts/）に出る文字＝生成文に出うる語彙。

    易経の卦名「澤雷隨」のような JIS 第2水準・水準外の字も、同梱データに出るものは
    すべて拾う（辞書的な巨大ファイルは除外）。
    """
    chars: set[str] = set()
    pats = ("fortune_dataset/data/*.json", "fortune_dataset/data/*.csv",
            "fortune_dataset/prompts*.json", "fortune_dataset/prompts/*.json",
            "fortune_dataset/data/*.md")
    for pat in pats:
        for f in glob.glob(str(ROOT / pat)):
            name = Path(f).name
            if name in VOCAB_SKIP_FILES:
                continue
            try:
                text = Path(f).read_text(encoding="utf-8")
            except Exception:
                continue
            if len({c for c in text if 0x4E00 <= ord(c) <= 0x9FFF}) > VOCAB_CJK_LIMIT:
                continue
            chars |= set(text)
    return {c for c in chars if not c.isspace()}


def target_chars() -> str:
    """Return source-supported fallback characters in stable order."""
    from fontTools.ttLib import TTFont

    if not SRC.is_file():
        raise FileNotFoundError(f"元フォントがありません: {SRC}（Noto Serif CJK JP が必要）")
    source = TTFont(str(SRC), fontNumber=0, lazy=True)
    try:
        source_cmap = set(source.getBestCmap() or {})
    finally:
        source.close()

    # Standard Japanese Kanji coverage plus kana, Japanese punctuation and
    # compatibility/fullwidth characters that often occur in reports and names.
    chars = set("".join(chr(cp) for cp in range(0x20, 0x7F)))
    chars |= _jis_kanji(range(16, 85))
    for lo, hi in ((0x00A0, 0x0100), (0x2000, 0x2070), (0x20A0, 0x2150),
                   (0x2460, 0x2500), (0x3000, 0x3100), (0x31F0, 0x3200),
                   (0x3200, 0x3300), (0xF900, 0xFB00), (0xFE30, 0xFE50),
                   (0xFF00, 0xFFF0)):
        chars.update(chr(cp) for cp in range(lo, hi))

    # Add all glyphs already used by the narrow chart face, plus the
    # manageable vocabulary found in the packaged data and prompts.
    for font_path in (FONTS / "typec_jp_subset.ttf",):
        if font_path.is_file():
            try:
                existing = TTFont(str(font_path), lazy=True)
                try:
                    chars.update(chr(cp) for cp in (existing.getBestCmap() or {}) if cp >= 0x20)
                finally:
                    existing.close()
            except Exception:
                pass
    chars |= _vocab_from_bundle()
    chars |= set(REQUIRED)

    usable = {ch for ch in chars if ch.isspace() or ord(ch) in source_cmap}
    missing = sorted(ch for ch in chars if not ch.isspace() and ord(ch) not in source_cmap)
    if missing:
        print("  （参考）Noto Serif CJK JP 元フォントに無い文字は除外: "
              + "".join(missing[:80]))
    return "".join(sorted(usable))


def _subset(chars: str) -> None:
    cmd = [sys.executable, "-m", "fontTools.subset", str(SRC),
           "--font-number=0", f"--text={chars}", f"--output-file={OUT}",
           "--layout-features=", "--no-hinting", "--desubroutinize"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("fontTools subset に失敗しました:\n" + result.stderr[-1200:])


def check() -> int:
    from fontTools.ttLib import TTFont

    if not OUT.is_file():
        print(f"❌ 同梱fallbackフォントがありません: {OUT}")
        return 1
    font = TTFont(str(OUT), lazy=True)
    try:
        cmap = set(font.getBestCmap() or {})
    finally:
        font.close()
    missing = [ch for ch in REQUIRED if ord(ch) not in cmap]
    if missing:
        print(f"❌ fallbackフォントに既知の日本語字がありません: {''.join(missing)}")
        return 1
    print(f"✅ {OUT.name}: {OUT.stat().st_size:,}B / {len(cmap):,} cmap字 / 既知の欠落字を収録")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="生成せず既存フォントを検査")
    args = ap.parse_args()
    if args.check:
        return check()
    chars = target_chars()
    FONTS.mkdir(parents=True, exist_ok=True)
    _subset(chars)
    print(f"作成: {OUT.name} / {OUT.stat().st_size:,}B / 要求 {len(chars):,}文字")
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
