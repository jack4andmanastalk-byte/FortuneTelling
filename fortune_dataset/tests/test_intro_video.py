# -*- coding: utf-8 -*-
"""mts5.69（2026-10-14・ユーザー決定）: 冒頭動画カード（同梱の固定動画・目次の直前）の回帰テスト。

決定事項:
  Q1 同梱の固定動画（assets/video/intro_video.json が正本）＋ Cell N2 の ON/OFF フラグ `EMBED_INTRO_VIDEO`
  Q2 再生は二段構え（data URI を 1 部だけ持ち、JS が Blob に変換して再生。JS 無効時は data URI）
  Q3 文言は試作どおり（見出し「お祓い（Purification）の動画」／注記／「大きなサイズの動画は
     オンラインからも視聴できます（YouTube）」＋ URL）
  Q4 配布は Kaggle 用 ZIP のみ同梱（引き継ぎ用 ZIP は MP4 を除外・設定とサムネイルは同梱）

テストは**同梱の MP4 が無い環境（引き継ぎ用 ZIP だけ）でも通る**ように、箱構造だけの
小さな偽 MP4 を作って使う。実物を使う検査は MP4 が無ければ skip。
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path

from fortunelib import html_report as H
from fortunelib import intro_video as IV
from fortunelib import notebook_guard as G

ROOT = Path(__file__).resolve().parent.parent          # fortune_dataset/fortune_dataset
REPO = ROOT.parent                                      # リポジトリ直下（verify/・tools/）
KG = ROOT / "kaggle"
VIDEO_DIR = ROOT / "assets" / "video"
YT = "https://www.youtube.com/watch?v=rnxxef4Jq8I"

_SPEC = importlib.util.spec_from_file_location(
    "verify_run_output", REPO / "verify" / "verify_run_output.py")
vro = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(vro)


# ---------------------------------------------------------------
# 偽 MP4（箱構造だけ・再生はできない）と人物フォルダ
# ---------------------------------------------------------------
def _box(typ: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), typ) + payload


def fake_mp4(seconds: float = 12.5, w: int = 320, h: int = 240, timescale: int = 600,
             payload: int = 2048) -> bytes:
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2avc1mp41")
    mvhd = _box(b"mvhd", bytes(4) + bytes(8) + struct.pack(">II", timescale, int(seconds * timescale))
                + bytes(80))
    audio = _box(b"trak", _box(b"tkhd", bytes(4) + bytes(72) + struct.pack(">II", 0, 0)))
    video = _box(b"trak", _box(b"tkhd", bytes(4) + bytes(72) + struct.pack(">II", w << 16, h << 16)))
    moov = _box(b"moov", mvhd + audio + video)
    mdat = _box(b"mdat", os.urandom(payload))
    return ftyp + moov + mdat


def make_assets(root: Path, *, sha: str | None = "auto", with_file: bool = True,
                with_poster: bool = True, extra: dict | None = None) -> tuple[Path, bytes]:
    """assets/images と assets/video を作る。戻り値 (assets/images, mp4 bytes)。"""
    images = root / "assets" / "images"
    (images / "M27_tarot").mkdir(parents=True, exist_ok=True)
    vdir = root / "assets" / "video"
    vdir.mkdir(parents=True, exist_ok=True)
    raw = fake_mp4()
    if with_file:
        (vdir / "clip.mp4").write_bytes(raw)
    if with_poster:
        (vdir / "clip.webp").write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 " + bytes(16))
    cfg = {"file": "clip.mp4", "poster": "clip.webp" if with_poster else "",
           "title": "お祓い（Purification）の動画",
           "note": "鑑定の前後にご覧いただく動画です。このファイル1枚で再生できます（自動再生はしません）。",
           "online_url": YT, "online_prefix": "大きなサイズの動画は ",
           "online_label": IV.ONLINE_LABEL, "online_suffix": "（YouTube）"}
    if sha == "auto":
        cfg["sha256"] = hashlib.sha256(raw).hexdigest()
    elif sha:
        cfg["sha256"] = sha
    if extra:
        cfg.update(extra)
    (vdir / IV.CONFIG_NAME).write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return images, raw


SYN_MD = (
    "# 統合鑑定レポート\n\n"
    "## ご相談\n\nテストの相談内容です。\n\n"
    "## 総合所見\n\n本文です。\n\n"
    "---\n※ 本レポートはエンターテインメント目的のシミュレーションであり、事実を表すものではありません。\n"
)


def make_person(d: Path) -> None:
    (d / "results").mkdir(parents=True, exist_ok=True)
    (d / "synthesis_report.md").write_text(SYN_MD, encoding="utf-8")
    (d / "results" / "M01_tool1.md").write_text(
        "# 占術1\n\n## ■ 使用した入力\n- 相談内容：テスト\n\n## ■ 鑑定文\n\n本文。\n", encoding="utf-8")


# ===============================================================
# 1. MP4 プローブ・置き場・設定
# ===============================================================
class TestProbeAndConfig(unittest.TestCase):
    def test_probe_reads_duration_and_size_from_boxes(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.mp4"
            p.write_bytes(fake_mp4(seconds=12.5, w=640, h=360))
            got = IV.probe_mp4(p)
        self.assertEqual(got, {"seconds": 12.5, "width": 640, "height": 360})

    def test_probe_is_silent_on_garbage(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.mp4"
            p.write_bytes(b"not an mp4 at all")
            self.assertEqual(IV.probe_mp4(p), {})
        self.assertEqual(IV.probe_mp4(Path("/nonexistent/x.mp4")), {})

    def test_find_video_dir_from_images_assets_video_and_pkg_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            images, _ = make_assets(root)
            vdir = root / "assets" / "video"
            self.assertEqual(IV.find_video_dir(images), vdir)            # assets/images
            self.assertEqual(IV.find_video_dir(root / "assets"), vdir)   # assets
            self.assertEqual(IV.find_video_dir(vdir), vdir)              # video 自身
            self.assertEqual(IV.find_video_dir(root), vdir)              # pkg ルート
            self.assertEqual(IV.find_video_dir(images / "M27_tarot"), None)
        self.assertIsNone(IV.find_video_dir(None))

    def test_load_config_rejects_broken_or_fileless_json(self):
        with tempfile.TemporaryDirectory() as td:
            vdir = Path(td)
            (vdir / IV.CONFIG_NAME).write_text("{broken", encoding="utf-8")
            self.assertIsNone(IV.load_config(vdir))
            (vdir / IV.CONFIG_NAME).write_text('{"title": "x"}', encoding="utf-8")
            self.assertIsNone(IV.load_config(vdir))
            (vdir / IV.CONFIG_NAME).write_text('{"file": "a.mp4"}', encoding="utf-8")
            self.assertEqual(IV.load_config(vdir)["file"], "a.mp4")


# ===============================================================
# 2. カード HTML
# ===============================================================
class TestCardHtml(unittest.TestCase):
    def _card(self, **extra):
        with tempfile.TemporaryDirectory() as td:
            images, raw = make_assets(Path(td), extra=extra or None)
            html, info = IV.load_intro_video_card(images)
        return html, info, raw

    def test_card_structure_and_single_data_uri(self):
        html, info, raw = self._card()
        self.assertEqual(info["reason"], "ok")
        self.assertTrue(html.startswith(f'<section id="{IV.CARD_ID}" class="card hl-card iv-card">'))
        self.assertIn("<h2>🎬 お祓い（Purification）の動画</h2>", html)
        self.assertIn('<p class="hl-note">鑑定の前後にご覧いただく動画です。', html)
        self.assertIn(f'<video id="{IV.PLAYER_ID}" class="hl-video" controls playsinline '
                      'preload="metadata" poster="data:image/webp;base64,', html)
        self.assertNotIn(" autoplay", html)
        self.assertEqual(html.count("data:video/mp4;base64,"), 1, "data URI は 1 部だけ")
        b64 = base64.b64encode(raw).decode("ascii")
        self.assertIn(f'<source src="data:video/mp4;base64,{b64}" type="video/mp4">', html)
        self.assertIn(f"<script>{IV.PLAYER_JS}</script>", html)
        self.assertIn("約12秒・", html)
        self.assertIn("（320×240 の軽量版）", html)

    def test_player_js_is_two_stage(self):
        js = IV.PLAYER_JS
        for needle in ("atob(", "new Blob(", "srcObject", "URL.createObjectURL(",
                       "createElement('source')", "replaceChild(", "v.load()",
                       "data-iv-mode"):
            self.assertIn(needle, js)
        self.assertTrue(js.isascii(), "JS は ASCII のみ（文字化け・エスケープ事故を避ける）")

    def test_online_line_has_label_url_and_new_tab(self):
        html, _, _ = self._card()
        self.assertIn('<p class="iv-online">大きなサイズの動画は '
                      f'<a href="{YT}" target="_blank" rel="noopener noreferrer">'
                      f'{IV.ONLINE_LABEL}</a>（YouTube）<br>'
                      f'<span class="iv-url">{YT}</span></p>', html)
        self.assertNotIn("<iframe", html, "オフライン HTML なので iframe は使わない")

    def test_texts_are_escaped_and_defaults_apply(self):
        html, _, _ = self._card(title="<b>x</b> & y", note="", online_url="https://e.com/?a=1&b=2")
        self.assertIn("<h2>🎬 &lt;b&gt;x&lt;/b&gt; &amp; y</h2>", html)
        self.assertIn(IV.DEFAULT_NOTE, html)
        self.assertIn('href="https://e.com/?a=1&amp;b=2"', html)

    def test_no_online_url_means_no_online_line(self):
        html, _, _ = self._card(online_url="")
        self.assertNotIn("iv-online", html)
        self.assertNotIn(IV.ONLINE_LABEL, html)

    def test_no_poster_means_no_poster_attribute(self):
        with tempfile.TemporaryDirectory() as td:
            images, _ = make_assets(Path(td), with_poster=False)
            html, info = IV.load_intro_video_card(images)
        self.assertNotIn(" poster=", html)
        self.assertFalse(info["poster"])


# ===============================================================
# 3. 読み込み（理由コード・SHA 突合）と埋め込み後の復号
# ===============================================================
class TestLoader(unittest.TestCase):
    def test_reasons(self):
        self.assertEqual(IV.load_intro_video_card("/x", enabled=False), ("", {"reason": "disabled"}))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            html, info = IV.load_intro_video_card(root)
            self.assertEqual((html, info["reason"]), ("", "no_config"))
            images, _ = make_assets(root, with_file=False)
            html, info = IV.load_intro_video_card(images)
            self.assertEqual((html, info["reason"], info["file"]), ("", "no_file", "clip.mp4"))
            (root / "assets" / "video" / IV.CONFIG_NAME).write_text("{]", encoding="utf-8")
            html, info = IV.load_intro_video_card(images)
            self.assertEqual((html, info["reason"]), ("", "bad_config"))

    def test_sha_match_flag(self):
        with tempfile.TemporaryDirectory() as td:
            images, raw = make_assets(Path(td))
            _, info = IV.load_intro_video_card(images)
            self.assertTrue(info["sha_match"])
            self.assertEqual(info["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(info["size_bytes"], len(raw))
        with tempfile.TemporaryDirectory() as td:
            images, _ = make_assets(Path(td), sha="0" * 64)
            _, info = IV.load_intro_video_card(images)
            self.assertIs(info["sha_match"], False)
        with tempfile.TemporaryDirectory() as td:
            images, _ = make_assets(Path(td), sha=None)
            _, info = IV.load_intro_video_card(images)
            self.assertIsNone(info["sha_match"])

    def test_embedded_digest_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            images, raw = make_assets(Path(td))
            card, _ = IV.load_intro_video_card(images)
        doc = "<body>" + card + '<nav class="toc"><ol></ol></nav></body>'
        d = IV.embedded_video_digest(doc)
        self.assertEqual(d["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(d["bytes"], len(raw))
        self.assertTrue(d["before_toc"])
        self.assertEqual(d["copies"], 1)
        self.assertTrue(d["online_label"])
        self.assertEqual(d["online_url"], YT)
        self.assertTrue(d["script"])
        self.assertTrue(d["poster"])
        self.assertFalse(d["autoplay"])
        self.assertIsNone(IV.embedded_video_digest("<body><nav class=\"toc\"></nav></body>"))


# ===============================================================
# 4. build_html への組み込み（目次の直前・CSS・画像集計から除外）
# ===============================================================
class TestBuildHtml(unittest.TestCase):
    def test_card_sits_right_before_toc_and_css_added(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            images, raw = make_assets(root)
            pd = root / "demo_person"
            make_person(pd)
            card, _ = IV.load_intro_video_card(images)
            out = H.build_html(pd, person_id="demo_person", images_dir=None, intro_video_html=card)
            html = out.read_text(encoding="utf-8")
        i_wrap = html.find('<div class="wrap">')
        i_card = html.find(f'id="{IV.CARD_ID}"')
        i_toc = html.find('<nav class="toc">')
        self.assertTrue(0 < i_wrap < i_card < i_toc, (i_wrap, i_card, i_toc))
        between = html[html.find("</section>", i_card) + len("</section>"):i_toc]
        self.assertEqual(between.strip(), "", "カードと目次の間に他の要素を挟まない")
        self.assertIn(".hl-card{", html)
        self.assertIn(".iv-online{", html)
        self.assertEqual(IV.embedded_video_digest(html)["sha256"], hashlib.sha256(raw).hexdigest())
        # サムネイル（data:image）は占術画像の集計に入れない
        self.assertEqual(html.count("data:image"), 1)
        self.assertEqual(H.IMAGE_AUDIT["images"], 0)

    def test_default_is_unchanged_html(self):
        with tempfile.TemporaryDirectory() as td:
            pd = Path(td) / "p"
            make_person(pd)
            html = H.build_html(pd, person_id="p").read_text(encoding="utf-8")
        self.assertNotIn(IV.CARD_ID, html)
        self.assertNotIn(".iv-online{", html)
        self.assertNotIn(".hl-card{", html)
        self.assertEqual(H._video_css(""), "")

    def test_card_css_is_self_contained(self):
        """カードの CSS は intro_video モジュールだけで完結する（共通部＋専用部）。"""
        css = H._video_css("<section class=\"card hl-card iv-card\"></section>")
        for sel in (".hl-card{", ".hl-note{", ".hl-video{", ".hl-meta{", ".iv-online{"):
            self.assertIn(sel, css)
        self.assertEqual(css, IV.CARD_CSS + IV.INTRO_CSS)
        import inspect
        self.assertNotIn("video_html", inspect.signature(H.build_html).parameters)
        self.assertIn("intro_video_html", inspect.signature(H.build_html).parameters)
        self.assertIn(".iv-online", css)


# ===============================================================
# 5. 検証器（verify/verify_run_output.py）
# ===============================================================
class TestVerifier(unittest.TestCase):
    def _doc(self, root: Path, *, mutate=None) -> tuple[str, Path]:
        images, raw = make_assets(root)
        card, _ = IV.load_intro_video_card(images)
        doc = "<html><body>" + card + '<nav class="toc"><ol></ol></nav></body></html>'
        if mutate:
            doc = mutate(doc)
        return doc, images

    def test_clean_card_has_no_findings(self):
        with tempfile.TemporaryDirectory() as td:
            doc, images = self._doc(Path(td))
            rep = vro.verify_intro_video(doc, images)
        self.assertTrue(rep["present"])
        self.assertEqual(rep["problems"], [])
        self.assertEqual(rep["warnings"], [])
        self.assertEqual(rep["sha_state"], "一致")
        self.assertIn("冒頭動画   : 有（", rep["line"])
        self.assertIn("SHA 一致（原本 clip.mp4）", rep["line"])
        self.assertIn("目次の前", rep["line"])

    def test_tampered_video_is_detected(self):
        def _mut(doc):
            i = doc.find("data:video/mp4;base64,") + len("data:video/mp4;base64,")
            return doc[:i] + base64.b64encode(b"tampered-bytes-" * 8).decode() + doc[doc.find('"', i):]
        with tempfile.TemporaryDirectory() as td:
            doc, images = self._doc(Path(td), mutate=_mut)
            rep = vro.verify_intro_video(doc, images)
        self.assertEqual(rep["sha_state"], "不一致")
        self.assertTrue(any("SHA-256" in p["detail"] for p in rep["problems"]))

    def test_card_after_toc_and_missing_label_are_problems(self):
        def _mut(doc):
            card = doc[doc.find("<section"):doc.find("</section>") + len("</section>")]
            doc = doc.replace(card, "").replace("</body>", card + "</body>")
            return doc.replace(IV.ONLINE_LABEL, "別の文言")
        with tempfile.TemporaryDirectory() as td:
            doc, images = self._doc(Path(td), mutate=_mut)
            rep = vro.verify_intro_video(doc, images)
        details = " / ".join(p["detail"] for p in rep["problems"])
        self.assertIn("目次（nav.toc）の前にありません", details)
        self.assertIn(IV.ONLINE_LABEL, details)

    def test_duplicate_data_uri_and_autoplay_are_problems(self):
        def _mut(doc):
            doc = doc.replace("controls playsinline", "controls autoplay playsinline", 1)
            return doc + '<video><source src="data:video/mp4;base64,AAAA" type="video/mp4"></video>'
        with tempfile.TemporaryDirectory() as td:
            doc, images = self._doc(Path(td), mutate=_mut)
            rep = vro.verify_intro_video(doc, images)
        details = " / ".join(p["detail"] for p in rep["problems"])
        self.assertIn("2 部あります", details)
        self.assertIn("autoplay", details)

    def test_missing_card_is_warning_only_when_dataset_has_the_video(self):
        doc = '<html><body><nav class="toc"></nav></body></html>'
        with tempfile.TemporaryDirectory() as td:
            images, _ = make_assets(Path(td))
            rep = vro.verify_intro_video(doc, images)
            self.assertFalse(rep["present"])
            self.assertEqual(rep["problems"], [])
            self.assertEqual(len(rep["warnings"]), 1)
            self.assertIn("EMBED_INTRO_VIDEO=False", rep["warnings"][0]["detail"])
        with tempfile.TemporaryDirectory() as td:
            rep = vro.verify_intro_video(doc, Path(td) / "assets" / "images")
        self.assertEqual((rep["problems"], rep["warnings"]), ([], []))
        self.assertIn("同梱なし", rep["line"])

    def test_verifier_rules_match_product_rules(self):
        self.assertEqual(vro.INTRO_CARD_ID, IV.CARD_ID)
        self.assertEqual(vro.INTRO_ONLINE_LABEL, IV.ONLINE_LABEL)
        self.assertEqual(vro._INTRO_B64.pattern, IV._B64_RE.pattern)
        self.assertIn("intro_video", vro._json_payload.__code__.co_consts)


# ===============================================================
# 6. Notebook（Cell N2 のフラグ・版チェックの許容差分）
# ===============================================================
class TestNotebookFlag(unittest.TestCase):
    def setUp(self):
        self.src = (KG / "cellN2_synthesis.py").read_text(encoding="utf-8")

    def test_cell_n2_has_the_flag_and_passes_the_card(self):
        self.assertIn("EMBED_INTRO_VIDEO = True", self.src)
        self.assertIn("if EMBED_INTRO_VIDEO:", self.src)
        self.assertIn("load_intro_video_card", self.src)
        self.assertIn("intro_video_html=_intro_html", self.src)
        self.assertIn("冒頭動画カードはOFF", self.src)
        self.assertIn("冒頭動画カードを埋め込めませんでした", self.src)
        self.assertIn('- _intro_html.count("data:image")', self.src)

    def test_guard_tolerates_only_the_boolean_flip(self):
        name = "cellN2_synthesis.py"
        base = G._normalized_cell_source(name, self.src)
        off = self.src.replace("EMBED_INTRO_VIDEO = True", "EMBED_INTRO_VIDEO = False", 1)
        self.assertNotEqual(off, self.src)
        self.assertEqual(G._normalized_cell_source(name, off), base)
        non_bool = self.src.replace("EMBED_INTRO_VIDEO = True", "EMBED_INTRO_VIDEO = 1", 1)
        self.assertNotEqual(G._normalized_cell_source(name, non_bool), base)
        other = self.src.replace("MAKE_HTML = True", "MAKE_HTML = False", 1)
        self.assertNotEqual(G._normalized_cell_source(name, other), base)
        self.assertEqual(G._normalized_cell_source("cell0_bootstrap.py", "EMBED_INTRO_VIDEO = True"),
                         "EMBED_INTRO_VIDEO = True", "許容は Cell N2 だけ")
        self.assertEqual(G._ALLOWED_SETTINGS, ("EMBED_INTRO_VIDEO",))

    def test_running_notebook_with_flag_off_is_not_stale(self):
        nb_path = KG / "fortune_notebook.ipynb"
        nb = json.loads(nb_path.read_text(encoding="utf-8"))
        hit = False
        for c in nb["cells"]:
            if c["cell_type"] != "code":
                continue
            src = "".join(c["source"])
            if "EMBED_INTRO_VIDEO = True" in src:
                c["source"] = src.replace("EMBED_INTRO_VIDEO = True",
                                          "EMBED_INTRO_VIDEO = False", 1).splitlines(keepends=True)
                hit = True
                break
        self.assertTrue(hit, "Notebook の Cell N2 に EMBED_INTRO_VIDEO = True がありません（build_notebook.py を実行）")
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / "__notebook__.ipynb"
            fake.write_text(json.dumps(nb, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(G.stale_cells(ROOT, fake), [])

    def test_notebook_markdown_mentions_the_flag(self):
        src = (KG / "build_notebook.py").read_text(encoding="utf-8")
        self.assertIn("EMBED_INTRO_VIDEO", src)


# ===============================================================
# 7. 配布（ZIP ビルダー）と同梱物
# ===============================================================
class TestDistribution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("build_dataset_zip",
                                                      REPO / "tools" / "build_dataset_zip.py")
        cls.bz = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.bz)

    def test_video_is_kaggle_only(self):
        self.assertIn(".mp4", self.bz.VIDEO_SUFFIX)
        rel = lambda files: {str(p.relative_to(self.bz.PKG)) for p in files}
        without = rel(self.bz.iter_files(images="exclude"))
        self.assertIn("fortune_dataset/assets/video/intro_video.json", without)
        self.assertIn("fortune_dataset/assets/video/Purification_Mini_poster.webp", without)
        self.assertFalse(any(p.endswith(".mp4") for p in without), "引き継ぎ用に MP4 を入れない")
        if (VIDEO_DIR / "Purification_Mini.mp4").is_file():
            with_images = rel(self.bz.iter_files(images="include"))
            self.assertIn("fortune_dataset/assets/video/Purification_Mini.mp4", with_images)
        only = rel(self.bz.iter_files(images="only"))
        self.assertFalse(any("/video/" in p for p in only), "画像だけの ZIP には動画を入れない")

    def test_bundled_config_is_consistent(self):
        cfg = json.loads((VIDEO_DIR / IV.CONFIG_NAME).read_text(encoding="utf-8"))
        self.assertEqual(cfg["file"], "Purification_Mini.mp4")
        self.assertEqual(cfg["online_url"], YT)
        self.assertEqual(cfg["online_label"], IV.ONLINE_LABEL)
        self.assertEqual(cfg["title"], "お祓い（Purification）の動画")
        self.assertEqual(cfg["sha256"], "a4b373f35acca9fa071fc4c50863f4048d5afe47d0b2b2d846e4d84c00d15985")
        self.assertEqual(cfg["size_bytes"], 7397866)
        poster = VIDEO_DIR / cfg["poster"]
        self.assertTrue(poster.is_file())
        self.assertEqual(hashlib.sha256(poster.read_bytes()).hexdigest(), cfg["poster_sha256"])
        self.assertLess(poster.stat().st_size, 20_000, "サムネイルは軽く保つ")

    def test_bundled_video_matches_config(self):
        mp4 = VIDEO_DIR / "Purification_Mini.mp4"
        if not mp4.is_file():
            self.skipTest("同梱 MP4 が無い環境（引き継ぎ用 ZIP のみ）")
        cfg = json.loads((VIDEO_DIR / IV.CONFIG_NAME).read_text(encoding="utf-8"))
        self.assertEqual(mp4.stat().st_size, cfg["size_bytes"])
        self.assertEqual(IV.sha256_of(mp4), cfg["sha256"])
        probe = IV.probe_mp4(mp4)
        self.assertEqual((probe["width"], probe["height"]), (320, 240))
        self.assertAlmostEqual(probe["seconds"], 239.27, places=1)
        card, info = IV.load_intro_video_card(ROOT / "assets" / "images")
        self.assertEqual(info["reason"], "ok")
        self.assertTrue(info["sha_match"])
        self.assertEqual(IV.embedded_video_digest(card + '<nav class="toc">')["sha256"], cfg["sha256"])
        self.assertGreater(len(card), 9_800_000)                       # base64 ≈ +33%
        self.assertLess(len(card), 10_200_000)


if __name__ == "__main__":
    unittest.main()
