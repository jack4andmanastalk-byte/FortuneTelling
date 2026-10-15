# -*- coding: utf-8 -*-
"""
共通出力JSONスキーマ（計算ロジック仕様書 §5 の実装）
- 全モジュールはこのラッパーで結果を返す
- LLMプロンプト埋め込み・UI表示・保存（results/*.json）で共通利用
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Optional

JST = timezone(timedelta(hours=9))


def build_result(
    module: str,
    divination: str,
    inputs: dict,
    approx_flags: list,
    result: dict,
    references: Optional[list] = None,
    warnings: Optional[list] = None,
    notes: Optional[list] = None,
    model: Optional[dict] = None,
    input_fingerprint: Optional[str] = None,
    schema_version: str = "1.0",
) -> dict:
    """共通出力JSONの組み立て

    mts5.53（P-2/P-9）: `model`（結果を書いたモデル名とフォールバックの有無）と
    `input_fingerprint`（スキップガードの突合に使う入力指紋）を任意で記録する。
    どちらも省略したときは従来と同じキー構成（既存呼び出しに影響しない）。
    """
    out = {
        "schema_version": schema_version,
        "module": module,
        "divination": divination,
        "generated_at": datetime.now(JST).isoformat(timespec="seconds"),
        "inputs": inputs,
        "approx_flags": approx_flags,
        "result": result,
        "references": references or [],
        "warnings": warnings or [],
        "notes": notes or [],
    }
    if model:
        out["model"] = model
    if input_fingerprint:
        out["input_fingerprint"] = input_fingerprint
    return out
