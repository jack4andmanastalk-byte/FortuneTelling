# -*- coding: utf-8 -*-
"""
占術パイプライン（Phase 4・ローカル実装）
- run_divination: 1占術の実行（プロンプト構築→生成→検証→再生成→保存→サマリー追記）
- スキップガード: results/{mcode}_{slug}.md が存在すればスキップ（mts5.53: 入力指紋で検証）
- 結果保存: {mcode}_{slug}.md（人間向け）＋ {mcode}_{slug}_raw.json（構造化）
- サマリー追記: profile_summary.json の themes に要点を追記（追記のみ・書き換え禁止）
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

from . import validate
from .backend import LLMBackend
from .prompt import build_system_prompt, build_user_prompt, sanitize, get_prompt_def
from .profile import to_dict
from .lineage import allowed_facts, lineage_note, neutral_context
from .registry import REGISTRY, availability_reason
from .schema import build_result

JST = timezone(timedelta(hours=9))

FOOTER = (
    "---\n"
    "※ 本結果はエンターテインメント目的のシミュレーションであり、事実を表すものではありません。\n"
    "※ 医療・法律・投資・人生の重大な決定には利用しないでください。"
)

FOOTER_PSI = (
    "※ 本占術は疑似体験モードです。体系の語彙・形式を模した創作文章であり、"
    "実際の鑑定・予知・治療ではありません。"
)

FOOTER_BARNUM = (
    "※ 本占術の記述は普遍的・一般的な表現を含みます（バーナム効果）。"
    "誰にでも当てはまりやすい内容である点にご留意ください。"
)

APPROX_NOTE = (
    "⚠ 出生時刻が不明のため正午（12:00）扱い・出生地は東京扱いで計算しています。"
    "時刻の影響が大きい占術（ヒューマンデザイン・紫微斗数・四柱推命・占星術系）では、"
    "正確な時刻が判明すれば結果が変わることがあります。"
)

BARNUM_HIGH = {"delphi", "crystalball", "crystal", "talisman", "african", "christian", "meso", "haruspex", "ornith"}


@dataclass
class PipelineContext:
    """パイプライン実行コンテキスト"""
    inputs: object                     # NormalizedInput
    profile_facts: dict = field(default_factory=dict)
    calc_results: dict = field(default_factory=dict)
    consultation: str = ""
    results_dir: Path = Path("results")
    summary_path: Path = Path("profile_summary.json")
    backend: LLMBackend | None = None
    seed: int | None = None
    regenerate_on_issue: bool = True
    max_regenerate: int = 1
    now: datetime | None = None
    summary_lock: object | None = None   # threading.Lock（MTS 時の themes 追記直列化）


def _result_paths(ctx: PipelineContext, entry: dict) -> tuple[Path, Path]:
    md = ctx.results_dir / f"{entry['mcode']}_{entry['slug']}.md"
    raw = ctx.results_dir / f"{entry['mcode']}_{entry['slug']}_raw.json"
    return md, raw


# ---- mts5.53（P-2/P-9）: 入力指紋とモデル名の記録 ------------------------------- #
# 監査の指摘: スキップガードは「md の存在＝前回の成功」だけで判定していたため、
# 生年月日・相談内容・対象日などを変えて再実行しても、**古い鑑定文が黙って**そのまま
# 残った（実機では未発動だが、再実行のたびに同じ罠がある）。ここでは実行入力の指紋を
# raw JSON に記録し、md を再利用する前に突合する。
#   - 指紋が一致   → 再利用（無駄な再生成をしない＝従来の意図を保つ）
#   - 指紋が不一致 → **作り直す**（入力が変わっている＝古い結果は無効）
#   - 指紋が無い（旧版の成果物）→ 再利用するが、警告として残す
#: 指紋の方式。v2 = 入力＋対象日＋seed（**calc を含めない**＝抽選系の引き直しと両立）。
#: 指紋の無い成果物（v2 以前の実行）は「指紋なし」として再利用しつつ警告に残す。
FINGERPRINT_VERSION = 2

#: 再利用の内訳（1実行分の集計。呼び出し側が読む）
SKIP_STATS: dict = {"fingerprint_match": 0, "no_fingerprint": 0, "stale_regenerated": 0}


def reset_skip_stats() -> dict:
    """再利用の内訳を0に戻す（mts5.55）。

    このカウンタは**プロセス共通**なので戻さないと前の実行の数値が次へ持ち越されます。
    実際に mts5.54 の Kaggle 実機では、**セルフテスト（Cell 0.1）で起きた再利用の内訳**が
    本番セル（Cell 1）のログと警告に混ざり、「本番では1件も再利用していないのに
    『旧版の成果物を1件 再利用しました』」と表示されました（`RUN_STRICT=1` のときは
    **本番セルが誤って不合格**になります）。`run_person_mts`（人ごとの冒頭）と
    本番セル（Cell 1・Cell N2）・ローカル生成ツールの冒頭でこれを呼びます。
    """
    for _k in SKIP_STATS:
        SKIP_STATS[_k] = 0
    return SKIP_STATS


def skip_stats_total(stats: dict | None = None) -> int:
    """再利用の内訳の合計（0 なら「今回は再利用なし」＝ログを出さない）。"""
    _s = SKIP_STATS if stats is None else stats
    return sum(int(_s.get(_k) or 0) for _k in SKIP_STATS)


def _json_stable(obj) -> str:
    """辞書順に固定した JSON 文字列（指紋計算用）。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


def input_fingerprint(ctx: PipelineContext, entry: dict) -> str:
    """この占術の出力を決める**入力**の指紋（先頭16桁）。指紋が変われば作り直す。

    ※ `calc`（計算結果）は**入れない**。タロット・ルーン・おみくじ等の抽選系は
      実行のたびに引き直すのが仕様で、calc を混ぜると「同じ入力でも毎回作り直し」に
      なり、スキップガード（＝レジュームのための機構）が機能しなくなるため。
      抽選系の結果は raw JSON 側に calc ごと残るので、後から追跡できる。
      日付に依存する部分は `target_date`（今日の運勢モードの対象日）で捉える。
    """
    payload = {
        "v": FINGERPRINT_VERSION,
        "mcode": entry["mcode"],
        "slug": entry["slug"],
        "prompt_id": entry["prompt_id"],
        "inputs": to_dict(ctx.inputs),
        "target_date": ctx.calc_results.get("target_date"),
        "seed": ctx.seed,
        "consultation": (ctx.consultation or "").strip(),
        # G6（創作系）はプロフィール事実と必須言及も結果を左右する
        "facts": (ctx.profile_facts if entry["group"] == "G6" else None),
        "must_mention": (_must_mention_facts(entry, ctx)
                         if entry["group"] == "G6" else None),
    }
    return hashlib.sha256(_json_stable(payload).encode("utf-8")).hexdigest()[:16]


def stored_fingerprint(raw_path: Path) -> str | None:
    """raw JSON に記録された入力指紋（旧版の成果物なら None）。"""
    try:
        if not Path(raw_path).exists():
            return None
        data = json.loads(Path(raw_path).read_text(encoding="utf-8")) or {}
        return data.get("input_fingerprint") or None
    except Exception:
        return None


def model_meta(backend, hint: str = "") -> dict:
    """結果を書いたモデル名とフォールバックの有無（mts5.53・P-9）。

    監査の指摘: `*_raw.json` にはモデル名が1つも残っておらず、どのモデルが書いた
    鑑定文かを後から追えなかった（`model_plan.json` の変更や 404 フォールバックの
    影響調査ができない）。バックエンドが名前を持たない場合は "(不明)"。
    """
    requested = str(getattr(backend, "model_name", "") or "").strip()
    resolved = str(getattr(backend, "resolved_model_name", "") or requested).strip()
    if not requested and hint:
        # バックエンドが名乗らない場合（モック・検証用）は MTS の担当レーン名を使う
        requested = resolved = str(hint).strip()
    if not requested and not resolved:
        return {"name": "(不明)", "requested": "", "fallback": False}
    return {
        "name": resolved or requested,
        "requested": requested or resolved,
        "fallback": bool(requested and resolved and requested != resolved),
    }


def _badges(entry: dict, ctx: PipelineContext) -> list:
    badges = []
    if entry["group"] == "G6":
        badges.append("疑似体験")
    if any(f.startswith(("time_unknown", "place_unknown", "partner_")) for f in ctx.inputs.approx_flags):
        badges.append("近似")
    return badges


def _render_markdown(entry: dict, ctx: PipelineContext, text: str,
                     issues: list, calc_result: dict | None,
                     model_info: dict | None = None) -> str:
    d = get_prompt_def(entry["prompt_id"])
    badges = _badges(entry, ctx)
    badge_str = "　".join(f"[{b}]" for b in badges)

    lines = [f"# {entry['name']}　{badge_str}", ""]
    lines.append(f"**体系**：{d['system_desc']}／**グループ**：{entry['group']}／**実行**：{datetime.now(JST).isoformat(timespec='seconds')}")
    lines.append("")

    if any(f.startswith(("time_unknown", "place_unknown")) for f in ctx.inputs.approx_flags):
        lines.append(f"> {APPROX_NOTE}")
        lines.append("")

    lines.append("## ■ 使用した入力")
    b = ctx.inputs.birth
    lines.append(f"- 生年月日：{b.date.isoformat()}／時刻：{b.time}（{'近似' if b.time_unknown else '実入力'}）"
                 f"／出生地：{b.place_name}（{'近似' if b.place_unknown else '実入力'}）")
    # 対象日（今日の運勢モード・⑦拡張）
    # mts4.1表示層ゲート: 相談ありで対象日が空欄（実行日フォールバック）のときは
    # 出力文章に日付を含めない（内部計算は実行日を維持）。今日の運勢モード、
    # もしくはCSV target欄の明示指定がある場合だけ表示する。明示指定は
    # inputs から導出し、calc スキーマは不変（B案統合）。
    t = ctx.calc_results.get("target_date", {})
    _today_mode = not (ctx.inputs.consultation or "").strip()
    _explicit_target = ctx.inputs.target_date is not None
    if isinstance(t, dict) and t.get("date") and (_today_mode or _explicit_target):
        lines.append(f"- 対象日：{t['date']}（{'今日' if t.get('is_today') else '指定日'}）")
    if ctx.inputs.partner:
        pb = ctx.inputs.partner
        lines.append(f"- 相手：{pb.date.isoformat()}／時刻：{pb.time}（{'近似' if pb.time_unknown else '実入力'}）")
    if ctx.inputs.name_kanji:
        lines.append(f"- 氏名：{ctx.inputs.name_kanji}（{ctx.inputs.name_kana} → {ctx.inputs.name_romaji}）")
    if ctx.inputs.blood_type != "unknown":
        lines.append(f"- 血液型：{ctx.inputs.blood_type}型")
    lines.append(f"- 相談内容：{ctx.consultation or '（なし・全般的な運勢）'}")
    lines.append("")

    if calc_result is not None:
        lines.append("## ■ 計算結果（事実）")
        lines.append("```json")
        lines.append(json.dumps(calc_result, ensure_ascii=False, default=str, indent=1))
        lines.append("```")
        lines.append("")

    lines.append("## ■ 鑑定文")
    lines.append("")
    lines.append(text)
    lines.append("")

    lines.append("## ■ この占術について")
    lines.append(f"- 体系：{d['system_desc']}")
    lines.append(f"- 文体：{d['style']}／出力構成：{d['output_structure']}（{d['char_min']}〜{d['char_max']}字）")
    # mts5.53（P-9）: どのモデルが書いたか（フォールバックの有無つき）を残す
    if model_info:
        _fb = "（指定モデルからフォールバック）" if model_info.get("fallback") else ""
        lines.append(f"- 生成モデル：{model_info.get('name') or '(不明)'}{_fb}")
    if issues:
        lines.append(f"- バリデーション警告：{'／'.join(issues)}")
    lines.append("")

    footer = [FOOTER]
    if entry["group"] == "G6":
        footer.append(FOOTER_PSI)
    if entry["slug"] in BARNUM_HIGH:
        footer.append(FOOTER_BARNUM)
    lines.append("\n".join(footer))
    return "\n".join(lines)


# 鑑定文中にそのまま書くのが不自然な事実（必須言及の対象から外す）
_NOT_QUOTABLE = {"氏名（ヘボン式）", "氏名（漢字）", "氏名（かな）",
                 "相手の生年月日"}

# ラベル → 本文で使われる代表的な言い回し（数値事実の照合用）
_NUMERIC_FACT_ALIASES = {
    "ライフパス": ("ライフパス{v}", "ライフパスナンバー{v}", "ライフパス・ナンバー{v}"),
    "運命数": ("運命数{v}",),
    "星数": ("星数{v}",),
}


def _summary_context(ctx: PipelineContext, limit: int = 12) -> str:
    """profile_summary.json の themes（＝final_report の「各占術の要点」）を返す。

    「御縁のある神さま」は他の占術の結果を踏まえて読むため、
    実行済み占術のサマリーを文脈として渡す（統合レポートと同じ情報源）。
    """
    if not ctx.summary_path.exists():
        return ""
    try:
        s = json.loads(ctx.summary_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    themes = s.get("themes") or []
    if not themes:
        return ""
    return "\n".join(f"- {t}" for t in themes[-limit:])


def _must_mention_facts(entry: dict, ctx: PipelineContext) -> list:
    """G6: 織り込み必須のプロファイル事実（値の一覧）

    ★BUG-14（2026-08-17 実機で判明）: 旧実装は isinstance(v, str) で絞っており、
      数値のプロファイル事実（数秘術のライフパス=8 など）が候補から丸ごと
      抜け落ちていた。実際に「ライフパス8をお持ちの方は…」と正しく織り込んだ
      出力が「事実が1つも無い」と誤判定され、無駄な再生成が走っていた。
      → 数値も候補に含める。ただし裸の "8" は "1988" 等に部分一致して
        しまうため、ラベル付きの言い回し（"ライフパス8"）で照合する。
    """
    if entry["group"] != "G6":
        return []

    # ★BUG-18（2026-08-18 実機で判明）: 系譜フィルタの副作用。
    #   古代オリエント系などは参照可能な事実が「氏名（ヘボン式）」だけになり、
    #   「SATO HANAKO を鑑定文に織り込め」という無理な要求になっていた
    #   （7件が誤判定）。
    #   ① ローマ字氏名は織り込み必須の対象から外す
    #   ② 抽選テキスト（オーメン・聖句・出目など）を引いている占術は、
    #      それ自体が固有の拠り所なので必須言及を課さない
    slug = entry.get("slug", "")
    calc = ctx.calc_results.get(entry.get("calc_key") or "", None)
    if isinstance(calc, dict) and any(
            k in calc for k in ("full_text", "protasis", "verse",
                                "judgment", "pattern_id", "answer")):
        return []

    scoped = allowed_facts(slug, ctx.profile_facts)
    # 鑑定文に literal で埋め込むのが不自然な事実は必須言及の対象外にする
    #   ローマ字氏名（SATO HANAKO）・生の日付（1988-07-22）など
    #   ※BUG-18 の第2波: 日付が残って3件が誤判定された
    scoped = {k: v for k, v in scoped.items()
              if k not in _NOT_QUOTABLE
              and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(v))}
    if not scoped:
        # 参照できる事実が残らない体系には必須言及を課さない
        return []

    # 特定の生成物で個別化の軸を指定している場合は、その事実を必須候補にする。
    # P55（タリスマン）は太陽星座をデザイン上の手掛かりとして固定する。
    prompt_id = entry.get("prompt_id")
    prompt_def = get_prompt_def(prompt_id) if prompt_id else {}
    preferred_key = prompt_def.get("profile_fact_key")
    if preferred_key and preferred_key in scoped:
        preferred_value = scoped[preferred_key]
        if isinstance(preferred_value, str) and 0 < len(preferred_value) <= 20:
            return [preferred_value]

    values = []
    for label, v in scoped.items():
        if isinstance(v, str):
            if v and len(v) <= 20:
                values.append(v)
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            matched = False
            for key, patterns in _NUMERIC_FACT_ALIASES.items():
                if key in label:
                    values.extend(p.format(v=v) for p in patterns)
                    matched = True
                    break
            if not matched:
                # ラベルの括弧内（例: 数秘術（ライフパス）→ ライフパス）を利用
                inner = label.split("（")[-1].rstrip("）")
                values.append(f"{inner}{v}")
    return values[:12]


def _append_summary(ctx: PipelineContext, entry: dict, text: str):
    """profile_summary.json の themes に要点を追記（追記のみ・既存は不変）

    ※ クロスチェック指摘（別AI実装の知見）: 創作系（G6）の出力はサマリーに入れない
      （創作内容が「事実」として後続セルに伝播するのを防ぐ）
    """
    if entry["group"] == "G6":
        return
    lock = ctx.summary_lock

    def _write():
        if not ctx.summary_path.exists():
            ctx.summary_path.write_text(json.dumps(
                {"facts": ctx.profile_facts, "themes": [], "disagreements": [],
                 "consultation": ctx.consultation, "version": 1},
                ensure_ascii=False, indent=1), encoding="utf-8")
        try:
            data = json.loads(ctx.summary_path.read_text(encoding="utf-8"))
        except Exception:
            data = {"facts": ctx.profile_facts, "themes": [], "disagreements": [],
                    "consultation": ctx.consultation, "version": 1}
        if "themes" not in data:
            data["themes"] = []
        # 要点＝冒頭の文章を1〜2文（約80字）で切り出す（LLM要約は将来拡張）
        snippet = text.strip().replace("\n", " ")[:80]
        data["themes"].append(f"{entry['name']}: {snippet}…")
        data["version"] = data.get("version", 1) + 1
        ctx.summary_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    if lock is not None:
        with lock:
            _write()
    else:
        _write()


def _build_fix_instruction(issues: list, d: dict, prev_len: int,
                           must_mention: list | None = None) -> str:
    """検証で見つかった問題を、モデルへの具体的な修正指示に変換する。

    同じプロンプトを投げ直しても直らないため、「何が」「どう」悪かったかを
    明示して書き直させる（BUG-05）。
    """
    lines = ["# 再出力の指示（前回の出力に不備がありました）"]
    for iss in issues:
        if iss.startswith("文字数"):
            lo, hi = d["char_min"], d["char_max"]
            if prev_len > hi:
                lines.append(
                    f"- 前回は{prev_len}字で長すぎました。"
                    f"内容の重複や冗長な言い回しを削り、必ず{lo}〜{hi}字に収めてください。")
            else:
                lines.append(
                    f"- 前回は{prev_len}字で短すぎました。"
                    f"具体例や根拠を補い、必ず{lo}〜{hi}字にしてください。")
        elif iss.startswith("禁止語句"):
            m = re.search(r"「(.+?)」", iss)
            word = m.group(1) if m else ""
            lines.append(
                f"- 「{word}」という表現は使用禁止です。"
                "断定を避け、「〜しやすい」「〜傾向があります」等の助言形に言い換えてください。")
        elif iss.startswith("事実整合"):
            if d.get("profile_fact_key") and must_mention:
                values = "、".join(str(v) for v in must_mention)
                lines.append(
                    f"- プロファイル事実「{d['profile_fact_key']}」の値（{values}）を"
                    "そのまま本文に含め、タリスマンの意匠や使い方とのつながりを具体的に説明してください。")
            else:
                lines.append(
                    "- プロファイル事実（生年月日・星座・本命星など）を最低1つ、"
                    "本文中に自然に織り込んでください。")
        elif iss.startswith("フォーマット"):
            lines.append(
                "- 見出し（#）・表（|）・コードブロック（```）は使わず、"
                "通常の文章と段落のみで書いてください。")
        elif iss.startswith("日本語率"):
            lines.append("- 日本語の自然な文章で書いてください。")
        else:
            lines.append(f"- {iss} を解消してください。")
    lines.append("")
    lines.append("上記を踏まえ、鑑定文の【全文】を最初から書き直してください。"
                 "差分や言い訳は書かず、完成した鑑定文のみを出力してください。")
    return "\n".join(lines)



def _max_chars(d: dict) -> int:
    """通常の注記許容を維持しつつ、個別に定めた絶対上限を適用する。"""
    allowed = int(d["char_max"]) + 100
    hard = d.get("hard_char_max")
    return min(allowed, int(hard)) if hard is not None else allowed


def _trim_to_complete_sentence(text: str, max_chars: int,
                               min_chars: int) -> str | None:
    """文末・段落境界を優先し、絶対上限を超えない長さへ整える。

    文字数上限内に完結文がない場合は節の区切りを使い、それも無ければ
    上限の直前で切って句点を付ける。hard limitを超えたまま残さない。
    """
    source = (text or "").strip()
    if len(source) <= max_chars:
        return source
    clipped = source[:max_chars]
    ends = [m.end() for m in re.finditer(r"[。！？!?]+[」』】）)]*", clipped)]
    ends.extend(m.end() for m in re.finditer(r"\n{1,2}", clipped))
    candidates = [end for end in ends
                  if min_chars <= len(clipped[:end].rstrip()) <= max_chars]
    if candidates:
        return clipped[:max(candidates)].rstrip()

    # 文末が見つからない場合は、句読点のある節境界を優先する。
    clause_ends = [m.end() for m in re.finditer(r"[、；;]+[」』】）)]*", clipped)]
    clause_candidates = [end for end in clause_ends
                          if min_chars <= len(clipped[:end].rstrip()) < max_chars]
    if clause_candidates:
        clause = clipped[:max(clause_candidates)].rstrip().rstrip("、；;")
        candidate = clause + "。"
        if min_chars <= len(candidate) <= max_chars:
            return candidate

    # 境界記号が一つも無い場合も、700字などの絶対上限は必ず守る。
    if max_chars > 0:
        candidate = clipped[:max_chars - 1].rstrip() + "。"
        if min_chars <= len(candidate) <= max_chars:
            return candidate
    return None


_TALISMAN_SIGN_SYMBOLS = {
    "牡羊座": ("火", "朱色"), "牡牛座": ("地", "苔色"),
    "双子座": ("風", "淡黄色"), "蟹座": ("水", "銀白"),
    "獅子座": ("火", "金色"), "乙女座": ("地", "生成り"),
    "天秤座": ("風", "薄桃色"), "蠍座": ("水", "深藍"),
    "射手座": ("火", "琥珀色"), "山羊座": ("地", "墨色"),
    "水瓶座": ("風", "青緑"), "魚座": ("水", "藤色"),
}


def _talisman_fact_clause(facts: dict) -> str:
    """護符案に組み込むプロフィール事実の短い補足文を作る。"""
    sign = str(facts.get("太陽星座") or "").strip()
    if sign:
        element, color = _TALISMAN_SIGN_SYMBOLS.get(sign, ("季節", "落ち着いた色"))
        return (f"プロフィールの太陽星座「{sign}」を手掛かりに、"
                f"{element}のイメージを{color}で添える意匠を提案します。")
    for label, value in facts.items():
        if label in _NOT_QUOTABLE or not value:
            continue
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)):
            continue
        if isinstance(value, (str, int, float)) and len(str(value)) <= 20:
            return (f"プロフィール事実「{label}: {value}」を、"
                    "この護符案の意匠を選ぶ手掛かりとして取り入れます。")
    return ""


def _ensure_talisman_fact(text: str, facts: dict, required: list,
                          min_chars: int, max_chars: int) -> tuple[str, bool]:
    """再生成後も事実が欠ける場合、星座に結び付いた短い補足文を加える。"""
    normalized = validate.normalize_for_match(text or "")
    if not required or any(validate.normalize_for_match(str(v)) in normalized
                           for v in required if v):
        return text, False
    clause = _talisman_fact_clause(facts)
    if not clause:
        return text, False
    suffix = "\n\n" + clause
    candidate = (text or "").strip() + suffix
    if len(candidate) <= max_chars:
        return candidate, True

    budget = max_chars - len(suffix)
    base_min = max(1, min_chars - len(suffix))
    trimmed = _trim_to_complete_sentence(text, budget, base_min)
    if trimmed is not None:
        candidate = trimmed + suffix
        if min_chars <= len(candidate) <= max_chars:
            return candidate, True
    # 文末記号が無い生成物でも、事実補足を残したまま許容上限内へ収める最終手段。
    if budget > 0:
        clipped = (text or "").strip()[:budget].rstrip()
        candidate = clipped + suffix
        if min_chars <= len(candidate) <= max_chars:
            return candidate, True
    return text, False


def _char_deviation(text: str, d: dict) -> int:
    """文字数が許容範囲からどれだけ逸脱するか（0なら範囲内）"""
    n = len(text.strip())
    lo, hi = d["char_min"], _max_chars(d)
    if n < lo:
        return lo - n
    if n > hi:
        return n - hi
    return 0

def _is_better(issues2: list, text2: str, issues: list, text: str, d: dict) -> bool:
    """再生成結果を採用すべきか判定する（BUG-07）。

    1. issue 件数が減っていれば採用
    2. 件数が増えていれば不採用
    3. 同数なら、文字数の逸脱量が小さいほうを採用（同点なら元を維持）
    """
    if len(issues2) != len(issues):
        return len(issues2) < len(issues)
    return _char_deviation(text2, d) < _char_deviation(text, d)



def run_divination(slug: str, ctx: PipelineContext, force: bool = False,
                   backend: LLMBackend | None = None,
                   model_hint: str | None = None) -> dict:
    """
    1占術の実行。

    Returns:
        {"status": "ok" | "skipped" | "unavailable" | "error",
         "slug": ..., "reason": ..., "issues": [...], "file": ...}
    """
    entry = REGISTRY[slug]
    md_path, raw_path = _result_paths(ctx, entry)

    fingerprint = input_fingerprint(ctx, entry)

    # スキップガード（再開可能性）。force=True で上書き再生成する
    # （御縁のある神さまは統合レポート後に選定し直すため force で呼ばれる）
    # mts5.53（P-2）: 「存在＝成功」ではなく、**入力指紋の一致**を条件にする。
    if md_path.exists() and not force:
        stored = stored_fingerprint(raw_path)
        if stored == fingerprint:
            SKIP_STATS["fingerprint_match"] += 1
            print(f"  ↺ {slug}: 既存の結果を再利用（入力指紋 {stored} が一致）")
            return {"status": "skipped", "slug": slug, "file": str(md_path),
                    "skip_reason": "fingerprint_match", "fingerprint": stored}
        if stored is None:
            SKIP_STATS["no_fingerprint"] += 1
            print(f"  ↺ {slug}: 既存の結果を再利用（旧版の成果物＝入力指紋が無いため照合できません）")
            _note = (f"{slug}: 入力指紋の無い旧版の成果物を再利用しました"
                     "（入力が変わっていても気づけません。次回の再実行で指紋が付きます）")
            try:
                from .runcheck import add_warning
                add_warning(_note)
            except Exception:
                pass
            return {"status": "skipped", "slug": slug, "file": str(md_path),
                    "skip_reason": "no_fingerprint"}
        # 入力が変わった＝古い結果は無効。黙って残さず作り直す。
        SKIP_STATS["stale_regenerated"] += 1
        print(f"  ↻ {slug}: 入力が変わったため作り直します"
              f"（入力指紋 {stored} → {fingerprint}）")
        try:
            from .runcheck import add_warning
            add_warning(f"{slug}: 入力が変わったため結果を作り直しました"
                        f"（入力指紋 {stored} → {fingerprint}）")
        except Exception:
            pass

    # 入力充足チェック
    reason = availability_reason(slug, ctx.inputs)
    if reason:
        return {"status": "unavailable", "slug": slug, "reason": reason}

    be = backend if backend is not None else ctx.backend
    if be is None:
        return {"status": "error", "slug": slug, "reason": "backend 未設定"}

    d = get_prompt_def(entry["prompt_id"])
    calc_result = ctx.calc_results.get(entry["calc_key"]) if entry["calc_key"] else None
    must_mention = (_must_mention_facts(entry, ctx)
                    if entry["group"] == "G6" else None)
    validation_max_chars = _max_chars(d)
    quality_adjustments: list[str] = []

    # 今日の運勢モード（⑦・クロスチェック拡張）: 相談内容が空なら自動で有効化
    today_mode = not (ctx.consultation or "").strip()
    today_instruction = None
    target_date_str = None
    if today_mode:
        from .today import get_today_instruction
        today_instruction = get_today_instruction(slug)
        t = ctx.calc_results.get("target_date", {})
        target_date_str = t.get("date") if isinstance(t, dict) else None

    # 相談内容のサニタイズ（インジェクション対策）
    consult = sanitize(ctx.consultation or "")

    sys_p = build_system_prompt(entry["prompt_id"],
                                today_mode=today_mode,
                                today_instruction=today_instruction)
    # ★系譜フィルタ（2026-08-18）: 他系譜の術語が流入するのを防ぐ。
    #   実機66種のうち30種で「ドゥクンが二黒土星を語る」等が起きていた。
    scoped_facts = allowed_facts(slug, ctx.profile_facts)
    if len(scoped_facts) < len(ctx.profile_facts):
        # 事実が減った体系には、系譜を問わない手がかり（季節など）を補う
        scoped_facts = {**scoped_facts, **neutral_context(ctx.profile_facts)}
    sys_p += lineage_note(slug)

    usr_p = build_user_prompt(entry["prompt_id"], scoped_facts,
                              calc_result, consult,
                              today_mode=today_mode,
                              target_date=target_date_str)

    # 「御縁のある神さま」は他占術の結果（＝統合レポートの要点）も踏まえて読む
    if slug == "deities":
        ctxt = _summary_context(ctx)
        if ctxt:
            usr_p += ("\n\n# これまでの占術の要点（統合レポートより・参考文脈）\n"
                      + ctxt
                      + "\n※ 上記は他体系の所見です。矛盾する場合は無理に整合させず、"
                        "神々との縁を読むための背景としてのみ用いてください。")

    max_tokens = d.get("max_tokens", d["char_max"] + 250)

    # 生成
    text = be.generate(sys_p, usr_p, temperature=d["temp"],
                      max_tokens=max_tokens, seed=ctx.seed)

    # 検証
    issues = validate.validate_output(
        text,
        min_chars=d["char_min"], max_chars=validation_max_chars,
        must_mention=must_mention,
    )

    # ------------------------------------------------------------------
    # 再生成（★BUG-05 修正・2026-08-16 実機ログで判明）
    #
    # 旧実装は「同じプロンプトを温度だけ下げて投げ直す」だけだったため、
    # モデルは何が悪かったのか分からず、実機では 10件すべてが再生成後も
    # 同じ違反（文字数超過）のままだった（約17分＝全体の20%を浪費）。
    #
    # 対処: 検出した issue を「修正指示」としてプロンプトに追加する。
    #   - 文字数超過 → 目標字数と「短くする」旨を明示
    #   - 禁止語句   → 該当語を挙げて言い換えを指示
    #   - 事実未言及 → 織り込むべき事実を明示
    # 改善しなければ元の文章を採用する（従来どおり）。
    # ------------------------------------------------------------------
    if issues and ctx.regenerate_on_issue and ctx.max_regenerate > 0:
        fix_prompt = usr_p + "\n\n" + _build_fix_instruction(
            issues, d, len(text), must_mention=must_mention)
        text2 = be.generate(
            sys_p, fix_prompt,
            temperature=max(0.1, d["temp"] - 0.2),
            max_tokens=max_tokens, seed=ctx.seed)
        issues2 = validate.validate_output(
            text2,
            min_chars=d["char_min"], max_chars=validation_max_chars,
            must_mention=must_mention,
        )
        # ★BUG-07（2026-08-16 実機ログ）: 旧判定は issue の「件数」だけを見ていたため、
        #   1166字 → 950字のように【明確に改善したが依然1件違反】の再生成結果を
        #   「同数だから」と破棄していた（西洋占星術が2回連続で1166字のまま残存）。
        #   → 件数が同じ場合は「違反の深刻度（字数の逸脱量）」で比較する。
        if _is_better(issues2, text2, issues, text, d):
            text, issues = text2, issues2

    # Tarot は出力を再生成しても絶対上限を超える場合、完結した文単位で整える。
    hard_max = d.get("hard_char_max")
    if hard_max is not None and len((text or "").strip()) > int(hard_max):
        trimmed = _trim_to_complete_sentence(
            text, int(hard_max), int(d["char_min"]))
        if trimmed is not None:
            text = trimmed
            quality_adjustments.append(
                f"文末・節境界を優先して上限内へ調整し、{len(text)}字に整理")
            issues = validate.validate_output(
                text, min_chars=d["char_min"], max_chars=validation_max_chars,
                must_mention=must_mention)

    # タリスマンは1回の修正生成でも事実を落とす場合があるため、個別事実を含む
    # 短い意匠提案を補い、M30の「一般論だけ」の出力を残さない。
    if slug == "talisman":
        text, added = _ensure_talisman_fact(
            text, scoped_facts, must_mention or [], d["char_min"],
            validation_max_chars)
        if added:
            quality_adjustments.append("不足していた太陽星座の個別化文を補足")
            issues = validate.validate_output(
                text, min_chars=d["char_min"], max_chars=validation_max_chars,
                must_mention=must_mention)

    # 空または極端に短い本文はファイル化しない。
    #   md を書いてしまうと再実行時の auto-skip で空の結果が恒久化し、
    #   「✅（再生成: [文字数: 0字…]）」のように成功扱いで保存されてしまう。
    #   error ステータスを返して次回の再実行で生成し直す
    if len((text or "").strip()) < 50:
        return {"status": "error", "slug": slug,
                "reason": (f"生成テキストが空/極端に短い（{len((text or '').strip())}字）。"
                           "生成枠を使い切った可能性")}

    # 保存
    ctx.results_dir.mkdir(parents=True, exist_ok=True)
    _model = model_meta(be, model_hint or "")
    md = _render_markdown(entry, ctx, text, issues, calc_result, _model)
    md_path.write_text(md, encoding="utf-8")

    result_payload = {"prompt_id": entry["prompt_id"], "group": entry["group"],
                      "text": text, "calc": calc_result}
    if quality_adjustments:
        result_payload["quality_adjustments"] = list(quality_adjustments)
    raw = build_result(
        module=entry["mcode"], divination=entry["name"],
        inputs=to_dict(ctx.inputs),
        approx_flags=list(ctx.inputs.approx_flags),
        result=result_payload,
        references=[f"prompts.json#{entry['prompt_id']}"],
        warnings=list(ctx.inputs.approx_flags),
        notes=issues,
        model=_model,                                   # mts5.53（P-9）
        input_fingerprint=fingerprint,                  # mts5.53（P-2）
    )
    raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")

    # サマリー追記（追記のみ）
    _append_summary(ctx, entry, text)

    return {"status": "ok", "slug": slug, "file": str(md_path),
            "issues": issues, "regenerated": bool(issues),
            "quality_adjustments": list(quality_adjustments),
            "model": _model, "fingerprint": fingerprint}
