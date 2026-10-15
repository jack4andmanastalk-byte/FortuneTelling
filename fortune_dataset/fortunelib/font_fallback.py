# -*- coding: utf-8 -*-
"""Pillow text drawing with a per-string Japanese glyph fallback.

The fallback is selected for the whole text run when the primary face is missing
one or more glyphs. It deliberately leaves unrelated scripts and symbol fonts
alone; callers decide which primary fonts are eligible for Japanese fallback.
"""
from __future__ import annotations

import warnings
from contextlib import contextmanager
from functools import lru_cache, wraps
from pathlib import Path
from threading import RLock
from typing import Callable, Iterator

_NOTDEF = "\ue000"
_DRAW_LOCK = RLock()
_REPORTED: set[tuple] = set()      # 同じ顔ぶれの警告は1回だけ（mts5.53）


@lru_cache(maxsize=32)
def _font_cmap(path: str) -> frozenset[int] | None:
    """Return a font's Unicode cmap, or None when fontTools cannot inspect it."""
    try:
        from fontTools.ttLib import TTFont
        font = TTFont(path, fontNumber=0, lazy=True)
        try:
            cmap = font.getBestCmap() or {}
            return frozenset(cmap)
        finally:
            font.close()
    except Exception:
        return None


def font_has_glyph(font, ch: str) -> bool:
    """Whether a Pillow font maps one character to a real glyph."""
    if not ch or ch.isspace():
        return True
    path = getattr(font, "path", None)
    if path:
        cmap = _font_cmap(str(Path(path).expanduser()))
        if cmap is not None:
            return ord(ch) in cmap
    try:
        glyph = font.getmask(ch)
        missing = font.getmask(_NOTDEF)
        if getattr(glyph, "size", (0, 0)) == (0, 0):
            return False
        return bytes(glyph) != bytes(missing) or glyph.size != missing.size
    except Exception:
        return False


def font_covers_text(font, text: str) -> bool:
    """Whether one font covers every non-whitespace character in a text run."""
    if font is None:
        return False
    return all(font_has_glyph(font, ch) for ch in str(text))


def choose_font(text: str, primary, fallback):
    """Use fallback for the whole run when it can repair any missing glyphs.

    mts5.53（P-4）: **どちらのフォントにも無い文字は、必ず報告する**。
    従来は「primary をそのまま返す」だけでした（＝フォールバックが欠けている環境でも
    警告も例外も出ず、画像だけが静かに豆腐化する経路がありました）。
    """
    if font_covers_text(primary, text):
        return primary
    missing = [ch for ch in dict.fromkeys(str(text))
               if not ch.isspace() and not font_has_glyph(primary, ch)]
    if fallback is not None and any(font_has_glyph(fallback, ch) for ch in missing):
        _report_unresolved([ch for ch in missing if not font_has_glyph(fallback, ch)])
        return fallback
    # Unsupported characters remain visible to the caller's preflight/diagnostic.
    _report_unresolved(missing)
    return primary


def _report_unresolved(chars: list[str]) -> None:
    """一次フォントにも日本語fallbackにも無い文字を報告する（mts5.53・P-4）。

    `RunWarning` を1回だけ（プロセス内で同じ顔ぶれは畳んで）出し、台帳にも積む。
    描画は従来どおり続行する（表示を止めるのは `RUN_STRICT=1` の役目）。
    """
    chars = [ch for ch in dict.fromkeys(chars) if ch and not ch.isspace()]
    if not chars:
        return
    codes = " ".join(f"U+{ord(ch):04X}" for ch in chars[:8])
    msg = (f"型Cの一次フォントと日本語fallbackの両方に無い文字があります: "
           f"{''.join(chars[:8])} ({codes})"
           + (f" 他{len(chars) - 8}字" if len(chars) > 8 else ""))
    key = ("fallback_missing", tuple(chars))
    if key in _REPORTED:
        return
    _REPORTED.add(key)
    try:
        from .runcheck import add_warning
        add_warning(msg)
    except Exception:
        pass
    warnings.warn(msg, RuntimeWarning, stacklevel=3)


def _wrap_draw_method(original, selector: Callable[[str, object], object]):
    @wraps(original)
    def wrapped(self, xy, text, *args, **kwargs):
        if isinstance(text, str):
            font = kwargs.get("font")
            positional_font = False
            # Pillow's signatures place font after fill: text(xy, text, fill, font).
            if font is None and len(args) >= 2:
                font = args[1]
                positional_font = True
            try:
                selected = selector(text, font)
            except Exception:
                selected = font
            if selected is not None and selected is not font:
                if "font" in kwargs:
                    kwargs = dict(kwargs)
                    kwargs["font"] = selected
                elif positional_font:
                    args = list(args)
                    args[1] = selected
                    args = tuple(args)
                else:
                    kwargs = dict(kwargs)
                    kwargs["font"] = selected
        return original(self, xy, text, *args, **kwargs)
    return wrapped


@contextmanager
def fallback_drawing(selector: Callable[[str, object], object]) -> Iterator[None]:
    """Temporarily apply a selector to Pillow's text and multiline_text calls.

    The patch is scoped and restored even after rendering errors. A re-entrant
    lock serializes concurrent render operations that use this helper.
    """
    from PIL import ImageDraw

    with _DRAW_LOCK:
        draw_cls = ImageDraw.ImageDraw
        orig_text = draw_cls.text
        orig_multiline = draw_cls.multiline_text
        draw_cls.text = _wrap_draw_method(orig_text, selector)
        draw_cls.multiline_text = _wrap_draw_method(orig_multiline, selector)
        try:
            yield
        finally:
            draw_cls.text = orig_text
            draw_cls.multiline_text = orig_multiline
