# -*- coding: utf-8 -*-
"""
文書の異スクリプト混入チェック（日本語ドキュメント向け）

■ ERROR（混入として扱う）
  1) 中国語簡体字専用の字形 … tools/simplified_only.txt（**件数は実行時に表示**）
     ※ 日本語の常用・人名漢字（KANJIDIC2 の grade つきの字。tools/jp_kanji_whitelist.txt＋
        data/kanji_kakusu_combined.json）を正本として除外済み。生成は
        tools/build_char_sets.py（zhconv の簡体字→繁体字変換表から導出・実行時依存なし）
     ※ mts5.32 のdocstringにあった「2,634字／2,998字」は実データ（2,633字／2,999字）と
        1字ずれていたため、固定値をやめて実行時の表示に一本化した（mts5.52・F-6）
  2) ハングル      U+1100–11FF / 3130–318F / A960–A97F / AC00–D7FF
  3) デーヴァナーガリー U+0900–097F / A8E0–A8FF
  4) キリル文字    U+0400–04FF / 0500–052F

■ WARN（混入ではないが目視推奨）
  日本語常用・人名漢字の範囲外にある漢字（例: 繁体字・旧字体の引用）。data/*.json の
  旧字体・簡体字は古典用語として正しいため（凍結ルール4）、本チェックはドキュメント
  （.md 等）にのみ使う。

使い方:
  python3 tools/check_scripts.py FILE [FILE ...]
  python3 tools/check_scripts.py --all          # /home/user 配下の .md を一括
終了コード: 0=ERROR なし / 1=ERROR あり / 2=**正本が読めない（検査不能）**

mts5.52（F-6）: 正本（simplified_only.txt / jp_kanji_whitelist.txt /
data/kanji_kakusu_combined.json）が読めない場合は **exit 2 で停止**する。
従来は `except Exception` で空集合に落ちて**簡体字の検出が黙って無効化**され、
簡体字だけの文書に「[OK] 混入なし」exit 0 を返していた（＝検査したつもりの誤り）。
"""
from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "fortune_dataset"
SIMPLE_TXT = Path(__file__).resolve().parent / "simplified_only.txt"
JP_WHITELIST_TXT = Path(__file__).resolve().parent / "jp_kanji_whitelist.txt"

RANGES = {
    "ハングル": [(0x1100, 0x11FF), (0x3130, 0x318F), (0xA960, 0xA97F), (0xAC00, 0xD7FF)],
    "デーヴァナーガリー": [(0x0900, 0x097F), (0xA8E0, 0xA8FF)],
    "キリル文字": [(0x0400, 0x04FF), (0x0500, 0x052F)],
}


def load_jp_kanji() -> tuple[set[str], list[str]]:
    """日本語の常用・人名漢字（KANJIDIC2 の grade 1〜10）を正本から読む。

    戻り値 (集合, 読めなかった正本の一覧)。**読めなかったことを呼び出し側へ伝える**
    （mts5.52・F-6: 以前は空集合に落ちて WARN 判定が黙って無効化されていた）。
    """
    missing: list[str] = []
    jp: set[str] = set()
    try:
        data = json.loads((PKG / "data" / "kanji_kakusu_combined.json").read_text(encoding="utf-8"))
        jp = {ch for ch, v in data.items() if v.get("grade")}
    except Exception:
        missing.append("data/kanji_kakusu_combined.json")
    try:
        jp |= set(JP_WHITELIST_TXT.read_text(encoding="utf-8"))
    except Exception:
        missing.append(f"{JP_WHITELIST_TXT.name}（{JP_WHITELIST_TXT.parent.name}/）")
    return jp, missing


def _load_simplified_checked() -> tuple[set[str], list[str]]:
    """簡体字専用字形の正本を読む。読めなければ「読めなかった」ことを返す（mts5.52・F-6）。"""
    try:
        return set(SIMPLE_TXT.read_text(encoding="utf-8")), []
    except Exception:
        return set(), [f"{SIMPLE_TXT.name}（{SIMPLE_TXT.parent.name}/）"]


def load_simplified_only() -> set[str]:
    """簡体字専用字形の正本を返す（後方互換・集合のみ）。

    ※ 読めなかった場合も空集合を返すため、**呼び出し側は MISSING_REFERENCE を見ること**
      （本体は読めなければ exit 2 で停止する。mts5.52・F-6）。
    """
    return _load_simplified_checked()[0]


SIMPLIFIED_ONLY, _MISSING_SIMPLE = _load_simplified_checked()
JP_KANJI, _MISSING_JP = load_jp_kanji()
MISSING_REFERENCE = _MISSING_SIMPLE + _MISSING_JP


def classify(ch: str) -> tuple[str | None, str]:
    """(種別, 重大度) を返す。重大度: ERROR / WARN / ''"""
    cp = ord(ch)
    for name, rs in RANGES.items():
        for lo, hi in rs:
            if lo <= cp <= hi:
                return name, "ERROR"
    if ch in SIMPLIFIED_ONLY:
        return "中国語簡体字（日本語非使用字形）", "ERROR"
    is_cjk = (0x3400 <= cp <= 0x9FFF) or (0xF900 <= cp <= 0xFAFF) or (0x20000 <= cp <= 0x2FA1F)
    if is_cjk and JP_KANJI and ch not in JP_KANJI:
        return "日本語常用・人名漢字の範囲外（引用なら可）", "WARN"
    return None, ""


def scan_file(path: Path) -> tuple[int, int]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"[SKIP] {path}: {type(e).__name__}: {e}")
        return 0, 0
    errors = warns = 0
    buckets: dict[str, int] = {}
    for i, ch in enumerate(text):
        kind, sev = classify(ch)
        if not kind:
            continue
        line = text.count("\n", 0, i) + 1
        col = i - (text.rfind("\n", 0, i) + 1) + 1
        key = f"{sev}/{kind}:{ch}"
        buckets[key] = buckets.get(key, 0) + 1
        if sev == "ERROR":
            errors += 1
        else:
            warns += 1
        if buckets[key] <= 3:
            print(f"        {line}行{col}列  U+{ord(ch):04X}  [{sev}][{kind}]  {ch}  ({unicodedata.name(ch, '?')})")
    if errors or warns:
        print(f"[{'NG' if errors else 'WARN'}] {path}: ERROR {errors} / WARN {warns}")
        print("        集計: " + ", ".join(f"{k}×{v}" for k, v in sorted(buckets.items())[:12])
              + (" …" if len(buckets) > 12 else ""))
    else:
        print(f"[OK]   {path}（混入なし / {len(text)} 文字）")
    return errors, warns


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--all":
        # mts5.31: 実行環境に依存しないよう、リポジトリの親から探す
        files = sorted((Path(__file__).resolve().parent.parent.parent).rglob("*.md"))
        files = [f for f in files if "node_modules" not in f.parts and "trash" not in f.parts]
    else:
        files = [Path(a) for a in argv]
    total_err = total_warn = 0
    print(f"（正本: 簡体字専用 {len(SIMPLIFIED_ONLY)} 字 / 日本語漢字 {len(JP_KANJI)} 字）\n")
    if MISSING_REFERENCE:
        # mts5.52（F-6）: 正本が無いと簡体字の検出が黙って無効化される（＝検査したつもりの誤り）。
        # 空集合のまま「[OK] 混入なし」を返さず、検査不能として停止する。
        print("❌ 正本が読めないため検査できません（検出が無効化されます）:")
        for name in MISSING_REFERENCE:
            print(f"   - {name}")
        print("   → tools/build_char_sets.py で正本を再生成するか、リポジトリ全体で実行してください")
        return 2
    for f in files:
        e, w = scan_file(f)
        total_err += e
        total_warn += w
    print(f"\n=== 総合判定: {'ERROR あり（要修正）' if total_err else 'ERROR なし'}"
          f" / 対象 {len(files)} ファイル / ERROR {total_err} 件・WARN {total_warn} 件 ===")
    return 1 if total_err else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
