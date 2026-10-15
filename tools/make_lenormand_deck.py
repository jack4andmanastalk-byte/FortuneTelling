# -*- coding: utf-8 -*-
"""M27_lenormand（レノルマン 36 枚）の画像を、文字なしの原画から PIL で合成する。

方針（他デッキと同じ「絵と文字の分離」）:
  - 原画は生成 AI で作った**文字なし**の水彩画（`<bases>/NN_<NameEn>.png|webp|jpg`）。
  - 文字（番号・和名・英名）と枠は**すべて PIL で確定合成**する（フォント欠けや誤字を作らない）。
  - 出力は 288×432 WebP q80（`fortune_dataset/assets/images/M27_lenormand/NN_<NameEn>.webp`）。
    ファイル名は `data/lenormand_36.json` の `no`／`name_en` から決める（空白は詰める）。

使い方（リポジトリ直下）:
    python3 tools/make_lenormand_deck.py --bases /path/to/bases            # 36 枚すべて
    python3 tools/make_lenormand_deck.py --bases /path/to/bases --only 1,2 # 一部だけ
    python3 tools/make_lenormand_deck.py --check                            # 出力 36 枚の存在とサイズだけ確認
合成後は `verify/asset_checksums.sha256` を更新し、`verify/asset_matching_audit.py` と pytest を回す。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "fortune_dataset" / "data"
OUT = ROOT / "fortune_dataset" / "assets" / "images" / "M27_lenormand"

W, H = 288, 432
CREAM = (246, 239, 222)
INK = (92, 70, 48)
INK_SOFT = (150, 128, 100)
ART_BOX = (14, 14, W - 14, 334)          # 絵の領域（左, 上, 右, 下）
BANNER_Y = 342                           # 下帯の上端

FONT_JP_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    str(ROOT / "fortune_dataset" / "assets" / "fonts" / "jp_cjk_fallback.ttf"),
]
FONT_LATIN_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    str(ROOT / "fortune_dataset" / "assets" / "fonts" / "jp_cjk_fallback.ttf"),
]


def _font(cands: list[str], size: int) -> ImageFont.FreeTypeFont:
    for c in cands:
        if Path(c).is_file():
            return ImageFont.truetype(c, size, index=0)
    raise FileNotFoundError(cands)


def cards() -> list[dict]:
    return json.loads((DATA / "lenormand_36.json").read_text(encoding="utf-8"))


def slug_of(card: dict) -> str:
    return f"{card['no']:02d}_{re.sub(r'[^A-Za-z0-9]', '', card['name_en'])}"


def crop_to_ratio(im: Image.Image, ratio: float) -> Image.Image:
    w, h = im.size
    if w / h > ratio:
        nw = int(h * ratio)
        return im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    nh = int(w / ratio)
    return im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))


def compose(card: dict, base: Path, out_dir: Path) -> Path:
    x0, y0, x1, y1 = ART_BOX
    art = Image.open(base).convert("RGB")
    art = crop_to_ratio(art, (x1 - x0) / (y1 - y0)).resize((x1 - x0, y1 - y0), Image.LANCZOS)

    im = Image.new("RGB", (W, H), CREAM)
    im.paste(art, (x0, y0))
    d = ImageDraw.Draw(im)
    # 枠（外側の細線＋絵の縁）
    d.rectangle([3, 3, W - 4, H - 4], outline=INK_SOFT, width=1)
    d.rectangle([6, 6, W - 7, H - 7], outline=INK, width=1)
    d.rectangle([x0 - 1, y0 - 1, x1, y1], outline=INK, width=1)
    # 番号バッジ（左上の円）
    cx, cy, r = 30, 30, 13
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=CREAM, outline=INK, width=1)
    d.text((cx, cy), str(card["no"]), font=_font(FONT_LATIN_CANDIDATES, 13), fill=INK, anchor="mm")
    # 下帯: 和名（大）＋英名（小）
    d.line([x0, BANNER_Y, x1, BANNER_Y], fill=INK_SOFT, width=1)
    ja = card["name_ja"]
    f_ja = _font(FONT_JP_CANDIDATES, 30 if len(ja) <= 5 else (24 if len(ja) <= 7 else 19))
    d.text((W // 2, 372), ja, font=f_ja, fill=INK, anchor="mm")
    d.text((W // 2, 404), card["name_en"], font=_font(FONT_LATIN_CANDIDATES, 14), fill=INK_SOFT, anchor="mm")

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{slug_of(card)}.webp"
    im.save(out, "WEBP", quality=80, method=6)
    return out


def find_base(bases: Path, card: dict) -> Path | None:
    no = card["no"]
    for p in sorted(bases.iterdir()) if bases.is_dir() else []:
        if p.suffix.lower() in {".png", ".webp", ".jpg", ".jpeg"} and re.match(rf"^{no:02d}[_-]", p.name):
            return p
    return None


def check(out_dir: Path = OUT) -> int:
    missing, big = [], []
    for c in cards():
        p = out_dir / f"{slug_of(c)}.webp"
        if not p.is_file():
            missing.append(p.name)
            continue
        if p.stat().st_size > 45 * 1024:
            big.append(p.name)
        if Image.open(p).size != (W, H):
            big.append(p.name + "(size)")
    print(f"  M27_lenormand: {36 - len(missing)}/36 枚 / 45KB 超・サイズ違い {len(big)} / 欠落 {missing}")
    return 1 if (missing or big) else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bases", help="文字なし原画のディレクトリ（NN_*.png|webp|jpg）")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--only", default=None, help="例: 1,2,3")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        return check(Path(a.out))
    if not a.bases:
        ap.error("--bases を指定してください（--check のときは不要）")
    wanted = {int(x) for x in a.only.split(",")} if a.only else None
    done, skipped = [], []
    for c in cards():
        if wanted and c["no"] not in wanted:
            continue
        base = find_base(Path(a.bases), c)
        if base is None:
            skipped.append(c["no"])
            continue
        out = compose(c, base, Path(a.out))
        done.append(f"{out.name} ({out.stat().st_size / 1024:.1f}KB)")
    print(f"合成 {len(done)} 枚 / 原画なし {skipped}")
    for s in done:
        print("  ", s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
