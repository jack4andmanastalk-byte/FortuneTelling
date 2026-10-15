# -*- coding: utf-8 -*-
"""
M20 紫微斗数 — iztro-py 委譲アダプタ
仕様：計算ロジック仕様書 §4.15
- ライブラリ: iztro-py 0.5.0（MIT・純Python・日本語対応）
- 出力: 十二宮・主星・輔星・四化（mutagen）・大限・五行局・旧暦・星座
- 注記: 大限の順逆は iztro 仕様（solar年の年支 × 性別で決定）
"""
from __future__ import annotations

from datetime import date

try:
    from iztro_py import astro as _astro
    _HAVE_IZTRO = True
except ImportError:
    _astro = None
    _HAVE_IZTRO = False

LANG = "ja-JP"
GENDER_MAP = {"M": "男", "F": "女", "other": "男", "unknown": "男"}


def _ziwei_virtual_age(birth: date, as_of: date) -> int:
    """紫微斗数の虚歳（出生時と基準日の旧暦年差＋1）を返す。"""
    try:
        from lunar_python import Solar
        birth_lunar_year = Solar.fromYmd(birth.year, birth.month, birth.day).getLunar().getYear()
        current_lunar_year = Solar.fromYmd(as_of.year, as_of.month, as_of.day).getLunar().getYear()
        return int(current_lunar_year) - int(birth_lunar_year) + 1
    except Exception as e:
        raise RuntimeError(f"紫微斗数の虚歳算出に失敗しました: {e}") from e

# ---------------------------------------------------------------- #
# mts5.63: 旧暦の文字を**日本語の漢字**へ直す。
#
# iztro-py の `lunar_date` は簡体字（中国語）で返るため、**閏月**や**臘月**に
# 生まれた人の鑑定だけ、同梱フォントに無い字（闰 U+95F0・腊 U+81D5）が混ざり、
# **型Cチャート（M20_ziwei）の日付が欠けて描画**されていました
# （2026-09-30 の mts5.62 実機＝1993-05-17 の人物が旧暦「一九九三年闰三月廿六」。
#   検証器はこれを「同梱フォントに無い文字」＋「納品画像と一致しない」の2件として
#   検出し、デッキ数も 48→47 に減りました。**豆腐（文字欠け）は成果物の欠陥**）。
#
# 対処は**データの正規化**（フォントを増やすのではなく、日本語として正しい字に直す）:
#   闰 → 閏 / 腊 → 臘。どちらも同梱の日本語フォントに収録があります。
# ---------------------------------------------------------------- #
_JA_KANJI_FIX = {
    "闰": "閏",     # 閏月（うるうづき）
    "腊": "臘",     # 臘月（ろうげつ＝旧暦12月）
}


def _ja_kanji(text) -> str:
    """旧暦などの簡体字を日本語の漢字へ直す（未知の字はそのまま）。"""
    s = "" if text is None else str(text)
    for zh, ja in _JA_KANJI_FIX.items():
        if zh in s:
            s = s.replace(zh, ja)
    return s

_JA_NAMES = None


def _ja_name_table():
    """iztro_ja_names.json（別AI実装・正確な日本語表示名）をロード"""
    global _JA_NAMES
    if _JA_NAMES is None:
        try:
            from ..data import load_json
            _JA_NAMES = load_json("iztro_ja_names.json")
        except Exception:
            _JA_NAMES = {}
    return _JA_NAMES


# iztro の四化（mutagen）は中国語（簡体字）で返る。日本語表示名テーブル
# （iztro_ja_names.json の "mutagen"）が用意されているので、こちらを適用する（mts5.31）
_MUTAGEN_ZH_TO_KEY = {
    "禄": "lu", "祿": "lu", "权": "quan", "權": "quan", "科": "ke", "忌": "ji",
}
_MUTAGEN_FALLBACK_JA = {"lu": "禄", "quan": "権", "ke": "科", "ji": "忌"}


def _ja_mutagen(zh: str) -> str:
    """四化（禄・権・科・忌）を日本語表記にする（未知の値はそのまま返す）"""
    key = _MUTAGEN_ZH_TO_KEY.get((zh or "").strip())
    tbl = (_ja_name_table().get("mutagen") or {})
    if key and key in tbl:
        return tbl[key]
    return _MUTAGEN_FALLBACK_JA.get(key, zh)


def _ja_name(english_key: str, fallback: str) -> str:
    """iztro の英語キー → 日本語名（テーブル優先・無ければ fallback）"""
    tbl = _ja_name_table()
    # 直接キー（soulPalace 等）
    if english_key in tbl:
        return tbl[english_key]
    # star 名（ziweiMaj 等）は「stars」セクション
    if "stars" in tbl and english_key in tbl["stars"]:
        return tbl["stars"][english_key]
    if "major" in tbl and english_key in tbl["major"]:
        return tbl["major"][english_key]
    if "minor" in tbl and english_key in tbl["minor"]:
        return tbl["minor"][english_key]
    return fallback


def _require():
    if not _HAVE_IZTRO:
        raise RuntimeError("iztro-py が必要です（pip install iztro-py）")


def _time_index(hour: int) -> int:
    """時（0-23）→ iztro の time_index（0=子, 1=丑, ..., 11=亥, 12=晚子）"""
    # 0-1時=子(0), 2-3=丑(1), ..., 22-23=亥(11), 23時=晚子(12)
    if hour == 23:
        return 12  # 晚子
    return hour // 2


def ziwei_chart(y: int, m: int, d: int, hour: int = 12, gender: str = "M",
                as_of: date | None = None) -> dict:
    """
    紫微斗数排盤。

    Args:
        y, m, d: 生年月日（グレゴリオ暦）
        hour: 出生時刻（時のみ。分は近似）
        gender: M / F / other

    Returns:
        dict: 十二宮・主星・四化・大限・五行局など（日本語ラベル）
    """
    _require()
    gender_ja = GENDER_MAP.get(gender, "男")
    chart = _astro.by_solar(f"{y}-{m}-{d}", _time_index(hour), gender_ja, language=LANG)
    # iztro の大限レンジは旧暦年基準の虚歳。本文で次周期を「現在」と誤認しないよう
    # 基準日と、虚歳に該当するレンジをJSONへ明示する。
    as_of = as_of or date.today()
    age_nominal = _ziwei_virtual_age(date(y, m, d), as_of)

    palaces = []
    for p in chart.palaces:
        # 日本語名は iztro_ja_names.json（別AI実装・正確なテーブル）を優先
        major = [_ja_name(s.name, s.translate_name(LANG)) for s in p.major_stars]
        minor = [_ja_name(s.name, s.translate_name(LANG)) for s in p.minor_stars]
        p_name = _ja_name(p.name, p.translate_name(LANG))
        decadal = None
        if p.decadal:
            decadal = {
                "range": [p.decadal.range[0], p.decadal.range[1]],
                "heavenly_stem": p.decadal.heavenly_stem.replace("Heavenly", ""),
                "earthly_branch": p.decadal.earthly_branch.replace("Earthly", ""),
            }
        palaces.append({
            "name": p_name,
            "heavenly_stem": p.heavenly_stem.replace("Heavenly", ""),
            "earthly_branch": p.earthly_branch.replace("Earthly", ""),
            "major_stars": major,
            "minor_stars": minor,
            "decadal": decadal,
        })

    # 四化（生年四化: mutagen ありの主星）
    transformations = []
    for p in chart.palaces:
        for s in p.major_stars:
            if s.has_mutagen():
                transformations.append({
                    "star": _ja_name(s.name, s.translate_name(LANG)),
                    "mutagen": _ja_mutagen(s.mutagen),
                    "palace": _ja_name(p.name, p.translate_name(LANG)),
                })

    current_decadal = next((p["decadal"]["range"] for p in palaces
                             if p.get("decadal")
                             and p["decadal"]["range"][0] <= age_nominal
                             <= p["decadal"]["range"][1]), None)

    return {
        "five_elements_class": chart.five_elements_class,
        "as_of_date": as_of.isoformat(),
        "nominal_age": age_nominal,
        "age_basis": "紫微斗数の虚歳（旧暦年−出生旧暦年＋1）",
        "current_decadal_range": current_decadal,
        "lunar_date": _ja_kanji(chart.lunar_date),   # mts5.63: 閏・臘を日本語の字へ
        "sign": chart.sign,
        "palaces": palaces,
        "transformations": transformations,
        "soul_palace": _ja_name(chart.get_soul_palace().name,
                                chart.get_soul_palace().translate_name(LANG)),
        "body_palace": _ja_name(chart.get_body_palace().name,
                                chart.get_body_palace().translate_name(LANG)),
        "references": ["iztro-py 0.5.0 (MIT)", "data/iztro_ja_names.json"],
        "notes": ["大限の順逆は iztro 仕様（solar年の年支×性別）。流派により異なる場合があります",
                  "日本語名は iztro_ja_names.json（別AI実装・検証済みテーブル）を適用"],
    }
