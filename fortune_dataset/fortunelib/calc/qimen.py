# -*- coding: utf-8 -*-
"""
M24 奇門遁甲 — kinqimen 委譲アダプタ
仕様：計算ロジック仕様書 §4.17
- ライブラリ: kinqimen 0.0.6.6（時家 拆補/置閏・刻家・金函玉鏡）
- 既知の問題: `import config` の絶対import → sys.modules 注入で回避
- 依存: sxtwl（インストール済み）+ ephem 4.2.1（pip で個別導入）
"""
from __future__ import annotations

import sys


def _patch_and_import():
    """kinqimen の絶対import問題を回避して import する"""
    import kinqimen.config as _kc
    sys.modules.setdefault("config", _kc)
    from kinqimen import kinqimen
    return kinqimen


_kinqimen = None
try:
    _kinqimen = _patch_and_import()
except ImportError:
    _kinqimen = None


def _require():
    if _kinqimen is None:
        raise RuntimeError("kinqimen が必要です（pip install --no-deps kinqimen 後に ephem 導入）")


# 方角マップ（九宮）
GONG_DIR = {1: "坎", 2: "坤", 3: "震", 4: "巽", 5: "中", 6: "乾", 7: "兌", 8: "艮", 9: "離"}


def qimen_pan(y: int, m: int, d: int, hour: int = 12, minute: int = 0,
              method: int = 1) -> dict:
    """
    時家奇門排盤（拆補法=1 / 置閏法=2）。

    Returns:
        dict: 干支・排局・節氣・天盤・地盤・八門・九星・八神・旬空・馬星など
    """
    _require()
    r = _kinqimen.Qimen(y, m, d, hour, minute).pan(method)
    # kinqimen の出力（中国語キー）をそのまま返す（LLM解釈に十分な情報量）
    return {
        "method": r.get("排盤方式"),
        "ganzhi": r.get("干支"),
        "xunshou": r.get("旬首"),
        "xunkong": r.get("旬空"),
        "juri": r.get("局日"),
        "paiju": r.get("排局"),
        "jieqi": r.get("節氣"),
        "zhifu_zhishi": r.get("值符值使"),
        "tianpan": r.get("天盤"),
        "dipan": r.get("地盤"),
        "men": r.get("門"),
        "xing": r.get("星"),
        "shen": r.get("神"),
        "maxing": r.get("馬星"),
        "references": ["kinqimen 0.0.6.6", "sxtwl", "ephem 4.2.1"],
        "notes": ["排盤方式: 時家転盤（拆補/置閏）", "流派により局数・暗干の扱いが異なる場合があります"],
    }
