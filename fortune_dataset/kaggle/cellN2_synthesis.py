# ============================================================
# Cell N2: 統合鑑定レポート → 御縁のある神さま → HTML一括出力
#
#   ① クラスタ中間レポート（1000〜2000字 × 5本＋6本）
#   ② 軸サマリー（method / culture の各総括）
#   ③ 最終統合レポート（両軸を突き合わせ・約4000字）
#   ④ 御縁のある神さま Top10（③の内容を踏まえて選定 → ③に追記）
#   ⑤ 全成果物を1枚のHTMLに束ねる（スマホ保存・閲覧用）
# ============================================================
import json  # noqa: E402
from pathlib import Path  # noqa: E402

from fortunelib.batch import build_profile_facts, build_calc_results  # noqa: E402
from fortunelib.html_report import build_html  # noqa: E402
from fortunelib.pipeline import PipelineContext  # noqa: E402
from fortunelib.profile import normalize_input  # noqa: E402
from fortunelib.mts import run_stage_b_mts, run_stage_c_mts  # noqa: E402

# ---- 設定 ---------------------------------------------------
# mts5.54: 前のセル（セルフテスト・段階A）の警告を持ち越さない。このセルの警告だけを数える。
# mts5.55: 再利用の内訳（SKIP_STATS）も同じくプロセス共通なので、ここで0に戻す。
try:
    from fortunelib.runcheck import clear as _warn_clear
    from fortunelib.pipeline import reset_skip_stats as _skip_reset
    _warn_clear()
    _skip_reset()
except Exception:
    pass
MAKE_HTML = True                       # 1枚HTMLを生成する
EMBED_INTRO_VIDEO = True               # ON/OFF: True なら同梱の冒頭動画（assets/video/intro_video.json）を目次の前に埋め込む（既定ON）

# 出力先の決定（CSVバッチ後か、1人モードかを自動判定）
_OUT_ROOT = Path("/kaggle/working/output")
if globals().get("CSV_BATCH_DONE") and _OUT_ROOT.is_dir():
    TARGETS = [p for p in sorted(_OUT_ROOT.iterdir()) if (p / "results").is_dir()]
else:
    TARGETS = [Path("/kaggle/working")]

print(f"■ MTS 統合レポート  対象 {len(TARGETS)}件 / 軸: method + culture")

_RUN_ERRORS = globals().setdefault("RUN_ERRORS", [])
_PROCESSED_TARGETS = 0
_SKIPPED_TARGETS = []

for _dir in TARGETS:
    _rd = _dir / "results"
    if not _rd.is_dir() or not list(_rd.glob("*_raw.json")):
        print(f"− {_dir.name}: 結果がないためスキップ")
        _SKIPPED_TARGETS.append(str(_dir))
        continue

    try:
        # プロファイル・相談内容を復元
        _sp = _dir / "profile_summary.json"
        if _sp.exists():
            _s = json.loads(_sp.read_text(encoding="utf-8"))
            _facts, _consult = _s.get("facts", {}), _s.get("consultation", "")
        else:
            _s = {}
            _facts = globals().get("FACTS") or {}
            _consult = globals().get("NI").consultation if globals().get("NI") else ""

        # 神々の生成に使う PipelineContext を用意
        #   CSVバッチ後やカーネル再起動後でも、profile_summary.json から確実に復元する
        _ctx = None
        _ni_for_target = None
        _calc_for_target = globals().get("CALC") or {}
        try:
            if not globals().get("CSV_BATCH_DONE") and globals().get("CTX") is not None:
                _ctx = CTX
            if _ctx is None and _sp.exists():
                _inp = _s.get("input_raw")
                _ni2 = normalize_input(_inp) if _inp else None
                _ni_for_target = _ni2
                if _ni2 is not None:
                    _f2 = build_profile_facts(_ni2)
                    _c2 = build_calc_results(_ni2, consultation=_ni2.consultation)
                    _calc_for_target = _c2
                    _ctx = PipelineContext(
                        inputs=_ni2, profile_facts=_f2, calc_results=_c2,
                        consultation=_ni2.consultation, results_dir=_rd,
                        summary_path=_sp, backend=BACKEND)
        except Exception as _e:
            raise RuntimeError(f"神々の実行コンテキストを用意できませんでした: {_e}") from _e

        # ★ F1ガード: _ctx が用意できない場合は絶対に沈黙スキップせず例外で落とす
        if _ctx is None:
            raise RuntimeError(
                f"{_dir.name}: 神々の実行コンテキスト (_ctx) を復元できませんでした。"
                f"profile_summary.json または Cell 1 の実行状態を確認してください。")

        _tgt = ""
        _cd = (_calc_for_target or {}).get("target_date") or {}
        # mts4.1表示層ゲート: 相談あり＋対象日空欄（実行日フォールバック）なら
        # Stage B/C へ対象日を渡さない。今日の運勢モードか明示指定なら渡す。
        # 明示指定は inputs（または input_raw）から導出し、calc スキーマは不変。
        if _ni_for_target is not None:
            _explicit_t = _ni_for_target.target_date is not None
        else:
            _explicit_t = bool(((_s.get("input_raw") or {}).get("target") or "").strip())
        if isinstance(_cd, dict) and (not _consult.strip() or _explicit_t):
            _tgt = _cd.get("date", "")

        print(f"\n▶ {_dir.name}")
        print("  ▶ MTS 段階 B（クラスタ lite 並列）")
        _b = run_stage_b_mts(
            _rd, _dir, get_mts_backends(), _facts,
            consultation=_consult, target_date=_tgt, verbose=True)
        _bcheck = _b.get("verification") or {}
        print(f"  ✅ MTS 段階 B 検証: {_bcheck.get('found', 0)}/"
              f"{_bcheck.get('expected', 0)}本・fallback "
              f"{len(_b.get('fallbacks') or [])}件")
        if not _b.get("complete") or _bcheck.get("found") != _bcheck.get("expected"):
            raise RuntimeError(
                f"Stage B が {_bcheck.get('found', 0)}/{_bcheck.get('expected', 0)}本です")
        print("  ▶ MTS 段階 C（最終＋神々・最上位 flash）")
        _res = run_stage_c_mts(
            _rd, _dir, get_mts_backends(), _facts,
            consultation=_consult, target_date=_tgt, verbose=True,
            ctx=_ctx, per_axis=_b.get("per_axis"))

        # ★ F1ガード: 神々の節が生成され、かつ正常であることを厳格に検証
        _deities_res = _res.get("deities")
        if not _deities_res or _deities_res.get("status") != "ok":
            _dstatus = (_deities_res or {}).get("status") or "未実行"
            _dreason = (_deities_res or {}).get("reason") or ""
            raise RuntimeError(
                f"神々の生成に失敗しました（status={_dstatus}, reason={_dreason}）。"
                f"最終レポートに御縁のある神さまが追記されていません。")

        print(f"  ✅ 最終 {len(_res['final_report'])}字 → {_res['file']}")
        from fortunelib.mts import deities_model
        print(f"  ✅ 御縁のある神さま: {deities_model()} で追記済み")

        # mts5.22: Stage D トーン化（かんたん／スピリチュアル風・mts5.65 で obaa を削除）
        # 定型本文を凍結した文体リライト。失敗しても「標準」のみのHTMLを生成して継続する
        # （UX機能の本番鑑定への影響は許さない＝失敗は警告のみ）。
        try:
            from fortunelib.tone import run_stage_d_tones
            _tone_man = run_stage_d_tones(
                _rd, _dir, get_mts_backends(), _facts, verbose=True)
            _tsum = ", ".join(
                f"{_tid}: {_tm.get('n_ok')}/{_tm.get('n_total')}({_tm.get('status')})"
                for _tid, _tm in (_tone_man.get("tones") or {}).items())
            print(f"  ✅ Stage D トーン化: {_tsum or '未生成'}")
        except Exception as _te:
            print(f"  ⚠ Stage D（トーン化）に失敗 → 標準のみのHTMLで継続: "
                  f"{type(_te).__name__}: {_te}")

        if MAKE_HTML:
            # mts5.53（P-4）: 型Cの画像は同梱フォントで描く。フォントが欠けると
            # 例外も警告も出ず画像だけが変わる（実証済み）ため、ここで必ず確認する。
            try:
                from fortunelib.chartdraw import check_bundled_fonts as _check_fonts
                _check_fonts(verbose=True)
            except Exception as _e_font:
                print(f"  ⚠ フォントの確認に失敗（{type(_e_font).__name__}: {_e_font}）")
            # 本番埋め込み: assets/images の各デッキから、結果に対応する1枚ずつを選抜して Base64 埋め込み
            # 画像ディレクトリの探索は fortunelib.html_report.discover_assets_root に一本化
            # （順番: Dataset ルート（BASE）→ 環境変数 FORTUNE_ASSETS_DIR / FORTUNE_DATA_DIR →
            #   /kaggle/input/**/assets/images の glob → /kaggle/input 直下の列挙。個人のパスは置かない）
            from fortunelib.html_report import discover_assets_root as _discover_assets_root
            _images_dir = _discover_assets_root(globals().get("BASE"))
            # mts5.53（P-8）: 監査の指摘＝画像ディレクトリの探索に失敗しても
            # **無言で**画像なしの HTML が出来ていた（どの候補を見たかも残らない）。
            # ここで必ず結果を出し、失敗は警告として残す。
            if _images_dir is not None:
                print(f"  [画像] 素材ディレクトリ: {_images_dir}")
            else:
                _msg_img = ("画像素材ディレクトリ（assets/images）が見つかりませんでした。"
                            "画像なしで HTML を作ります（Add Input の Dataset に "
                            "assets/images が含まれているか確認してください）")
                print(f"  ⚠ {_msg_img}")
                try:
                    from fortunelib.runcheck import add_warning as _add_warning
                    _add_warning(_msg_img)
                except Exception:
                    pass

            # 同梱の固定動画（冒頭カード・目次の直前・全員共通）。
            # OFF なら読み込みも埋め込みもしない。無ければ警告を残して動画なしで続ける。
            _intro_html, _intro_info = "", {"reason": "disabled"}
            if EMBED_INTRO_VIDEO:
                try:
                    from fortunelib.intro_video import load_intro_video_card as _load_iv
                    _intro_html, _intro_info = _load_iv(_images_dir or globals().get("BASE"))
                except Exception as _e_iv:
                    _intro_info = {"reason": "error", "error": f"{type(_e_iv).__name__}: {_e_iv}"}
                if _intro_html:
                    print(f"  ✅ 冒頭動画カード: {_intro_info.get('file')}"
                          f"（{_intro_info.get('size_mb', 0):.2f}MB・約{_intro_info.get('seconds', 0):.0f}秒・"
                          f"SHA一致 {'OK' if _intro_info.get('sha_match') else '未確認'}・"
                          f"オンライン案内 {'有' if _intro_info.get('online_url') else '無'}）")
                else:
                    _msg_iv = ("冒頭動画カードを埋め込めませんでした"
                               f"（{_intro_info.get('reason')}: "
                               f"{_intro_info.get('error') or _intro_info.get('file') or _intro_info.get('searched') or ''}）"
                               "。動画なしで HTML を作ります（Dataset の assets/video に intro_video.json と MP4 があるか確認）")
                    print(f"  ⚠ {_msg_iv}")
                    try:
                        from fortunelib.runcheck import add_warning as _add_warning_iv
                        _add_warning_iv(_msg_iv)
                    except Exception:
                        pass
            else:
                print("  ⏭ 冒頭動画カードはOFF（EMBED_INTRO_VIDEO=False）のためスキップ（HTML は通常どおり作成）")

            _html = build_html(_dir, person_id=_dir.name, images_dir=_images_dir,
                               intro_video_html=_intro_html)
            if _images_dir:
                # 表示: 実際に埋め込まれた枚数と、画像を持つデッキ数を数える
                # （固定のツール一覧だと陳腐化するため、生成済みHTMLと画像ディレクトリから集計する）
                _n_img, _n_deck = 0, 0
                try:
                    # mts5.69: 冒頭動画カードのサムネイルは数えない（占術画像ではない）
                    _n_img = (_html.read_text(encoding="utf-8").count("data:image")
                              - _intro_html.count("data:image"))
                    _root = _images_dir if _images_dir.name == "images" else _images_dir.parent
                    for _d in sorted(_root.iterdir()):
                        if _d.is_dir() and any(_f.suffix.lower() in (".webp", ".jpg", ".jpeg", ".png")
                                               for _f in _d.iterdir()):
                            _n_deck += 1
                except Exception:
                    pass
                # 簡易表示
                # mts5.55: ここで数えているのは**素材ディレクトリの数**（結果の対応先ではない）。
                # build_html 側の「対象 51デッキ（結果の対応先）」と混同しないよう書き分ける。
                print(f"  ✅ HTML: {_html}（{_html.stat().st_size/1024:.0f} KB）"
                      f"［画像埋め込み: {_images_dir}（{_n_img}枚 / 素材 {_n_deck}デッキ＝画像ディレクトリ）］")
            else:
                print(f"  ✅ HTML: {_html}（{_html.stat().st_size/1024:.0f} KB）")
        _PROCESSED_TARGETS += 1
    except Exception as _e:
        _message = f"{type(_e).__name__}: {_e}"
        _RUN_ERRORS.append({"stage": "N2", "target": str(_dir),
                            "message": _message})
        print(f"  ❌ {_dir.name}: {_message}")
        continue

if not _PROCESSED_TARGETS and not _RUN_ERRORS:
    _RUN_ERRORS.append({"stage": "N2", "target": "all",
                        "message": "処理対象の結果ファイルがありません"})

# mts5.53（P-10）: ここまでの警告（フォント・画像・再利用など）を1か所にまとめて出す。
# 既定は**警告のみ**で実行は続く（従来の運用を壊さない）。厳格に止めたいときだけ
# RUN_STRICT=1 を設定する（Kaggle なら先頭のセルで %env RUN_STRICT=1）。
try:
    from fortunelib.runcheck import WARNINGS as _WARNINGS, enforce as _enforce, report as _report
    if _WARNINGS:
        print("\n■ 警告（既定では合否に影響しません）")
    _report(prefix="  ⚠")
    _enforce()
except SystemExit:
    raise
except Exception as _e_warn:
    print(f"  ⚠ 警告の集約に失敗（{type(_e_warn).__name__}: {_e_warn}）")

print("\n■ 完了")
print("  synthesis_report.md  … 統合レポート（神々の節を含む）")
print("  cluster_reports/     … 軸サマリー＋分野別の中間レポート")
print("  *_report.html        … 全内容を1枚にまとめたHTML（スマホ保存用）")

if _RUN_ERRORS:
    _detail = "\n".join(
        f"[{e.get('stage')}] {e.get('target')}: {e.get('message')}"
        for e in _RUN_ERRORS[-20:])
    raise RuntimeError("占術シミュレーターがエラーで終了しました。上のログを確認してください。\n"
                       + _detail)

print(f"✅ 全工程が正常終了しました（{_PROCESSED_TARGETS}件）")
