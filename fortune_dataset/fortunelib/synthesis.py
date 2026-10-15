# -*- coding: utf-8 -*-
"""
MTS統合レポートの共有プロンプト・出力ヘルパー。

  Stage B: クラスタごとの中間レポート
  Stage C: 手法軸／文化圏軸のサマリー、最終レポート、神々節

全占術の本文を一度に投入せず、クラスタ単位に分割して要約することで
各段階の入力を安全な範囲に収める。`final_report.md` は索引、
`synthesis_report.md` は読者向けの統合本文として両方を残す。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .registry import REGISTRY

JST = timezone(timedelta(hours=9))

# ------------------------------------------------------------------
# ★TUNE-02（2026-08-18 実測に基づく）: 「指示字数」と「検証字数」を分離する
#
#   実機データから、LLM の出力字数は【指示した下限に比例】することが判った。
#     出力 ≒ 指示下限 × 1.085（σ 0.080・n=14）
#   指示と検証を同じ値にすると、約14%が下限をわずかに割って再生成が発火する
#   （実機では 15工程中5件が発火し、1件あたり約2.7倍の時間を要した）。
#
#   そこで【指示は検証下限の約1.10倍】に設定する。すると
#     ・出力は約10%増える（品質↑）
#     ・下限割れの確率が 14.4% → 1.4% に下がり、再生成がほぼ消える（時間↓）
#   という両取りになる（試算: 45.2分/18,336字 → 44.7分/20,170字）。
#
#   上限は据え置き。上振れは元々ほとんど起きていないため。
# ------------------------------------------------------------------
INSTRUCT_MARGIN = 1.10          # 指示下限 = 検証下限 × この係数（短文用）
INSTRUCT_MARGIN_LONG = 1.22     # 長文（3000字超）用のマージン
LONG_THRESHOLD = 3000

# ★TUNE-03（2026-08-18 実機で判明）: 指示に対する伸び率は長さに依存する。
#   実測: 1200字級 → 比 1.24 ／ 3800字級 → 比 1.02
#   長文ほど指示下限に張り付くため、同じ係数では最終レポートだけ発火した
#   （2/15工程のうち1件）。長文には大きめのマージンを当てる。
#
# ★TUNE-04（2026-08-25 10回目の実機で判明）: LONG を 1.18 → 1.22 に引き上げ。
#   10回目は発火0で合格したが、最終統合が 3,559字（検証下限 3,400）と
#   余裕わずか159字（指示下限 4,012 に対し比 0.89 で下振れ）。
#   個体差で下振れすると発火し得るため安全側に寄せる。
#   1.22 → 指示下限 4,148字（+136字、約 +20秒の見込み）。上限は据え置き。


def _instruct_range(lo: int, hi: int) -> tuple:
    """検証レンジ (lo, hi) → プロンプトに書く指示レンジ"""
    margin = INSTRUCT_MARGIN_LONG if lo >= LONG_THRESHOLD else INSTRUCT_MARGIN
    return int(lo * margin), hi


# 1件あたりに渡す抜粋の上限（クラスタ入力が膨らみすぎないように）
EXCERPT_CHARS = 420
# 中間レポート1本に渡す抜粋の合計上限（概算トークン ≒ 文字数）
CLUSTER_INPUT_BUDGET = 5200

FOOTER = (
    "---\n"
    "※ 本レポートはエンターテインメント目的のシミュレーションであり、"
    "事実を表すものではありません。\n"
    "※ 医療・法律・投資・人生の重大な決定には利用しないでください。\n"
    "※ 疑似体験モード（象徴・霊性クラスタ）の内容は、体系の語彙を模した"
    "創作文章です。"
)


# ---------------------------------------------------------------
# 入力の収集
# ---------------------------------------------------------------
def _read_result(results_dir: Path, slug: str) -> dict | None:
    """{mcode}_{slug}_raw.json を読む"""
    entry = REGISTRY.get(slug)
    if not entry:
        return None
    p = results_dir / f"{entry['mcode']}_{slug}_raw.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    """鑑定文の要点を抜き出す（見出し・空行を畳んで先頭 limit 字）"""
    t = re.sub(r"\s+", " ", (text or "").strip())
    return t[:limit] + ("…" if len(t) > limit else "")


MIN_EXCERPT_CHARS = 150   # これ以上は削らない（下回るなら件数を絞るしかない）


def collect_cluster_inputs(results_dir, cluster: dict,
                           budget: int = CLUSTER_INPUT_BUDGET) -> list:
    """クラスタに属する占術の抜粋を集める。

    ★重要: 予算超過時に「先頭から詰めて後ろを捨てる」と、
      25種のクラスタで12種が黙って落ちてしまう（＝レポートに反映されない）。
      そこで【件数に応じて1件あたりの抜粋長を自動調整】し、
      クラスタ内の全占術を必ず収載する。
    """
    results_dir = Path(results_dir)

    available = []
    for slug in cluster["slugs"]:
        raw = _read_result(results_dir, slug)
        if not raw:
            continue
        text = raw.get("result", {}).get("text", "")
        if text:
            available.append((slug, text))
    if not available:
        return []

    # 1件あたりの割り当て（下限 MIN_EXCERPT_CHARS・上限 EXCERPT_CHARS）
    per = max(MIN_EXCERPT_CHARS, min(EXCERPT_CHARS, budget // len(available)))

    items = []
    for slug, text in available:
        items.append({"slug": slug, "name": REGISTRY[slug]["name"],
                      "group": REGISTRY[slug]["group"],
                      "excerpt": _excerpt(text, per)})
    return items


# ---------------------------------------------------------------
# 段階1: クラスタ中間レポート
# ---------------------------------------------------------------
def build_cluster_prompt(cluster: dict, items: list, facts: dict,
                         consultation: str, target_date: str = "") -> tuple:
    """中間レポート用の (system, user) プロンプト"""
    sys_p = (
        "あなたは複数の占術体系を横断して読み解く鑑定編集者です。\n"
        "与えられた複数の占術結果を統合し、読者が全体像を掴めるレポートを書きます。\n\n"
        "【絶対ルール】\n"
        "1. 与えられた鑑定文に書かれていない事実・数値・シンボルを創作しないこと。\n"
        "2. 体系ごとの結論が食い違う場合、無理に一致させず「異なる観点」として併記すること。\n"
        "3. 断定を避け、「〜傾向があります」「〜しやすいでしょう」等の助言形で書くこと。\n"
        "4. 医療・法律・投資・生命に関わる断定的助言はしないこと。\n"
        "5. 見出し（#）や表は使わず、段落による文章で書くこと。\n"
        "6. 出力は本文のみ。前置き・自己言及・結びの定型句は書かないこと。\n\n"
        f"【このクラスタ】{cluster['title']}\n{cluster['desc']}\n\n"
        "【出力構成】①このクラスタ全体に共通して見える傾向 "
        "②特に注目すべき体系とその読み（2〜4件） "
        "③体系間で見解が分かれる点（あれば） ④このクラスタからの助言\n"
        f"【分量】{_instruct_range(*CLUSTER_CHARS)[0]}〜{CLUSTER_CHARS[1]}字（この範囲を必ず守ること）"
    )
    if cluster["id"] in ("M-E", "C-MO"):
        sys_p += ("\n【注意】この群は疑似体験モード（体系の語彙を模した創作）を含みます。"
                  "断定的な予言や治療効果の主張をせず、象徴的な読み物として記述してください。")

    lines = ["# 相談者のプロファイル事実（確定済み・改変禁止）"]
    lines += [f"{k}: {v}" for k, v in facts.items() if not k.startswith("_")]
    lines.append("")
    lines.append(f"# 相談内容\n{consultation or '（なし・今日の運勢モード）'}")
    if target_date:
        lines.append(f"対象日: {target_date}")
    lines.append("")
    lines.append(f"# このクラスタの占術結果（{len(items)}件・抜粋）")
    for it in items:
        lines.append(f"\n## {it['name']}\n{it['excerpt']}")
    lines.append("\n# 依頼")
    lines.append("上記を統合し、出力構成に従って中間レポートを書いてください。")
    return sys_p, "\n".join(lines)


# ---------------------------------------------------------------
# 段階2: 最終統合レポート
# ---------------------------------------------------------------
# ---------------------------------------------------------------
# 実行
# ---------------------------------------------------------------
def _gen(backend, sys_p, usr_p, temperature, max_tokens, seed=None) -> str:
    return (backend.generate(sys_p, usr_p, temperature=temperature,
                             max_tokens=max_tokens, seed=seed) or "").strip()


def _fits(text: str, lo: int, hi: int) -> bool:
    return lo <= len(text.strip()) <= hi


# ---------------------------------------------------------------
# 両軸統合（3段階）: 軸サマリー → 最終
# ---------------------------------------------------------------
AXIS_LABEL = {"method": "手法軸（計算の確からしさで分類）",
              "culture": "文化圏軸（発祥の文化で分類）"}

AXIS_SUMMARY_CHARS = (1200, 2200)      # 検証レンジ
CLUSTER_CHARS = (950, 2100)            # 検証レンジ（中間レポート）
# ★mts5.58（2026-09-30・ユーザー決定）: 最終レポートの下限を上げて、標準本文を
#   「毎回 4,000字前後」に揃える。実機4回の実測＝本文 3,434／3,471／3,978／4,745字
#   （旧レンジ 3400〜4800・指示下限 4,148字）で、下振れ（指示に対する実測比 0.83〜0.96）
#   のぶんだけ小さめに出ていた。対策は3つで、いずれも**プロンプトの指示と検証だけ**の変更
#   （占術の計算・事実・プロファイルは不変）:
#   ① 検証レンジの下限を 3,400 → **4,000**（4,000 を割ったら1回だけ再生成。上限は 4,800 → 4,900）
#   ② プロンプトの【分量】は **4,400〜4,900字**（FINAL_INSTRUCT_CHARS）。
#      比例マージン（1.22）では下限が 4,880 になり上限に張り付くため、最終レポートだけ
#      明示の指示レンジを使う（下振れを見込んで下限を 400字 上乗せ）。
#   ③ 出力構成の章ごとの予算も合計 4,400字へ引き上げる（章の足し上げと全体指示の一致）。
#
# ★mts5.60（2026-09-30・ユーザー決定）: mts5.58 の実機で **3,716字**（対 指示下限 4,400字で
#   実測比 0.84）となり、新しい下限 4,000字に届きませんでした（503 の連鎖で上位モデルが
#   使えない縮退運転だったことも重なる）。**作り直しの回数は増やさず**（＝呼び出し回数は
#   最大2回のまま）、**指示の下限そのものを 4,400 → 4,800字へ引き上げ**ます
#   （実測比 0.84 でも 4,032字＝下限 4,000 を上回る計算）。あわせて
#   ① 章の足し上げを 4,800字へ（全体指示の下限 4,800 と一致させる）
#   ② 検証レンジの上限は 4,900 → **5,300**（指示の上限 5,200 の出力を「長すぎ」と
#      警告しないため。下限は 4,000 のまま）
#   ③ max_tokens（文字数ベース）を 5,600 → **6,400**（上限 5,200字で切れないように）
FINAL_CHARS = (4000, 5300)             # 検証レンジ（最終レポート）
FINAL_INSTRUCT_CHARS = (4800, 5200)    # プロンプトに書く指示レンジ（最終レポートのみ明示）


def build_axis_summary_prompt(axis: str, cluster_reports: list, facts: dict,
                              consultation: str, target_date: str = "",
                              budget: int = 5600) -> tuple:
    """1つの軸の中間レポート群 → その軸の総括（段階2）"""
    sys_p = (
        "あなたは複数の占術体系を横断して読み解く鑑定編集者です。\n"
        f"以下は「{AXIS_LABEL.get(axis, axis)}」で分類した各分野の中間レポートです。\n"
        "この軸から見たときに全体がどう読めるかを総括します。\n\n"
        "【絶対ルール】\n"
        "1. 中間レポートに無い事実・数値を創作しないこと。\n"
        "2. 分野間で結論が食い違う場合、無理に一致させず併記すること。\n"
        "3. 断定を避け助言形で書くこと。医療・法律・投資への断定的助言はしないこと。\n"
        "4. 見出しや表は使わず、段落による文章で書くこと。\n"
        "5. 出力は本文のみ。前置き・自己言及は書かないこと。\n"
        "6. 氏名を記す場合は、プロファイル事実の『氏名（漢字）』を正確に転記すること。"
        "ローマ字から漢字を推定せず、氏名に触れない場合は『あなた』と呼ぶこと。\n\n"
        "【出力構成】①この軸から見た全体像 ②分野をまたいで繰り返し現れた主題 "
        "③この軸ならではの気づき（分類の仕方によって見えてくること） "
        "④分野間で見解が分かれた点\n"
        f"【分量】{_instruct_range(*AXIS_SUMMARY_CHARS)[0]}〜{AXIS_SUMMARY_CHARS[1]}字（この範囲を必ず守ること）"
    )
    lines = ["# 相談者のプロファイル事実（確定済み・改変禁止）"]
    lines += [f"{k}: {v}" for k, v in facts.items() if not k.startswith("_")]
    lines.append("")
    lines.append(f"# 相談内容\n{consultation or '（なし・今日の運勢モード）'}")
    if target_date:
        lines.append(f"対象日: {target_date}")
    lines.append("")
    lines.append(f"# 「{AXIS_LABEL.get(axis, axis)}」の分野別中間レポート")
    used = 0
    for r in cluster_reports:
        body = r["text"].strip()
        room = budget - used
        if room < 300:
            break
        if len(body) > room:
            body = body[:room] + "…"
        lines.append(f"\n## {r['title']}（{r['count']}種）\n{body}")
        used += len(body)
    lines.append("\n# 依頼")
    lines.append("上記を統合し、出力構成に従ってこの軸の総括を書いてください。")
    return sys_p, "\n".join(lines)


def build_crossaxis_final_prompt(axis_summaries: list, facts: dict,
                                 consultation: str, target_date: str = "",
                                 budget: int = 6000) -> tuple:
    """複数軸の総括 → 最終レポート（段階3）"""
    sys_p = (
        "あなたは複数の占術体系を横断して読み解く主任鑑定編集者です。\n"
        "同じ鑑定結果を【2つの異なる分類軸】で総括したレポートが与えられます。\n"
        "両者を突き合わせ、相談者本人が読むための最終レポートを書きます。\n\n"
        "【絶対ルール】\n"
        "1. 与えられた総括に無い事実・数値・シンボルを創作しないこと。\n"
        "2. 軸によって見え方が異なる場合、それ自体を洞察として扱うこと。\n"
        "   （例: 手法軸では慎重論が優勢だが、文化圏軸では東アジア系が積極的、など）\n"
        "3. 体系間・軸間の不一致は無理に解消せず、誠実に示すこと。\n"
        "4. 断定を避け助言形で書くこと。運命の決めつけをしないこと。\n"
        "5. 医療・法律・投資・生命に関わる断定的助言はしないこと。\n"
        "6. 相談者に語りかける文体で、専門用語には短い補足を添えること。\n"
        "7. 見出しは ## まで使ってよい。表とコードブロックは使わないこと。\n"
        "8. 出力は本文のみ。前置きや自己言及は書かないこと。\n"
        "9. 氏名を記す場合は、プロファイル事実の『氏名（漢字）』を正確に転記すること。"
        "ローマ字から漢字を推定せず、氏名に触れない場合は『あなた』と呼ぶこと。\n\n"
        "【出力構成】\n"
        "① 総括（この鑑定全体で最も強く示されたこと・550字程度）\n"
        "② あなたという人（複数体系が重ねて指摘する資質・1000字程度）\n"
        "③ 相談内容への答え（各分野の読みを束ねた見解・1200字程度）\n"
        "④ 二つの視点（手法軸と文化圏軸で何が違って見えたか・1000字程度）\n"
        "⑤ 見方が分かれる点（率直に併記・450字程度）\n"
        "⑥ これからの過ごし方（具体的な行動の提案・600字程度）\n"
        # mts5.58/5.60: 章の足し上げ（4,800字）と全体指示の下限（4,800字）を一致させる
        f"【分量】全体で{FINAL_INSTRUCT_CHARS[0]}〜{FINAL_INSTRUCT_CHARS[1]}字（この範囲を必ず守ること）"
    )
    lines = ["# 相談者のプロファイル事実（確定済み・改変禁止）"]
    lines += [f"{k}: {v}" for k, v in facts.items() if not k.startswith("_")]
    lines.append("")
    lines.append(f"# 相談内容\n{consultation or '（なし・今日の運勢モード）'}")
    if target_date:
        lines.append(f"対象日: {target_date}")
    lines.append("")
    used = 0
    for a in axis_summaries:
        body = a["text"].strip()
        room = budget - used
        if room < 300:
            break
        if len(body) > room:
            body = body[:room] + "…"
        lines.append(f"\n# 【{AXIS_LABEL.get(a['axis'], a['axis'])}】からの総括\n{body}")
        used += len(body)
    lines.append("\n# 依頼")
    lines.append("2つの軸の総括を突き合わせ、出力構成に従って最終レポートを書いてください。")
    return sys_p, "\n".join(lines)

def normalize_subject_name(text: str, facts: dict) -> str:
    """ローマ字氏名に括弧で添えられた誤った漢字名を正本へ直す。

    Stage C本文で氏名を再構成した場合でも、ローマ字と隣接して現れる表記は
    入力の漢字名へ置換する。無関係な日本語語句は変更しない。
    """
    canonical = str(facts.get("氏名（漢字）") or "").strip()
    romaji = str(facts.get("氏名（ヘボン式）") or "").strip()
    if not text or not canonical or not romaji:
        return text
    romaji_parts = [p for p in re.split(r"\s+", romaji) if p]
    if not romaji_parts:
        return text
    romaji_pattern = r"[ \t\u3000]+".join(re.escape(p) for p in romaji_parts)
    jp_char = r"[\u3040-\u30ff\u3400-\u9fff々〆〇ヶー・]"
    # 本文の文頭から括弧までを氏名扱いしないよう、入力氏名の文字数と同じ
    # 長さだけを置換対象にする。日本語の説明文には名前との境界が無い場合があり、
    # 幅広い「漢字ラン」では「今回の対象は星野明理」全体を誤置換するため。
    name_len = len(re.findall(jp_char, canonical))
    if name_len < 2:
        return text
    alias = rf"(?:{jp_char}[ \u3000]*){{{name_len}}}"
    pattern = re.compile(
        rf"(?P<alias>{alias})(?P<paren>[ \t\u3000]*[（(][ \t\u3000]*"
        rf"{romaji_pattern}[ \t\u3000]*[）)])",
        re.IGNORECASE,
    )
    return pattern.sub(lambda m: f"{canonical}（{romaji}）", text)

def write_synthesis_file(out_dir, final: str, facts: dict, consultation: str,
                         target_date: str, per_axis: dict,
                         axis_summaries: list) -> Path:
    """synthesis_report.md を書き出す（両軸版）"""
    out_dir = Path(out_dir)
    final = normalize_subject_name(final, facts)
    total = sum(r["count"] for reps in per_axis.values() for r in reps)
    n_axes = len(per_axis)
    head = ["# 統合鑑定レポート", "",
            f"**生成**: {datetime.now(JST).isoformat(timespec='seconds')}"
            f"／**分類軸**: {' + '.join(per_axis.keys())}"
            f"／**参照**: {total // max(1, n_axes)}種", ""]
    if consultation:
        head += [f"**ご相談**: {consultation}", ""]
    elif target_date:
        head += [f"**対象日**: {target_date}（今日の運勢モード）", ""]
    head += ["## あなたのプロファイル", ""]
    head += [f"- {k}: {v}" for k, v in facts.items() if not k.startswith("_")]
    head += ["", "---", ""]

    toc = ["", "---", "", "## 軸サマリー", ""]
    for a in axis_summaries:
        toc.append(f"- **{AXIS_LABEL.get(a['axis'], a['axis'])}**"
                   f"（{len(a['text'])}字）: `cluster_reports/AXIS_{a['axis']}.md`")
    toc += ["", "## 分野別の中間レポート", ""]
    for axis, reps in per_axis.items():
        toc.append(f"### {AXIS_LABEL.get(axis, axis)}")
        for r in reps:
            toc.append(f"- **{r['title']}**（{r['count']}種・{r['chars']}字）: "
                       f"`cluster_reports/{r['id']}_{axis}.md`")
        toc.append("")

    path = out_dir / "synthesis_report.md"
    path.write_text("\n".join(head) + final + "\n" + "\n".join(toc)
                    + "\n" + FOOTER + "\n", encoding="utf-8")
    return path


def append_deities_section(synthesis_path, deities_calc: dict, text: str) -> Path:
    """統合レポートの末尾に「御縁のある神さま」節を追記する。

    神々の選定は統合レポート完成後に行うため、本文をいったん書き出してから
    この関数で追記する（＝全占術＋統合の総意を踏まえた選定になる）。
    """
    p = Path(synthesis_path)
    body = p.read_text(encoding="utf-8")

    lines = ["", "---", "", "## 御縁のある神さま Top10", "",
             "*全占術と統合レポートの内容を踏まえて選定しています。*", ""]
    for d in deities_calc.get("ranking", []):
        reasons = "／".join(d.get("affinity_reasons", [])) or "今日の縁"
        lines.append(f"{d['rank']}. **{d['name']}**（{d['pantheon']}・{d['domain']}）"
                     f" — {reasons}")
    lines += ["", text.strip(), ""]

    # フッタの前に差し込む
    marker = "---\n※ 本レポートはエンターテインメント"
    if marker in body:
        head, foot = body.split(marker, 1)
        new = head + "\n".join(lines) + "\n" + marker + foot
    else:
        new = body + "\n".join(lines)
    p.write_text(new, encoding="utf-8")
    return p

