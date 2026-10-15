# -*- coding: utf-8 -*-
"""
型C 動的チャート描画（mts5.16）

方式（docs/images.md「型 C: 実行時チャート描画」）:
  ・占術ごとに**文字なしAIベース画像**を1枚同梱（assets/images/<slug>/<name>_base.webp）。
  ・実行時（Kaggle Notebook 内）に `calc` の決定論的結果を PIL で上書き描画する。
    LLM・外部モデルは不要。文字は画像生成AIに書かせず PIL のみ（手記§4準拠）。
  ・CJK グリフは同梱サブセットフォント assets/fonts/typec_jp_subset.ttf を優先し、
    文字列に欠落があれば同梱の広い日本語fallbackへ切り替える。fallbackにも無い字は警告する。

対象（パイロット3件）:
  M03_kyusei           九星気学（後天定位・本命星盤）
  M04_numerology_birth 数秘術（運命数／誕生日数／氏名数）
  M06_kabbalah         カバラ数秘術（生命の樹）

描画パラメータは docs/images.md「型 C」に記載のとおり（テストで固定）。
"""
from __future__ import annotations

import datetime as dt
import html as _html
import json
import warnings
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .font_fallback import fallback_drawing, font_covers_text, font_has_glyph

W, H = 300, 400          # このワークスペースでの作業サイズ（真サイズ288×432の縮小版・手記§4）
WEBP_Q = 80

_PKG_ROOT = Path(__file__).resolve().parents[1]          # fortune_dataset/
_BUNDLED_FONT = _PKG_ROOT / "assets" / "fonts" / "typec_jp_subset.ttf"
_BUNDLED_JP_FALLBACK = _PKG_ROOT / "assets" / "fonts" / "jp_cjk_fallback.ttf"
_BUNDLED_DEV = _PKG_ROOT / "assets" / "fonts" / "typec_devanagari_subset.ttf"
_BUNDLED_SYM = _PKG_ROOT / "assets" / "fonts" / "typec_symbols_subset.ttf"
_FALLBACK_FONTS = [
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
]

_font_cache: dict[int, ImageFont.FreeTypeFont] = {}
_font_source: str | None = None


def font_source() -> str:
    """現在使用中のフォントパス（テスト・デバッグ用）"""
    F(12)
    return _font_source or ""


def bundled_font_path() -> str:
    """同梱サブセットフォントのパス（無ければ空文字）"""
    return str(_BUNDLED_FONT) if _BUNDLED_FONT.is_file() else ""


def uses_bundled_font() -> bool:
    """現在の描画が同梱サブセットフォントを使っているか。

    mts5.28 追加。Kaggle には CJK フォントが無いため、**同梱フォントが無いと
    型Cの全チャートが豆腐（□□□）になる**（2026-09-26 の mts5.27 実機で発生）。
    ここで False が返る状態は「本番で文字が消える」危険信号。
    """
    src = font_source()
    return bool(src) and src == bundled_font_path()


def glyph_is_tofu(ch: str, size: int = 16) -> bool:
    """1文字が豆腐（.notdef と同じ絵）かどうかを判定する（テスト・検証用）。

    専用の未割当私用領域文字（U+E000）を基準に、同じマスクなら豆腐とみなす。
    一次フォントに無い字は、同梱の日本語fallbackが持っていればそのフォントで判定する。
    """
    ref = ""
    try:
        f = F(size)
        if _missing_in(f, ch):
            fallback = F_JP_FALLBACK(size)
            if fallback is not None and not _missing_in(fallback, ch):
                f = fallback
    except Exception:
        return True
    try:
        a = f.getmask(ch)
        b = f.getmask(ref)
    except Exception:
        return True
    if a.size == (0, 0) and b.size == (0, 0):
        return True
    return bytes(a) == bytes(b) and a.size == b.size


def _missing_in(font, ch: str, ref: str = "\ue000") -> bool:
    """フォントにその文字のグリフが無い（＝描いても出ない）か

    .notdef（未割当私用領域文字 U+E000）と同じ絵なら「無い」と判定します。
    mts5.32 追加: **文字が1つ欠ける不具合は平均差では見えず**、
    2026-09-27 にデーヴァナーガリー数字が無言で消えていました。
    """
    if ch.isspace():
        return False
    try:
        a = font.getmask(ch)
        b = font.getmask(ref)
    except Exception:
        return True
    if getattr(a, "size", (0, 0)) == (0, 0):
        return True                      # 空＝描かれない
    return bytes(a) == bytes(b) and a.size == getattr(b, "size", None)


def missing_glyphs(chars, role: str = "cjk") -> list[str]:
    """渡した文字のうち、その役割のフォントで描けない文字を返す（テスト・検証用）

    role: "cjk"（一次＋日本語fallback）/ "dev"（デーヴァナーガリー）/ "sym"（惑星・星座）
    """
    getter = {"cjk": F, "dev": F_DEV, "sym": F_SYM}.get(role, F)
    font = getter(14)
    unique = [ch for ch in dict.fromkeys(chars) if not ch.isspace()]
    if role == "cjk":
        fallback = F_JP_FALLBACK(14)
        return [ch for ch in unique
                if not font_has_glyph(font, ch)
                and (fallback is None or not font_has_glyph(fallback, ch))]
    return [ch for ch in unique if _missing_in(font, ch)]


def _role_of_font(font) -> str:
    """描画に使われたフォントの役割（実体のパスで判定＝フォールバックも正しく扱う）"""
    p = str(getattr(font, "path", "") or "")
    if p == str(_BUNDLED_DEV):
        return "dev"
    if p == str(_BUNDLED_SYM):
        return "sym"
    return "cjk"


def drawn_chars(slug: str, calc, extra=None) -> dict[str, set[str]]:
    """そのスラグの描画で**実際に使われた文字**を役割ごとに返す（テスト・検証用）

    ImageDraw.text / multiline_text を一時的に包んで採取します。
    """
    from PIL import ImageDraw as _ID
    seen: dict[str, set[str]] = {"cjk": set(), "dev": set(), "sym": set()}
    orig_text, orig_ml = _ID.ImageDraw.text, _ID.ImageDraw.multiline_text

    def _rec(text, font):
        seen[_role_of_font(font)].update(str(text))

    def _t(self, xy, text, *a, **kw):
        _rec(text, kw.get("font"))
        return orig_text(self, xy, text, *a, **kw)

    def _m(self, xy, text, *a, **kw):
        _rec(text, kw.get("font"))
        return orig_ml(self, xy, text, *a, **kw)

    _ID.ImageDraw.text, _ID.ImageDraw.multiline_text = _t, _m
    try:
        render_for_slug(slug, calc, extra)
    finally:
        _ID.ImageDraw.text, _ID.ImageDraw.multiline_text = orig_text, orig_ml
    return seen


# ---- mts5.53（P-4）: 同梱フォントの存在と被覆の起動時チェック --------------------- #
# 監査の指摘: `jp_cjk_fallback.ttf` を隠すと**警告0件のまま画像だけが変わり**
# （M15_parimicham で 55/120,000 px の差）、「警告0で画像だけ変わる」事故を
# 検出できなかった。実行の入口で4フォントの存在と代表文字の被覆を確かめる。
BUNDLED_FONT_FILES: dict[str, Path] = {
    "cjk": _BUNDLED_FONT,              # 型Cの一次フォント（日本語サブセット）
    "jp_fallback": _BUNDLED_JP_FALLBACK,   # 日本語の広いfallback
    "devanagari": _BUNDLED_DEV,        # デーヴァナーガリー数字
    "symbols": _BUNDLED_SYM,           # 惑星・星座記号・✓✗
}

#: 被覆を確かめる代表文字（実機で消えた文字＝tests/test_chart_font_coverage.py の
#: 「known key glyphs」＋ 各フォントの実際の用途から抜いた文字。フォントを作り直す
#: ときに落ちては困る文字だけを入れる＝増やしすぎると誤検知になる）
REQUIRED_GLYPHS: dict[str, str] = {
    "cjk": "乾赤字玄虎蛇初役擎軍鈴鉞旁路えしなや不利当該0123456789",
    "jp_fallback": "ガ司庫栞藤崎乾赤字玄虎蛇軍鉞路0123456789",
    "devanagari": "०१२३४५६७८९",
    "symbols": "☉☽☿♀♂♃♄♅♆♇♈♉♊♋♌♍♎♏♐♑♒♓✓✗",
}


def _font_missing(path: Path, chars: str) -> list[str]:
    """そのフォントが持っていない文字（存在しない/壊れている場合は全文字）。"""
    unique = [c for c in dict.fromkeys(chars) if c and not c.isspace()]
    try:
        font = ImageFont.truetype(str(path), 14)
    except Exception:
        return list(unique)
    return [c for c in unique if not font_has_glyph(font, c)]


def bundled_font_problems() -> list[str]:
    """同梱フォントの存在と被覆の問題（空リスト＝問題なし）。"""
    problems: list[str] = []
    for role, path in BUNDLED_FONT_FILES.items():
        if not Path(path).is_file():
            problems.append(f"同梱フォントがありません: {Path(path).name}（{path}）")
            continue
        try:
            if Path(path).stat().st_size < 2_000:
                problems.append(f"同梱フォントが小さすぎます（壊れている可能性）: {Path(path).name}")
                continue
        except Exception:
            pass
        missing = _font_missing(Path(path), REQUIRED_GLYPHS.get(role, ""))
        if missing:
            problems.append(f"{Path(path).name} に無い文字があります: "
                            f"{''.join(missing[:10])}"
                            f"（{' '.join(f'U+{ord(c):04X}' for c in missing[:5])}）"
                            "→ tools/build_chart_fonts.py で作り直してください")
    if not uses_bundled_font():
        problems.append("型Cの一次フォントが同梱物ではなくシステムフォントへ落ちています"
                        "（Kaggle では豆腐になります）")
    return problems


def check_bundled_fonts(verbose: bool = True) -> list[str]:
    """フォントチェックを実行し、結果を出力・警告台帳へ登録する（mts5.53・P-4）。"""
    problems = bundled_font_problems()
    n_chars = sum(len(v) for v in REQUIRED_GLYPHS.values())
    if verbose:
        if problems:
            for x in problems:
                print(f"  ⚠ {x}")
        else:
            print(f"  [フォント] 同梱{len(BUNDLED_FONT_FILES)}フォント OK（存在＋代表 {n_chars}字の被覆を確認）")
    for x in problems:
        try:
            from .runcheck import add_warning
            add_warning(x)
        except Exception:
            pass
    return problems


def missing_glyphs_for(slug: str, calc, extra=None) -> list[tuple[str, str]]:
    """その描画で「描かれるのにフォントに無い文字」を (役割, 文字) で返す

    空リスト＝すべて描ける（型Cの検証・テスト用 / mts5.32）。
    """
    seen = drawn_chars(slug, calc, extra)
    out: list[tuple[str, str]] = []
    for role in ("cjk", "dev", "sym"):
        for ch in missing_glyphs(sorted(seen.get(role, ())), role):
            out.append((role, ch))
    return out


def F(size: int) -> ImageFont.FreeTypeFont:
    global _font_source
    if size not in _font_cache:
        if _BUNDLED_FONT.is_file():
            _font_cache[size] = ImageFont.truetype(str(_BUNDLED_FONT), size)
            _font_source = str(_BUNDLED_FONT)
        else:
            for p in _FALLBACK_FONTS:
                if Path(p).exists():
                    try:
                        _font_cache[size] = ImageFont.truetype(p, size, index=0)
                    except Exception:
                        _font_cache[size] = ImageFont.truetype(p, size)
                    _font_source = p
                    break
            else:
                _font_cache[size] = ImageFont.load_default()
                _font_source = "default"
    return _font_cache[size]


_jp_fallback_cache: dict[int, ImageFont.FreeTypeFont] = {}


def F_JP_FALLBACK(size: int) -> ImageFont.FreeTypeFont | None:
    """広い日本語fallback（JIS第1・第2水準＋配布物語彙）。"""
    if not _BUNDLED_JP_FALLBACK.is_file():
        return None
    if size not in _jp_fallback_cache:
        try:
            _jp_fallback_cache[size] = ImageFont.truetype(str(_BUNDLED_JP_FALLBACK), size)
        except Exception:
            return None
    return _jp_fallback_cache.get(size)


def _note_missing_glyphs(missing: list[str]) -> None:
    """フォント欠落を**警告台帳**にも残す（mts5.63）。

    背景（2026-09-30 の mts5.62 実機）: 旧暦の簡体字「闰」が同梱フォントに無く、
    型Cチャートの文字が欠けたまま納品されました。実行ログには `RuntimeWarning` が
    出ていたものの、**実行の最後の「■ 警告」一覧には出てこない**ため見落とされます
    （検証器で初めて気づきました）。原因そのものは ziwei 側で直しましたが、
    **同じクラスの事故（使用文字とフォントの不一致）を毎回見える形**にしておきます。
    """
    try:
        from .runcheck import add_warning
        chars = "".join(dict.fromkeys(missing))[:8]
        add_warning("型Cチャートの文字が同梱フォントに無く、欠けて描画されます"
                    f"（{chars}）。tools/build_chart_fonts.py でフォントを作り直すか、"
                    "データ側の文字を日本語へ直してください")
    except Exception:            # 台帳が無い環境（単体利用）では黙って続ける
        pass


def _select_cjk_font(text: str, font):
    """欠けたCJK文字列はfallbackへ切り替え、未収録字が残る場合は警告する。"""
    if font is None or _role_of_font(font) != "cjk" or font_covers_text(font, text):
        return font
    size = int(getattr(font, "size", 14) or 14)
    fallback = F_JP_FALLBACK(size)
    missing_primary = [ch for ch in dict.fromkeys(text)
                       if not ch.isspace() and not font_has_glyph(font, ch)]
    missing = [ch for ch in missing_primary
               if fallback is None or not font_has_glyph(fallback, ch)]
    if missing:
        codes = " ".join(f"U+{ord(ch):04X}" for ch in missing[:8])
        warnings.warn("型Cの一次フォントと日本語fallbackの両方に無い文字があります: "
                      f"{''.join(missing[:8])} ({codes})", RuntimeWarning, stacklevel=3)
        _note_missing_glyphs(missing)          # mts5.63: 警告台帳へも残す
    # 文字列の一部しかfallbackで覆えなくても、覆える字は救済する。
    if fallback is not None and any(font_has_glyph(fallback, ch)
                                    for ch in missing_primary):
        return fallback
    return font


def _cjk_fallback_scope():
    """描画中だけPillow text/multiline_textへ日本語fallbackを適用する。"""
    return fallback_drawing(_select_cjk_font)


_dev_cache: dict[int, ImageFont.FreeTypeFont] = {}


def F_DEV(size: int) -> ImageFont.FreeTypeFont:
    """デーヴァナーガリー数字用（同梱サブセット。無ければ CJK フォントへフォールバック）"""
    if size not in _dev_cache:
        if _BUNDLED_DEV.is_file():
            _dev_cache[size] = ImageFont.truetype(str(_BUNDLED_DEV), size)
        else:
            _dev_cache[size] = F(size)
    return _dev_cache[size]


_sym_cache: dict[int, ImageFont.FreeTypeFont] = {}


def F_SYM(size: int) -> ImageFont.FreeTypeFont:
    """惑星・星座グリフ用（同梱サブセット。無ければ F() へフォールバック）"""
    if size not in _sym_cache:
        if _BUNDLED_SYM.is_file():
            _sym_cache[size] = ImageFont.truetype(str(_BUNDLED_SYM), size)
        else:
            _sym_cache[size] = F(size)
    return _sym_cache[size]


SYM_SUN, SYM_MOON, SYM_MERCURY, SYM_VENUS, SYM_MARS = "☉", "☽", "☿", "♀", "♂"
SYM_JUPITER, SYM_SATURN, SYM_URANUS, SYM_NEPTUNE, SYM_PLUTO = "♃", "♄", "♅", "♆", "♇"
PLANET_SYM = {"太陽": SYM_SUN, "月": SYM_MOON, "水星": SYM_MERCURY, "金星": SYM_VENUS,
              "火星": SYM_MARS, "木星": SYM_JUPITER, "土星": SYM_SATURN,
              "天王星": SYM_URANUS, "海王星": SYM_NEPTUNE, "冥王星": SYM_PLUTO}
SIGN_SYM = ["♈", "♉", "♊", "♋", "♌", "♍", "♎", "♏", "♐", "♑", "♒", "♓"]
ASPECT_COL = {"コンジャンクション": (214, 180, 100, 235),
              "セクスタイル": (116, 156, 216, 235),
              "スクエア": (214, 96, 76, 235),
              "トライン": (126, 186, 122, 235),
              "オポジション": (176, 126, 216, 235)}

DEV_DIGITS = "०१२३४५६७८९"  # Devanagari 0-9


def dev_str(n: int) -> str:
    return "".join(DEV_DIGITS[int(c)] for c in str(n))


def _draw_cuneiform(d: ImageDraw.ImageDraw, cx: float, cy: float, n: int,
                    color, s: float = 0.6) -> None:
    """メソポタミア数字（1-9）＝縦楔（𒁹）を3個/行で組んで PIL 描画。
    楔形文字フォントは同梱しない（形状が単純なためベクタ描画で確定表示）。"""
    w, h1, h2 = 20 * s, 24 * s, 14 * s
    gap_x, gap_y = w * 1.45, h1 + h2 + 8 * s
    counts: list[int] = []
    rem = max(1, min(9, n))
    while rem:
        counts.append(min(3, rem))
        rem -= min(3, rem)
    total_h = len(counts) * gap_y
    y = cy - total_h / 2 + 4 * s
    for cnt in counts:
        for i in range(cnt):
            x = cx + (i - (cnt - 1) / 2) * gap_x
            d.polygon([(x - w / 2, y), (x + w / 2, y), (x, y + h1)], fill=color)
            d.rectangle([x - 2.5 * s, y + h1 - 5 * s, x + 2.5 * s, y + h1 + h2],
                        fill=color)
        y += gap_y


# ---------------------------------------------------------------- ベース画像
# slug → (ベースファイル名, 和名ヘッダ, 英小見出)
TYPEC_DECKS = {
    "M03_kyusei": ("kyusei", "九星気学", "KYUSEI KIGAKU"),
    "M04_numerology_birth": ("numerology", "数秘術", "NUMEROLOGY CHART"),
    "M06_kabbalah": ("kabbalah", "カバラ数秘術", "TREE OF LIFE"),
    # バッチ1（2026-09-26 採用・サンプル提示）
    "M05_numerology_name": ("numerology", "数秘術（氏名）", "NAME NUMBER"),
    "M07_chaldean": ("chaldean", "カルデア数秘術", "CHALDEAN NUMEROLOGY"),
    "M04_tantra": ("tantra", "タントラ数秘術", "TANTRA NUMEROLOGY"),
    "M04_anka": ("anka", "アンカ・シャーストラ", "ANKA SHASTRA"),
    "M10_rokusei": ("rokusei", "六星占術", "ROKUSEI"),
    "M14_weton": ("weton", "ウェトン", "WETON JAVANESE"),
    "M13_primbon": ("primbon", "プリンボン・ジャワ", "PRIMBON JAWA"),
    # バッチ2（2026-09-26 サンプル作成）
    "M16_seimei": ("seimei", "姓名判断", "SEIMEI FIVE GRILLES"),
    "M17_bazi": ("bazi", "四柱推命", "FOUR PILLARS"),
    "M19_vedic": ("vedic", "ヴェーダ占星術", "VEDIC JYOTISH"),
    "M21_sanmei": ("sanmei", "算命学", "SANMEIGAKU"),
    "M24_qimen": ("qimen", "奇門遁甲", "QIMEN DUNJIA"),
    # B群・西洋占星術系（2026-09-26 サンプル提案・natal/western 意匠共有）
    "M18_western": ("astro", "西洋占星術", "WESTERN HOROSCOPE"),
    "M18_natal": ("astro", "ネイタル占星術", "NATAL CHART"),
    "M18_transit": ("astro", "トランジット分析", "TRANSIT"),
    "M18_synastry": ("synastry", "シナストリー", "SYNASTRY"),
    # B群残（2026-09-26 サンプル提案）
    "M20_ziwei": ("ziwei", "紫微斗数", "ZIWEI DOUSHU"),
    "M25_hd": ("hd", "ヒューマンデザイン", "HUMAN DESIGN"),
    "M15_parimicham": ("parimicham", "パリミチャム", "PORUTHAM"),
}

# アンカ・シャーストラの惑星対応（1=太陽…9=火星・batch.py の note と同一）
ANKA_PLANETS = {1: "太陽", 2: "月", 3: "木星", 4: "ラーフ", 5: "水星",
                6: "金星", 7: "ケートゥ", 8: "土星", 9: "火星"}

# 型Cスラグ全10件（パイロット3＋バッチ1・7）＝dispatch/検証/テストで共用
TYPEC_SLUGS = tuple(TYPEC_DECKS)


def load_base(slug: str, assets_root: Path | None = None) -> Image.Image | None:
    """ベース画像を解決する。assets_root 優先、同梱 assets/images へフォールバック。"""
    name = TYPEC_DECKS[slug][0]
    cands = []
    if assets_root is not None:
        cands.append(Path(assets_root) / slug / f"{name}_base.webp")
    cands.append(_PKG_ROOT / "assets" / "images" / slug / f"{name}_base.webp")
    for c in cands:
        if c.is_file():
            img = Image.open(c).convert("RGB")
            return img.resize((W, H)) if img.size != (W, H) else img
    return None


def _header(d: ImageDraw.ImageDraw, title_ja: str, sub_en: str, color, subcolor) -> None:
    d.text((W / 2, 26), title_ja, font=F(24), fill=color, anchor="mm")
    d.text((W / 2, 47), sub_en, font=F(10), fill=subcolor, anchor="mm")


# ---------------------------------------------------------------- M03 九星気学
GRID = [
    [(4, "巽", "東南"), (9, "離", "南"), (2, "坤", "西南")],
    [(3, "震", "東"), (5, "中", "中央"), (7, "兌", "西")],
    [(8, "艮", "東北"), (1, "坎", "北"), (6, "乾", "西北")],
]
KANJI = ["一", "二", "三", "四", "五", "六", "七", "八", "九"]


def render_kyusei(year: int, honmei_no: int) -> Image.Image:
    img = load_base("M03_kyusei")
    if img is None:
        img = Image.new("RGB", (W, H), (246, 242, 232))
    d = ImageDraw.Draw(img, "RGBA")
    ink = (35, 32, 45, 235)
    gold = (176, 138, 58, 255)
    _header(d, "九星気学", "KYUSEI KIGAKU", ink, gold)

    gx0, gy0, side = 42, 66, 216
    cell = side / 3
    for r in range(3):
        for c in range(3):
            if GRID[r][c][0] == honmei_no:
                d.rectangle([gx0 + c * cell + 2, gy0 + r * cell + 2,
                             gx0 + (c + 1) * cell - 2, gy0 + (r + 1) * cell - 2],
                            fill=(196, 62, 42, 46))
    d.rectangle([gx0, gy0, gx0 + side, gy0 + side], outline=ink, width=2)
    for i in (1, 2):
        d.line([gx0 + i * cell, gy0, gx0 + i * cell, gy0 + side], fill=ink, width=1)
        d.line([gx0, gy0 + i * cell, gx0 + side, gy0 + i * cell], fill=ink, width=1)
    from .calc import kyusei
    for r in range(3):
        for c in range(3):
            star, gua, dirja = GRID[r][c]
            cx = gx0 + (c + 0.5) * cell
            cy = gy0 + (r + 0.5) * cell
            hl = (star == honmei_no)
            num_color = (150, 42, 30, 255) if hl else ink
            d.text((cx, cy - 14), KANJI[star - 1], font=F(30), fill=num_color, anchor="mm")
            d.text((cx, cy + 13), kyusei.STAR_NAMES[star - 1], font=F(10),
                   fill=num_color if hl else (70, 66, 80, 235), anchor="mm")
            d.text((cx, cy + 27), f"{gua}・{dirja}", font=F(8),
                   fill=(96, 90, 104, 210), anchor="mm")
    for r in range(3):
        for c in range(3):
            if GRID[r][c][0] == honmei_no:
                d.rectangle([gx0 + c * cell + 1, gy0 + r * cell + 1,
                             gx0 + (c + 1) * cell - 1, gy0 + (r + 1) * cell - 1],
                            outline=(176, 138, 58, 255), width=2)
    d.text((W / 2, gy0 - 9), "南", font=F(10), fill=ink, anchor="mm")
    d.text((W / 2, gy0 + side + 11), "北", font=F(10), fill=ink, anchor="mm")
    d.text((gx0 - 13, gy0 + side / 2), "東", font=F(10), fill=ink, anchor="mm")
    d.text((gx0 + side + 13, gy0 + side / 2), "西", font=F(10), fill=ink, anchor="mm")
    d.line([50, 330, 250, 330], fill=gold, width=1)
    d.text((W / 2, 348), f"{year}年生", font=F(13), fill=ink, anchor="mm")
    d.text((W / 2, 370), f"本命星：{kyusei.STAR_NAMES[honmei_no - 1]}", font=F(16),
           fill=(150, 42, 30, 255), anchor="mm")
    return img


# ---------------------------------------------------------------- M04 数秘術
def render_numerology(life_path_no: int, birth: dt.date,
                      name_number: int | None = None,
                      romaji: str | None = None) -> Image.Image:
    img = load_base("M04_numerology_birth")
    if img is None:
        img = Image.new("RGB", (W, H), (246, 240, 226))
    d = ImageDraw.Draw(img, "RGBA")
    ink = (74, 52, 26, 240)
    gold = (160, 116, 40, 255)
    _header(d, "数秘術", "NUMEROLOGY CHART", ink, gold)

    from .calc import numerology
    bd = numerology.digital_root(birth.day)

    def medallion(cx: float, cy: float, r: int, num, label: str, big: bool) -> None:
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(252, 246, 230, 200),
                  outline=gold, width=2)
        d.ellipse([cx - r + 4, cy - r + 4, cx + r - 4, cy + r - 4],
                  outline=(160, 116, 40, 120), width=1)
        d.text((cx, cy - 4), str(num), font=F(44 if big else 30),
               fill=(120, 74, 22, 255), anchor="mm")
        d.text((cx, cy + r + 13), label, font=F(11), fill=ink, anchor="mm")

    if name_number is not None:
        medallion(W / 2, 128, 46, life_path_no, "運命数（ライフパス）", True)
        medallion(96, 252, 34, bd, "誕生日数", False)
        medallion(204, 252, 34, name_number, "氏名数", False)
    else:
        medallion(W / 2, 128, 46, life_path_no, "運命数（ライフパス）", True)
        medallion(W / 2, 252, 34, bd, "誕生日数", False)
    d.line([50, 322, 250, 322], fill=gold, width=1)
    d.text((W / 2, 340), f"{birth.isoformat()} 生", font=F(13), fill=ink, anchor="mm")
    if romaji:
        d.text((W / 2, 362), romaji.upper(), font=F(14), fill=(120, 74, 22, 255), anchor="mm")
    return img


# ---------------------------------------------------------------- M06 カバラ
SEPHIROT = [
    (1, "ケテル", 0.50, 0.06), (2, "ホクマー", 0.80, 0.18), (3, "ビナー", 0.20, 0.18),
    (4, "ケセド", 0.80, 0.42), (5, "ゲブラー", 0.20, 0.42), (6, "ティファレト", 0.50, 0.54),
    (7, "ネツァク", 0.80, 0.66), (8, "ホド", 0.20, 0.66), (9, "イェソド", 0.50, 0.80),
    (10, "マルクト", 0.50, 0.97),
]
PATHS = [(1, 2), (1, 3), (1, 6), (2, 3), (2, 4), (2, 6), (3, 5), (3, 6),
         (4, 5), (4, 6), (4, 7), (5, 6), (5, 8), (6, 7), (6, 8), (6, 9),
         (7, 8), (7, 9), (7, 10), (8, 9), (8, 10), (9, 10)]


def render_kabbalah(value: int, romaji: str) -> Image.Image:
    img = load_base("M06_kabbalah")
    if img is None:
        img = Image.new("RGB", (W, H), (16, 22, 44))
    d = ImageDraw.Draw(img, "RGBA")
    silver = (205, 213, 226, 255)
    gold = (214, 180, 100, 255)
    _header(d, "カバラ数秘術", "TREE OF LIFE", silver, gold)

    x0, y0, tw, th = 74, 74, 152, 252
    pos = {num: (x0 + sx * tw, y0 + sy * th) for num, _ja, sx, sy in SEPHIROT}
    for a, b in PATHS:
        d.line([pos[a], pos[b]], fill=(180, 190, 210, 150), width=1)
    r = 14
    for num, ja, _sx, _sy in SEPHIROT:
        cx, cy = pos[num]
        hl = (num == value)
        if hl:
            d.ellipse([cx - r - 4, cy - r - 4, cx + r + 4, cy + r + 4],
                      outline=(214, 180, 100, 200), width=2)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(24, 32, 60, 220),
                  outline=gold if hl else silver, width=2 if hl else 1)
        d.text((cx, cy), str(num), font=F(14), fill=gold if hl else silver, anchor="mm")
        d.text((cx, cy + r + 8), ja, font=F(8), fill=(220, 226, 238, 235), anchor="mm")
    d.line([60, 344, 240, 344], fill=gold, width=1)
    d.text((W / 2, 362), f"{romaji.upper()} → {value}", font=F(14), fill=gold, anchor="mm")
    return img


# ---------------------------------------------------------------- バッチ1: 数秘ファミリー
def _render_medallion_card(slug: str, number, label: str, foot: list[str],
                           digit: str = "arabic",
                           header_num: int | None = None,
                           y0: int = 0) -> Image.Image:
    """数秘ファミリー共通: 中央メダリオン1個＋フッター行。
    digit: "arabic" / "devanagari" / "cuneiform"。
    header_num: 指定時、占術名称の後にアラビア数字を挿入（ユーザー指定 2026-09-26）。"""
    img = load_base(slug)
    if img is None:
        img = Image.new("RGB", (W, H), (246, 240, 226))
    d = ImageDraw.Draw(img, "RGBA")
    base, ja, en = TYPEC_DECKS[slug]
    ink = (74, 52, 26, 240)
    gold = (160, 116, 40, 255)
    title = ja if header_num is None else f"{ja} {header_num}"
    if y0:
        # 装飾帯を避けて内側パネルへ小さめに配置（アンカ等）
        d.text((W / 2, 26 + y0), title, font=F(16), fill=ink, anchor="mm")
        d.text((W / 2, 44 + y0), en, font=F(9), fill=gold, anchor="mm")
    else:
        _header(d, title, en, ink, gold)
    cx, cy, r = W / 2, 150 + y0 // 2, 52
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(252, 246, 230, 200),
              outline=gold, width=2)
    d.ellipse([cx - r + 4, cy - r + 4, cx + r - 4, cy + r - 4],
              outline=(160, 116, 40, 120), width=1)
    if digit == "devanagari":
        d.text((cx, cy - 2), dev_str(int(number)), font=F_DEV(46),
               fill=(120, 74, 22, 255), anchor="mm")
    elif digit == "cuneiform":
        _draw_cuneiform(d, cx, cy, int(number), (120, 74, 22, 255))
    else:
        d.text((cx, cy - 4), str(number), font=F(48), fill=(120, 74, 22, 255), anchor="mm")
    d.text((cx, cy + r + 16), label, font=F(12), fill=ink, anchor="mm")
    d.line([50, 300, 250, 300], fill=gold, width=1)
    y = 322
    for line in foot:
        d.text((W / 2, y), line, font=F(13), fill=(120, 74, 22, 255), anchor="mm")
        y += 24
    return img


def render_numerology_name(number: int, romaji: str) -> Image.Image:
    return _render_medallion_card(
        "M05_numerology_name", number, "氏名数（ピタゴラス式）", [romaji.upper()])


def render_chaldean(number: int, romaji: str) -> Image.Image:
    return _render_medallion_card(
        "M07_chaldean", number, "カルデア数（楔形数字）", [romaji.upper()],
        digit="cuneiform", header_num=number)


def render_tantra(number: int) -> Image.Image:
    return _render_medallion_card(
        "M04_tantra", number, "タントラ数（1-11で一巡）", ["出生数ベース"],
        digit="devanagari", header_num=number)


def render_anka(number: int) -> Image.Image:
    planet = ANKA_PLANETS.get(number)
    foot = [f"支配惑星：{planet}"] if planet else ["支配惑星：（数値対応外）"]
    return _render_medallion_card("M04_anka", number, "アンカ数", foot,
                                  digit="devanagari", header_num=number, y0=62)


# ---------------------------------------------------------------- バッチ1: 六星占術
def render_rokusei(calc: dict) -> Image.Image:
    img = load_base("M10_rokusei")
    if img is None:
        img = Image.new("RGB", (W, H), (18, 24, 52))
    d = ImageDraw.Draw(img, "RGBA")
    silver = (214, 220, 236, 255)
    gold = (214, 180, 100, 255)
    shu = (214, 96, 76, 255)
    _header(d, "六星占術", "ROKUSEI", silver, gold)

    d.text((W / 2, 106), str(calc.get("type", "")), font=F(24), fill=gold, anchor="mm")
    d.text((W / 2, 130), f"運命数 {calc.get('unmei_number', '')}",
           font=F(11), fill=silver, anchor="mm")

    rows = [("年運", calc.get("cycle"), calc.get("is_daissakai")),
            ("月運", calc.get("month_cycle"), calc.get("month_is_daissakai")),
            ("日運", calc.get("day_cycle"), calc.get("day_is_daissakai"))]
    y = 176
    for label, cycle, dai in rows:
        d.rounded_rectangle([60, y - 20, 240, y + 20], 8,
                            fill=(214, 96, 76, 40) if dai else (255, 255, 255, 26),
                            outline=shu if dai else (214, 180, 100, 140), width=1)
        d.text((86, y), label, font=F(14), fill=silver, anchor="mm")
        d.text((150, y), str(cycle or "－"), font=F(18),
               fill=shu if dai else gold, anchor="mm")
        if dai:
            d.text((212, y), "大殺界", font=F(11), fill=shu, anchor="mm")
        y += 52
    d.line([60, 342, 240, 342], fill=gold, width=1)
    d.text((W / 2, 362), f"{calc.get('target_year', '')}年の年運",
           font=F(13), fill=silver, anchor="mm")
    return img


# ---------------------------------------------------------------- バッチ1: ウェトン
_DOW_COLS = ["日", "月", "火", "水", "木", "金", "土"]
_PASARAN_ROWS = ["Legi", "Pahing", "Pon", "Wage", "Kliwon"]
_PASARAN_KATA = {"Legi": "レギ", "Pahing": "パイン", "Pon": "ポン",
                 "Wage": "ワゲ", "Kliwon": "クリウォン"}


def render_weton(calc: dict) -> Image.Image:
    img = load_base("M14_weton")
    if img is None:
        img = Image.new("RGB", (W, H), (240, 226, 196))
    d = ImageDraw.Draw(img, "RGBA")
    ink = (72, 46, 22, 240)
    gold = (150, 104, 40, 255)
    hi = (166, 74, 32, 255)
    _header(d, "ウェトン", "WETON JAVANESE", ink, gold)

    gx0, gy0, gw, gh = 58, 78, 184, 200
    cw, chh = gw / 7, gh / 5
    d.rectangle([gx0, gy0, gx0 + gw, gy0 + gh], outline=ink, width=2)
    for i in range(1, 7):
        d.line([gx0 + i * cw, gy0, gx0 + i * cw, gy0 + gh], fill=ink, width=1)
    for i in range(1, 5):
        d.line([gx0, gy0 + i * chh, gx0 + gw, gy0 + i * chh], fill=ink, width=1)
    for c, dw in enumerate(_DOW_COLS):
        d.text((gx0 + (c + 0.5) * cw, gy0 - 10), dw, font=F(11), fill=ink, anchor="mm")
    day_col = _DOW_COLS.index(calc.get("day_ja", "月曜")[:1]) \
        if calc.get("day_ja", "")[:1] in _DOW_COLS else 0
    pas_row = _PASARAN_ROWS.index(calc["pasaran"]) if calc.get("pasaran") in _PASARAN_ROWS else 0
    for r, pas in enumerate(_PASARAN_ROWS):
        d.text((gx0 - 6, gy0 + (r + 0.5) * chh), _PASARAN_KATA[pas],
               font=F(9), fill=ink, anchor="rm")
        for c in range(7):
            if r == pas_row and c == day_col:
                d.rectangle([gx0 + c * cw + 2, gy0 + r * chh + 2,
                             gx0 + (c + 1) * cw - 2, gy0 + (r + 1) * chh - 2],
                            fill=(166, 74, 32, 60), outline=hi, width=2)
                d.ellipse([gx0 + (c + 0.5) * cw - 6, gy0 + (r + 0.5) * chh - 6,
                           gx0 + (c + 0.5) * cw + 6, gy0 + (r + 0.5) * chh + 6],
                          fill=hi)
    d.line([50, 316, 250, 316], fill=gold, width=1)
    d.text((W / 2, 338), calc.get("weton_name", ""), font=F(16), fill=hi, anchor="mm")
    d.text((W / 2, 362), f"（{calc.get('date', '')}）", font=F(11), fill=ink, anchor="mm")
    return img


# ---------------------------------------------------------------- バッチ1: プリンボン
def render_primbon(calc: dict) -> Image.Image:
    img = load_base("M13_primbon")
    if img is None:
        img = Image.new("RGB", (W, H), (20, 60, 56))
    d = ImageDraw.Draw(img, "RGBA")
    cream = (240, 236, 220, 255)
    gold = (214, 180, 100, 255)
    ink = (72, 46, 22, 255)          # ベース中央の淡色パネル用
    deep = (150, 104, 40, 255)
    _header(d, "プリンボン・ジャワ", "PRIMBON JAWA", cream, gold)

    def box(cx: float, cy: float, w: int, h: int, val, label: str, big: bool) -> None:
        d.rounded_rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], 10,
                            fill=(255, 252, 240, 170), outline=deep,
                            width=2 if big else 1)
        d.text((cx, cy - (6 if big else 3)), str(val),
               font=F(30 if big else 20), fill=deep, anchor="mm")
        d.text((cx, cy + h / 2 + 10), label, font=F(8), fill=ink, anchor="mm")

    dn = calc.get("day_neptu", 0)
    pn = calc.get("pasaran_neptu", 0)
    tot = calc.get("neptu_total", dn + pn)
    # 白地パネル（約 x45-255 / y120-370）内に収まるコンパクト配置（2026-09-26 是正）
    box(96, 168, 60, 60, dn, f"曜ネプトゥ（{calc.get('day_ja', '')}）", False)
    d.text((150, 168), "＋", font=F(20), fill=ink, anchor="mm")
    box(204, 168, 60, 60, pn,
        f"パサラン（{_PASARAN_KATA.get(calc.get('pasaran', ''), '')}）", False)
    d.text((W / 2, 222), "＝", font=F(20), fill=ink, anchor="mm")
    box(W / 2, 266, 84, 70, tot, "ネプトゥ合計", True)
    d.line([60, 320, 240, 320], fill=deep, width=1)
    d.text((W / 2, 338), calc.get("weton", ""), font=F(13), fill=deep, anchor="mm")
    d.text((W / 2, 358), f"（{calc.get('date', '')}）", font=F(10), fill=ink, anchor="mm")
    return img


# ---------------------------------------------------------------- 統合API
# ---------------------------------------------------------------- バッチ2: 共通
_B2_SILVER = (214, 220, 236, 255)
_B2_GOLD = (214, 180, 100, 255)
_B2_SHU = (214, 96, 76, 255)
_B2_WX = {"木": (126, 186, 122, 255), "火": (226, 116, 102, 255),
          "土": (206, 166, 96, 255), "金": (226, 226, 230, 255),
          "水": (116, 156, 216, 255)}


# ---------------------------------------------------------------- バッチ2: 四柱推命
def render_bazi(calc: dict) -> Image.Image:
    # 掛け軸4本の実測センター x=51/117/183/248（ベース画像から計測・2026-09-26）
    img = load_base("M17_bazi")
    if img is None:
        img = Image.new("RGB", (W, H), (30, 26, 22))
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([64, 8, 236, 58], 8, fill=(20, 16, 12, 175))
    _header(d, "四柱推命", "FOUR PILLARS", _B2_SILVER, _B2_GOLD)
    pillars = calc.get("pillars") or {}
    xs = {"year": 248, "month": 183, "day": 117, "hour": 51}
    labels = {"year": "年柱", "month": "月柱", "day": "日柱", "hour": "時柱"}
    det = (calc.get("detail") or {})
    for key, x in xs.items():
        gz = str(pillars.get(key, "  "))
        if key == "day":
            d.rounded_rectangle([x - 19, 60, x + 19, 250], 5,
                                fill=(214, 96, 76, 40), outline=_B2_SHU, width=2)
        d.text((x, 78), labels[key], font=F(9), fill=_B2_SILVER, anchor="mm")
        wx = _B2_WX.get((det.get(key) or {}).get("gan_wuxing", ""), _B2_GOLD)
        sh = (30, 24, 18, 200)
        d.text((x + 1, 123), gz[:1], font=F(26), fill=sh, anchor="mm")
        d.text((x, 122), gz[:1], font=F(26), fill=wx, anchor="mm")
        d.text((x + 1, 167), gz[1:2], font=F(26), fill=sh, anchor="mm")
        d.text((x, 166), gz[1:2], font=F(26), fill=_B2_SILVER, anchor="mm")
    dm = calc.get("day_master") or {}
    # 日主＋納音は掛け軸の下（y268〜）へ
    d.rounded_rectangle([36, 268, 264, 344], 8, fill=(20, 16, 12, 175))
    d.text((W / 2, 292), f"日主：{dm.get('gan', '')}（{dm.get('wuxing', '')}・{dm.get('yinyang', '')}）",
           font=F(16), fill=_B2_GOLD, anchor="mm")
    nayin = (det.get("day") or {}).get("nayin", "")
    if nayin:
        d.text((W / 2, 320), f"日柱納音：{nayin}", font=F(11), fill=_B2_SILVER, anchor="mm")
    return img


# ---------------------------------------------------------------- バッチ2: 算命学
_SMEI_POS = {"頭": (150, 96), "右肩": (112, 128), "左肩": (188, 128),
             "右手": (84, 178), "左手": (216, 178), "胸": (150, 152),
             "腹": (150, 196), "右足": (124, 246), "左足": (176, 246)}


def render_sanmei(calc: dict) -> Image.Image:
    img = load_base("M21_sanmei")
    if img is None:
        img = Image.new("RGB", (W, H), (16, 18, 40))
    d = ImageDraw.Draw(img, "RGBA")
    _header(d, "算命学", "SANMEIGAKU", _B2_SILVER, _B2_GOLD)
    for entry in (calc.get("十大主星") or []) + (calc.get("十二大従星") or []):
        pos = entry.get("position")
        xy = _SMEI_POS.get(pos)
        if not xy:
            continue
        star = str(entry.get("star", ""))
        d.ellipse([xy[0] - 21, xy[1] - 13, xy[0] + 21, xy[1] + 13],
                  fill=(255, 255, 255, 30), outline=(214, 180, 100, 190), width=1)
        d.text(xy, star, font=F(9), fill=_B2_SILVER, anchor="mm")
    d.rounded_rectangle([40, 288, 260, 368], 8, fill=(10, 12, 30, 165))
    d.text((W / 2, 308), f"中心星：{calc.get('中心星', '')}",
           font=F(17), fill=_B2_GOLD, anchor="mm")
    d.text((W / 2, 332), f"総エネルギー {calc.get('総エネルギー', '')}",
           font=F(12), fill=_B2_SILVER, anchor="mm")
    yp = (calc.get("陰占") or {}).get("日柱", "")
    if yp:
        d.text((W / 2, 354), f"日柱：{yp}", font=F(10), fill=_B2_SILVER, anchor="mm")
    return img


# ---------------------------------------------------------------- バッチ2: 姓名判断
def render_seimei(calc: dict) -> Image.Image:
    # 筆・硯を避けてタイトル・表とも下方へ（ユーザー指示 2026-09-26）
    img = load_base("M16_seimei")
    if img is None:
        img = Image.new("RGB", (W, H), (34, 30, 26))
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([60, 52, 240, 92], 8, fill=(250, 246, 238, 190))
    d.text((W / 2, 66), "姓名判断", font=F(17), fill=(72, 52, 34, 255), anchor="mm")
    d.text((W / 2, 84), "SEIMEI FIVE GRILLES", font=F(8),
           fill=(150, 60, 40, 255), anchor="mm")
    fg = calc.get("five_grilles") or {}
    sc = calc.get("san_sai") or {}
    d.rectangle([52, 100, 248, 318], fill=(255, 255, 255, 160),
                outline=(120, 90, 60, 200), width=1)
    y = 122
    for name in ["天格", "人格", "地格", "外格", "総格"]:
        d.text((86, y), name, font=F(13), fill=(60, 44, 30, 255), anchor="mm")
        d.text((150, y), str(fg.get(name, "")), font=F(19),
               fill=(150, 60, 40, 255), anchor="mm")
        _WX_D = {"木": (46, 124, 60, 255), "火": (196, 60, 48, 255),
                 "土": (150, 110, 40, 255), "金": (105, 105, 118, 255),
                 "水": (40, 90, 160, 255)}
        wxc = _WX_D.get(sc.get(name, ""), (60, 44, 30, 255))
        d.text((210, y), str(sc.get(name, "")), font=F(15), fill=wxc, anchor="mm")
        if y < 306:
            d.line([60, y + 21, 240, y + 21], fill=(120, 90, 60, 120), width=1)
        y += 43
    st = calc.get("strokes") or {}
    d.text((W / 2, 340), f"姓 {st.get('姓', '')}画／名 {st.get('名', '')}画",
           font=F(12), fill=(72, 52, 34, 255), anchor="mm")
    d.text((W / 2, 364), "三才：天・人・地の五行", font=F(9),
           fill=(110, 90, 70, 230), anchor="mm")
    return img


# ---------------------------------------------------------------- バッチ2: ヴェーダ
_VEDIC_SIGNS = ["白羊座", "金牛座", "双子座", "蟹座", "獅子座", "処女座",
                "天秤座", "天蝎座", "人馬座", "磨羯座", "水瓶座", "双魚座"]


def render_vedic(calc: dict) -> Image.Image:
    import math
    img = load_base("M19_vedic")
    if img is None:
        img = Image.new("RGB", (W, H), (40, 16, 20))
    d = ImageDraw.Draw(img, "RGBA")
    _header(d, "ヴェーダ占星術", "VEDIC JYOTISH", _B2_SILVER, _B2_GOLD)
    moon = (calc.get("planets") or {}).get("月") or {}
    sign = moon.get("sign", "")
    cx, cy, r = 150, 172, 82
    for i in range(12):
        a0 = math.radians(i * 30 - 90)
        a1 = math.radians((i + 1) * 30 - 90)
        if _VEDIC_SIGNS[i] == sign:
            d.pieslice([cx - r, cy - r, cx + r, cy + r], math.degrees(a0),
                       math.degrees(a1), fill=(214, 180, 100, 120))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=_B2_GOLD, width=2)
    d.ellipse([cx - r + 22, cy - r + 22, cx + r - 22, cy + r - 22],
              outline=(214, 180, 100, 150), width=1)
    d.ellipse([cx - 44, cy - 34, cx + 44, cy + 34], fill=(24, 10, 14, 190))
    d.text((cx, cy - 12), "月", font=F(11), fill=_B2_SILVER, anchor="mm")
    d.text((cx, cy + 10), str(sign), font=F(17), fill=_B2_GOLD, anchor="mm")
    d.rounded_rectangle([40, 278, 260, 360], 8, fill=(24, 10, 14, 175))
    d.text((W / 2, 296), str(moon.get("nakshatra", "")),
           font=F(14), fill=_B2_SILVER, anchor="mm")
    d.text((W / 2, 320), f"（パダ {moon.get('nakshatra_pada', '')}）",
           font=F(11), fill=_B2_GOLD, anchor="mm")
    d.text((W / 2, 346), f"アヤナームシャ：{calc.get('ayanamsa', '')}",
           font=F(9), fill=(214, 220, 236, 200), anchor="mm")
    return img


# ---------------------------------------------------------------- バッチ2: 奇門遁甲
_QM_ROWS = [["巽", "離", "坤"], ["震", "中", "兌"], ["艮", "坎", "乾"]]


def render_qimen(calc: dict) -> Image.Image:
    img = load_base("M24_qimen")
    if img is None:
        img = Image.new("RGB", (W, H), (24, 20, 16))
    d = ImageDraw.Draw(img, "RGBA")
    _header(d, "奇門遁甲", "QIMEN DUNJIA", _B2_SILVER, _B2_GOLD)
    tp, dp = calc.get("tianpan") or {}, calc.get("dipan") or {}
    men, xing, shen = (calc.get("men") or {}, calc.get("xing") or {},
                       calc.get("shen") or {})
    zf = calc.get("zhifu_zhishi") or {}
    zs_pal = (zf.get("值使門宮") or [None, None])[-1]
    zf_pal = (zf.get("值符星宮") or [None, None])[-1]
    x0, y0, cw, ch = 45, 74, 70, 66
    for ri, row in enumerate(_QM_ROWS):
        for ci, pal in enumerate(row):
            x, y = x0 + ci * cw, y0 + ri * ch
            if pal == "中":
                d.rectangle([x, y, x + cw, y + ch], fill=(24, 20, 14, 150),
                            outline=(214, 180, 100, 160), width=1)
                d.text((x + cw / 2, y + ch / 2 - 8), "中", font=F(11),
                       fill=_B2_SILVER, anchor="mm")
                d.text((x + cw / 2, y + ch / 2 + 10), str(dp.get("中", "")),
                       font=F(12), fill=_B2_GOLD, anchor="mm")
                continue
            d.rectangle([x, y, x + cw, y + ch], fill=(24, 20, 14, 150),
                        outline=(214, 180, 100, 160), width=1)
            if pal == zs_pal:
                d.rectangle([x + 1, y + 1, x + cw - 1, y + ch - 1],
                            outline=_B2_SHU, width=2)
            elif pal == zf_pal:
                d.rectangle([x + 1, y + 1, x + cw - 1, y + ch - 1],
                            outline=_B2_GOLD, width=2)
            d.text((x + 12, y + 11), f"{shen.get(pal, '')}{xing.get(pal, '')}",
                   font=F(8), fill=(214, 220, 236, 210), anchor="mm")
            d.text((x + cw / 2, y + 33), str(men.get(pal, "")),
                   font=F(16), fill=_B2_GOLD, anchor="mm")
            d.text((x + cw - 13, y + 54), str(tp.get(pal, "")),
                   font=F(11), fill=_B2_SILVER, anchor="mm")
    d.rounded_rectangle([40, 280, 260, 328], 8, fill=(24, 20, 14, 170))
    pj = str(calc.get("paiju", ""))
    d.text((W / 2, 294), pj, font=F(13), fill=_B2_GOLD, anchor="mm")
    d.text((W / 2, 316), f"値使：{str(men.get(zs_pal, ''))}門・{zs_pal}宮",
           font=F(11), fill=_B2_SILVER, anchor="mm")
    return img


# ---------------------------------------------------------------- B群: 西洋占星術系
import math as _math


def _astro_xy(cx, cy, r, lon):
    """黄経→画像座標（0°=左・反時計回り）"""
    a = _math.radians(180 - lon)
    return cx + r * _math.cos(a), cy - r * _math.sin(a)


def _draw_wheel(d, cx, cy, planets, r_planet, glyph_col, stagger=True):
    lons = sorted(((p["lon"], n) for n, p in planets.items()), reverse=True)
    placed = []
    for lon, name in lons:
        r = r_planet
        if stagger:
            for other_lon, _n, orr in placed:
                if abs(((lon - other_lon + 180) % 360) - 180) < 10 and orr == r_planet:
                    r = r_planet - 12
                    break
        x, y = _astro_xy(cx, cy, r, lon)
        placed.append((lon, name, r))
        d.text((x, y), PLANET_SYM.get(name, ""), font=F_SYM(11),
               fill=glyph_col, anchor="mm")


def render_western(calc: dict, title: str, sub: str) -> Image.Image:
    img = load_base("M18_western")
    if img is None:
        img = Image.new("RGB", (W, H), (12, 14, 34))
    d = ImageDraw.Draw(img, "RGBA")
    _header(d, title, sub, _B2_SILVER, _B2_GOLD)
    cx, cy, R = 150, 196, 108
    pl = calc.get("planets") or {}
    hs = calc.get("houses") or {}
    # 星座リング
    d.ellipse([cx - R, cy - R, cx + R, cy + R], outline=_B2_GOLD, width=2)
    d.ellipse([cx - R + 16, cy - R + 16, cx + R - 16, cy + R - 16],
              outline=(214, 180, 100, 150), width=1)
    for i in range(12):
        x0, y0 = _astro_xy(cx, cy, R, i * 30)
        x1, y1 = _astro_xy(cx, cy, R - 16, i * 30)
        d.line([x0, y0, x1, y1], fill=(214, 180, 100, 150), width=1)
        xs, ys = _astro_xy(cx, cy, R - 8, i * 30 + 15)
        d.text((xs, ys), SIGN_SYM[i], font=F_SYM(9), fill=_B2_SILVER, anchor="mm")
    # ハウス（カスプ目盛＋番号）
    cusps = hs.get("cusps") or []
    for i, c in enumerate(cusps[:12]):
        x0, y0 = _astro_xy(cx, cy, R - 16, c)
        x1, y1 = _astro_xy(cx, cy, R - 26, c)
        d.line([x0, y0, x1, y1], fill=(214, 220, 236, 160), width=1)
        xn, yn = _astro_xy(cx, cy, R - 32, c + 14)
        d.text((xn, yn), str(i + 1), font=F(7), fill=(214, 220, 236, 170), anchor="mm")
    # ASC/MC
    asc = hs.get("asc")
    if asc is not None:
        x0, y0 = _astro_xy(cx, cy, R + 6, asc)
        d.text((x0, y0), "ASC", font=F(7), fill=_B2_SHU, anchor="mm")
    mc = hs.get("mc")
    if mc is not None:
        x0, y0 = _astro_xy(cx, cy, R + 6, mc)
        d.text((x0, y0), "MC", font=F(7), fill=_B2_GOLD, anchor="mm")
    # アスペクト線
    for a in (calc.get("aspects") or []):
        p1, p2 = pl.get(a.get("p1")), pl.get(a.get("p2"))
        if not p1 or not p2:
            continue
        x1, y1 = _astro_xy(cx, cy, R - 42, p1["lon"])
        x2, y2 = _astro_xy(cx, cy, R - 42, p2["lon"])
        d.line([x1, y1, x2, y2], fill=ASPECT_COL.get(a["aspect"], _B2_SILVER), width=1)
    _draw_wheel(d, cx, cy, pl, R - 24, _B2_GOLD)
    d.rounded_rectangle([30, 322, 270, 378], 8, fill=(12, 14, 34, 185))
    d.text((W / 2, 338), f"太陽：{pl.get('太陽', {}).get('sign', '')}／月：{pl.get('月', {}).get('sign', '')}",
           font=F(12), fill=_B2_GOLD, anchor="mm")
    d.text((W / 2, 360), f"ASC：{hs.get('asc_sign', '')}／MC：{hs.get('mc_sign', '')}",
           font=F(11), fill=_B2_SILVER, anchor="mm")
    return img


def render_transit(calc: dict, natal: dict) -> Image.Image:
    img = load_base("M18_transit")
    if img is None:
        img = Image.new("RGB", (W, H), (12, 14, 34))
    d = ImageDraw.Draw(img, "RGBA")
    _header(d, "トランジット分析", "TRANSIT", _B2_SILVER, _B2_GOLD)
    cx, cy, R = 150, 196, 108
    tp = calc.get("transit_planets") or {}
    np_ = (natal or {}).get("planets") or {}
    d.ellipse([cx - R, cy - R, cx + R, cy + R], outline=_B2_GOLD, width=2)
    d.ellipse([cx - R + 14, cy - R + 14, cx + R - 14, cy + R - 14],
              outline=(214, 180, 100, 150), width=1)
    d.ellipse([cx - 58, cy - 58, cx + 58, cy + 58], outline=(214, 220, 236, 150), width=1)
    for i in range(12):
        x0, y0 = _astro_xy(cx, cy, R, i * 30)
        x1, y1 = _astro_xy(cx, cy, R - 14, i * 30)
        d.line([x0, y0, x1, y1], fill=(214, 180, 100, 150), width=1)
        xs, ys = _astro_xy(cx, cy, R - 7, i * 30 + 15)
        d.text((xs, ys), SIGN_SYM[i], font=F_SYM(8), fill=_B2_SILVER, anchor="mm")
    # 内外アスペクト（トランジット→ネイタル）
    for a in (calc.get("aspects_to_natal") or []):
        cur, nat = tp.get(a["planet"]), np_.get(a["planet"])
        if not cur:
            continue
        if nat is None:
            continue
        x1, y1 = _astro_xy(cx, cy, R - 22, cur["lon"])
        x2, y2 = _astro_xy(cx, cy, 50, nat["lon"])
        d.line([x1, y1, x2, y2], fill=ASPECT_COL.get(a["aspect"], _B2_SILVER), width=1)
    _draw_wheel(d, cx, cy, tp, R - 22, _B2_GOLD)
    _draw_wheel(d, cx, cy, np_, 46, _B2_SILVER)
    n_asp = len(calc.get("aspects_to_natal") or [])
    d.rounded_rectangle([30, 322, 270, 378], 8, fill=(12, 14, 34, 185))
    d.text((W / 2, 338), f"トランジット 太陽：{tp.get('太陽', {}).get('sign', '')}／月：{tp.get('月', {}).get('sign', '')}",
           font=F(11), fill=_B2_GOLD, anchor="mm")
    d.text((W / 2, 360), f"出生図へのアスペクト {n_asp}件（外環=現在・内環=出生）",
           font=F(10), fill=_B2_SILVER, anchor="mm")
    return img


def render_synastry(calc: dict) -> Image.Image:
    img = load_base("M18_synastry")
    if img is None:
        img = Image.new("RGB", (W, H), (20, 12, 26))
    d = ImageDraw.Draw(img, "RGBA")
    _header(d, "シナストリー", "SYNASTRY", _B2_SILVER, _B2_GOLD)
    mine, theirs = calc.get("mine") or {}, calc.get("theirs") or {}
    for cx, chart, label in ((82, mine, "自分"), (218, theirs, "相手")):
        d.ellipse([cx - 52, 148 - 52, cx + 52, 148 + 52], outline=_B2_GOLD, width=1)
        d.ellipse([cx - 40, 148 - 40, cx + 40, 148 + 40],
                  outline=(214, 180, 100, 130), width=1)
        _draw_wheel(d, cx, 148, chart.get("planets") or {}, 34, _B2_SILVER, stagger=False)
        d.text((cx, 212), label, font=F(10), fill=_B2_GOLD, anchor="mm")
    aspects = calc.get("aspects") or []
    d.rounded_rectangle([24, 228, 276, 378], 8, fill=(20, 12, 26, 200))
    if not aspects:
        d.text((W / 2, 300), "主要アスペクトはオーブ外", font=F(12),
               fill=_B2_SILVER, anchor="mm")
    for i, a in enumerate(aspects[:5]):
        y = 246 + i * 26
        d.text((40, y), PLANET_SYM.get(a["p1"], ""), font=F_SYM(11),
               fill=_B2_GOLD, anchor="mm")
        d.text((56, y), f"自・{a['p1']}", font=F(10), fill=_B2_SILVER, anchor="lm")
        d.text((150, y), a["aspect"], font=F(10), fill=ASPECT_COL.get(a["aspect"], _B2_SILVER),
               anchor="mm")
        d.text((244, y), PLANET_SYM.get(a["p2"], ""), font=F_SYM(11),
               fill=_B2_GOLD, anchor="mm")
        d.text((258, y), f"相・{a['p2']}", font=F(10), fill=_B2_SILVER, anchor="lm")
    return img


# ---------------------------------------------------------------- B群残: 紫微斗数
_ZW_BRANCH = {"yin": "寅", "mao": "卯", "chen": "辰", "si": "巳", "wu": "午",
              "wei": "未", "shen": "申", "you": "酉", "xu": "戌", "hai": "亥",
              "zi": "子", "chou": "丑"}
_ZW_POS = {"yin": (0, 3), "mao": (0, 2), "chen": (0, 1), "si": (0, 0),
           "wu": (1, 0), "wei": (2, 0), "shen": (3, 0), "you": (3, 1),
           "xu": (3, 2), "hai": (3, 3), "zi": (2, 3), "chou": (1, 3)}


def render_ziwei(calc: dict) -> Image.Image:
    img = load_base("M20_ziwei")
    if img is None:
        img = Image.new("RGB", (W, H), (26, 18, 34))
    d = ImageDraw.Draw(img, "RGBA")
    _header(d, "紫微斗数", "ZIWEI DOUSHU", _B2_SILVER, _B2_GOLD)
    soul, body = calc.get("soul_palace"), calc.get("body_palace")
    x0, y0, cw, ch = 0, 62, 75, 75
    for pal in (calc.get("palaces") or []):
        pos = _ZW_POS.get(pal.get("earthly_branch", ""))
        if not pos:
            continue
        cx, cy = x0 + pos[0] * cw, y0 + pos[1] * ch
        d.rectangle([cx + 1, cy + 1, cx + cw - 1, cy + ch - 1],
                    fill=(255, 255, 255, 22), outline=(214, 180, 100, 130), width=1)
        if pal.get("name") == soul:
            d.rectangle([cx + 2, cy + 2, cx + cw - 2, cy + ch - 2],
                        outline=_B2_SHU, width=2)
        elif pal.get("name") == body:
            d.rectangle([cx + 2, cy + 2, cx + cw - 2, cy + ch - 2],
                        outline=_B2_GOLD, width=2)
        d.text((cx + 6, cy + 9), str(pal.get("name", "")), font=F(8),
               fill=_B2_GOLD, anchor="lm")
        d.text((cx + cw - 7, cy + 9), _ZW_BRANCH.get(pal.get("earthly_branch", ""), ""),
               font=F(8), fill=_B2_SILVER, anchor="rm")
        for i, st in enumerate((pal.get("major_stars") or [])[:2]):
            d.text((cx + 8, cy + 26 + i * 14), st, font=F(9),
                   fill=_B2_SILVER, anchor="lm")
        for i, st in enumerate((pal.get("minor_stars") or [])[:2]):
            d.text((cx + cw - 8, cy + 62 - i * 12), st, font=F(7),
                   fill=(214, 220, 236, 170), anchor="rm")
    # 中央パネルも盤面セルと同じ透過度（背景の北天星図が見える・ユーザー指示 2026-09-26）
    d.rectangle([76, 138, 224, 286], fill=(255, 255, 255, 22),
                outline=(214, 180, 100, 130), width=1)
    sh = (30, 24, 18, 210)
    d.text((W / 2 + 1, 177), str(calc.get("five_elements_class", "")),
           font=F(15), fill=sh, anchor="mm")
    d.text((W / 2, 176), str(calc.get("five_elements_class", "")),
           font=F(15), fill=_B2_GOLD, anchor="mm")
    d.text((W / 2 + 1, 205), f"命宮：{soul or ''}", font=F(11), fill=sh, anchor="mm")
    d.text((W / 2, 204), f"命宮：{soul or ''}", font=F(11), fill=_B2_SILVER, anchor="mm")
    d.text((W / 2 + 1, 227), f"身宮：{body or ''}", font=F(11), fill=sh, anchor="mm")
    d.text((W / 2, 226), f"身宮：{body or ''}", font=F(11), fill=_B2_SILVER, anchor="mm")
    d.text((W / 2 + 1, 253), str(calc.get("lunar_date", "")), font=F(9),
           fill=sh, anchor="mm")
    d.text((W / 2, 252), str(calc.get("lunar_date", "")), font=F(9),
           fill=(214, 220, 236, 200), anchor="mm")
    return img


# ---------------------------------------------------------------- B群残: ヒューマンデザイン
_HD_TYPE_JA = {"Generator": "ジェネレーター", "Manifestor": "マニフェスター",
               "Projector": "プロジェクター", "Reflector": "リフレクター",
               "Manifesting Generator": "マニフェスティング・ジェネレーター"}
_HD_AUTH_JA = {"Sacral": "仙骨", "Emotional / Solar Plexus": "感情",
               "Splenic": "脾", "Ego": "自己", "Self-Projected": "自己",
               "Throat": "喉", "Mental": "頭"}
_HD_CENTERS = [
    ("Head", (150, 84), "tri"), ("Ajna", (150, 116), "trid"),
    ("Throat", (150, 150), "sq"), ("Self", (150, 186), "dia"),
    ("Heart", (172, 210), "tri"), ("Spleen", (106, 232), "tri"),
    ("Solar Plexus", (194, 232), "trid"), ("Sacral", (150, 236), "sq"),
    ("Root", (150, 276), "sq")]


def _hd_shape(d, name, xy, kind, defined):
    x, y = xy
    fill = (214, 140, 80, 220) if defined else (255, 255, 255, 40)
    line = _B2_GOLD if defined else (214, 220, 236, 160)
    if kind == "sq":
        d.rectangle([x - 15, y - 12, x + 15, y + 12], fill=fill, outline=line, width=1)
    elif kind == "dia":
        d.polygon([(x, y - 15), (x + 15, y), (x, y + 15), (x - 15, y)],
                  fill=fill, outline=line)
    elif kind == "tri":
        d.polygon([(x, y - 13), (x + 14, y + 10), (x - 14, y + 10)],
                  fill=fill, outline=line)
    else:
        d.polygon([(x - 14, y - 10), (x + 14, y - 10), (x, y + 13)],
                  fill=fill, outline=line)


def render_hd(calc: dict) -> Image.Image:
    img = load_base("M25_hd")
    if img is None:
        img = Image.new("RGB", (W, H), (16, 20, 26))
    d = ImageDraw.Draw(img, "RGBA")
    _header(d, "ヒューマンデザイン", "HUMAN DESIGN", _B2_SILVER, _B2_GOLD)
    defined = set(calc.get("defined_centers") or [])
    links = [("Head", "Ajna"), ("Ajna", "Throat"), ("Throat", "Self"),
             ("Self", "Sacral"), ("Sacral", "Root"), ("Spleen", "Root"),
             ("Solar Plexus", "Root"), ("Throat", "Heart"), ("Spleen", "Throat"),
             ("Solar Plexus", "Throat")]
    pos = {n: xy for n, xy, _k in _HD_CENTERS}
    for a, b in links:
        d.line([pos[a], pos[b]], fill=(214, 220, 236, 110), width=1)
    for name, xy, kind in _HD_CENTERS:
        _hd_shape(d, name, xy, kind, name in defined)
    d.text((40, 232), "脾", font=F(8), fill=_B2_SILVER, anchor="rm")
    d.text((260, 232), "感情", font=F(8), fill=_B2_SILVER, anchor="lm")
    d.rounded_rectangle([30, 306, 270, 378], 8, fill=(16, 20, 26, 200))
    d.text((W / 2, 324), _HD_TYPE_JA.get(calc.get("type", ""), str(calc.get("type", ""))),
           font=F(15), fill=_B2_GOLD, anchor="mm")
    d.text((W / 2, 348), f"権威：{_HD_AUTH_JA.get(calc.get('authority', ''), str(calc.get('authority', '')))}",
           font=F(11), fill=_B2_SILVER, anchor="mm")
    d.text((W / 2, 368), f"プロフィール：{calc.get('profile', '')}",
           font=F(10), fill=_B2_SILVER, anchor="mm")
    return img


# ---------------------------------------------------------------- B群残: パリミチャム
def render_parimicham(calc: dict) -> Image.Image:
    # 上下のコラム文様帯（〜y55 / y345〜）を避け、字入れは y60-342 に収める
    # （ユーザー指示 2026-09-26）
    img = load_base("M15_parimicham")
    if img is None:
        img = Image.new("RGB", (W, H), (30, 22, 16))
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([46, 60, 254, 92], 8, fill=(30, 22, 16, 210))
    d.text((W / 2, 72), "パリミチャム", font=F(15), fill=_B2_SILVER, anchor="mm")
    d.text((W / 2, 86), "PORUTHAM", font=F(8), fill=_B2_GOLD, anchor="mm")
    me, op = calc.get("本人") or {}, calc.get("相手") or {}
    d.rounded_rectangle([24, 98, 276, 128], 8, fill=(30, 22, 16, 190))
    d.text((W / 2, 113), f"本人：{me.get('nakshatra', '')}／相手：{op.get('nakshatra', '')}",
           font=F(11), fill=_B2_SILVER, anchor="mm")
    d.rounded_rectangle([24, 134, 276, 254], 8, fill=(255, 250, 240, 170))
    y = 150
    for name, result, ok in (calc.get("checks") or [])[:4]:
        d.text((34, y), str(name), font=F(9), fill=(60, 44, 30, 255), anchor="lm")
        d.text((168, y), str(result), font=F(8), fill=(90, 70, 50, 255), anchor="lm")
        mark = "✓" if ok else "✗"
        col = (46, 124, 60, 255) if ok else (196, 60, 48, 255)
        d.text((262, y), mark, font=F_SYM(12), fill=col, anchor="mm")
        if y < 240:
            d.line([32, y + 15, 268, y + 15], fill=(120, 90, 60, 120), width=1)
        y += 30
    d.rounded_rectangle([24, 260, 276, 342], 8, fill=(30, 22, 16, 210))
    d.text((W / 2, 286), f"{calc.get('score', '')} / {calc.get('score_max', '')}",
           font=F(22), fill=_B2_GOLD, anchor="mm")
    d.text((W / 2, 308), "得点", font=F(9), fill=_B2_SILVER, anchor="mm")
    vd = str(calc.get("verdict", ""))
    vd = vd[: vd.index("（")] .upper() + vd[vd.index("（"):] if "（" in vd else vd.upper()
    d.text((W / 2, 328), vd, font=F(13), fill=_B2_GOLD, anchor="mm")
    return img


def _render_for_slug_impl(slug: str, calc: dict, extra: dict | None = None):
    """内部実装。CJK fallback は公開関数 render_for_slug でスコープ適用する。"""
    calc = calc or {}
    extra = extra or {}
    if slug == "M03_kyusei":
        try:
            year = int(calc.get("year"))
            no = int(calc.get("honmei_no"))
        except (TypeError, ValueError):
            return None, ""
        if not 1 <= no <= 9:
            return None, ""
        return render_kyusei(year, no), f"【九星気学】{year}年生・本命星：{calc.get('honmei', '')}"
    if slug == "M04_numerology_birth":
        try:
            lp = int(calc.get("life_path"))
            birth = dt.date.fromisoformat(str(calc.get("date")))
        except (TypeError, ValueError):
            return None, ""
        nn = extra.get("number")
        romaji = extra.get("romaji")
        return (render_numerology(lp, birth, nn, romaji),
                f"【数秘術】運命数{lp}（{birth.isoformat()}生）")
    if slug == "M06_kabbalah":
        try:
            val = int(calc.get("number"))
        except (TypeError, ValueError):
            return None, ""
        romaji = str(calc.get("romaji") or "")
        if not romaji:
            return None, ""
        return render_kabbalah(val, romaji), f"【カバラ数秘術】{romaji.upper()} → {val}"
    # ---- バッチ1 ----
    if slug == "M05_numerology_name":
        try:
            n = int(calc.get("number"))
        except (TypeError, ValueError):
            return None, ""
        romaji = str(calc.get("romaji") or "")
        if not romaji:
            return None, ""
        return (render_numerology_name(n, romaji),
                f"【数秘術（氏名）】氏名数{n}（{romaji.upper()}）")
    if slug == "M07_chaldean":
        try:
            n = int(calc.get("number"))
        except (TypeError, ValueError):
            return None, ""
        romaji = str(calc.get("romaji") or "")
        if not romaji:
            return None, ""
        return (render_chaldean(n, romaji),
                f"【カルデア数秘術】カルデア数{n}（{romaji.upper()}）")
    if slug == "M04_tantra":
        try:
            n = int(calc.get("number"))
        except (TypeError, ValueError):
            return None, ""
        return render_tantra(n), f"【タントラ数秘術】タントラ数{n}"
    if slug == "M04_anka":
        try:
            n = int(calc.get("number"))
        except (TypeError, ValueError):
            return None, ""
        planet = ANKA_PLANETS.get(n, "")
        return render_anka(n), f"【アンカ・シャーストラ】アンカ数{n}" + (
            f"・支配星：{planet}" if planet else "")
    if slug == "M10_rokusei":
        if not calc.get("type") or not calc.get("cycle"):
            return None, ""
        return (render_rokusei(calc),
                f"【六星占術】{calc['type']}／年運：{calc['cycle']}"
                f"（{calc.get('target_year', '')}）")
    if slug == "M14_weton":
        if not calc.get("weton_name") or not calc.get("pasaran"):
            return None, ""
        return render_weton(calc), f"【ウェトン】{calc['weton_name']}"
    if slug == "M13_primbon":
        if not calc.get("weton") or calc.get("neptu_total") is None:
            return None, ""
        return (render_primbon(calc),
                f"【プリンボン・ジャワ】{calc['weton']}／ネプトゥ{calc['neptu_total']}")
    # ---- バッチ2 ----
    if slug == "M16_seimei":
        fg = calc.get("five_grilles") or {}
        if not fg:
            return None, ""
        return (render_seimei(calc),
                f"【姓名判断】五格 天{fg.get('天格', '')}・人{fg.get('人格', '')}"
                f"・地{fg.get('地格', '')}・外{fg.get('外格', '')}・総{fg.get('総格', '')}")
    if slug == "M17_bazi":
        p4 = calc.get("pillars") or {}
        if not p4.get("year"):
            return None, ""
        dm = calc.get("day_master") or {}
        return (render_bazi(calc),
                f"【四柱推命】年柱{p4.get('year', '')}／月柱{p4.get('month', '')}"
                f"／日柱{p4.get('day', '')}／時柱{p4.get('hour', '')}"
                f"・日主：{dm.get('gan', '')}（{dm.get('wuxing', '')}・{dm.get('yinyang', '')}）")
    if slug == "M19_vedic":
        moon = (calc.get("planets") or {}).get("月") or {}
        if not moon.get("sign"):
            return None, ""
        return (render_vedic(calc),
                f"【ヴェーダ占星術】月：{moon.get('sign', '')}・{moon.get('nakshatra', '')}"
                f"（パダ{moon.get('nakshatra_pada', '')}）")
    if slug == "M21_sanmei":
        if not calc.get("中心星"):
            return None, ""
        return (render_sanmei(calc),
                f"【算命学】中心星：{calc['中心星']}／総エネルギー{calc.get('総エネルギー', '')}")
    # ---- B群残: 紫微斗数/HD/パリミチャム ----
    if slug == "M20_ziwei":
        if not calc.get("palaces"):
            return None, ""
        return (render_ziwei(calc),
                f"【紫微斗数】{calc.get('five_elements_class', '')}・命宮：{calc.get('soul_palace', '')}"
                f"／身宮：{calc.get('body_palace', '')}")
    if slug == "M25_hd":
        if not calc.get("type"):
            return None, ""
        return (render_hd(calc),
                f"【ヒューマンデザイン】{_HD_TYPE_JA.get(calc.get('type', ''), calc.get('type', ''))}"
                f"・権威：{_HD_AUTH_JA.get(calc.get('authority', ''), calc.get('authority', ''))}"
                f"・{calc.get('profile', '')}")
    if slug == "M15_parimicham":
        if calc.get("status") != "ok" or "error" in calc:
            return None, ""
        return (render_parimicham(calc),
                f"【パリミチャム】{calc.get('score', '')}/{calc.get('score_max', '')}"
                f"・{calc.get('verdict', '')}")
    # ---- B群: 西洋占星術系 ----
    if slug == "M18_western":
        if not (calc.get("planets") or {}).get("太陽"):
            return None, ""
        return (render_western(calc, "西洋占星術", "WESTERN HOROSCOPE"),
                f"【西洋占星術】太陽：{calc['planets']['太陽'].get('sign', '')}／"
                f"月：{calc['planets']['月'].get('sign', '')}／"
                f"ASC：{(calc.get('houses') or {}).get('asc_sign', '')}")
    if slug == "M18_natal":
        if not (calc.get("planets") or {}).get("太陽"):
            return None, ""
        return (render_western(calc, "ネイタル占星術", "NATAL CHART"),
                f"【ネイタル占星術】太陽：{calc['planets']['太陽'].get('sign', '')}／"
                f"月：{calc['planets']['月'].get('sign', '')}／"
                f"ASC：{(calc.get('houses') or {}).get('asc_sign', '')}")
    if slug == "M18_transit":
        if not (calc.get("transit_planets") or {}).get("太陽"):
            return None, ""
        return (render_transit(calc, extra or {}),
                f"【トランジット】太陽：{calc['transit_planets']['太陽'].get('sign', '')}／"
                f"月：{calc['transit_planets']['月'].get('sign', '')}／"
                f"アスペクト{len(calc.get('aspects_to_natal') or [])}件")
    if slug == "M18_synastry":
        if not calc.get("mine") or "error" in calc:
            return None, ""
        asp = calc.get("aspects") or []
        top = f"・{asp[0]['p1']}×{asp[0]['p2']} {asp[0]['aspect']}" if asp else ""
        return (render_synastry(calc), f"【シナストリー】アスペクト{len(asp)}件{top}")
    if slug == "M24_qimen":
        if not calc.get("paiju") or not calc.get("men"):
            return None, ""
        zf = calc.get("zhifu_zhishi") or {}
        zs_pal = (zf.get("值使門宮") or [None, None])[-1]
        men = calc.get("men") or {}
        return (render_qimen(calc),
                f"【奇門遁甲】{calc['paiju']}／値使：{men.get(zs_pal, '')}門・{zs_pal}宮")
    return None, ""


def render_for_slug(slug: str, calc: dict, extra: dict | None = None):
    """calc から (Image, caption) を返す。不足するCJK文字列は同梱fallbackで描く。"""
    with _cjk_fallback_scope():
        return _render_for_slug_impl(slug, calc, extra)


def _read_calc(person_dir: Path, slug: str) -> dict | None:
    raw = person_dir / "results" / f"{slug}_raw.json"
    if not raw.is_file():
        return None
    try:
        data = json.loads(raw.read_text(encoding="utf-8"))
        return (data.get("result") or {}).get("calc") or None
    except Exception:
        return None


def typec_tag(slug: str, person_dir: Path, assets_root: Path | None) -> str:
    """html_report 用: calc から描画し1枚大表示のタグを返す（不可なら ""）。"""
    if slug not in TYPEC_DECKS:
        return ""
    if load_base(slug, assets_root) is None:
        return ""
    calc = _read_calc(person_dir, slug)
    if calc is None:
        return ""
    extra = None
    if slug == "M04_numerology_birth":
        extra = _read_calc(person_dir, "M04_numerology_name") or None
    if slug == "M18_transit":
        extra = _read_calc(person_dir, "M18_western") or None
    img, cap = render_for_slug(slug, calc, extra)
    if img is None:
        return ""
    import base64
    import io
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=WEBP_Q)
    b64 = "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    return (f'<div class="fortune-image-container"><img src="{b64}" '
            f'alt="{_html.escape(cap)}" class="fortune-visual" loading="lazy" />'
            f'<div class="fortune-image-caption">{_html.escape(cap)}</div></div>')
