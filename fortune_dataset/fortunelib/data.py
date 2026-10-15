# -*- coding: utf-8 -*-
"""
データローダ（data/*.json の読込）

解決順序（最初に見つかったものを採用）:
  1. 環境変数 FORTUNE_DATA_DIR
  2. パッケージと同階層の data/          （merged / kaggle_dataset レイアウト）
  3. パッケージの親の親の data/          （engine/ + data/ の分離レイアウト）
  4. /kaggle/input/ 配下の再帰探索        （Kaggle Dataset マウント・最大6階層）

※ 旧実装は 3 のみを見ていたため、kaggle_dataset レイアウトで
   FileNotFoundError（90テストエラー）になっていた。→ 本実装で解消。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_MARKER = "prompts.json"   # data ディレクトリの判定マーカー


def _candidates():
    env = os.environ.get("FORTUNE_DATA_DIR")
    if env:
        yield Path(env)
    here = Path(__file__).resolve().parent
    yield here.parent / "data"            # <root>/data （fortunelib と同階層）
    yield here.parent.parent / "data"     # engine/../data
    yield here / "data"                   # fortunelib/data（同梱時）


def _scan_kaggle():
    root = Path("/kaggle/input")
    if not root.is_dir():
        return None
    for depth in range(1, 7):
        for p in root.glob("/".join(["*"] * depth) + "/data"):
            if (p / _MARKER).exists():
                return p
    return None


def _resolve_data_dir() -> Path:
    for c in _candidates():
        if c and (c / _MARKER).exists():
            return c
    k = _scan_kaggle()
    if k:
        return k
    # マーカーが無くても存在するディレクトリを最後の砦として返す
    for c in _candidates():
        if c and c.is_dir():
            return c
    return Path(os.environ.get("FORTUNE_DATA_DIR", "data"))


DATA_DIR = _resolve_data_dir()


def load_json(name: str) -> list | dict:
    """data/ 配下のJSONを読み込む"""
    path = DATA_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"データファイルがありません: {path}\n"
            f"（FORTUNE_DATA_DIR を設定するか、fortunelib と同階層に data/ を置いてください）"
        )
    with open(path, encoding="utf-8") as f:
        return json.load(f)
