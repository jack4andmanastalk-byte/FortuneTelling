# -*- coding: utf-8 -*-
"""姓名判断の画数辞書 `data/kanji_kakusu_combined.json` を公開データから作る。

出典（いずれも再配布可能なライセンス）:
  1. KANJIDIC2（EDRDG・CC BY-SA 4.0）… JIS X 0208/0212/0213 の 13,108 字。
     `misc/stroke_count` の先頭値（常用漢字表に準拠した新字体の画数）を採用し、
     `misc/grade`（1〜8＝常用漢字、9〜10＝人名用漢字）があれば `grade` として残す。
     https://www.edrdg.org/kanjidic/kanjidic2.xml.gz
  2. Unihan `kTotalStrokes`（Unicode License v3）… KANJIDIC2 に無い CJK 統合漢字の補完。
     複数値（zh-Hans／zh-Hant）のときは先頭値。
     https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip の Unihan_IRGSources.txt
  3. かな … 学校教育の筆順に基づく標準的な画数（事実情報）。濁点 +2・半角 −／半濁点 +1。

出力の形:  { "字": {"strokes": 画数, "source": "kanjidic2"|"unihan"|"kana", "grade": 1..10（任意）} }
（`fortunelib/calc/seimei.py` が `strokes` を、`tools/check_scripts.py` が `grade` の有無を読む）

使い方（リポジトリ直下）:
    python3 tools/build_kakusu_dict.py --kanjidic2 /tmp/kanjidic2.xml.gz \
        --unihan /tmp/unihan/Unihan_IRGSources.txt
    python3 tools/build_kakusu_dict.py --check          # 既存 JSON の整合だけ確かめる
"""
from __future__ import annotations

import argparse
import gzip
import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fortune_dataset" / "data" / "kanji_kakusu_combined.json"

#: ひらがな（清音・ゐゑ）の画数。濁音 +2、半濁音 +1、小書きは同じ。
HIRAGANA = {
    "あ": 3, "い": 2, "う": 2, "え": 2, "お": 3,
    "か": 3, "き": 4, "く": 1, "け": 3, "こ": 2,
    "さ": 3, "し": 1, "す": 2, "せ": 3, "そ": 1,
    "た": 4, "ち": 2, "つ": 1, "て": 1, "と": 2,
    "な": 4, "に": 3, "ぬ": 2, "ね": 2, "の": 1,
    "は": 3, "ひ": 1, "ふ": 4, "へ": 1, "ほ": 4,
    "ま": 3, "み": 2, "む": 3, "め": 2, "も": 3,
    "や": 3, "ゆ": 2, "よ": 2,
    "ら": 2, "り": 2, "る": 1, "れ": 2, "ろ": 1,
    "わ": 2, "ゐ": 1, "ゑ": 1, "を": 3, "ん": 1,
}
#: カタカナ（清音・ヰヱ）の画数。
KATAKANA = {
    "ア": 2, "イ": 2, "ウ": 3, "エ": 3, "オ": 3,
    "カ": 2, "キ": 3, "ク": 2, "ケ": 3, "コ": 2,
    "サ": 3, "シ": 3, "ス": 2, "セ": 2, "ソ": 2,
    "タ": 3, "チ": 3, "ツ": 3, "テ": 3, "ト": 2,
    "ナ": 2, "ニ": 2, "ヌ": 2, "ネ": 4, "ノ": 1,
    "ハ": 2, "ヒ": 2, "フ": 1, "ヘ": 1, "ホ": 4,
    "マ": 2, "ミ": 3, "ム": 2, "メ": 2, "モ": 3,
    "ヤ": 2, "ユ": 2, "ヨ": 3,
    "ラ": 2, "リ": 2, "ル": 2, "レ": 1, "ロ": 3,
    "ワ": 2, "ヰ": 4, "ヱ": 3, "ヲ": 3, "ン": 2,
}
_DAKUTEN = {  # 濁点つき → 清音
    "が": "か", "ぎ": "き", "ぐ": "く", "げ": "け", "ご": "こ",
    "ざ": "さ", "じ": "し", "ず": "す", "ぜ": "せ", "ぞ": "そ",
    "だ": "た", "ぢ": "ち", "づ": "つ", "で": "て", "ど": "と",
    "ば": "は", "び": "ひ", "ぶ": "ふ", "べ": "へ", "ぼ": "ほ",
    "ガ": "カ", "ギ": "キ", "グ": "ク", "ゲ": "ケ", "ゴ": "コ",
    "ザ": "サ", "ジ": "シ", "ズ": "ス", "ゼ": "セ", "ゾ": "ソ",
    "ダ": "タ", "ヂ": "チ", "ヅ": "ツ", "デ": "テ", "ド": "ト",
    "バ": "ハ", "ビ": "ヒ", "ブ": "フ", "ベ": "ヘ", "ボ": "ホ",
    "ヴ": "ウ",
}
_HANDAKUTEN = {"ぱ": "は", "ぴ": "ひ", "ぷ": "ふ", "ぺ": "へ", "ぽ": "ほ",
               "パ": "ハ", "ピ": "ヒ", "プ": "フ", "ペ": "ヘ", "ポ": "ホ"}
_SMALL = {"ぁ": "あ", "ぃ": "い", "ぅ": "う", "ぇ": "え", "ぉ": "お", "っ": "つ",
          "ゃ": "や", "ゅ": "ゆ", "ょ": "よ", "ゎ": "わ",
          "ァ": "ア", "ィ": "イ", "ゥ": "ウ", "ェ": "エ", "ォ": "オ", "ッ": "ツ",
          "ャ": "ヤ", "ュ": "ユ", "ョ": "ヨ", "ヮ": "ワ", "ヶ": "ケ", "ヵ": "カ"}


def kana_table() -> dict[str, int]:
    base = dict(HIRAGANA)
    base.update(KATAKANA)
    out = dict(base)
    for k, b in _DAKUTEN.items():
        out[k] = base[b] + 2
    for k, b in _HANDAKUTEN.items():
        out[k] = base[b] + 1
    for k, b in _SMALL.items():
        out[k] = base[b]
    out["ー"] = 1
    out["々"] = 3
    return out


def read_kanjidic2(path: Path) -> dict[str, dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as f:
        root = ET.parse(f).getroot()
    out: dict[str, dict] = {}
    for ch in root.findall("character"):
        lit = ch.find("literal").text
        counts = [int(s.text) for s in ch.findall("misc/stroke_count")]
        if not counts:
            continue
        ent = {"strokes": counts[0], "source": "kanjidic2"}
        g = ch.find("misc/grade")
        if g is not None and g.text:
            ent["grade"] = int(g.text)
        out[lit] = ent
    hdr = root.find("header")
    ver = {c.tag: c.text for c in hdr} if hdr is not None else {}
    print(f"  KANJIDIC2: {len(out):,} 字（{ver.get('database_version', '?')}・{ver.get('date_of_creation', '?')}）")
    return out


def read_unihan_total_strokes(path: Path) -> tuple[dict[str, int], str]:
    out: dict[str, int] = {}
    version = "?"
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.startswith("# Unicode Version"):
                version = line.split(":", 1)[-1].strip() if ":" in line else line.split()[-1]
            if line.startswith("#") or not line.strip():
                continue
            cp, field, value = line.rstrip("\n").split("\t", 2)
            if field != "kTotalStrokes":
                continue
            n = int(value.split()[0])
            out[chr(int(cp[2:], 16))] = n
    print(f"  Unihan kTotalStrokes: {len(out):,} 字（Unicode {version}）")
    return out, version


def build(kanjidic2: Path, unihan: Path, out: Path) -> dict:
    kd = read_kanjidic2(kanjidic2)
    uh, uver = read_unihan_total_strokes(unihan)
    combined: dict[str, dict] = {}
    for ch, n in uh.items():
        combined[ch] = {"strokes": n, "source": "unihan"}
    for ch, ent in kd.items():                       # KANJIDIC2 が優先
        combined[ch] = ent
    for ch, n in kana_table().items():
        combined[ch] = {"strokes": n, "source": "kana"}
    ordered = dict(sorted(combined.items(), key=lambda kv: ord(kv[0])))
    out.write_text(json.dumps(ordered, ensure_ascii=False, indent=1), encoding="utf-8")
    n_grade = sum(1 for v in ordered.values() if v.get("grade"))
    print(f"  → {out}（{len(ordered):,} 字・grade つき {n_grade:,} 字・Unicode {uver}）")
    return ordered


def check(out: Path = OUT) -> int:
    data = json.loads(out.read_text(encoding="utf-8"))
    bad = [k for k, v in data.items() if not isinstance(v.get("strokes"), int) or v["strokes"] <= 0]
    srcs = {}
    for v in data.values():
        srcs[v.get("source")] = srcs.get(v.get("source"), 0) + 1
    n_grade = sum(1 for v in data.values() if v.get("grade"))
    print(f"  {out.name}: {len(data):,} 字 / source {srcs} / grade つき {n_grade:,} 字 / 不正 {len(bad)}")
    for ch, want in (("海", 9), ("類", 18), ("像", 14), ("凪", 6), ("あ", 3), ("ア", 2), ("が", 5)):
        got = data.get(ch, {}).get("strokes")
        print(f"    {ch}: {got}（期待 {want}）{'OK' if got == want else 'NG'}")
        if got != want:
            bad.append(ch)
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kanjidic2", help="kanjidic2.xml または kanjidic2.xml.gz")
    ap.add_argument("--unihan", help="Unihan_IRGSources.txt（Unihan.zip 内）")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--check", action="store_true", help="既存 JSON の整合だけ確かめる")
    a = ap.parse_args()
    if a.check:
        return check(Path(a.out))
    if not (a.kanjidic2 and a.unihan):
        ap.error("--kanjidic2 と --unihan を指定してください（--check のときは不要）")
    build(Path(a.kanjidic2), Path(a.unihan), Path(a.out))
    return check(Path(a.out))


if __name__ == "__main__":
    raise SystemExit(main())
