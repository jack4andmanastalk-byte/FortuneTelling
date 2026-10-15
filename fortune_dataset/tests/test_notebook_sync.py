# -*- coding: utf-8 -*-
"""Kaggle ノートブックが「セルの正本（cell*.py）」と一致していることの検査。

背景: セルの .py を直したのに `kaggle/build_notebook.py` の実行を忘れると、配布した
`fortune_notebook.ipynb` は古い内容のまま Kaggle に上がり、新しいコードが一度も走らない。
→ ノートブックは**手で編集しない**（cell*.py が正本）。ここで一致を固定し、
Cell 0 の版チェック（notebook_guard）が「古いセル」を名指しできることも固定する。
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from fortunelib import notebook_guard as G

PKG = Path(__file__).resolve().parents[1]
KG = PKG / "kaggle"
NB = KG / "fortune_notebook.ipynb"
BUILDER = KG / "build_notebook.py"


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_notebook", BUILDER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # __name__ != "__main__" なので生成は走らない
    return mod


def _code_cells() -> list[str]:
    nb = json.loads(NB.read_text(encoding="utf-8"))
    return ["".join(c["source"]) if isinstance(c["source"], list) else c["source"]
            for c in nb["cells"] if c["cell_type"] == "code"]


class TestNotebookSync(unittest.TestCase):
    def test_notebook_matches_the_cell_sources(self):
        """ノートブックのコードセルは cell*.py と**1字も違わない**（二重管理しない）。"""
        self.assertTrue(NB.exists(), "fortune_notebook.ipynb がありません")
        ok, problems = _load_builder().check()
        self.assertTrue(ok, "ノートブックが cell*.py と食い違っています（build_notebook.py を実行）: "
                            + " / ".join(problems))

    def test_notebook_has_the_intro_video_flag(self):
        """Cell N2 が冒頭動画カードのフラグと組み込みコードを持つ（既定 ON）。"""
        n2 = [c for c in _code_cells() if "load_intro_video_card" in c]
        self.assertEqual(len(n2), 1, "Cell N2 に load_intro_video_card の呼び出しがありません")
        self.assertIn("EMBED_INTRO_VIDEO = True", n2[0])
        self.assertIn("if EMBED_INTRO_VIDEO:", n2[0])
        self.assertIn("intro_video_html=_intro_html", n2[0])
        self.assertIn("build_html(_dir", n2[0])

    def test_intro_video_off_skips_loader_but_keeps_html_path(self):
        """フラグOFFは読み込みを分岐ごと飛ばし、HTML生成経路は残す。"""
        import ast
        n2 = next(c for c in _code_cells() if "load_intro_video_card" in c)
        tree = ast.parse(n2)
        switches = [node for node in ast.walk(tree)
                    if isinstance(node, ast.If)
                    and isinstance(node.test, ast.Name)
                    and node.test.id == "EMBED_INTRO_VIDEO"]
        self.assertEqual(len(switches), 1)
        switch = switches[0]

        def _calls_loader(stmts):
            return any(isinstance(node, ast.Call)
                       and ((isinstance(node.func, ast.Name) and node.func.id == "_load_iv")
                            or (isinstance(node.func, ast.Attribute)
                                and node.func.attr == "load_intro_video_card"))
                       for stmt in stmts for node in ast.walk(stmt))
        self.assertTrue(_calls_loader(switch.body))
        self.assertFalse(_calls_loader(switch.orelse))
        self.assertIn("冒頭動画カードはOFF", n2)

    def test_people_sample_uses_fictional_person_with_partner_data(self):
        """Kaggle既定CSVは架空IDで、相性検証用の相手情報も揃っている。

        相談内容は約1,600字の架空の相談文（人生相談風）。過去の人物IDは
        「別の人物に更新されていること」の履歴として残す。
        """
        import csv
        from tests.fixtures.consultation import (
            CONSULTATION, TARGET_CHARS, TOLERANCE, csv_consultation,
            is_fictional_consultation)
        sample = KG / "people_sample.csv"
        with sample.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["person_id"], "demo_hoshino_nagi")
        self.assertEqual(row["name_kanji"], "星野 凪")
        for old in ("demo_asakura_riko", "demo_kirishima_souta", "demo_morimoto_haruka",
                    "demo_miyashita_chihiro", "demo_shiraishi_nanami",
                    "demo_amano_yuma"):
            self.assertNotEqual(row["person_id"], old)
        c = row["consultation"]
        self.assertIn("架空", c)
        self.assertIn("シナストリー", c)
        self.assertTrue(is_fictional_consultation(c), len(c))
        self.assertLessEqual(abs(len(c) - TARGET_CHARS), TOLERANCE)   # 1,600字前後
        self.assertEqual(c, csv_consultation())        # フィクスチャと一致
        self.assertEqual(c, CONSULTATION)
        for key in ("partner_date", "partner_time", "partner_place"):
            self.assertTrue(row[key], key)

    def test_new_sample_normalizes_partner_for_synastry(self):
        """新しい架空CSVの本人・相手情報が正規化され、シナストリー計算へ入る。"""
        import csv
        from fortunelib.batch import build_calc_results, build_profile_facts
        from fortunelib.batch_runner import row_to_input
        from fortunelib.profile import normalize_input
        with (KG / "people_sample.csv").open(encoding="utf-8", newline="") as f:
            row = next(csv.DictReader(f))
        ni = normalize_input(row_to_input(row))
        self.assertEqual(ni.name_romaji, "HOSHINO NAGI")
        self.assertEqual(len(ni.consultation), len(row["consultation"]))
        self.assertEqual(ni.partner.date.isoformat(), row["partner_date"])
        self.assertEqual(ni.partner.time, row["partner_time"])
        self.assertEqual(ni.partner.place_name, row["partner_place"])
        facts = build_profile_facts(ni)
        self.assertEqual(facts["氏名（漢字）"], row["name_kanji"])
        synastry = build_calc_results(ni, consultation=ni.consultation)["synastry"]
        self.assertIn("mine", synastry)
        self.assertIn("theirs", synastry)

    def test_cell_count_matches_dataset_version(self):
        """期待セル数は dataset_version.json が正（Kaggle 実機の検査と一致させる）。"""
        nb = json.loads(NB.read_text(encoding="utf-8"))
        ver = json.loads((PKG / "data" / "dataset_version.json").read_text(encoding="utf-8"))
        self.assertEqual(len(nb["cells"]), ver["expected"]["notebook_cells"])

    def test_cell0_warns_when_the_notebook_is_stale(self):
        """実行中の Notebook が古ければ Cell 0 が警告する。

        「N2 の組み込みコードが無い古い Notebook を実行した」事故を再現して、
        **そのセル名を名指しで**検出できることを固定する。
        """
        nb = json.loads(NB.read_text(encoding="utf-8"))
        for c in nb["cells"]:
            if c["cell_type"] != "code":
                continue
            src = "".join(c["source"])
            if "load_intro_video_card" in src:
                c["source"] = src.replace("_load_iv(", "NOT_CALLED(").splitlines(keepends=True)
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / "__notebook__.ipynb"
            fake.write_text(json.dumps(nb, ensure_ascii=False), encoding="utf-8")
            logs: list[str] = []
            stale = G.check_notebook_freshness(PKG, notebook=fake, log=logs.append)
        self.assertIn("cellN2_synthesis.py", stale)
        self.assertTrue(any("古い" in l for l in logs))

    def test_flag_boolean_override_is_allowed_but_other_n2_changes_are_detected(self):
        """設定行の True/False だけを許容し、同じセルの他の古い差分は検出する。"""
        nb = json.loads(NB.read_text(encoding="utf-8"))
        for c in nb["cells"]:
            if c["cell_type"] != "code":
                continue
            src = "".join(c["source"])
            if "EMBED_INTRO_VIDEO" in src:
                flipped = src.replace("EMBED_INTRO_VIDEO = True",
                                      "EMBED_INTRO_VIDEO = False", 1)
                self.assertNotEqual(flipped, src, "フラグの正本行が見つかりません")
                c["source"] = flipped.splitlines(keepends=True)
                break
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / "__notebook__.ipynb"
            fake.write_text(json.dumps(nb, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(G.stale_cells(PKG, fake), [])

            # フラグ反転に加えて無関係な処理行も変えたら、Cell N2を古いと判定する。
            c = next(c for c in nb["cells"] if c["cell_type"] == "code"
                     and "EMBED_INTRO_VIDEO" in "".join(c["source"]))
            src = "".join(c["source"])
            c["source"] = src.replace("MAKE_HTML = True", "MAKE_HTML = False", 1).splitlines(keepends=True)
            fake.write_text(json.dumps(nb, ensure_ascii=False), encoding="utf-8")
            self.assertIn("cellN2_synthesis.py", G.stale_cells(PKG, fake))

    def test_flag_setting_accepts_only_boolean_literals(self):
        """True/False以外への変更は許容差分に含めない。"""
        source = (KG / "cellN2_synthesis.py").read_text(encoding="utf-8")
        altered = source.replace("EMBED_INTRO_VIDEO = True",
                                 "EMBED_INTRO_VIDEO = 1", 1)
        self.assertNotEqual(
            G._normalized_cell_source("cellN2_synthesis.py", source),
            G._normalized_cell_source("cellN2_synthesis.py", altered),
        )

    def test_guard_is_silent_for_a_fresh_notebook_and_without_one(self):
        """一致していれば ✅、Notebook が見つからなければ**何も言わない**（誤警告しない）。"""
        logs: list[str] = []
        self.assertEqual(G.check_notebook_freshness(PKG, notebook=NB, log=logs.append), [])
        self.assertTrue(any("一致" in l for l in logs))
        empty: list[str] = []
        with tempfile.TemporaryDirectory() as td:
            got = G.check_notebook_freshness(PKG, notebook=Path(td) / "none.ipynb",
                                             cwd=Path(td), log=empty.append)
        self.assertEqual(got, [])
        self.assertEqual(empty, [])

    def test_cell0_actually_calls_the_guard_and_never_raises(self):
        """Cell 0 が検査を呼び、失敗しても本処理を止めない（try/except で包む）。"""
        c0 = _code_cells()[0]
        self.assertIn("check_notebook_freshness", c0)
        self.assertIn("except Exception", c0)

    def test_notebook_sha_matches_dataset_version(self):
        """配布物の同一性: dataset_version.json に記録した sha256 と実ファイルが一致する。"""
        import hashlib
        ver = json.loads((PKG / "data" / "dataset_version.json").read_text(encoding="utf-8"))
        sha = hashlib.sha256(NB.read_bytes()).hexdigest()
        self.assertEqual(ver.get("notebook_sha256"), sha,
                         "Notebook を作り直したら dataset_version.json の notebook_sha256 も更新すること")

    def test_builder_has_a_check_mode(self):
        """`--check` を持ち、一致/不一致を終了コードで返せること（CI・手順書から使う）。"""
        src = BUILDER.read_text(encoding="utf-8")
        self.assertIn('"--check"', src)
        self.assertIn("def check(", src)


if __name__ == "__main__":
    unittest.main()
