# -*- coding: utf-8 -*-
"""冒頭動画カード（mts5.69・2026-10-14 ユーザー決定）。

HTML レポート（1枚・オフライン可）の**目次の直前**に、同梱の固定動画（全員共通）を
Base64 で埋め込んで置く。あわせて、大きなサイズのオンライン版（YouTube）への案内
「オンラインからも視聴できます」を添える。

設計の柱（**失敗しても本体を壊さない**＝ハイライト動画カード mts5.35 と同じ流儀）:

1. **同梱の固定動画** ＝ `assets/video/intro_video.json` が置き場と文言の正本
   （`file`・`poster`・`title`・`note`・`online_url`・`sha256` …）。JSON が無ければカードは
   出さない（＝従来どおりの HTML）。例外は呼び出し側へ投げない。
2. **再生は二段構え**。本文には base64 の data URI を **1 部だけ**持ち（JS が無効なら
   そのまま再生＝Chrome/Android/PC）、JS が動くときは Blob に変換して再生する。
   iOS/macOS Safari は `data:` URI の動画が再生されない既知の不具合（WebKit #232076）が
   あるため、Safari が受け付ける `srcObject = Blob` を先に試し、受け付けない
   ブラウザでは Blob URL を新しい `<source>` に差し込む（iOS 17 系で `video.src` への
   直接代入が効かない報告があるため）。
3. **自動再生はしない**（`controls playsinline preload="metadata"`）。再生前の絵は同梱の
   静止画（poster）。
4. **ON/OFF は Cell N2 の `EMBED_INTRO_VIDEO`**（既定 True）。`build_html(intro_video_html="")`
   で OFF、`None` で自動（assets/video を探す）。Notebook の版チェックはこの 1 行の
   True/False だけを設定差分として許容する（`notebook_guard`）。
5. **検証**: `embedded_video_digest(html)` が HTML 内の動画を復号して SHA-256 を返す。
   `verify/verify_run_output.py` は同じ規則を独立に実装し、同梱の原本と突合する。
"""
from __future__ import annotations

import base64
import hashlib
import html as _html
import json
import re
import struct
from pathlib import Path

CONFIG_NAME = "intro_video.json"
VIDEO_DIRNAME = "video"
CARD_ID = "intro-video"
PLAYER_ID = "iv-player"
ONLINE_LABEL = "オンラインからも視聴できます"
DEFAULT_TITLE = "お祓い（Purification）の動画"
DEFAULT_NOTE = ("鑑定の前後にご覧いただく動画です。"
                "このファイル1枚で再生できます（自動再生はしません）。")
DEFAULT_ONLINE_PREFIX = "大きなサイズの動画は "
DEFAULT_ONLINE_SUFFIX = "（YouTube）"

# 動画カードの共通 CSS（.hl-card/.hl-note/.hl-video/.hl-meta）
CARD_CSS = """
.hl-card{ border:1px solid #d8cbb4; background:#fffdf7; }
.hl-card h2::before{ content:""; }
.hl-note{ margin:4px 0 10px; padding:8px 10px; border-left:3px solid #d8cbb4;
          font-size:12.5px; color:#6b6355; background:#faf6ee; }
.hl-video{ width:100%; max-width:640px; display:block; border-radius:8px;
           background:#000; margin:0 auto; }
.hl-meta{ margin:8px 0 0; font-size:12px; color:#8a7f6d; text-align:center; }
"""

# 冒頭動画カード専用の CSS（オンライン案内の行）
INTRO_CSS = """
.iv-online{ margin:10px 0 0; text-align:center; font-size:14px; }
.iv-online a{ font-weight:600; }
.iv-url{ font-size:12px; color:#8a7f6d; word-break:break-all; }
"""

# 再生用の JS（ASCII のみ・依存なし）。data: URI を 1 部だけ持ち、Blob に変換して再生する。
PLAYER_JS = (
    "(function(){"
    "var v=document.getElementById('" + PLAYER_ID + "');if(!v)return;"
    "var s=v.querySelector('source');if(!s)return;"
    "var src=s.getAttribute('src')||'';var i=src.indexOf('base64,');if(i<0)return;"
    "try{"
    "var bin=atob(src.slice(i+7));var n=bin.length;var u8=new Uint8Array(n);"
    "for(var k=0;k<n;k++){u8[k]=bin.charCodeAt(k);}"
    "var blob=new Blob([u8],{type:'video/mp4'});var done=false;"
    "try{v.srcObject=blob;done=!!v.srcObject;}catch(e){done=false;}"
    "if(!done){var ns=document.createElement('source');ns.type='video/mp4';"
    "ns.src=URL.createObjectURL(blob);v.replaceChild(ns,s);}"
    "else{v.removeChild(s);}"
    "v.load();v.setAttribute('data-iv-mode',done?'srcObject':'blob-url');"
    "}catch(e){v.setAttribute('data-iv-mode','data-uri');}"
    "})();"
)

_B64_RE = re.compile(r'data:video/mp4;base64,([A-Za-z0-9+/=]+)')


# --- 1. MP4 の簡易プローブ（ffmpeg 不要） --------------------------------------

def probe_mp4(path) -> dict:
    """moov/mvhd と tkhd から 秒数・幅・高さ を読む（読めない項目は入れない）。"""
    out: dict = {}
    try:
        data = Path(path).read_bytes()
    except Exception:
        return out
    n = len(data)

    def boxes(start: int, end: int):
        pos = start
        while pos + 8 <= end:
            size, typ = struct.unpack(">I4s", data[pos:pos + 8])
            hdr = 8
            if size == 1 and pos + 16 <= end:
                size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
                hdr = 16
            elif size == 0:
                size = end - pos
            if size < hdr:
                return
            yield typ, pos + hdr, min(pos + size, end)
            pos += size

    try:
        for typ, b, e in boxes(0, n):
            if typ != b"moov":
                continue
            for t2, b2, e2 in boxes(b, e):
                if t2 == b"mvhd" and e2 - b2 >= 20:
                    ver = data[b2]
                    if ver == 1:
                        ts = struct.unpack(">I", data[b2 + 20:b2 + 24])[0]
                        du = struct.unpack(">Q", data[b2 + 24:b2 + 32])[0]
                    else:
                        ts, du = struct.unpack(">II", data[b2 + 12:b2 + 20])
                    if ts:
                        out["seconds"] = round(du / ts, 2)
                elif t2 == b"trak" and "width" not in out:
                    for t3, b3, e3 in boxes(b2, e2):
                        if t3 == b"tkhd":
                            w, h = struct.unpack(">II", data[e3 - 8:e3])
                            w, h = w >> 16, h >> 16
                            if w and h:
                                out["width"], out["height"] = w, h
            break
    except Exception:
        pass
    return out


# --- 2. 置き場と設定 ------------------------------------------------------------

def find_video_dir(start) -> Path | None:
    """assets/images（または assets・video 自身・pkg ルート）から assets/video を解決する。"""
    if start is None:
        return None
    p = Path(start)
    cands = [p, p / VIDEO_DIRNAME, p.parent / VIDEO_DIRNAME,
             p / "assets" / VIDEO_DIRNAME, p.parent / "assets" / VIDEO_DIRNAME]
    for c in cands:
        try:
            if (c / CONFIG_NAME).is_file():
                return c
        except Exception:
            continue
    return None


def load_config(video_dir) -> dict | None:
    try:
        cfg = json.loads((Path(video_dir) / CONFIG_NAME).read_text(encoding="utf-8"))
    except Exception:
        return None
    return cfg if isinstance(cfg, dict) and cfg.get("file") else None


def sha256_of(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --- 3. カード HTML ---------------------------------------------------------------

def _poster_attr(poster: Path | None) -> str:
    if poster is None or not Path(poster).is_file():
        return ""
    suffix = Path(poster).suffix.lower().lstrip(".")
    mime = {"webp": "image/webp", "png": "image/png", "jpg": "image/jpeg",
            "jpeg": "image/jpeg"}.get(suffix, "image/webp")
    p64 = base64.b64encode(Path(poster).read_bytes()).decode("ascii")
    return f' poster="data:{mime};base64,{p64}"'


def intro_video_card_html(mp4, cfg: dict, *, poster=None, probe: dict | None = None) -> str:
    """冒頭カード（base64 を 1 部だけ埋め込み・autoplay なし・オンライン案内つき）。"""
    mp4 = Path(mp4)
    raw = mp4.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    info = dict(probe or {})
    for k in ("seconds", "width", "height"):
        if not info.get(k) and cfg.get(k):
            info[k] = cfg[k]
    title = _html.escape(str(cfg.get("title") or DEFAULT_TITLE))
    note = _html.escape(str(cfg.get("note") or DEFAULT_NOTE))
    url = str(cfg.get("online_url") or "").strip()
    label = _html.escape(str(cfg.get("online_label") or ONLINE_LABEL))
    prefix = _html.escape(str(cfg.get("online_prefix", DEFAULT_ONLINE_PREFIX)))
    suffix = _html.escape(str(cfg.get("online_suffix", DEFAULT_ONLINE_SUFFIX)))
    size_mb = len(raw) / 1e6
    meta_bits = []
    if info.get("seconds"):
        meta_bits.append(f"約{float(info['seconds']):.0f}秒")
    meta_bits.append(f"{size_mb:.2f}MB")
    if info.get("width") and info.get("height"):
        meta_bits.append(f"（{int(info['width'])}×{int(info['height'])} の軽量版）")
    meta = "・".join(meta_bits[:2]) + ("".join(meta_bits[2:]))
    online = ""
    if url:
        url_attr = _html.escape(url, quote=True)
        online = (f'<p class="iv-online">{prefix}<a href="{url_attr}" target="_blank" '
                  f'rel="noopener noreferrer">{label}</a>{suffix}'
                  f'<br><span class="iv-url">{_html.escape(url)}</span></p>')
    return (
        f'<section id="{CARD_ID}" class="card hl-card iv-card">'
        f'<h2>🎬 {title}</h2>'
        f'<p class="hl-note">{note}</p>'
        f'<video id="{PLAYER_ID}" class="hl-video" controls playsinline preload="metadata"'
        f'{_poster_attr(poster)}>'
        f'<source src="data:video/mp4;base64,{b64}" type="video/mp4">'
        'お使いのブラウザは動画タグに対応していません。</video>'
        f'<script>{PLAYER_JS}</script>'
        f'<p class="hl-meta">{meta}</p>'
        f'{online}'
        '</section>')


def load_intro_video_card(assets_root, *, enabled: bool = True) -> tuple[str, dict]:
    """同梱の設定から冒頭カードを作る。戻り値は (HTML, 情報)。失敗は ("", {"reason": ...})。"""
    if not enabled:
        return "", {"reason": "disabled"}
    vdir = find_video_dir(assets_root)
    if vdir is None:
        return "", {"reason": "no_config", "searched": str(assets_root)}
    cfg = load_config(vdir)
    if cfg is None:
        return "", {"reason": "bad_config", "dir": str(vdir)}
    mp4 = vdir / str(cfg["file"])
    if not mp4.is_file():
        return "", {"reason": "no_file", "dir": str(vdir), "file": str(cfg["file"])}
    try:
        digest = sha256_of(mp4)
        probe = probe_mp4(mp4)
        poster = (vdir / str(cfg["poster"])) if cfg.get("poster") else None
        html_text = intro_video_card_html(mp4, cfg, poster=poster, probe=probe)
    except Exception as e:                      # 本体を壊さない
        return "", {"reason": "error", "error": f"{type(e).__name__}: {e}", "dir": str(vdir)}
    want = str(cfg.get("sha256") or "").lower()
    info = {
        "reason": "ok", "dir": str(vdir), "file": mp4.name,
        "size_bytes": mp4.stat().st_size, "size_mb": mp4.stat().st_size / 1e6,
        "seconds": float(probe.get("seconds") or cfg.get("seconds") or 0),
        "width": probe.get("width") or cfg.get("width"),
        "height": probe.get("height") or cfg.get("height"),
        "sha256": digest, "sha_match": (digest == want) if want else None,
        "online_url": str(cfg.get("online_url") or ""),
        "poster": bool(poster and Path(poster).is_file()),
        "html_bytes": len(html_text.encode("utf-8")),
    }
    return html_text, info


# --- 4. 検証用（HTML から復号） -----------------------------------------------------

def embedded_video_digest(html_text: str) -> dict | None:
    """HTML の冒頭カードを読み、埋め込み動画の SHA-256・位置・案内の有無を返す。

    カードが無ければ None。検証器（verify_run_output.py）とテストが使う。
    """
    i_card = html_text.find(f'id="{CARD_ID}"')
    if i_card < 0:
        return None
    i_toc = html_text.find('<nav class="toc">')
    seg_end = i_toc if i_toc > i_card else len(html_text)
    seg = html_text[i_card:seg_end]
    m = _B64_RE.search(seg)
    out = {
        "before_toc": i_toc > i_card,
        "copies": len(_B64_RE.findall(html_text)),
        "online_label": ONLINE_LABEL in seg,
        "online_url": "",
        "script": f"getElementById('{PLAYER_ID}')" in seg,
        "autoplay": " autoplay" in seg,
        "poster": ' poster="data:image/' in seg,
    }
    mu = re.search(r'<a href="([^"]+)" target="_blank"', seg)
    if mu:
        out["online_url"] = _html.unescape(mu.group(1))
    if m:
        try:
            raw = base64.b64decode(m.group(1), validate=True)
            out["sha256"] = hashlib.sha256(raw).hexdigest()
            out["bytes"] = len(raw)
        except Exception:
            out["sha256"], out["bytes"] = None, 0
    else:
        out["sha256"], out["bytes"] = None, 0
    return out
