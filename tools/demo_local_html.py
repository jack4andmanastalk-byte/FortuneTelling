#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ローカル動作確認用: API を使わずに本番と同じ形の HTML を生成する（mts5.26 新設）

目的:
  Kaggle 実機テストの前に、**口調切替タブを含む成果物 HTML** を手元で生成し、
  ブラウザで動作確認できるようにする（LLM は 1 回も呼びません）。

しくみ:
  - バックエンドを MockBackend の派生（DemoBackend）に差し替え、プロンプトに
    書かれた**文字数レンジを読み取って、その範囲内の鑑定文を決定的に生成**する。
    （本番と同じ検証・再生成ロジック・Stage B/C/D の分割・検証を通すため、
      成果物の構造と HTML の作りは実機と同一になります）
  - Stage D も**本物の `run_stage_d_tones` を通します**（セグメント分割・
    数値凍結検証・units.json/tone_manifest.json の書き出しまで本番どおり）。
    文体変換だけを DemoBackend が「それらしく」行います。

★注意: 生成される**文章はダミー**です（占術的な中身はありません）。
  HTML のレイアウト・口調切替の挙動・画像の埋め込みを確認するためのものです。

使い方:
  cd /home/user/fortune_dataset
  python3 tools/demo_local_html.py                     # 既定: /home/user/demo_out/demo_local
  python3 tools/demo_local_html.py --pid takahashi_ren
  python3 tools/demo_local_html.py --tone-ids easy,obaa # 一部のトーンだけ作る（速い）
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "fortune_dataset"
sys.path.insert(0, str(PKG))

from fortunelib.backend import MockBackend                     # noqa: E402
from fortunelib.mts import load_model_plan, run_person_mts      # noqa: E402
from fortunelib.tone import (TONE_DEFS, run_stage_d_tones,      # noqa: E402
                             tone_from_prompt)

# mts5.53（P-6）: --pid は人物フォルダ名になる。`..` や `/` を通すと
# `--fresh` の削除対象が出力ルートの外へ飛ぶため、**厳格に検証**する。
_PID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

DEFAULT_ROW = {
    "person_id": "demo_local",
    "birth_date": "1978-07-07",
    "birth_time": "05:20",
    "birth_place": "福岡県",
    "gender": "M",
    "blood_type": "O",
    "name_kanji": "高橋 蓮",
    "name_kana": "たかはし れん",
    "partner_date": "1982-11-30",
    "partner_time": "23:45",
    "partner_place": "北海道",
    "consultation": "独立して事業を始めるべきか、今の会社で昇進を目指すべきか迷っています",
    "target": "",
}

_RANGE_FUJIN = re.compile(r"【分量】\s*(\d+)\s*〜\s*(\d+)\s*字")
_RANGE_KAKKO = re.compile(r"（\s*(\d+)\s*〜\s*(\d+)\s*字")
_FACTS_HEAD = "# プロファイル事実"
_FACTS_TAIL = ("# 計算結果", "# 相談内容", "# 依頼")

# ダミー本文の種（数値を含める＝Stage D の数値凍結検証を本番と同じように通す）
_BODY_SENTENCES = [
    "あなたの歩みは、1つずつ確かめることで強くなっていく性質です。",
    "全体の傾向としては、今年は3つの流れが重なる時期にあたります。",
    "相談内容に対しては、まず足元を整えることが近道になります。",
    "数字で見ると、4という周期が節目として働いています。",
    "周囲との関わりでは、相手の立場を想像する姿勢が助けになります。",
    "無理を重ねず、休息を予定に入れておくと流れが崩れません。",
    "準備してきたことが形になり始める兆しがあります。",
    "判断に迷うときは、小さく試してから広げると安全です。",
    "学び直しや道具の見直しが、次の段階への入口になります。",
    "気持ちの余白を残すことが、結果として最短の道になります。",
]


class DemoBackend(MockBackend):
    """本番の検証を通る長さのダミー鑑定文を返すバックエンド（API 不使用）。

    - Stage A/B/C: プロンプトの「分量」レンジの中央値に合わせて本文を作る。
    - Stage D: システムプロンプトの【指定された口調】からトーンを判定し、
      本文（"===" 以降）だけを決定的に文体変換する（数値・固有名詞は不変）。
    """

    def __init__(self):
        super().__init__()
        self.tone_calls = 0

    # -------------------------------------------------- Stage D
    @staticmethod
    def _tone_id(system_prompt: str) -> str | None:
        for t in TONE_DEFS:
            if t.get("rewrite") and t.get("style") and t["style"] in system_prompt:
                return t["id"]
        # mts5.56: 読み物版は style ⑤ を外して書き換えるため、固有の数値で判定する
        return tone_from_prompt(system_prompt)

    @staticmethod
    def _rewrite(tid: str, text: str) -> str:
        """文体だけを置換（数値・固有名詞は触らない＝検証を通る）

        ★置換順は「長い語尾→短い語尾」の順に並べること（例: ります。→ るんだ。を
          先に処理。逆順だと「ます。」が先に当たって不自然な日本語になる）。
        """
        t = text
        if tid == "easy":
            subs = [("ではありません。", "ではないよ。"), ("ましょう。", "ようね。"),
                    ("ください。", "してみてね。"), ("でしょう。", "と思うよ。"),
                    ("ります。", "るんだ。"), ("います。", "いるんだ。"),
                    ("ます。", "んだ。"), ("ません。", "ないよ。"),
                    ("です。", "だよ。")]
        elif tid == "obaa":
            subs = [("ください。", "くださいね。"), ("でしょう。", "でしょうね。"),
                    ("あります。", "ありますよ。"), ("なります。", "なりますよ。"),
                    ("ります。", "りますよ。"), ("います。", "いますよ。"),
                    ("ます。", "ますよ。"), ("ません。", "ませんよ。"),
                    ("大切です。", "大事ですよ。"), ("です。", "ですよ。")]
        elif tid == "spiritual":
            subs = [("でしょう。", "という星の流れなのでしょう。"),
                    ("傾向があります。", "エネルギーがそう示しています。"),
                    ("大切です。", "魂の学びとして大切なのです。"),
                    ("ます。", "ます。"), ("です。", "なのです。")]
        else:
            return t
        for a, b in subs:
            t = t.replace(a, b)
        # 数値・記号はそのまま（検証: 数値の多重集合一致）
        return t

    def generate(self, system_prompt: str, user_prompt: str,
                 temperature: float = 0.7, max_tokens: int = 1000,
                 seed: int | None = None) -> str:
        self.calls.append({
            "system": system_prompt, "user": user_prompt,
            "temperature": temperature, "max_tokens": max_tokens, "seed": seed,
        })
        tid = self._tone_id(system_prompt)
        if tid and "===\n" in user_prompt:
            seg = user_prompt.split("===\n", 1)[1].strip()
            self.tone_calls += 1
            return self._rewrite(tid, seg)
        return self._body(user_prompt)

    # -------------------------------------------------- Stage A/B/C
    def _body(self, user_prompt: str) -> str:
        m = _RANGE_FUJIN.search(user_prompt) or _RANGE_KAKKO.search(user_prompt)
        lo, hi = (int(m.group(1)), int(m.group(2))) if m else (400, 600)
        target = (lo + hi) // 2
        facts = self._facts(user_prompt)
        parts = []
        if facts:
            parts.append(f"プロファイル事実として、{facts}をふまえて読み解きます。")
        i = 0
        while sum(len(p) for p in parts) < target - 80:
            parts.append(_BODY_SENTENCES[i % len(_BODY_SENTENCES)])
            i += 1
            if i > 400:
                break
        text = "".join(parts)
        # レンジ内に収める（末尾の文を調整）
        while len(text) > hi and parts:
            parts.pop()
            text = "".join(parts)
        pad = "この流れを意識して過ごすと、判断がぶれにくくなります。"
        while len(text) < lo:
            text += pad
            if len(text) > hi:
                break
        return text

    @staticmethod
    def _facts(user_prompt: str) -> str:
        """プロンプトのプロファイル事実から、短いラベル付き事実を1つ拾う（G6 の必須言及対策）"""
        try:
            head = user_prompt.index(_FACTS_HEAD)
        except ValueError:
            return ""
        tail = len(user_prompt)
        for k in _FACTS_TAIL:
            j = user_prompt.find(k, head)
            if j != -1:
                tail = min(tail, j)
        block = user_prompt[head:tail]
        vals = [x.strip("- ").strip() for x in block.splitlines()[1:] if x.strip()]
        vals = [v for v in vals if 0 < len(v) <= 24]
        return vals[0] if vals else ""


def _load_row(pid: str) -> dict:
    csv_path = PKG / "kaggle" / "people_sample.csv"
    if csv_path.is_file():
        import csv
        with csv_path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("person_id") == pid:
                    return dict(row)
    row = dict(DEFAULT_ROW)
    row["person_id"] = pid
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", default="demo_local", help="person_id（人物フォルダ名）")
    ap.add_argument("--out", default=str(ROOT.parent / "demo_out"),
                    help="出力ルート（既定はリポジトリの隣の demo_out/）")
    ap.add_argument("--tone-ids", default="",
                    help="Stage D で作るトーン（カンマ区切り・既定は全トーン）")
    ap.add_argument("--fresh", action="store_true", help="既存の出力を消して作り直す")
    ap.add_argument("--no-images", action="store_true",
                    help="画像を埋め込まない（HTML が軽くなり口調タブの確認が速い）")
    ap.add_argument("--no-intro-video", action="store_true",
                    help="同梱の冒頭動画カード（assets/video）を付けない")
    args = ap.parse_args()

    if not _PID_RE.match(args.pid) or args.pid in (".", ".."):
        print(f"❌ --pid が不正です: {args.pid!r}"
              "（英数字で始まる 1〜64文字の 英数字 . _ - のみ）")
        return 2

    from fortunelib.runcheck import clear as _warn_clear
    from fortunelib.pipeline import reset_skip_stats as _skip_reset
    _warn_clear()                       # mts5.54: 前回の警告を持ち越さない
    _skip_reset()                       # mts5.55: 前回の再利用の内訳も持ち越さない
    out_root = Path(args.out)
    person_dir = out_root / args.pid
    # mts5.53（P-6）: 監査の指摘＝`--fresh` が `--out/<pid>` を無条件に rmtree していた
    # （検証では --out /tmp/audit_prod --pid victim で無関係なファイルが消えた）。
    # 削除対象が「この実行の出力ディレクトリ」であることを確認してから消す。
    if args.fresh and person_dir.exists():
        if person_dir.resolve().parent != out_root.resolve():
            print(f"❌ --fresh の削除対象が出力ルートの外です（中止）: {person_dir}")
            return 2
        _entries = sorted(x.name for x in person_dir.iterdir())
        print(f"■ --fresh: この実行の出力だけを削除します: {person_dir}"
              f"（{len(_entries)}件: {', '.join(_entries[:6])}"
              + (" ほか" if len(_entries) > 6 else "") + "）")
        shutil.rmtree(person_dir)
    person_dir.mkdir(parents=True, exist_ok=True)

    row = _load_row(args.pid)
    plan = load_model_plan()
    backends = {m: DemoBackend() for m in plan["models"]}

    print(f"■ ローカル HTML 生成（LLM 呼び出しなし）  person_id={args.pid}")
    print(f"  出力: {person_dir}")

    t0 = time.time()
    res = run_person_mts(row, backends, out_root, session_prefix="demo",
                         stages=("A", "B", "C"), verbose=False, monitor=False)
    print(f"  Stage A/B/C 完了: ok={res.ok} skipped={res.skipped} "
          f"対象外={res.unavailable} 失敗={res.error}（{time.time() - t0:.1f}秒）")
    if res.failed:
        print(f"  ⚠ 失敗: {res.failed}")

    # Stage D（本番と同じ関数・同じ検証）
    facts = {}
    summary = person_dir / "profile_summary.json"
    if summary.is_file():
        facts = (json.loads(summary.read_text(encoding="utf-8"))
                 .get("profile_facts") or {})
    tone_ids = [x for x in args.tone_ids.split(",") if x] or None
    man = run_stage_d_tones(person_dir / "results", person_dir, backends, facts,
                            verbose=False, tone_ids=tone_ids)
    tsum = ", ".join(f"{tid}: {tm.get('n_ok')}/{tm.get('n_total')}"
                     for tid, tm in (man.get("tones") or {}).items())
    print(f"  Stage D トーン化: {tsum}")

    # HTML（本番と同じ build_html・画像も埋め込む）
    from fortunelib.html_report import build_html
    images_dir = None
    if not args.no_images:
        cand = PKG / "assets" / "images"
        images_dir = cand if cand.is_dir() else None
    intro_html = ""
    if not args.no_intro_video:                                   # 同梱の冒頭動画
        try:
            from fortunelib.intro_video import load_intro_video_card
            intro_html, _iv = load_intro_video_card(images_dir or (ROOT / "fortune_dataset"))
            if intro_html:
                print(f"   冒頭動画カード: {_iv.get('file')}（{_iv.get('size_mb', 0):.2f}MB・"
                      f"約{_iv.get('seconds', 0):.0f}秒・オンライン案内 {'有' if _iv.get('online_url') else '無'}）")
            else:
                print(f"   冒頭動画カード: なし（{_iv.get('reason')}）")
        except Exception as e:                                    # noqa: BLE001
            print(f"   ⚠ 冒頭動画カードを付けられません（{type(e).__name__}: {e}）")
    html = build_html(person_dir, person_id=args.pid, images_dir=images_dir,
                      intro_video_html=intro_html)
    text = html.read_text(encoding="utf-8")
    omake = 'id="omake-data"' in text
    print(f"  ✅ {html}  {len(text.encode('utf-8')) / 1024:.0f}KB / "
          f"画像 {text.count('data:image')}枚 / "
          f"口調ボタン {text.count('class=\"tb-btn\"')}個 / "
          f"tone-text {text.count('class=\"tone-text\"')}個")
    if omake:
        print("  形式: 読み物版（オマケ）＝統合鑑定レポートの直下のカードで切替"
              "（他の節は標準のまま）")
    print(f"  合計 {time.time() - t0:.1f}秒")
    if omake:
        print("\n次の手順: この HTML をダウンロードし、ブラウザで開いて"
              "「統合鑑定レポート」の直下にある【オマケ】読み物版のボタンをお試しください。")
    else:
        print("\n次の手順: この HTML をダウンロードし、ブラウザで開いて口調タブをお試しください。")
    print("（実 DOM での自動確認: NODE_PATH=/tmp/tone_jsdom/node_modules "
          f"node fortune_dataset/tests/tone_ui_domtest.js {html}）")

    # mts5.53（P-4/P-10）: 実行時の警告（フォント・画像など）をまとめて出し、
    # RUN_STRICT=1 のときだけ不合格にする（既定は警告のみ）。
    try:
        from fortunelib import chartdraw as _cd, runcheck as _rc
        _cd.check_bundled_fonts(verbose=True)
        _rc.report(prefix="  ⚠")
        _n_warn = len(_rc.WARNINGS)
        if _n_warn == 0:
            print("  ■ 警告なし（既定モード）")
        _rc.enforce()
    except SystemExit:
        raise
    except Exception as e:                                        # noqa: BLE001
        print(f"  ⚠ 警告の集約に失敗しました（{type(e).__name__}: {e}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
