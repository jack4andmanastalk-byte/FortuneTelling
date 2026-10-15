# -*- coding: utf-8 -*-
"""verify/verify_run_output.py の回帰テスト（mts5.5 で追加）

背景:
  本番実行（Kaggle・mts5.2）で発見した「ルーンの誤充当」（位置1 ウンジョに 01_Fehu）は、
  実行HTMLの「キャプションの名前 ⇄ 画像ファイル名」を突き合わせれば機械的に検出できる。
  そのために作った verify_run_output.py を、
    1) M23_meihua と M26_iching の64枚がバイト同一であることによる**デッキ別枚数の誤集計**
    2) 和名だけのキャプション（キッパー・レノルマン・カルトマンシー・おみくじ・血液型）が
       すべて「判定不能」になり、**誤充当を検出できない**
  の2点で強化した（mts5.4 の実行検証で判明）。

  本ファイルはその強化部分が壊れていないことを守る。
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "verify_run_output", ROOT.parent / "verify" / "verify_run_output.py")
vro = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(vro)

ASSETS = ROOT / "assets" / "images"
TABLES = vro.build_name_tables(ROOT)


class TestDecodeEscapedStem(unittest.TestCase):
    """卦名のファイル名（U+XXXX の連なり）を漢字へ復号できること"""

    def test_hexagram_name_is_decoded(self):
        self.assertEqual(vro.decode_escaped_stem("10_U5929U6fa4U5c65"), "天澤履")
        self.assertEqual(vro.decode_escaped_stem("01_U4e7eU70baU5929"), "乾為天")

    def test_ordinary_names_are_not_decoded(self):
        self.assertEqual(vro.decode_escaped_stem("05_Tree"), "")
        self.assertEqual(vro.decode_escaped_stem("08_Wunjo"), "")


class TestCaptionTables(unittest.TestCase):
    """data/*.json 由来の対応表で、和名だけのキャプションを照合できること"""

    @classmethod
    def setUpClass(cls):
        cls.tables = vro.build_name_tables(ROOT)

    def test_tables_are_built(self):
        self.assertGreater(len(self.tables["ja2en"]), 100)   # kipper/lenormand/oracle/angel
        self.assertGreater(len(self.tables["card"]), 40)     # cartomancy
        self.assertEqual(len(self.tables["omikuji"]), 12)

    def test_kipper_japanese_name_matches_english_file(self):
        self.assertEqual(vro.check_caption_by_tables(
            "【キッパー】位置1 結婚", "03_Marriage", self.tables, ""), True)
        # 別の札を充当したら「不一致」と判定できること
        self.assertEqual(vro.check_caption_by_tables(
            "【キッパー】位置1 結婚", "20_House", self.tables, ""), False)

    def test_single_character_name_matches(self):
        """「家」「鎌」のような1文字の和名でも照合できること（部分一致で走査）"""
        self.assertEqual(vro.check_caption_by_tables(
            "【キッパー】位置5 家", "20_House", self.tables, ""), True)
        self.assertEqual(vro.check_caption_by_tables(
            "【レノルマン】過去 鎌", "10_Scythe", self.tables, ""), True)
        self.assertEqual(vro.check_caption_by_tables(
            "【レノルマン】現在 木", "05_Tree", self.tables, ""), True)

    def test_cartomancy_name_with_digit_matches(self):
        """「ダイヤの2」のように数字混じりの和名でも照合できること"""
        self.assertEqual(vro.check_caption_by_tables(
            "【カルトマンシー】位置2 ダイヤの2", "02_of_Diamonds", self.tables, ""), True)
        self.assertEqual(vro.check_caption_by_tables(
            "【カルトマンシー】位置2 ダイヤの2", "03_of_Diamonds", self.tables, ""), False)

    def test_omikuji_level_matches_number(self):
        self.assertEqual(vro.check_caption_by_tables(
            "【おみくじ】小凶　やや停滞・小さなトラブル注意", "09_shokyo_d", self.tables, ""), True)
        self.assertEqual(vro.check_caption_by_tables(
            "【おみくじ】小凶　やや停滞・小さなトラブル注意", "12_daikyo_a", self.tables, ""), False)

    def test_blood_type_letter_matches(self):
        self.assertEqual(vro.check_caption_by_tables(
            "【血液型占い】Type O　おおらか・社交的", "02_O", self.tables, ""), True)
        self.assertEqual(vro.check_caption_by_tables(
            "【血液型占い】Type O　おおらか・社交的", "01_A", self.tables, ""), False)

    def test_hexagram_caption_matches_by_decoded_name(self):
        self.assertEqual(vro.check_caption_by_tables(
            "【易】本卦：水雷屯（03）", "03_U6c34U96f7U5c6f", self.tables,
            vro.decode_escaped_stem("03_U6c34U96f7U5c6f")), True)
        self.assertEqual(vro.check_caption_by_tables(
            "【易】本卦：水雷屯（03）", "10_U5929U6fa4U5c65", self.tables,
            vro.decode_escaped_stem("10_U5929U6fa4U5c65")), False)


class TestVerifyCaption(unittest.TestCase):
    """本体ループと同じ経路（verify_caption）で誤充当を検出できること"""

    def test_rune_draw_order_regression_is_detected(self):
        """mts5.2 の実例: 位置1 ウンジョに 01_Fehu を充当 → 不一致として検出"""
        bad = vro.verify_caption("【ルーン】位置1 ウンジョ（Wunjo）",
                                 ASSETS / "M27_runes" / "01_Fehu.webp", {})
        self.assertEqual(bad[0], "bad")
        good = vro.verify_caption("【ルーン】位置1 ウンジョ（Wunjo）",
                                  ASSETS / "M27_runes" / "08_Wunjo.webp", {})
        self.assertEqual(good[0], "ok")

    def test_japanese_only_caption_is_verified_not_skipped(self):
        """和名だけのキャプションが「判定不能」で素通りしないこと"""
        verdict, _ = vro.verify_caption("【キッパー】位置1 結婚",
                                        ASSETS / "M27_kipper" / "03_Marriage.webp",
                                        vro.build_name_tables(ROOT))
        self.assertEqual(verdict, "ok")

    def test_deck_is_attributed_by_caption_marker(self):
        """M23_meihua と M26_iching は画像がバイト同一でも見出しで区別できること"""
        self.assertEqual(next(d for m, d in vro.CAPTION_DECK if m in "【梅花易数】本卦：天澤履（10）"),
                         "M23_meihua")
        self.assertEqual(next(d for m, d in vro.CAPTION_DECK if m in "【易】本卦：水雷屯（03）"),
                         "M26_iching")

    def test_missing_asset_is_unknown(self):
        verdict, _ = vro.verify_caption("【ルーン】位置1 ウンジョ（Wunjo）", None, {})
        self.assertEqual(verdict, "unknown")


class TestPkgDataLoader(unittest.TestCase):
    """mts5.6: パッケージの照合表を **ZIP からも** 作れること

    引き継ぎZIPは画像を含まないため、ZIP単体でも `data/*.json` を読めないと
    和名キャプションが「判定不能」に落ちて誤充当を検出できない（実際に mts5.6 の
    検証中、--pkg にZIPを渡したところ 判定不能20 に落ちる事象を確認した）。
    """

    def test_zip_package_tables(self):
        import shutil
        import tempfile
        import zipfile

        with tempfile.TemporaryDirectory() as td:
            zp = Path(td) / "pkg.zip"
            # 実パッケージと同じ二重階層（fortune_dataset/fortune_dataset/data/…）で作る
            with zipfile.ZipFile(zp, "w") as z:
                for name in ("kipper_36.json", "omikuji_12.json"):
                    src = ROOT / "data" / name
                    if src.is_file():
                        z.write(src, arcname=f"fortune_dataset/fortune_dataset/data/{name}")
            tables = vro.build_name_tables(zp)
            self.assertTrue(tables["ja2en"], "ZIP から和名→英名の表を作れていない")
            self.assertTrue(tables["omikuji"], "ZIP からおみくじの表を作れていない")
            # 実在するパッケージ（引き継ぎZIP）でも同様に読めること
            real = sorted((ROOT.parent.parent).glob("fortune_dataset*.zip"))
            if real:
                rt = vro.build_name_tables(real[0])
                self.assertTrue(rt["ja2en"], f"{real[0].name} から照合表を作れていない")

    def test_broken_pkg_path_yields_empty_tables(self):
        """存在しないパスや画像ディレクトリを渡しても例外にせず、データ由来の表は空になる

        mts5.8: 型D/型B の小デッキ（ペンデュラム等）は**実装側と対になる固定表**（FIXED_JA2EN）を
        常に持つ。パッケージが読めないときの「データ由来の表が空」を確認する。
        """
        tables = vro.build_name_tables(Path("/no/such/pkg"))
        self.assertEqual(tables["card"], {})
        self.assertEqual(tables["omikuji"], {})
        # 固定表（実装と同期しているもの）だけが残る
        self.assertEqual(tables["ja2en"], dict(vro.FIXED_JA2EN))
        self.assertTrue(vro.FIXED_JA2EN, "ペンデュラムの固定表が空")
        self.assertEqual(vro.pkg_data_loader(None), None)


class TestOmittedDecks(unittest.TestCase):
    """mts5.7: 画像をオミットしたデッキ（血液型）の画像は「問題」ではなく参考として扱う

    旧い実行結果（mts5.6 以前）の HTML には血液型の画像が入っているため、オミット後の納品画像で検証すると
    「納品画像と一致しない」になる。これは想定内なので、誤警報を出さないようにした。
    """

    def test_omitted_markers_are_defined(self):
        self.assertIn("血液型", vro.OMITTED_DECKS)
        self.assertIn("M08_blood", vro.OMITTED_DECKS["血液型"])

    def test_blood_caption_is_classified_as_omitted(self):
        """オミット済みデッキのキャプションが検出できること（納品画像が無くても問題にしない）"""
        cap = "【血液型占い】Type O　おおらか・社交的"
        self.assertTrue(any(m in cap for m in vro.OMITTED_DECKS))

    def test_delivered_decks_are_not_in_omitted(self):
        """納品しているデッキはオミット扱いになっていないこと（誤って素通りさせない）"""
        for mark in ("干支", "星座占い", "ルーン", "おみくじ", "キッパー",
                     "ペンデュラム", "水晶玉"):
            self.assertNotIn(mark, vro.OMITTED_DECKS)
        self.assertIn(("干支", "M01_eto"), vro.CAPTION_DECK)

    def test_pendulum_caption_is_matched_to_file(self):
        """ペンデュラムはキャプションの和名（肯定/否定/中立）から画像を検証できる（mts5.8）

        英名が Yes / No（4文字未満）のため英名トークン経路では拾えない。固定表（FIXED_JA2EN）で
        「キャプションの和名 → ファイル名の英名」を照合し、**誤充当を bad として検出する**。
        """
        tables = vro.build_name_tables(None)
        cases = [("【ペンデュラム】肯定（Yes）", "01_Yes", "ok"),
                 ("【ペンデュラム】否定（No）", "02_No", "ok"),
                 ("【ペンデュラム】中立・保留（Neutral）", "03_Neutral", "ok"),
                 ("【ペンデュラム】否定（No）", "01_Yes", "bad"),
                 ("【ペンデュラム】肯定（Yes）", "03_Neutral", "bad")]
        for cap, stem, want in cases:
            with self.subTest(cap=cap, stem=stem):
                verdict, _ = vro.verify_caption(
                    cap, Path("/tmp") / f"{stem}.webp", tables)
                self.assertEqual(verdict, want)

    def test_crystal_caption_is_matched_to_file(self):
        """クリスタルはキャプションの英名（Amethyst 等）で画像を検証できる（mts5.9）"""
        tables = vro.build_name_tables(None)
        cases = [("【クリスタル・ヒーリング】アメジスト（Amethyst）", "01_Amethyst", "ok"),
                 ("【クリスタル・ヒーリング】水晶（Clear Quartz）", "02_ClearQuartz", "ok"),
                 ("【クリスタル・ヒーリング】ラピスラズリ（Lapis Lazuli）", "06_LapisLazuli", "ok"),
                 ("【クリスタル・ヒーリング】アメジスト（Amethyst）", "06_LapisLazuli", "bad"),
                 ("【クリスタル・ヒーリング】ガーネット（Garnet）", "11_Moonstone", "bad")]
        for cap, stem, want in cases:
            with self.subTest(cap=cap, stem=stem):
                verdict, _ = vro.verify_caption(cap, Path("/tmp") / f"{stem}.webp", tables)
                self.assertEqual(verdict, want)

    def test_pkg_double_nested_dir_builds_tables(self):
        """`<pkg>/fortune_dataset/data` の二重階層でも照合表を作れる（mts5.10）

        引き継ぎではリポジトリ直下を --pkg に渡しがちで、その場合に照合表が空になり
        「和名だけのキャプション」が判定不能に落ちていた。
        """
        root = Path(vro.__file__).resolve().parent.parent      # パッケージ直下
        tables = vro.build_name_tables(root)
        self.assertGreater(len(tables["ja2en"]), 100)          # キッパー等の和名→英名が入る
        self.assertEqual(len(tables["omikuji"]), 12)
        self.assertGreater(len(tables["card"]), 40)

    def test_african_open_count_is_verified(self):
        """アフリカは「開き N 枚（OpenN）」の数字まで検証する（mts5.10）

        英字だけの LATIN_TOKEN では `Open3` の数字が落ちて誤りを見逃すため、
        英字＋数字のトークンを別に照合する。
        """
        tables = vro.build_name_tables(None)
        cases = [("【伝統的アフリカ占い】開き 4 枚（Open4）", "05_Open4", "ok"),
                 ("【伝統的アフリカ占い】開き 0 枚（Open0）", "01_Open0", "ok"),
                 ("【伝統的アフリカ占い】開き 8 枚（Open8）", "09_Open8", "ok"),
                 ("【伝統的アフリカ占い】開き 4 枚（Open4）", "05_Open5", "bad"),
                 ("【伝統的アフリカ占い】開き 4 枚（Open4）", "04_Open4", "bad")]
        for cap, stem, want in cases:
            with self.subTest(cap=cap, stem=stem):
                verdict, _ = vro.verify_caption(cap, Path("/tmp") / f"{stem}.webp", tables)
                self.assertEqual(verdict, want)

    def test_type_d_decks_are_registered(self):
        """mts5.8/mts5.9 で追加した型D（ペンデュラム・水晶玉・クリスタル）が帰属先に登録されていること"""
        self.assertIn(("ペンデュラム", "M29_pendulum"), vro.CAPTION_DECK)
        self.assertIn(("水晶玉", "M30_crystalball"), vro.CAPTION_DECK)
        self.assertIn(("クリスタル", "M30_crystal"), vro.CAPTION_DECK)
        self.assertIn(("アフリカ占い", "M29_african"), vro.CAPTION_DECK)
        self.assertIn(("タリスマン", "M30_talisman"), vro.CAPTION_DECK)
        self.assertEqual(
            next(d for m, d in vro.CAPTION_DECK if m in "【ペンデュラム】肯定（Yes）"),
            "M29_pendulum")
        self.assertEqual(
            next(d for m, d in vro.CAPTION_DECK if m in "【水晶玉占い】水晶玉（Scrying）"),
            "M30_crystalball")


if __name__ == "__main__":
    unittest.main()

    unittest.main()

    unittest.main()

class TestCardNameWithPosition(unittest.TestCase):
    """mts5.12: 「（正位置）（逆位置）」つきのカード名を画像と照合する。

    実例（mts5.11 の実行検証）: 「【タロット】自分自身 The Sun（逆位置）」に 19_Sun.jpg が
    埋め込まれていたが、英名が3文字（Sun）のため英名トークン経路（4文字以上）で拾えず、
    「判定不能」として素通りしていた（バイト一致では同一と確認できていたが、
    名前での検証ができていなかった）。
    """

    def _cap(self, cap: str, rel: str):
        return vro.verify_caption(cap, ASSETS / rel, TABLES)

    def test_reversed_card_matches_by_last_word(self):
        v, d = self._cap("【タロット】自分自身 The Sun（逆位置）", "M27_tarot/19_Sun.jpg")
        self.assertEqual(v, "ok", d)

    def test_upright_card_matches(self):
        v, d = self._cap("【タロット】相手 The Star（正位置）", "M27_tarot/17_Star.jpg")
        self.assertEqual(v, "ok", d)

    def test_wrong_card_is_detected(self):
        v, d = self._cap("【タロット】自分自身 The Sun（逆位置）", "M27_tarot/04_Cancer.webp")
        self.assertEqual(v, "bad")
        self.assertIn("Sun", d)



class TestMts515CaptionRules(unittest.TestCase):
    """mts5.15 で追加したキャプション規則（メソポタミア／籤占／キリスト教／肝占）"""

    def test_meso_eae_number_rule(self):
        v, _ = vro.verify_caption("【メソポタミア天体オーメン】EAE-02（栄達・達成）",
                                  Path("02_CrownedMoon.webp"), TABLES)
        self.assertEqual(v, "ok")
        v, _ = vro.verify_caption("【メソポタミア天体オーメン】EAE-02（栄達・達成）",
                                  Path("03_EquinoctialSun.webp"), TABLES)
        self.assertEqual(v, "bad")

    def test_astragaloi_throw_rule(self):
        v, _ = vro.verify_caption("【籤占】第1骨：3の目", Path("02_Trias_3.webp"), TABLES)
        self.assertEqual(v, "ok")
        v, _ = vro.verify_caption("【籤占】第1骨：3の目", Path("01_Chios_1.webp"), TABLES)
        self.assertEqual(v, "bad")

    def test_christian_ref_rule(self):
        v, _ = vro.verify_caption("【キリスト教的黙想】ピリピ 4:13（支えられる力）",
                                  Path("20_WingsOfEagles.webp"), TABLES)
        self.assertEqual(v, "ok")
        v, _ = vro.verify_caption("【キリスト教的黙想】ピリピ 4:13（支えられる力）",
                                  Path("01_LiliesOfTheField.webp"), TABLES)
        self.assertEqual(v, "bad")

    def test_haruspex_fixed_table(self):
        v, _ = vro.verify_caption("【肝占（バールートゥ）】バビロニアの粘土肝模型（神々の啓示）",
                                  Path("01_ClayLiver.webp"), TABLES)
        self.assertEqual(v, "ok")

class TestMts516TypeCDynamic(unittest.TestCase):
    """型C 動的照合（calc 再生成ピクセル比較）（mts5.16）"""

    def setUp(self):
        try:
            from PIL import Image  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("PIL 未導入")
        from fortunelib import chartdraw
        self.chartdraw = chartdraw

    def _encode(self, img) -> bytes:
        import io
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=self.chartdraw.WEBP_Q)
        return buf.getvalue()

    def _zip(self, tmp: Path, calc: dict, img_bytes: bytes, caption: str) -> Path:
        import base64
        import json
        import zipfile
        b64 = base64.b64encode(img_bytes).decode()
        html = (f'<img src="data:image/webp;base64,{b64}" class="fortune-visual" />'
                f'<div class="fortune-image-caption">{caption}</div>')
        zp = tmp / "results.zip"
        with zipfile.ZipFile(zp, "w") as z:
            z.writestr("report.html", html)
            z.writestr("results/M03_kyusei_raw.json",
                       json.dumps({"result": {"calc": calc}}))
        return zp

    CALC = {"year": 1985, "honmei_no": 6, "honmei": "六白金星"}

    def test_unit_ok_and_bad(self):
        import tempfile
        img, cap = self.chartdraw.render_for_slug("M03_kyusei", self.CALC)
        raw = self._encode(img)
        with tempfile.TemporaryDirectory() as t:
            zp = self._zip(Path(t), self.CALC, raw, cap)
            self.assertEqual(vro.typec_dynamic_verify(cap, raw, zp, ROOT)[:2],
                             ("ok", "M03_kyusei"))
            # キャプションと異なる本命星の calc → キャプション⇄calc 不整合で bad
            zp2 = self._zip(Path(t), {"year": 1990, "honmei_no": 1,
                                      "honmei": "一白水星"}, raw, cap)
            self.assertEqual(vro.typec_dynamic_verify(cap, raw, zp2, ROOT)[:2],
                             ("bad", "M03_kyusei"))

    def test_unrelated_image_is_bad(self):
        import tempfile
        img, cap = self.chartdraw.render_for_slug("M03_kyusei", self.CALC)
        other, _ = self.chartdraw.render_for_slug("M06_kabbalah",
                                                  {"romaji": "X", "number": 1})
        import io
        buf = io.BytesIO()
        other.save(buf, "WEBP", quality=self.chartdraw.WEBP_Q)
        with tempfile.TemporaryDirectory() as t:
            zp = self._zip(Path(t), self.CALC, buf.getvalue(), cap)
            self.assertEqual(vro.typec_dynamic_verify(cap, buf.getvalue(), zp, ROOT)[:2],
                             ("bad", "M03_kyusei"))

    def test_tofu_font_is_detected(self):
        """mts5.28: CJKフォント欠落（豆腐□□□）の画像を bad として検出する

        Kaggle に同梱フォントが無いと型Cは豆腐になるが、文字は画素の一部なので
        平均差では閾内に隠れる（mts5.27 実機で実際に素通りした）。
        「フォント無しで描いた画像」との近さで判定する。
        """
        import tempfile
        img, cap = self.chartdraw.render_for_slug("M03_kyusei", self.CALC)
        tofu, restore = vro._render_without_cjk(self.chartdraw, "M03_kyusei",
                                                self.CALC, None)
        try:
            self.assertIsNotNone(tofu, "フォント無し描画の再現に失敗")
            import io
            buf = io.BytesIO()
            tofu.save(buf, "WEBP", quality=self.chartdraw.WEBP_Q)
            raw = buf.getvalue()
        finally:
            restore()
        with tempfile.TemporaryDirectory() as t:
            zp = self._zip(Path(t), self.CALC, raw, cap)
            verdict, slug, detail = vro.typec_dynamic_verify(cap, raw, zp, ROOT)
        self.assertEqual((verdict, slug), ("bad", "M03_kyusei"))
        self.assertIn("CJKフォント", detail)
        # 本物の画像（同梱フォントで描画）は ok のまま（誤検出しない）
        import io as _io
        b = _io.BytesIO()
        img.save(b, "WEBP", quality=self.chartdraw.WEBP_Q)
        with tempfile.TemporaryDirectory() as t:
            zp = self._zip(Path(t), self.CALC, b.getvalue(), cap)
            verdict2, _s, detail2 = vro.typec_dynamic_verify(
                cap, b.getvalue(), zp, ROOT)
        self.assertEqual(verdict2, "ok", detail2)

    def test_non_typec_caption_is_none(self):
        self.assertEqual(vro.typec_dynamic_verify("【タロット】自分自身 The Sun",
                                                  b"", None, ROOT)[:2], (None, ""))

    def test_main_end_to_end(self):
        import contextlib
        import io
        import json
        import tempfile
        img, cap = self.chartdraw.render_for_slug("M03_kyusei", self.CALC)
        raw = self._encode(img)
        with tempfile.TemporaryDirectory() as t:
            zp = self._zip(Path(t), self.CALC, raw, cap)
            out = Path(t) / "out.json"
            argv = ["verify", "--results-zip", str(zp), "--assets", str(ASSETS),
                    "--json-out", str(out)]
            old = sys.argv
            sys.argv = argv
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    rc = vro.main()
            finally:
                sys.argv = old
            data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(rc, 0)
        self.assertEqual(data["byte_ok"], 1)
        self.assertEqual(data["name_ok"], 1)
        self.assertEqual(data["decks"].get("M03_kyusei"), 1)


class TestMts517TypeCCaptions(unittest.TestCase):
    """mts5.17 型Cバッチ1: キャプション規則（整合・改ざん検知・見出し順）。"""

    def test_slug_marker_table(self):
        pairs = dict(vro.TYPEC_CAPTION_SLUG)
        for marker, slug in [("【数秘術（氏名）】", "M05_numerology_name"),
                             ("【カルデア数秘術】", "M07_chaldean"),
                             ("【タントラ数秘術】", "M04_tantra"),
                             ("【アンカ・シャーストラ】", "M04_anka"),
                             ("【六星占術】", "M10_rokusei"),
                             ("【ウェトン】", "M14_weton"),
                             ("【プリンボン・ジャワ】", "M13_primbon")]:
            self.assertEqual(pairs.get(marker), slug)
        marks = [m for m, _ in vro.TYPEC_CAPTION_SLUG]
        self.assertLess(marks.index("【数秘術（氏名）】"), marks.index("【数秘術】"))

    def test_match_ok(self):
        cases = [
            ("M05_numerology_name", "【数秘術（氏名）】氏名数8（HANAKO YAMADA）",
             {"number": 8, "romaji": "Hanako Yamada"}),
            ("M07_chaldean", "【カルデア数秘術】カルデア数5（KEN SATO）",
             {"number": 5, "romaji": "Ken Sato"}),
            ("M04_tantra", "【タントラ数秘術】タントラ数9", {"number": 9}),
            ("M04_anka", "【アンカ・シャーストラ】アンカ数3・支配星：木星", {"number": 3}),
            ("M10_rokusei", "【六星占術】金星人プラス／年運：大殺界（2026）",
             {"type": "金星人プラス", "cycle": "大殺界", "target_year": 2026}),
            ("M14_weton", "【ウェトン】月曜・Pon",
             {"weton_name": "月曜・Pon", "pasaran": "Pon"}),
            ("M13_primbon", "【プリンボン・ジャワ】月曜・Pon／ネプトゥ12",
             {"weton": "月曜・Pon", "neptu_total": 12}),
        ]
        for slug, cap, calc in cases:
            self.assertTrue(
                vro._typec_caption_calc_match(slug, cap, calc, pkg=ROOT), slug)

    def test_match_detects_tampering(self):
        f = vro._typec_caption_calc_match
        self.assertFalse(f("M05_numerology_name",
                           "【数秘術（氏名）】氏名数8（HANAKO YAMADA）",
                           {"number": 7, "romaji": "Hanako Yamada"}, pkg=ROOT))
        self.assertFalse(f("M07_chaldean",
                           "【カルデア数秘術】カルデア数5（KEN SATO）",
                           {"number": 5, "romaji": "Ken Sato X"}, pkg=ROOT))
        self.assertFalse(f("M04_tantra", "【タントラ数秘術】タントラ数9",
                           {"number": 4}, pkg=ROOT))
        # アンカ: 支配星不一致（3=木星なのにキャプションは土星）
        self.assertFalse(f("M04_anka", "【アンカ・シャーストラ】アンカ数3・支配星：土星",
                           {"number": 3}, pkg=ROOT))
        self.assertFalse(f("M10_rokusei",
                           "【六星占術】金星人プラス／年運：大殺界（2026）",
                           {"type": "金星人プラス", "cycle": "再会", "target_year": 2026},
                           pkg=ROOT))
        self.assertFalse(f("M13_primbon", "【プリンボン・ジャワ】月曜・Pon／ネプトゥ12",
                           {"weton": "月曜・Pon", "neptu_total": 13}, pkg=ROOT))

    def test_ornithomancy_is_unverifiable_by_design(self):
        # 鳥占は5変種ランダム表示（おみくじ感覚・mts5.14）→ 名前照合対象外
        self.assertEqual(
            vro.verify_caption("【鳥占】燕の群れ・旋回（Swallows - Circling）",
                               ROOT / "assets" / "images" / "M30_ornith" /
                               "04_SwallowCircle.webp", vro.build_name_tables(ROOT)),
            ("unknown", ""))


class TestMts518TypeCCaptions(unittest.TestCase):
    """mts5.18 型Cバッチ2: キャプション規則（整合・改ざん検知・見出し表）。"""

    def test_slug_marker_table(self):
        pairs = dict(vro.TYPEC_CAPTION_SLUG)
        for marker, slug in [("【姓名判断】", "M16_seimei"),
                             ("【四柱推命】", "M17_bazi"),
                             ("【ヴェーダ占星術】", "M19_vedic"),
                             ("【算命学】", "M21_sanmei"),
                             ("【奇門遁甲】", "M24_qimen")]:
            self.assertEqual(pairs.get(marker), slug)

    def test_match_ok(self):
        from fortunelib.calc.bazi import bazi_paipan
        from fortunelib.calc.astrology import vedic_sidereal, to_jd
        from fortunelib.calc.sanmeigaku import sanmeigaku_full
        from fortunelib.calc.qimen import qimen_pan
        from fortunelib.calc.seimei import seimei_calc
        cases = [
            ("M16_seimei", "【姓名判断】五格 天11・人26・地27・外12・総36",
             seimei_calc("高", "橋連")),
            ("M17_bazi", "【四柱推命】年柱戊午／月柱己未／日柱庚午／時柱壬午・日主：庚（金・陽）",
             bazi_paipan(1978, 7, 7, 12, 0, lon_east=139.7, apply_true_solar=True)),
            ("M19_vedic", "【ヴェーダ占星術】月：蟹座・プシュヤ（パダ2）",
             vedic_sidereal(to_jd(1978, 7, 7, 12.0))),
            ("M21_sanmei", "【算命学】中心星：牽牛星／総エネルギー21",
             {"status": "ok", **sanmeigaku_full(1978, 7, 7)}),
            ("M24_qimen", "【奇門遁甲】陰遁一局中元／値使：死門・坤宮",
             qimen_pan(2026, 9, 26, 9, 0)),
        ]
        for slug, cap, calc in cases:
            self.assertTrue(
                vro._typec_caption_calc_match(slug, cap, calc, pkg=ROOT), slug)

    def test_match_detects_tampering(self):
        f = vro._typec_caption_calc_match
        self.assertFalse(f("M16_seimei", "【姓名判断】五格 天11・人26・地27・外12・総36",
                           {"five_griddles": {}, "five_grilles":
                            {"天格": 11, "人格": 26, "地格": 27, "外格": 12,
                             "総格": 37}}, pkg=ROOT))
        self.assertFalse(f("M17_bazi",
                           "【四柱推命】年柱戊午／月柱己未／日柱庚午／時柱壬午・日主：庚（金・陽）",
                           {"pillars": {"year": "戊午", "month": "己未",
                                        "day": "辛未", "hour": "壬午"},
                            "day_master": {"gan": "辛", "wuxing": "金",
                                           "yinyang": "陰"}}, pkg=ROOT))
        self.assertFalse(f("M19_vedic", "【ヴェーダ占星術】月：蟹座・プシュヤ（パダ2）",
                           {"planets": {"月": {"sign": "蟹座",
                                               "nakshatra": "アシュレーシャ",
                                               "nakshatra_pada": 2}}}, pkg=ROOT))
        self.assertFalse(f("M21_sanmei", "【算命学】中心星：牽牛星／総エネルギー21",
                           {"中心星": "龍高星", "総エネルギー": 21}, pkg=ROOT))
        self.assertFalse(f("M24_qimen", "【奇門遁甲】陰遁一局中元／値使：死門・坤宮",
                           {"paiju": "陽遁九局", "men": {"坤": "死"},
                            "zhifu_zhishi": {"值使門宮": ["死", "坤"]}}, pkg=ROOT))


class TestMts519AstroCaptions(unittest.TestCase):
    """mts5.19 西洋占星術系: キャプション規則（整合・改ざん検知・見出し表）。"""

    @classmethod
    def setUpClass(cls):
        from fortunelib.calc.astrology import natal_chart, transit_chart
        cls.mine = natal_chart(1978, 7, 7, 12.0, 35.7, 139.7)
        cls.theirs = natal_chart(1980, 1, 15, 10.0, 35.7, 139.7)
        cls.tr = transit_chart(cls.mine)

    def test_slug_marker_table(self):
        pairs = dict(vro.TYPEC_CAPTION_SLUG)
        for marker, slug in [("【西洋占星術】", "M18_western"),
                             ("【ネイタル占星術】", "M18_natal"),
                             ("【トランジット】", "M18_transit"),
                             ("【シナストリー】", "M18_synastry")]:
            self.assertEqual(pairs.get(marker), slug)

    def test_match_ok(self):
        from fortunelib import chartdraw
        for slug, calc, extra in [
                ("M18_western", self.mine, None),
                ("M18_natal", self.mine, None),
                ("M18_transit", self.tr, self.mine)]:
            _img, cap = chartdraw.render_for_slug(slug, calc, extra)
            self.assertTrue(
                vro._typec_caption_calc_match(slug, cap, calc, pkg=ROOT), slug)
        syn = {"aspects": [{"p1": "金星", "p2": "月", "aspect": "トライン",
                           "angle": 120, "orb": 1.0}],
               "mine": self.mine, "theirs": self.theirs}
        _img, cap = chartdraw.render_for_slug("M18_synastry", syn)
        self.assertTrue(vro._typec_caption_calc_match("M18_synastry", cap, syn,
                                                      pkg=ROOT))

    def test_match_detects_tampering(self):
        f = vro._typec_caption_calc_match
        cap = "【西洋占星術】太陽：蟹座／月：獅子座／ASC：天秤座"
        bad = {"planets": {"太陽": {"sign": "蟹座"}, "月": {"sign": "獅子座"}},
               "houses": {"asc_sign": "牡羊座"}}
        self.assertFalse(f("M18_western", cap, bad, pkg=ROOT))
        cap = "【トランジット】太陽：天秤座／月：魚座／アスペクト1件"
        self.assertFalse(f("M18_transit", cap,
                           {"transit_planets": {"太陽": {"sign": "天秤座"},
                                                "月": {"sign": "魚座"}},
                            "aspects_to_natal": []}, pkg=ROOT))
        cap = "【シナストリー】アスペクト2件・金星×月 トライン"
        self.assertFalse(f("M18_synastry", cap,
                           {"aspects": [{"p1": "金星", "p2": "月",
                                         "aspect": "オポジション", "angle": 180,
                                         "orb": 1.0},
                                        {"p1": "太陽", "p2": "太陽",
                                         "aspect": "トライン", "angle": 120,
                                         "orb": 1.0}]}, pkg=ROOT))


class TestMts520BRestCaptions(unittest.TestCase):
    """mts5.20 B群残: キャプション規則（整合・改ざん検知・見出し表）。"""

    def test_slug_marker_table(self):
        pairs = dict(vro.TYPEC_CAPTION_SLUG)
        for marker, slug in [("【紫微斗数】", "M20_ziwei"),
                             ("【ヒューマンデザイン】", "M25_hd"),
                             ("【パリミチャム】", "M15_parimicham")]:
            self.assertEqual(pairs.get(marker), slug)

    def test_match_ok(self):
        from fortunelib.calc.ziwei import ziwei_chart
        from fortunelib.calc.hd_full import calculate_chart
        from fortunelib.calc.parimicham import parimicham_calc
        from fortunelib import chartdraw
        cases = [("M20_ziwei", ziwei_chart(1978, 7, 7, 12, gender="male"), None),
                 ("M25_hd", calculate_chart(1978, 7, 7, 12, 0, 9.0), None)]
        p = parimicham_calc({"date": "1978-07-07"}, {"date": "1980-01-15"},
                            role1="本人", role2="相手")
        p["status"] = "ok"
        cases.append(("M15_parimicham", p, None))
        for slug, calc, extra in cases:
            _img, cap = chartdraw.render_for_slug(slug, calc, extra)
            self.assertTrue(
                vro._typec_caption_calc_match(slug, cap, calc, pkg=ROOT), slug)

    def test_match_detects_tampering(self):
        f = vro._typec_caption_calc_match
        self.assertFalse(f("M20_ziwei",
                           "【紫微斗数】金の四局・命宮：命宮／身宮：命宮",
                           {"five_elements_class": "水の二局",
                            "soul_palace": "命宮", "body_palace": "命宮"}, pkg=ROOT))
        self.assertFalse(f("M25_hd",
                           "【ヒューマンデザイン】ジェネレーター・権威：仙骨・6/2",
                           {"type": "Projector", "authority": "Sacral",
                            "profile": "6/2"}, pkg=ROOT))
        self.assertFalse(f("M15_parimicham", "【パリミチャム】5.0/8.0・Good（良い相性）",
                           {"score": 3.0, "score_max": 8.0,
                            "verdict": "Good（良い相性）"}, pkg=ROOT))

# ===============================================================
# mts5.22: Stage D（トーン化）の検証
# ===============================================================
import json as _json
import tempfile as _tempfile
import zipfile as _zipfile


def _tone_zip(td: str, tamper=None, scope=None):
    """トーン化済みの結果ZIPを合成する（1人・3ユニット・easy 1トーン）。

    実コード（run_stage_d_tones）で生成するため、fixture は本番と同じ形式。
    tamper: 任意の関数（tone_reports の Path を引数に・ZIP 化前に改ざん可能）
    """
    from fortunelib.backend import MockBackend
    from fortunelib.tone import run_stage_d_tones

    root = Path(td)
    p = root / "takahashi_ren"
    (p / "results").mkdir(parents=True)
    (p / "cluster_reports").mkdir(parents=True)
    (p / "synthesis_report.md").write_text(
        "# 統合鑑定レポート\n\n"
        "**生成**: 2026-09-26T20:12:24+09:00\n\n"
        "## 総括\n"
        "総合得点は7点中5点です。\n", encoding="utf-8")
    (p / "cluster_reports" / "AXIS_method.md").write_text(
        "# 軸\n\n**対象**: 1本\n\n3つの傾向が見られます。\n",
        encoding="utf-8")
    (p / "results" / "M27_tarot.md").write_text(
        "# タロット\n\n**体系**：テスト。／**実行**：2026-09-26T20:06:57+09:00\n\n"
        "## ■ 使用した入力\n- 生年月日：1978-07-07\n\n"
        "## ■ 鑑定文\n抽出は1枚目と3枚目でした。4の数字です。\n\n"
        "## ■ この占術について\n- 体系：テスト。\n",
        encoding="utf-8")

    class _Rewrite(MockBackend):
        def generate(self, system_prompt, user_prompt, temperature=0.7,
                     max_tokens=1000, seed=None):
            self.calls.append({"user": user_prompt})
            seg = user_prompt.split("===\n", 1)[1]
            if "【再実行の注意】" in seg:
                seg = seg.split("【再実行の注意】", 1)[0].strip()
            return "（口調化）" + seg

    plan = {"reliability": {"backoff_503_s": 0.01},
            "stage_d": {"model": "gemini-3.5-flash-lite",
                        "fallback": ["gemini-3.1-flash-lite"]}}
    if scope:
        plan["stage_d"]["scope"] = scope
    run_stage_d_tones(p / "results", p, {"gemini-3.5-flash-lite": _Rewrite()},
                      plan=plan, verbose=False, workers=2,
                      tone_ids=["easy"])
    if tamper:
        tamper(p / "tone_reports")
    zp = Path(td) / "results.zip"
    with _zipfile.ZipFile(zp, "w") as z:
        for f in root.rglob("*"):
            if f.is_file() and f.name != "results.zip":
                z.write(f, f.relative_to(root).as_posix())
    return str(zp)


_GOOD_TONE_HTML = (
    '<html><body>'
    '<div class="tonebar" id="tonebar">'
    '<button type="button" class="tb-btn" data-tone="standard">標準</button>'
    '<button type="button" class="tb-btn" data-tone="easy">かんたん</button>'
    '</div>'
    '<div class="tone-text" data-unit="synthesis"><p>x</p></div>'
    '<div class="tone-text" data-unit="axis_method"><p>y</p></div>'
    '<div class="tone-text" data-unit="M27_tarot"><p>z</p></div>'
    '<script type="application/json" id="tone-data">'
    '{"tones":{"standard":{"label":"標準","units":{}},'
    '"easy":{"label":"かんたん","units":{"synthesis":"a","axis_method":"b",'
    '"M27_tarot":"c"},"fallback":false}},"rules":{"easy":{"subs":[]}}}'
    '</script>'
    '</body></html>'
)


class TestMts522ToneVerification(unittest.TestCase):
    def test_no_manifest_returns_none(self):
        with _tempfile.TemporaryDirectory() as td:
            zp = _tone_zip(td)
            bad = Path(td) / "no_man.zip"
            with _zipfile.ZipFile(zp) as src, _zipfile.ZipFile(bad, "w") as dst:
                for item in src.infolist():
                    if not item.filename.endswith("tone_manifest.json"):
                        dst.writestr(item, src.read(item.filename))
            self.assertIsNone(vro.verify_tones("<html></html>", str(bad)))

    def test_ok_manifest_no_problems(self):
        with _tempfile.TemporaryDirectory() as td:
            zp = _tone_zip(td)
            rep = vro.verify_tones(_GOOD_TONE_HTML, zp, pkg=ROOT)
            self.assertIsNotNone(rep)
            self.assertTrue(rep["manifest"])
            self.assertEqual(rep["tones"]["easy"]["ok"], 3)
            self.assertEqual(rep["tones"]["easy"]["bad"], 0)
            self.assertEqual(rep["problems"], [])
            self.assertTrue(rep["html"]["tonebar"])
            self.assertTrue(rep["html"]["json"])
            self.assertEqual(rep["html"]["buttons"], 2)
            self.assertEqual(rep["html"]["units"], 3)

    def test_ok_weak_path_without_pkg(self):
        """pkg が無い（弱めチェック）でも正常な成果物は問題なし"""
        with _tempfile.TemporaryDirectory() as td:
            zp = _tone_zip(td)
            rep = vro.verify_tones(_GOOD_TONE_HTML, zp)
            self.assertIsNotNone(rep)
            self.assertEqual(rep["tones"]["easy"]["ok"], 3)
            self.assertEqual(rep["problems"], [])

    def _rezip(self, td, name):
        root = Path(td)
        zp = Path(td) / name
        with _zipfile.ZipFile(zp, "w") as z:
            for f in root.rglob("*"):
                if f.is_file() and f.suffix != ".zip":
                    z.write(f, f.relative_to(root).as_posix())
        return str(zp)

    def test_detects_number_tampering(self):
        def tamper(tr):
            up = tr / "easy" / "segments.json"
            obj = _json.loads(up.read_text(encoding="utf-8"))
            for uid, segs in obj.items():
                for sid, txt in segs["segments"].items():
                    if "7" in txt:
                        segs["segments"][sid] = txt.replace("7点", "6点")
            up.write_text(_json.dumps(obj, ensure_ascii=False),
                          encoding="utf-8")

        with _tempfile.TemporaryDirectory() as td:
            _tone_zip(td, tamper=tamper)
            rep = vro.verify_tones(_GOOD_TONE_HTML, Path(td) / "results.zip",
                                   pkg=ROOT)
            self.assertEqual(rep["tones"]["easy"]["bad"], 1)
            self.assertTrue(any("数値不一致" in pr for pr in rep["problems"]))

    def test_detects_data_tampering(self):
        def tamper(tr):
            up = tr / "easy" / "segments.json"
            obj = _json.loads(up.read_text(encoding="utf-8"))
            obj["M27_tarot"]["data_pre"] = obj["M27_tarot"]["data_pre"].replace(
                "1978", "1979")
            up.write_text(_json.dumps(obj, ensure_ascii=False),
                          encoding="utf-8")

        with _tempfile.TemporaryDirectory() as td:
            _tone_zip(td, tamper=tamper)
            rep = vro.verify_tones(_GOOD_TONE_HTML, Path(td) / "results.zip",
                                   pkg=ROOT)
            self.assertEqual(rep["tones"]["easy"]["bad"], 1)
            self.assertTrue(any("データ部が改変" in pr for pr in rep["problems"]))

    def test_narrative_scope_verified_clean(self):
        """mts5.27: scope=narrative の実行は対象が物語系のみ・問題なし"""
        with _tempfile.TemporaryDirectory() as td:
            zp = _tone_zip(td, scope="narrative")
            rep = vro.verify_tones(_GOOD_TONE_HTML, zp, pkg=ROOT)
            self.assertEqual(rep.get("scope"), "narrative")
            self.assertEqual(rep.get("target_units"), 2)   # synthesis + axis
            self.assertNotIn("M27_tarot",
                             _json.loads(_zipfile.ZipFile(zp).read(
                                 "takahashi_ren/tone_reports/easy/units.json"
                             ).decode("utf-8")))
            self.assertFalse([p for p in rep["problems"]
                              if "scope=narrative" in p], rep["problems"])
            self.assertEqual(rep["tones"]["easy"]["bad"], 0)

    def test_narrative_scope_with_tool_unit_is_problem(self):
        """scope=narrative なのに個別占術が対象に入っていたら検出する（設定ずれ）"""
        def tamper(tr):
            mp = tr / "tone_manifest.json"
            obj = _json.loads(mp.read_text(encoding="utf-8"))
            obj["scope"] = "narrative"        # scope だけ書き換えて矛盾を作る
            mp.write_text(_json.dumps(obj, ensure_ascii=False),
                          encoding="utf-8")

        with _tempfile.TemporaryDirectory() as td:
            _tone_zip(td, tamper=tamper)      # 実体は scope=all（tool を含む）
            rep = vro.verify_tones(_GOOD_TONE_HTML, Path(td) / "results.zip",
                                   pkg=ROOT)
            self.assertTrue(any("scope=narrative なのに物語系以外" in p
                                for p in rep["problems"]), rep["problems"])

    def test_tonebar_without_json_is_problem(self):
        html = ('<div class="tonebar"><button class="tb-btn">'
                'data-tone="standard"</button></div>')
        with _tempfile.TemporaryDirectory() as td:
            zp = _tone_zip(td)
            rep = vro.verify_tones(html, zp, pkg=ROOT)
            self.assertTrue(any("tone-data" in pr for pr in rep["problems"]))

    def test_old_run_html_no_tonebar(self):
        """前バージョンの実行（manifest なし・tonebar なし）は問題なし"""
        with _tempfile.TemporaryDirectory() as td:
            zp = _tone_zip(td)
            rep = vro.verify_tones(
                "<html><body><p>旧HTML</p></body></html>", zp, pkg=ROOT)
            # manifest はあるが tonebar なし → 「tonebar がない」問題
            self.assertTrue(any("tonebar" in pr for pr in rep["problems"]))


if __name__ == "__main__":
    unittest.main()

class TestSynthesisTabsHtmlOnly(unittest.TestCase):
    """mts5.46: results.zipなしでも統合レポート内の読み物版切替を検査する。"""

    def _html(self, with_switcher=True, with_note=True, with_json=True):
        buttons = ('' if not with_switcher else
                   '<div class="synthesis-switcher" id="synthesis-switcher" role="tablist">'
                   '<button type="button" class="tb-btn synthesis-view-btn" '
                   'id="synthesis-tab-standard" data-tone="standard" '
                   'aria-pressed="true" aria-selected="true">標準</button>'
                   '<button type="button" class="tb-btn synthesis-view-btn" '
                   'data-tone="easy" aria-pressed="false">かんたん</button>'
                   '<button type="button" class="tb-btn synthesis-view-btn" '
                   'data-tone="spiritual" aria-pressed="false">スピリチュアル風</button>'
                   '</div>')
        note = ('<p class="synthesis-note">読み物版は表現を変えたものです。'
                '正確な内容・数値の正本は「標準」です。</p>' if with_note else '')
        data = ('<script type="application/json" id="omake-data">'
                '{"omake":{"easy":"<p>a</p>","spiritual":"<p>c</p>"}}'
                '</script>' if with_json else '')
        return ("<html><body><section id=\"synthesis\" class=\"card\">"
                "<h2>統合鑑定レポート</h2>" + buttons + note
                + '<div id="synthesis-body" class="tone-text" data-unit="synthesis">標準</div>'
                + data + "</section></body></html>")

    def test_reports_switcher_without_zip(self):
        rep = vro.verify_tones(self._html(), None)
        self.assertIsNotNone(rep)
        self.assertEqual(rep.get("mode"), "omake-html")
        self.assertTrue(rep["html"]["synthesis_switcher"])
        self.assertTrue(rep["html"]["synthesis_body"])
        self.assertTrue(rep["html"]["standard_default"])
        self.assertFalse(rep["html"]["legacy_omake_card"])
        self.assertTrue(rep["html"]["variants_json"])
        self.assertEqual(rep["html"]["variants"], 2)     # mts5.65: obaa を削除
        self.assertEqual(rep["html"]["buttons"], 3)      # 標準＋2トーン
        self.assertEqual(rep["problems"], [])

    def test_flags_missing_note_and_json(self):
        rep = vro.verify_tones(self._html(with_note=False, with_json=False), None)
        self.assertTrue(any("正本" in p or "正確な内容・数値" in p
                            for p in rep["problems"]), rep["problems"])
        self.assertTrue(any("JSON" in p for p in rep["problems"]), rep["problems"])

    def test_flags_nonstandard_default_or_legacy_card(self):
        html = self._html().replace('aria-pressed="true"', 'aria-pressed="false"', 1)
        html = html.replace('<section id="synthesis"',
                            '<section id="omake" class="card omake-card"><section id="synthesis"')
        rep = vro.verify_tones(html, None)
        self.assertTrue(any("標準" in p for p in rep["problems"]), rep["problems"])
        self.assertTrue(any("旧レイアウト" in p for p in rep["problems"]), rep["problems"])

    def test_manifest_and_html_use_the_new_switcher(self):
        with _tempfile.TemporaryDirectory() as td:
            zp = _tone_zip(td, scope="synthesis")
            person = Path(td) / "takahashi_ren"
            from fortunelib.html_report import build_html
            out = build_html(person, person_id="test")
            rep = vro.verify_tones(out.read_text(encoding="utf-8"), zp, pkg=ROOT)
        self.assertEqual(rep.get("mode"), "omake")
        self.assertEqual(rep["tones"]["easy"]["ok"], 1)
        self.assertTrue(rep["html"]["synthesis_switcher"])
        self.assertTrue(rep["html"]["standard_default"])
        self.assertFalse(rep["html"]["legacy_omake_card"])
        self.assertEqual(rep["problems"], [], rep["problems"])

    def test_plain_html_is_unchanged(self):
        """variantsの無いHTMLではStage D UIモードにならない。"""
        rep = vro.verify_tones("<html><body><p>読み物版なし</p></body></html>", None)
        self.assertNotEqual((rep or {}).get("mode"), "omake-html")
        self.assertNotEqual((rep or {}).get("mode"), "omake")


class TestDeckScopedNamesMts551(unittest.TestCase):
    """同名カードを持つ別デッキの照合（mts5.51）

    「思いやり」はオラクル40（Compassion）とエンジェル43（Kindness）の両方にあり、
    かつ**どちらも no=43/40 が実在**する。以前は和名→英名の表を1つに詰めていたため
    先に読んだ側の英名だけが使われ、もう一方が「対応しない」と誤検出されていた。

    ※ 実測（2026-09-29のmts5.50実行）: angel 思いやり（逆位置）→ 43_Kindness.webp は
      正しい画像なのに name 判定が bad になっていた。その再発防止。
    """

    ANGEL_CAPTION = "【エンジェル】位置3 思いやり（逆位置）"
    ORACLE_CAPTION = "【オラクル】位置40 思いやり（正位置）"

    def test_angel_compassion_name_resolves_to_kindness(self):
        verdict, detail = vro.verify_caption(
            self.ANGEL_CAPTION, ASSETS / "M27_angel" / "43_Kindness.webp", TABLES)
        self.assertEqual(verdict, "ok", detail)

    def test_oracle_compassion_name_resolves_to_compassion(self):
        verdict, detail = vro.verify_caption(
            self.ORACLE_CAPTION, ASSETS / "M27_oracle" / "40_Compassion.webp", TABLES)
        self.assertEqual(verdict, "ok", detail)

    def test_wrong_deck_image_is_still_detected(self):
        """デッキ別にした結果、誤充当を見逃さないこと（過剰緩和の防止）"""
        verdict, _ = vro.verify_caption(
            self.ANGEL_CAPTION, ASSETS / "M27_oracle" / "40_Compassion.webp", TABLES)
        self.assertEqual(verdict, "bad")

    def test_deck_table_exists_and_is_scoped(self):
        self.assertEqual(TABLES["ja2en_by_deck"]["M27_angel"]["思いやり"], "Kindness")
        self.assertEqual(TABLES["ja2en_by_deck"]["M27_oracle"]["思いやり"], "Compassion")


class TestJsonOutEndToEndMts551(unittest.TestCase):
    """`--json-out` を付けたCLI実行が通ること（mts5.51）

    以前は main() の後半に `import json` があったため `json` が関数ローカル扱いになり、
    同じ関数の前半（読み物版＝omake 分岐）の json.dumps が UnboundLocalError で落ちていた。
    omake の結果ZIPを作り、CLIとして実行して**出力JSONが書けること**を固定する。
    """

    @staticmethod
    def _omake_zip(td: str, easy_extra: dict | None = None,
                   manifest_extra: dict | None = None) -> str:
        """omake（読み物版）の結果ZIPを作る。

        mts5.56: `easy_extra` で easy トーンの `discrimination` などを、
        `manifest_extra` で manifest 直下（`discrimination` のトーン間類似度など）を足せる。
        """
        import base64
        import json as _json
        import zipfile as _zipfile

        root = Path(td)
        person = root / "demo_person"
        (person / "tone_reports" / "easy").mkdir(parents=True)
        body = "総括です。" * 12
        (person / "synthesis_report.md").write_text(
            "# 統合鑑定レポート\n\n" + body + "\n", encoding="utf-8")

        def _img(rel: str) -> str:
            raw = (ASSETS / rel).read_bytes()
            return base64.b64encode(raw).decode()

        html = (
            '<html><body>'
            f'<img src="data:image/webp;base64,{_img("M27_angel/43_Kindness.webp")}" alt="a" />'
            '<div class="fortune-image-caption">【エンジェル】位置3 思いやり（逆位置）</div>'
            f'<img src="data:image/webp;base64,{_img("M27_oracle/40_Compassion.webp")}" alt="b" />'
            '<div class="fortune-image-caption">【オラクル】位置40 思いやり（正位置）</div>'
            '</body></html>'
        )
        (person / f"{person.name}_report.html").write_text(html, encoding="utf-8")
        easy = {"status": "ok", "mode": "omake", "chars": len(body), "ratio": 1.0,
                "numbers_new": []}
        if easy_extra:
            easy.update(easy_extra)
        man = {"scope": "synthesis", "omake_unit_id": "synthesis_omake",
               "tones": {"easy": easy}}
        if manifest_extra:
            man.update(manifest_extra)
        (person / "tone_reports" / "tone_manifest.json").write_text(
            _json.dumps(man, ensure_ascii=False), encoding="utf-8")
        (person / "tone_reports" / "easy" / "units.json").write_text(
            _json.dumps({"synthesis_omake": body}, ensure_ascii=False), encoding="utf-8")
        zp = root / "results.zip"
        with _zipfile.ZipFile(zp, "w") as z:
            for f in person.rglob("*"):
                if f.is_file():
                    z.write(f, f.relative_to(root).as_posix())
        return str(zp)

    def test_json_out_is_written_on_the_omake_branch(self):
        import json as _json
        import subprocess
        with _tempfile.TemporaryDirectory() as td:
            zp = self._omake_zip(td)
            out = Path(td) / "verify.json"
            script = ROOT.parent / "verify" / "verify_run_output.py"
            proc = subprocess.run(
                [sys.executable, str(script), "--results-zip", zp,
                 "--assets", str(ASSETS), "--pkg", str(ROOT), "--json-out", str(out)],
                capture_output=True, text=True, timeout=300)
            self.assertEqual(proc.returncode, 0, proc.stdout[-800:] + proc.stderr[-800:])
            self.assertTrue(out.is_file(), "json-out が書かれていません")
            rep = _json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(rep["images"], 2)
        self.assertEqual(rep["name_bad"], 0, rep["problems"])
        self.assertEqual(rep["byte_miss"], 0)
        # json_out の tones は検証結果オブジェクトそのもの（manifest/tones/html/problems）
        self.assertTrue(rep["tones"]["manifest"])
        self.assertEqual(rep["tones"]["tones"]["easy"]["ok"], 1)


class TestToneStyleReportingMts556(unittest.TestCase):
    """読み物版の弁別指標を検証器が表示し、未達を警告に残すこと（mts5.56）。

    - 指標（丁寧体%・平均文長・目印語・標準類似・試行回数）とトーン間の類似度を表示する
    - 未達のまま採用された本文は **警告**（不合格ではない＝既定の終了コードは 0）
    - モックの記録（`enforced: false`）は警告にしない
    """

    _OK_DISC = {"polite_ratio": 0.41, "avg_sentence_chars": 38.0, "marker_total": 9,
                "similarity": 0.62, "problems": [], "enforced": True}
    _PAIR = {"pairwise": {"easy|spiritual": 0.31}, "pair_sim_max": 0.75,
             "problems": []}

    def _run(self, td: str, disc: dict | None, attempts: int = 2):
        import subprocess
        easy_extra = {"discrimination": disc, "attempts": attempts}
        zp = TestJsonOutEndToEndMts551._omake_zip(
            td, easy_extra=easy_extra, manifest_extra={"discrimination": self._PAIR})
        out = Path(td) / "verify.json"
        script = ROOT.parent / "verify" / "verify_run_output.py"
        proc = subprocess.run(
            [sys.executable, str(script), "--results-zip", zp,
             "--assets", str(ASSETS), "--pkg", str(ROOT), "--json-out", str(out)],
            capture_output=True, text=True, timeout=300)
        self.assertTrue(out.is_file(), proc.stdout[-800:] + proc.stderr[-800:])
        rep = _json.loads(out.read_text(encoding="utf-8"))
        return proc, rep

    def test_metrics_and_pairwise_are_reported(self):
        with _tempfile.TemporaryDirectory() as td:
            proc, rep = self._run(td, dict(self._OK_DISC), attempts=2)
        self.assertEqual(proc.returncode, 0, proc.stdout[-800:])
        self.assertIn("口調: 丁寧体41%", proc.stdout)
        self.assertIn("平均38字", proc.stdout)
        self.assertIn("目印語9個", proc.stdout)
        self.assertIn("標準類似62%", proc.stdout)
        self.assertIn("2試行", proc.stdout)
        self.assertIn("トーン間", proc.stdout)           # トーン間の類似度
        self.assertEqual(rep["tones"]["tones"]["easy"]["style"]["marker_total"], 9)
        self.assertEqual(rep["tones"]["tones"]["easy"]["attempts"], 2)
        self.assertFalse([w for w in rep["warnings"] if "口調の指定に未達" in w],
                         rep["warnings"])

    def test_unmet_style_is_a_warning_not_a_failure(self):
        with _tempfile.TemporaryDirectory() as td:
            disc = dict(self._OK_DISC)
            disc["problems"] = ["丁寧体（です・ます調）で終わる文が 91%（上限 60%）で、"
                                "標準の文体のままです"]
            proc, rep = self._run(td, disc)
        self.assertEqual(proc.returncode, 0, proc.stdout[-800:])   # 警告どまり
        self.assertEqual(rep["problems"], [], rep["problems"])     # 不合格ではない
        self.assertTrue(any("口調の指定に未達" in w for w in rep["warnings"]),
                        rep["warnings"])
        self.assertIn("未達1件", proc.stdout)

    def test_mock_records_are_not_warned(self):
        with _tempfile.TemporaryDirectory() as td:
            disc = dict(self._OK_DISC)
            disc["problems"] = ["丁寧体（です・ます調）で終わる文が 91%（上限 60%）で、"
                                "標準の文体のままです"]
            disc["enforced"] = False                     # モック（demo・単体テスト）
            proc, rep = self._run(td, disc)
        self.assertEqual(proc.returncode, 0, proc.stdout[-800:])
        self.assertFalse([w for w in rep["warnings"] if "口調の指定に未達" in w],
                         rep["warnings"])


class TestPkgArgumentGuardMts551(unittest.TestCase):
    """誤った `--pkg` を渡したときに黙って劣化せず警告すること（mts5.51）

    実例: ローカルのリポジトリ直下（`/home/user/fortune_dataset`）で、Kaggle/ZIP 用の
    `--pkg fortune_dataset/fortune_dataset` を渡すと **data/*.json も fortunelib も読めず**、
    型C 22枚が「納品画像と一致しない」・和名が「判定不能」に静かに劣化していた
    （mts5.50 成果物の再検証で実際に踏んだ）。警告が出ることを固定する。
    """

    def test_warns_when_pkg_cannot_be_loaded(self):
        import subprocess
        with _tempfile.TemporaryDirectory() as td:
            zp = TestJsonOutEndToEndMts551._omake_zip(td)
            bogus = Path(td) / "not_a_pkg"
            bogus.mkdir()
            script = ROOT.parent / "verify" / "verify_run_output.py"
            proc = subprocess.run(
                [sys.executable, str(script), "--results-zip", zp,
                 "--assets", str(ASSETS), "--pkg", str(bogus)],
                capture_output=True, text=True, timeout=300)
            self.assertEqual(proc.returncode, 0, proc.stdout[-500:] + proc.stderr[-500:])
        self.assertIn("[警告]", proc.stdout)
        self.assertIn("--pkg", proc.stdout)

    def test_no_warning_for_the_real_package_dir(self):
        import subprocess
        with _tempfile.TemporaryDirectory() as td:
            zp = TestJsonOutEndToEndMts551._omake_zip(td)
            script = ROOT.parent / "verify" / "verify_run_output.py"
            proc = subprocess.run(
                [sys.executable, str(script), "--results-zip", zp,
                 "--assets", str(ASSETS), "--pkg", str(ROOT)],
                capture_output=True, text=True, timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stdout[-500:])
        # mts5.52: 「成果物についての警告」（デッキ数など）は出るので、
        # **--pkg の解決に関する警告が出ていないこと**を固定する。
        self.assertNotIn("では検証情報を十分に読めません", proc.stdout)
        self.assertNotIn("--pkg", proc.stdout)


class TestPkgResolutionMts552(unittest.TestCase):
    """`--pkg` の自動解決（mts5.52・F-2）

    実例（mts5.50 の成果物）: 実行ディレクトリと `--pkg` の組み合わせ次第で、型C 22枚が
    「納品画像と一致しない」という**誤報**（exit 1）になっていた。とくに
    「ZIP展開ルートの親 + `--pkg fortune_dataset`」では**警告も出なかった**。
    """

    @staticmethod
    def _fake_pkg(root: Path, name: str = "fortune_dataset") -> Path:
        pkg = root / name
        (pkg / "data").mkdir(parents=True)
        (pkg / "data" / "dataset_version.json").write_text('{"build_id": "test"}',
                                                           encoding="utf-8")
        (pkg / "fortunelib").mkdir()
        (pkg / "fortunelib" / "chartdraw.py").write_text("# stub\n", encoding="utf-8")
        return pkg

    def test_two_level_layout_is_usable(self):
        """ZIP展開後（<ルート>/fortune_dataset/…）でも data と fortunelib を解決できる"""
        import tempfile as _tempfile
        with _tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "extracted"
            pkg = self._fake_pkg(repo)
            self.assertTrue(vro.pkg_is_usable(repo))       # リポジトリ直下を渡しても可
            self.assertTrue(vro.pkg_is_usable(pkg))
            self.assertEqual(vro._pkg_lib_dir(repo), pkg)

    def test_data_only_directory_is_not_usable(self):
        """data は読めるが fortunelib が無い場所は候補にしない（静かな誤報の原因）"""
        import tempfile as _tempfile
        with _tempfile.TemporaryDirectory() as td:
            d = Path(td) / "only_data"
            (d / "data").mkdir(parents=True)
            self.assertFalse(vro.pkg_is_usable(d))

    def test_resolve_from_assets(self):
        """--assets から逆算して解決する（--pkg を省略できる）"""
        import tempfile as _tempfile
        with _tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            pkg = self._fake_pkg(repo)
            (pkg / "assets" / "images").mkdir(parents=True)
            got, tried = vro.resolve_pkg(None, pkg / "assets" / "images", script_dir=Path(td))
            self.assertEqual(got, pkg)
            self.assertTrue(tried)

    def test_explicit_pkg_is_not_silently_replaced(self):
        """--pkg を指定したのに解決できないときは、別のパッケージへ黙って移らない"""
        import tempfile as _tempfile
        with _tempfile.TemporaryDirectory() as td:
            bogus = Path(td) / "bogus"
            bogus.mkdir()
            got, tried = vro.resolve_pkg(str(bogus), None, script_dir=ROOT.parent)
            self.assertIsNone(got)
            self.assertTrue(all(str(bogus) in str(t) for t in tried), tried)


class TestFontCloserMts552(unittest.TestCase):
    """1文字ぶんの豆腐の判定（mts5.52・F-4）

    実測（mts5.50 の型C・M15 パリミチャム）: 正常 0 画素 / 1グリフ豆腐 14 画素
    （CJKを描く画素 1,711）。平均差 0.03・画素率 0.03% で、従来の閾値
    （平均差 8.0 / 画素率 1.0%）はどちらも素通りしていた。
    """

    @staticmethod
    def _images(glyph: bool):
        from PIL import Image
        correct = Image.new("L", (40, 40), 255)
        no_cjk = Image.new("L", (40, 40), 255)
        if glyph:
            for x in range(10, 22):
                for y in range(10, 22):
                    correct.putpixel((x, y), 0)
        return correct.convert("RGB"), no_cjk.convert("RGB")

    def test_tofu_is_separated_from_the_real_image(self):
        correct, no_cjk = self._images(True)
        n_ok, _r, strokes = vro._font_closer_stats(correct.copy(), correct, no_cjk)
        n_tofu, _r2, _s2 = vro._font_closer_stats(no_cjk.copy(), correct, no_cjk)
        self.assertGreater(strokes, 0)
        self.assertEqual(n_ok, 0)
        self.assertGreaterEqual(n_tofu, strokes)        # 文字画素すべてが「フォント無し寄り」
        self.assertFalse(vro.font_missing_trigger(n_ok, strokes))
        self.assertTrue(vro.font_missing_trigger(n_tofu, strokes))

    def test_measured_values_from_the_real_run(self):
        """実測値（正常0画素 / 豆腐14画素・描画画素1,711）で判定式が境界どおり動く"""
        self.assertFalse(vro.font_missing_trigger(0, 1711))
        self.assertFalse(vro.font_missing_trigger(2, 1711))     # わずかな揺らぎは許容
        self.assertTrue(vro.font_missing_trigger(14, 1711))

    def test_no_strokes_is_safe(self):
        self.assertFalse(vro.font_missing_trigger(0, 0))


class TestExitCodesMts552(unittest.TestCase):
    """終了コードの方針（mts5.52・F-3）: 不合格=exit 1 / 警告は `--strict` のときだけ"""

    def test_exit_code_helper(self):
        probs = [{"caption": "x", "kind": "bytes", "detail": "y"}]
        warns = ["トーンの警告"]
        self.assertEqual(vro._exit_code(probs, [], False), 1)
        self.assertEqual(vro._exit_code(probs, warns, True), 1)
        self.assertEqual(vro._exit_code([], [], False), 0)
        self.assertEqual(vro._exit_code([], warns, False), 0)    # 既定は警告のみ＝合格
        self.assertEqual(vro._exit_code([], warns, True), 1)     # --strict で不合格


class TestCoverageAndStrictCliMts552(unittest.TestCase):
    """CLI 実行での網羅の検査と `--strict`（mts5.52・F-1 / F-3）"""

    SCRIPT = ROOT.parent / "verify" / "verify_run_output.py"

    @staticmethod
    def _run(*args):
        import subprocess
        return subprocess.run([sys.executable, str(TestCoverageAndStrictCliMts552.SCRIPT), *args],
                              capture_output=True, text=True, timeout=300)

    def test_zero_images_is_a_failure(self):
        """画像が1枚も無いHTMLは不合格（従来は「問題なし」exit 0 だった）"""
        import tempfile as _tempfile
        with _tempfile.TemporaryDirectory() as td:
            html = Path(td) / "no_images.html"
            html.write_text("<html><body><p>画像なし</p></body></html>", encoding="utf-8")
            proc = self._run("--html", str(html), "--assets", str(ASSETS))
            self.assertEqual(proc.returncode, 1, proc.stdout[-400:])
            self.assertIn("■ 不合格", proc.stdout)
            self.assertIn("画像が1枚も埋め込まれていません", proc.stdout)

    def test_expect_images_mismatch_is_a_failure(self):
        import tempfile as _tempfile
        with _tempfile.TemporaryDirectory() as td:
            zp = TestJsonOutEndToEndMts551._omake_zip(td)     # 画像2枚・デッキ2
            ok = self._run("--results-zip", zp, "--assets", str(ASSETS), "--pkg", str(ROOT),
                           "--expect-images", "2", "--expect-decks", "2")
            self.assertEqual(ok.returncode, 0, ok.stdout[-500:])
            bad = self._run("--results-zip", zp, "--assets", str(ASSETS), "--pkg", str(ROOT),
                            "--expect-images", "3")
            self.assertEqual(bad.returncode, 1, bad.stdout[-500:])
            self.assertIn("画像枚数が期待と一致しません", bad.stdout)

    def test_strict_makes_warnings_fail(self):
        """読み物版の警告（トーン・レイアウト）は既定では合格、`--strict` で不合格"""
        import tempfile as _tempfile
        with _tempfile.TemporaryDirectory() as td:
            zp = TestJsonOutEndToEndMts551._omake_zip(td)
            base = self._run("--results-zip", zp, "--assets", str(ASSETS), "--pkg", str(ROOT))
            strict = self._run("--results-zip", zp, "--assets", str(ASSETS), "--pkg", str(ROOT),
                               "--strict")
            self.assertEqual(base.returncode, 0, base.stdout[-500:])
            self.assertIn("■ 警告", base.stdout)
            self.assertEqual(strict.returncode, 1, strict.stdout[-500:])


class TestTypeCUnverifiableMts552(unittest.TestCase):
    """型Cの照合不能の扱い（mts5.52・F-2③ / F-1）

    ・検証環境の不足（fortunelib を読めない）→ **exit 2**（誤報ではなく「検証できない」）
    ・実行ごとの材料不足（生JSONが無い）→ **不合格 exit 1**（fail-safe は維持）
    """

    SCRIPT = ROOT.parent / "verify" / "verify_run_output.py"
    PREFIX = vro.TYPEC_CAPTION_SLUG[0][0]

    @classmethod
    def _zip_with_typec_image(cls, td: str) -> str:
        """納品画像とはバイトが違う画像（＝型Cの再生成画像の代役）＋型CキャプションのZIP"""
        import base64
        import io
        import zipfile as _zipfile
        from PIL import Image
        img = Image.open(io.BytesIO((ASSETS / "M27_angel" / "43_Kindness.webp").read_bytes()))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG")            # 別形式＝バイト不一致
        b64 = base64.b64encode(buf.getvalue()).decode()
        html = ("<html><body>"
                f'<img src="data:image/png;base64,{b64}" alt="x" />'
                f'<div class="fortune-image-caption">{cls.PREFIX}テスト</div>'
                "</body></html>")
        zp = Path(td) / "results.zip"
        with _zipfile.ZipFile(zp, "w") as z:
            z.writestr("demo/demo_report.html", html)
            z.writestr("demo/synthesis_report.md", "# 統合鑑定レポート\n\n本文です。\n")
        return str(zp)

    @staticmethod
    def _run(*args):
        import subprocess
        return subprocess.run([sys.executable, str(TestTypeCUnverifiableMts552.SCRIPT), *args],
                              capture_output=True, text=True, timeout=300)

    def test_pkg_not_resolvable_stops_with_exit_2(self):
        """型Cがあるのに fortunelib を解決できない → 警告続行ではなく exit 2"""
        import tempfile as _tempfile
        with _tempfile.TemporaryDirectory() as td:
            zp = self._zip_with_typec_image(td)
            bogus = Path(td) / "bogus"
            bogus.mkdir()
            proc = self._run("--results-zip", zp, "--assets", str(ASSETS), "--pkg", str(bogus))
            self.assertEqual(proc.returncode, 2, proc.stdout[-600:])
            self.assertIn("型Cの照合ができません", proc.stdout)
            self.assertIn("--pkg", proc.stdout)

    def test_missing_raw_json_is_still_a_failure(self):
        """生JSONが無い＝照合不能は「不一致」ではなく「照合不能」に計上し、不合格は維持"""
        import json as _json
        import tempfile as _tempfile
        with _tempfile.TemporaryDirectory() as td:
            zp = self._zip_with_typec_image(td)
            out = Path(td) / "verify.json"
            proc = self._run("--results-zip", zp, "--assets", str(ASSETS), "--pkg", str(ROOT),
                             "--json-out", str(out))
            self.assertEqual(proc.returncode, 1, proc.stdout[-600:])
            self.assertIn("照合不能", proc.stdout)
            self.assertIn("raw.json が無いため照合できません", proc.stdout)
            rep = _json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(rep["byte_unverified"], 1)
        self.assertEqual(rep["byte_miss"], 0, rep["problems"])
        self.assertTrue(any(p["kind"] == "typec_unverifiable" for p in rep["problems"]))


class TestTypecJapaneseReverseMappingMts561(unittest.TestCase):
    """型Cの「キャプション ⇄ calc」照合で、日本語→英語の逆引きの**多対一**を正しく扱う。

    実機 mts5.60（人物 demo_morimoto_haruka）で発見:
      `chartdraw._HD_AUTH_JA` は Ego と Self-Projected が**どちらも「自己」**。
      素朴な逆引き `{v: k for k, v in table.items()}` は後勝ちで Self-Projected になり、
      **権威=Ego の鑑定が「キャプションと calc が不一致」と誤報**されていました
      （画像も『納品画像と一致しない』に計上され、デッキ数も 47/48 に減って
      カバレッジ警告まで連鎖。成果物そのものは正常）。
    """

    def _caption(self, type_ja: str, auth_ja: str, profile: str) -> str:
        return f"【ヒューマンデザイン】{type_ja}・権威：{auth_ja}・{profile}"

    def test_reverse_multi_keeps_every_english_value(self):
        from fortunelib import chartdraw
        rev = vro._reverse_multi(chartdraw._HD_AUTH_JA)
        self.assertEqual(rev["自己"], {"Ego", "Self-Projected"})   # 潰れていない
        self.assertEqual(rev["仙骨"], {"Sacral"})

    def test_ja_matches_accepts_either_owner_of_an_ambiguous_label(self):
        self.assertTrue(vro._ja_matches({"自己": {"Ego", "Self-Projected"}},
                                        "自己", "Ego"))
        self.assertTrue(vro._ja_matches({"自己": {"Ego", "Self-Projected"}},
                                        "自己", "Self-Projected"))
        self.assertFalse(vro._ja_matches({"自己": {"Ego"}}, "自己", "Sacral"))
        # 未知のラベルは英語がそのまま書かれている場合がある
        self.assertTrue(vro._ja_matches({}, "Manifestor", "Manifestor"))
        self.assertFalse(vro._ja_matches({}, "Manifestor", "Generator"))

    def test_ego_authority_caption_matches_calc(self):
        """実機の再現: 権威=Ego の鑑定が不一致と誤報されない。"""
        calc = {"type": "Manifestor", "authority": "Ego", "profile": "3/5"}
        ok = vro._typec_caption_calc_match(
            "M25_hd", self._caption("マニフェスター", "自己", "3/5"), calc,
            pkg=ROOT)
        self.assertTrue(ok)

    def test_self_projected_authority_also_matches(self):
        calc = {"type": "Projector", "authority": "Self-Projected", "profile": "1/3"}
        ok = vro._typec_caption_calc_match(
            "M25_hd", self._caption("プロジェクター", "自己", "1/3"), calc,
            pkg=ROOT)
        self.assertTrue(ok)

    def test_wrong_authority_is_still_detected(self):
        """誤りは今までどおり検出する（緩めすぎない）。"""
        calc = {"type": "Manifestor", "authority": "Ego", "profile": "3/5"}
        bad = vro._typec_caption_calc_match(
            "M25_hd", self._caption("マニフェスター", "脾", "3/5"), calc,
            pkg=ROOT)
        self.assertFalse(bad)
        bad2 = vro._typec_caption_calc_match(
            "M25_hd", self._caption("ジェネレーター", "自己", "3/5"), calc,
            pkg=ROOT)
        self.assertFalse(bad2)
        bad3 = vro._typec_caption_calc_match(
            "M25_hd", self._caption("マニフェスター", "自己", "6/2"), calc,
            pkg=ROOT)
        self.assertFalse(bad3)

    def test_real_run_result_is_clean(self):
        """実機 mts5.60 の結果ZIP（あれば）で「問題 0・デッキ48」を確認する。"""
        import json
        import subprocess
        import tempfile
        # 実機の結果ZIPは開発側の uploads/ に置かれる（mts5.61: 探索先を複数候補に）。
        cands = [ROOT.parent.parent / "uploads", ROOT.parent / "uploads", Path("/home/user/uploads")]
        z = next((c / "results_mts5.60.zip.txt" for c in cands
                  if (c / "results_mts5.60.zip.txt").exists()), None)
        if z is None:
            self.skipTest("実機の結果ZIPが無い環境")
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "v.json"
            subprocess.run(
                [sys.executable, str(ROOT.parent / "verify" / "verify_run_output.py"),
                 "--results-zip", str(z), "--json-out", str(out)],
                cwd=str(ROOT.parent), check=False, capture_output=True)
            data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(data["problems"], [])
        self.assertEqual(len(data["decks"]), 48)
