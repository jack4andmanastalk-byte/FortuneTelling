# -*- coding: utf-8 -*-
"""mts4.8 画像解決の取り違え防止テスト（fortunelib.html_report / fortunelib.calc.cards）

背景（mts4.7 までの不具合。本番アセットでの全数監査で判明）:
  1) cards.draw() の card_id は、データに "no" が無い小アルカナでは「デッキ内の並び順」。
     さらに `c.get("no") or ... or i + 1` のため、大アルカナ「愚者」(no=0) も並び順に化けていた。
  2) html_report は card_id の番号でファイルを引いていたため、
     - 小アルカナの画像が無いとき別の大アルカナを充当し、
     - 大アルカナでも同じ番号で始まる小アルカナ（例: 02_of_Swords）を拾っていた。
  3) マルセイユは 08=Justice / 11=Strength と RWS で番号体系が異なる（番号引きでは必ず誤る）。

mts4.8 の解決規則:
  カード名での一致（完全一致 → 正規化一致 → 末尾一致）を最優先し、
  名前が無い場合に限り大アルカナ番号を使う。該当が無ければスキップ（誤充当より欠落を選ぶ）。
"""
from __future__ import annotations

import html as _html
import json
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fortunelib.calc.cards import draw  # noqa: E402
from fortunelib.html_report import (  # noqa: E402
    _find_animal_image_file, _find_eto_image_file, _find_genekeys_image_file,
    _find_numbered_deck_image, _find_oracle_image_file,
    _find_pendulum_image_file, _find_rune_image_file, _find_seiza_image_file,
    _find_tarot_image_file, build_html,
)


def _touch(path: Path, size: int = 32) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF" + b"\x00" * max(0, size - 4))
    return path


def _deck(path: Path = ROOT / "data" / "tarot_78.json") -> list:
    return json.loads(path.read_text(encoding="utf-8"))


class TestTarotImageMatching(unittest.TestCase):
    def test_major_resolved_by_name(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "12_Hanged_Man.webp")
            card = {"arcana": "major", "card_id": 12, "name_en": "The Hanged Man",
                    "position": "最終結果"}
            got = _find_tarot_image_file(card, d)
            self.assertIsNotNone(got)
            self.assertEqual(got.name, "12_Hanged_Man.webp")

    def test_fool_zero_is_resolved(self):
        """愚者 (no=0) を 00_Fool.webp に解決する（0 が falsy でも落とさない）"""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "00_Fool.webp")
            card = {"arcana": "major", "card_id": 0, "name_en": "The Fool", "position": "現在"}
            got = _find_tarot_image_file(card, d)
            self.assertIsNotNone(got)
            self.assertEqual(got.name, "00_Fool.webp")

    def test_marseille_numbering_differs_from_rws(self):
        """マルセイユは 08=Justice / 11=Strength。番号ではなく名前で解決する"""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "08_Justice.webp")
            _touch(d / "11_Strength.webp")
            strength = {"arcana": "major", "card_id": 8, "name_en": "Strength"}
            justice = {"arcana": "major", "card_id": 11, "name_en": "Justice"}
            self.assertEqual(_find_tarot_image_file(strength, d).name, "11_Strength.webp")
            self.assertEqual(_find_tarot_image_file(justice, d).name, "08_Justice.webp")

    def test_major_does_not_steal_minor_with_same_prefix(self):
        """大アルカナが 02_of_Swords のような同番号の小アルカナを拾わない"""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "02_of_Swords.webp")
            card = {"arcana": "major", "card_id": 2, "name_en": "The High Priestess"}
            self.assertIsNone(_find_tarot_image_file(card, d))

    def test_minor_resolved_by_rank_and_suit(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "04_of_Swords.webp")
            card = {"arcana": "minor", "card_id": 1, "name_en": "Four of Swords",
                    "position": "現在の状況"}
            got = _find_tarot_image_file(card, d)
            self.assertIsNotNone(got)
            self.assertEqual(got.name, "04_of_Swords.webp")

    def test_minor_missing_image_is_skipped_not_substituted(self):
        """小アルカナの画像が無いとき、番号一致の大アルカナを充当しない"""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "01_The_Magician.webp")
            card = {"arcana": "minor", "card_id": 1, "name_en": "Four of Swords"}
            self.assertIsNone(_find_tarot_image_file(card, d))

    def test_court_and_ace_names(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            for n in ("Ace_of_Cups.webp", "Page_of_Wands.webp", "Knight_of_Pentacles.webp",
                      "Queen_of_Swords.webp", "King_of_Cups.webp"):
                _touch(d / n)
            for name, fname in (("Ace of Cups", "Ace_of_Cups.webp"),
                                ("Page of Wands", "Page_of_Wands.webp"),
                                ("Knight of Pentacles", "Knight_of_Pentacles.webp"),
                                ("Queen of Swords", "Queen_of_Swords.webp"),
                                ("King of Cups", "King_of_Cups.webp")):
                card = {"arcana": "minor", "card_id": 1, "name_en": name}
                self.assertEqual(_find_tarot_image_file(card, d).name, fname)

    def test_smaller_of_webp_and_jpg_is_chosen(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "04_of_Swords.webp", size=64)
            _touch(d / "04_of_Swords.jpg", size=4096)
            card = {"arcana": "minor", "card_id": 1, "name_en": "Four of Swords"}
            self.assertEqual(_find_tarot_image_file(card, d).suffix, ".webp")

    def test_spaced_and_unspaced_major_names(self):
        """M27_tarot(12_Hanged_Man) と M27_marseille(12_HangedMan) の両方を解決"""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "12_HangedMan.webp")
            card = {"arcana": "major", "card_id": 12, "name_en": "The Hanged Man"}
            self.assertEqual(_find_tarot_image_file(card, d).name, "12_HangedMan.webp")


class TestFullDeckResolution(unittest.TestCase):
    """デッキ全枚（実際にシャッフルして引く）で取り違えが起きないこと"""

    def _build_assets(self, root: Path) -> Path:
        """data/tarot_78.json の実際のカード名で 78 ファイルを作る"""
        assets = root / "assets" / "images"
        word = {"Ace": "Ace", "Two": "02", "Three": "03", "Four": "04", "Five": "05",
                "Six": "06", "Seven": "07", "Eight": "08", "Nine": "09", "Ten": "10",
                "Page": "Page", "Knight": "Knight", "Queen": "Queen", "King": "King"}
        for c in _deck():
            if c.get("arcana") == "major":
                base = f"{int(c['no']):02d}_{c['name_en'].replace('The ', '').replace(' ', '_')}"
            else:
                r, s = c["name_en"].split(" of ")
                base = f"{word[r]}_of_{s}"
            _touch(assets / "M27_tarot" / f"{base}.webp")
        return assets

    @staticmethod
    def _expected_base(card: dict) -> str:
        word = {"Ace": "Ace", "Two": "02", "Three": "03", "Four": "04", "Five": "05",
                "Six": "06", "Seven": "07", "Eight": "08", "Nine": "09", "Ten": "10",
                "Page": "Page", "Knight": "Knight", "Queen": "Queen", "King": "King"}
        if card.get("arcana") == "major":
            return f"{int(card['card_id']):02d}_{card['name_en'].replace('The ', '').replace(' ', '_')}"
        r, s = card["name_en"].split(" of ")
        return f"{word[r]}_of_{s}"

    def test_all_78_cards_map_to_their_own_image(self):
        """実際に 78 枚シャッフルして引いたとき、全カードが自分の画像に解決される"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = self._build_assets(root)
            for seed in (7, 42, 1234, 20260923):
                drawn = draw("tarot", 78, seed=seed, mode="reproducible")
                wrong = []
                for c in drawn["cards"]:
                    got = _find_tarot_image_file(c, assets / "M27_tarot")
                    if got is None:
                        wrong.append((c["name_en"], "未解決"))
                    elif got.stem != self._expected_base(c):
                        wrong.append((c["name_en"], got.name))
                self.assertEqual(wrong, [], f"seed={seed}")

    def test_marseille_all_78_cards_map_to_their_own_image(self):
        """マルセイユ（08=Justice / 11=Strength、名前に空白なし）でも全枚が自分の画像に解決される"""
        marseille = {
            "The Fool": "00_Fool", "The Magician": "01_Magician",
            "The High Priestess": "02_HighPriestess", "The Empress": "03_Empress",
            "The Emperor": "04_Emperor", "The Hierophant": "05_Hierophant",
            "The Lovers": "06_Lovers", "The Chariot": "07_Chariot",
            "Strength": "11_Strength", "The Hermit": "09_Hermit",
            "Wheel of Fortune": "10_WheelOfFortune", "Justice": "08_Justice",
            "The Hanged Man": "12_HangedMan", "Death": "13_Death",
            "Temperance": "14_Temperance", "The Devil": "15_Devil",
            "The Tower": "16_Tower", "The Star": "17_Star", "The Moon": "18_Moon",
            "The Sun": "19_Sun", "Judgement": "20_Judgement", "The World": "21_World",
        }
        word = {"Ace": "Ace", "Two": "02", "Three": "03", "Four": "04", "Five": "05",
                "Six": "06", "Seven": "07", "Eight": "08", "Nine": "09", "Ten": "10",
                "Page": "Page", "Knight": "Knight", "Queen": "Queen", "King": "King"}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            d = root / "assets" / "images" / "M27_marseille"
            expected = {}
            for c in _deck():
                if c.get("arcana") == "major":
                    base = marseille[c["name_en"]]
                    key = c["name_en"]
                else:
                    r, s = c["name_en"].split(" of ")
                    base = f"{word[r]}_of_{s}"
                    key = c["name_en"]
                expected[key] = base
                _touch(d / f"{base}.webp")
            drawn = draw("marseille", 78, seed=99, mode="reproducible")
            wrong = []
            for c in drawn["cards"]:
                got = _find_tarot_image_file(c, d)
                if got is None:
                    wrong.append((c["name_en"], "未解決"))
                elif got.stem != expected[c["name_en"]]:
                    wrong.append((c["name_en"], got.name))
            self.assertEqual(wrong, [])

    def test_full_deck_html_has_78_images(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = self._build_assets(root)
            person = root / "p"
            (person / "results").mkdir(parents=True, exist_ok=True)
            (person / "results" / "M27_tarot_raw.json").write_text(
                json.dumps({"result": {"calc": draw("tarot", 78, seed=5, mode="reproducible")}},
                           ensure_ascii=False), encoding="utf-8")
            (person / "results" / "M27_tarot.md").write_text("# タロット\n\n本文。\n", encoding="utf-8")
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 78)


class TestCardIdPreservesTrueNumber(unittest.TestCase):
    """cards.draw() が実カード番号を返す（愚者=0、大アルカナ=0〜21）"""

    def test_major_card_ids_are_true_numbers(self):
        r = draw("tarot", 78, seed=42, mode="reproducible")
        majors = [c for c in r["cards"] if c.get("arcana") == "major"]
        self.assertEqual(len(majors), 22)
        deck = {c["name_en"]: c["no"] for c in _deck() if c.get("arcana") == "major"}
        for c in majors:
            self.assertEqual(c["card_id"], deck[c["name_en"]], c["name_en"])
        fool = [c for c in majors if c["name_en"] == "The Fool"][0]
        self.assertEqual(fool["card_id"], 0)

    def test_minor_card_id_is_deck_order(self):
        """小アルカナはデータに no が無いため card_id はデッキ内の並び順（画像解決には使わない）"""
        r = draw("tarot", 78, seed=42, mode="reproducible")
        minors = [c for c in r["cards"] if c.get("arcana") != "major"]
        self.assertEqual(len(minors), 56)
        for c in minors:
            self.assertIsInstance(c["card_id"], int)
            self.assertTrue(1 <= c["card_id"] <= 78)


class TestTarotImageEmbedding(unittest.TestCase):
    """HTML 側でも取り違えが起きないこと"""

    def _person(self, root: Path, cards: list) -> Path:
        d = root / "p"
        (d / "results").mkdir(parents=True, exist_ok=True)
        (d / "results" / "M27_tarot_raw.json").write_text(
            json.dumps({"result": {"calc": {"cards": cards}}}, ensure_ascii=False),
            encoding="utf-8")
        (d / "results" / "M27_tarot.md").write_text("# タロット\n\n本文。\n", encoding="utf-8")
        return d

    def test_no_substitution_in_html(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M27_tarot" / "01_The_Magician.webp")
            person = self._person(root, [
                {"arcana": "minor", "card_id": 1, "name_en": "Four of Swords",
                 "position": "現在の状況"},
            ])
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 0)

    def test_single_card_uses_container(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M27_tarot" / "12_Hanged_Man.webp")
            person = self._person(root, [
                {"arcana": "major", "card_id": 12, "name_en": "The Hanged Man",
                 "position": "最終結果"},
            ])
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 1)
            self.assertIn("fortune-image-container", html)
            self.assertNotIn('class="fortune-image-grid"', html)

    def test_multiple_cards_use_grid(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            for name in ("12_Hanged_Man.webp", "13_Death.webp", "15_The_Devil.webp"):
                _touch(assets / "M27_tarot" / name)
            person = self._person(root, [
                {"arcana": "major", "card_id": 12, "name_en": "The Hanged Man", "position": "過去"},
                {"arcana": "major", "card_id": 13, "name_en": "Death", "position": "現在"},
                {"arcana": "major", "card_id": 15, "name_en": "The Devil", "position": "未来"},
            ])
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 3)
            self.assertEqual(html.count('class="fortune-image-grid"'), 1)
            self.assertEqual(html.count('class="fortune-image-item"'), 3)


if __name__ == "__main__":
    unittest.main()


# ============================================================
# mts4.9: M27_kipper / M27_runes / M28_omikuji の表示統合
# ============================================================
from fortunelib.html_report import (_find_kipper_image_file, _find_omikuji_image_file,  # noqa: E402
                                    _find_rune_image_file, _generic_kipper_tag,
                                    _generic_omikuji_tag, _generic_runes_tag)


def _make_person(root: Path, slug: str, calc: dict) -> Path:
    d = root / "p"
    (d / "results").mkdir(parents=True, exist_ok=True)
    (d / "results" / f"{slug}_raw.json").write_text(
        json.dumps({"result": {"calc": calc}}, ensure_ascii=False), encoding="utf-8")
    (d / "results" / f"{slug}.md").write_text(f"# {slug}\n\n本文。\n", encoding="utf-8")
    return d


class TestKipperImages(unittest.TestCase):
    def test_resolves_by_number_and_name(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "07_PleasantMessage.webp")
            card = {"card_id": 7, "name_en": "Pleasant Message", "name_ja": "朗報"}
            self.assertEqual(_find_kipper_image_file(card, d).name, "07_PleasantMessage.webp")

    def test_name_mismatch_is_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "07_OtherCard.webp")
            card = {"card_id": 7, "name_en": "Pleasant Message"}
            self.assertIsNone(_find_kipper_image_file(card, d))

    def test_five_cards_render_as_grid(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            names = ["Man", "Woman", "Marriage", "Courtship", "Mature Man"]
            for i, n in enumerate(names, 1):
                _touch(assets / "M27_kipper" / f"{i:02d}_{n.replace(' ', '')}.webp")
            cards = [{"card_id": i, "name_en": n, "name_ja": f"カード{i}", "position": "過去"}
                     for i, n in enumerate(names, 1)]
            person = _make_person(root, "M27_kipper", {"cards": cards})
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 5)
            self.assertEqual(html.count('class="fortune-image-grid"'), 1)


class TestRuneImages(unittest.TestCase):
    def test_resolves_by_number_and_name(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "01_Fehu.webp")
            self.assertEqual(_find_rune_image_file({"card_id": 1, "name_en": "Fehu"}, d).name,
                             "01_Fehu.webp")

    def test_three_cards_render_as_grid(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            for i, n in enumerate(["Fehu", "Uruz", "Thurisaz"], 1):
                _touch(assets / "M27_runes" / f"{i:02d}_{n}.webp")
            cards = [{"card_id": i, "name_en": n, "name_ja": n, "position": "現在"}
                     for i, n in enumerate(["Fehu", "Uruz", "Thurisaz"], 1)]
            person = _make_person(root, "M27_runes", {"cards": cards})
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 3)


class TestOmikujiImages(unittest.TestCase):
    def _assets(self, root: Path, level_no: int, slugs: str) -> Path:
        assets = root / "assets" / "images"
        for pose in "abcdefgh":
            _touch(assets / "M28_omikuji" / f"{level_no:02d}_{slugs}_{pose}.webp")
        return assets

    def test_level_number_selects_correct_group(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = self._assets(root, 2, "daikichi")
            got = _find_omikuji_image_file(2, 3, assets / "M28_omikuji")
            self.assertIsNotNone(got)
            self.assertTrue(got.stem.startswith("02_daikichi_"))
            self.assertTrue(got.stem.endswith("_d"))          # pose_idx=3 → "d"

    def test_other_level_is_not_used(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = self._assets(root, 2, "daikichi")
            self.assertIsNone(_find_omikuji_image_file(5, 0, assets / "M28_omikuji"))

    def test_daidaikichi_uses_gold_special(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            for pose in "abcdefgh":
                _touch(assets / "M28_omikuji" / f"01_daidaikichi_{pose}.webp")
            _touch(assets / "M28_omikuji" / "01_daidaikichi_gold1.webp")
            _touch(assets / "M28_omikuji" / "01_daidaikichi_gold2.webp")
            person = _make_person(root, "M28_omikuji",
                                  {"level": "大大吉", "keyword": "運気絶頂"})
            html = _generic_omikuji_tag(person, assets, "p")
            self.assertIn("data:image", html)
            self.assertIn("大大吉", html)

    def test_deterministic_pose_for_same_person(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = self._assets(root, 6, "suekichi")
            person = _make_person(root, "M28_omikuji", {"level": "末吉", "keyword": "兆し"})
            first = _generic_omikuji_tag(person, assets, "takahashi_ren")
            second = _generic_omikuji_tag(person, assets, "takahashi_ren")
            self.assertEqual(first, second)                    # 同一人物は常に同じ柄

    def test_unknown_level_is_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = self._assets(root, 6, "suekichi")
            person = _make_person(root, "M28_omikuji", {"level": "存在しない段階"})
            self.assertEqual(_generic_omikuji_tag(person, assets, "p"), "")


# ============================================================
# mts5.0: M27_oracle / M27_angel（44枚デッキ）の表示統合
# ============================================================
from fortunelib.html_report import (_find_angel_image_file,  # noqa: E402
                                    _find_oracle_image_file, _generic_angel_tag,
                                    _generic_oracle_tag)


class TestOracleImages(unittest.TestCase):
    def test_resolves_by_number_and_name(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "01_NewBeginning.webp")
            card = {"card_id": 1, "name_en": "New Beginning", "name_ja": "新しい始まり"}
            self.assertEqual(_find_oracle_image_file(card, d).name, "01_NewBeginning.webp")

    def test_name_mismatch_is_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "01_OldEnding.webp")
            card = {"card_id": 1, "name_en": "New Beginning"}
            self.assertIsNone(_find_oracle_image_file(card, d))

    def test_three_cards_render_as_grid(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            names = ["Hope", "Courage", "Trust"]
            for i, n in enumerate(names, 1):
                _touch(assets / "M27_oracle" / f"{i:02d}_{n}.webp")
            cards = [{"card_id": i, "name_en": n, "name_ja": f"カード{i}", "position": f"位置{i}"}
                     for i, n in enumerate(names, 1)]
            person = _make_person(root, "M27_oracle", {"cards": cards})
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 3)
            self.assertEqual(html.count('class="fortune-image-grid"'), 1)
            self.assertIn("【オラクル】", html)


class TestAngelImages(unittest.TestCase):
    def test_resolves_ascii_head_of_mixed_name(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "01_Michael.webp")
            card = {"card_id": 1, "name_en": "Michael・守護と浄化", "name_ja": "大天使ミカエル"}
            self.assertEqual(_find_angel_image_file(card, d).name, "01_Michael.webp")

    def test_english_phrase_name_resolves(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "05_PureLove.webp")
            card = {"card_id": 5, "name_en": "Pure Love"}
            self.assertEqual(_find_angel_image_file(card, d).name, "05_PureLove.webp")

    def test_name_mismatch_is_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "01_Gabriel.webp")
            card = {"card_id": 1, "name_en": "Michael・守護と浄化"}
            self.assertIsNone(_find_angel_image_file(card, d))

    def test_three_cards_render_as_grid(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            for i, n in enumerate(["Michael", "Gabriel", "Raphael"], 1):
                _touch(assets / "M27_angel" / f"{i:02d}_{n}.webp")
            cards = [{"card_id": i, "name_en": f"{n}・守護", "name_ja": f"大天使{i}", "position": "現在"}
                     for i, n in enumerate(["Michael", "Gabriel", "Raphael"], 1)]
            person = _make_person(root, "M27_angel", {"cards": cards})
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 3)
            self.assertIn("【エンジェル】", html)

# --------------------------------------------------- M09_animal / M33_genekeys（mts5.2）
class TestAnimalImages(unittest.TestCase):
    """M09_animal: 番号＋英名（animals_60_profiles.json）で検証して解決"""

    def test_resolves_by_number_and_name(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "18_Elephant.webp")
            img = _find_animal_image_file(18, d)
            self.assertIsNotNone(img)
            self.assertEqual(img.name, "18_Elephant.webp")

    def test_name_mismatch_is_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "18_Wolf.webp")          # 18番は Elephant（ゾウ）なので誤り
            self.assertIsNone(_find_animal_image_file(18, d))

    def test_unknown_number_is_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "61_Elephant.webp")
            self.assertIsNone(_find_animal_image_file(61, d))

    def test_renders_single_container_with_caption(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M09_animal" / "18_Elephant.webp")
            person = _make_person(root, "M09_animal", {"number": 18, "character": "傷つきやすいゾウ"})
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 1)
            self.assertIn("【動物占い】", html)
            self.assertIn("Elephant", html)


class TestGenekeysImages(unittest.TestCase):
    """M33_genekeys: ゲート番号＋アーキタイプSlug（genekeys_64_archetypes.json）で検証して解決"""

    def test_resolves_by_gate_and_slug(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "17_FarSeeingSeer.webp")
            img = _find_genekeys_image_file(17, d)
            self.assertIsNotNone(img)
            self.assertEqual(img.name, "17_FarSeeingSeer.webp")

    def test_slug_mismatch_is_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "17_NavigatorOfUnity.webp")   # 17鍵は FarSeeingSeer
            self.assertIsNone(_find_genekeys_image_file(17, d))

    def test_renders_single_container_with_caption(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M33_genekeys" / "17_FarSeeingSeer.webp")
            person = _make_person(root, "M11_genekeys", {"status": "ok", "sun_gate": {"gate": 17}, "key": {"gate": 17}})
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 1)
            self.assertIn("【ジーンキーズ】", html)
            self.assertIn("遠見の見者", html)

# ------------------------------------------------- M02_seiza（mts5.3）
class TestSeizaImages(unittest.TestCase):
    """M02_seiza: 星座和名 → 画像番号＋英名（白羊宮01 … 双魚宮12）で検証して解決"""

    def test_resolves_by_sign_and_english_name(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "01_Aries.webp")
            self.assertEqual(_find_seiza_image_file("牡羊座", d).name, "01_Aries.webp")

    def test_wrong_sign_is_not_substituted(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "01_Taurus.webp")          # 01番は Aries なので牡羊座に充当してはいけない
            self.assertIsNone(_find_seiza_image_file("牡羊座", d))

    def test_unknown_sign_is_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "01_Aries.webp")
            self.assertIsNone(_find_seiza_image_file("へびつかい座", d))

    def test_missing_image_is_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "05_Leo.webp")
            self.assertIsNone(_find_seiza_image_file("蠍座", d))   # 07 が無い

    def test_renders_single_container_with_caption(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M02_seiza" / "05_Leo.webp")
            person = _make_person(root, "M02_seiza", {"sign": "獅子座", "sign_en": "Leo"})
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 1)
            self.assertIn("【星座占い】", html)
            self.assertIn("獅子座", html)
            self.assertIn("Leo", html)


class TestEtoImages(unittest.TestCase):
    """M01_eto: 支（子・丑…）→ 画像番号＋英名（Rat 等）で検証して解決（mts5.7 で追加）

    血液型（M08_blood）は mts5.7 で**画像をオミット**する方針になったため、
    表示・解決のテストはこの干支クラスに置き換えた（画像は assets_bases/blood/_clean に退避）。
    """

    def test_resolves_each_branch(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "01_Rat.webp")
            _touch(d / "07_Horse.webp")
            _touch(d / "12_Boar.webp")
            self.assertEqual(_find_eto_image_file("子", d).name, "01_Rat.webp")
            self.assertEqual(_find_eto_image_file("午", d).name, "07_Horse.webp")
            self.assertEqual(_find_eto_image_file("亥", d).name, "12_Boar.webp")

    def test_wrong_branch_is_not_substituted(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "01_Horse.webp")            # 01番は Rat なので「子」に充当してはいけない
            self.assertIsNone(_find_eto_image_file("子", d))
            _touch(d / "07_Rat.webp")              # 07番は Horse なので「午」に充当してはいけない
            self.assertIsNone(_find_eto_image_file("午", d))

    def test_missing_branch_image_is_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "01_Rat.webp")
            self.assertIsNone(_find_eto_image_file("丑", d))   # 02 が無い

    def test_renders_single_container_with_caption(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M01_eto" / "07_Horse.webp")
            person = _make_person(root, "M01_eto",
                                  {"shi": "午", "animal": "馬", "ganzhi": "戊午"})
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 1)
            self.assertIn("【干支】", html)
            self.assertIn("午", html)
            self.assertIn("Horse", html)
            self.assertIn("戊午", html)

    def test_blood_image_is_not_rendered(self):
        """M08_blood は画像を出さない（オミット後。画像があっても埋め込まない）"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M08_blood" / "01_A.webp")
            person = _make_person(root, "M08_blood", {"type": "A"})
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 0)


class TestRuneDrawOrderRegression(unittest.TestCase):
    """mts5.4: ルーンの card_id は「抽選順」であり石の番号ではない（実運用で発見した誤充当の回帰テスト）

    実例（本番実行ログの検証で発見）: 位置1 ウンジョ（Wunjo）に対して 01_Fehu が表示されていた。
    card_id=1 は抽選順であってエルダーフサルク順の 01 ではないため、名前で引く必要がある。
    """

    def test_draw_position_is_not_used_as_file_number(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            for name in ("01_Fehu.webp", "02_Uruz.webp", "08_Wunjo.webp"):
                _touch(d / name)
            card = {"position": "位置1", "card_id": 1, "name_ja": "ウンジョ", "name_en": "Wunjo"}
            img = _find_rune_image_file(card, d)
            self.assertIsNotNone(img)
            self.assertEqual(img.name, "08_Wunjo.webp")     # 01_Fehu を充当してはいけない

    def test_other_runes_resolve_by_name(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            for name in ("03_Thurisaz.webp", "19_Ehwaz.webp", "22_Ingwaz.webp"):
                _touch(d / name)
            self.assertEqual(_find_rune_image_file({"card_id": 2, "name_en": "Ingwaz"}, d).name,
                             "22_Ingwaz.webp")
            self.assertEqual(_find_rune_image_file({"card_id": 3, "name_en": "Ehwaz"}, d).name,
                             "19_Ehwaz.webp")

    def test_name_mismatch_is_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "01_Fehu.webp")
            self.assertIsNone(_find_rune_image_file({"card_id": 1, "name_en": "Wunjo"}, d))

    def test_missing_name_is_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "01_Fehu.webp")
            self.assertIsNone(_find_rune_image_file({"card_id": 1}, d))

class TestPendulumImages(unittest.TestCase):
    """M29_pendulum: calc.answer（yes/no/neutral）→ 番号＋英名（Yes/No/Neutral）で解決（mts5.8 で追加）"""

    def test_resolves_each_state(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "01_Yes.webp")
            _touch(d / "02_No.webp")
            _touch(d / "03_Neutral.webp")
            self.assertEqual(_find_pendulum_image_file("yes", d).name, "01_Yes.webp")
            self.assertEqual(_find_pendulum_image_file("no", d).name, "02_No.webp")
            self.assertEqual(_find_pendulum_image_file("neutral", d).name, "03_Neutral.webp")

    def test_wrong_state_is_not_substituted(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "01_No.webp")        # 01番は Yes なので「no」に充当してはいけない
            self.assertIsNone(_find_pendulum_image_file("no", d))
            _touch(d / "03_Yes.webp")       # 03番は Neutral なので「yes」に充当してはいけない
            self.assertIsNone(_find_pendulum_image_file("yes", d))

    def test_missing_state_image_is_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "01_Yes.webp")
            self.assertIsNone(_find_pendulum_image_file("neutral", d))   # 03 が無い

    def test_unknown_answer_is_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "01_Yes.webp")
            self.assertIsNone(_find_pendulum_image_file("maybe", d))

    def test_renders_single_container_with_caption(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M29_pendulum" / "02_No.webp")
            person = _make_person(root, "M29_pendulum", {"answer": "no"})
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 1)
            self.assertIn("【ペンデュラム】", html)
            self.assertIn("否定", html)
            self.assertIn("No", html)


class TestAfricanImages(unittest.TestCase):
    """M29_african: calc.open_count（0〜8）→ 01_Open0 … 09_Open8（mts5.10 で追加）

    図は「敷物の情景（AI原画）」＋「コーリー貝（開き＝殻口が上／閉じ＝背面）を PIL で投げた配置」で、
    開きの枚数が結果と一致する。番号は open_count + 1。
    """

    def test_resolves_each_open_count(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            for i in range(9):
                _touch(d / f"{i + 1:02d}_Open{i}.webp")
            for oc in range(9):
                with self.subTest(open_count=oc):
                    self.assertEqual(_find_african_image_file(oc, d).name,
                                     f"{oc + 1:02d}_Open{oc}.webp")

    def test_wrong_number_is_not_substituted(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "05_Open5.webp")     # 開き5枚の枠しか無い → 開き4枚には充当しない
            self.assertIsNone(_find_african_image_file(4, d))

    def test_wrong_name_is_not_substituted(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "05_Cowrie.webp")    # 番号は合うが英名が違う
            self.assertIsNone(_find_african_image_file(4, d))

    def test_out_of_range_is_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            for i in range(9):
                _touch(d / f"{i + 1:02d}_Open{i}.webp")
            self.assertIsNone(_find_african_image_file(9, d))    # 0〜8 の外
            self.assertIsNone(_find_african_image_file(-1, d))

    def test_renders_single_container_with_caption(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M29_african" / "05_Open4.webp")
            person = _make_person(root, "M29_african", {"open_count": 4})
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 1)
            self.assertIn("【伝統的アフリカ占い】", html)
            self.assertIn("開き 4 枚（Open4）", html)


class TestTalismanImages(unittest.TestCase):
    """M30_talisman: 護符の意匠を1枚にまとめた固定の1枚（calc を持たない。mts5.10 で追加）"""

    def test_resolves_single_talisman_image(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "01_Talisman.webp")
            self.assertEqual(_find_numbered_deck_image(1, d, "Talisman").name, "01_Talisman.webp")

    def test_wrong_name_is_not_substituted(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "01_Charm.webp")        # 番号は合うが英名が違う
            self.assertIsNone(_find_numbered_deck_image(1, d, "Talisman"))

    def test_wrong_number_is_not_substituted(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "02_Talisman.webp")     # 1番の画像が無い → 充当しない
            self.assertIsNone(_find_numbered_deck_image(1, d, "Talisman"))
            self.assertEqual(_find_numbered_deck_image(2, d, "Talisman").name, "02_Talisman.webp")

    def test_renders_single_container_with_caption(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M30_talisman" / "01_Talisman.webp")
            person = _make_person(root, "M30_talisman", {})
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 1)
            self.assertIn("【タリスマン・お守り】", html)
            self.assertIn("Talisman", html)


class TestCrystalImages(unittest.TestCase):
    """M30_crystal: 鑑定文の石名 → 12石の1枚を解決（mts5.9 で追加）

    このデッキは calc を持たない生成系（registry calc_key=None）のため、鑑定文（result.text）に
    現れた石名（和名・英名）を照合する。一致が無ければ埋め込まない（誤充当より欠落を選ぶ）。
    """

    def test_text_matching_returns_stone_number(self):
        cases = [("アメジストがおすすめです。", 1),
                 ("この石はローズクォーツです。", 3),
                 ("Clear Quartz を身につけるとよい。", 2),
                 ("オレンジカルサイトという石が合います。", 0),   # 12石に無い石名
                 ("石の指定はありません。", 0)]
        for text, want in cases:
            with self.subTest(text=text):
                self.assertEqual(_crystal_stone_in_text(text), want)

    def test_text_matching_prefers_earlier_position(self):
        """複数の石名が現れたら、先に出た方を採る（決定的）"""
        self.assertEqual(_crystal_stone_in_text("ガーネットの次にシトリンを試す。"), 12)
        self.assertEqual(_crystal_stone_in_text("シトリンの次にガーネットを試す。"), 4)

    def test_resolves_by_number_and_name(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "04_Citrine.webp")
            _touch(d / "11_Moonstone.webp")
            self.assertEqual(_find_crystal_image_file(4, d).name, "04_Citrine.webp")
            self.assertEqual(_find_crystal_image_file(11, d).name, "11_Moonstone.webp")

    def test_wrong_name_is_not_substituted(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "04_Fluorite.webp")   # 04番はシトリンなので充当しない
            self.assertIsNone(_find_crystal_image_file(4, d))

    def test_renders_single_container_with_caption(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M30_crystal" / "06_LapisLazuli.webp")
            person = root / "p"
            (person / "results").mkdir(parents=True, exist_ok=True)
            (person / "results" / "M30_crystal_raw.json").write_text(
                json.dumps({"result": {"calc": None,
                                       "text": "ラピスラズリを身につけるとよいでしょう。"}},
                           ensure_ascii=False), encoding="utf-8")
            (person / "results" / "M30_crystal.md").write_text("# crystal\n\n本文。\n",
                                                               encoding="utf-8")
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 1)
            self.assertIn("【クリスタル・ヒーリング】", html)
            self.assertIn("ラピスラズリ", html)
            self.assertIn("Lapis Lazuli", html)

    def test_no_stone_in_text_skips(self):
        """石名が本文に無ければ埋め込まない（誤充当より欠落）"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M30_crystal" / "02_ClearQuartz.webp")
            person = root / "p"
            (person / "results").mkdir(parents=True, exist_ok=True)
            (person / "results" / "M30_crystal_raw.json").write_text(
                json.dumps({"result": {"calc": None, "text": "今日は静かに過ごしましょう。"}},
                           ensure_ascii=False), encoding="utf-8")
            (person / "results" / "M30_crystal.md").write_text("# crystal\n\n本文。\n",
                                                               encoding="utf-8")
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 0)


class TestCrystalBallImages(unittest.TestCase):
    """M30_crystalball: 情景1枚を解決（calc を持たない占術。mts5.8 で追加）"""

    def test_resolves_single_scrying_image(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "01_Scrying.webp")
            self.assertEqual(_find_numbered_deck_image(1, d, "Scrying").name,
                             "01_Scrying.webp")

    def test_wrong_name_is_not_substituted(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _touch(d / "01_Scrying2.webp")   # 英名が一致しないので充当しない
            self.assertIsNone(_find_numbered_deck_image(1, d, "Scrying"))

    def test_renders_single_container_with_caption(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M30_crystalball" / "01_Scrying.webp")
            person = _make_person(root, "M30_crystalball", {})
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 1)
            self.assertIn("【水晶玉占い】", html)
            self.assertIn("Scrying", html)


class TestPowerStoneImages(unittest.TestCase):
    """M12_stone（パワーストーン）: M30_crystal 共有プールから誕生石を解決（mts5.13 で追加）"""

    def test_resolves_birthstone_from_calc_garnet(self):
        """calc.birthstone = 'ガーネット' → 12_Garnet.webp を M30_crystal から解決"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M30_crystal" / "12_Garnet.webp")
            person = root / "p"
            (person / "results").mkdir(parents=True, exist_ok=True)
            (person / "results" / "M12_stone_raw.json").write_text(
                json.dumps({"result": {"calc": {"birthstone": "ガーネット"}}},
                           ensure_ascii=False), encoding="utf-8")
            (person / "results" / "M12_stone.md").write_text("# stone\n\n本文。\n",
                                                            encoding="utf-8")
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 1)
            self.assertIn("【パワーストーン】", html)
            self.assertIn("ガーネット", html)
            self.assertIn("Garnet", html)

    def test_resolves_birthstone_from_calc_amethyst(self):
        """calc.birthstone = 'アメジスト' → 01_Amethyst.webp を M30_crystal から解決"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M30_crystal" / "01_Amethyst.webp")
            person = root / "p"
            (person / "results").mkdir(parents=True, exist_ok=True)
            (person / "results" / "M12_stone_raw.json").write_text(
                json.dumps({"result": {"calc": {"birthstone": "アメジスト"}}},
                           ensure_ascii=False), encoding="utf-8")
            (person / "results" / "M12_stone.md").write_text("# stone\n\n本文。\n",
                                                            encoding="utf-8")
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 1)
            self.assertIn("【パワーストーン】", html)
            self.assertIn("アメジスト", html)
            self.assertIn("Amethyst", html)

    def test_resolves_birthstone_new_aquamarine(self):
        """calc.birthstone = 'アクアマリン' → 13_Aquamarine.webp（新規追加石）を解決"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M30_crystal" / "13_Aquamarine.webp")
            person = root / "p"
            (person / "results").mkdir(parents=True, exist_ok=True)
            (person / "results" / "M12_stone_raw.json").write_text(
                json.dumps({"result": {"calc": {"birthstone": "アクアマリン"}}},
                           ensure_ascii=False), encoding="utf-8")
            (person / "results" / "M12_stone.md").write_text("# stone\n\n本文。\n",
                                                            encoding="utf-8")
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 1)
            self.assertIn("【パワーストーン】", html)
            self.assertIn("アクアマリン", html)
            self.assertIn("Aquamarine", html)

    def test_unmatched_stone_skips(self):
        """石が見つからなければスキップ（誤充当より欠落）"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M30_crystal" / "01_Amethyst.webp")
            person = root / "p"
            (person / "results").mkdir(parents=True, exist_ok=True)
            (person / "results" / "M12_stone_raw.json").write_text(
                json.dumps({"result": {"calc": {"birthstone": "架空の石"}}},
                           ensure_ascii=False), encoding="utf-8")
            (person / "results" / "M12_stone.md").write_text("# stone\n\n本文。\n",
                                                            encoding="utf-8")
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 0)


class TestLiuyaoImages(unittest.TestCase):
    """M22_liuyao: M26_iching 64卦画像から本卦・之卦を流用解決（mts5.13 で追加）"""

    def test_resolves_origin_and_variant_hexagram(self):
        """本卦（乾→01乾為天）と之卦（坤→02坤為地）の2枚グリッド表示"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M26_iching" / "01_U4e7eU70baU5929.webp")
            _touch(assets / "M26_iching" / "02_U5764U70baU5730.webp")
            person = root / "p"
            (person / "results").mkdir(parents=True, exist_ok=True)
            (person / "results" / "M22_liuyao_raw.json").write_text(
                json.dumps({"result": {"calc": {
                    "origin_hexagram": "乾",
                    "variant_hexagram": "坤"
                }}}, ensure_ascii=False), encoding="utf-8")
            (person / "results" / "M22_liuyao.md").write_text("# liuyao\n\n本文。\n",
                                                              encoding="utf-8")
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 2)
            self.assertIn("fortune-image-grid", html)
            self.assertIn("【六爻】本卦：乾為天（01）", html)
            self.assertIn("【六爻】之卦：坤為地（02）", html)

    def test_resolves_single_hexagram_when_no_change(self):
        """本卦と之卦が同一（蒙→04山水蒙）の場合は1枚コンテナ大表示"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M26_iching" / "04_U5c71U6c34U8499.webp")
            person = root / "p"
            (person / "results").mkdir(parents=True, exist_ok=True)
            (person / "results" / "M22_liuyao_raw.json").write_text(
                json.dumps({"result": {"calc": {
                    "origin_hexagram": "蒙",
                    "variant_hexagram": "蒙"
                }}}, ensure_ascii=False), encoding="utf-8")
            (person / "results" / "M22_liuyao.md").write_text("# liuyao\n\n本文。\n",
                                                              encoding="utf-8")
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 1)
            self.assertIn("fortune-image-container", html)
            self.assertIn("【六爻】本卦：山水蒙（04）", html)

    def test_unmatched_hexagram_skips(self):
        """未知の卦名なら画像を埋め込まない（誤充当より欠落）"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M26_iching" / "01_U4e7eU70baU5929.webp")
            person = root / "p"
            (person / "results").mkdir(parents=True, exist_ok=True)
            (person / "results" / "M22_liuyao_raw.json").write_text(
                json.dumps({"result": {"calc": {
                    "origin_hexagram": "未知の卦",
                    "variant_hexagram": "未知の卦"
                }}}, ensure_ascii=False), encoding="utf-8")
            (person / "results" / "M22_liuyao.md").write_text("# liuyao\n\n本文。\n",
                                                              encoding="utf-8")
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 0)


class TestMesoImages(unittest.TestCase):
    """M30_meso: メソポタミア天体オーメン 24枚解決（mts5.13 で追加）"""

    def test_resolves_meso_omen_by_id(self):
        """EAE-01 -> 01_CrescentMoon.webp が大画像として解決される"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M30_meso" / "01_CrescentMoon.webp")
            person = root / "p"
            (person / "results").mkdir(parents=True, exist_ok=True)
            (person / "results" / "M30_meso_raw.json").write_text(
                json.dumps({"result": {"calc": {
                    "omen_id": "EAE-01",
                    "theme": "信頼・吉兆"
                }}}, ensure_ascii=False), encoding="utf-8")
            (person / "results" / "M30_meso.md").write_text("# meso\n\n本文。\n",
                                                            encoding="utf-8")
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 1)
            self.assertIn("fortune-image-container", html)
            self.assertIn("【メソポタミア天体オーメン】EAE-01（信頼・吉兆）", html)

    def test_unmatched_or_missing_omen_id_skips(self):
        """画像が存在しない、または無効なIDならスキップ（誤充当より欠落）"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M30_meso" / "01_CrescentMoon.webp")
            person = root / "p"
            (person / "results").mkdir(parents=True, exist_ok=True)
            (person / "results" / "M30_meso_raw.json").write_text(
                json.dumps({"result": {"calc": {
                    "omen_id": "EAE-99",
                    "theme": "未知"
                }}}, ensure_ascii=False), encoding="utf-8")
            (person / "results" / "M30_meso.md").write_text("# meso\n\n本文。\n",
                                                            encoding="utf-8")
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 0)


class TestChristianImages(unittest.TestCase):
    """M30_christian: キリスト教的黙想 24枚解決（mts5.13 で追加）"""

    def test_resolves_christian_verse_by_ref(self):
        """マタイ 6:34 -> 01_LiliesOfTheField.webp が大画像として解決される"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M30_christian" / "01_LiliesOfTheField.webp")
            person = root / "p"
            (person / "results").mkdir(parents=True, exist_ok=True)
            (person / "results" / "M30_christian_raw.json").write_text(
                json.dumps({"result": {"calc": {
                    "reference": "マタイ 6:34",
                    "theme": "憂いを手放す"
                }}}, ensure_ascii=False), encoding="utf-8")
            (person / "results" / "M30_christian.md").write_text("# christian\n\n本文。\n",
                                                                 encoding="utf-8")
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 1)
            self.assertIn("fortune-image-container", html)
            self.assertIn("【キリスト教的黙想】マタイ 6:34（憂いを手放す）", html)

    def test_unmatched_or_missing_ref_skips(self):
        """画像が存在しない、または無効な聖句参照ならスキップ（誤充当より欠落）"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M30_christian" / "01_LiliesOfTheField.webp")
            person = root / "p"
            (person / "results").mkdir(parents=True, exist_ok=True)
            (person / "results" / "M30_christian_raw.json").write_text(
                json.dumps({"result": {"calc": {
                    "reference": "架空の書 99:99",
                    "theme": "未知"
                }}}, ensure_ascii=False), encoding="utf-8")
            (person / "results" / "M30_christian.md").write_text("# christian\n\n本文。\n",
                                                                 encoding="utf-8")
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 0)


class TestUrbanTarotImages(unittest.TestCase):
    """M27_urbantarot: 現代タロット 既存M27_tarot画像共用（mts5.13 で追加）"""

    def test_resolves_urbantarot_using_tarot_images(self):
        """M27_tarot のカード画像を使って3枚スプレッドが表示される"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M27_tarot" / "00_TheFool.jpg")
            _touch(assets / "M27_tarot" / "01_TheMagician.jpg")
            _touch(assets / "M27_tarot" / "02_TheHighPriestess.jpg")
            person = root / "p"
            (person / "results").mkdir(parents=True, exist_ok=True)
            (person / "results" / "M27_urbantarot_raw.json").write_text(
                json.dumps({"result": {"calc": {"tarot": {"cards": [
                    {"name_en": "The Fool", "upright": True, "position": "過去"},
                    {"name_en": "The Magician", "upright": True, "position": "現在"},
                    {"name_en": "The High Priestess", "upright": False, "position": "未来"}
                ]}}}}, ensure_ascii=False), encoding="utf-8")
            (person / "results" / "M27_urbantarot.md").write_text("# urbantarot\n\n本文。\n",
                                                                  encoding="utf-8")
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 3)
            self.assertIn("fortune-image-grid", html)
            self.assertIn("【現代タロット】過去 The Fool（正位置）", html)
            self.assertIn("【現代タロット】現在 The Magician（正位置）", html)
            self.assertIn("【現代タロット】未来 The High Priestess（逆位置）", html)


class TestAstragaloiImages(unittest.TestCase):
    """M28_astragaloi: 籤占 距骨出目グリッド表示（mts5.13 で追加）"""

    def test_resolves_astragaloi_throws_grid(self):
        """throws [1, 3, 4, 6] が4枚グリッドとして解決される"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M28_astragaloi" / "01_Chios_1.webp")
            _touch(assets / "M28_astragaloi" / "02_Trias_3.webp")
            _touch(assets / "M28_astragaloi" / "03_Tetras_4.webp")
            _touch(assets / "M28_astragaloi" / "04_Stron_6.webp")
            person = root / "p"
            (person / "results").mkdir(parents=True, exist_ok=True)
            (person / "results" / "M28_astragaloi_raw.json").write_text(
                json.dumps({"result": {"calc": {
                    "throws": [1, 3, 4, 6],
                    "total": 14,
                    "judgment": "アフロディーテの目（最上の目）"
                }}}, ensure_ascii=False), encoding="utf-8")
            (person / "results" / "M28_astragaloi.md").write_text("# astragaloi\n\n本文。\n",
                                                                  encoding="utf-8")
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 4)
            self.assertIn("fortune-image-grid", html)
            self.assertIn("アフロディーテの目（最上の目）", html)
            self.assertIn("合計: 14", html)


class TestHaruspexImages(unittest.TestCase):
    """M30_haruspex: 肝占 バビロニア粘土肝模型 大画像表示（mts5.13 で追加）"""

    def test_resolves_haruspex_clay_liver(self):
        """01_ClayLiver.webp が大画像として解決される"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M30_haruspex" / "01_ClayLiver.webp")
            person = root / "p"
            (person / "results").mkdir(parents=True, exist_ok=True)
            (person / "results" / "M30_haruspex_raw.json").write_text(
                json.dumps({"result": {"text": "肝占の鑑定本文。"}}, ensure_ascii=False), encoding="utf-8")
            (person / "results" / "M30_haruspex.md").write_text("# haruspex\n\n本文。\n",
                                                                encoding="utf-8")
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 1)
            self.assertIn("fortune-image-container", html)
            self.assertIn("【肝占（バールートゥ）】バビロニアの粘土肝模型", html)


from fortunelib.html_report import (_crystal_stone_in_text,  # noqa: E402
                                   _find_crystal_image_file)


from fortunelib.html_report import (  # noqa: E402
    _find_african_image_file, _find_african_image_file as _fa,
)


class TestOrnithDelphiImages(unittest.TestCase):
    """M30_ornith / M30_delphi: P6 古代託宣群・5変種からランダムに1枚表示（mts5.14 で追加）

    両デッキは calc を持たない生成系のため、占術結果と**無関係**に1枚を表示する。
    選択は**意図的なランダム**（御神籤感覚・ユーザー決定 2026-09-26）。
    """

    def _person(self, root: Path, deck: str) -> Path:
        person = root / "p"
        (person / "results").mkdir(parents=True, exist_ok=True)
        (person / "results" / f"{deck}_raw.json").write_text(
            json.dumps({"result": {"text": "鑑定本文。"}}, ensure_ascii=False), encoding="utf-8")
        (person / "results" / f"{deck}.md").write_text(f"# {deck}\n\n本文。\n", encoding="utf-8")
        return person

    def test_ornith_random_pick_always_valid(self):
        """繰り返し実行でも常に1枚・キャプションは5変種のいずれかと一致する"""
        from fortunelib.html_report import ORNITH_VARIANTS
        import re as _re
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            for no, slug, ja, en in ORNITH_VARIANTS:
                _touch(assets / "M30_ornith" / f"{no:02d}_{slug}.webp")
            person = self._person(root, "M30_ornith")
            seen = set()
            for _ in range(60):
                out = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
                self.assertEqual(out.count("data:image"), 1)
                m = _re.search(r"【鳥占】([^（]+)（([^）]+)）", _html.unescape(out))
                self.assertIsNotNone(m)
                pair = (m.group(1), m.group(2))
                self.assertIn(pair, [(ja, en) for _, _, ja, en in ORNITH_VARIANTS])
                seen.add(pair)
            # 意図的なランダム: 60回で2種以上が観察される（1種だけに固定されない）
            self.assertGreater(len(seen), 1)

    def test_delphi_random_pick_always_valid(self):
        from fortunelib.html_report import DELPHI_VARIANTS
        import re as _re
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            for no, slug, ja, en in DELPHI_VARIANTS:
                _touch(assets / "M30_delphi" / f"{no:02d}_{slug}.webp")
            person = self._person(root, "M30_delphi")
            seen = set()
            for _ in range(60):
                out = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
                self.assertEqual(out.count("data:image"), 1)
                m = _re.search(r"【デルポイの託宣】([^（]+)（([^）]+)）", _html.unescape(out))
                self.assertIsNotNone(m)
                self.assertIn((m.group(1), m.group(2)),
                              [(ja, en) for _, _, ja, en in DELPHI_VARIANTS])
                seen.add((m.group(1), m.group(2)))
            self.assertGreater(len(seen), 1)

    def test_missing_raw_skips(self):
        """raw が無ければ画像なし（誤充当より欠落）"""
        from fortunelib.html_report import ORNITH_VARIANTS
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            for no, slug, ja, en in ORNITH_VARIANTS:
                _touch(assets / "M30_ornith" / f"{no:02d}_{slug}.webp")
            person = root / "p"
            (person / "results").mkdir(parents=True, exist_ok=True)
            (person / "results" / "M30_ornith.md").write_text("# ornith\n\n本文。\n", encoding="utf-8")
            out = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(out.count("data:image"), 0)

    def test_real_assets_present(self):
        """納品アセットに5変種がすべて揃っている"""
        for deck, want in (("M30_ornith", {"01_HawkEast", "02_DoveSouth", "03_CrowWest",
                                           "04_SwallowCircle", "05_OwlNight"}),
                           ("M30_delphi", {"01_Tripod", "02_LaurelCrown", "03_CastaliaSpring",
                                           "04_ZeusEagle", "05_Omphalos"})):
            d = ROOT / "assets" / "images" / deck
            got = {f.stem for f in d.glob("*.webp")}
            self.assertEqual(got, want)


class TestNoImageNotices(unittest.TestCase):
    """画像なしの注意書き（mts5.15 で追加・ユーザー要望 2026-09-26）"""

    def _person(self, root: Path, deck: str, raw: dict | None, body: str = "本文。") -> Path:
        person = root / "p"
        (person / "results").mkdir(parents=True, exist_ok=True)
        if raw is not None:
            (person / "results" / f"{deck}_raw.json").write_text(
                json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        (person / "results" / f"{deck}.md").write_text(f"# {deck}\n\n{body}\n", encoding="utf-8")
        return person

    def test_deities_shows_spec_notice(self):
        """M31_deities（オミット確定）には『画像はありません（仕様）』の注意書き"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            person = self._person(root, "M31_deities", {"result": {"text": "神々の鑑定。"}})
            out = build_html(person, person_id="p", images_dir=root / "assets" / "images").read_text(encoding="utf-8")
            self.assertIn("※この占術には画像がありません（バグではなく、仕様です）。", out)
            self.assertIn("fortune-no-image", out)
            self.assertEqual(out.count("data:image"), 0)

    def test_crystal_shows_result_notice_when_no_stone(self):
        """クリスタル: 鑑定文に石名が無ければ『結果に対して画像なし（仕様）』の注意書き"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M30_crystal" / "01_Amethyst.webp")
            person = self._person(root, "M30_crystal",
                                  {"result": {"text": "今日は静かに過ごしましょう。"}})
            out = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertIn("今回の占術結果に対しては画像がありません（バグではなく、仕様です）。", out)
            self.assertEqual(out.count("data:image"), 0)

    def test_crystal_no_notice_when_stone_matches(self):
        """クリスタル: 石名が一致すれば画像が表示され注意書きは出ない"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M30_crystal" / "01_Amethyst.webp")
            person = self._person(root, "M30_crystal",
                                  {"result": {"text": "アメジストが導きです。"}})
            out = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertNotIn("今回の占術結果に対しては画像がありません", out)
            self.assertEqual(out.count("data:image"), 1)

class TestTypeCHtmlIntegration(unittest.TestCase):
    """型C（mts5.16）: M03/M04/M06 の結果から動的チャートがHTMLに埋め込まれる"""

    def _person(self, root: Path, slug: str, calc: dict, extra=None) -> Path:
        person = root / "p"
        (person / "results").mkdir(parents=True, exist_ok=True)
        (person / "results" / f"{slug}_raw.json").write_text(
            json.dumps({"result": {"calc": calc}}), encoding="utf-8")
        (person / "results" / f"{slug}.md").write_text(
            f"# {slug}\n\n本文。\n", encoding="utf-8")
        if extra is not None:
            (person / "results" / "M04_numerology_name_raw.json").write_text(
                json.dumps({"result": {"calc": extra}}), encoding="utf-8")
        return person

    def test_kyusei_chart_embedded(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            person = self._person(root, "M03_kyusei",
                                  {"year": 1985, "honmei_no": 6, "honmei": "六白金星"})
            html = build_html(person, person_id="p",
                              images_dir=ROOT / "assets" / "images").read_text(encoding="utf-8")
        self.assertIn("【九星気学】1985年生・本命星：六白金星", html)
        self.assertIn("fortune-image-container", html)

    def test_kabbalah_chart_embedded(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            person = self._person(Path(t), "M06_kabbalah",
                                  {"romaji": "Takahashi Ren", "number": 5})
            html = build_html(person, person_id="p",
                              images_dir=ROOT / "assets" / "images").read_text(encoding="utf-8")
        self.assertIn("【カバラ数秘術】TAKAHASHI REN → 5", html)

    def test_no_base_no_tag(self):
        import tempfile
        from unittest import mock
        from fortunelib import chartdraw
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            person = self._person(root, "M03_kyusei",
                                  {"year": 1985, "honmei_no": 6, "honmei": "六白金星"})
            # ベース画像が解決できない環境を模す（load_base を不能化）
            with mock.patch.object(chartdraw, "load_base",
                                   lambda slug, assets_root=None: None):
                html = build_html(person, person_id="p",
                                  images_dir=root / "emptyassets").read_text(encoding="utf-8")
        self.assertNotIn("【九星気学】", html)


class TestTypeCBatch1HtmlIntegration(unittest.TestCase):
    """mts5.17: html_report の型Cバッチ1 dispatch（typec_tag 経由・calc 有無）。"""

    CALC = {
        "M05_numerology_name": ({"number": 8, "romaji": "Hanako Yamada"},
                                "氏名数8（HANAKO YAMADA）"),
        "M07_chaldean": ({"number": 5, "romaji": "Ken Sato"},
                         "カルデア数5（KEN SATO）"),
        "M04_tantra": ({"number": 9}, "タントラ数9"),
        "M04_anka": ({"number": 3}, "アンカ数3・支配星：木星"),
        "M10_rokusei": ({"type": "金星人プラス", "cycle": "大殺界", "target_year": 2026},
                        "金星人プラス／年運：大殺界（2026）"),
        "M14_weton": ({"weton_name": "月曜・Pon", "pasaran": "Pon"}, "月曜・Pon"),
        "M13_primbon": ({"weton": "月曜・Pon", "neptu_total": 12},
                        "月曜・Pon／ネプトゥ12"),
    }

    def _person(self, tmp_path, slug):
        calc, _ = self.CALC[slug]
        rd = tmp_path / "person"
        (rd / "results").mkdir(parents=True, exist_ok=True)
        (rd / "results" / f"{slug}_raw.json").write_text(
            json.dumps({"result": {"calc": calc}}), encoding="utf-8")
        return rd

    def test_tag_with_calc(self):
        from fortunelib import chartdraw
        assets = ROOT / "assets" / "images"
        with tempfile.TemporaryDirectory() as td:
            for slug, (_, frag) in self.CALC.items():
                rd = self._person(Path(td), slug)
                tag = chartdraw.typec_tag(slug, rd, assets)
                self.assertIn("<img", tag, slug)
                self.assertIn(frag, tag, slug)

    def test_tag_without_calc_is_empty(self):
        from fortunelib import chartdraw
        assets = ROOT / "assets" / "images"
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td) / "empty"
            (rd / "results").mkdir(parents=True)
            for slug in self.CALC:
                self.assertEqual(chartdraw.typec_tag(slug, rd, assets), "", slug)


class TestTypeCBatch2HtmlIntegration(unittest.TestCase):
    """mts5.18: html_report の型Cバッチ2 dispatch（typec_tag 経由・calc 有無）。"""

    def _calcs(self):
        from fortunelib.calc.bazi import bazi_paipan
        from fortunelib.calc.astrology import vedic_sidereal, to_jd
        from fortunelib.calc.sanmeigaku import sanmeigaku_full
        from fortunelib.calc.qimen import qimen_pan
        from fortunelib.calc.seimei import seimei_calc
        return {
            "M17_bazi": (bazi_paipan(1978, 7, 7, 12, 0, lon_east=139.7,
                                     apply_true_solar=True), "日主：庚"),
            "M19_vedic": (vedic_sidereal(to_jd(1978, 7, 7, 12.0)), "プシュヤ"),
            "M21_sanmei": ({"status": "ok", **sanmeigaku_full(1978, 7, 7)},
                           "中心星：牽牛星"),
            "M24_qimen": (qimen_pan(2026, 9, 26, 9, 0), "陰遁一局中元"),
            "M16_seimei": (seimei_calc("高", "橋連"), "人26・地27"),
        }

    def test_tag_with_calc(self):
        from fortunelib import chartdraw
        assets = ROOT / "assets" / "images"
        with tempfile.TemporaryDirectory() as td:
            for slug, (calc, frag) in self._calcs().items():
                rd = Path(td) / slug
                (rd / "results").mkdir(parents=True)
                (rd / "results" / f"{slug}_raw.json").write_text(
                    json.dumps({"result": {"calc": calc}}), encoding="utf-8")
                tag = chartdraw.typec_tag(slug, rd, assets)
                self.assertIn("<img", tag, slug)
                self.assertIn(frag, tag, slug)

    def test_tag_without_calc_is_empty(self):
        from fortunelib import chartdraw
        assets = ROOT / "assets" / "images"
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td) / "empty"
            (rd / "results").mkdir(parents=True)
            for slug in self._calcs():
                self.assertEqual(chartdraw.typec_tag(slug, rd, assets), "", slug)


class TestTypeCAstroHtmlIntegration(unittest.TestCase):
    """mts5.19: html_report の西洋占星術系 dispatch（typec_tag・transit は extra 併読）。"""

    def test_tags(self):
        from fortunelib.calc.astrology import natal_chart, transit_chart
        from fortunelib import chartdraw
        mine = natal_chart(1978, 7, 7, 12.0, 35.7, 139.7)
        tr = transit_chart(mine)
        assets = ROOT / "assets" / "images"
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td) / "p"
            (rd / "results").mkdir(parents=True)
            (rd / "results" / "M18_western_raw.json").write_text(
                json.dumps({"result": {"calc": mine}}), encoding="utf-8")
            (rd / "results" / "M18_transit_raw.json").write_text(
                json.dumps({"result": {"calc": tr}}), encoding="utf-8")
            tag = chartdraw.typec_tag("M18_western", rd, assets)
            self.assertIn("太陽：", tag)
            tag = chartdraw.typec_tag("M18_transit", rd, assets)
            self.assertIn("アスペクト", tag)
            self.assertIn("<img", tag)

    def test_tag_without_calc_is_empty(self):
        from fortunelib import chartdraw
        assets = ROOT / "assets" / "images"
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td) / "empty"
            (rd / "results").mkdir(parents=True)
            for slug in ("M18_western", "M18_natal", "M18_transit", "M18_synastry"):
                self.assertEqual(chartdraw.typec_tag(slug, rd, assets), "", slug)


class TestTypeCBRestHtmlIntegration(unittest.TestCase):
    """mts5.20: html_report のB群残 dispatch（typec_tag 経由・calc 有無）。"""

    def test_tags(self):
        from fortunelib.calc.ziwei import ziwei_chart
        from fortunelib.calc.hd_full import calculate_chart
        from fortunelib.calc.parimicham import parimicham_calc
        from fortunelib import chartdraw
        assets = ROOT / "assets" / "images"
        p = parimicham_calc({"date": "1978-07-07"}, {"date": "1980-01-15"},
                            role1="本人", role2="相手")
        p["status"] = "ok"
        calcs = {"M20_ziwei": (ziwei_chart(1978, 7, 7, 12, gender="male"), "金の四局"),
                 "M25_hd": (calculate_chart(1978, 7, 7, 12, 0, 9.0), "ジェネレーター"),
                 "M15_parimicham": (p, "5.0/8.0")}
        with tempfile.TemporaryDirectory() as td:
            for slug, (calc, frag) in calcs.items():
                rd = Path(td) / slug
                (rd / "results").mkdir(parents=True)
                (rd / "results" / f"{slug}_raw.json").write_text(
                    json.dumps({"result": {"calc": calc}}), encoding="utf-8")
                tag = chartdraw.typec_tag(slug, rd, assets)
                self.assertIn("<img", tag, slug)
                self.assertIn(frag, tag, slug)

    def test_tag_without_calc_is_empty(self):
        from fortunelib import chartdraw
        assets = ROOT / "assets" / "images"
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td) / "empty"
            (rd / "results").mkdir(parents=True)
            for slug in ("M20_ziwei", "M25_hd", "M15_parimicham"):
                self.assertEqual(chartdraw.typec_tag(slug, rd, assets), "", slug)

class TestTypecFontGuard(unittest.TestCase):
    """mts5.28: 型Cの同梱CJKフォント欠落（豆腐□□□）の再発防止。

    背景: mts5.27 実機（2026-09-26）で、型Cの全チャートが**豆腐**になった。
    原因は **同梱必須の assets/fonts/typec_jp_subset.ttf が配布ZIPに入っていなかった**こと
    （Kaggle 側に CJK フォントは無く、フォールバック先も無い）。
    文字は画素の一部なので、既存の検証器（平均差）では閾内に隠れて素通りした。
    """

    def test_bundled_font_present(self):
        """配布物には同梱CJKフォントが必須（テストは常に検知できること）"""
        from fortunelib import chartdraw
        self.assertNotEqual(chartdraw.bundled_font_path(), "",
                            "assets/fonts/typec_jp_subset.ttf がありません")
        self.assertTrue(chartdraw.uses_bundled_font(),
                        "描画が同梱フォントを使っていません（Kaggle では豆腐になります）")

    def test_glyphs_are_not_tofu(self):
        """型Cで使う代表文字が豆腐でない（同梱フォントで実グリフが出る）"""
        from fortunelib import chartdraw
        for ch in ("紫", "微", "斗", "数", "星", "宮"):
            self.assertFalse(chartdraw.glyph_is_tofu(ch), f"{ch} が豆腐になっています")

    def test_warning_when_font_missing(self):
        """同梱フォントが無い状態で build_html すると警告が出る（Kaggle ログで気づける）"""
        import json as _json
        import tempfile
        from fortunelib import chartdraw, html_report as hr
        saved = (chartdraw._BUNDLED_FONT, list(chartdraw._FALLBACK_FONTS),
                 dict(chartdraw._font_cache), chartdraw._font_source)
        try:
            with tempfile.TemporaryDirectory() as td:
                person = Path(td) / "p"
                (person / "results").mkdir(parents=True)
                (person / "results" / "M03_kyusei_raw.json").write_text(
                    _json.dumps({"result": {"calc": {"year": 1985,
                                                     "honmei_no": 6,
                                                     "honmei": "六白金星"}}}),
                    encoding="utf-8")
                (person / "results" / "M03_kyusei.md").write_text(
                    "# 九星気学\n\n**実行**：2026-09-26T00:00:00+09:00\n\n"
                    "## ■ 鑑定文\n本文です。\n", encoding="utf-8")
                # フォントを無効化して描画（Kaggle の状況を再現）
                chartdraw._font_cache.clear()
                chartdraw._BUNDLED_FONT = Path("/nonexistent")
                chartdraw._FALLBACK_FONTS = []
                hr._typec_font_warned[0] = False
                # 型Cは assets_root が解決できるときだけ描画されるため、
                # 実物の納品画像（型Cベース）を使い、フォントだけを無効化する
                assets = (Path(__file__).resolve().parents[1]
                          / "assets" / "images")
                with warnings.catch_warnings(record=True) as w:
                    warnings.simplefilter("always")
                    build_html(person, person_id="p", images_dir=assets)
                msgs = [str(x.message) for x in w]
        finally:
            chartdraw._BUNDLED_FONT, chartdraw._FALLBACK_FONTS = saved[0], saved[1]
            chartdraw._font_cache.clear()
            chartdraw._font_cache.update(saved[2])
            chartdraw._font_source = saved[3]
            hr._typec_font_warned[0] = False
        self.assertTrue(any("同梱CJKフォント" in m for m in msgs),
                        f"フォント欠落の警告が出ていません: {msgs}")

    def test_zip_builder_checks_font(self):
        """ZIP ビルダがフォント欠落を検知して中止できる（検査関数が機能する）"""
        import sys
        from pathlib import Path as _P
        root = _P(__file__).resolve().parents[2]
        sys.path.insert(0, str(root / "tools"))
        try:
            import build_dataset_zip as bz
        finally:
            sys.path.pop(0)
        self.assertEqual(bz.check_bundled_font("exclude"), [])
        self.assertEqual(bz.check_bundled_font("include"), [])

    def test_zip_builder_paths_are_portable(self):
        """mts5.30: ZIP ビルダのパスは実行環境から解決される（/home/user 固定の再発防止）。

        背景: mts5.28 で追加した同梱物検査は Kaggle のセルフテスト（Cell 0.1）からも
        呼ばれる。以前は ROOT が `/home/user` 固定だったため、Kaggle マウント
        （/kaggle/input/datasets/.../fortune_dataset/...）では**実在するフォントを
        「無い」と誤判定**し、セルフテストが失敗して本番セルが実行されなかった
        （2026-09-27 の mts5.29 実機ログで発生）。

        ここでは **別の場所に置いたコピー**を読み込み、パスがファイル位置から
        解決されること（＝環境に依存しないこと）を検証する。
        """
        import importlib.util
        import shutil
        import tempfile
        from pathlib import Path as _P

        src = _P(__file__).resolve().parents[2] / "tools" / "build_dataset_zip.py"
        with tempfile.TemporaryDirectory() as td:
            fake = _P(td) / "elsewhere" / "repo"
            (fake / "tools").mkdir(parents=True)
            # パッケージの存在だけを模す（中身は不要＝パス解決の検証のみ）
            (fake / "fortune_dataset" / "data").mkdir(parents=True)
            shutil.copy2(src, fake / "tools" / "build_dataset_zip.py")
            spec = importlib.util.spec_from_file_location(
                "bz_portable_test", fake / "tools" / "build_dataset_zip.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            # ROOT はコピー先（＝ファイルの2つ上）を指す
            self.assertEqual(mod.ROOT, fake,
                             f"ROOT が実行位置から解決されていません: {mod.ROOT}")
            # フォントの検査は「その場所」を見る（別環境のパスを見ていない）
            probs = mod.check_bundled_font("exclude")
            self.assertTrue(probs, "存在しない場所なのに問題なしと判定されました")
            self.assertIn(str(fake), probs[0],
                          f"検査対象が実行位置ではありません: {probs[0]}")

    def test_check_bundled_font_without_tools_dir(self):
        """mts5.32: tools/ を伴わない環境でも同梱物検査は落ちない（Kaggle マウント等）。

        背景: 実描画の被覆検査は tools/build_chart_fonts.py を読み込むため、
        ビルダだけが置かれた環境では FileNotFoundError で落ちていた。ここでは
        **文字列ベースの検査へ縮退**することを固定する（例外を出さない）。
        """
        import importlib.util
        import shutil
        import tempfile
        from pathlib import Path as _P

        src = _P(__file__).resolve().parents[2] / "tools" / "build_dataset_zip.py"
        fonts = _P(__file__).resolve().parents[2] / "fortune_dataset" / "assets" / "fonts"
        with tempfile.TemporaryDirectory() as td:
            fake = _P(td) / "elsewhere" / "repo"
            (fake / "tools").mkdir(parents=True)
            (fake / "fortune_dataset" / "assets" / "fonts").mkdir(parents=True)
            (fake / "fortune_dataset" / "data").mkdir(parents=True)
            shutil.copy2(src, fake / "tools" / "build_dataset_zip.py")
            # フォントだけは置く（無いと被覆検査まで到達しないため）
            for f in sorted(fonts.glob("*.ttf")):
                shutil.copy2(f, fake / "fortune_dataset" / "assets" / "fonts" / f.name)
            spec = importlib.util.spec_from_file_location(
                "bz_no_tools_test", fake / "tools" / "build_dataset_zip.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            probs = mod.check_bundled_font("exclude")   # 例外を出さないこと
            self.assertIsInstance(probs, list)
            self.assertTrue(any("省略" in x for x in probs),
                            f"縮退の注記がありません: {probs}")

    def test_no_hardcoded_home_path_in_portable_tools(self):
        """mts5.30: 配布テストから実行されるツールに /home/user 固定パスが無いこと

        コード中の文字列定数だけを見る（説明文の docstring やコメントは対象外）。
        許可するのは後方互換の最終フォールバック "/home/user/fortune_dataset" のみ。
        """
        import ast
        from pathlib import Path as _P

        root = _P(__file__).resolve().parents[2]
        allowed = {"/home/user/fortune_dataset"}
        for rel in ("tools/build_dataset_zip.py",
                    "fortune_dataset/fortunelib/chartdraw.py",
                    "verify/verify_run_output.py"):
            path = root / rel
            if not path.is_file():
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.FunctionDef,
                                     ast.AsyncFunctionDef, ast.ClassDef)):
                    body = getattr(node, "body", None) or []
                    if (body and isinstance(body[0], ast.Expr)
                            and isinstance(body[0].value, ast.Constant)
                            and isinstance(body[0].value.value, str)):
                        docstrings.add(id(body[0].value))
            hard = sorted({n.value for n in ast.walk(tree)
                           if isinstance(n, ast.Constant)
                           and isinstance(n.value, str)
                           and n.value.startswith("/home/user")
                           and id(n) not in docstrings})
            unexpected = [x for x in hard if x not in allowed]
            self.assertEqual(
                unexpected, [],
                f"{rel} に /home/user 固定パスが残っています: {unexpected}"
                f"（検出: {hard}）")

class TestChartdrawVisibleToUnittest(unittest.TestCase):
    """mts5.31: 型C描画（chartdraw）が**Kaggle のセルフテストでも走る**ようにする。

    背景: tests/test_chartdraw.py は pytest 形式（pytest.importorskip / fixture /
    parametrize）で書かれているため、Cell 0.1 の `unittest discover` では
    **1件も実行されない**（ローカル pytest 824件 vs Kaggle 検出 793件の差31件）。
    型Cは「文字が豆腐（□□□）になった」不具合を出した領域なので、
    ここで最小限の不変条件を unittest 側にも固定する。
    """

    @classmethod
    def setUpClass(cls):
        try:
            from fortunelib import chartdraw as _cd
        except Exception as e:                      # noqa: BLE001
            raise unittest.SkipTest(f"chartdraw を読み込めません: {e}")
        cls.cd = _cd

    def test_renders_expected_size(self):
        img = self.cd.render_kyusei(1985, 6)
        self.assertEqual(img.size, (300, 400))

    def test_uses_bundled_font(self):
        """同梱CJKフォントが使われる（Kaggle に CJK フォントが無いため必須）"""
        if self.cd.bundled_font_path() is None:
            self.skipTest("同梱フォントが無い環境（配布物では必ず入ります）")
        self.cd.render_kyusei(1985, 6)
        self.assertTrue(self.cd.uses_bundled_font(),
                        "同梱フォントがあるのに使われていません（Kaggle で豆腐になります）")

    def test_rendered_text_is_not_tofu(self):
        """描画した文字が豆腐（□）になっていないこと（型Cの生命線）"""
        from PIL import Image, ImageDraw
        img = self.cd.render_kyusei(1985, 6)
        # フォントが無い場合は豆腐になるので、同梱フォント前提の検査
        if self.cd.bundled_font_path() is None:
            self.skipTest("同梱フォントが無い環境")
        self.assertTrue(self.cd.uses_bundled_font(),
                        f"同梱フォントを使っていません（解決先: {self.cd.font_source()}）")
        self.assertFalse(self.cd.glyph_is_tofu("占"), "『占』が豆腐判定です")

    def test_render_for_slug_and_unknown(self):
        img, cap = self.cd.render_for_slug(
            "M03_kyusei", {"year": 1985, "honmei_no": 6, "honmei": "六白金星"})
        self.assertIsNotNone(img)
        self.assertIn("六白金星", cap)
        img2, cap2 = self.cd.render_for_slug("M99_unknown", {})
        self.assertIsNone(img2)
        self.assertEqual(cap2, "")

    def test_deterministic(self):
        a = self.cd.render_kyusei(1990, 1)
        b = self.cd.render_kyusei(1990, 1)
        self.assertEqual(a.tobytes(), b.tobytes())

class TestSingleImageNotDropped(unittest.TestCase):
    """mts5.31: 「1枚だけ解決できた」ときに画像を落とさない（回帰テスト）。

    背景: 全枚表示のレンダラは、解決できた枚数が1枚のときだけ「大表示」に切り替える。
    その分岐が **先頭の要素（hexes[0] / cards[0]）で画像を探し直していた** ため、
    先頭の画像が無い場合に
      - IndexError（易・六爻の hexes[0] 版）→ 例外が握りつぶされて **1枚も出ない**
      - `if not img_path: return ""`（カード系）→ **見つかっていた1枚も出ない**
    という「静かな画像消失」が起きていた。解決済みの1件を使う実装に変更した。
    """

    def test_iching_keeps_variant_when_ben_image_missing(self):
        """本卦の画像が無くても、変卦の1枚は表示する"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M26_iching" / "05_U6c34U5929U9700.webp")   # 05 水天需 のみ
            person = root / "p"
            (person / "results").mkdir(parents=True, exist_ok=True)
            (person / "results" / "M26_iching_raw.json").write_text(
                json.dumps({"result": {"calc": {
                    "ben_hexagram": {"kingwen_no": 3, "name_ja": "水雷屯"},
                    "derived_hexagram": {"kingwen_no": 5, "name_ja": "水天需"},
                }}}, ensure_ascii=False), encoding="utf-8")
            (person / "results" / "M26_iching.md").write_text("# iching\n\n本文。\n",
                                                             encoding="utf-8")
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 1,
                             "本卦の画像が無いときに変卦の1枚まで消えています")
            self.assertIn("水天需", html)

    def test_liuyao_keeps_variant_when_origin_image_missing(self):
        """六爻: 本卦の画像が無くても之卦の1枚は表示する（IndexError の回帰）"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M26_iching" / "05_U6c34U5929U9700.webp")
            person = root / "p"
            (person / "results").mkdir(parents=True, exist_ok=True)
            (person / "results" / "M22_liuyao_raw.json").write_text(
                json.dumps({"result": {"calc": {
                    "origin_hexagram": "屯",           # 03（画像なし）
                    "variant_hexagram": "需",          # 05（画像あり）
                }}}, ensure_ascii=False), encoding="utf-8")
            (person / "results" / "M22_liuyao.md").write_text("# liuyao\n\n本文。\n",
                                                             encoding="utf-8")
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 1,
                             "本卦の画像が無いときに之卦の1枚まで消えています")
            self.assertIn("水天需", html)

    def test_tarot_keeps_the_resolved_card(self):
        """タロット: 画像が1枚だけ解決したとき、その1枚を表示する（cards[0] ではない）"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets" / "images"
            _touch(assets / "M27_tarot" / "13_Death.jpg")     # 13 死神 のみ配置
            person = root / "p"
            (person / "results").mkdir(parents=True, exist_ok=True)
            (person / "results" / "M27_tarot_raw.json").write_text(
                json.dumps({"result": {"calc": {"cards": [
                    {"no": 12, "name_en": "Hanged Man", "position": "1", "upright": True},
                    {"no": 13, "name_en": "Death", "position": "2", "upright": True},
                ]}}}, ensure_ascii=False), encoding="utf-8")
            (person / "results" / "M27_tarot.md").write_text("# tarot\n\n本文。\n",
                                                             encoding="utf-8")
            html = build_html(person, person_id="p", images_dir=assets).read_text(encoding="utf-8")
            self.assertEqual(html.count("data:image"), 1,
                             "12番の画像が無いため、13番の1枚まで消えています")
            self.assertIn("Death", html)


class TestJstDateGate(unittest.TestCase):
    """mts5.31: 「今日の運勢」の対象日は常に日本時間で決まること。

    Kaggle のコンテナは UTC で動くため、素の datetime.now()（＝naive・環境依存）を
    calc_results に渡すと、00:00〜08:59 JST の実行で**対象日が前日**になる。
    """

    def test_run_person_mts_passes_jst_aware_now(self):
        import datetime as _dt
        from unittest import mock
        from fortunelib import mts as _mts

        seen = {}
        real = _mts.build_calc_results

        def spy(ni, **kw):
            seen["now"] = kw.get("now")
            return real(ni, **kw)

        row = {"person_id": "jst_check", "birth_date": "1990-05-05",
               "birth_time": "12:00", "birth_place": "東京都", "gender": "M",
               "blood_type": "A", "name_kanji": "検証 太郎",
               "name_kana": "けんしょう たろう", "consultation": "",
               "target": "", "_index": 1}
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(_mts, "build_calc_results", spy), \
                    mock.patch.object(_mts, "run_slugs_mts", lambda *a, **k: []):
                _mts.run_person_mts(row, {}, Path(td), stages="A",
                                    verbose=False, monitor=False)

        now = seen.get("now")
        self.assertIsNotNone(now, "build_calc_results に now が渡っていません")
        self.assertIsNotNone(getattr(now, "tzinfo", None),
                             f"now が naive（環境依存の時刻）です: {now}")
        offset = now.utcoffset()
        self.assertEqual(offset, _dt.timedelta(hours=9),
                         f"now が日本時間ではありません: {now}（オフセット {offset}）")
        # UTC の 2025-12-31 23:30 は JST では 2026-01-01（この差が対象日に出ないこと）
        self.assertEqual(now.date().isoformat(), (now.astimezone(
            _dt.timezone.utc) + _dt.timedelta(hours=9)).date().isoformat())



class _FakeDateTime:
    """datetime.now(tz) だけを差し替えるためのスタブ（テスト用）"""

    def __init__(self, moment):
        self._moment = moment

    def now(self, tz=None):
        return self._moment.astimezone(tz) if tz else self._moment


