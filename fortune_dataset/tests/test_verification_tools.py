# -*- coding: utf-8 -*-
"""検証ツール側の mts5.52 修正の回帰テスト（F-6 / F-7 / F-8 / F-10）

背景（Turn 5 の監査）:
  * `tools/check_scripts.py` は正本（simplified_only.txt 等）が無いと**黙って**
    簡体字検出を無効化し、簡体字だけの文書に「[OK] 混入なし」exit 0 を返していた（F-6）。
  * `verify/asset_matching_audit.py` は常に exit 0 で、デッキ欠落も無言だった（F-7）。
  * `tools/build_dataset_zip.py` はビルド後のZIPを検証せず、CRC・重複・画像枚数・
    同梱物の突合は毎回**手作業**だった（F-8）。
  * `tools/make_typec_font.py` は構文エラーで**実行不能**のまま配布ZIPに入っていた（F-10。
    手順書の compileall 対象が fortunelib/kaggle/tests だけで tools/ を見ていなかった）。

本ファイルはこの4点の再発を防ぐ。リポジトリ直下（tools/ と verify/ がある場所）が
見つからない環境では該当テストをスキップする。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]            # …/fortune_dataset（パッケージ）


def _repo_root() -> Path | None:
    """tools/ と verify/ を持つリポジトリ直下を探す（Kaggle でも同じ構成）。"""
    for cand in [PKG.parent, *PKG.parents]:
        if ((cand / "tools" / "check_scripts.py").is_file()
                and (cand / "verify" / "asset_matching_audit.py").is_file()
                and (cand / "fortune_dataset" / "data").is_dir()):
            return cand
    return None


ROOT = _repo_root()
SIMPLE_ONLY_DOC = "これは測試文書です。書、车、见、长。\n"      # 簡体字専用字形のみ


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], capture_output=True, text=True, timeout=600)


@unittest.skipUnless(ROOT, "リポジトリ直下（tools/・verify/）が見つかりません")
class TestAllPythonFilesCompileMts552(unittest.TestCase):
    """tools/ と verify/ を含めた全 .py が構文エラー無しで読めること（F-10 の再発防止）"""

    def test_every_python_file_compiles(self):
        targets = [ROOT / "tools", ROOT / "verify", ROOT / "fortune_dataset"]
        checked = 0
        for base in targets:
            for p in sorted(base.rglob("*.py")):
                if "__pycache__" in p.parts:
                    continue
                with self.subTest(file=str(p.relative_to(ROOT))):
                    try:
                        compile(p.read_text(encoding="utf-8"), str(p), "exec")
                    except SyntaxError as e:                       # noqa: PERF203
                        self.fail(f"{p.relative_to(ROOT)} が読めません: {e}")
                checked += 1
        self.assertGreater(checked, 30)


@unittest.skipUnless(ROOT, "リポジトリ直下（tools/・verify/）が見つかりません")
class TestCheckScriptsFailClosedMts552(unittest.TestCase):
    """`tools/check_scripts.py`（F-6）: 正本が無ければ検査不能として停止する"""

    def test_detects_simplified_chinese_with_reference_files(self):
        with tempfile.TemporaryDirectory() as td:
            doc = Path(td) / "simple.md"
            doc.write_text(SIMPLE_ONLY_DOC, encoding="utf-8")
            proc = _run(str(ROOT / "tools" / "check_scripts.py"), str(doc))
        self.assertEqual(proc.returncode, 1, proc.stdout[-400:])
        self.assertIn("ERROR", proc.stdout)

    def test_stops_with_exit_2_when_reference_files_are_missing(self):
        """正本が無い複製では「[OK] 混入なし」ではなく exit 2 で停止する（従来は exit 0）"""
        with tempfile.TemporaryDirectory() as td:
            tools = Path(td) / "tools"
            tools.mkdir()
            (tools / "check_scripts.py").write_text(
                (ROOT / "tools" / "check_scripts.py").read_text(encoding="utf-8"),
                encoding="utf-8")
            doc = Path(td) / "simple.md"
            doc.write_text(SIMPLE_ONLY_DOC, encoding="utf-8")
            proc = _run(str(tools / "check_scripts.py"), str(doc))
        self.assertEqual(proc.returncode, 2, proc.stdout[-400:])
        self.assertIn("正本が読めない", proc.stdout)
        self.assertNotIn("[OK]", proc.stdout)


@unittest.skipUnless(ROOT, "リポジトリ直下（tools/・verify/）が見つかりません")
class TestAssetAuditStrictMts552(unittest.TestCase):
    """`verify/asset_matching_audit.py`（F-7）: `--strict` と欠落の明示"""

    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        base = Path(cls.td.name)
        # リポジトリの tools/ に置いた複製（out_audit の書き出し先を temp 内に向ける）
        (base / "tools").mkdir()
        (base / "tools" / "asset_matching_audit.py").write_text(
            (ROOT / "verify" / "asset_matching_audit.py").read_text(encoding="utf-8"),
            encoding="utf-8")
        pkg = base / "pkgcopy"
        pkg.mkdir()
        (pkg / "assets" / "images").mkdir(parents=True)
        (pkg / "data").symlink_to(ROOT / "fortune_dataset" / "data")
        (pkg / "fortunelib").symlink_to(ROOT / "fortune_dataset" / "fortunelib")
        cls.base = base
        cls.pkg = pkg
        cls.script = base / "tools" / "asset_matching_audit.py"

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def _audit(self, *extra: str):
        return _run(str(self.script), "--pkg", str(self.pkg),
                    "--assets", str(self.pkg / "assets" / "images"), *extra)

    def test_empty_assets_is_reported(self):
        """assets が空でも「検査したデッキ 0 / 未検査 26」と明示する（従来は無言）"""
        proc = self._audit()
        self.assertIn("未検査", proc.stdout)
        self.assertIn("[欠落]", proc.stdout)
        self.assertIn("検査したデッキ 0（対象 26）", proc.stdout)

    def test_default_exit_is_zero_but_strict_is_one(self):
        self.assertEqual(self._audit().returncode, 0)
        self.assertEqual(self._audit("--strict").returncode, 1)

    def test_filename_based_note_is_printed(self):
        proc = self._audit()
        self.assertIn("ファイル名ベース", proc.stdout)


@unittest.skipUnless(ROOT, "リポジトリ直下（tools/・verify/）が見つかりません")
class TestBuildZipVerifyMts552(unittest.TestCase):
    """`tools/build_dataset_zip.py --verify`（F-8）: 作り終えたZIPの読み取り専用検査"""

    FONTS = {"typec_jp_subset.ttf": 12_000,
             "typec_devanagari_subset.ttf": 3_000,
             "typec_symbols_subset.ttf": 3_000,
             "jp_cjk_fallback.ttf": 1_100_000}

    @classmethod
    def _make_zip(cls, path: Path, *, drop_font: str | None = None,
                  duplicate: bool = False, secret: str | None = None) -> Path:
        import zipfile
        import json as _json
        prefix = "fortune_dataset/"
        entries = {
            "fortune_dataset/data/dataset_version.json":
                _json.dumps({"build_id": "2026-09-29-mts5.52",
                             "expected": {"tests": 1}}, ensure_ascii=False),
            "fortune_dataset/fortunelib/chartdraw.py": "# stub\n",
            "fortune_dataset/kaggle/fortune_notebook.ipynb": "{}",
            "fortune_dataset/kaggle/cell0_selftest.py": "# stub\n",
            "fortune_dataset/kaggle/people_sample.csv": "name\n",
            "tools/build_chart_fonts.py": "# stub\n",
            "verify/verify_run_output.py": "# stub\n",
            "verify/asset_checksums.sha256": "# manifest\n",
            "fortune_dataset/assets/fonts/README.md": "fonts\n",
            # v1.0.0: ライセンス・第三者表示も必須同梱物
            "LICENSE": "GNU AFFERO GENERAL PUBLIC LICENSE\n",
            "LICENSE-ASSETS": "CC BY 4.0\n",
            "THIRD_PARTY_NOTICES.md": "# notices\n",
            "fortune_dataset/assets/fonts/OFL.txt": "SIL OPEN FONT LICENSE Version 1.1\n",
            "fortune_dataset/data/kanji_kakusu_license.json": "{}\n",
        }
        for name, size in cls.FONTS.items():
            if name == drop_font:
                continue
            entries[f"fortune_dataset/assets/fonts/{name}"] = "\0" * size
        if secret:
            entries["fortune_dataset/kaggle/notes.txt"] = secret
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in entries.items():
                z.writestr(prefix + name, data)
            if duplicate:
                first = prefix + "fortune_dataset/data/dataset_version.json"
                z.writestr(first, entries["fortune_dataset/data/dataset_version.json"])
        return path

    @staticmethod
    def _verify(zpath: Path):
        return _run(str(ROOT / "tools" / "build_dataset_zip.py"), "--verify", str(zpath))

    def test_good_zip_passes(self):
        with tempfile.TemporaryDirectory() as td:
            zp = self._make_zip(Path(td) / "good.zip")
            proc = self._verify(zp)
        self.assertEqual(proc.returncode, 0, proc.stdout[-600:])
        self.assertIn("✅ 合格", proc.stdout)

    def test_missing_font_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            zp = self._make_zip(Path(td) / "nofont.zip", drop_font="jp_cjk_fallback.ttf")
            proc = self._verify(zp)
        self.assertEqual(proc.returncode, 1, proc.stdout[-400:])
        self.assertIn("jp_cjk_fallback.ttf", proc.stdout)

    def test_duplicate_entry_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            zp = self._make_zip(Path(td) / "dup.zip", duplicate=True)
            proc = self._verify(zp)
        self.assertEqual(proc.returncode, 1, proc.stdout[-400:])
        self.assertIn("重複エントリ", proc.stdout)

    def test_secret_is_detected(self):
        # 鍵は文字列連結で作る（このリポジトリ自身が --verify の秘密情報スキャンに引っかからないように）
        fake = "AIza" + "Sy" + "D" * 35 + "\n"
        with tempfile.TemporaryDirectory() as td:
            zp = self._make_zip(Path(td) / "secret.zip",
                                secret="GOOGLE_API_KEY=" + fake)
            proc = self._verify(zp)
        self.assertEqual(proc.returncode, 1, proc.stdout[-400:])
        self.assertIn("秘密情報", proc.stdout)

    def test_missing_zip_is_exit_2(self):
        with tempfile.TemporaryDirectory() as td:
            proc = self._verify(Path(td) / "nothing.zip")
        self.assertEqual(proc.returncode, 2, proc.stdout[-200:])
