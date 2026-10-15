# -*- coding: utf-8 -*-
"""
M22 六爻 — divicast 委譲アダプタ＋コイン起卦RNG
仕様：計算ロジック仕様書 §4.16
- ライブラリ: divicast 0.2.3（MIT・本卦之卦・納甲・六親・六神・世応・伏神）
- 入力形式: コインの「表の枚数」(0-3) を受け取るため、爻値(6/7/8/9)を変換
- 起卦: RNG（3枚のコインを6回）または手動爻値
"""
from __future__ import annotations

import random
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))

try:
    from divicast.sixline.divinatory_symbol import DivinatorySymbol
    from divicast.sixline import plain_draw_divination, to_standard_format
    _HAVE_DIVICAST = True
except ImportError:
    _HAVE_DIVICAST = False

try:                                   # 簡体字 → 日本語表記（mts5.31）
    from ..text_ja import to_ja_text as _to_ja
except Exception:                      # pragma: no cover - 単体実行時のみ
    def _to_ja(x):
        return x


YAO_TO_COINS = {6: 0, 7: 1, 8: 2, 9: 3}   # 爻値 → 表の枚数
COINS_TO_YAO = {0: 6, 1: 7, 2: 8, 3: 9}   # 表の枚数 → 爻値


def _require():
    if not _HAVE_DIVICAST:
        raise RuntimeError("divicast が必要です（pip install divicast）")


def throw_coins(rng: random.Random) -> list:
    """コイン3枚 × 6回（下から上へ）→ 爻値 [6,7,8,9] のリスト"""
    result = []
    for _ in range(6):
        heads = sum(1 for _ in range(3) if rng.random() < 0.5)
        result.append(COINS_TO_YAO[heads])
    return result


def liuyao_paipan(yao_values: list | None = None,
                  seed: int | None = None,
                  manual: bool = False,
                  rng_mode: str = "random",
                  when: datetime | None = None) -> dict:
    """
    六爻排盤。

    Args:
        yao_values: 爻値リスト（下から上、6要素）。None ならRNG起卦
        seed: RNGシード（再現モード）
        manual: True なら yao_values をそのまま使用（False なら 6→0等に変換）
        rng_mode: "random"（既定・毎回ランダム）/ "reproducible"（再現）
        when: 起卦時刻。省略時は **JST（日本時間）の現在時刻**（mts5.50）。
              六神・空亡・神煞は起卦日の日干・日支で決まるため、コンテナの
              ローカル時刻（Kaggle＝UTC）に依存させない。aware な datetime は
              JSTへ変換して使う。naive な datetime は「JSTの壁時計」とみなす。

    Returns:
        dict: 本卦・之卦・六親・六神・納甲・世応・神煞・干支
    """
    _require()
    # mts5.50: 他のツール（astrology / meihua は datetime.now(JST)）と揃える。
    # 従来は divicast 側の datetime.now()（naive＝Kaggle では UTC）に任せていた。
    when = when or datetime.now(JST)
    _naive = when.astimezone(JST).replace(tzinfo=None) if when.tzinfo else when
    if yao_values is None:
        if rng_mode == "reproducible":
            rng = random.Random(seed)
        else:
            from ..rng import FortuneRNG
            rng = FortuneRNG(seed=None, mode="random")
        yao_values = throw_coins(rng)

    if not manual:
        coins = [YAO_TO_COINS.get(v, 2) for v in yao_values]
    else:
        coins = yao_values

    ds = DivinatorySymbol.create(coins, now=_naive)
    out = to_standard_format(ds)

    # 爻ごとの詳細（六親・六神・納甲・世応・動爻・伏神）
    lines = []
    for i in range(1, 7):
        y = getattr(out, f"yao_{i}")
        o = y.origin
        lines.append({
            "pos": i,  # 1=初爻（下）〜6=上爻
            "liushen": _to_ja(y.liushen),               # 六神（簡体字→日本語表記）
            "relative": _to_ja(o.relative),             # 六親
            "gan": o.gan, "zhi": o.zhi, "wuxing": o.wuxing,  # 納甲
            "is_subject": o.is_subject,                 # 世
            "is_object": o.is_object,                   # 応
            "is_changed": o.is_changed,                 # 動爻
            "fushen": _to_ja(o.fushen.relative) if o.fushen else None,  # 伏神
        })

    return {
        "yao_values": yao_values,      # 6/7/8/9（下から上）
        "origin_hexagram": _to_ja(str(ds.origin_hexagram), "name"),
        "variant_hexagram": _to_ja(str(ds.variant_hexagram), "name"),
        "lines": lines,
        "bazi": out.bazi,
        "kongwang": out.kongwang,
        "shensha": ([{"name": _to_ja(s.name), "zhi": s.zhi} for s in out.shensha]
                    if hasattr(out, "shensha") and out.shensha else []),
        "plain": _to_ja(plain_draw_divination(ds)),
        "references": ["divicast 0.2.3 (MIT)"],
        "notes": [
            "起卦はコイン3枚×6回シミュレーション（seed固定で再現可）",
            "起卦時刻はJST（日本時間）を基準にします。六神・空亡・神煞は"
            "起卦日の日干・日支で決まるため、`when` で時刻を明示指定できます（mts5.50）",
            "ライブラリ（divicast）が返す中国語表記は日本語表記へ変換しています"
            "（卦名＝伝統字形・六神/六親/神煞＝日本語の通用字形。数値・構造は原文どおり／mts5.31）",
        ],
    }
