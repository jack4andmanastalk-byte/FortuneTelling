# -*- coding: utf-8 -*-
"""mts5.53 の製品側ガードの回帰テスト（P-1〜P-10 のうち製品コード側）

背景（製品側ツールの独立監査・2026-09-29）:
  * P-1: 画像が欠けても**例外も警告も出ず**、HTML は「※…仕様です」表示に化けていた
    （M27_angel のディレクトリを隠すと 87枚 → 84枚、警告0）。
  * P-2: スキップガードは「md の存在＝前回の成功」だけで、入力を変えても古い鑑定文が残った。
  * P-4: `jp_cjk_fallback.ttf` を隠すと**警告0のまま画像だけ変わる**（M15 で 55px 差）。
  * P-5/P-6: 画像ツールの既定出力が納品先そのもの／`--fresh` が任意の `--out/<pid>` を削除。
  * P-7: 画像0枚の実行が正常と区別できなかった。
  * P-9: `*_raw.json` にモデル名が残らなかった。
  * P-10: 警告の集約・合否への反映が無かった（RUN_STRICT=1 で不合格にする）。

すべて**既定の挙動は従来どおり**（警告のみ）であることも合わせて固定する。

**mts5.54 の修正（2026-09-29・Kaggle実機で発覚）**: `test_no_images_dir_is_distinguishable` は
「`images_dir=None` なら画像は入らない」と決め打ちしていましたが、`build_html` には
**画像ディレクトリの自動探索**（mts4.6・`/kaggle/input/**/assets/images` を探す）があるため、
**Kaggle では画像が見つかって `no_assets_root=False` になり失敗**しました（`FAILED (failures=1)`、
1008件中1件）。テストの側が環境依存だったのが原因で、製品の挙動は正しい（Kaggle で自動探索が
効くのは意図どおり）ため、探索を `_auto_discover_assets_root()` として切り出して
**テストで経路を固定**できるようにしました。**同じ罠を二度踏まないよう、探索そのものの
テスト（自動探索で画像が入る場合／入らない場合）もここに追加**しています。

**mts5.55 の修正（2026-09-29・同じ実機の続き）**: `test_` ではなく**製品側の取りこぼし**を1件直しました。
再利用の内訳（`fortunelib.pipeline.SKIP_STATS`）はプロセス共通のカウンタで、**セルフテスト
（Cell 0.1）で起きた再利用が本番セル（Cell 1）のログ・警告に持ち越され**、「本番では1件も
再利用していないのに『旧版の成果物を1件 再利用しました』」と表示されていました
（`RUN_STRICT=1` なら本番セルが誤って不合格）。人ごとの冒頭と本番セル・ローカル生成ツールの
冒頭で0に戻し、内訳が0のときは行を出さないようにしました。あわせて、紛らわしかった
デッキ数の表記（結果の対応先 / 素材ディレクトリ）を書き分け、`index.md` を作らないのに
「index.md に一覧」と案内していた文を実態に合わせました。
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil

from tests.fixtures.consultation import CONSULTATION, CONSULTATION_ALT
import sys
import tempfile
import unittest
import warnings
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest import mock

PKG = Path(__file__).resolve().parents[1]              # …/fortune_dataset（パッケージ）
REPO = PKG.parent                                      # リポジトリ直下

for _p in (str(PKG), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fortunelib import mts                                         # noqa: E402
from fortunelib import pipeline                                    # noqa: E402
from fortunelib import runcheck                                   # noqa: E402
from fortunelib.backend import MockBackend                         # noqa: E402
from fortunelib.pipeline import (PipelineContext, input_fingerprint,  # noqa: E402
                                model_meta, run_divination,
                                stored_fingerprint)
from fortunelib.profile import normalize_input
from tests.fixtures.consultation import (CONSULTATION,                   # noqa: E402
                                         CONSULTATION_ALT)
from fortunelib.schema import build_result                         # noqa: E402

_IMAGES = PKG / "assets" / "images"


@contextmanager
def _patch_discovery(mod, value):
    """画像ディレクトリの自動探索そのものを差し替える（環境から独立させる・mts5.54）。"""
    original = mod._auto_discover_assets_root
    mod._auto_discover_assets_root = (lambda: value)
    try:
        yield
    finally:
        mod._auto_discover_assets_root = original


@contextmanager
def _only_candidates(mod, candidates):
    """自動探索の**候補だけ**を差し替える（glob・列挙場所・環境変数も無効化）。

    Kaggle では絶対パス（`/kaggle/input/**/assets/images`）も候補になるため、CWD を変えるだけでは
    テストが環境に依存したままです。ここでは探索の入力（候補・glob・基底・環境変数）を
    すべて空にしてから、指定した候補だけを見せます。
    """
    saved = (mod.DISCOVERY_CANDIDATES, mod.DISCOVERY_GLOBS, mod.DISCOVERY_BASES,
             os.environ.get("FORTUNE_DATA_DIR"), os.environ.get("FORTUNE_ASSETS_DIR"))
    mod.DISCOVERY_CANDIDATES = [Path(c) for c in candidates]
    mod.DISCOVERY_GLOBS = []
    mod.DISCOVERY_BASES = []
    os.environ.pop("FORTUNE_DATA_DIR", None)
    os.environ.pop("FORTUNE_ASSETS_DIR", None)
    try:
        yield
    finally:
        (mod.DISCOVERY_CANDIDATES, mod.DISCOVERY_GLOBS, mod.DISCOVERY_BASES) = saved[:3]
        for _k, _v in (("FORTUNE_DATA_DIR", saved[3]), ("FORTUNE_ASSETS_DIR", saved[4])):
            if _v is not None:
                os.environ[_k] = _v


@contextmanager
def _no_auto_discovery(mod):
    """自動探索を無効化する（画像ディレクトリ未指定の経路を固定する）。"""
    with _patch_discovery(mod, None):
        yield


@contextmanager
def _strict(value: str | None):
    """RUN_STRICT を一時的に設定する（後片付けつき）。"""
    old = os.environ.get("RUN_STRICT")
    try:
        if value is None:
            os.environ.pop("RUN_STRICT", None)
        else:
            os.environ["RUN_STRICT"] = value
        yield
    finally:
        if old is None:
            os.environ.pop("RUN_STRICT", None)
        else:
            os.environ["RUN_STRICT"] = old


def _ctx(backend=None, consultation=CONSULTATION, tmp: Path | None = None,
         target: str | None = None) -> PipelineContext:
    raw = {
        "birth": {"date": "1990-01-15", "time": "05:20", "place": "福岡県"},
        "gender": "M", "blood_type": "A",
        "name_kanji": "山田 太郎", "name_kana": "やまだ たろう",
        "consultation": consultation,
    }
    if target:
        raw["target"] = target
    ni = normalize_input(raw)
    calc = {
        "tarot": {"spread": "three", "cards": [{"name_ja": "節制"}]},
        "target_date": {"date": target or "2026-09-29", "is_today": target is None},
    }
    d = tmp or Path(tempfile.mkdtemp())
    return PipelineContext(
        inputs=ni, profile_facts={"太陽星座": "山羊座"},
        calc_results=calc, consultation=ni.consultation,
        results_dir=d / "results", summary_path=d / "profile_summary.json",
        backend=backend or MockBackend(), seed=42,
    )


class TestRuncheck(unittest.TestCase):
    """警告台帳と RUN_STRICT（P-10）"""

    def setUp(self):
        runcheck.clear()
        self.addCleanup(runcheck.clear)

    def tearDown(self):
        # mts5.54: テスト由来の警告を台帳に残さない（本番セルへ持ち越さない）
        runcheck.clear()

    def test_add_and_dedupe(self):
        runcheck.add_warning("同じ警告")
        runcheck.add_warning("同じ警告")
        runcheck.add_warning("  ")
        self.assertEqual(runcheck.WARNINGS, ["同じ警告"])

    def test_report_counts_and_since(self):
        import io
        from contextlib import redirect_stdout
        runcheck.add_warning("a")
        with redirect_stdout(io.StringIO()):           # テスト出力を汚さない
            mark = runcheck.report_since(0, prefix="  ⚠")
        self.assertEqual(mark, 1)
        runcheck.add_warning("b")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(runcheck.report_since(mark, prefix="  ⚠"), 2)
            self.assertEqual(runcheck.report(), 2)

    def test_default_does_not_fail(self):
        """既定（RUN_STRICT 無し）では**止めない**＝従来の運用を壊さない"""
        runcheck.add_warning("警告だけ")
        with _strict(None):
            self.assertFalse(runcheck.strict_enabled())
            runcheck.enforce()          # SystemExit しない

    def test_strict_fails_only_with_warnings(self):
        import io
        from contextlib import redirect_stdout
        with _strict("1"):
            runcheck.enforce()          # 警告が無ければ通る
            runcheck.add_warning("警告あり")
            with redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    runcheck.enforce()
            self.assertEqual(cm.exception.code, 1)

    def test_strict_truthy_values(self):
        for v in ("1", "true", "TRUE", "Yes", "on"):
            with _strict(v):
                self.assertTrue(runcheck.strict_enabled(), v)
        for v in ("0", "false", "", "no", "off"):
            with _strict(v):
                self.assertFalse(runcheck.strict_enabled(), v)


class TestInputFingerprint(unittest.TestCase):
    """スキップガードの指紋（P-2）"""

    ENTRY = {"mcode": "M27", "slug": "tarot", "prompt_id": "p_tarot",
             "calc_key": "tarot", "group": "G1"}

    def test_same_inputs_same_fingerprint(self):
        a = input_fingerprint(_ctx(), self.ENTRY)
        b = input_fingerprint(_ctx(), self.ENTRY)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 16)

    def test_consultation_and_target_change(self):
        base = input_fingerprint(_ctx(), self.ENTRY)
        self.assertNotEqual(base, input_fingerprint(
            _ctx(consultation=CONSULTATION_ALT), self.ENTRY))
        self.assertNotEqual(base, input_fingerprint(_ctx(target="2026-10-03"), self.ENTRY))

    def test_birth_date_change(self):
        ctx = _ctx()
        other = _ctx()
        other.inputs.birth.date = other.inputs.birth.date.replace(year=1980)
        self.assertNotEqual(input_fingerprint(ctx, self.ENTRY),
                            input_fingerprint(other, self.ENTRY))

    def test_calc_is_excluded(self):
        """抽選系（タロット等）は実行ごとに引き直すのが仕様＝calc は指紋に含めない"""
        a = _ctx()
        b = _ctx()
        b.calc_results["tarot"]["cards"] = [{"name_ja": "運命の輪"}]
        self.assertEqual(input_fingerprint(a, self.ENTRY),
                         input_fingerprint(b, self.ENTRY))

    def test_stored_fingerprint_reads_raw(self):
        d = Path(tempfile.mkdtemp())
        raw = d / "M27_tarot_raw.json"
        self.assertIsNone(stored_fingerprint(raw))
        raw.write_text(json.dumps({"input_fingerprint": "abc123"}), encoding="utf-8")
        self.assertEqual(stored_fingerprint(raw), "abc123")
        raw.write_text("{壊れたJSON", encoding="utf-8")
        self.assertIsNone(stored_fingerprint(raw))          # 壊れていても例外にしない


class TestSkipGuardBehaviour(unittest.TestCase):
    """run_divination の再利用・作り直し（P-2/P-9）"""

    def _run(self, ctx, slug="tarot", **kw):
        return run_divination(slug, ctx, backend=ctx.backend, **kw)

    def test_fingerprint_match_reuses_and_mismatch_regenerates(self):
        import io
        from contextlib import redirect_stdout
        tmp = Path(tempfile.mkdtemp())
        ctx = _ctx(tmp=tmp)
        r1 = self._run(ctx)
        self.assertEqual(r1["status"], "ok", r1)
        self.assertTrue(r1.get("model", {}).get("name"))     # P-9: モデル名が残る
        # 2回目（同じ入力）＝再利用
        buf = io.StringIO()
        with redirect_stdout(buf):
            r2 = self._run(ctx)
        self.assertEqual(r2["status"], "skipped")
        self.assertEqual(r2["skip_reason"], "fingerprint_match")
        # 入力（相談内容）を変える＝作り直す（黙って古い結果を残さない）
        ctx2 = _ctx(tmp=tmp, consultation=CONSULTATION_ALT)
        buf = io.StringIO()
        with redirect_stdout(buf):
            r3 = self._run(ctx2)
        self.assertEqual(r3["status"], "ok")
        self.assertIn("作り直します", buf.getvalue())

    def test_missing_fingerprint_warns_and_reuses(self):
        import io
        from contextlib import redirect_stdout
        tmp = Path(tempfile.mkdtemp())
        ctx = _ctx(tmp=tmp)
        self._run(ctx)
        raw = tmp / "results" / "M27_tarot_raw.json"
        data = json.loads(raw.read_text(encoding="utf-8"))
        data.pop("input_fingerprint", None)                 # 旧版の成果物を再現
        raw.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        runcheck.clear()
        self.addCleanup(runcheck.clear)
        buf = io.StringIO()
        with redirect_stdout(buf):
            r = self._run(ctx)
        self.assertEqual(r["status"], "skipped")
        self.assertEqual(r["skip_reason"], "no_fingerprint")
        self.assertTrue(any("旧版" in w for w in runcheck.WARNINGS))

    def test_raw_records_model_and_fingerprint(self):
        tmp = Path(tempfile.mkdtemp())
        ctx = _ctx(tmp=tmp)
        self._run(ctx, model_hint="gemini-3.1-flash-lite")
        raw = json.loads((tmp / "results" / "M27_tarot_raw.json").read_text(encoding="utf-8"))
        self.assertEqual(raw["model"]["name"], "gemini-3.1-flash-lite")
        self.assertTrue(raw["input_fingerprint"])
        md = (tmp / "results" / "M27_tarot.md").read_text(encoding="utf-8")
        self.assertIn("生成モデル：gemini-3.1-flash-lite", md)


class TestModelMeta(unittest.TestCase):
    """モデル名の記録（P-9）"""

    def test_hint_used_when_backend_is_anonymous(self):
        meta = model_meta(MockBackend(), "gemini-2.5-flash")
        self.assertEqual(meta["name"], "gemini-2.5-flash")
        self.assertFalse(meta["fallback"])

    def test_fallback_flag(self):
        be = MockBackend()
        be.model_name = "gemini-3.1-flash-lite"
        be.resolved_model_name = "gemini-3.5-flash"
        meta = model_meta(be)
        self.assertTrue(meta["fallback"])
        self.assertEqual(meta["requested"], "gemini-3.1-flash-lite")
        self.assertEqual(meta["name"], "gemini-3.5-flash")

    def test_no_backend_info(self):
        class _Anonymous:
            pass
        self.assertEqual(model_meta(_Anonymous())["name"], "(不明)")

    def test_schema_keys_are_optional(self):
        base = build_result(module="M00", divination="x", inputs={},
                            approx_flags=[], result={})
        self.assertNotIn("model", base)
        self.assertNotIn("input_fingerprint", base)
        with_meta = build_result(module="M00", divination="x", inputs={},
                                 approx_flags=[], result={},
                                 model={"name": "m"}, input_fingerprint="f")
        self.assertEqual(with_meta["model"], {"name": "m"})
        self.assertEqual(with_meta["input_fingerprint"], "f")


class TestHtmlImageAudit(unittest.TestCase):
    """画像監査（P-1/P-7）"""

    @classmethod
    def setUpClass(cls):
        try:
            import PIL  # noqa: F401
        except ImportError:                                  # pragma: no cover
            raise unittest.SkipTest("PIL が無い環境のためスキップ")
        cls.images = _IMAGES
        if not (cls.images / "M27_tarot" / "00_Fool.jpg").is_file():
            raise unittest.SkipTest("納品画像が無い環境のためスキップ")

    def _person(self, tmp: Path, slugs=("M27_tarot",)) -> Path:
        p = tmp / "person"
        (p / "results").mkdir(parents=True)
        for stem in slugs:
            (p / "results" / f"{stem}.md").write_text(
                f"# {stem}\n\n## ■ 鑑定文\n\n本文テストです。\n", encoding="utf-8")
        (p / "results" / "M27_tarot_raw.json").write_text(json.dumps(
            {"result": {"calc": {"cards": [
                {"name_en": "The Fool", "position": "1枚目", "upright": True,
                 "arcana": "major", "card_id": 0}]}}}), encoding="utf-8")
        return p

    def test_ok_counts_and_no_warning(self):
        from fortunelib import html_report
        tmp = Path(tempfile.mkdtemp())
        p = self._person(tmp)
        aroot = tmp / "assets" / "images"
        (aroot / "M27_tarot").mkdir(parents=True)
        shutil.copy(self.images / "M27_tarot" / "00_Fool.jpg",
                    aroot / "M27_tarot" / "00_Fool.jpg")
        runcheck.clear()
        self.addCleanup(runcheck.clear)
        html = html_report.build_html(p, person_id="t", images_dir=aroot)
        self.assertEqual(html_report.IMAGE_AUDIT["images"], 1)
        self.assertEqual(html_report.IMAGE_AUDIT["decks_with_images"], 1)
        self.assertEqual(runcheck.WARNINGS, [])

    def test_missing_deck_dir_is_reported(self):
        """P-1 の陽性対照: 素材ディレクトリを隠すと警告＋本文注記が出る（従来は無言）"""
        from fortunelib import html_report
        tmp = Path(tempfile.mkdtemp())
        p = self._person(tmp, slugs=("M27_tarot", "M27_angel"))
        aroot = tmp / "assets" / "images"
        (aroot / "M27_tarot").mkdir(parents=True)
        shutil.copy(self.images / "M27_tarot" / "00_Fool.jpg",
                    aroot / "M27_tarot" / "00_Fool.jpg")
        runcheck.clear()
        self.addCleanup(runcheck.clear)
        html = html_report.build_html(p, person_id="t", images_dir=aroot)
        self.assertEqual(html_report.IMAGE_AUDIT["no_deck_dir_decks"], ["M27_angel"])
        self.assertTrue(any("M27_angel" in w for w in runcheck.WARNINGS))
        self.assertIn("画像を埋め込めなかった占術があります",
                      html.read_text(encoding="utf-8"))

    def test_no_images_dir_is_distinguishable(self):
        """P-7: 画像0枚の実行は「画像ディレクトリ未指定」として区別できる

        mts5.54: **自動探索を無効化してから**確かめます（Kaggle では `/kaggle/input/**` の
        画像が見つかってしまうため、探索を止めないとこの経路は再現できません）。
        """
        from fortunelib import html_report
        tmp = Path(tempfile.mkdtemp())
        p = self._person(tmp)
        runcheck.clear()
        self.addCleanup(runcheck.clear)
        with _no_auto_discovery(html_report):
            html_report.build_html(p, person_id="t", images_dir=None)
        self.assertTrue(html_report.IMAGE_AUDIT["no_assets_root"])
        self.assertEqual(html_report.IMAGE_AUDIT["images"], 0)
        self.assertTrue(any("画像ディレクトリ未指定" in w for w in runcheck.WARNINGS))

    def test_auto_discovery_is_used_when_dir_is_omitted(self):
        """自動探索（mts4.6）が生きていること＝Kaggle で `images_dir=None` でも画像が入る

        mts5.53 の実機で **探索が効いていた** ことを、環境に依存せずに固定します。
        """
        from fortunelib import html_report
        tmp = Path(tempfile.mkdtemp())
        p = self._person(tmp)
        aroot = tmp / "assets" / "images"
        (aroot / "M27_tarot").mkdir(parents=True)
        shutil.copy(self.images / "M27_tarot" / "00_Fool.jpg",
                    aroot / "M27_tarot" / "00_Fool.jpg")
        runcheck.clear()
        self.addCleanup(runcheck.clear)
        with _only_candidates(html_report, [aroot]):        # Kaggle の絶対パスは見せない
            html_report.build_html(p, person_id="t", images_dir=None)
        self.assertFalse(html_report.IMAGE_AUDIT["no_assets_root"])
        self.assertEqual(html_report.IMAGE_AUDIT["images"], 1)

    def test_auto_discovery_is_off_when_nothing_is_found(self):
        """探索しても見つからなければ None（＝画像0枚の成果物として区別できる）"""
        from fortunelib import html_report
        with _only_candidates(html_report, []):
            self.assertIsNone(html_report._auto_discover_assets_root())

    def test_auto_discovery_requires_tarot_deck(self):
        """探索の合格条件は `M27_tarot` を持つこと（デッキが1つも無い場所では拾わない）"""
        from fortunelib import html_report
        tmp = Path(tempfile.mkdtemp())
        aroot = tmp / "assets" / "images"
        (aroot / "M30_crystal").mkdir(parents=True)
        with _only_candidates(html_report, [aroot]):
            self.assertIsNone(html_report._auto_discover_assets_root())   # タロットが無い
            (aroot / "M27_tarot").mkdir()
            found = html_report._auto_discover_assets_root()
            self.assertIsNotNone(found)
            self.assertEqual(Path(found).resolve(), aroot.resolve())

    def test_audit_line_names_both_deck_counts(self):
        """mts5.55: 「対象（結果の対応先）」と「素材あり（実際に埋め込み）」を書き分ける

        Kaggle の実機では build_html の「対象 51デッキ」と Cell N2 の「画像あり48デッキ」が
        同じ実行に出て紛らわしかった（数えている対象が違う）。数字の意味を語に埋める。
        """
        from fortunelib import html_report
        tmp = Path(tempfile.mkdtemp())
        p = self._person(tmp)
        aroot = tmp / "assets" / "images"
        (aroot / "M27_tarot").mkdir(parents=True)
        shutil.copy(self.images / "M27_tarot" / "00_Fool.jpg",
                    aroot / "M27_tarot" / "00_Fool.jpg")
        runcheck.clear()
        self.addCleanup(runcheck.clear)
        buf = io.StringIO()
        with redirect_stdout(buf):
            html_report.build_html(p, person_id="t", images_dir=aroot)
        lines = [l for l in buf.getvalue().splitlines() if "[画像] 埋め込み" in l]
        self.assertEqual(len(lines), 1, buf.getvalue())
        self.assertIn("対象 1デッキ（結果の対応先）", lines[0])
        self.assertIn("素材あり 1デッキ（実際に埋め込み）", lines[0])
        self.assertNotIn("画像あり", lines[0])            # 紛らわしい旧表記は使わない

    def test_production_candidates_keep_kaggle_paths(self):
        """本番の探索候補（Kaggle の汎用マウント名・glob・列挙場所）を消していないこと（回帰の見張り）

        v1.0.0: 個人アカウント名を含むパスは置かない（公開版）。所有者名が何であっても
        `/kaggle/input/**/assets/images` の glob と `/kaggle/input` 直下の列挙で拾う。
        """
        from fortunelib import html_report as H
        cands = [str(p) for p in H.DISCOVERY_CANDIDATES]
        self.assertEqual(cands[0], "assets/images")
        self.assertTrue(any("/kaggle/input/fortune-dataset" in c for c in cands))
        # 固定候補は「相対の assets/images」と「汎用の Dataset 名」だけ（所有者名つきのパスは置かない）
        self.assertTrue(all(c == "assets/images" or c.startswith("/kaggle/input/fortune-dataset")
                            for c in cands), cands)
        self.assertEqual([str(b) for b in H.DISCOVERY_BASES], ["/kaggle/input"])
        self.assertIn("/kaggle/input/**/assets/images", H.DISCOVERY_GLOBS)
        self.assertEqual(H.DISCOVERY_REQUIRED_DECK, "M27_tarot")
        self.assertTrue(any(str(b) == "/kaggle/input" for b in H.DISCOVERY_BASES))
        self.assertEqual(H.ASSETS_DIR_ENV, "FORTUNE_ASSETS_DIR")

    def test_assets_dir_env_has_top_priority(self):
        """`FORTUNE_ASSETS_DIR` は候補より優先され、`assets/images` 自体でも親でも受け付ける"""
        from fortunelib import html_report as H
        tmp = Path(tempfile.mkdtemp())
        a = tmp / "a" / "assets" / "images"
        b = tmp / "b" / "assets" / "images"
        for r in (a, b):
            (r / "M27_tarot").mkdir(parents=True)
        with _only_candidates(H, [a]):
            self.assertEqual(Path(H._auto_discover_assets_root()).resolve(), a.resolve())
            os.environ["FORTUNE_ASSETS_DIR"] = str(b)                 # 画像ディレクトリそのもの
            self.assertEqual(Path(H._auto_discover_assets_root()).resolve(), b.resolve())
            os.environ["FORTUNE_ASSETS_DIR"] = str(tmp / "b")         # その親（Dataset ルート）
            self.assertEqual(Path(H._auto_discover_assets_root()).resolve(), b.resolve())
            os.environ["FORTUNE_ASSETS_DIR"] = str(tmp / "nowhere")   # 無効なら次の経路へ
            self.assertEqual(Path(H._auto_discover_assets_root()).resolve(), a.resolve())
            os.environ.pop("FORTUNE_ASSETS_DIR", None)
            # 公開 API: base 優先 → 自動探索
            self.assertEqual(Path(H.discover_assets_root(tmp / "b")).resolve(), b.resolve())
            self.assertEqual(Path(H.discover_assets_root(tmp / "nowhere")).resolve(), a.resolve())
        with _only_candidates(H, []):
            self.assertIsNone(H.discover_assets_root(tmp / "nowhere"))

    def test_deck_alias(self):
        """結果ファイル名と素材ディレクトリ名の対応（監査で確定した事実）"""
        from fortunelib.html_report import IMAGE_DECK_ALIASES, _deck_dir_for
        tmp = Path(tempfile.mkdtemp())
        (tmp / "M33_genekeys").mkdir()
        self.assertEqual(_deck_dir_for("M11_genekeys", tmp).name, "M33_genekeys")
        self.assertEqual(IMAGE_DECK_ALIASES["M11_genekeys"], "M33_genekeys")
        self.assertEqual(IMAGE_DECK_ALIASES["M27_urbantarot"], "M27_tarot")
        self.assertEqual(IMAGE_DECK_ALIASES["M22_liuyao"], "M26_iching")
        self.assertEqual(IMAGE_DECK_ALIASES["M12_stone"], "M30_crystal")
        self.assertIsNone(_deck_dir_for("M27_angel", tmp))       # 無ければ None


class TestFontGuard(unittest.TestCase):
    """同梱フォントの存在と被覆（P-4）"""

    @classmethod
    def setUpClass(cls):
        try:
            import PIL  # noqa: F401
        except ImportError:                                  # pragma: no cover
            raise unittest.SkipTest("PIL が無い環境のためスキップ")

    def test_no_problems_in_this_repo(self):
        from fortunelib import chartdraw
        self.assertEqual(chartdraw.bundled_font_problems(), [])
        self.assertEqual(chartdraw.check_bundled_fonts(verbose=False), [])
        self.assertEqual(sorted(chartdraw.BUNDLED_FONT_FILES),
                         ["cjk", "devanagari", "jp_fallback", "symbols"])

    def test_missing_font_detected(self):
        from fortunelib import chartdraw
        missing = chartdraw._font_missing(Path("/nonexistent/font.ttf"), "あいう")
        self.assertEqual(missing, ["あ", "い", "う"])

    def test_font_names_are_flagged(self):
        """納品先の名前（拡張子違い等）でも「存在しない」と判定できること"""
        from fortunelib import chartdraw
        self.assertEqual(len(chartdraw.BUNDLED_FONT_FILES), 4)
        for p in chartdraw.BUNDLED_FONT_FILES.values():
            self.assertTrue(str(p).endswith(".ttf"))

    def test_unresolved_chars_are_reported(self):
        """P-4 の無言経路: 一次にもfallbackにも無い文字は必ず報告する"""
        from fortunelib import chartdraw, font_fallback
        primary = chartdraw.F(14)
        # 「栞」は一次フォントに無い（fallback には有る）
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            selected = font_fallback.choose_font("栞", primary, None)
        self.assertIs(selected, primary)
        self.assertTrue(any("両方に無い文字" in str(w.message) for w in caught))
        codes = [str(w.message) for w in caught]
        self.assertTrue(any("U+681E" in c for c in codes))


class TestSkipStatsLedger(unittest.TestCase):
    """再利用の内訳（SKIP_STATS）の持ち越し（mts5.55）

    背景: mts5.54 の Kaggle 実機で、**本番では1件も再利用していない**のに Cell 1 の末尾に
    「↺ 再利用 0件（入力指紋が一致 3 / 旧版で照合不能 1）」
    「⚠ 入力指紋の無い旧版の成果物を 1件 再利用しました」が出ました。原因は集計が
    プロセス共通で、**セルフテスト（Cell 0.1）で起きた再利用の数値が持ち越された**ことです
    （`RUN_STRICT=1` のときは本番セルが誤って不合格になります）。
    """

    _ROW = {
        "person_id": "guard_skip", "birth_date": "1990-01-15", "birth_time": "14:30",
        "birth_place": "千葉県", "gender": "M", "blood_type": "A",
        "name_kanji": "山田 太郎", "name_kana": "やまだ たろう",
        "partner_date": "", "partner_time": "", "partner_place": "",
        "consultation": CONSULTATION, "target": "", "_index": 1,
    }

    def setUp(self):
        runcheck.clear()
        self.addCleanup(runcheck.clear)
        self.addCleanup(pipeline.reset_skip_stats)

    def _run_person(self, items):
        """Stage A の結果だけを差し替えて1人分を走らせ、標準出力を取り出す（API は呼ばない）"""
        tmp = Path(tempfile.mkdtemp())
        out = io.StringIO()
        with mock.patch.object(mts, "run_slugs_mts", lambda *a, **k: list(items)):
            with redirect_stdout(out):
                res = mts.run_person_mts(dict(self._ROW), {}, tmp, verbose=True,
                                         stages="A", monitor=False)
        return res, out.getvalue()

    def test_reset_and_total_helpers(self):
        pipeline.SKIP_STATS.update(fingerprint_match=3, no_fingerprint=1,
                                   stale_regenerated=1)
        self.assertEqual(pipeline.skip_stats_total(), 5)
        pipeline.reset_skip_stats()
        self.assertEqual(dict(pipeline.SKIP_STATS),
                         {"fingerprint_match": 0, "no_fingerprint": 0,
                          "stale_regenerated": 0})
        self.assertEqual(pipeline.skip_stats_total(), 0)
        self.assertEqual(pipeline.skip_stats_total({}), 0)     # 欠けたキーでも数えられる

    def test_run_person_mts_resets_the_ledger(self):
        """人ごとの冒頭で戻す（＝前の人・セルフテストの数値を持ち越さない）"""
        pipeline.SKIP_STATS.update(fingerprint_match=3, no_fingerprint=1,
                                   stale_regenerated=1)
        with mock.patch.object(pipeline, "reset_skip_stats",
                               wraps=pipeline.reset_skip_stats) as spy:
            _res, out = self._run_person([])
        self.assertTrue(spy.called, "run_person_mts がリセットを呼んでいません")
        self.assertEqual(pipeline.skip_stats_total(), 0)
        self.assertNotIn("↺ 再利用", out)         # 何も再利用していないので行を出さない

    def test_reuse_line_is_shown_when_something_was_reused(self):
        """陽性対照: 実際に再利用があれば行は出る（黙って隠さない）"""
        res, out = self._run_person([{"status": "skipped", "slug": "eto"}])
        self.assertEqual(res.skipped, 1)
        self.assertIn("↺ 再利用 1件", out)

    def test_entry_points_reset_the_ledger(self):
        """本番セル（Cell 1・N2）とローカル生成ツールの冒頭でも戻す（回帰の見張り）"""
        for rel in ("kaggle/cell1_csv_input.py", "kaggle/cellN2_synthesis.py"):
            src = (PKG / rel).read_text(encoding="utf-8")
            self.assertIn("reset_skip_stats", src, rel)
        demo = (REPO / "tools" / "demo_local_html.py").read_text(encoding="utf-8")
        self.assertIn("reset_skip_stats", demo)

    def test_cell1_does_not_claim_index_md(self):
        """案内文と実態の一致: index.md を作らないのに「index.md に一覧」と言わない"""
        src = (PKG / "kaggle" / "cell1_csv_input.py").read_text(encoding="utf-8")
        self.assertNotIn("index.md に一覧", src)             # 作らない物を「あります」と言わない
        self.assertIn("index.md はありません", src)


class TestToolsSafety(unittest.TestCase):
    """生成ツールの安全弁（P-5/P-6）"""

    def _load(self, rel: str, name: str):
        spec = importlib.util.spec_from_file_location(name, REPO / rel)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_demo_pid_regex(self):
        m = self._load("tools/demo_local_html.py", "demo_local_html_for_test")
        for ok in ("demo_local", "person-01", "A.b_c-9", "x" * 64):
            self.assertTrue(m._PID_RE.match(ok), ok)
        for bad in ("../victim", "/tmp/x", "", ".hidden", "-x", "a/b", "..",
                    "x" * 65, "あいう"):
            self.assertFalse(m._PID_RE.match(bad), bad)


if __name__ == "__main__":
    unittest.main()
