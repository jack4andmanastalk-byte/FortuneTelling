# -*- coding: utf-8 -*-
"""
配布用 ZIP の生成と検査（開発側のみ）

出力: `build/zips/` などに作る ZIP（トップ＝`fortune_dataset/`、その中がリポジトリ直下の構成）。
除外: internal/ uploads/ build/ assets_bases/ font_sources/ __pycache__/ .pytest_cache/ *.pyc など
（EXCLUDE_DIRS / EXCLUDE_FILES）。

用途別:
  python3 tools/build_dataset_zip.py --with-images --out build/zips/fortune_dataset_kaggle_v1.0.0.zip
        # Kaggle Dataset 用（画像・冒頭動画込み）。未指定なら fortune_dataset_kaggle_<build_id>.zip
  python3 tools/build_dataset_zip.py                 # ソースのみ（画像なし）→ fortune_dataset.zip
  python3 tools/build_dataset_zip.py --images-only   # 画像だけ → fortune_images_<build_id>.zip
  python3 tools/build_dataset_zip.py --dry-run       # 対象ファイル数・サイズのみ表示
  python3 tools/build_dataset_zip.py --verify build/zips/<name>.zip
        # 作り終えた ZIP を読み取り専用で検査（CRC・重複・必須同梱物・版印・フォント・
        # 画像の枚数とハッシュ・秘密情報や個人識別子の混入）。

注意（容量）: 画像込み ZIP は 30MB 強。作業領域の上限が小さい環境では、作成 → 検査 → 削除の順で扱う。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import zipfile
from pathlib import Path

def _resolve_root() -> Path:
    """リポジトリの置き場所を実行環境から解決する（mts5.30）。

    mts5.28 で追加した同梱物検査（check_bundled_font）は Kaggle のセルフテスト
    （Cell 0.1）からも呼ばれる。以前は /home/user を固定で使っていたため、
    Kaggle（/kaggle/input/datasets/.../fortune_dataset/...）では**フォントが
    存在しないと誤判定**し、セルフテストが失敗して本番セルが実行されなかった。
    そこで「このファイルの2つ上（＝リポジトリ直下）」を基点にする。
    環境変数 FORTUNE_DATASET_ROOT があればそれを優先する。
    """
    import os
    env = os.environ.get("FORTUNE_DATASET_ROOT")
    if env:
        cand = Path(env).expanduser().resolve()
        if (cand / "fortune_dataset" / "data").is_dir():
            return cand
    here = Path(__file__).resolve().parent.parent
    if (here / "fortune_dataset" / "data").is_dir():
        return here
    # 想定外の配置（後方互換）
    return Path("/home/user/fortune_dataset")


ROOT = _resolve_root()          # リポジトリ直下（fortune_dataset/ パッケージを内包）
PKG = ROOT                      # 互換名（PKG / "fortune_dataset" / ... で参照）
# font_sources は開発用の元フォント置き場（配布物にはサブセットのみ同梱・mts5.32）
EXCLUDE_DIRS = {"__pycache__", "trash", ".pytest_cache", ".mypy_cache", "tmp_progress",
                "font_sources", "internal", "uploads", "build", "out_audit", "demo_out",
                ".git", ".idea", ".vscode",
                "assets_bases"}  # 原画退避（_clean）は別管理。--with-bases で解除
# mts5.35: 動画フォントの検査に使う文字（占術名・神名・型Cのラベル字）
FONT_SAMPLE_EXTRA = (
    "蟹座 獅子座 月 惑星 記号 並 四柱推命の旁・路、紫微斗数の擎・鉞、奇門遁甲の玄・虎・蛇 "
    "九星の乾・赤 ①②③ⅠⅡⅢ サンプル 様"
)

EXCLUDE_FILES = {".DS_Store", "ChatLog.md", "mts4.8_proposal.md",
                # 前セッションのターン別確認シート（デッキ全数シートに置き換え済み）
                "turn18_contact_sheet.webp", "turn19_genekeys_sheet.webp",
                "turn20_animal_sheet.webp", "turn21_genekeys_sheet.webp",
                "turn22_animal_sheet.webp"}
EXCLUDE_SUFFIX = {".pyc", ".pyo"}
IMAGE_SUFFIX = {".webp", ".jpg", ".jpeg", ".png"}
VIDEO_SUFFIX = {".mp4", ".m4v", ".webm"}      # mts5.69: 冒頭動画（assets/video）
OUT_ROOT = ROOT.parent              # 出力先（開発環境では /home/user）
DEFAULT_OUT = OUT_ROOT / "fortune_dataset.zip"

# --- 再現性（2026-09-25 追加）-----------------------------------------------
# ZIP は「ファイルの更新時刻」をエントリに記録するため、同じ内容でも作業環境によって
# バイト列（＝sha256）が変わってしまう（実例: 画像ZIPの中身は 768/768 同じなのに、
# ワークスペース復元で mtime が変わってハッシュが不一致になった）。
# 配布物のハッシュを突き合わせられるように、**エントリの時刻を固定**して再現可能にする。
FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def write_entry(z: zipfile.ZipFile, src: Path, arcname: str) -> None:
    """エントリを固定時刻で書き込む（内容だけに依存する決定的なZIPにする）。"""
    zi = zipfile.ZipInfo(arcname, date_time=FIXED_TIME)
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.external_attr = 0o644 << 16
    z.writestr(zi, src.read_bytes(), compresslevel=9)


def build_id() -> str:
    """data/dataset_version.json の build_id（例 2026-09-24-mts5.6）から版印 mts5.6 を取り出す。"""
    import json
    v = PKG / "fortune_dataset" / "data" / "dataset_version.json"
    try:
        return json.loads(v.read_text(encoding="utf-8"))["build_id"].split("-")[-1]
    except Exception:
        return "unknown"


def iter_files(include_bases: bool = False, images: str = "include") -> list[Path]:
    """images: "include"（全部）/ "exclude"（画像なし）/ "only"（画像だけ）"""
    out: list[Path] = []
    for p in sorted(PKG.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(PKG)
        excluded = set(EXCLUDE_DIRS) - ({"assets_bases"} if include_bases else set())
        if any(part in excluded for part in rel.parts):
            continue
        if p.name in EXCLUDE_FILES or p.suffix in EXCLUDE_SUFFIX:
            continue
        is_img = p.suffix.lower() in IMAGE_SUFFIX and "assets" in rel.parts and "images" in rel.parts
        # mts5.69: 冒頭動画の MP4（assets/video）は画像と同じ扱い＝Kaggle 用（--with-images）だけ同梱し、
        # 画像なし ZIP には入れない。設定 JSON とサムネイルは小さいので常に同梱する。
        is_video = p.suffix.lower() in VIDEO_SUFFIX and "assets" in rel.parts and "video" in rel.parts
        if images == "exclude" and (is_img or is_video):
            continue
        if images == "only" and not is_img:
            continue
        out.append(p)
    return out


def check_bundled_font(images: str) -> list[str]:
    """同梱フォントの検査（mts5.49で日本語fallbackを追加）。

    Kaggle には日本語フォントが無いため、型C・動画用の一次フォントに加えて、
    広い日本語fallbackフォントが必要です。既知の文字被覆と実際に描く文字を検査し、
    fallbackにも無い文字を含む場合はビルドを止めます。
    """
    problems = []
    base = PKG / "fortune_dataset"          # <リポジトリ>/fortune_dataset
    fonts = {
        "typec_jp_subset.ttf": 10_000,          # 日本語・漢字・英数（型Cチャート）
        "typec_devanagari_subset.ttf": 2_000,   # デーヴァナーガリー数字
        "typec_symbols_subset.ttf": 2_000,      # 惑星・星座・✓✗
        # mts5.49: 型C／動画共通の広い日本語fallback（JIS第1・第2水準＋配布物語彙）。
        "jp_cjk_fallback.ttf": 1_000_000,
    }
    for name, min_size in fonts.items():
        font = base / "assets" / "fonts" / name
        if name == "jp_cjk_fallback.ttf":
            tool = "tools/build_jp_fallback_font.py"
        else:
            tool = "tools/build_chart_fonts.py"
        if not font.is_file():
            problems.append(f"同梱フォントがありません: {font}（{tool} で生成）")
        elif font.stat().st_size < min_size:
            problems.append(
                f"同梱フォントが小さすぎます: {font}（{font.stat().st_size}B）")
    def _japanese_fallback_report(problems: list[str]) -> None:
        fallback = base / "assets" / "fonts" / "jp_cjk_fallback.ttf"
        if not fallback.is_file():
            return                                   # 無い場合は上の検査で報告済み
        try:
            from fontTools.ttLib import TTFont
            cmap = set(TTFont(str(fallback), lazy=True).getBestCmap() or {})
        except Exception as e:
            problems.append(f"※ 日本語fallbackの文字検査は省略（{type(e).__name__}）")
            return
        required = "ガ司庫栞"
        miss = [ch for ch in required if ord(ch) not in cmap]
        if miss:
            problems.append(
                f"日本語fallbackに既知の欠落文字がありません: {''.join(miss)}"
                "。tools/build_jp_fallback_font.py で再生成してください")

    # 実際に描く文字がフォントに入っているか（1文字でも欠ければ文字が消える）
    def _coverage_report(problems: list[str]) -> None:
        """① 実描画で 22占術の文字を採取（本命・計算ライブラリが要る）
        ② それが無理な環境では、コード内の文字列と定数で簡易検査（保険）
        どちらも実行できない場合は「省略」の注記だけ残して落ちない。"""
        import importlib.util as _ilu
        import sys as _sys
        if str(base) not in _sys.path:
            _sys.path.insert(0, str(base))
        try:
            from fortunelib import chartdraw           # noqa: PLC0415
        except Exception as e:
            problems.append(f"※ 文字の被覆検査は省略（fortunelib を読み込めません: "
                            f"{type(e).__name__}）")
            return
        mod = None
        tools = ROOT / "tools" / "build_chart_fonts.py"
        if tools.exists():
            try:
                spec = _ilu.spec_from_file_location("build_chart_fonts", tools)
                mod = _ilu.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception as e:
                mod = None
                problems.append(f"※ 実描画の被覆検査は省略（{type(e).__name__}）。"
                                "文字列ベースの検査のみ実施")
        else:
            problems.append("※ 実描画の被覆検査は省略（tools/ が無い環境）。"
                            "文字列ベースの検査のみ実施")
        # ① 22占術を実際に描いた採取（本番と同じ経路）
        missing, checked = [], 0
        if mod is not None and hasattr(mod, "_sample_cases"):
            try:
                for slug, calc, extra in mod._sample_cases():
                    try:
                        miss = chartdraw.missing_glyphs_for(slug, calc, extra)
                    except Exception:
                        continue
                    checked += 1
                    if miss:
                        missing.append((slug, miss))
            except Exception as e:                 # 計算ライブラリ未導入など
                checked = 0
                problems.append(f"※ 描画による被覆検査は省略（{type(e).__name__}: {e}）。"
                                "文字列ベースの検査のみ実施")
        if checked:
            if not missing:
                return                             # ★本命の検査に合格
            head = "、".join(f"{s2}: {''.join(ch for _r, ch in m[:4])}"
                            for s2, m in missing[:5])
            problems.append(
                f"一次フォントと日本語fallbackに無い文字を描いています（{len(missing)}占術）: {head}"
                "。tools/build_chart_fonts.py / tools/build_jp_fallback_font.py で再生成してください")
            return
        # ② 保険＝役割が自明なものは専用フォントで厳密に、それ以外は union 判定
        dev_chars = chartdraw.DEV_DIGITS
        sym_chars = ("".join(chartdraw.PLANET_SYM.values())
                     + "".join(chartdraw.SIGN_SYM) + "✓✗")
        bad = []
        for role, chars in (("dev", dev_chars), ("sym", sym_chars)):
            miss = chartdraw.missing_glyphs(chars, role)
            if miss:
                bad.append(f"{role}: {''.join(miss[:20])}")
        lits = ""
        if mod is not None and hasattr(mod, "_literals_in_chartdraw"):
            lits = mod._literals_in_chartdraw()
        other = "".join(ch for ch in lits
                        if ch not in dev_chars and ch not in sym_chars)
        if other:
            have = set()
            for f in sorted((base / "assets" / "fonts").glob("*.ttf")):
                try:
                    from fontTools.ttLib import TTFont as _TT
                    ft = _TT(str(f), fontNumber=0)
                    for t in ft["cmap"].tables:
                        have |= set(t.cmap.keys())
                except Exception:
                    pass
            miss_any = "".join(sorted({ch for ch in other
                                      if not ch.isspace() and ord(ch) not in have}))
            if miss_any:
                bad.append(f"cjk: {miss_any[:40]}")
        if bad:
            problems.append("同梱フォントに無い文字があります（文字列検査）: "
                            + " / ".join(bad)
                            + "。tools/build_chart_fonts.py でフォントを再生成してください")

    _coverage_report(problems)
    _japanese_fallback_report(problems)
    if images != "exclude":
        n_bases = len(list((base / "assets" / "images").glob("*/[a-z]*_base.webp")))
        if n_bases < 22:
            problems.append(f"型Cベース画像が不足しています: {n_bases} 枚（期待 22 以上）")
    return problems


# ZIP は「トップ＝リポジトリ直下 `fortune_dataset/`」（中の `fortune_dataset/` がパッケージ）。
# つまり全エントリは `fortune_dataset/<リポジトリ直下からの相対パス>` になる（mts5.52 で統一）。
ZIP_PREFIX = "fortune_dataset/"
VERIFY_REQUIRED = [                      # リポジトリ直下からの相対パス
    "LICENSE",                            # v1.0.0: AGPL-3.0（コード）
    "LICENSE-ASSETS",                     # v1.0.0: CC BY 4.0（画像・自作データ・プロンプト）
    "THIRD_PARTY_NOTICES.md",             # v1.0.0: 第三者データ・ライブラリ・商標
    "fortune_dataset/assets/fonts/OFL.txt",
    "fortune_dataset/data/kanji_kakusu_license.json",
    "fortune_dataset/data/dataset_version.json",
    "fortune_dataset/fortunelib/chartdraw.py",
    "fortune_dataset/kaggle/fortune_notebook.ipynb",
    "fortune_dataset/kaggle/cell0_selftest.py",
    "fortune_dataset/kaggle/people_sample.csv",
    "tools/build_chart_fonts.py",
    "verify/verify_run_output.py",
    "verify/asset_checksums.sha256",
]


def _zip_path(rel: str) -> str:
    """リポジトリ直下からの相対パス → ZIP エントリ名。"""
    return ZIP_PREFIX + rel
VERIFY_FONT_MIN = {"typec_jp_subset.ttf": 10_000,
                   "typec_devanagari_subset.ttf": 2_000,
                   "typec_symbols_subset.ttf": 2_000,
                   "jp_cjk_fallback.ttf": 1_000_000}
VERIFY_SECRET_PATTERNS = (
    ("Google API キー", re.compile(rb"AIza[0-9A-Za-z_\-]{35}")),
    ("OpenAI 風キー", re.compile(rb"sk-[A-Za-z0-9]{20,}")),
    ("Slack トークン", re.compile(rb"xox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("AWS キー", re.compile(rb"AKIA[0-9A-Z]{16}")),
    ("HuggingFace トークン", re.compile(rb"hf_[A-Za-z0-9]{20,}")),
    ("秘密鍵ブロック", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # mts5.52: 環境変数**名**はコード・文書に普通に出るため、値らしき文字列が続く場合だけ拾う
    ("KAGGLE 資格情報", re.compile(
        rb"KAGGLE_(?:KEY|USERNAME)[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{12,}")),
    ("APIキー代入", re.compile(
        rb"(?:api[_-]?key|apikey|token)\s*[:=]\s*[\"'][A-Za-z0-9_\-]{20,}[\"']",
        re.IGNORECASE)),
)
VERIFY_SECRET_NAMES = (".env", "kaggle.json", ".netrc")


def verify_zip(zpath) -> int:
    """作り終えたZIPを**読み取り専用**で検査する（mts5.52・F-8）。

    従来はビルド後の検証が無く、CRC・重複エントリ・画像枚数・同梱物・秘密情報の突合は
    毎回**手作業**でした（Turn 4 は手で実施）。ここでは ZIP を書き換えずに検査だけ行います。
    """
    zp = Path(zpath)
    if not zp.is_file():
        print(f"❌ ZIP がありません: {zp}")
        return 2
    try:
        z = zipfile.ZipFile(zp)
    except Exception as e:
        print(f"❌ ZIP を開けません（{type(e).__name__}: {e}）")
        return 2
    names = z.namelist()
    problems: list[str] = []
    notes: list[str] = []
    print(f"検査: {zp}（{zp.stat().st_size / 1e6:.1f} MB / {len(names)} エントリ）")

    # ① CRC（全エントリを読み切って検証。1件ずつ読むので zlib エラーでも止まらない）
    crc_bad = []
    for n in names:
        try:
            with z.open(n) as fh:
                while fh.read(1 << 20):
                    pass
        except Exception as e:
            crc_bad.append(f"{n}（{type(e).__name__}）")
    if crc_bad:
        problems.append(f"CRC/読込エラー {len(crc_bad)} 件: " + ", ".join(crc_bad[:5]))

    # ② 重複エントリ
    seen, dups = set(), []
    for n in names:
        if n in seen:
            dups.append(n)
        seen.add(n)
    if dups:
        problems.append(f"重複エントリ {len(dups)} 件: {', '.join(dups[:5])}")

    # ③ 必須の同梱物
    for req in VERIFY_REQUIRED:
        if _zip_path(req) not in names:
            problems.append(f"同梱物がありません: {_zip_path(req)}")

    # ④ 版印（dataset_version.json）
    ver = None
    try:
        raw = z.read(_zip_path("fortune_dataset/data/dataset_version.json")).decode("utf-8")
        ver = json.loads(raw)
        print(f"  版印: {ver.get('build_id', '?')}"
              f"（expected: {ver.get('expected')}）")
    except Exception as e:
        problems.append(f"dataset_version.json を読めません（{type(e).__name__}）")

    # ⑤ 同梱フォント（サイズ下限）
    for name, min_size in VERIFY_FONT_MIN.items():
        entry = _zip_path(f"fortune_dataset/assets/fonts/{name}")
        if entry not in names:
            problems.append(f"同梱フォントがありません: {entry}")
            continue
        size = z.getinfo(entry).file_size
        if size < min_size:
            problems.append(f"同梱フォントが小さすぎます: {entry}（{size}B）")

    # ⑤b 冒頭動画（mts5.69）: 設定 JSON があれば、Kaggle 用 ZIP では MP4 の SHA-256 を設定値と突合し、
    #     画像なし ZIP では「非同梱」を注記する（画像と同じ扱い）。
    _iv_cfg_entry = _zip_path("fortune_dataset/assets/video/intro_video.json")
    if _iv_cfg_entry in names:
        try:
            _iv_cfg = json.loads(z.read(_iv_cfg_entry).decode("utf-8"))
        except Exception as e:
            _iv_cfg = None
            problems.append(f"intro_video.json を読めません（{type(e).__name__}）")
        if isinstance(_iv_cfg, dict) and _iv_cfg.get("file"):
            _iv_entry = _zip_path(f"fortune_dataset/assets/video/{_iv_cfg['file']}")
            _iv_poster = _zip_path(f"fortune_dataset/assets/video/{_iv_cfg.get('poster') or ''}")
            if _iv_entry in names:
                got = hashlib.sha256(z.read(_iv_entry)).hexdigest()
                want = str(_iv_cfg.get("sha256") or "").lower()
                size = z.getinfo(_iv_entry).file_size
                if want and got != want:
                    problems.append(f"冒頭動画の SHA-256 が intro_video.json と一致しません: {_iv_entry}")
                else:
                    print(f"  冒頭動画: {_iv_cfg['file']}（{size / 1e6:.2f} MB・SHA-256 "
                          f"{'一致' if want else '設定なし'}・poster "
                          f"{'有' if _iv_cfg.get('poster') and _iv_poster in names else '無'}）")
                if _iv_cfg.get("poster") and _iv_poster not in names:
                    problems.append(f"冒頭動画のサムネイルがありません: {_iv_poster}")
            else:
                notes.append(f"冒頭動画 {_iv_cfg['file']} は非同梱（画像なし ZIP）。"
                             "Kaggle 用は --with-images で同梱されます")

    # ⑥ 画像（枚数とハッシュ: 同梱のチェックサム表と突合）
    img_root = _zip_path("fortune_dataset/assets/images/")
    img_entries = [n for n in names
                   if n.startswith(img_root)
                   and Path(n).suffix.lower() in IMAGE_SUFFIX]
    if not img_entries:
        notes.append("画像は非同梱（画像なし ZIP）。チェックサム表との突合は省略しました")
    else:
        try:
            manifest = z.read(_zip_path("verify/asset_checksums.sha256")).decode("utf-8")
        except Exception:
            manifest = ""
        if not manifest:
            problems.append("チェックサム表（verify/asset_checksums.sha256）を読めません")
        else:
            listed = mismatched = missing = 0
            for line in manifest.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(None, 1)
                if len(parts) != 2:
                    continue
                want, rel = parts
                listed += 1
                entry = posixpath.normpath(img_root + rel)
                if entry not in names:
                    missing += 1
                    problems.append(f"チェックサム表のファイルがZIPにありません: {entry}")
                    continue
                got = hashlib.sha256(z.read(entry)).hexdigest()
                if got != want:
                    mismatched += 1
                    problems.append(f"ハッシュ不一致: {entry}")
            print(f"  画像: {len(img_entries)} 枚 / チェックサム表 {listed} 件"
                  f"（不一致 {mismatched}・欠落 {missing}）")
            n_fonts = len(VERIFY_FONT_MIN)
            if listed and listed != len(img_entries) + n_fonts:   # 画像＋フォント
                notes.append(f"チェックサム表 {listed} 件に対し、ZIP の画像は"
                             f"{len(img_entries)} 枚（画像＋フォント{n_fonts}点＝{len(img_entries) + n_fonts} 件が期待値）")

    # ⑦ 秘密情報（ファイル名と本文）
    for n in names:
        base = Path(n).name
        if base in VERIFY_SECRET_NAMES or base.endswith((".pem", ".key")):
            problems.append(f"秘密情報らしきファイル: {n}")
    scanned = 0
    for n in names:
        if n.endswith("/"):
            continue
        if Path(n).suffix.lower() in (".webp", ".jpg", ".jpeg", ".png", ".ttf", ".zip"):
            continue
        try:
            blob = z.read(n)
        except Exception:
            continue
        scanned += 1
        for label, rx in VERIFY_SECRET_PATTERNS:
            if rx.search(blob):
                problems.append(f"秘密情報らしき文字列（{label}）: {n}")
    print(f"  秘密情報スキャン: テキスト系 {scanned} ファイル（画像・フォントは除外）")

    for x in notes:
        print(f"  ℹ {x}")
    if problems:
        print(f"\n❌ 不合格（{len(problems)}件）:")
        for x in problems[:40]:
            print(f"   - {x}")
        if len(problems) > 40:
            print(f"   … 他 {len(problems) - 40} 件")
        return 1
    print("\n✅ 合格: CRC・重複・同梱物・版印・フォント・画像・秘密情報に問題はありません")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None,
                    help="出力先（未指定なら用途別の既定名。画像なし=fortune_dataset.zip / "
                         "画像込み=fortune_dataset_kaggle_<版>.zip / 画像のみ=fortune_images_<版>.zip）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--with-bases", action="store_true", help="原画退避 assets_bases を同梱する")
    ap.add_argument("--bases-zip", default=None, help="原画退避だけの別ZIPを作成する")
    ap.add_argument("--with-images", action="store_true",
                    help="納品画像（assets/images）を同梱する。**Kaggle Dataset 用**"
                         "（既定は画像を除外したソースのみ）")
    ap.add_argument("--no-images", action="store_true",
                    help="（既定と同義・後方互換。画像を除外する）")
    ap.add_argument("--images-only", action="store_true",
                    help="画像だけの ZIP を作る")
    ap.add_argument("--verify", default=None, metavar="ZIP",
                    help="既存のZIPを読み取り専用で検査する（mts5.52・F-8）")
    args = ap.parse_args()

    if args.verify:
        return verify_zip(args.verify)

    if args.images_only:
        imgs = [q for q in sorted((PKG / "fortune_dataset" / "assets" / "images").rglob("*"))
                if q.is_file() and q.suffix.lower() in IMAGE_SUFFIX]
        raw = sum(q.stat().st_size for q in imgs)
        out = Path(args.out) if args.out else OUT_ROOT / f"fortune_images_{build_id()}.zip"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for q in imgs:
                write_entry(z, q, str(Path("assets") / "images"
                                      / q.relative_to(PKG / "fortune_dataset" / "assets" / "images")))
        print(f"画像のみ: {len(imgs)} 枚 / 非圧縮 {raw / 1e6:.1f} MB -> {out} = {out.stat().st_size / 1e6:.2f} MB")
        return 0

    if args.bases_zip:
        bases = [q for q in sorted((PKG / "assets_bases").rglob("*")) if q.is_file()]
        raw = sum(q.stat().st_size for q in bases)
        out = Path(args.bases_zip)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for q in bases:
                write_entry(z, q, str(Path("assets_bases") / q.relative_to(PKG / "assets_bases")))
        print(f"原画退避のみ: {len(bases)} ファイル / 非圧縮 {raw / 1e6:.1f} MB -> {out} = {out.stat().st_size / 1e6:.2f} MB")
        return 0

    mode = "include" if args.with_images else "exclude"
    # mts5.49: 型C／動画の一次フォントと日本語fallbackを必ず同梱する
    font_problems = check_bundled_font(mode)
    if font_problems:
        # mts5.52（F-8 の指摘）: 「検査を省略した」注記と「本当の問題」を分けて表示する
        # （どちらも安全側でビルドは中止するが、原因の見当が付くようにする）。
        skipped = [x for x in font_problems if x.startswith("※")]
        real = [x for x in font_problems if not x.startswith("※")]
        if real:
            print("❌ 同梱物の検査で問題があります（画像に文字が入らない不具合の原因）:")
            for x in real:
                print(f"   - {x}")
        if skipped:
            print("⚠ 同梱物の検査を完了できませんでした（安全側でビルドを中止します）:")
            for x in skipped:
                print(f"   - {x}")
        return 2
    files = iter_files(include_bases=args.with_bases, images=mode)
    raw = sum(p.stat().st_size for p in files)
    print(f"対象: {len(files)} ファイル / 非圧縮 {raw / 1e6:.1f} MB")
    if args.dry_run:
        return 0

    if args.out:
        out = Path(args.out)
    elif mode == "include":
        out = OUT_ROOT / f"fortune_dataset_kaggle_{build_id()}.zip"
    else:
        out = DEFAULT_OUT
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in files:
            write_entry(z, p, str(Path("fortune_dataset") / p.relative_to(PKG)))
    n_img = sum(1 for p in files if p.suffix.lower() in IMAGE_SUFFIX and "images" in p.parts)
    print(f"作成: {out} = {out.stat().st_size / 1e6:.1f} MB（画像 {n_img} 枚"
          f"{'・画像は除外' if mode == 'exclude' else ''}）")
    if mode == "include":
        print("  → Kaggle Dataset の New Version にアップロードするZIPです（画像込み）。")
    else:
        print("  → ソースのみの ZIP です（画像は含みません。画像込みは --with-images）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
