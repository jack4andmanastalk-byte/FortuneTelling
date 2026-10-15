# -*- coding: utf-8 -*-
"""実行中の Kaggle Notebook が Dataset のセル定義より古くないかの検査（mts5.40）。

**なぜ必要か**: mts5.35 で `cellN2_synthesis.py` に「音声つきハイライト動画」を追加したが、
手元の Kaggle Notebook（＝ユーザーが実行する .ipynb）は**取り込み直されていなかった**ため、
本番では動画のコードが1行も走らず**カードが出なかった**（2026-09-27 の実機で発覚）。
Dataset の New Version だけでは Notebook の中身は変わらない、という落とし穴を塞ぐ。

Cell 0（ブートストラップ）が最初に呼ぶので、**12分のAPI呼び出しを始める前に気づける**。
見つからなければ何も言わない（誤警告を出さない）。例外も投げない。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# Cell N2 の動画ON/OFFだけは、利用者が実行コストを調整するための設定差分として許容する。
# True/False以外への変更、同セルの他の差分、他セルの差分は従来どおり不一致にする。
# mts5.69: 冒頭動画の埋め込み（EMBED_INTRO_VIDEO）も同じ扱い（各 1 行・Boolean 値だけ）。
_ALLOWED_SETTINGS = ("EMBED_INTRO_VIDEO",)


def _setting_re(name: str) -> re.Pattern:
    return re.compile(
        r"(?m)^(?P<prefix>[ \t]*" + name + r"[ \t]*=[ \t]*)"
        r"(?P<value>True|False)(?P<suffix>[ \t]*(?:\#.*)?)(?=\r?$)"
    )


_SETTING_RES = {name: _setting_re(name) for name in _ALLOWED_SETTINGS}
_VIDEO_SETTING = _SETTING_RES["EMBED_INTRO_VIDEO"]      # 後方互換（旧名）
_VIDEO_SETTING_SENTINEL = "<VIDEO_SETTING>"


def _normalized_cell_source(name: str, source: str) -> str:
    """許可する設定行（各 1 行）の Boolean 値だけを正規化する。

    行全体の改変や、設定名・値の型の変更は許可しない。
    """
    if name != "cellN2_synthesis.py":
        return source
    out = source
    for key, rx in _SETTING_RES.items():
        normalized, count = rx.subn(
            lambda m, _k=key: f"{m.group('prefix')}<{_k}>{m.group('suffix')}",
            out,
        )
        if count == 1:
            out = normalized
    return out


# ノートブックのコードセルに対応する正本（この順に並んでいる）
CELL_FILES = ("cell0_bootstrap.py", "cell0_selftest.py",
              "cell1_csv_input.py", "cellN2_synthesis.py")


def code_cells(nb: dict) -> list[str]:
    """ノートブックのコードセル本文（改行を結合して返す）。"""
    out = []
    for c in nb.get("cells") or []:
        if c.get("cell_type") != "code":
            continue
        src = c.get("source") or ""
        out.append("".join(src) if isinstance(src, list) else str(src))
    return out


def find_running_notebook(cwd: Path | None = None,
                          extra: tuple[Path, ...] = ()) -> Path | None:
    """実行中のノートブック本体を探す（見つからなければ None）。

    Kaggle の実行では作業ディレクトリに `__notebook__.ipynb` が置かれる。
    無ければ cwd / /kaggle/working の *.ipynb を探す。
    """
    here = Path(cwd) if cwd else Path.cwd()
    cands = [here / "__notebook__.ipynb"]
    for d in (here, Path("/kaggle/working"), *extra):
        try:
            cands += sorted(Path(d).glob("*.ipynb"))
        except Exception:
            continue
    for c in cands:
        try:
            if c.is_file():
                return c
        except Exception:
            continue
    return None


def load_cells(notebook: Path) -> list[str] | None:
    """ノートブックのコードセル本文を読む（読めなければ None＝判断しない）。"""
    try:
        nb = json.loads(Path(notebook).read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(nb, dict) or "cells" not in nb:
        return None
    return code_cells(nb)


def stale_cells(base: Path, notebook: Path) -> list[str]:
    """Dataset の `kaggle/cell*.py` のうち、ノートブックに**そのまま入っていない**もの。

    ノートブックが読めない場合は空を返す（＝警告しない。誤警告を避ける）。
    """
    kg = Path(base) / "kaggle"
    if not kg.is_dir():
        return []
    have = load_cells(notebook)
    if have is None:
        return []
    stale = []
    for name in CELL_FILES:
        p = kg / name
        try:
            src = p.read_text(encoding="utf-8")
        except Exception:
            continue
        expected = _normalized_cell_source(name, src)
        if not any(_normalized_cell_source(name, candidate) == expected
                   for candidate in have):
            stale.append(name)
    return stale


def check_notebook_freshness(base: Path, notebook: Path | None = None,
                             cwd: Path | None = None, log=print) -> list[str]:
    """古いセルがあれば警告を出す。戻り値は古いセル名のリスト（空＝一致）。"""
    try:
        nb = Path(notebook) if notebook else find_running_notebook(cwd)
        if nb is None or not Path(base).is_dir():
            return []
        if load_cells(nb) is None:
            return []                      # 読めない＝判断しない（誤警告も誤「一致」もしない）
        stale = stale_cells(base, nb)
        if not stale:
            log(f"✅ Notebook の版チェック: Dataset のセル定義と一致（{nb.name}）")
            return []
        log("=" * 62)
        log("⚠️ この Notebook は Dataset より古い可能性があります（mts5.40 の検査）")
        log("   一致しないセル: " + ", ".join(stale))
        log("   → Kaggle の File → Import Notebook で、Dataset 内の")
        log("     fortune_dataset/kaggle/fortune_notebook.ipynb を取り込み直してください。")
        log("     （古い Notebook のまま実行すると、新しい機能が動きません）")
        log("=" * 62)
        return stale
    except Exception:
        return []
