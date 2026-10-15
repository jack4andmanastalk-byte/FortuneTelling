# -*- coding: utf-8 -*-
"""実行時の警告台帳と強化モード（mts5.53）。

背景（製品側ツールの独立監査・P-1／P-4／P-7／P-10）:
  - 画像やフォントが欠けても、**警告も例外も出ずに成果物だけが静かに変わる**経路があった。
  - 警告は標準エラーに流れるだけで、**集約も合否への反映も無かった**。

ここでは「気づいた問題を1か所に集める」だけを担う（挙動は既定で従来どおり）:
  - `add_warning(text)`: 台帳に1行追加（重複は畳む）。
  - `report()`: 台帳を1ブロックで出力し、件数を返す。
  - `enforce()`: 環境変数 `RUN_STRICT=1`（真偽値相当）のときだけ `SystemExit(1)`。
    既定（未設定）では**停止しない**＝これまでの運用を壊さない。

Kaggle で厳格に回したいときだけ、Cell 1 などで `%env RUN_STRICT=1` を設定してください。
"""
from __future__ import annotations

import os

#: 収集した警告（プロセス内で共有・重複は畳む）
WARNINGS: list[str] = []

#: RUN_STRICT の真偽値として扱う文字列
_TRUTHY = {"1", "true", "yes", "on", "y", "t"}


def strict_enabled() -> bool:
    """`RUN_STRICT` が有効か（既定は False＝警告のみ）。"""
    return (os.environ.get("RUN_STRICT", "") or "").strip().lower() in _TRUTHY


def add_warning(text: str) -> None:
    """警告を台帳に追加する（空文字・重複は無視）。"""
    t = (text or "").strip()
    if t and t not in WARNINGS:
        WARNINGS.append(t)


def clear() -> None:
    """台帳を空にする（テスト用）。"""
    WARNINGS.clear()


def report(prefix: str = "  ⚠") -> int:
    """台帳を出力する。件数を返す（出力は `print`＝Notebook のログに残す）。"""
    for w in WARNINGS:
        print(f"{prefix} {w}")
    if WARNINGS:
        print(f"{prefix} 合計 {len(WARNINGS)} 件"
              + ("（RUN_STRICT=1 のため不合格にします）" if strict_enabled()
                 else "（合否には影響しません。RUN_STRICT=1 で不合格にできます）"))
    return len(WARNINGS)


def report_since(mark: int = 0, prefix: str = "  ⚠") -> int:
    """`mark` 以降に増えた警告だけを出力する（人ごとの実行で使う）。新しい mark を返す。"""
    for w in WARNINGS[mark:]:
        print(f"{prefix} {w}")
    return len(WARNINGS)


def enforce() -> None:
    """`RUN_STRICT=1` かつ警告があるときだけ停止する（既定では何もしない）。"""
    if WARNINGS and strict_enabled():
        print(f"❌ RUN_STRICT=1: 警告 {len(WARNINGS)} 件を不合格として停止します")
        raise SystemExit(1)
