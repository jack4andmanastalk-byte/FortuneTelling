# -*- coding: utf-8 -*-
"""
入力の正規化・近似モード適用（仕様設計メモ §2.1, §3.1 の実装）
- 時刻不明 → 正午（12:00）扱い
- 出生地不明 → 東京扱い
- 氏名（かな）→ ヘボン式ローマ字自動変換（hepburn.kana_to_hepburn）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from .hepburn import kana_to_hepburn

PLACE_DEFAULT = {
    "name": "東京",
    "lat": 35.6895,
    "lon": 139.6917,
    "tz": "Asia/Tokyo",
}

TIME_DEFAULT = "12:00"  # 時刻不明時の近似（正午扱い）


@dataclass
class BirthInfo:
    """出生情報（正規化後）"""
    date: date
    time: str = TIME_DEFAULT
    time_unknown: bool = False
    place_name: str = PLACE_DEFAULT["name"]
    place_lat: float = PLACE_DEFAULT["lat"]
    place_lon: float = PLACE_DEFAULT["lon"]
    place_tz: str = PLACE_DEFAULT["tz"]
    place_unknown: bool = False
    gender: str = "unknown"  # M / F / other / unknown


@dataclass
class NormalizedInput:
    """正規化済み入力（標準プロファイル）"""
    birth: BirthInfo
    partner: Optional[BirthInfo] = None
    name_kanji: str = ""
    name_kana: str = ""
    name_romaji: str = ""       # ヘボン式変換結果
    blood_type: str = "unknown"  # A / B / O / AB / unknown
    consultation: str = ""
    target_date: Optional[date] = None  # 対象日（今日の運勢モード用・任意）
    approx_flags: list = field(default_factory=list)


_PREF_CACHE = None


def _prefectures() -> list:
    """都道府県の座標辞書（47件）を読み込む"""
    global _PREF_CACHE
    if _PREF_CACHE is None:
        try:
            from .data import load_json
            _PREF_CACHE = load_json("japan_prefectures.json")
        except Exception:
            _PREF_CACHE = []
    return _PREF_CACHE


def resolve_place(place: str) -> tuple:
    """出生地名 → (name, lat, lon, resolved)

    ★BUG-12（2026-08-17）: 従来は出生地を【入力すると】lat/lon が 0.0 になり、
      ギニア湾沖（緯度0・経度0）で天体計算していた。空欄（東京扱い）より
      精度が悪化するという逆転が起きていた。
      → japan_prefectures.json（47件）で名寄せして実座標を解決する。

    「東京都」「東京」「大阪府」のように接尾辞の有無を吸収する。
    解決できない場合は東京の座標を用い、resolved=False を返す。
    """
    p = (place or "").strip()
    if not p:
        return PLACE_DEFAULT["name"], PLACE_DEFAULT["lat"], PLACE_DEFAULT["lon"], False

    # 接尾辞を除いた表記で照合（北海道はそのまま）
    stripped = p
    for suffix in ("都", "府", "県"):
        if stripped.endswith(suffix):
            stripped = stripped[:-1]
            break

    for e in _prefectures():
        n = e.get("name", "")
        if n and (n == p or n == stripped or p.startswith(n) or stripped.startswith(n)):
            return p, e["lat"], e["lon"], True

    # 未解決: 東京座標で代替（近似フラグを立てる）
    return p, PLACE_DEFAULT["lat"], PLACE_DEFAULT["lon"], False


def _normalize_gender(value: str) -> str:
    """性別表記のゆらぎを M / F / other / unknown に正規化する。

    ★BUG-13（2026-08-17）: INPUT のトップレベルにある "gender" を
      _parse_birth が読んでおらず（birth の中を見ていた）、常に unknown に
      なっていた。紫微斗数は GENDER_MAP のフォールバックで必ず「男」として
      命盤を立てるため、女性の入力でも男性の結果が出ていた。
    """
    g = (value or "").strip()
    if not g:
        return "unknown"
    low = g.lower()
    if low in ("m", "male", "man", "男", "男性"):
        return "M"
    if low in ("f", "female", "woman", "女", "女性"):
        return "F"
    return "other"


def _parse_birth(raw: dict, gender: str = "") -> BirthInfo:
    d = date.fromisoformat(raw["date"])  # YYYY-MM-DD 必須
    time_str = (raw.get("time") or "").strip()
    time_unknown = not time_str
    time_str = time_str or TIME_DEFAULT
    place = (raw.get("place") or "").strip()
    # birth 内の指定を優先し、無ければ引数（INPUTトップレベル）を使う
    gender = _normalize_gender(raw.get("gender") or gender)

    name, lat, lon, resolved = resolve_place(place)
    # 入力があっても解決できなければ「近似（東京扱い）」とみなす
    place_unknown = not resolved

    return BirthInfo(
        date=d,
        time=time_str,
        time_unknown=time_unknown,
        place_name=name,
        place_lat=lat,
        place_lon=lon,
        place_tz="Asia/Tokyo",
        place_unknown=place_unknown,
        gender=gender,
    )


def normalize_input(raw: dict) -> NormalizedInput:
    """ユーザーINPUT辞書 → 正規化済み入力（近似モード適用済み）"""
    birth = _parse_birth(raw["birth"], raw.get("gender", ""))
    partner = (_parse_birth(raw["partner"], raw.get("partner", {}).get("gender", ""))
               if raw.get("partner", {}).get("date") else None)

    name_kanji = (raw.get("name_kanji") or "").strip()
    name_kana = (raw.get("name_kana") or "").strip()
    name_romaji = kana_to_hepburn(name_kana) if name_kana else ""

    blood = (raw.get("blood_type") or "").strip().upper() or "unknown"
    if blood not in ("A", "B", "O", "AB"):
        blood = "unknown"

    target_raw = (raw.get("target") or "").strip()
    target_date = None
    if target_raw:
        try:
            target_date = date.fromisoformat(target_raw)
        except ValueError:
            target_date = None

    approx_flags = []
    if birth.time_unknown:
        approx_flags.append("time_unknown")
    if birth.place_unknown:
        approx_flags.append("place_unknown")
    if partner:
        if partner.time_unknown:
            approx_flags.append("partner_time_unknown")
        if partner.place_unknown:
            approx_flags.append("partner_place_unknown")

    return NormalizedInput(
        birth=birth,
        partner=partner,
        name_kanji=name_kanji,
        name_kana=name_kana,
        name_romaji=name_romaji,
        blood_type=blood,
        consultation=(raw.get("consultation") or "").strip(),
        target_date=target_date,
        approx_flags=approx_flags,
    )


def to_dict(ni: NormalizedInput) -> dict:
    """標準プロファイルJSON（計算ロジック仕様書 §2.1）"""
    def bdict(b: BirthInfo) -> dict:
        return {
            "date": b.date.isoformat(),
            "time": b.time,
            "time_unknown": b.time_unknown,
            "place": {"name": b.place_name, "lat": b.place_lat, "lon": b.place_lon, "tz": b.place_tz},
            "place_unknown": b.place_unknown,
            "gender": b.gender,
        }
    return {
        "birth": bdict(ni.birth),
        "partner": bdict(ni.partner) if ni.partner else None,
        "name": {
            "kanji": ni.name_kanji,
            "kana": ni.name_kana,
            "romaji_hepburn": ni.name_romaji,
        },
        "blood_type": ni.blood_type,
        "consultation": ni.consultation,
        "target_date": ni.target_date.isoformat() if ni.target_date else None,
        "approx_flags": ni.approx_flags,
    }
