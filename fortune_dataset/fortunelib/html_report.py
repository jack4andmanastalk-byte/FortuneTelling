# -*- coding: utf-8 -*-
"""
全成果物を1枚のHTMLに束ねる（スマホでの保存・閲覧向け）

狙い:
  - 1ファイル完結（画像・外部CSS・外部JSに依存しない）→ 端末に保存すれば
    オフラインでも読める。AirDrop やメール添付でも崩れない。
  - iPhone / Android のブラウザで読みやすいレスポンシブCSSを内蔵。
  - 目次から各節へジャンプ。個別占術は折りたたみ（<details>）で
    最初は畳んでおき、必要な人だけ開く。

構成順（ユーザー指定）:
  1. 統合レポート（synthesis_report.md）
  2. クラスター別の中間レポート（cluster_reports/*.md）
  3. 個別の占術レポート（results/*.md）

画像埋め込み（Turn10-13統合 → mts4.7多枚対応）:
  - assets/images 配下の6ツール（M23_meihua 64, M26_iching 64, M27_tarot 78, M27_marseille 78, M27_lenormand 36, M27_cartomancy 52）に
    ついて、占術結果の全てのカード/卦に対応する画像をBase64埋め込み（全枚表示・1枚の場合は単独表示）。
    見つからなければスキップ（後方互換）。
    例: タロット10枚(ケルト十字)・マルセイユ3枚・レノルマン3枚・カルトマンシー5枚は全枚表示し、画像サイズはグリッドで調整。
  - WebPとJPGの大小比較：小さい方を採用（Turn10: WebP>JPGならJPG配布）
  - M27_kipper / M27_runes / M28_omikuji は mts4.9 で表示統合（キッパー=グリッド、ルーン=グリッド、おみくじ=1枚大表示）
  - M27_oracle / M27_angel は mts5.0 で表示統合（44枚デッキ。番号＋カード名で解決し、名前不一致はスキップ）
  - M23_meihua は本卦・変卦・互卦の3卦、M26_iching は本卦・変卦の2卦を全表示（存在すれば）
  - M09_animal / M11_genekeys は mts5.2 で表示統合（1枚大表示。番号＋名前で解決し、不一致はスキップ）
  - M02_seiza は mts5.3 で表示統合（星座12の1枚大表示。番号＋英名で解決）
  - M01_eto は mts5.7 で表示統合（干支12の1枚大表示。支→番号＋英名で解決）
  - M08_blood（血液型4）は **mts5.7 で画像をオミット**（方針変更。突合・目視で型が分かるため画像を出さない。
    画像そのものは `assets_bases/blood/_clean/` に退避してあり、`--tool blood` で復活できる）
  - M29_pendulum（ペンデュラム3）・M30_crystalball（水晶玉1）は **mts5.8 で追加**（型D: 用具・情景型）。
  - M30_crystal（クリスタル12石）は **mts5.9 で追加**（型D。鑑定文に現れた石名と一致する1枚のみ表示）。
  - M29_african（アフリカ9枚）・M30_talisman（タリスマン1枚）は **mts5.10 で追加**（型D。アフリカは `calc.open_count`、タリスマンは固定1枚）。
  - M30_ornith（鳥占5枚）・M30_delphi（デルポイの託宣5枚）は **mts5.14 で追加**（P6 古代託宣群。calc を持たない生成系のため
    **占術結果と無関係に5変種から意図的にランダムに1枚表示**＝御神籤感覚・ユーザー決定 2026-09-26）。
    calc.answer（yes/no/neutral）→ 番号＋英名（Yes/No/Neutral）で検証して1枚大表示
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

# mts5.60: 石の表（クリスタル／パワーストーン）の唯一の正本
from .stones import CRYSTAL_STONES, resolve_stone_in_text

JST = timezone(timedelta(hours=9))

CSS = """
:root{
  --bg:#faf8f5; --card:#fff; --ink:#2b2b30; --sub:#6b6b76;
  --line:#e6e1d8; --accent:#7b5ea7; --accent2:#b08d57; --mark:#f6f1e7;
}
@media (prefers-color-scheme:dark){
  :root{ --bg:#16161a; --card:#1e1e24; --ink:#e9e7e3; --sub:#a8a6a0;
         --line:#33333c; --accent:#b9a0e0; --accent2:#d4b071; --mark:#26262e; }
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Hiragino Kaku Gothic ProN",
    "Noto Sans JP","Yu Gothic",Meiryo,sans-serif;
  line-height:1.9; font-size:16.5px; letter-spacing:.02em;
}
.wrap{max-width:820px; margin:0 auto; padding:0 16px 80px}
header.hero{
  background:linear-gradient(160deg,var(--accent) 0%,#5a4580 100%);
  color:#fff; padding:38px 20px 30px; margin-bottom:22px;
}
header.hero .inner{max-width:820px;margin:0 auto}
header.hero h1{margin:0 0 8px; font-size:1.55rem; letter-spacing:.04em; font-weight:700}
header.hero .meta{opacity:.92; font-size:.85rem; line-height:1.7}
.card{
  background:var(--card); border:1px solid var(--line); border-radius:14px;
  padding:20px 18px; margin:0 0 18px;
}
h2{
  font-size:1.2rem; margin:2px 0 14px; padding-bottom:10px;
  border-bottom:2px solid var(--accent); color:var(--accent);
  letter-spacing:.03em;
}
h3{font-size:1.05rem; margin:22px 0 8px; color:var(--accent2)}
h4{font-size:.98rem; margin:16px 0 6px; color:var(--sub)}
p{margin:0 0 1.05em; text-align:justify}
ul,ol{padding-left:1.3em; margin:0 0 1em}
li{margin-bottom:.45em}
strong{color:var(--accent); font-weight:700}
hr{border:0; border-top:1px dashed var(--line); margin:22px 0}
blockquote{
  margin:0 0 1em; padding:10px 14px; background:var(--mark);
  border-left:3px solid var(--accent2); border-radius:0 8px 8px 0;
  font-size:.94rem; color:var(--sub);
}
code{background:var(--mark); padding:1px 5px; border-radius:4px; font-size:.9em}
pre{background:var(--mark); padding:12px; border-radius:8px; overflow-x:auto; font-size:.82rem}
/* 目次 */
nav.toc{position:sticky; top:0; z-index:5}
nav.toc details{
  background:var(--card); border:1px solid var(--line);
  border-radius:12px; margin-bottom:18px;
}
nav.toc summary{
  padding:13px 16px; font-weight:700; cursor:pointer; color:var(--accent);
  list-style:none; border-radius:12px;
}
nav.toc summary::-webkit-details-marker{display:none}
nav.toc summary::after{content:" ▾"; font-size:.8em}
nav.toc ol{margin:0; padding:0 16px 14px 32px}
nav.toc a{color:var(--ink); text-decoration:none; border-bottom:1px dotted var(--line)}
/* 折りたたみカード */
details.item{
  background:var(--card); border:1px solid var(--line);
  border-radius:12px; margin-bottom:10px; overflow:hidden;
}
details.item>summary{
  padding:14px 16px; cursor:pointer; font-weight:600; list-style:none;
  display:flex; align-items:center; gap:10px;
}
details.item>summary::-webkit-details-marker{display:none}
details.item>summary::before{content:"＋"; color:var(--accent); font-weight:700}
details.item[open]>summary::before{content:"−"}
details.item .body{padding:2px 16px 18px; border-top:1px solid var(--line)}
.badge{
  display:inline-block; font-size:.7rem; padding:2px 8px; border-radius:999px;
  background:var(--mark); color:var(--sub); border:1px solid var(--line);
  margin-left:auto; white-space:nowrap;
}
.section-lead{color:var(--sub); font-size:.9rem; margin:-6px 0 14px}
/* mts5.68: 相談内容の参照行（全文は冒頭の 1 回だけ） */
li.consult-ref{color:var(--sub)}
a.consult-ref{color:var(--accent); text-decoration:underline dotted}
footer.fin{
  margin-top:34px; padding:18px; border-radius:12px;
  background:var(--mark); color:var(--sub); font-size:.82rem; line-height:1.8;
}
.totop{
  display:block; text-align:center; margin:26px 0 0;
  color:var(--accent); text-decoration:none; font-size:.85rem;
}
.fortune-image-container{ text-align:center; margin:18px 0 22px 0; }
.fortune-visual{ max-width:100%; height:auto; border-radius:10px; box-shadow:0 8px 20px rgba(0,0,0,0.4); border:1px solid #D4AF37; }
.fortune-image-caption{ font-size:0.85em; color:#a0a0a0; margin-top:6px; font-style:italic; }
.fortune-image-grid{ display:flex; flex-wrap:wrap; gap:10px; justify-content:center; margin:18px 0 22px 0; }
.fortune-image-item{ flex:0 1 140px; max-width:32%; text-align:center; }
.fortune-image-item img{ width:100%; height:auto; border-radius:8px; box-shadow:0 4px 12px rgba(0,0,0,0.3); border:1px solid #D4AF37; }
.fortune-image-item .fortune-image-caption{ font-size:0.72em; color:#a0a0a0; margin-top:4px; font-style:italic; line-height:1.4; word-break:break-word; }
.fortune-no-image{ border:1px dashed #8a8a8a; border-radius:8px; padding:10px 12px; margin:10px 0; color:#9a9a9a; font-size:0.85em; }
@media (max-width:600px){ .fortune-image-item{ flex:0 1 44%; max-width:44%; } }
/* mts5.22: トーン切替バー（Stage D） */
.tonebar{ position:sticky; top:0; z-index:50; display:flex; gap:6px; flex-wrap:wrap; align-items:center;
  padding:8px 14px; background:rgba(247,243,235,0.95); backdrop-filter:blur(6px);
  border-bottom:1px solid #e2d9c8; }
.tonebar .tb-label{ font-size:12px; color:#8a7f6d; margin-right:2px; }
.tb-btn{ border:1px solid #d8cbb4; background:#fff; color:#5c5244; border-radius:999px;
  padding:5px 12px; font-size:12px; cursor:pointer; line-height:1.4; }
.tb-btn:active{ transform:scale(0.97); }
.tb-btn[aria-pressed="true"]{ background:#7a5c3e; border-color:#7a5c3e; color:#fff; }
.tone-note{ margin:8px 14px 0; padding:6px 10px; border:1px dashed #cbb99a; border-radius:8px;
  font-size:12px; color:#8a6d3b; background:#faf6ee; display:none; }
/* mts5.46: 統合レポート内の表示切替。別カードを作らず、縦スクロールを増やさない。 */
.synthesis-switcher{ display:flex; flex-wrap:wrap; gap:6px; align-items:center;
  margin:0 0 7px; }
.synthesis-switcher .switch-label{ font-size:12px; color:#8a7f6d; margin-right:2px; }
.synthesis-view-btn{ flex:0 0 auto; white-space:nowrap; }
.synthesis-note{ margin:0 0 10px; padding:6px 9px; border-left:3px solid #d8cbb4;
  background:#faf6ee; font-size:12px; color:#6b6152; line-height:1.6; }
@media print{
  header.hero{background:#5a4580 !important; -webkit-print-color-adjust:exact}
  nav.toc{display:none} details.item{break-inside:avoid}
  details.item[open]>summary::before,details.item>summary::before{content:""}
  .tonebar,.tone-note,.synthesis-switcher,.synthesis-note{display:none}
}
"""


# ---------------------------------------------------------------
# 最小限の Markdown → HTML（外部依存なし）
# ---------------------------------------------------------------
def md_to_html(md: str) -> str:
    """本文用の簡易Markdown変換。見出し・箇条書き・強調・引用・水平線に対応。"""
    md = md.replace("\r\n", "\n")
    out, in_ul, in_ol, in_pre = [], False, False, False

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    def inline(t: str) -> str:
        t = html.escape(t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"(?<!\*)\*([^*\\n]+)\*(?!\*)", r"<em>\1</em>", t)
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        return t

    for line in md.split("\n"):
        st = line.strip()
        if st.startswith("```"):
            close_lists()
            out.append("</pre>" if in_pre else "<pre>")
            in_pre = not in_pre
            continue
        if in_pre:
            out.append(html.escape(line))
            continue
        if not st:
            close_lists()
            continue
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", st):
            close_lists()
            out.append("<hr>")
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", st)
        if m:
            close_lists()
            lv = min(6, len(m.group(1)) + 2)   # 文書内は h3 以降を使う
            out.append(f"<h{lv}>{inline(m.group(2))}</h{lv}>")
            continue
        if st.startswith(">"):
            close_lists()
            out.append(f"<blockquote>{inline(st.lstrip('> '))}</blockquote>")
            continue
        m = re.match(r"^(\d+)[.)]\s+(.*)$", st)
        if m:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{inline(m.group(2))}</li>")
            continue
        if re.match(r"^([-*]\s+|・\s*)", st):
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            item = re.sub(r"^([-*]\s+|・\s*)", "", st)
            out.append(f"<li>{inline(item)}</li>")
            continue
        if st.startswith("|"):          # 表は簡易にそのまま出す
            close_lists()
            out.append(f"<p>{inline(st)}</p>")
            continue
        close_lists()
        out.append(f"<p>{inline(st)}</p>")

    close_lists()
    if in_pre:
        out.append("</pre>")
    return "\n".join(out)


# 各ファイル末尾に付く免責の書き出し（種類が複数ある）
#   個別占術  : 「※ 本結果はエンターテインメント…」
#   中間/統合 : 「※ 本レポートはエンターテインメント…」
_FOOTER_MARKS = ("※ 本結果はエンターテインメント",
                 "※ 本レポートはエンターテインメント")


def _strip_footer(md: str) -> str:
    """各ファイル末尾の免責を落とす（HTML全体で1回だけ出すため）。

    ★BUG-17（2026-08-18 実機で判明）: 「本レポートは」しか見ておらず、
      個別占術の「本結果は」を落とせていなかった。結果、1枚HTMLに
      免責が67回も現れていた（本来1回）。両方の書き出しに対応する。
    """
    idx = [md.find(m) for m in _FOOTER_MARKS]
    idx = [i for i in idx if i > 0]
    if not idx:
        return md.rstrip()
    i = min(idx)
    cut = md.rfind("---", 0, i)
    return md[:cut if cut > 0 else i].rstrip()


def _title_of(md: str, fallback: str) -> str:
    m = re.search(r"^#\s+(.+)$", md, re.M)
    return m.group(1).strip() if m else fallback


# ---------------------------------------------------------------
# mts5.68: 相談内容の重複表示を HTML 整形段階で 1 回にまとめる
#   実機（mts5.67・相談 1,703字）では相談文が HTML に 54 回（統合レポート冒頭 1 回＋
#   個別占術 53 件の「■ 使用した入力」）現れ、約 9.2 万字が重複していた。
#   .md の原本（results/*.md・synthesis_report.md）は変えず、HTML 化のときに
#   **最初の 1 回だけ全文**を残し、以降は 1 行の参照（冒頭へのリンク）に置き換える。
# ---------------------------------------------------------------
#: 個別占術の「■ 使用した入力」の相談内容の行（pipeline._write_result_md が書く形）
_CONSULT_ITEM_RE = re.compile(r"^- 相談内容：(?P<body>.*?)(?=\n\n|\n## |\Z)", re.M | re.S)
#: 統合レポート冒頭の「**ご相談**: …」段落（synthesis.write_synthesis_file が書く形）
_CONSULT_SYN_RE = re.compile(r"^\*\*ご相談\*\*: (?P<body>.*?)(?=\n\n|\Z)", re.M | re.S)
#: 置き換え後の 1 行（md のまま。HTML 化後に _linkify_consult_ref でリンクにする）
CONSULT_REF_TEXT = "相談内容：冒頭の「ご相談」のとおり（全文は省略）"
#: 「相談なし」の印（今日の運勢モード）は短いので置き換えない
_CONSULT_PLACEHOLDER_PREFIX = "（なし"


def dedupe_consultation_md(md: str, seen: dict) -> str:
    """個別占術 md の「- 相談内容：…」を、2 回目以降は 1 行の参照に置き換える（mts5.68）。

    Args:
        md:   results/*.md（フッタ除去後）の本文
        seen: 文書全体で共有する状態 ``{"shown": bool, "replaced": int, "saved": int}``。
              ``shown`` が False のうちは全文を残して True にする（＝最初の 1 回）。
    Returns: 置き換え後の md（相談なし・該当行なしのときは不変）
    """
    m = _CONSULT_ITEM_RE.search(md)
    if not m:
        return md
    body = (m.group("body") or "").strip()
    if not body or body.startswith(_CONSULT_PLACEHOLDER_PREFIX):
        return md                                   # 今日の運勢モード等＝短い印は残す
    if not seen.get("shown"):
        seen["shown"] = True                        # 最初の 1 回＝全文を残す
        return md
    seen["replaced"] = int(seen.get("replaced") or 0) + 1
    seen["saved"] = int(seen.get("saved") or 0) + len(body)
    return md[:m.start()] + "- " + CONSULT_REF_TEXT + md[m.end():]


def note_consultation_in_synthesis(md: str, seen: dict) -> None:
    """統合レポート冒頭の「**ご相談**」があれば『表示済み』にする（＝最初の 1 回・mts5.68）。"""
    m = _CONSULT_SYN_RE.search(md)
    if m and (m.group("body") or "").strip():
        seen["shown"] = True


def _linkify_consult_ref(frag: str) -> str:
    """HTML 化した参照行の「冒頭の「ご相談」」を統合レポートへのリンクにする（mts5.68）。"""
    esc = html.escape(CONSULT_REF_TEXT)
    if esc not in frag:
        return frag
    linked = esc.replace("冒頭の「ご相談」",
                         '<a class="consult-ref" href="#synthesis">冒頭の「ご相談」</a>')
    return frag.replace(f"<li>{esc}</li>", f'<li class="consult-ref">{linked}</li>')


def _drop_h1(md: str) -> str:
    return re.sub(r"^#\s+.+$", "", md, count=1, flags=re.M).lstrip()


DISCLAIMER = (
    "※ 本レポートはエンターテインメント目的のシミュレーションであり、"
    "事実を表すものではありません。<br>"
    "※ 医療・法律・投資・人生の重大な決定には利用しないでください。<br>"
    "※ 疑似体験モードの内容は、体系の語彙・形式を模した創作文章です。"
)


import base64 as _b64
import json as _json
import random as _random


def _encode_image_to_base64(image_path: Path) -> str:
    """画像ファイルをData URI形式のBase64文字列に変換（外部依存なし）"""
    ext = image_path.suffix.lower().replace(".", "")
    mime = "image/webp" if ext == "webp" else (f"image/{ext}" if ext != "jpg" else "image/jpeg")
    with open(image_path, "rb") as _f:
        _enc = _b64.b64encode(_f.read()).decode("utf-8")
    return f"data:{mime};base64,{_enc}"


def _resolve_assets_root(images_dir: Path | None) -> Path | None:
    """images_dir から assets/images ルートを解決（後方互換）"""
    if images_dir is None:
        return None
    p = Path(images_dir)
    if not p.exists():
        return None
    # すでに assets/images 自体が渡された場合
    if (p / "M27_tarot").is_dir() or (p / "M23_meihua").is_dir():
        # p が assets/images
        return p
    # p が M23_meihua 等の個別ディレクトリの場合 -> 親が assets/images
    if p.parent.name == "images" and (p.parent / "M27_tarot").is_dir():
        return p.parent
    if p.name == "M23_meihua" and p.parent.name == "images":
        return p.parent
    # フォールバック: 2階層上を assets/images とみなす
    # 例: assets/images/M23_meihua -> parent
    if p.is_dir():
        # try to find assets/images by walking up
        cur = p
        for _ in range(3):
            if (cur / "M27_tarot").is_dir() or (cur / "M23_meihua").is_dir():
                return cur
            if cur.name == "images" and cur.parent.name == "assets":
                return cur
            cur = cur.parent
    return p.parent if p.is_dir() else None


def _pick_smaller_image(base_without_ext: Path) -> Path | None:
    """同一ベース名の .webp と .jpg の小さい方を選ぶ（Turn10）"""
    webp = base_without_ext.with_suffix(".webp")
    jpg = base_without_ext.with_suffix(".jpg")
    # also try .jpeg
    jpg2 = base_without_ext.with_suffix(".jpeg")
    candidates = []
    for cand in [webp, jpg, jpg2]:
        if cand.exists():
            candidates.append(cand)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    # 複数ある場合、サイズが小さい方を採用
    return min(candidates, key=lambda p: p.stat().st_size)



def _trace_image(card: dict, path, note: str) -> None:
    """画像解決のトレース（FORTUNE_IMAGE_TRACE=1 のときだけ出力／mts4.8）

    本番で「キャプションのカードと画像ファイルが一致しているか」を後から検証できるようにする。
    """
    import os as _os
    if _os.environ.get("FORTUNE_IMAGE_TRACE") != "1":
        return
    try:
        pos = card.get("position") or ""
        name = card.get("name_en") or card.get("name_ja") or ""
        print(f"[IMG] {note}: {pos} {name} -> {path.name if path else 'なし'}")
    except Exception:
        pass


_TAROT_RANK_WORD = {"Ace": "Ace", "Two": "02", "Three": "03", "Four": "04", "Five": "05",
                    "Six": "06", "Seven": "07", "Eight": "08", "Nine": "09", "Ten": "10",
                    "Page": "Page", "Knight": "Knight", "Queen": "Queen", "King": "King"}

_DIR_FILE_CACHE: dict[str, list[Path]] = {}


def _dir_image_files(assets_dir: Path) -> list[Path]:
    """ディレクトリ内の画像ファイル一覧（走査はキャッシュ。消えたファイルは再走査で反映）"""
    key = str(assets_dir)
    files = _DIR_FILE_CACHE.get(key)
    if files is None or any(not f.exists() for f in files):
        files = sorted(
            list(assets_dir.glob("*.webp")) + list(assets_dir.glob("*.jpg"))
            + list(assets_dir.glob("*.jpeg")) + list(assets_dir.glob("*.png")))
        _DIR_FILE_CACHE[key] = files
    return files


def _norm_token(text: str) -> str:
    """比較用の正規化（小文字化・英数以外を除去）: 12_Hanged_Man -> 12hangedman"""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _leading_number(stem: str) -> int | None:
    """ファイル名先頭の番号（02_of_Swords -> 2 / 12_Hanged_Man -> 12）"""
    m = re.match(r"^(\d{1,2})(?![0-9])", stem)
    return int(m.group(1)) if m else None


def _tarot_name_bases(card: dict) -> list[str]:
    """カード名から想定されるファイル名（拡張子なし）を優先順に返す"""
    name_en = (card.get("name_en") or "").strip()
    bases: list[str] = []
    parts = name_en.split(" of ")
    if len(parts) == 2:                                    # 小アルカナ: 04_of_Swords 等
        rank, suit = parts
        bases.append(f"{_TAROT_RANK_WORD.get(rank, rank)}_of_{suit}")
        bases.append(f"{rank}_of_{suit}")
    if name_en:                                            # 大アルカナ: Hanged_Man / HangedMan 等
        plain = name_en.replace("The ", "").strip()
        bases.append(plain.replace(" ", "_"))
        bases.append(plain.replace(" ", ""))
    return bases


def _find_tarot_image_file(card: dict, assets_dir: Path) -> Path | None:
    """カードdictから画像ファイルを解決する（mts4.8: 名前優先・番号は検証付き）

    mts4.7 までは card_id による機械的な番号引きを行っていたため、次の2つの誤充当があった。
      (1) 小アルカナの card_id は「デッキ内の並び順」であり実カード番号ではない
      (2) 大アルカナでも、card_id が並び順になっている場合に、同じ番号で始まる
          小アルカナのファイル（例: 02_of_Swords）を拾ってしまう
      さらにマルセイユは 08=Justice / 11=Strength と RWS で番号体系が異なる。
    本版は
      1) ファイル名の完全一致（rank_of_suit / カード名）
      2) 正規化一致・末尾一致（12_Hanged_Man、02_HighPriestess など）
      3) カード名が無い場合に限り、大アルカナ番号での一致
    の順に解決し、該当が無ければ None を返す（誤った画像より欠落を選ぶ）。
    """
    try:
        files = _dir_image_files(assets_dir)
        if not files:
            return None
        name_en = (card.get("name_en") or "").strip()
        nname = _norm_token(name_en.replace("The ", ""))
        true_no = None
        if card.get("arcana") == "major" and card.get("card_id") is not None:
            try:
                n = int(card["card_id"])
                if 0 <= n <= 21:
                    true_no = n
            except Exception:
                true_no = None
        bases = _tarot_name_bases(card)
        nbases = {_norm_token(b) for b in bases if b}
        lower_bases = {b.lower() for b in bases if b}

        scored: list[tuple[int, Path]] = []
        for f in files:
            stem = f.stem
            ns = _norm_token(stem)
            score = 0
            if stem.lower() in lower_bases:                      # 完全一致
                score = 100
            elif ns and ns in nbases:                            # 正規化一致
                score = 95
            elif nname and len(nname) >= 6 and ns.endswith(nname):
                score = 80
            elif nname and 4 <= len(nname) < 6 and ns.endswith(nname):
                score = 70
            elif nname and len(nname) == 3 and ns.endswith(nname):
                score = 60
            elif not nname and true_no is not None and _leading_number(stem) == true_no                     and not re.search(r"[A-Za-z]", stem):
                score = 50                                          # 名前の無い番号のみの命名
            if score == 0:
                continue
            if true_no is not None and _leading_number(stem) == true_no:
                score += 10                                          # 番号も一致していれば優先
            scored.append((score, f))
        if not scored:
            _trace_image(card, None, "skip:no-image")
            return None
        best_score = max(sc for sc, _ in scored)
        cands = [f for sc, f in scored if sc == best_score]
        best = None
        for c in cands:
            alt = _pick_smaller_image(c.with_suffix("")) or c
            if best is None or alt.stat().st_size < best.stat().st_size:
                best = alt
        _trace_image(card, best, "resolved")
        return best
    except Exception:
        return None


def _find_lenormand_image_file(card: dict, assets_dir: Path) -> Path | None:
    """レノルマン: 先頭番号＋カード名で解決（mts4.8: 名前を検証して誤充当を防ぐ）"""
    try:
        no = card.get("card_id") or card.get("no") or card.get("kingwen_no")
        if not no:
            return None
        n = int(no)
        nname = _norm_token(card.get("name_en") or card.get("name_ja") or "")
        cands = [f for f in _dir_image_files(assets_dir) if _leading_number(f.stem) == n]
        if not cands:
            _trace_image(card, None, "skip:no-image")
            return None
        if nname:
            exact = [f for f in cands if _norm_token(f.stem).endswith(nname)]
            if exact:
                cands = exact
            else:
                cands = [f for f in cands if not re.search(r"[A-Za-z]", f.stem)]
                if not cands:
                    _trace_image(card, None, "skip:name-mismatch")
                    return None
        best = None
        for c in cands:
            alt = _pick_smaller_image(c.with_suffix("")) or c
            if best is None or alt.stat().st_size < best.stat().st_size:
                best = alt
        _trace_image(card, best, "resolved")
        return best
    except Exception:
        return None


def _find_cartomancy_image_file(card: dict, assets_dir: Path) -> Path | None:
    """カルトマンシー: ランク＋スートの完全一致で解決（mts4.8: 曖昧一致を採らない）"""
    try:
        suit = card.get("suit") or ""
        rank = card.get("rank") or ""
        suit_map = {"H": "Hearts", "D": "Diamonds", "C": "Clubs", "S": "Spades",
                    "Hearts": "Hearts", "Diamonds": "Diamonds", "Clubs": "Clubs", "Spades": "Spades"}
        rank_map = {"A": "Ace", "1": "Ace", "J": "Jack", "Q": "Queen", "K": "King",
                    "Jack": "Jack", "Queen": "Queen", "King": "King", "Ace": "Ace"}
        suit_full = suit_map.get(suit, suit)
        if rank in rank_map:
            rank_full = rank_map[rank]
        else:
            try:
                rank_full = f"{int(rank):02d}"
            except Exception:
                rank_full = str(rank)
        if not (rank_full and suit_full):
            return None
        want = _norm_token(f"{rank_full}_of_{suit_full}")
        cands = [f for f in _dir_image_files(assets_dir) if _norm_token(f.stem) == want]
        if not cands:
            _trace_image(card, None, "skip:no-image")
            return None
        best = None
        for c in cands:
            alt = _pick_smaller_image(c.with_suffix("")) or c
            if best is None or alt.stat().st_size < best.stat().st_size:
                best = alt
        _trace_image(card, best, "resolved")
        return best
    except Exception:
        return None


def _find_meihua_image_file(no: int, assets_dir: Path) -> Path | None:
    try:
        cands = list(assets_dir.glob(f"{int(no):02d}_*.jpg")) + list(assets_dir.glob(f"{int(no):02d}_*.webp")) + list(assets_dir.glob(f"{int(no):02d}_*.png"))
        if not cands:
            fb = assets_dir / "M23_meihua.jpg"
            if fb.exists():
                cands = [fb]
        if not cands:
            return None
        best = _pick_smaller_image(cands[0].with_suffix("")) or cands[0]
        for cand in cands:
            alt = _pick_smaller_image(cand.with_suffix(""))
            if alt and alt.stat().st_size < best.stat().st_size:
                best = alt
        return best
    except Exception:
        return None

def _meihua_image_tag(person_dir: Path, assets_root: Path | None) -> str:
    """M23_meihua: 本卦・変卦・互卦の全てをグリッド表示（見つからなければ空文字）"""
    if assets_root is None:
        return ""
    try:
        _raw = person_dir / "results" / "M23_meihua_raw.json"
        if not _raw.exists():
            return ""
        _data = _json.loads(_raw.read_text(encoding="utf-8"))
        _calc = (_data.get("result") or {}).get("calc") or _data.get("calc") or {}
        _dir = assets_root / "M23_meihua"
        if not _dir.is_dir():
            return ""
        # 収集: 本卦・変卦・互卦
        hexes = []
        for key, label in [("ben_hexagram","本卦"),("derived_hexagram","変卦"),("mutual_hexagram","互卦")]:
            hx = _calc.get(key) or {}
            no = hx.get("kingwen_no")
            name = hx.get("name_ja") or ""
            if no:
                hexes.append((int(no), name, label))
        # フォールバック: 旧形式でbenしかない場合でも1枚は表示
        if not hexes:
            _ben = _calc.get("ben_hexagram") or {}
            no = _ben.get("kingwen_no")
            name = _ben.get("name_ja") or ""
            if no:
                hexes.append((int(no), name, "本卦"))
        if not hexes:
            return ""
        items = []
        found = []      # mts5.31: 実際に解決できた1件（先頭要素の再探索は画像を落とす）
        for no, name, label in hexes:
            img_path = _find_meihua_image_file(no, _dir)
            if not img_path:
                continue
            b64 = _encode_image_to_base64(img_path)
            alt = f"梅花易数 {name}（{no:02d}）{label}" if name else f"梅花易数 {no:02d} {label}"
            cap = f"【梅花易数】{label}：{name}（{no:02d}）"
            found.append((b64, alt, name, label))
            items.append(f'<div class="fortune-image-item"><img src="{b64}" alt="{html.escape(alt)}" loading="lazy" /><div class="fortune-image-caption">{html.escape(cap)}</div></div>')
        if not items:
            return ""
        if len(items)==1:
            # 1枚は従来の大きな表示（解決済みの1件を使う＝取りこぼし防止）
            b64, alt, name, label = found[0]
            return f'<div class="fortune-image-container"><img src="{b64}" alt="{html.escape(alt)}" class="fortune-visual" loading="lazy" /><div class="fortune-image-caption">【梅花易数】{label}：{name} の象意図（パブリックドメイン B方式）</div></div>'
        return f'<div class="fortune-image-grid">{"".join(items)}</div>'
    except Exception:
        return ""

def _generic_lenormand_tag(person_dir: Path, assets_root: Path | None) -> str:
    """M27_lenormand 全枚表示（3枚等）"""
    if assets_root is None:
        return ""
    try:
        raw = person_dir / "results" / "M27_lenormand_raw.json"
        if not raw.exists():
            return ""
        data = _json.loads(raw.read_text(encoding="utf-8"))
        calc = (data.get("result") or {}).get("calc") or data.get("calc") or {}
        cards = calc.get("cards") or data.get("cards") or []
        if not cards:
            cards = data.get("result", {}).get("cards", [])
        if not cards:
            return ""
        _dir = assets_root / "M27_lenormand"
        if not _dir.is_dir():
            return ""
        items = []
        found = []
        for card in cards:
            img_path = _find_lenormand_image_file(card, _dir)
            if not img_path:
                continue
            b64 = _encode_image_to_base64(img_path)
            name = card.get("name_ja") or card.get("name_en") or ""
            pos = card.get("position") or ""
            no = card.get("card_id") or ""
            alt = f"レノルマン {name}（{no}）{pos}" if name else f"レノルマン {no}"
            cap = f"【レノルマン】{pos} {name}" if pos else f"【レノルマン】{name}"
            cap = cap.strip()
            found.append((b64, name, no))
            items.append(f'<div class="fortune-image-item"><img src="{b64}" alt="{html.escape(alt)}" loading="lazy" /><div class="fortune-image-caption">{html.escape(cap)}</div></div>')
        if not items:
            return ""
        if len(items)==1:
            # 単独は大きく（解決済みの1件を使う＝取りこぼし防止）
            b64, name, no = found[0]
            alt = f"レノルマン {name}（{no:02d}）" if name else f"レノルマン {no}"
            return f'<div class="fortune-image-container"><img src="{b64}" alt="{html.escape(alt)}" class="fortune-visual" loading="lazy" /><div class="fortune-image-caption">【レノルマン】{name} の象意</div></div>'
        return f'<div class="fortune-image-grid">{"".join(items)}</div>'
    except Exception:
        return ""

def _generic_tarot_tag(person_dir: Path, assets_root: Path | None, slug: str) -> str:
    """M27_tarot / M27_marseille / M27_urbantarot 全枚表示（mts5.13 で urbantarot 対応）"""
    if assets_root is None:
        return ""
    try:
        raw_name = f"M27_{slug}_raw.json"
        raw = person_dir / "results" / raw_name
        if not raw.exists():
            return ""
        data = _json.loads(raw.read_text(encoding="utf-8"))
        calc = (data.get("result") or {}).get("calc") or data.get("calc") or {}
        if slug == "urbantarot":
            cards = (calc.get("tarot") or {}).get("cards") or calc.get("cards") or []
        else:
            cards = calc.get("cards") or data.get("cards") or []
        if not cards:
            return ""
        dir_name = "M27_tarot" if slug in ("tarot", "urbantarot") else "M27_marseille"
        _dir = assets_root / dir_name
        if not _dir.is_dir():
            return ""
        items = []
        found = []
        for card in cards:
            img_path = _find_tarot_image_file(card, _dir)
            if not img_path:
                continue
            b64 = _encode_image_to_base64(img_path)
            name_en = card.get("name_en") or card.get("name_ja") or ""
            pos = card.get("position") or ""
            upright = card.get("upright")
            rev_note = "（正位置）" if upright is True else ("（逆位置）" if upright is False else "")
            label = f"{name_en}{rev_note}"
            cap = f"{pos} {label}".strip() if pos else label
            prefix = "マルセイユ" if slug=="marseille" else ("現代タロット" if slug=="urbantarot" else "タロット")
            found.append((b64, label))
            items.append(f'<div class="fortune-image-item"><img src="{b64}" alt="{html.escape(label)}" loading="lazy" /><div class="fortune-image-caption">【{prefix}】{html.escape(cap)}</div></div>')
        if not items:
            return ""
        if len(items)==1:
            # 単独は大きく表示（解決済みの1件を使う＝取りこぼし防止）
            b64, label = found[0]
            prefix = "マルセイユ" if slug=="marseille" else "タロット"
            caption = f"【{prefix}】{label} の象意"
            return f'<div class="fortune-image-container"><img src="{b64}" alt="{html.escape(label)}" class="fortune-visual" loading="lazy" /><div class="fortune-image-caption">{caption}</div></div>'
        return f'<div class="fortune-image-grid">{"".join(items)}</div>'
    except Exception:
        return ""

def _generic_cartomancy_tag(person_dir: Path, assets_root: Path | None) -> str:
    """M27_cartomancy 全枚表示（5枚等）"""
    if assets_root is None:
        return ""
    try:
        raw = person_dir / "results" / "M27_cartomancy_raw.json"
        if not raw.exists():
            return ""
        data = _json.loads(raw.read_text(encoding="utf-8"))
        calc = (data.get("result") or {}).get("calc") or data.get("calc") or {}
        cards = calc.get("cards") or data.get("cards") or []
        if not cards:
            return ""
        _dir = assets_root / "M27_cartomancy"
        if not _dir.is_dir():
            return ""
        items = []
        found = []
        for card in cards:
            img_path = _find_cartomancy_image_file(card, _dir)
            if not img_path:
                continue
            b64 = _encode_image_to_base64(img_path)
            name_ja = card.get("name_ja") or f"{card.get('suit')} {card.get('rank')}"
            pos = card.get("position") or ""
            alt = f"{name_ja} {pos}".strip()
            cap = f"【カルトマンシー】{pos} {name_ja}".strip() if pos else f"【カルトマンシー】{name_ja}"
            found.append((b64, name_ja))
            items.append(f'<div class="fortune-image-item"><img src="{b64}" alt="{html.escape(alt)}" loading="lazy" /><div class="fortune-image-caption">{html.escape(cap)}</div></div>')
        if not items:
            return ""
        if len(items)==1:
            # mts5.31: 解決済みの1件を使う（取りこぼし防止）
            b64, name_ja = found[0]
            return f'<div class="fortune-image-container"><img src="{b64}" alt="{html.escape(name_ja)}" class="fortune-visual" loading="lazy" /><div class="fortune-image-caption">【カルトマンシー】{name_ja} の象意</div></div>'
        return f'<div class="fortune-image-grid">{"".join(items)}</div>'
    except Exception:
        return ""

# ---------------------------------------------------------------- mts4.9 追加3ツール
OMIKUJI_POSES = ["a", "b", "c", "d", "e", "f", "g", "h"]


def _find_kipper_image_file(card: dict, assets_dir: Path) -> Path | None:
    """M27_kipper: 番号＋カード名で解決（ファイル名は NN_NameNoSpaces.webp）"""
    try:
        no = card.get("card_id")
        if no is None:
            no = card.get("no")
        no = int(no) if no is not None else None
        name = (card.get("name_en") or "").strip()
        if no is None:
            _trace_image(card, None, "skip:no-number")
            return None
        cands = [f for f in _dir_image_files(assets_dir) if _leading_number(f.stem) == no]
        if not cands:
            _trace_image(card, None, "skip:no-image")
            return None
        if name:
            want = _norm_token(name)
            exact = [f for f in cands if _norm_token(f.stem).endswith(want)]
            if exact:
                cands = exact
            else:
                cands = [f for f in cands if not re.search(r"[A-Za-z]", f.stem)]
                if not cands:
                    _trace_image(card, None, "skip:name-mismatch")
                    return None
        best = None
        for c in cands:
            alt = _pick_smaller_image(c.with_suffix("")) or c
            if best is None or alt.stat().st_size < best.stat().st_size:
                best = alt
        _trace_image(card, best, "resolved")
        return best
    except Exception:
        return None


def _find_rune_image_file(card: dict, assets_dir: Path) -> Path | None:
    """M27_runes: **石の名（Fehu 等）で解決**（ファイル名は NN_Name.webp＝エルダーフサルク順）

    注意（mts5.4 で修正）: ルーンの card_id は「抽選順（1,2,3…）」であり、
    runes_24.json の並び順（01_Fehu … ）を意味しない。名前で引かずに card_id で引くと
    別の石の画像を充当してしまう（例: 位置1 ウンジョ に 01_Fehu を表示）。
    名前が一致しない場合はスキップする（誤充当より欠落を選ぶ）。
    """
    try:
        name = (card.get("name_en") or card.get("name_ja") or "").strip()
        if name:
            want = _norm_token(name)
            exact = [f for f in _dir_image_files(assets_dir)
                     if _norm_token(f.stem).endswith(want)]
            if not exact:
                _trace_image(card, None, "skip:name-mismatch")
                return None
            cands = exact
        else:
            _trace_image(card, None, "skip:no-name")
            return None
        best = None
        for c in cands:
            alt = _pick_smaller_image(c.with_suffix("")) or c
            if best is None or alt.stat().st_size < best.stat().st_size:
                best = alt
        _trace_image(card, best, "resolved")
        return best
    except Exception:
        return None


def _omikuji_level_index(level: str) -> int | None:
    """段階名 → 1始まりの番号（data/omikuji_12.json の順序が正本）"""
    try:
        levels = _json.loads((_data_dir() / "omikuji_12.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    for i, row in enumerate(levels, 1):
        if row.get("level") == level:
            return i
    return None


def _data_dir() -> Path:
    """data ディレクトリの解決（mts5.31: 共通ローダと同じ解決順にする）

    以前は cwd 依存の `Path("data")` を候補・最終結果にしていたため、Kaggle
    （cwd=/kaggle/working）では**存在しないパス**を返し得た。fortunelib.data は
    環境変数→パッケージ相対→/kaggle/input 再帰探索の順で解決するので、それに合わせる。
    """
    here = Path(__file__).resolve().parent.parent / "data"
    if here.is_dir():
        return here
    try:
        from .data import DATA_DIR as _DD
        if Path(_DD).is_dir():
            return Path(_DD)
    except Exception:
        pass
    for cand in (Path("data"), Path("/kaggle/input/fortune-dataset/data")):
        if (cand / "omikuji_12.json").exists():
            return cand
    return Path("data")


def _stable_index(text: str, mod: int) -> int:
    """プロセス間で安定したハッシュ（Pythonのhash()は実行ごとに揺れるため使わない）"""
    import zlib
    return zlib.crc32(text.encode("utf-8")) % max(1, mod)


def _find_omikuji_image_file(level_no: int, pose_idx: int, assets_dir: Path,
                             special: str | None = None) -> Path | None:
    """M28_omikuji: 段階番号で引き、特別柄 → ポーズ順 → 先頭 の順に選ぶ"""
    try:
        cands = [f for f in _dir_image_files(assets_dir)
                 if f.stem.startswith(f"{level_no:02d}_")]
        if not cands:
            return None
        if special:
            spec = [f for f in cands if special in f.stem]
            if spec:
                return spec[min(pose_idx, len(spec) - 1)]
        pose = OMIKUJI_POSES[pose_idx % len(OMIKUJI_POSES)]
        pool = [f for f in cands if f.stem.endswith(f"_{pose}")] or cands
        best = None
        for c in pool:
            alt = _pick_smaller_image(c.with_suffix("")) or c
            if best is None or alt.stat().st_size < best.stat().st_size:
                best = alt
        return best
    except Exception:
        return None



def _ascii_name_head(name_en: str) -> str:
    """「Michael・守護と浄化」→「Michael」。ASCIIが無ければ空文字を返す"""
    head = re.split(r"[・/]", name_en or "")[0].strip()
    if not re.search(r"[A-Za-z]", head):
        return ""
    return re.sub(r"[^A-Za-z0-9\- ]", "", head).strip()


def _find_generated_deck_image(card: dict, assets_dir: Path, *, ascii_head: bool = False,
                               strict_name: bool = True) -> Path | None:
    """生成デッキ共通の解決: 先頭番号＝カード番号、名前で検証（不一致はスキップ＝誤充当防止）"""
    try:
        no = card.get("card_id")
        if no is None:
            no = card.get("no")
        name = (card.get("name_en") or "").strip()
        if ascii_head:
            name = _ascii_name_head(name)
        if no is None:
            _trace_image(card, None, "skip:no-number")
            return None
        no = int(no)
        cands = [f for f in _dir_image_files(assets_dir) if _leading_number(f.stem) == no]
        if not cands:
            _trace_image(card, None, "skip:no-image")
            return None
        if name:
            want = _norm_token(name)
            exact = [f for f in cands if _norm_token(f.stem).endswith(want)]
            if exact:
                cands = exact
            elif strict_name:
                _trace_image(card, None, "skip:name-mismatch")
                return None
        best = None
        for c in cands:
            alt = _pick_smaller_image(c.with_suffix("")) or c
            if best is None or alt.stat().st_size < best.stat().st_size:
                best = alt
        _trace_image(card, best, "resolved")
        return best
    except Exception:
        return None


def _find_oracle_image_file(card: dict, assets_dir: Path) -> Path | None:
    """M27_oracle: 番号＋カード名（New Beginning 等）で解決"""
    return _find_generated_deck_image(card, assets_dir)


def _find_angel_image_file(card: dict, assets_dir: Path) -> Path | None:
    """M27_angel: 番号＋ASCII英名の先頭語（「Michael・守護と浄化」→ Michael）で解決"""
    return _find_generated_deck_image(card, assets_dir, ascii_head=True)


# --------------------------------------------------------------- 生成デッキ（animal / genekeys）
def _data_json(name: str) -> dict:
    """data/ 配下の JSON を読む（画像の名前検証用・失敗時は空）"""
    try:
        return _json.loads((_data_dir() / name).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _find_numbered_deck_image(no: int, assets_dir: Path, want_name: str) -> Path | None:
    """番号＋英名で検証して解決（不一致はスキップ＝誤充当防止の共通方針）"""
    try:
        if not want_name:
            return None
        cands = [f for f in _dir_image_files(assets_dir) if _leading_number(f.stem) == int(no)]
        if not cands:
            return None
        want = _norm_token(want_name)
        exact = [f for f in cands if _norm_token(f.stem).endswith(want)]
        if not exact:
            return None
        best = None
        for c in exact:
            alt = _pick_smaller_image(c.with_suffix("")) or c
            if best is None or alt.stat().st_size < best.stat().st_size:
                best = alt
        return best
    except Exception:
        return None


def _animal_profile(no: int) -> dict:
    items = _data_json("animals_60_profiles.json").get("items") or []
    return next((i for i in items if int(i.get("no", -1)) == int(no)), {})


def _genekeys_archetype(gate: int) -> dict:
    items = _data_json("genekeys_64_archetypes.json").get("items") or []
    return next((i for i in items if int(i.get("no", -1)) == int(gate)), {})


def _genekeys_key_name(gate: int) -> str:
    keys = _data_json("genekeys_64.json").get("keys") or []
    return next((k.get("key_name", "") for k in keys if int(k.get("gate", -1)) == int(gate)), "")


def _find_animal_image_file(no: int, assets_dir: Path) -> Path | None:
    """M09_animal: 60番号＋英名（animals_60_profiles.json）で検証して解決"""
    return _find_numbered_deck_image(no, assets_dir, _animal_profile(no).get("animal_en", ""))


def _find_genekeys_image_file(gate: int, assets_dir: Path) -> Path | None:
    """M33_genekeys: ゲート番号＋アーキタイプSlug（genekeys_64_archetypes.json）で検証して解決"""
    return _find_numbered_deck_image(gate, assets_dir, _genekeys_archetype(gate).get("slug", ""))


# 干支の並び（画像側の番号＝子01 … 亥12）と英名（ファイル名の検証語）
_ETO_ORDER = [("子", "Rat"), ("丑", "Ox"), ("寅", "Tiger"), ("卯", "Rabbit"),
              ("辰", "Dragon"), ("巳", "Snake"), ("午", "Horse"), ("未", "Goat"),
              ("申", "Monkey"), ("酉", "Rooster"), ("戌", "Dog"), ("亥", "Boar")]


def _find_eto_image_file(shi: str, assets_dir: Path) -> Path | None:
    """M01_eto: 支（子・丑…）→ 番号＋英名（Rat 等）で検証して解決（不一致はスキップ）"""
    for i, (ja, en) in enumerate(_ETO_ORDER, start=1):
        if ja == shi:
            return _find_numbered_deck_image(i, assets_dir, en)
    return None


# 「星座＝白羊宮01 … 双魚宮12」の対応（画像側の番号はこの並び）
_SEIZA_ORDER = [("牡羊座", "Aries"), ("牡牛座", "Taurus"), ("双子座", "Gemini"), ("蟹座", "Cancer"),
                ("獅子座", "Leo"), ("乙女座", "Virgo"), ("天秤座", "Libra"), ("蠍座", "Scorpio"),
                ("射手座", "Sagittarius"), ("山羊座", "Capricorn"), ("水瓶座", "Aquarius"), ("魚座", "Pisces")]
_SEIZA_PERIOD = {"牡羊座": "3/21 - 4/19", "牡牛座": "4/20 - 5/20", "双子座": "5/21 - 6/21",
                 "蟹座": "6/22 - 7/22", "獅子座": "7/23 - 8/22", "乙女座": "8/23 - 9/22",
                 "天秤座": "9/23 - 10/23", "蠍座": "10/24 - 11/22", "射手座": "11/23 - 12/21",
                 "山羊座": "12/22 - 1/19", "水瓶座": "1/20 - 2/18", "魚座": "2/19 - 3/20"}
def _find_seiza_image_file(sign_ja: str, assets_dir: Path) -> Path | None:
    """M02_seiza: 星座和名 → 番号＋英名（Aries 等）で検証して解決"""
    for i, (ja, en) in enumerate(_SEIZA_ORDER, start=1):
        if ja == sign_ja:
            return _find_numbered_deck_image(i, assets_dir, en)
    return None


def _generic_seiza_tag(person_dir: Path, assets_root: Path | None) -> str:
    """M02_seiza（星座占い）: M02_seiza_raw.json の sign を 1枚大表示"""
    if assets_root is None:
        return ""
    try:
        raw = person_dir / "results" / "M02_seiza_raw.json"
        if not raw.exists():
            return ""
        data = _json.loads(raw.read_text(encoding="utf-8"))
        calc = data.get("calc") or (data.get("result") or {}).get("calc") or {}
        sign = calc.get("sign") or ""
        _dir = assets_root / "M02_seiza"
        if not sign or not _dir.is_dir():
            return ""
        img = _find_seiza_image_file(sign, _dir)
        if not img:
            return ""
        en = next((e for j, e in _SEIZA_ORDER if j == sign), "")
        cap = f"【星座占い】{sign}（{en}）{_SEIZA_PERIOD.get(sign, '')}".strip()
        return _single_image_tag(img, cap)
    except Exception:
        return ""


def _generic_eto_tag(person_dir: Path, assets_root: Path | None) -> str:
    """M01_eto（干支）: M01_eto_raw.json の result.calc から支を読み、1枚大表示（mts5.7 で追加）"""
    if assets_root is None:
        return ""
    try:
        raw = person_dir / "results" / "M01_eto_raw.json"
        if not raw.exists():
            return ""
        data = _json.loads(raw.read_text(encoding="utf-8"))
        calc = data.get("calc") or (data.get("result") or {}).get("calc") or {}
        shi = (calc.get("shi") or "").strip()
        animal = (calc.get("animal") or "").strip()
        if not shi:
            return ""
        _dir = assets_root / "M01_eto"
        if not _dir.is_dir():
            return ""
        img = _find_eto_image_file(shi, _dir)
        if not img:
            return ""
        en = next((e for j, e in _ETO_ORDER if j == shi), "")
        cap = f"【干支】{shi}（{en}）　{animal}　年柱 {calc.get('ganzhi', '')}".strip()
        return _single_image_tag(img, cap)
    except Exception:
        return ""


# ペンデュラム（M29_pendulum）: calc.answer → 画像番号＋英名（mts5.8 で追加）
_PENDULUM_ORDER = [("yes", "Yes", "肯定"), ("no", "No", "否定"),
                   ("neutral", "Neutral", "中立・保留")]


def _find_pendulum_image_file(answer: str, assets_dir: Path) -> Path | None:
    """M29_pendulum: answer（yes/no/neutral）→ 番号＋英名で検証して解決（不一致はスキップ）"""
    a = (answer or "").strip().lower()
    for i, (key, en, _ja) in enumerate(_PENDULUM_ORDER, start=1):
        if key == a:
            return _find_numbered_deck_image(i, assets_dir, en)
    return None


def _generic_pendulum_tag(person_dir: Path, assets_root: Path | None) -> str:
    """M29_pendulum: M29_pendulum_raw.json の calc.answer に対応する1枚を大表示（mts5.8）"""
    if assets_root is None:
        return ""
    try:
        raw = person_dir / "results" / "M29_pendulum_raw.json"
        if not raw.exists():
            return ""
        data = _json.loads(raw.read_text(encoding="utf-8"))
        calc = (data.get("result") or {}).get("calc") or data.get("calc") or {}
        answer = (calc.get("answer") or "").strip()
        if not answer:
            return ""
        _dir = assets_root / "M29_pendulum"
        if not _dir.is_dir():
            return ""
        img = _find_pendulum_image_file(answer, _dir)
        if not img:
            return ""
        key = answer.lower()
        en = next((e for k, e, _j in _PENDULUM_ORDER if k == key), "")
        ja = next((j for k, _e, j in _PENDULUM_ORDER if k == key), "")
        cap = f"【ペンデュラム】{ja}（{en}）".strip()
        return _single_image_tag(img, cap)
    except Exception:
        return ""


def _generic_crystalball_tag(person_dir: Path, assets_root: Path | None) -> str:
    """M30_crystalball: 情景1枚を大表示（calc を持たない占術のため固定の1枚。mts5.8）"""
    if assets_root is None:
        return ""
    try:
        raw = person_dir / "results" / "M30_crystalball_raw.json"
        if not raw.exists():
            return ""
        _dir = assets_root / "M30_crystalball"
        if not _dir.is_dir():
            return ""
        img = _find_numbered_deck_image(1, _dir, "Scrying")
        if not img:
            return ""
        return _single_image_tag(img, "【水晶玉占い】水晶玉（Scrying）")
    except Exception:
        return ""


# クリスタル・ヒーリング（M30_crystal）＆ パワーストーン（M12_stone）共有プール
# mts5.60: 石の表は `fortunelib/stones.py` を**唯一の正本**にした（プロンプトの候補リストと
# 画像解決が同じ表を使う。片方だけずれると「本文が名指しした石の画像が無い」が再発するため）。
_CRYSTAL_STONES = CRYSTAL_STONES      # 旧名の別名（既存のテスト・呼び出しを維持）


def _crystal_stone_in_text(text: str) -> int:
    """鑑定文に現れた石名（和名・英名）を番号へ解決する（mts5.60: stones.py へ委譲）。"""
    return resolve_stone_in_text(text)


def _find_crystal_image_file(stone_no: int, assets_dir: Path) -> Path | None:
    """M30_crystal: 石番号 → 番号＋英名（Amethyst 等）で検証して解決（不一致はスキップ）"""
    en = next((e for n, _ja, e, _a in _CRYSTAL_STONES if n == stone_no), "")
    return _find_numbered_deck_image(stone_no, assets_dir, en)


# ---- 画像監査（mts5.53・製品側ツールの監査 P-1/P-7） ------------------------- #
# 監査の指摘: 画像が欠けても **例外も警告も出ず**、HTML に
# 「※この占術には画像がありません（バグではなく、仕様です）。」とだけ出て正常終了していた。
# ここでは「結果ファイルがあるのに画像を1枚も埋め込めなかった占術」を集計し、
# ①HTML 本文に注記 ②標準出力に警告 ③実行時の警告台帳（runcheck）へ記録 する。
#
# ※ 画像ディレクトリ名が結果ファイル名と違う占術の対応表（例: 素材は M33_genekeys を共用）
IMAGE_DECK_ALIASES = {
    "M11_genekeys": "M33_genekeys",     # 結果 M11_genekeys → 素材 M33_genekeys
    "M27_urbantarot": "M27_tarot",      # 素材はタロットを共用
    "M22_liuyao": "M26_iching",         # 素材は易経64卦を共用
    "M12_stone": "M30_crystal",         # 素材はクリスタルを共用
}

#: 直近の `build_html` の画像監査結果（呼び出し側＝cellN2 が読む）
IMAGE_AUDIT: dict = {}


def _deck_dir_for(stem: str, assets_root: Path | None) -> Path | None:
    """結果ファイル名 → 素材ディレクトリ（無ければ None）。"""
    if assets_root is None:
        return None
    d = assets_root / IMAGE_DECK_ALIASES.get(stem, stem)
    return d if d.is_dir() else None


def _is_typec_slug(stem: str) -> bool:
    """型C（チャート描画）の占術か。型Cは素材ディレクトリを持たない。"""
    try:
        from .chartdraw import TYPEC_DECKS
        return stem in TYPEC_DECKS
    except Exception:
        return False


def _deck_can_have_image(stem: str, assets_root: Path | None) -> bool:
    """この占術の結果に画像が付くはずか（型C or 素材ディレクトリがある）。"""
    if _is_typec_slug(stem):
        return True
    return _deck_dir_for(stem, assets_root) is not None


# ---- 画像が無い場合の注意書き（mts5.15・ユーザー要望 2026-09-26） ----
# (A) 画像オミットが確定している占術: バグではなく仕様임을明示する。
NO_IMAGE_NOTICE_SLUGS = {"M31_deities", "M08_blood"}
NOTICE_NO_IMAGE = "※この占術には画像がありません（バグではなく、仕様です）。"
# (B) 結果対応型で、今回の結果に対応する画像が無い場合（誤充当より欠落を選ぶ方針の明示）。
NOTICE_NO_MATCH = "今回の占術結果に対しては画像がありません（バグではなく、仕様です）。"


def _no_image_notice_tag(text: str) -> str:
    """画像なしの注意書き（破線枠の小表示。画像と誤認させないための専用スタイル）"""
    return f'<div class="fortune-no-image">{html.escape(text)}</div>'


def _generic_crystal_tag(person_dir: Path, assets_root: Path | None) -> str:
    """M30_crystal: 鑑定文に現れた石の1枚を大表示（mts5.9。石名が無ければ注意書き＝mts5.15）"""
    if assets_root is None:
        return ""
    try:
        raw = person_dir / "results" / "M30_crystal_raw.json"
        if not raw.exists():
            return ""
        data = _json.loads(raw.read_text(encoding="utf-8"))
        text = (data.get("result") or {}).get("text") or ""
        no = _crystal_stone_in_text(text)
        if not no:
            return _no_image_notice_tag(NOTICE_NO_MATCH)
        _dir = assets_root / "M30_crystal"
        if not _dir.is_dir():
            return ""
        img = _find_crystal_image_file(no, _dir)
        if not img:
            return _no_image_notice_tag(NOTICE_NO_MATCH)
        ja, en = next(((j, e) for n, j, e, _a in _CRYSTAL_STONES if n == no), ("", ""))
        return _single_image_tag(img, f"【クリスタル・ヒーリング】{ja}（{en}）")
    except Exception:
        return ""


def _generic_stone_tag(person_dir: Path, assets_root: Path | None) -> str:
    """M12_stone（パワーストーン）: calc.birthstone（誕生石）→ M30_crystal 共有画像を表示（mts5.13）"""
    if assets_root is None:
        return ""
    try:
        raw = person_dir / "results" / "M12_stone_raw.json"
        if not raw.exists():
            return ""
        data = _json.loads(raw.read_text(encoding="utf-8"))
        res = data.get("result") or {}
        calc = res.get("calc") or {}
        b_name = calc.get("birthstone") if isinstance(calc, dict) else None
        no = 0
        if b_name:
            no = next((n for n, j, _e, _a in _CRYSTAL_STONES if j == b_name), 0)
        if not no:
            # calc に無ければ鑑定文から解決を試みる
            text = res.get("text") or ""
            no = _crystal_stone_in_text(text)
        if not no:
            return _no_image_notice_tag(NOTICE_NO_MATCH)
        # 共有ディレクトリ M30_crystal から解決
        _dir = assets_root / "M30_crystal"
        if not _dir.is_dir():
            return ""
        img = _find_crystal_image_file(no, _dir)
        if not img:
            return _no_image_notice_tag(NOTICE_NO_MATCH)
        ja, en = next(((j, e) for n, j, e, _a in _CRYSTAL_STONES if n == no), ("", ""))
        return _single_image_tag(img, f"【パワーストーン】{ja}（{en}）")
    except Exception:
        return ""


# 六爻（M22_liuyao）: origin_hexagram / variant_hexagram → M26_iching 64卦画像を流用表示（mts5.13）
# divicast の卦名（簡体字含む）→ (kingwen_no, 日本語卦名) の対応表
_LIUYAO_HEXAGRAM_MAP = {
    '乾': (1, '乾為天'), '坤': (2, '坤為地'), '屯': (3, '水雷屯'), '蒙': (4, '山水蒙'),
    '需': (5, '水天需'), '讼': (6, '天水訟'), '师': (7, '地水師'), '比': (8, '水地比'),
    '小畜': (9, '風天小畜'), '履': (10, '天澤履'), '泰': (11, '地天泰'), '否': (12, '天地否'),
    '同人': (13, '天火同人'), '大有': (14, '火天大有'), '谦': (15, '地山謙'), '豫': (16, '雷地豫'),
    '随': (17, '澤雷隨'), '蛊': (18, '山風蠱'), '临': (19, '地澤臨'), '观': (20, '風地觀'),
    '噬嗑': (21, '火雷噬嗑'), '贲': (22, '山火賁'), '剥': (23, '山地剝'), '复': (24, '地雷復'),
    '无妄': (25, '天雷無妄'), '大畜': (26, '山天大畜'), '颐': (27, '山雷頤'), '大过': (28, '澤風大過'),
    '坎': (29, '坎為水'), '离': (30, '離為火'), '咸': (31, '澤山咸'), '恒': (32, '雷風恆'),
    '遁': (33, '天山遯'), '大壮': (34, '雷天大壯'), '晋': (35, '火地晉'), '明夷': (36, '地火明夷'),
    '家人': (37, '風火家人'), '睽': (38, '火澤睽'), '蹇': (39, '水山蹇'), '解': (40, '雷水解'),
    '损': (41, '山澤損'), '益': (42, '風雷益'), '夬': (43, '澤天夬'), '姤': (44, '天風姤'),
    '萃': (45, '澤地萃'), '升': (46, '地風升'), '困': (47, '澤水困'), '井': (48, '水風井'),
    '革': (49, '澤火革'), '鼎': (50, '火風鼎'), '震': (51, '震為雷'), '艮': (52, '艮為山'),
    '渐': (53, '風山漸'), '归妹': (54, '雷澤歸妹'), '丰': (55, '雷火豐'), '旅': (56, '火山旅'),
    '巽': (57, '巽為風'), '兑': (58, '兌為澤'), '涣': (59, '風水渙'), '节': (60, '水澤節'),
    '中孚': (61, '風澤中孚'), '小过': (62, '雷山小過'), '既济': (63, '水火既濟'), '未济': (64, '火水未濟')
}

# mts5.31: 六爻の卦名を日本語表記（伝統字形）へ正規化したため、両方の字形で引けるようにする。
# 旧い実行（簡体字のまま保存された raw JSON）も、新しい実行（伝統字形）も同じ画像に解決される。
try:
    from .text_ja import to_ja_text as _to_ja_text
except Exception:                                  # pragma: no cover - 単体実行時のみ
    def _to_ja_text(x):
        return x

_LIUYAO_HEXAGRAM_MAP.update(
    {_to_ja_text(k, "name"): v for k, v in list(_LIUYAO_HEXAGRAM_MAP.items())})


def _generic_liuyao_tag(person_dir: Path, assets_root: Path | None) -> str:
    """M22_liuyao: 本卦・之卦を M26_iching 64卦画像から流用表示（mts5.13）"""
    if assets_root is None:
        return ""
    try:
        raw = person_dir / "results" / "M22_liuyao_raw.json"
        if not raw.exists():
            return ""
        data = _json.loads(raw.read_text(encoding="utf-8"))
        res = data.get("result") or {}
        calc = res.get("calc") or {}

        # 旧形式（簡体字）の raw JSON でも引けるように正規化してから照合する
        origin_name = _to_ja_text(calc.get("origin_hexagram") or "", "name")
        variant_name = _to_ja_text(calc.get("variant_hexagram") or "", "name")

        hexes = []
        if origin_name and origin_name in _LIUYAO_HEXAGRAM_MAP:
            no, ja = _LIUYAO_HEXAGRAM_MAP[origin_name]
            hexes.append((no, ja, "本卦"))
        if variant_name and variant_name in _LIUYAO_HEXAGRAM_MAP and variant_name != origin_name:
            no, ja = _LIUYAO_HEXAGRAM_MAP[variant_name]
            hexes.append((no, ja, "之卦"))

        if not hexes:
            return _no_image_notice_tag(NOTICE_NO_MATCH)

        _dir = assets_root / "M26_iching"
        if not _dir.is_dir():
            return ""

        items = []
        found = []
        for no, name, label in hexes:
            cands = list(_dir.glob(f"{no:02d}_*.webp")) + list(_dir.glob(f"{no:02d}_*.jpg"))
            if not cands:
                continue
            best = _pick_smaller_image(cands[0].with_suffix("")) or cands[0]
            for c in cands:
                alt = _pick_smaller_image(c.with_suffix(""))
                if alt and alt.stat().st_size < best.stat().st_size:
                    best = alt
            b64 = _encode_image_to_base64(best)
            alt = f"六爻 {name}（{no:02d}）{label}"
            cap = f"【六爻】{label}：{name}（{no:02d}）"
            found.append((b64, cap))
            items.append(
                f'<div class="fortune-image-item"><img src="{b64}" alt="{html.escape(alt)}" loading="lazy" />'
                f'<div class="fortune-image-caption">{html.escape(cap)}</div></div>')

        if not items:
            return ""
        if len(items) == 1:
            # mts5.31: 解決済みの1件を使う（先頭要素を再探索すると、その画像が無い場合に
            #          IndexError で**見つかっていた1枚まで消える**）
            b64, cap = found[0]
            return (f'<div class="fortune-image-container"><img src="{b64}" alt="{html.escape(cap)}" '
                    f'class="fortune-visual" loading="lazy" />'
                    f'<div class="fortune-image-caption">{html.escape(cap)}</div></div>')
        return f'<div class="fortune-image-grid">{"".join(items)}</div>'
    except Exception:
        return ""


def _generic_meso_tag(person_dir: Path, assets_root: Path | None) -> str:
    """M30_meso: メソポタミア天体オーメン 24枚から1枚解決（mts5.13）"""
    if assets_root is None:
        return ""
    try:
        raw = person_dir / "results" / "M30_meso_raw.json"
        if not raw.exists():
            return ""
        data = _json.loads(raw.read_text(encoding="utf-8"))
        res = data.get("result") or {}
        calc = res.get("calc") or {}

        omen_id = calc.get("omen_id")
        if not omen_id or not omen_id.startswith("EAE-"):
            return ""
        try:
            no = int(omen_id.split("-")[1])
        except (ValueError, IndexError):
            return ""

        _dir = assets_root / "M30_meso"
        if not _dir.is_dir():
            return ""

        cands = list(_dir.glob(f"{no:02d}_*.webp")) + list(_dir.glob(f"{no:02d}_*.jpg"))
        if not cands:
            return ""
        best = _pick_smaller_image(cands[0].with_suffix("")) or cands[0]
        theme = calc.get("theme", "")
        cap = f"【メソポタミア天体オーメン】{omen_id}（{theme}）" if theme else f"【メソポタミア天体オーメン】{omen_id}"
        b64 = _encode_image_to_base64(best)
        return (f'<div class="fortune-image-container"><img src="{b64}" alt="{html.escape(cap)}" '
                f'class="fortune-visual" loading="lazy" />'
                f'<div class="fortune-image-caption">{html.escape(cap)}</div></div>')
    except Exception:
        return ""


# キリスト教的黙想（M30_christian）: calc.reference（章句）→ 画像番号（01〜24）（mts5.13 で追加）
_CHRISTIAN_REF_MAP = {
    "マタイ 6:34": 1, "マタイ 7:7": 2, "マタイ 6:21": 3, "マタイ 11:28": 4,
    "マタイ 5:9": 5, "マルコ 4:28": 6, "ルカ 6:38": 7, "ルカ 12:25": 8,
    "ヨハネ 8:32": 9, "ヨハネ 14:27": 10, "ヨハネ 12:24": 11, "ローマ 5:3-4": 12,
    "ローマ 12:12": 13, "コリント一 13:4": 14, "コリント一 13:7": 15, "コリント一 10:13": 16,
    "コリント二 12:9": 17, "ガラテヤ 6:9": 18, "ピリピ 4:6": 19, "ピリピ 4:13": 20,
    "使徒 1:7": 21, "ヤコブ 1:19": 22, "ヘブル 11:1": 23, "ペテロ一 5:7": 24,
}


def _generic_christian_tag(person_dir: Path, assets_root: Path | None) -> str:
    """M30_christian: キリスト教的黙想 24枚から1枚解決（mts5.13）"""
    if assets_root is None:
        return ""
    try:
        raw = person_dir / "results" / "M30_christian_raw.json"
        if not raw.exists():
            return ""
        data = _json.loads(raw.read_text(encoding="utf-8"))
        res = data.get("result") or {}
        calc = res.get("calc") or {}

        ref = calc.get("reference")
        if not ref or ref not in _CHRISTIAN_REF_MAP:
            return ""
        no = _CHRISTIAN_REF_MAP[ref]

        _dir = assets_root / "M30_christian"
        if not _dir.is_dir():
            return ""

        cands = list(_dir.glob(f"{no:02d}_*.webp")) + list(_dir.glob(f"{no:02d}_*.jpg"))
        if not cands:
            return ""
        best = _pick_smaller_image(cands[0].with_suffix("")) or cands[0]
        theme = calc.get("theme", "")
        cap = f"【キリスト教的黙想】{ref}（{theme}）" if theme else f"【キリスト教的黙想】{ref}"
        b64 = _encode_image_to_base64(best)
        return (f'<div class="fortune-image-container"><img src="{b64}" alt="{html.escape(cap)}" '
                f'class="fortune-visual" loading="lazy" />'
                f'<div class="fortune-image-caption">{html.escape(cap)}</div></div>')
    except Exception:
        return ""


# 籤占（M28_astragaloi）: calc.throws（1, 3, 4, 6のリスト）→ 画像解決・グリッド表示（mts5.13 で追加）
_ASTRAGALOI_FACE_MAP = {
    1: "01_Chios_1",
    3: "02_Trias_3",
    4: "03_Tetras_4",
    6: "04_Stron_6",
}


def _generic_astragaloi_tag(person_dir: Path, assets_root: Path | None) -> str:
    """M28_astragaloi: 投擲出目リスト（throws）から各面の画像を複数枚グリッド表示（mts5.13）"""
    if assets_root is None:
        return ""
    try:
        raw = person_dir / "results" / "M28_astragaloi_raw.json"
        if not raw.exists():
            return ""
        data = _json.loads(raw.read_text(encoding="utf-8"))
        res = data.get("result") or {}
        calc = res.get("calc") or {}

        throws = calc.get("throws") or []
        if not throws:
            return ""

        _dir = assets_root / "M28_astragaloi"
        if not _dir.is_dir():
            return ""

        items = []
        for idx, val in enumerate(throws, start=1):
            face_slug = _ASTRAGALOI_FACE_MAP.get(val)
            if not face_slug:
                continue
            cands = list(_dir.glob(f"{face_slug}.webp")) + list(_dir.glob(f"{face_slug}.jpg"))
            if not cands:
                continue
            best = _pick_smaller_image(cands[0].with_suffix("")) or cands[0]
            b64 = _encode_image_to_base64(best)
            cap = f"第{idx}骨：{val}の目"
            items.append(f'<div class="fortune-image-item"><img src="{b64}" alt="{html.escape(cap)}" loading="lazy" /><div class="fortune-image-caption">【籤占】{html.escape(cap)}</div></div>')

        if not items:
            return ""
        judgment = calc.get("judgment", "")
        total = calc.get("total")
        total_str = f"（合計: {total}）" if total is not None else ""
        header_cap = f'<div class="fortune-image-caption">【籤占アストラガロイ】判定: {html.escape(judgment)}{total_str}</div>' if judgment else ""
        return f'<div class="fortune-image-grid">{"".join(items)}</div>{header_cap}'
    except Exception:
        return ""


def _generic_haruspex_tag(person_dir: Path, assets_root: Path | None) -> str:
    """M30_haruspex: 肝占 総合粘土模型図1枚を大表示（mts5.13）"""
    if assets_root is None:
        return ""
    try:
        raw = person_dir / "results" / "M30_haruspex_raw.json"
        if not raw.exists():
            return ""
        _dir = assets_root / "M30_haruspex"
        if not _dir.is_dir():
            return ""
        cands = list(_dir.glob("01_*.webp")) + list(_dir.glob("01_*.jpg"))
        if not cands:
            return ""
        best = _pick_smaller_image(cands[0].with_suffix("")) or cands[0]
        b64 = _encode_image_to_base64(best)
        cap = "【肝占（バールートゥ）】バビロニアの粘土肝模型（神々の啓示）"
        return (f'<div class="fortune-image-container"><img src="{b64}" alt="{html.escape(cap)}" '
                f'class="fortune-visual" loading="lazy" />'
                f'<div class="fortune-image-caption">{html.escape(cap)}</div></div>')
    except Exception:
        return ""


# ---- P6 古代託宣群: 鳥占（M30_ornith）／デルポイの託宣（M30_delphi）（mts5.14 で追加） ----
# 両ツールは calc_key=None（生成系）のため、画像は占術結果と**無関係**に5変種から1枚を表示する。
# **意図的なランダム表示（御神籤感覚）**＝ユーザー決定 2026-09-26（再現性は意図しない）。
ORNITH_VARIANTS = (
    (1, "HawkEast", "鷹・東天の飛翔", "Hawk - Eastern Flight"),
    (2, "DoveSouth", "鳩・南天の飛翔", "Dove - Southern Flight"),
    (3, "CrowWest", "鴉・西天の飛翔", "Crow - Western Flight"),
    (4, "SwallowCircle", "燕の群れ・旋回", "Swallows - Circling"),
    (5, "OwlNight", "梟・夜間の見張り", "Owl - Night Watch"),
)
DELPHI_VARIANTS = (
    (1, "Tripod", "アポローンの三脚鼎", "Apollo's Tripod"),
    (2, "LaurelCrown", "月桂樹の冠", "Laurel Crown"),
    (3, "CastaliaSpring", "カスタリアの泉", "Castalian Spring"),
    (4, "ZeusEagle", "ゼウスの鷲", "Eagle of Zeus"),
    (5, "Omphalos", "オンパロス石", "Omphalos Stone"),
)


def _pick_pd6_variant(variants) -> tuple:
    """5変種から**意図的にランダムに**1つ選ぶ（御神籤感覚・mts5.14・ユーザー決定）"""
    return _random.choice(list(variants))


def _generic_pd6_tag(person_dir: Path, assets_root: Path | None, deck: str,
                     variants, cap_head: str) -> str:
    """M30_ornith / M30_delphi: 結果と無関係に5変種からランダムに1枚を大表示（mts5.14）"""
    if assets_root is None:
        return ""
    try:
        raw = person_dir / "results" / f"{deck}_raw.json"
        if not raw.exists():
            return ""
        _dir = assets_root / deck
        if not _dir.is_dir():
            return ""
        no, slug, ja, en = _pick_pd6_variant(variants)
        img = _find_numbered_deck_image(no, _dir, slug)
        if not img:
            return ""
        return _single_image_tag(img, f"【{cap_head}】{ja}（{en}）")
    except Exception:
        return ""


def _generic_ornith_tag(person_dir: Path, assets_root: Path | None) -> str:
    """M30_ornith: 鳥占 5変種からランダムに1枚を大表示（mts5.14）"""
    return _generic_pd6_tag(person_dir, assets_root, "M30_ornith", ORNITH_VARIANTS, "鳥占")


def _generic_delphi_tag(person_dir: Path, assets_root: Path | None) -> str:
    """M30_delphi: デルポイの託宣 5変種からランダムに1枚を大表示（mts5.14）"""
    return _generic_pd6_tag(person_dir, assets_root, "M30_delphi", DELPHI_VARIANTS, "デルポイの託宣")


# アフリカ（M29_african）: calc.open_count（0〜8）→ 画像番号（01〜09）＋英名（Open0〜Open8）（mts5.10 で追加）
_AFRICAN_ORDER = [(n - 1, f"Open{n - 1}") for n in range(1, 10)]


def _find_african_image_file(open_count: int, assets_dir: Path) -> Path | None:
    """M29_african: 開きの数（0〜8）→ 番号＋英名で検証して解決（不一致はスキップ）"""
    en = next((e for oc, e in _AFRICAN_ORDER if oc == int(open_count)), "")
    if not en:
        return None
    return _find_numbered_deck_image(int(open_count) + 1, assets_dir, en)


def _generic_african_tag(person_dir: Path, assets_root: Path | None) -> str:
    """M29_african: M29_african_raw.json の calc.open_count に対応する1枚を大表示（mts5.10）"""
    if assets_root is None:
        return ""
    try:
        raw = person_dir / "results" / "M29_african_raw.json"
        if not raw.exists():
            return ""
        data = _json.loads(raw.read_text(encoding="utf-8"))
        calc = (data.get("result") or {}).get("calc") or data.get("calc") or {}
        oc = calc.get("open_count")
        if not isinstance(oc, int):
            return ""
        _dir = assets_root / "M29_african"
        if not _dir.is_dir():
            return ""
        img = _find_african_image_file(oc, _dir)
        if not img:
            return ""
        return _single_image_tag(img, f"【伝統的アフリカ占い】開き {oc} 枚（Open{oc}）")
    except Exception:
        return ""


def _generic_talisman_tag(person_dir: Path, assets_root: Path | None) -> str:
    """M30_talisman: 護符の意匠1枚を大表示（calc を持たない占術のため固定の1枚。mts5.10）"""
    if assets_root is None:
        return ""
    try:
        raw = person_dir / "results" / "M30_talisman_raw.json"
        if not raw.exists():
            return ""
        _dir = assets_root / "M30_talisman"
        if not _dir.is_dir():
            return ""
        img = _find_numbered_deck_image(1, _dir, "Talisman")
        if not img:
            return ""
        return _single_image_tag(img, "【タリスマン・お守り】タリスマン（Talisman）")
    except Exception:
        return ""


def _single_image_tag(img_path: Path, caption: str) -> str:
    """1枚大表示（既存の fortune-image-container を流用）"""
    b64 = _encode_image_to_base64(img_path)
    return (f'<div class="fortune-image-container"><img src="{b64}" alt="{html.escape(caption)}" '
            f'class="fortune-visual" loading="lazy" />'
            f'<div class="fortune-image-caption">{html.escape(caption)}</div></div>')


def _generic_animal_tag(person_dir: Path, assets_root: Path | None) -> str:
    """M09_animal（動物占い）: M09_animal_raw.json の number を 1枚大表示"""
    if assets_root is None:
        return ""
    try:
        raw = person_dir / "results" / "M09_animal_raw.json"
        if not raw.exists():
            return ""
        data = _json.loads(raw.read_text(encoding="utf-8"))
        calc = data.get("calc") or (data.get("result") or {}).get("calc") or {}
        no = calc.get("number")
        if no is None:
            return ""
        _dir = assets_root / "M09_animal"
        if not _dir.is_dir():
            return ""
        img = _find_animal_image_file(int(no), _dir)
        if not img:
            _trace_image({"card_id": no, "name_en": _animal_profile(int(no)).get("animal_en", "")},
                         None, "skip:animal")
            return ""
        prof = _animal_profile(int(no))
        cap = f"【動物占い】No.{int(no):02d} {prof.get('animal', '')}（{prof.get('animal_en', '')}）{prof.get('profile', '')}".strip()
        return _single_image_tag(img, cap)
    except Exception:
        return ""


def _generic_genekeys_tag(person_dir: Path, assets_root: Path | None) -> str:
    """M33_genekeys（ジーンキーズ）: M11_genekeys_raw.json の太陽ゲートを 1枚大表示"""
    if assets_root is None:
        return ""
    try:
        raw = person_dir / "results" / "M11_genekeys_raw.json"
        if not raw.exists():
            return ""
        data = _json.loads(raw.read_text(encoding="utf-8"))
        calc = data.get("calc") or (data.get("result") or {}).get("calc") or {}
        gate = (calc.get("sun_gate") or {}).get("gate") or (calc.get("key") or {}).get("gate")
        if gate is None:
            return ""
        gate = int(gate)
        _dir = assets_root / "M33_genekeys"
        if not _dir.is_dir():
            return ""
        img = _find_genekeys_image_file(gate, _dir)
        if not img:
            return ""
        arch = _genekeys_archetype(gate)
        cap = f"【ジーンキーズ】第{gate}鍵 {_genekeys_key_name(gate)}／{arch.get('archetype_ja', '')}（{arch.get('archetype_en', '')}）".strip()
        return _single_image_tag(img, cap)
    except Exception:
        return ""


# --------------------------------------------------------------- 生成デッキ（oracle / angel）
def _generic_deck_tag_anchor() -> None:
    """（拡張の目印・処理なし）"""


def _generic_deck_tag(person_dir: Path, assets_root: Path | None, deck_dir: str,
                      raw_stem: str, label: str, finder) -> str:
    """生成デッキ（oracle / angel）の全枚表示。1枚なら単独大表示、複数ならグリッド"""
    if assets_root is None:
        return ""
    try:
        raw = person_dir / "results" / f"{raw_stem}_raw.json"
        if not raw.exists():
            return ""
        data = _json.loads(raw.read_text(encoding="utf-8"))
        calc = (data.get("result") or {}).get("calc") or data.get("calc") or {}
        cards = calc.get("cards") or data.get("cards") or []
        if not cards:
            return ""
        _dir = assets_root / deck_dir
        if not _dir.is_dir():
            return ""
        items = []
        found = []
        for card in cards:
            img_path = finder(card, _dir)
            if not img_path:
                continue
            b64 = _encode_image_to_base64(img_path)
            name = card.get("name_ja") or card.get("name_en") or ""
            pos = card.get("position") or ""
            rev = "（逆位置）" if card.get("upright") is False else ""
            cap = f"{pos} {name}{rev}".strip()
            found.append((b64, name))
            items.append(f'<div class="fortune-image-item"><img src="{b64}" alt="{html.escape(cap)}" loading="lazy" />'
                         f'<div class="fortune-image-caption">【{label}】{html.escape(cap)}</div></div>')
        if not items:
            return ""
        if len(items) == 1:
            # mts5.31: 解決済みの1件を使う（cards[0] に画像が無いと1枚も表示できない）
            b64, name = found[0]
            return (f'<div class="fortune-image-container"><img src="{b64}" alt="{html.escape(name)}" '
                    f'class="fortune-visual" loading="lazy" />'
                    f'<div class="fortune-image-caption">【{label}】{html.escape(name)}</div></div>')
        return f'<div class="fortune-image-grid">{"".join(items)}</div>'
    except Exception:
        return ""


def _generic_oracle_tag(person_dir: Path, assets_root: Path | None) -> str:
    """M27_oracle 全枚表示"""
    return _generic_deck_tag(person_dir, assets_root, "M27_oracle", "M27_oracle",
                             "オラクル", _find_oracle_image_file)


def _generic_angel_tag(person_dir: Path, assets_root: Path | None) -> str:
    """M27_angel 全枚表示"""
    return _generic_deck_tag(person_dir, assets_root, "M27_angel", "M27_angel",
                             "エンジェル", _find_angel_image_file)


def _generic_kipper_tag(person_dir: Path, assets_root: Path | None) -> str:
    """M27_kipper 全枚表示"""
    if assets_root is None:
        return ""
    try:
        raw = person_dir / "results" / "M27_kipper_raw.json"
        if not raw.exists():
            return ""
        data = _json.loads(raw.read_text(encoding="utf-8"))
        calc = (data.get("result") or {}).get("calc") or data.get("calc") or {}
        cards = calc.get("cards") or []
        if not cards:
            return ""
        _dir = assets_root / "M27_kipper"
        if not _dir.is_dir():
            return ""
        items = []
        found = []
        for card in cards:
            img_path = _find_kipper_image_file(card, _dir)
            if not img_path:
                continue
            b64 = _encode_image_to_base64(img_path)
            name = card.get("name_ja") or card.get("name_en") or ""
            pos = card.get("position") or ""
            rev = ""
            if card.get("upright") is False:
                rev = "（逆位置）"
            label = f"{pos} {name}{rev}".strip()
            found.append((b64, name))
            items.append(f'<div class="fortune-image-item"><img src="{b64}" alt="{html.escape(label)}" loading="lazy" />'
                         f'<div class="fortune-image-caption">【キッパー】{html.escape(label)}</div></div>')
        if not items:
            return ""
        if len(items) == 1:
            # mts5.31: 解決済みの1件を使う（取りこぼし防止）
            b64, name = found[0]
            return (f'<div class="fortune-image-container"><img src="{b64}" alt="{html.escape(name)}" '
                    f'class="fortune-visual" loading="lazy" />'
                    f'<div class="fortune-image-caption">【キッパー】{html.escape(name)} の象意</div></div>')
        return f'<div class="fortune-image-grid">{"".join(items)}</div>'
    except Exception:
        return ""


def _generic_runes_tag(person_dir: Path, assets_root: Path | None) -> str:
    """M27_runes 全枚表示"""
    if assets_root is None:
        return ""
    try:
        raw = person_dir / "results" / "M27_runes_raw.json"
        if not raw.exists():
            return ""
        data = _json.loads(raw.read_text(encoding="utf-8"))
        calc = (data.get("result") or {}).get("calc") or data.get("calc") or {}
        cards = calc.get("cards") or []
        if not cards:
            return ""
        _dir = assets_root / "M27_runes"
        if not _dir.is_dir():
            return ""
        items = []
        found = []
        for card in cards:
            img_path = _find_rune_image_file(card, _dir)
            if not img_path:
                continue
            b64 = _encode_image_to_base64(img_path)
            name = card.get("name_ja") or card.get("name_en") or ""
            name_en = card.get("name_en") or ""
            pos = card.get("position") or ""
            label = f"{pos} {name}（{name_en}）".strip()
            found.append((b64, name))
            items.append(f'<div class="fortune-image-item"><img src="{b64}" alt="{html.escape(label)}" loading="lazy" />'
                         f'<div class="fortune-image-caption">【ルーン】{html.escape(label)}</div></div>')
        if not items:
            return ""
        if len(items) == 1:
            # mts5.31: 解決済みの1件を使う（取りこぼし防止）
            b64, name = found[0]
            return (f'<div class="fortune-image-container"><img src="{b64}" alt="{html.escape(name)}" '
                    f'class="fortune-visual" loading="lazy" />'
                    f'<div class="fortune-image-caption">【ルーン】{html.escape(name)} の石</div></div>')
        return f'<div class="fortune-image-grid">{"".join(items)}</div>'
    except Exception:
        return ""


def _generic_omikuji_tag(person_dir: Path, assets_root: Path | None,
                         person_id: str = "") -> str:
    """M28_omikuji 1枚表示（段階・ポーズは決定的に選択）"""
    if assets_root is None:
        return ""
    try:
        raw = person_dir / "results" / "M28_omikuji_raw.json"
        if not raw.exists():
            return ""
        data = _json.loads(raw.read_text(encoding="utf-8"))
        calc = (data.get("result") or {}).get("calc") or data.get("calc") or {}
        level = calc.get("level") or ""
        if not level:
            return ""
        level_no = _omikuji_level_index(level)
        if not level_no:
            return ""
        seed = calc.get("seed")
        pose_idx = int(seed) % len(OMIKUJI_POSES) if isinstance(seed, int) \
            else _stable_index(f"{person_id or person_dir.name}:{level}", len(OMIKUJI_POSES))
        special = None
        if level_no == 1:            # 大大吉は金縁の特別柄
            special = "gold"
        elif level_no == 12:         # 大凶は黒縁の特別柄
            special = "ink"
        _dir = assets_root / "M28_omikuji"
        if not _dir.is_dir():
            return ""
        img_path = _find_omikuji_image_file(level_no, pose_idx, _dir, special)
        if not img_path:
            return ""
        b64 = _encode_image_to_base64(img_path)
        keyword = calc.get("keyword") or ""
        cap = f"【おみくじ】{level}" + (f"　{keyword}" if keyword else "")
        return (f'<div class="fortune-image-container"><img src="{b64}" alt="{html.escape(level)}" '
                f'class="fortune-visual" loading="lazy" />'
                f'<div class="fortune-image-caption">{html.escape(cap)}</div></div>')
    except Exception:
        return ""


def _generic_image_tag(slug: str, person_dir: Path, assets_root: Path | None) -> str:
    """汎用画像タグ生成（M26_iching等へ横展開） - 全枚対応"""
    if assets_root is None:
        return ""
    if slug == "M26_iching":
        raw = person_dir / "results" / "M26_iching_raw.json"
        if raw.exists():
            try:
                data = _json.loads(raw.read_text(encoding="utf-8"))
                calc = (data.get("result") or {}).get("calc") or data.get("calc") or {}
                # 本卦・変卦の2卦を全表示
                hexes = []
                for key, label in [("ben_hexagram","本卦"),("derived_hexagram","変卦")]:
                    hx = calc.get(key) or {}
                    no = hx.get("kingwen_no")
                    name = hx.get("name_ja") or ""
                    if no:
                        hexes.append((int(no), name, label))
                if not hexes:
                    # 旧互換
                    ben = calc.get("ben_hexagram") or calc.get("hexagram") or {}
                    no = ben.get("kingwen_no")
                    if no:
                        hexes.append((int(no), ben.get("name_ja",""), "本卦"))
                if not hexes:
                    return ""
                _dir = assets_root / "M26_iching"
                if not _dir.is_dir():
                    return ""
                items = []
                found = []
                for no, name, label in hexes:
                    cands = list(_dir.glob(f"{no:02d}_*.webp")) + list(_dir.glob(f"{no:02d}_*.jpg"))
                    if not cands:
                        continue
                    best = _pick_smaller_image(cands[0].with_suffix("")) or cands[0]
                    for c in cands:
                        alt = _pick_smaller_image(c.with_suffix(""))
                        if alt and alt.stat().st_size < best.stat().st_size:
                            best = alt
                    b64 = _encode_image_to_base64(best)
                    alt = f"易 {name}（{no:02d}）{label}" if name else f"易 {no:02d} {label}"
                    cap = f"【易】{label}：{name}（{no:02d}）"
                    found.append((b64, cap, name))
                    items.append(f'<div class="fortune-image-item"><img src="{b64}" alt="{html.escape(alt)}" loading="lazy" /><div class="fortune-image-caption">{html.escape(cap)}</div></div>')
                if not items:
                    return ""
                if len(items)==1:
                    # mts5.31: 解決済みの1件を使う（IndexError による画像の消失を防ぐ）
                    b64, cap, name = found[0]
                    return f'<div class="fortune-image-container"><img src="{b64}" alt="易 {html.escape(name)}" class="fortune-visual" loading="lazy" /><div class="fortune-image-caption">{html.escape(cap)} の象意図（CC0）</div></div>'
                return f'<div class="fortune-image-grid">{"".join(items)}</div>'
            except Exception:       # mts5.31: 裸の except は KeyboardInterrupt も飲む
                pass
    return ""

def load_tone_data(person_dir) -> dict | None:
    """mts5.22: Stage D の成果（tone_reports/）を読み込む。

    返り値: {"tones": {tid: {"label", "units": {uid: html}, "fallback"}},
             "rules": {tid: {...}}} ／ 利用可能なトーンが無ければ None
    （standard は units 空 = 元テキストを JS が復元するため）
    """
    from . import tone as _tone
    tr = Path(person_dir) / "tone_reports"
    mp = tr / "tone_manifest.json"
    if not mp.is_file():
        return None
    try:
        manifest = _json.loads(mp.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    tones: dict = {}
    missing: list = []          # mts5.57: 今回作れなかったトーン（HTML に理由を出す）
    for tdef in _tone.TONE_DEFS:
        tid = tdef["id"]
        if tid == "standard":
            tones[tid] = {"label": tdef["label"], "units": {}, "fallback": False}
            continue
        entry = (manifest.get("tones") or {}).get(tid) or {}
        up = tr / tid / "units.json"
        units: dict = {}
        if up.is_file():
            try:
                raw = _json.loads(up.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                raw = {}
            for uid, text in raw.items():
                if isinstance(text, str) and text.strip():
                    # mts5.24 以降の値は HTML（md_to_html 済み）→ そのまま採用。
                    # 旧形式（プレーン Markdown）のみ md_to_html を適用。
                    if re.search(r"</?(?:p|div|strong|em|ul|ol|li|pre|code|h[1-6]|br|hr)\b",
                                 text, re.I):
                        units[uid] = text
                    else:
                        units[uid] = md_to_html(text)
        if not units:
            # 全ユニット失敗のトーンはタブを出さない（JS規則のみ）。
            # mts5.57: **その実行で作ろうとして作れなかった**トーンは、黙って消さず
            # 理由を1行だけ注記に残す（manifest に記録が無い＝今回は対象外、は出さない）。
            if entry and entry.get("status") != "ok":
                missing.append({"id": tid, "label": tdef["label"],
                                "reason": entry.get("reason") or "none"})
            continue
        tones[tid] = {
            "label": tdef["label"],
            "units": units,
            "fallback": entry.get("status") == "fallback",
        }
    if len(tones) <= 1:
        return None  # 標準のみならタブ UI は不要
    # mts5.29: scope="synthesis" は「読み物版（オマケ）」モード。
    # tones の units は {synthesis_omake: html} 1件だけ＝カード内で切り替える。
    omake_id = manifest.get("omake_unit_id")
    is_omake = bool(omake_id) or any(
        (manifest.get("tones", {}).get(t, {}) or {}).get("mode") == "omake"
        for t in tones)
    if is_omake:
        omake = {}
        for tid, t in tones.items():
            if tid == "standard":
                continue
            html_text = (t.get("units") or {}).get(omake_id or "synthesis_omake")
            if isinstance(html_text, str) and html_text.strip():
                omake[tid] = html_text
        if not omake:
            return None      # 全トーン失敗＝カードを出さない（標準のみ）
        return {"tones": tones, "rules": {}, "omake": omake,
                "omake_unit_id": omake_id or "synthesis_omake",
                "tone_units": [omake_id or "synthesis_omake"],
                "scope": manifest.get("scope"), "missing": missing}
    rules = {tid: _tone.TONE_RULES[tid] for tid in tones if tid in _tone.TONE_RULES}
    # mts5.27: 口調化の対象ユニット（scope=narrative では物語系のみ）。
    # 対象外の .tone-text は JS が orig（標準）へ固定する＝JS 規則も適用しない。
    target = manifest.get("target_units")
    return {"tones": tones, "rules": rules,
            "tone_units": target if isinstance(target, list) else None,
            "scope": manifest.get("scope"), "missing": missing}


def _tone_ui_html(tone_data: dict) -> str:
    """タブバー＋トーンデータJSON＋切替JS（オフライン・外部依存なし）

    tone_data["tones"] の挿入順が TONE_DEFS 順（standard が先頭）。
    mts5.46: scope=synthesis は表示データ＋切替JSのみを出す。
    ボタンは統合レポートの見出し直下に置き、標準本文の同じ表示枠を切り替える。
    """
    if tone_data.get("omake"):
        payload = _json.dumps({"omake": tone_data["omake"],
                               "labels": {tid: t.get("label", tid)
                                          for tid, t in tone_data["tones"].items()}},
                              ensure_ascii=False).replace("</", "<\\/")
        return ('<script type="application/json" id="omake-data">' + payload
                + '</script>\n<script>\n' + _SYNTHESIS_TABS_JS + '\n</script>')
    order = list(tone_data["tones"].keys())
    buttons = "".join(
        f'<button type="button" class="tb-btn" data-tone="{tid}"'
        f' aria-pressed="{"true" if i == 0 else "false"}">{tone_data["tones"][tid]["label"]}</button>'
        for i, tid in enumerate(order))
    payload = _json.dumps(
        {"tones": tone_data["tones"], "rules": tone_data.get("rules") or {},
         "tone_units": tone_data.get("tone_units")},
        ensure_ascii=False).replace("</", "<\\/")
    return (
        '<div class="tonebar" id="tonebar"><span class="tb-label">口調</span>'
        + buttons + '</div>'
        '<p class="tone-note" id="tone-note">現在、簡易変換（近似）で表示しています。</p>'
        '<script type="application/json" id="tone-data">' + payload + '</script>'
        '<script>\n' + _TONE_JS + '\n</script>'
    )


def _video_css(intro_video_html: str = "") -> str:
    """冒頭動画カードがあるときだけ CSS を足す（無い人のHTMLを太らせない）。"""
    if not intro_video_html:
        return ""
    try:
        from fortunelib.intro_video import CARD_CSS, INTRO_CSS
        return CARD_CSS + INTRO_CSS
    except Exception:
        return ""


def _synthesis_tone_tabs_html(tone_data: dict) -> str:
    """統合レポート見出し内の表示切替（mts5.46）。標準本文を同じ枠で差し替える。"""
    from . import tone as _tone          # mts5.57: 失敗理由の文言
    variants = tone_data.get("omake") or {}
    order = ["standard"] + [tid for tid in variants
                            if tid in (tone_data.get("tones") or {})]
    buttons = "".join(
        f'<button type="button" class="tb-btn synthesis-view-btn" '
        f'id="synthesis-tab-{html.escape(tid, quote=True)}" '
        f'data-tone="{html.escape(tid, quote=True)}" role="tab" '
        f'aria-controls="synthesis-body" aria-selected="{"true" if i == 0 else "false"}" '
        f'aria-pressed="{"true" if i == 0 else "false"}">'
        f'{html.escape((tone_data["tones"].get(tid) or {}).get("label", tid))}</button>'
        for i, tid in enumerate(order))
    if len(order) <= 1:
        return ""
    # mts5.57: 作れなかったトーンがあれば理由を添える（「なぜか表示されない」を防ぐ）
    missing = list(tone_data.get("missing") or [])
    miss_html = ""
    if missing:
        def _one(m: dict) -> str:
            reason = _tone.FAIL_REASONS.get(str(m.get("reason") or "none"),
                                            _tone.FAIL_REASONS["none"])
            label = str(m.get("label") or m.get("id") or "")
            return html.escape(label) + "（" + html.escape(reason) + "）"
        items = "、".join(_one(m) for m in missing)
        miss_html = (
            '<p class="synthesis-note synthesis-missing-note">'
            '※ 今回の実行では ' + items + ' を作れませんでした。'
            '読み物版は再実行すると作られます（鑑定内容の正本は「標準」です）。</p>')
    return (
        '<div class="synthesis-switcher" id="synthesis-switcher" role="tablist" '
        'aria-label="統合鑑定レポートの表示切替">'
        '<span class="switch-label">表示</span>' + buttons + '</div>'
        '<p class="synthesis-note">読み物版は標準をもとに表現を変えたものです。'
        '正確な内容・数値の正本は「標準」です。</p>' + miss_html)


_SYNTHESIS_TABS_JS = r"""
(function(){
  /* mts5.46: 読み物版を別カードではなく統合本文のタブとして切り替える。
     ページを開いた時は常に標準。以前のfortune_omake保存値は読み込まない。 */
  function boot(){
    var el=document.getElementById('omake-data');
    if(!el) return;
    var D;
    try{ D=JSON.parse(el.textContent); }catch(e){ return; }
    if(!D.omake) return;
    var body=document.getElementById('synthesis-body');
    var bar=document.getElementById('synthesis-switcher');
    if(!body || !bar) return;
    var standard=body.innerHTML;
    var buttons=Array.prototype.slice.call(
      bar.querySelectorAll('.synthesis-view-btn'));
    if(!buttons.length) return;
    function setTone(tid){
      var content=(tid==='standard') ? standard : D.omake[tid];
      if(typeof content!=='string' || !content){
        tid='standard';
        content=standard;
      }
      body.innerHTML=content;
      bar.setAttribute('data-active-tone',tid);
      buttons.forEach(function(b){
        var active=b.getAttribute('data-tone')===tid;
        b.setAttribute('aria-pressed',active?'true':'false');
        b.setAttribute('aria-selected',active?'true':'false');
      });
    }
    buttons.forEach(function(b){
      b.addEventListener('click',function(){
        setTone(b.getAttribute('data-tone'));
      });
    });
    /* 常に標準を初期表示し、オマケカード時代のlocalStorage値も尊重しない。 */
    setTone('standard');
  }
  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',boot);
  }else{
    boot();
  }
})();
"""


_TONE_JS = r"""
(function(){
  /* mts5.26: パース順序に依存しない初期化（BUG-23 の修正）。
     この script は body 直後（本文の .tone-text より前）に置かれるため、
     即時 IIFE で querySelectorAll('.tone-text') を実行すると 0 件になり
     「タブは出るがクリックしても何も変わらない」状態になっていた。
     → DOM 構築完了後に boot() を実行する。 */
  function boot(){
    var el=document.getElementById('tone-data');
    if(!el) return;
    var D;
    try{ D=JSON.parse(el.textContent); }catch(e){ return; }
    if(!D.tones) return;
    var texts=[], orig={};
    /* 本文 .tone-text を収集する。orig は「最初に見た内容＝標準トーン」を
       保持する（遅延収集でトーン適用済みの内容を orig に混ぜないため）。 */
    function collect(){
      texts=Array.prototype.slice.call(document.querySelectorAll('.tone-text'));
      texts.forEach(function(t){
        var u=t.getAttribute('data-unit');
        if(u!=null && !(u in orig)) orig[u]=t.innerHTML;
      });
      return texts.length;
    }
    var note=document.getElementById('tone-note');
    function applyRules(tid,uid){
      var r=(D.rules||{})[tid];
      var h=orig[uid];
      if(r==null||h==null) return null;
      (r.subs||[]).forEach(function(s){ h=h.split(s[0]).join(s[1]); });
      return h;
    }
    function setTone(tid){
      /* 保険: 収集前に呼ばれても切替対象を取り直す（順序非依存） */
      if(!texts.length) collect();
      var btns=Array.prototype.slice.call(document.querySelectorAll('.tb-btn'));
      btns.forEach(function(b){
        b.setAttribute('aria-pressed', b.getAttribute('data-tone')===tid ? 'true':'false');
      });
      var toneData=(D.tones||{})[tid]||{units:{}};
      var fallback=0, total=0;
      texts.forEach(function(t){
        var uid=t.getAttribute('data-unit');
        total++;
        /* mts5.27: 口調化の対象外ユニット（例: scope=narrative での個別占術）は
           常に標準のまま。JS 規則も適用せず、注記のカウントにも入れない。 */
        if(D.tone_units && D.tone_units.indexOf(uid)===-1){
          t.innerHTML=orig[uid]!=null?orig[uid]:'';
          return;
        }
        var u=toneData.units[uid];
        if(u!=null){ t.innerHTML=u; return; }
        if(tid!=='standard'){
          var rb=applyRules(tid,uid);
          if(rb!=null){ t.innerHTML=rb; fallback++; return; }
        }
        t.innerHTML=orig[uid]!=null?orig[uid]:'';
      });
      var showNote = tid!=='standard' && (toneData.fallback===true || fallback>0);
      if(note) note.style.display=showNote?'block':'none';
      try{ localStorage.setItem('fortune_tone',tid); }catch(e){}
    }
    var n=collect();
    if(!n && typeof console!=='undefined' && console.warn){
      console.warn('tone: .tone-text が 0 件です（本文が無い HTML かパース順序の退行）');
    }
    Array.prototype.slice.call(document.querySelectorAll('.tb-btn')).forEach(function(b){
      b.addEventListener('click',function(){ setTone(b.getAttribute('data-tone')); });
    });
    var saved=null;
    try{ saved=localStorage.getItem('fortune_tone'); }catch(e){}
    if(saved && (D.tones||{})[saved]) setTone(saved);
  }
  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded', boot);
  }else{
    boot();
  }
})();
"""


# mts5.28: 型Cフォント欠落の警告を1回だけ出すためのフラグ
_typec_font_warned = [False]


#: 自動探索でまず見る固定候補（相対パスは CWD 基準。順番が優先順位。個人のマウント名は含めない）
DISCOVERY_CANDIDATES = [
    Path("assets/images"),
    Path("/kaggle/input/fortune-dataset/assets/images"),
]

#: 見つからなければ走査する glob（Kaggle の Dataset 名・所有者名が何であっても拾えるように）
DISCOVERY_GLOBS = ["/kaggle/input/**/assets/images",
                   "/kaggle/input/datasets/**/assets/images"]

#: 直下を列挙して探す場所（マウント名が全く違う場合の最後の手段）
DISCOVERY_BASES = [Path("/kaggle/input")]

#: 「画像ディレクトリらしい」と判定するために必ずあるデッキ（この判定は mts4.6 から不変）
DISCOVERY_REQUIRED_DECK = "M27_tarot"

#: 画像ディレクトリを明示する環境変数（最優先。`assets/images` そのもの、またはその親を指す）
ASSETS_DIR_ENV = "FORTUNE_ASSETS_DIR"


def _looks_like_assets_root(path) -> bool:
    """画像ディレクトリらしいか（`M27_tarot` を持つディレクトリか）。"""
    try:
        p = Path(path)
        return p.is_dir() and (p / DISCOVERY_REQUIRED_DECK).is_dir()
    except Exception:
        return False


def _assets_root_from_env() -> Path | None:
    """環境変数 `FORTUNE_ASSETS_DIR` → `FORTUNE_DATA_DIR` の順に、画像ディレクトリを推定する。"""
    import os as _os
    _explicit = _os.environ.get(ASSETS_DIR_ENV, "")
    if _explicit:
        for _try in (Path(_explicit), Path(_explicit) / "assets" / "images", Path(_explicit) / "images"):
            if _looks_like_assets_root(_try):
                return _try
    _fdd = _os.environ.get("FORTUNE_DATA_DIR", "")
    if _fdd:
        _try = Path(_fdd).parent / "assets" / "images"
        if _looks_like_assets_root(_try):
            return _try
    return None


def _auto_discover_assets_root() -> Path | None:
    """画像ディレクトリの自動探索（`images_dir` 未指定のときだけ使う）。

    順番: 環境変数（`FORTUNE_ASSETS_DIR` → `FORTUNE_DATA_DIR` の親/assets/images）→
    `DISCOVERY_CANDIDATES` → `DISCOVERY_GLOBS` → `DISCOVERY_BASES` 直下の列挙。
    合格条件はどの経路でも `M27_tarot` を持つこと。候補・glob・列挙場所は定数（`DISCOVERY_*`）
    なので、テストでは差し替えて環境から独立させられる。個人や特定アカウントのパスは含めない。
    """
    found = _assets_root_from_env()
    if found is not None:
        return found

    for cand in DISCOVERY_CANDIDATES:
        if _looks_like_assets_root(cand):
            return Path(cand)

    # 汎用探索: /kaggle/input 配下を走査（Dataset 名・所有者名の違いを吸収）
    try:
        import glob as _glob
        for _pat in DISCOVERY_GLOBS:
            for _g in sorted(_glob.glob(_pat, recursive=True)):
                if _looks_like_assets_root(_g):
                    return Path(_g)
    except Exception:
        pass

    # マウント直下を列挙して探す（最後の手段）
    for _base in DISCOVERY_BASES:
        try:
            if not Path(_base).is_dir():
                continue
            for _child in sorted(Path(_base).iterdir()):
                _try2 = _child / "assets" / "images"
                if _looks_like_assets_root(_try2):
                    return _try2
                # datasets/* の2階層
                if _child.name == "datasets":
                    for _g2 in sorted(_child.rglob("assets/images")):
                        if _looks_like_assets_root(_g2):
                            return Path(_g2)
        except Exception:
            continue
    return None


def discover_assets_root(base=None) -> Path | None:
    """画像ディレクトリ（`assets/images`）を見つける公開 API（Kaggle の Cell N2 などが使う）。

    `base` を渡すと、まず `base`（それ自体が画像ディレクトリの場合）と `base/assets/images` を見る。
    見つからなければ `_auto_discover_assets_root()` と同じ順番（環境変数 → 候補 → glob → 列挙）で探す。
    返り値は `M27_tarot` を持つディレクトリ、無ければ None。
    """
    if base:
        for _try in (Path(base) / "assets" / "images", Path(base)):
            if _looks_like_assets_root(_try):
                return _try
    return _auto_discover_assets_root()


def build_html(person_dir, title: str = "", person_id: str = "",
               images_dir: str | Path | None = None,
               intro_video_html: str = "") -> Path:
    """1人分の成果物を1枚のHTMLにまとめる。

    Args:
        images_dir: M23_meihua等の画像アセットディレクトリ（例: assets/images/M23_meihua）または
                    assets/images ルート。指定時は該当する1枚のみをBase64埋め込みする（2段階方式の本番埋め込み）。
                    見つからなければスキップ（後方互換）。
        intro_video_html: 同梱の固定動画（`assets/video/intro_video.json`）の冒頭カード。
                    `fortunelib.intro_video.load_intro_video_card()` の戻り値を渡す（Cell N2 の
                    `EMBED_INTRO_VIDEO` が ON のとき）。既定 "" ＝付けない。
                    **目次の直前**に置く（autoplay はしない）。カード内のサムネイル
                    （poster）は画像枚数の集計から除く。

    Returns: 生成した HTML のパス
    """
    person_dir = Path(person_dir)
    pid = person_id or person_dir.name
    _DIR_FILE_CACHE.clear()          # mts4.8: 同一プロセスでの再生成でも最新のファイル構成を見る
    syn = person_dir / "synthesis_report.md"
    cluster_dir = person_dir / "cluster_reports"
    results_dir = person_dir / "results"

    # assets/images ルートを解決（images_dir が個別ディレクトリでもルートでも対応）
    assets_root = _resolve_assets_root(Path(images_dir) if images_dir else None)
    # images_dir が None でも、自動探索を試みる（kaggle/cellN2 対策）
    if assets_root is None:
        assets_root = _auto_discover_assets_root()

    # ---- mts5.53: 画像監査の初期化（P-1/P-4/P-7 の集計元）----
    IMAGE_AUDIT.clear()
    IMAGE_AUDIT.update({"images": 0, "decks_with_images": 0,
                        "decks_expected": 0, "missing_decks": [],
                        "no_assets_root": assets_root is None,
                        "assets_root": str(assets_root) if assets_root else ""})
    if assets_root is None:
        # mts5.53（P-7）: 「画像を指定していない実行」を正常と区別できるようにする
        print("  ⚠ 画像ディレクトリが指定されていないため、HTML に画像を1枚も埋め込みません"
              "（画像なしの成果物になります。バグではありませんが、意図した設定か確認してください）")

    parts, toc = [], []

    # 同梱の固定動画（冒頭カード・目次の直前）は呼び出し側が作って渡す（"" なら無し）。
    intro_video_html = intro_video_html or ""

    # mts5.22: トーン化データ（Stage D）があればタブ UI を有効化
    tone_data = load_tone_data(person_dir)

    # mts5.68: 相談内容は文書全体で**最初の 1 回だけ全文**（統合レポート冒頭の「ご相談」。
    # 無ければ最初に現れる個別占術）。以降の「■ 使用した入力」は 1 行の参照に置き換える。
    consult_seen: dict = {"shown": False, "replaced": 0, "saved": 0}

    # ---- 1. 統合レポート（標準を既定表示・mts5.46） ----
    if syn.exists():
        md = _strip_footer(syn.read_text(encoding="utf-8"))
        note_consultation_in_synthesis(md, consult_seen)
        syn_html = md_to_html(_drop_h1(md))
        switcher = (_synthesis_tone_tabs_html(tone_data)
                    if tone_data and tone_data.get("omake") else "")
        toc.append(("synthesis", "統合鑑定レポート"))
        parts.append(
            '<section id="synthesis" class="card">'
            '<h2>統合鑑定レポート</h2>'
            + switcher
            + f'<div id="synthesis-body" class="tone-text" data-unit="synthesis">{syn_html}</div>'
            + '<a class="totop" href="#top">▲ 目次へ</a>'
            + '</section>')

    # ---- 2. クラスター別（軸サマリー → 中間） ----
    if cluster_dir.is_dir():
        axis_files = sorted(cluster_dir.glob("AXIS_*.md"))
        mid_files = sorted(f for f in cluster_dir.glob("*.md")
                           if not f.name.startswith("AXIS_"))
        if axis_files or mid_files:
            toc.append(("clusters", "分野別レポート"))
            body = ['<section id="clusters" class="card">',
                    '<h2>分野別レポート</h2>',
                    '<p class="section-lead">占術を分野ごとにまとめた中間レポートです。'
                    'タップで開きます。</p>']
            for f in axis_files:
                md = _strip_footer(f.read_text(encoding="utf-8"))
                t = _title_of(md, f.stem)
                md = dedupe_consultation_md(md, consult_seen)          # mts5.68
                body.append(
                    f'<details class="item"><summary>{html.escape(t)}'
                    f'<span class="badge">軸サマリー</span></summary>'
                    f'<div class="body"><div class="tone-text" '
                    f'data-unit="axis_{html.escape(f.stem[len("AXIS_"):])}">'
                    f'{_linkify_consult_ref(md_to_html(_drop_h1(md)))}</div></div></details>')
            for f in mid_files:
                md = _strip_footer(f.read_text(encoding="utf-8"))
                t = _title_of(md, f.stem)
                md = dedupe_consultation_md(md, consult_seen)          # mts5.68
                body.append(
                    f'<details class="item"><summary>{html.escape(t)}'
                    f'<span class="badge">中間</span></summary>'
                    f'<div class="body"><div class="tone-text" '
                    f'data-unit="cluster_{html.escape(f.stem)}">'
                    f'{_linkify_consult_ref(md_to_html(_drop_h1(md)))}</div></div></details>')
            body.append('<a class="totop" href="#top">▲ 目次へ</a></section>')
            parts.append("\n".join(body))

    # ---- 3. 個別の占術 ----
    if results_dir.is_dir():
        files = sorted(f for f in results_dir.glob("*.md") if "_raw" not in f.name)
        if files:
            toc.append(("results", f"個別の占術（{len(files)}件）"))
            body = ['<section id="results" class="card">',
                    f'<h2>個別の占術（{len(files)}件）</h2>',
                    '<p class="section-lead">各占術の詳細です。'
                    'タップで開きます。</p>']
            # 画像タグを事前に生成（1枚選抜・本番埋め込み）
            # M23_meihua 用 + 新規4ツール
            _meihua_tag = _meihua_image_tag(person_dir, assets_root)
            # 汎用タグを事前生成して辞書化
            _image_tags = {}
            if assets_root is not None:
                # 各スラッグについて1枚ずつ生成
                for slug in ["M27_tarot","M27_marseille","M27_lenormand","M27_cartomancy","M26_iching",
                         "M27_kipper","M27_runes","M28_omikuji",
                         "M27_oracle","M27_angel",
                         "M09_animal","M11_genekeys",
                         "M02_seiza","M01_eto","M12_stone","M22_liuyao",
                         "M29_pendulum","M30_crystalball","M30_crystal",
                         "M29_african","M30_talisman","M30_meso","M30_christian",
                        "M27_urbantarot","M28_astragaloi","M30_haruspex",
                        "M30_ornith","M30_delphi",
                        "M03_kyusei","M04_numerology_birth","M06_kabbalah",
                        "M05_numerology_name","M07_chaldean","M04_tantra","M04_anka",
                        "M10_rokusei","M14_weton","M13_primbon",
                        "M16_seimei","M17_bazi","M19_vedic","M21_sanmei","M24_qimen",
                        "M18_western","M18_natal","M18_transit","M18_synastry",
                        "M20_ziwei","M25_hd","M15_parimicham"]:
                    # slug -> assets dir name mapping
                    if slug in ("M03_kyusei", "M04_numerology_birth", "M06_kabbalah",
                                  "M05_numerology_name", "M07_chaldean", "M04_tantra",
                                  "M04_anka", "M10_rokusei", "M14_weton", "M13_primbon",
                                  "M16_seimei", "M17_bazi", "M19_vedic", "M21_sanmei",
                                  "M24_qimen", "M18_western", "M18_natal",
                                  "M18_transit", "M18_synastry", "M20_ziwei",
                                  "M25_hd", "M15_parimicham"):
                        # 型C（mts5.16）: ベース画像＋calc 動的オーバーレイ（chartdraw）
                        from . import chartdraw as _chartdraw
                        # mts5.28: 同梱CJKフォントが無いと型Cの文字が豆腐（□□□）に
                        # なるため、警告を出す（Dataset 同梱物の不備・Kaggle 実機で発生）
                        if not _typec_font_warned[0]:
                            _typec_font_warned[0] = True
                            if not _chartdraw.uses_bundled_font():
                                import warnings as _warnings
                                _warnings.warn(
                                    "同梱CJKフォントが無いため、型Cの画像は文字が"
                                    "豆腐（□□□）になります。"
                                    "assets/fonts/typec_jp_subset.ttf を同梱してください"
                                    "（tools/make_typec_font.py で生成）",
                                    RuntimeWarning, stacklevel=2)
                        _image_tags[slug] = _chartdraw.typec_tag(
                            slug, person_dir, assets_root)
                    elif slug == "M27_tarot":
                        _image_tags[slug] = _generic_tarot_tag(person_dir, assets_root, "tarot")
                    elif slug == "M27_urbantarot":
                        _image_tags[slug] = _generic_tarot_tag(person_dir, assets_root, "urbantarot")
                    elif slug == "M27_marseille":
                        _image_tags[slug] = _generic_tarot_tag(person_dir, assets_root, "marseille")
                    elif slug == "M27_lenormand":
                        _image_tags[slug] = _generic_lenormand_tag(person_dir, assets_root)
                    elif slug == "M27_cartomancy":
                        _image_tags[slug] = _generic_cartomancy_tag(person_dir, assets_root)
                    elif slug == "M26_iching":
                        _image_tags[slug] = _generic_image_tag("M26_iching", person_dir, assets_root)
                    elif slug == "M27_kipper":
                        _image_tags[slug] = _generic_kipper_tag(person_dir, assets_root)
                    elif slug == "M27_runes":
                        _image_tags[slug] = _generic_runes_tag(person_dir, assets_root)
                    elif slug == "M28_omikuji":
                        _image_tags[slug] = _generic_omikuji_tag(person_dir, assets_root, pid)
                    elif slug == "M27_oracle":
                        _image_tags[slug] = _generic_oracle_tag(person_dir, assets_root)
                    elif slug == "M27_angel":
                        _image_tags[slug] = _generic_angel_tag(person_dir, assets_root)
                    elif slug == "M09_animal":
                        _image_tags[slug] = _generic_animal_tag(person_dir, assets_root)
                    elif slug == "M11_genekeys":
                        _image_tags[slug] = _generic_genekeys_tag(person_dir, assets_root)
                    elif slug == "M02_seiza":
                        _image_tags[slug] = _generic_seiza_tag(person_dir, assets_root)
                    elif slug == "M01_eto":
                        _image_tags[slug] = _generic_eto_tag(person_dir, assets_root)
                    elif slug == "M12_stone":
                        _image_tags[slug] = _generic_stone_tag(person_dir, assets_root)
                    elif slug == "M22_liuyao":
                        _image_tags[slug] = _generic_liuyao_tag(person_dir, assets_root)
                    elif slug == "M29_pendulum":
                        _image_tags[slug] = _generic_pendulum_tag(person_dir, assets_root)
                    elif slug == "M30_crystalball":
                        _image_tags[slug] = _generic_crystalball_tag(person_dir, assets_root)
                    elif slug == "M30_crystal":
                        _image_tags[slug] = _generic_crystal_tag(person_dir, assets_root)
                    elif slug == "M29_african":
                        _image_tags[slug] = _generic_african_tag(person_dir, assets_root)
                    elif slug == "M30_talisman":
                        _image_tags[slug] = _generic_talisman_tag(person_dir, assets_root)
                    elif slug == "M30_meso":
                        _image_tags[slug] = _generic_meso_tag(person_dir, assets_root)
                    elif slug == "M30_christian":
                        _image_tags[slug] = _generic_christian_tag(person_dir, assets_root)
                    elif slug == "M28_astragaloi":
                        _image_tags[slug] = _generic_astragaloi_tag(person_dir, assets_root)
                    elif slug == "M30_haruspex":
                        _image_tags[slug] = _generic_haruspex_tag(person_dir, assets_root)
                    elif slug == "M30_ornith":
                        _image_tags[slug] = _generic_ornith_tag(person_dir, assets_root)
                    elif slug == "M30_delphi":
                        _image_tags[slug] = _generic_delphi_tag(person_dir, assets_root)
            _audit_missing: list[str] = []          # 画像が付くはずなのに付かなかった占術
            _audit_nomatch: list[str] = []          # 今回の結果に対応する素材が無い（仕様）
            _audit_nodir: list[str] = []            # 素材ディレクトリが無い占術
            _audit_ok = 0
            for f in files:
                md = _strip_footer(f.read_text(encoding="utf-8"))
                t = _title_of(md, f.stem)
                t = re.sub(r"\s*\[.*?\]\s*", " ", t).strip()
                md = dedupe_consultation_md(md, consult_seen)          # mts5.68
                _inner = _linkify_consult_ref(md_to_html(_drop_h1(md)))
                # 各占術の先頭に該当画像を挿入（存在すれば）
                # mts5.22: 画像タグは tone-text の外に置く（トーン切替で画像を壊さない）
                _tag = ""
                if f.stem == "M23_meihua" and _meihua_tag:
                    _tag = _meihua_tag
                elif f.stem in _image_tags and _image_tags[f.stem]:
                    _tag = _image_tags[f.stem]
                elif f.stem == "M26_iching" and _image_tags.get("M26_iching"):
                    _tag = _image_tags["M26_iching"]
                if not _tag and f.stem in NO_IMAGE_NOTICE_SLUGS:
                    # mts5.15: 画像オミット確定の占術には仕様である旨を明示
                    _tag = _no_image_notice_tag(NOTICE_NO_IMAGE)
                if _tag and "data:image" in _tag:
                    _audit_ok += 1
                elif f.stem in NO_IMAGE_NOTICE_SLUGS:
                    pass
                elif NOTICE_NO_MATCH in _tag:
                    # 「今回の結果に対応する素材が無い」＝仕様（バグではない）。件数だけ残す
                    _audit_nomatch.append(f.stem)
                elif assets_root is not None and _deck_can_have_image(f.stem, assets_root):
                    # 画像が付くはずの占術なのに1枚も入らなかった＝欠落（mts5.53・P-1）
                    _audit_missing.append(f.stem)
                elif assets_root is not None and not _is_typec_slug(f.stem):
                    # 素材ディレクトリ自体が無い（隠した・欠けた・名前が違う）
                    _audit_nodir.append(f.stem)
                body.append(
                    f'<details class="item"><summary>{html.escape(t)}'
                    f'<span class="badge">{html.escape(f.stem)}</span></summary>'
                    f'<div class="body">{_tag}'
                    f'<div class="tone-text" data-unit="{html.escape(f.stem)}">'
                    f'{_inner}</div></div></details>')
            if _audit_missing or _audit_nodir:
                # mts5.53（P-1）: 画像の欠落を「仕様です」と混同させない（本文に明示）
                _broken = _audit_missing + [f"{s}（素材ディレクトリなし）" for s in _audit_nodir]
                body.insert(3, _no_image_notice_tag(
                    "⚠ 画像を埋め込めなかった占術があります（素材の欠落・読み込み失敗など。"
                    f"バグの可能性があります）: {', '.join(_broken)}"))
            IMAGE_AUDIT.update({
                "decks_with_images": _audit_ok,
                "decks_expected": sum(
                    1 for f in files
                    if f.stem not in NO_IMAGE_NOTICE_SLUGS
                    and _deck_can_have_image(f.stem, assets_root)),
                "missing_decks": list(_audit_missing),
                "no_match_decks": list(_audit_nomatch),
                "no_deck_dir_decks": list(_audit_nodir)})
            body.append('<a class="totop" href="#top">▲ 目次へ</a></section>')
            parts.append("\n".join(body))

    if not parts:
        raise RuntimeError(f"HTML化できる成果物がありません: {person_dir}")

    toc_html = "\n".join(
        f'<li><a href="#{i}">{html.escape(t)}</a></li>' for i, t in toc)
    stamp = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    head_title = title or f"占術統合レポート｜{pid}"

    doc = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<title>{html.escape(head_title)}</title>
<style>{CSS}{_video_css(intro_video_html)}</style>
</head>
<body>
<a id="top"></a>
<header class="hero"><div class="inner">
  <h1>{html.escape(head_title)}</h1>
  <div class="meta">生成 {stamp}／このファイル1枚で全内容が読めます（オフライン可）</div>
</div></header>
{_tone_ui_html(tone_data) if tone_data else ""}
<div class="wrap">
{intro_video_html}
<nav class="toc"><details open><summary>目次</summary><ol>
{toc_html}
</ol></details></nav>
{"".join(parts)}
<footer class="fin">{DISCLAIMER}</footer>
</div>
</body>
</html>
"""
    out = person_dir / f"{pid}_report.html"
    out.write_text(doc, encoding="utf-8")

    # ---- mts5.68: 相談内容の重複をまとめた結果（常時1行・監査にも記録）----
    IMAGE_AUDIT["consultation"] = {
        "shown_once": bool(consult_seen.get("shown")),
        "replaced": int(consult_seen.get("replaced") or 0),
        "saved_chars": int(consult_seen.get("saved") or 0)}
    if consult_seen.get("replaced"):
        print(f"  [相談内容] 全文は冒頭の 1 回だけ表示・"
              f"個別占術など {consult_seen['replaced']} 件は参照行に置換"
              f"（重複 {consult_seen['saved']:,} 字を削減）")

    # ---- mts5.53（P-1/P-10）: 画像監査の確定と警告（常時1行・台帳にも記録）----
    # mts5.69: 冒頭動画カードのサムネイル（poster）は占術画像ではないので数えない
    n_img = doc.count("data:image") - intro_video_html.count("data:image")
    n_ok = IMAGE_AUDIT.get("decks_with_images", 0)
    n_exp = IMAGE_AUDIT.get("decks_expected", 0)
    _nm = list(IMAGE_AUDIT.get("no_match_decks") or [])
    IMAGE_AUDIT["images"] = n_img
    if IMAGE_AUDIT.get("no_assets_root"):
        print(f"  [画像] 埋め込み {n_img}枚 / 画像ディレクトリ未指定"
              "（画像0枚の成果物。対象デッキ数は数えません）")
    else:
        # 「今回の結果に対応する素材が無い」＝仕様（誤充当より欠落を選ぶ方針）だが、
        # **どの占術なのか**は常に見えるようにする（素材の取り違えに気づけるように）
        # mts5.55: 「対象」と「素材あり」は数える対象が違う（前者＝結果が対応する占術、
        # 後者＝画像を実際に埋め込めた占術）。Kaggle 実機では Cell N2 が素材ディレクトリの
        # 数（48）を「画像あり48デッキ」と出していたため、**どちらを数えた数字か**を書き分ける。
        _line = (f"  [画像] 埋め込み {n_img}枚 / 対象 {n_exp}デッキ（結果の対応先）"
                 f" / 素材あり {n_ok}デッキ（実際に埋め込み）")
        if _nm:
            _line += (f"・対応素材なし {len(_nm)}: {', '.join(_nm[:6])}"
                      + (" ほか" if len(_nm) > 6 else ""))
        print(_line)

    def _warn(msg: str) -> None:
        print(f"  ⚠ {msg}")
        try:
            from .runcheck import add_warning
            add_warning(msg)
        except Exception:
            pass

    if IMAGE_AUDIT.get("no_deck_dir_decks"):
        _warn("素材ディレクトリが無い占術: " + ", ".join(IMAGE_AUDIT["no_deck_dir_decks"])
              + "（画像アセットの欠落・配置ミス。HTML には注記を入れました）")
    if IMAGE_AUDIT.get("missing_decks"):
        _warn("画像を埋め込めなかった占術: " + ", ".join(IMAGE_AUDIT["missing_decks"])
              + "（素材の欠落・読み込み失敗の可能性。HTML には注記を入れました）")
    if assets_root is None:
        _warn("画像ディレクトリ未指定のまま HTML を作成しました（画像0枚の成果物）")
    # 期待値との突合（任意・環境変数で指定したときだけ。既定は表示のみ）
    import os as _os
    _exp_img = (_os.environ.get("FORTUNE_EXPECT_IMAGES") or "").strip()
    if _exp_img.isdigit() and int(_exp_img) != n_img:
        _warn(f"埋め込み画像が期待値と違います: {n_img}枚（期待 {int(_exp_img)}枚）")
    _exp_deck = (_os.environ.get("FORTUNE_EXPECT_DECKS") or "").strip()
    if _exp_deck.isdigit() and int(_exp_deck) != n_ok:
        _warn(f"画像つきデッキ数が期待値と違います: {n_ok}（期待 {int(_exp_deck)}）")
    return out
