# -*- coding: utf-8 -*-
"""型Cチャート用サブセットフォントの再生成（mts5.32）

**このツールが必要な理由（2026-09-27 の不具合）**

Kaggle には日本語フォントが無いため、型Cは同梱サブセットフォントで描きます。
mts5.16〜5.31 は**手書きの文字リスト**からフォントを作っていたため、
後から増えた描画文字が反映されず、**文字が無言で消えて**いました
（デーヴァナーガリー数字・`乾`『赤』『字』『玄』『虎』『蛇』『軍』『鈴』『鉞』✓✗ など）。

**現在のやり方（推測しない）**

1. 22占術の描画を**実際に走らせて、描かれた文字を全部採取**する
   （`ImageDraw.text` と `F()/F_DEV()/F_SYM()` を包んで「どのフォントで何を描いたか」を記録）。
   値のバリエーション（本命星1〜9・数秘1〜9/11/22/33・六星の全タイプ・卦64種 等）も回す。
2. `chartdraw.py` の**文字列リテラル全部**を AST で足す（サンプルでは通らない分岐の保険）。
3. 採取した文字だけを元フォントから抽出して `assets/fonts/*.ttf` を作る。
4. **作ったフォントで全部の文字が描けることを確認**（1つでも欠けたら中止）。

使い方（リポジトリ直下で）::

    python3 tools/build_chart_fonts.py            # 生成して検証
    python3 tools/build_chart_fonts.py --check    # 生成せず「欠け」だけ検査

元フォントは `tools/font_sources/`（配布ZIPには含めません）。
"""
from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]              # リポジトリ直下
PKG = ROOT / "fortune_dataset"
FONTS = PKG / "assets" / "fonts"
SOURCES = ROOT / "tools" / "font_sources"

CJK_SRC = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"
DEV_SRC = SOURCES / "NotoSansDevanagari-Regular.ttf"
SYM_SRC = SOURCES / "NotoSansSymbols-Regular.ttf"
SYM2_SRC = SOURCES / "NotoSansSymbols2-Regular.ttf"

OUT_CJK = FONTS / "typec_jp_subset.ttf"
OUT_DEV = FONTS / "typec_devanagari_subset.ttf"
OUT_SYM = FONTS / "typec_symbols_subset.ttf"

# 予備（コードに現れないが今後出うる共通文字。これだけは手で足す）
MARGIN = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz" \
         " ．，・：；（）［］【】「」『』〜～ー−-–/／％%＋+＝=×÷°※→←" \
         "✓✗☉☽☿♀♂♃♄♅♆♇♈♉♊♋♌♍♎♏♐♑♒♓०१२३४५६७८९"


# --------------------------------------------------------------------------- #
# 1. 実際に描かれる文字の採取
# --------------------------------------------------------------------------- #

def _literals_in_chartdraw() -> str:
    """chartdraw.py の文字列リテラル（サンプルでは通らない分岐の保険）

    説明文（docstring）は描かれないので除きます（例: 楔形の説明に含まれる 𒁹 は
    文字ではなくベクタで描くため）。
    """
    src = (PKG / "fortunelib" / "chartdraw.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docs.add(id(body[0].value))
    return "".join(n.value for n in ast.walk(tree)
                   if isinstance(n, ast.Constant) and isinstance(n.value, str)
                   and id(n) not in docs)


def _ensure_path() -> None:
    """fortune_dataset/ を import パスへ（このツールはリポジトリ直下から実行する）"""
    if str(PKG) not in sys.path:
        sys.path.insert(0, str(PKG))


def _sample_cases():
    """22占術 × 値のバリエーション（描画コードを網羅するための入力）"""
    _ensure_path()
    from fortunelib.calc.astrology import (natal_chart, to_jd,
                                           transit_chart, vedic_sidereal)
    from fortunelib.calc.bazi import bazi_paipan
    from fortunelib.calc.hd_full import calculate_chart
    from fortunelib.calc.parimicham import parimicham_calc
    from fortunelib.calc.qimen import qimen_pan
    from fortunelib.calc.sanmeigaku import sanmeigaku_full
    from fortunelib.calc.seimei import seimei_calc
    from fortunelib.calc.ziwei import ziwei_chart

    cases: list[tuple[str, object, object]] = []

    # 九星気学（本命星 1〜9 × 年）
    for honmei in range(1, 10):
        cases.append(("M03_kyusei", {"year": 1985, "honmei_no": honmei,
                                     "honmei": ""}, None))
    # 数秘（ライフパス 1〜9・11・22・33）
    for n in list(range(1, 10)) + [11, 22, 33]:
        cases.append(("M04_numerology_birth",
                      {"life_path": n, "date": "1985-07-15"},
                      {"number": n, "romaji": "Takahashi Ren"}))
        cases.append(("M05_numerology_name", {"number": n, "romaji": "Hanako Yamada"}, None))
        cases.append(("M06_kabbalah", {"romaji": "Takahashi Ren", "number": n}, None))
    # カルデア・タントラ・アンカ（1〜9）
    for n in range(1, 10):
        cases.append(("M07_chaldean", {"number": n, "romaji": "Ken Sato"}, None))
        cases.append(("M04_tantra", {"number": n}, None))
        cases.append(("M04_anka", {"number": n}, None))
    # 六星（12タイプ × 年運の代表）
    for t in ("土星人プラス", "土星人マイナス", "金星人プラス", "金星人マイナス",
              "火星人プラス", "火星人マイナス", "天王星人プラス", "天王星人マイナス",
              "木星人プラス", "木星人マイナス", "水星人プラス", "水星人マイナス"):
        for cyc in ("大殺界", "種子", "緑生", "立花", "健弱", "達成", "乱気",
                    "再会", "財成", "安定", "陰影", "停止", "減退"):
            cases.append(("M10_rokusei", {"type": t, "cycle": cyc,
                                          "target_year": 2026}, None))
    # ウェトン・プリンボン（曜日 × パサラン）
    for d in ("月曜", "火曜", "水曜", "木曜", "金曜", "土曜", "日曜"):
        for p in ("Legi", "Pahing", "Pon", "Wage", "Kliwon"):
            cases.append(("M14_weton", {"weton_name": f"{d}・{p}", "pasaran": p}, None))
            cases.append(("M13_primbon", {"weton": f"{d}・{p}",
                                          "neptu_total": 7 + len(p) % 9}, None))
    # 四柱推命（複数日）
    for (y, m, d) in ((1978, 7, 7), (1985, 1, 1), (2000, 12, 31), (1990, 5, 20)):
        cases.append(("M17_bazi", bazi_paipan(y, m, d, 12, 0, lon_east=139.7,
                                              apply_true_solar=True), None))
    # ヴェーダ（複数日）× 算命学 × 奇門遁甲
    for (y, m, d) in ((1978, 7, 7), (1985, 1, 1), (2000, 12, 31)):
        cases.append(("M19_vedic", vedic_sidereal(to_jd(y, m, d, 12.0)), None))
        cases.append(("M21_sanmei", {"status": "ok", **sanmeigaku_full(y, m, d)}, None))
    for (y, m, d, hh) in ((2026, 9, 26, 9), (2026, 1, 1, 0), (2026, 12, 31, 23)):
        cases.append(("M24_qimen", qimen_pan(y, m, d, hh, 0), None))
    # 姓名判断
    for (sei, mei) in (("高", "橋連"), ("山", "田花子"), ("佐", "藤一")):
        cases.append(("M16_seimei", seimei_calc(sei, mei), None))
    # 西洋系
    charts = [natal_chart(1978, 7, 7, 12.0, 35.7, 139.7),
              natal_chart(1980, 1, 15, 10.0, 35.7, 139.7),
              natal_chart(1990, 11, 3, 5.5, 35.7, 139.7)]
    for ch in charts:
        cases.append(("M18_western", ch, None))
        cases.append(("M18_natal", ch, None))
        cases.append(("M18_transit", transit_chart(ch), ch))
    cases.append(("M18_synastry", {"aspects": [], "mine": charts[0],
                                   "theirs": charts[1]}, None))
    # 紫微斗数（複数日）× ヒューマンデザイン × パリミチャム
    for (y, m, d) in ((1978, 7, 7), (1990, 5, 20), (2001, 2, 3)):
        cases.append(("M20_ziwei", ziwei_chart(y, m, d, 12, gender="male"), None))
        cases.append(("M25_hd", calculate_chart(y, m, d, 12, 0, 9.0), None))
    for (a, b) in (("1978-07-07", "1980-01-15"), ("1990-05-20", "1991-06-21")):
        p = parimicham_calc({"date": a}, {"date": b}, role1="本人", role2="相手")
        p["status"] = "ok"
        cases.append(("M15_parimicham", p, None))
    return cases


def _role_of(font) -> str:
    """描画に使われたフォントの役割（実体のパスで判定＝フォールバックも正しく扱う）"""
    p = str(getattr(font, "path", "") or "")
    if p == str(OUT_DEV):
        return "dev"
    if p == str(OUT_SYM):
        return "sym"
    return "cjk"


def capture_chars(verbose: bool = True) -> dict[str, set[str]]:
    """22占術を実際に描いて「フォント役割ごとに描かれた文字」を返す

    役割は**実際に使われたフォントの実体**で判定します（同梱フォントが無いときは
    F_DEV/F_SYM が本フォントへフォールバックするため、要求ではなく実体で見るのが正）。
    """
    _ensure_path()
    from PIL import ImageDraw

    from fortunelib import chartdraw as cd

    seen: dict[str, set[str]] = {"cjk": set(), "dev": set(), "sym": set(), "other": set()}
    orig_text = ImageDraw.ImageDraw.text
    orig_ml = ImageDraw.ImageDraw.multiline_text

    def record(text, font):
        seen[_role_of(font)].update(str(text))

    def text_spy(self, xy, text, *a, **kw):
        record(text, kw.get("font"))
        return orig_text(self, xy, text, *a, **kw)

    def ml_spy(self, xy, text, *a, **kw):
        record(text, kw.get("font"))
        return orig_ml(self, xy, text, *a, **kw)

    ImageDraw.ImageDraw.text = text_spy
    ImageDraw.ImageDraw.multiline_text = ml_spy
    n_ok = n_ng = 0
    try:
        for slug, calc, extra in _sample_cases():
            try:
                cd.render_for_slug(slug, calc, extra)
                n_ok += 1
            except Exception as e:            # 入力が想定外でも採取は続ける
                n_ng += 1
                if verbose:
                    print(f"  （参考）{slug} は描画できませんでした: {type(e).__name__}: {e}")
    finally:
        ImageDraw.ImageDraw.text = orig_text
        ImageDraw.ImageDraw.multiline_text = orig_ml
    if verbose:
        print(f"  採取: {n_ok} 描画 OK / {n_ng} 描画不可")
    return seen


# --------------------------------------------------------------------------- #
# 2. フォント生成
# --------------------------------------------------------------------------- #

def _subset(src: Path | str, out: Path, chars: str, font_number: int = 0) -> int:
    chars = "".join(sorted(set(chars)))
    cmd = [sys.executable, "-m", "fontTools.subset", str(src),
           f"--font-number={font_number}", f"--text={chars}",
           f"--output-file={out}", "--layout-features=", "--no-hinting",
           "--desubroutinize"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"subset に失敗: {src}\n{r.stderr[-800:]}")
    return len(chars)


def _cmap(path: Path) -> set[int]:
    from fontTools.ttLib import TTFont
    f = TTFont(str(path), fontNumber=0)
    s: set[int] = set()
    for t in f["cmap"].tables:
        s |= set(t.cmap.keys())
    return s


def _missing(path: Path, chars: str) -> str:
    have = _cmap(path)
    return "".join(ch for ch in sorted(set(chars)) if not ch.isspace() and ord(ch) not in have)


def build(check_only: bool = False) -> int:
    # --- 1回目の採取（同梱フォントが無い状態。要求ベースで候補を集める） ---
    first = capture_chars(verbose=False)
    cjk_src_have = _cmap(Path(CJK_SRC))
    dev_have = _cmap(DEV_SRC) if DEV_SRC.is_file() else set()
    sym_have = set()
    for src in (SYM_SRC, SYM2_SRC):
        if src.is_file():
            sym_have |= _cmap(src)

    literals = _literals_in_chartdraw()
    cand = {
        "cjk": set(first["cjk"]) | set(literals) | set(MARGIN),
        "dev": set(first["dev"]) | set(MARGIN),
        "sym": set(first["sym"]) | set(MARGIN),
    }
    # 元フォントが持っている文字だけを対象にする（持っていない文字は下で報告）
    plan = {
        "cjk": "".join(sorted(c for c in cand["cjk"] if ord(c) in cjk_src_have or c.isspace())),
        "dev": "".join(sorted(c for c in cand["dev"] if ord(c) in dev_have or c.isspace())),
        "sym": "".join(sorted(c for c in cand["sym"] if ord(c) in sym_have or c.isspace())),
    }
    print(f"  必要文字: CJK {len(set(plan['cjk']))} / DEV {len(set(plan['dev']))} / SYM {len(set(plan['sym']))}")

    dropped = {r: sorted(set(cand[r]) - set(plan[r])) for r in cand}
    for r, chs in dropped.items():
        if chs:
            print(f"  （参考）{r.upper()} の元フォントに無い文字は対象外: {''.join(chs)}")

    if not check_only:
        FONTS.mkdir(parents=True, exist_ok=True)
        if not Path(CJK_SRC).is_file():
            raise SystemExit(f"CJK元フォントがありません: {CJK_SRC}")
        for src in (DEV_SRC, SYM_SRC, SYM2_SRC):
            if not src.is_file():
                raise SystemExit(f"元フォントがありません: {src}（tools/font_sources/）")
        n = _subset(CJK_SRC, OUT_CJK, plan["cjk"], font_number=0)
        print(f"  作成 {OUT_CJK.name}: {OUT_CJK.stat().st_size}B / {n} 文字")
        n = _subset(DEV_SRC, OUT_DEV, plan["dev"])
        print(f"  作成 {OUT_DEV.name}: {OUT_DEV.stat().st_size}B / {n} 文字")
        # 記号は2つの元フォントを突き合わせる（☉ と ✓✗ は Symbols2、
        # 惑星・星座は Symbols にしか無い）
        tmp1, tmp2 = FONTS / "_sym1.ttf", FONTS / "_sym2.ttf"
        _subset(SYM_SRC, tmp1, plan["sym"])
        have1 = _cmap(tmp1)
        rest = "".join(ch for ch in sorted(set(plan["sym"]))
                       if ord(ch) not in have1 and not ch.isspace())
        if rest:
            _subset(SYM2_SRC, tmp2, rest)
        else:
            _subset(SYM2_SRC, tmp2, " ")
        from fontTools.merge import Merger
        Merger().merge([str(tmp1), str(tmp2)]).save(str(OUT_SYM))
        tmp1.unlink(missing_ok=True)
        tmp2.unlink(missing_ok=True)
        print(f"  作成 {OUT_SYM.name}: {OUT_SYM.stat().st_size}B / {len(set(plan['sym']))} 文字")

    # --- 2回目の採取（同梱フォントが実在する状態＝実際に使われたフォントで判定） ---
    second = capture_chars(verbose=False)
    ok = True
    for role, path, label in (("cjk", OUT_CJK, "CJK"), ("dev", OUT_DEV, "DEV"), ("sym", OUT_SYM, "SYM")):
        need = second[role]
        if not path.is_file():
            print(f"  ✗ {label}: ファイルがありません {path}")
            ok = False
            continue
        miss = _missing(path, "".join(sorted(need)))
        if miss:
            print(f"  ✗ {label}: 描くのに足りない文字 {len(miss)}: {miss}")
            ok = False
        else:
            print(f"  ○ {label}: {path.stat().st_size}B / 実際に描く {len(need)} 文字すべてを保持")
    unused = {r: sorted(set(MARGIN) - second[r]) for r in ("cjk", "dev", "sym")}
    for r, chs in unused.items():
        if chs:
            print(f"  （参考）{r.upper()} の予備文字（今回未使用）: {''.join(chs)[:60]}")
    print("  → 検証:", "OK" if ok else "NG")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="生成せず、いまの同梱フォントが全部の文字を描けるかだけ検査")
    args = ap.parse_args()
    print(f"型Cサブセットフォント{'の検査' if args.check else 'の生成'}（mts5.32）")
    return build(check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
