# -*- coding: utf-8 -*-
"""型C 動的チャート描画（chartdraw）のテスト（mts5.16）

mts5.31: **unittest でも回るように統一**しました。理由＝Kaggle のセルフテスト
（Cell 0.1）は `unittest discover` でテストを集めるため、pytest 形式
（fixture / parametrize / importorskip）で書かれていると**1件も実行されません**。
型Cは「文字が豆腐（□□□）になった」不具合を出した領域なので、
Kaggle のCIゲートから漏れないようにここを unittest 形式へ揃えました
（pytest からもそのまま実行できます）。
"""
from __future__ import annotations

import datetime as dt
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:                                    # PIL が無い環境ではテストごとスキップ
    import PIL                          # noqa: F401
    _HAS_PIL = True
except ImportError:                     # pragma: no cover
    _HAS_PIL = False

from fortunelib import chartdraw  # noqa: E402


class _ChartdrawTestCase(unittest.TestCase):
    """共通の下準備（PIL が無い環境ではスキップ・一時ディレクトリの後始末）"""

    @classmethod
    def setUpClass(cls):
        if not _HAS_PIL:
            raise unittest.SkipTest("PIL が無い環境のためスキップ（Pillow 未導入）")

    def tmp(self) -> Path:
        """テスト用の一時ディレクトリ（テスト終了時に自動削除）"""
        d = Path(self.enterContext(tempfile.TemporaryDirectory()))
        return d


def _px(img):
    return img.tobytes()


class TestRenderBasics(_ChartdrawTestCase):
    def test_size_and_determinism(self):
        a = chartdraw.render_kyusei(1985, 6)
        b = chartdraw.render_kyusei(1985, 6)
        assert a.size == (300, 400)
        assert _px(a) == _px(b)

    def test_kyusei_highlight_varies(self):
        a = chartdraw.render_kyusei(1985, 6)   # 六白金星＝北西（下段右）
        b = chartdraw.render_kyusei(1990, 1)   # 一白水星＝北（下段中央）
        assert _px(a) != _px(b)
        # 本命セル（下段右）中心は強調により両者で異なる
        ca = a.getpixel((234, 248))
        cb = b.getpixel((234, 248))
        assert ca != cb

    def test_numerology_with_and_without_name(self):
        d = dt.date(1985, 7, 15)
        a = chartdraw.render_numerology(9, d, 7, "Takahashi Ren")
        b = chartdraw.render_numerology(9, d)
        assert a.size == (300, 400) and b.size == (300, 400)
        assert _px(a) != _px(b)

    def test_kabbalah_highlight_varies(self):
        a = chartdraw.render_kabbalah(5, "Takahashi Ren")
        b = chartdraw.render_kabbalah(2, "Suzuki Hana")
        assert _px(a) != _px(b)

    def test_webp_budget(self):
        buf = io.BytesIO()
        chartdraw.render_kyusei(1985, 6).save(buf, "WEBP", quality=chartdraw.WEBP_Q)
        assert buf.tell() <= 45 * 1024

    def test_font_resolved(self):
        assert chartdraw.font_source() != ""


class TestRenderForSlug(_ChartdrawTestCase):
    def test_kyusei(self):
        img, cap = chartdraw.render_for_slug(
            "M03_kyusei", {"year": 1985, "honmei_no": 6, "honmei": "六白金星"})
        assert img is not None
        assert "六白金星" in cap and "1985" in cap

    def test_numerology(self):
        img, cap = chartdraw.render_for_slug(
            "M04_numerology_birth", {"life_path": 9, "date": "1985-07-15"},
            {"number": 7, "romaji": "Takahashi Ren"})
        assert img is not None and "運命数9" in cap

    def test_kabbalah(self):
        img, cap = chartdraw.render_for_slug(
            "M06_kabbalah", {"romaji": "Takahashi Ren", "number": 5})
        assert img is not None and "TAKAHASHI REN" in cap and "5" in cap

    def test_invalid(self):
        cases = [
            ("M03_kyusei", {"year": 1985}),                  # honmei_no 欠落
            ("M03_kyusei", {"year": 1985, "honmei_no": 12}),  # 範囲外
            ("M04_numerology_birth", {"life_path": 9}),      # date 欠落
            ("M06_kabbalah", {"number": 5}),                 # romaji 欠落
            ("M99_unknown", {}),
        ]
        for slug, calc in cases:
            with self.subTest(slug=slug):
                img, cap = chartdraw.render_for_slug(slug, calc)
                self.assertIsNone(img)
                self.assertEqual(cap, "")


class TestTypecTag(_ChartdrawTestCase):
    def _person(self, tmp_path: Path, slug: str, calc: dict, extra=None) -> Path:
        """person ディレクトリの下準備（tmp_path は self.tmp() の戻り値）"""
        rd = tmp_path / "person" / "results"
        rd.mkdir(parents=True, exist_ok=True)
        (rd / f"{slug}_raw.json").write_text(json.dumps(
            {"result": {"calc": calc}}), encoding="utf-8")
        if extra:
            (rd / "M04_numerology_name_raw.json").write_text(json.dumps(
                {"result": {"calc": extra}}), encoding="utf-8")
        return tmp_path / "person"

    def test_tag_with_assets(self):
        tmp_path = self.tmp()
        person = self._person(tmp_path, "M03_kyusei",
                              {"year": 1990, "honmei_no": 1, "honmei": "一白水星"})
        assets = tmp_path / "assets"
        (assets / "M03_kyusei").mkdir(parents=True)
        src = Path(chartdraw.__file__).resolve().parents[1] / \
            "assets" / "images" / "M03_kyusei" / "kyusei_base.webp"
        (assets / "M03_kyusei" / "kyusei_base.webp").write_bytes(src.read_bytes())
        tag = chartdraw.typec_tag("M03_kyusei", person, assets)
        assert "fortune-image-container" in tag
        assert "data:image/webp;base64," in tag
        assert "一白水星" in tag

    def test_tag_without_base_is_empty(self):
        tmp_path = self.tmp()
        person = self._person(tmp_path, "M03_kyusei",
                              {"year": 1990, "honmei_no": 1, "honmei": "一白水星"})
        with mock.patch.object(chartdraw, "_PKG_ROOT", tmp_path / "nonexistent"):
            self.assertEqual(
                chartdraw.typec_tag("M03_kyusei", person, tmp_path / "assets"), "")

    def test_tag_without_raw_is_empty(self):
        tmp_path = self.tmp()
        self.assertEqual(
            chartdraw.typec_tag("M03_kyusei", tmp_path / "noperson", None), "")

    def test_numerology_uses_name_extra(self):
        tmp_path = self.tmp()
        person = self._person(
            tmp_path, "M04_numerology_birth",
            {"life_path": 9, "date": "1985-07-15"},
            extra={"number": 7, "romaji": "Takahashi Ren"})
        tag = chartdraw.typec_tag("M04_numerology_birth", person, None)
        assert tag and "【数秘術】運命数9" in tag
        # 氏名数の有無で描画が変わる（氏名メダリオン3個 vs 2個）
        (person / "results" / "M04_numerology_name_raw.json").unlink()
        tag2 = chartdraw.typec_tag("M04_numerology_birth", person, None)
        assert tag2 and tag != tag2


class TestBatch1Renders(_ChartdrawTestCase):
    """mts5.17 型Cバッチ1（7件）: 描画とキャプション（承認サンプル準拠）。"""

    CASES = [
        ("M05_numerology_name", {"number": 8, "romaji": "Hanako Yamada"},
         "【数秘術（氏名）】氏名数8（HANAKO YAMADA）"),
        ("M07_chaldean", {"number": 5, "romaji": "Ken Sato"},
         "【カルデア数秘術】カルデア数5（KEN SATO）"),
        ("M04_tantra", {"number": 9}, "【タントラ数秘術】タントラ数9"),
        ("M04_anka", {"number": 3}, "【アンカ・シャーストラ】アンカ数3・支配星：木星"),
        ("M10_rokusei", {"type": "金星人プラス", "cycle": "大殺界", "target_year": 2026},
         "【六星占術】金星人プラス／年運：大殺界（2026）"),
        ("M14_weton", {"weton_name": "月曜・Pon", "pasaran": "Pon"},
         "【ウェトン】月曜・Pon"),
        ("M13_primbon", {"weton": "月曜・Pon", "neptu_total": 12},
         "【プリンボン・ジャワ】月曜・Pon／ネプトゥ12"),
    ]

    def test_renders_and_captions(self):
        for slug, calc, cap in self.CASES:
            img, got = chartdraw.render_for_slug(slug, calc)
            assert img is not None and got == cap, slug
            assert img.size == (300, 400), slug

    def test_webp_budget(self):
        for slug, calc, _cap in self.CASES:
            img, _ = chartdraw.render_for_slug(slug, calc)
            buf = io.BytesIO()
            img.save(buf, "WEBP", quality=chartdraw.WEBP_Q)
            assert buf.tell() <= 45 * 1024, slug

    def test_typec_slugs(self):
        # パイロット3＋バッチ1・7＋バッチ2・5＋西洋系4＋B残3＝22
        assert len(chartdraw.TYPEC_SLUGS) == 22
        for slug, _calc, _cap in self.CASES:
            assert slug in chartdraw.TYPEC_SLUGS
        for slug in ("M16_seimei", "M17_bazi", "M19_vedic",
                     "M21_sanmei", "M24_qimen",
                     "M18_western", "M18_natal", "M18_transit", "M18_synastry",
                     "M20_ziwei", "M25_hd", "M15_parimicham"):
            assert slug in chartdraw.TYPEC_SLUGS

    def test_invalid(self):
        cases = [
            ("M05_numerology_name", {"number": 7}),      # romaji 欠落
            ("M07_chaldean", {"romaji": "X Y"}),         # number 欠落
            ("M04_tantra", {}),
            ("M04_anka", {}),
            ("M10_rokusei", {"type": "土星人マイナス"}),  # cycle 欠落
            ("M14_weton", {"pasaran": "Pon"}),           # weton_name 欠落
            ("M13_primbon", {"weton": "月曜・Pon"}),     # neptu 欠落
        ]
        for slug, calc in cases:
            img, cap = chartdraw.render_for_slug(slug, calc)
            assert img is None and cap == "", slug


class TestBatch2Renders(_ChartdrawTestCase):
    """mts5.18 型Cバッチ2（5件）: 描画とキャプション（承認サンプル準拠）。"""

    def _calcs(self):
        from fortunelib.calc.bazi import bazi_paipan
        from fortunelib.calc.astrology import vedic_sidereal, to_jd
        from fortunelib.calc.sanmeigaku import sanmeigaku_full
        from fortunelib.calc.qimen import qimen_pan
        from fortunelib.calc.seimei import seimei_calc
        return {
            "M17_bazi": bazi_paipan(1978, 7, 7, 12, 0, lon_east=139.7,
                                    apply_true_solar=True),
            "M19_vedic": vedic_sidereal(to_jd(1978, 7, 7, 12.0)),
            "M21_sanmei": {"status": "ok", **sanmeigaku_full(1978, 7, 7)},
            "M24_qimen": qimen_pan(2026, 9, 26, 9, 0),
            "M16_seimei": seimei_calc("高", "橋連"),
        }

    def test_renders_and_captions(self):
        expect = {
            "M17_bazi": "【四柱推命】年柱戊午／月柱己未／日柱庚午／時柱壬午・日主：庚（金・陽）",
            "M19_vedic": "【ヴェーダ占星術】月：蟹座・プシュヤ（パダ2）",
            "M21_sanmei": "【算命学】中心星：牽牛星／総エネルギー21",
            "M24_qimen": "【奇門遁甲】陰遁一局中元／値使：死門・坤宮",
            "M16_seimei": "【姓名判断】五格 天11・人26・地27・外12・総36",
        }
        for slug, calc in self._calcs().items():
            img, cap = chartdraw.render_for_slug(slug, calc)
            assert img is not None and cap == expect[slug], (slug, cap)
            assert img.size == (300, 400), slug

    def test_webp_budget(self):
        for slug, calc in self._calcs().items():
            img, _ = chartdraw.render_for_slug(slug, calc)
            buf = io.BytesIO()
            img.save(buf, "WEBP", quality=chartdraw.WEBP_Q)
            assert buf.tell() <= 45 * 1024, slug

    def test_invalid(self):
        cases = [
            ("M16_seimei", {}),                       # five_grilles 欠落
            ("M17_bazi", {"day_master": {"gan": "庚"}}),  # pillars 欠落
            ("M19_vedic", {"planets": {}}),           # 月欠落
            ("M21_sanmei", {"status": "ok"}),         # 中心星欠落
            ("M24_qimen", {"paiju": "陰遁一局"}),     # men 欠落
        ]
        for slug, calc in cases:
            img, cap = chartdraw.render_for_slug(slug, calc)
            assert img is None and cap == "", slug


class TestAstroRenders(_ChartdrawTestCase):
    """mts5.19 西洋占星術系（4件）: 描画とキャプション。"""

    @staticmethod
    def _charts():
        from fortunelib.calc.astrology import natal_chart, transit_chart
        mine = natal_chart(1978, 7, 7, 12.0, 35.7, 139.7)
        theirs = natal_chart(1980, 1, 15, 10.0, 35.7, 139.7)
        return mine, theirs, transit_chart(mine)

    def test_renders_and_captions(self):
        mine, theirs, tr = self._charts()
        img, cap = chartdraw.render_for_slug("M18_western", mine)
        assert img is not None and cap.startswith("【西洋占星術】太陽：")
        img, cap = chartdraw.render_for_slug("M18_natal", mine)
        assert img is not None and cap.startswith("【ネイタル占星術】太陽：")
        img, cap = chartdraw.render_for_slug("M18_transit", tr, mine)
        assert img is not None and cap.startswith("【トランジット】太陽：")
        syn = {"aspects": [], "mine": mine, "theirs": theirs}
        img, cap = chartdraw.render_for_slug("M18_synastry", syn)
        assert img is not None and cap.startswith("【シナストリー】アスペクト")

    def test_webp_budget(self):
        mine, theirs, tr = self._charts()
        cases = [("M18_western", mine, None), ("M18_natal", mine, None),
                 ("M18_transit", tr, mine),
                 ("M18_synastry", {"aspects": [], "mine": mine,
                                   "theirs": theirs}, None)]
        for slug, calc, extra in cases:
            img, _ = chartdraw.render_for_slug(slug, calc, extra)
            buf = io.BytesIO()
            img.save(buf, "WEBP", quality=chartdraw.WEBP_Q)
            assert buf.tell() <= 45 * 1024, slug

    def test_invalid(self):
        for slug, calc in [("M18_western", {}), ("M18_natal", {"planets": {}}),
                           ("M18_transit", {}), ("M18_synastry", {}),
                           ("M18_synastry", {"error": "相手情報なし"})]:
            img, cap = chartdraw.render_for_slug(slug, calc)
            assert img is None and cap == "", slug


class TestBRestRenders(_ChartdrawTestCase):
    """mts5.20 B群残（3件）: 描画とキャプション。"""

    @staticmethod
    def _calcs():
        from fortunelib.calc.ziwei import ziwei_chart
        from fortunelib.calc.hd_full import calculate_chart
        from fortunelib.calc.parimicham import parimicham_calc
        p = parimicham_calc({"date": "1978-07-07"}, {"date": "1980-01-15"},
                            role1="本人", role2="相手")
        p["status"] = "ok"
        return {"M20_ziwei": ziwei_chart(1978, 7, 7, 12, gender="male"),
                "M25_hd": calculate_chart(1978, 7, 7, 12, 0, 9.0),
                "M15_parimicham": p}

    def test_renders_and_captions(self):
        expect = {
            "M20_ziwei": "【紫微斗数】金の四局・命宮：命宮／身宮：命宮",
            "M25_hd": "【ヒューマンデザイン】ジェネレーター・権威：仙骨・6/2",
            "M15_parimicham": "【パリミチャム】5.0/8.0・Good（良い相性）",
        }
        for slug, calc in self._calcs().items():
            img, cap = chartdraw.render_for_slug(slug, calc)
            assert img is not None and cap == expect[slug], (slug, cap)
            assert img.size == (300, 400), slug

    def test_webp_budget(self):
        for slug, calc in self._calcs().items():
            img, _ = chartdraw.render_for_slug(slug, calc)
            buf = io.BytesIO()
            img.save(buf, "WEBP", quality=chartdraw.WEBP_Q)
            assert buf.tell() <= 45 * 1024, slug

    def test_invalid(self):
        for slug, calc in [("M20_ziwei", {}), ("M25_hd", {}),
                           ("M15_parimicham", {}),
                           ("M15_parimicham", {"status": "unavailable"})]:
            img, cap = chartdraw.render_for_slug(slug, calc)
            assert img is None and cap == "", slug
