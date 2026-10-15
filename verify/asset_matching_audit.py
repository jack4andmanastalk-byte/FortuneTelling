# -*- coding: utf-8 -*-
"""
画像アセット適合監査（本番アセット assets/images を全数チェック）

やること:
  各デッキ（tarot / marseille / lenormand / cartomancy / meihua / iching）について
  デッキ全枚を cards.draw() と同じ手順でカードdict化し、html_report の解決関数で
  画像ファイルが「解決できるか」「正しいカードの画像か」を全数検査する。

**この監査が見るのは「ファイル名の対応」だけ**です（画像の中身＝キャプションとの整合は
`verify/verify_run_output.py` が担当）。名前だけの監査では **中身を入れ替えても気づけません**
（実測: tarot の 00↔01 を中身ごと入れ替えても「78/78 正しい画像」のまま）。

実行:
  python3 verify/asset_matching_audit.py --pkg fortune_dataset
  python3 verify/asset_matching_audit.py --pkg fortune_dataset --strict   # 合否を終了コードへ
  python3 verify/asset_matching_audit.py --pkg work/fortune_dataset/fortune_dataset   # mts4.7（無修正）
出力:
  verify/out_audit/<pkg名>.json（結果）＋ 標準出力サマリ

終了コード（mts5.52・F-7）:
  0 = 既定（従来どおり。数字は目視で確認）
  1 = `--strict` で「誤り・未解決・**検査できなかったデッキ**」が1件以上
  2 = 監査できない（data/*.json が読めない等）

mts5.52（F-7）の変更点:
  ①`--strict` を追加（従来は常に exit 0 = 自動化から使えなかった）
  ②**デッキの欠落を明示**（assets ディレクトリが無い／画像が0枚のデッキを
    「未検査」として一覧表示。従来は行が1つも出ない無言のスキップ）
  ③出力の先頭に「ファイル名ベースの監査である」ことを1行追加
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RANK_WORD_TO_NUM = {"Ace": "Ace", "Two": "02", "Three": "03", "Four": "04", "Five": "05",
                    "Six": "06", "Seven": "07", "Eight": "08", "Nine": "09", "Ten": "10",
                    "Page": "Page", "Knight": "Knight", "Queen": "Queen", "King": "King"}


def _norm(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def rank_base(name_en: str) -> str | None:
    parts = (name_en or "").split(" of ")
    if len(parts) == 2:
        return f"{RANK_WORD_TO_NUM.get(parts[0], parts[0])}_of_{parts[1]}"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkg", default="fortune_dataset", help="検査対象パッケージのパス")
    ap.add_argument("--assets", default=None, help="assets/images（既定: PKG/assets/images）")
    ap.add_argument("--strict", action="store_true",
                    help="誤り・未解決・検査できなかったデッキがあれば exit 1（mts5.52）")
    args = ap.parse_args()

    pkg = Path(args.pkg)
    if not pkg.is_absolute():
        pkg = ROOT / pkg
    assets = Path(args.assets) if args.assets else pkg / "assets" / "images"
    sys.path.insert(0, str(pkg))

    from fortunelib.calc import cards as cards_mod
    from fortunelib.html_report import (_find_cartomancy_image_file, _find_lenormand_image_file,
                                        _find_meihua_image_file, _find_tarot_image_file)

    iching = json.loads((pkg / "data" / "iching_64.json").read_text(encoding="utf-8"))
    tarot_data = json.loads((pkg / "data" / "tarot_78.json").read_text(encoding="utf-8"))
    TRUE_NO = {c["name_en"]: c["no"] for c in tarot_data if c.get("arcana") == "major"}
    TRUE_BASE = {}
    for c in tarot_data:
        if c.get("arcana") != "major":
            r, s = c["name_en"].split(" of ")
            TRUE_BASE[c["name_en"]] = f"{RANK_WORD_TO_NUM[r]}_of_{s}"
    # 監査が対象とするデッキ（M08_blood は mts5.7 で画像をオミットしたため対象外）
    REQUIRED_DECKS = ["M27_tarot", "M27_marseille", "M27_lenormand", "M27_cartomancy",
                      "M27_runes", "M28_omikuji", "M27_kipper", "M27_oracle", "M27_angel",
                      "M09_animal", "M33_genekeys", "M23_meihua", "M26_iching",
                      "M02_seiza", "M01_eto", "M29_pendulum", "M30_crystalball",
                      "M30_crystal", "M29_african", "M30_talisman", "M30_meso",
                      "M30_christian", "M28_astragaloi", "M30_haruspex",
                      "M30_ornith", "M30_delphi"]
    result: dict = {"pkg": str(pkg), "assets": str(assets), "decks": {},
                    "skipped": [],
                    "note": "ファイル名ベースの監査（画像の中身は verify_run_output.py）"}
    print("[note] 本監査は**ファイル名ベース**です（画像の中身＝キャプションとの整合は "
          "verify/verify_run_output.py が担当）。")

    def _skip(deck: str, reason: str) -> None:
        """検査できなかったデッキを無言で飛ばさない（mts5.52・F-7）。"""
        result["skipped"].append({"deck": deck, "reason": reason})
        print(f"[{deck:12s}] 未検査: {reason}")

    # ---- カード系（tarot / marseille / lenormand / cartomancy） ----
    deck_dirs = {"tarot": "M27_tarot", "marseille": "M27_marseille",
                 "lenormand": "M27_lenormand", "cartomancy": "M27_cartomancy"}
    for deck_id, sub in deck_dirs.items():
        d = assets / sub
        if not d.is_dir():
            result["decks"][deck_id] = {"error": "assets dir not found"}
            _skip(sub, "assets ディレクトリがありません")
            continue
        spread = "celtic_cross" if deck_id in ("tarot", "marseille") else None
        count = 78 if deck_id in ("tarot", "marseille") else (36 if deck_id == "lenormand" else 52)
        drawn = cards_mod.draw(deck_id, count, spread=spread, seed=7, mode="reproducible")
        ok = bad = miss = 0
        problems = []
        for c in drawn["cards"]:
            if deck_id in ("tarot", "marseille"):
                got = _find_tarot_image_file(c, d)
            elif deck_id == "lenormand":
                got = _find_lenormand_image_file(c, d)
            else:
                got = _find_cartomancy_image_file(c, d)
            if got is None:
                miss += 1
                problems.append({"card": c.get("name_en"), "issue": "unresolved"})
                continue
            # 正解判定
            if deck_id in ("tarot", "marseille"):
                if c.get("arcana") == "major":
                    # 期待値は「デッキデータの実カード名」から作る（card_id には依存しない）。
                    # マルセイユは 08=Justice / 11=Strength と RWS で番号体系が異なるため、
                    # 名前の一致で判定する（画像ファイル名にカード名が含まれていれば正しい）。
                    plain = c["name_en"].replace("The ", "").replace(" ", "")
                    correct = plain.lower() in _norm(got.stem)
                else:
                    want = TRUE_BASE.get(c.get("name_en") or "", "")
                    correct = (got.stem == want or _norm(got.stem) == _norm(want))
            elif deck_id == "lenormand":
                want = f"{int(c['card_id']):02d}_"
                correct = got.stem.startswith(want)
            else:
                suit_map = {"H": "Hearts", "D": "Diamonds", "C": "Clubs", "S": "Spades"}
                rank_map = {"A": "Ace", "J": "Jack", "Q": "Queen", "K": "King"}
                suit_full = suit_map.get(c.get("suit"), c.get("suit"))
                rank_full = rank_map.get(c.get("rank"))
                if rank_full is None:
                    try:
                        rank_full = f"{int(c.get('rank')):02d}"
                    except Exception:
                        rank_full = str(c.get("rank"))
                want = f"{rank_full}_of_{suit_full}"
                correct = (got.stem == want)
            if correct:
                ok += 1
            else:
                bad += 1
                problems.append({"card": c.get("name_en") or c.get("name_ja"),
                                 "expected": want, "got": got.name})
        result["decks"][deck_id] = {"total": count, "ok": ok, "wrong": bad,
                                    "unresolved": miss, "problems": problems[:12]}
        print(f"[{deck_id:10s}] 全 {count:3d} 枚 → 正しい画像 {ok:3d} / 誤り {bad:3d} / 未解決 {miss:3d}")

    # ---- runes / omikuji（生成画像）: 全枚の命名一致を確認 ----
    runes_data = json.loads((pkg / "data" / "runes_24.json").read_text(encoding="utf-8"))
    d_runes = assets / "M27_runes"
    if not d_runes.is_dir():
        _skip("M27_runes", "assets ディレクトリがありません")
    if d_runes.is_dir():
        ok = bad = miss = 0
        problems = []
        for i, r in enumerate(runes_data, 1):
            want = f"{i:02d}_{r['name_en']}.webp"
            got = d_runes / want
            if got.exists():
                ok += 1
            else:
                miss += 1
                problems.append({"no": i, "name": r["name_en"], "expected": want})
        result["decks"]["M27_runes"] = {"total": 24, "ok": ok, "wrong": bad,
                                        "unresolved": miss, "problems": problems[:12]}
        print(f"[M27_runes ] 全 24 枚 → 一致 {ok:3d} / 不一致 {bad:3d} / 欠落 {miss:3d}")

    d_omi = assets / "M28_omikuji"
    if not d_omi.is_dir():
        _skip("M28_omikuji", "assets ディレクトリがありません")
    if d_omi.is_dir():
        files = sorted(f.name for f in d_omi.glob("*.webp"))
        ok = len(files)
        miss = max(0, 100 - ok)
        result["decks"]["M28_omikuji"] = {"total": 100, "ok": ok, "wrong": 0,
                                          "unresolved": miss, "problems": []}
        print(f"[M28_omikuji] 全 100 枚 → 配置 {ok:3d} / 欠落 {miss:3d}")

    d_kip = assets / "M27_kipper"
    if not (d_kip.is_dir() and any(d_kip.glob("*.webp"))):
        _skip("M27_kipper", "画像が0枚（ディレクトリなし or 空）")
    if d_kip.is_dir() and any(d_kip.glob("*.webp")):
        kip = json.loads((pkg / "data" / "kipper_36.json").read_text(encoding="utf-8"))
        ok = miss = 0
        problems = []
        for c in kip:
            want = f"{c['no']:02d}_{c['name_en'].replace(' ', '')}.webp"
            if (d_kip / want).exists():
                ok += 1
            else:
                miss += 1
                problems.append({"no": c["no"], "expected": want})
        result["decks"]["M27_kipper"] = {"total": 36, "ok": ok, "wrong": 0,
                                         "unresolved": miss, "problems": problems[:6]}
        _tail = "" if miss == 0 else "（生成進行中）"
        print(f"[M27_kipper] 全 36 枚 → 配置 {ok:3d} / 欠落 {miss:3d}{_tail}")

    # ---- oracle / angel（生成画像・進行中）: 番号＋英名の一致を確認 ----
    for _deck, _fname, _key in (("M27_oracle", "oracle_44.json", "M27_oracle"),
                                ("M27_angel", "angel_44.json", "M27_angel")):
        d_dec = assets / _deck
        if not d_dec.is_dir() or not any(d_dec.glob("*.webp")):
            _skip(_deck, "画像が0枚（ディレクトリなし or 空）")
            continue
        cards = json.loads((pkg / "data" / _fname).read_text(encoding="utf-8"))
        by_no = {}
        for f in d_dec.glob("*.webp"):
            try:
                by_no[int(f.name[:2])] = f.name
            except ValueError:
                continue
        ok = miss = 0
        problems = []
        for c in cards:
            want_prefix = f"{c['no']:02d}_"
            if str(by_no.get(c["no"], "")).startswith(want_prefix):
                ok += 1
            else:
                miss += 1
                if len(problems) < 6:
                    problems.append({"no": c["no"], "expected_prefix": want_prefix,
                                     "found": by_no.get(c["no"], None)})
        result["decks"][_key] = {"total": len(cards), "ok": ok, "wrong": 0,
                                 "unresolved": miss, "problems": problems}
        _tail = "" if miss == 0 else "（生成進行中）"
        print(f"[{_deck:<9}] 全 {len(cards):2d} 枚 → 配置 {ok:3d} / 欠落 {miss:3d}{_tail}")

    # ---- M09_animal（60枚）: 番号＋英名（animals_60_profiles.json）の一致 ----
    d_an = assets / "M09_animal"
    if not (d_an.is_dir() and any(d_an.glob("*.webp"))):
        _skip("M09_animal", "画像が0枚（ディレクトリなし or 空）")
    if d_an.is_dir() and any(d_an.glob("*.webp")):
        prof = json.loads((pkg / "data" / "animals_60_profiles.json").read_text(encoding="utf-8"))["items"]
        want = {int(i["no"]): i["animal_en"].replace(" ", "").lower() for i in prof}
        present = {}
        for f in d_an.glob("*.webp"):
            try:
                present[int(f.name[:2])] = f.name
            except ValueError:
                continue
        ok = wrong = miss = 0
        problems = []
        for no, en in sorted(want.items()):
            fn = present.get(no)
            if fn is None:
                miss += 1
                continue
            if _norm(Path(fn).stem).endswith(_norm(en)):
                ok += 1
            else:
                wrong += 1
                if len(problems) < 6:
                    problems.append({"no": no, "expected_name": en, "found": fn})
        result["decks"]["M09_animal"] = {"total": len(want), "ok": ok, "wrong": wrong,
                                         "unresolved": miss, "problems": problems}
        print(f"[M09_animal] 全 {len(want):2d} 種 → 正しい画像 {ok:3d} / 誤り {wrong:3d} / 未解決 {miss:3d}")

    # ---- M33_genekeys（64枚）: ゲート番号＋アーキタイプSlug の一致 ----
    d_gk = assets / "M33_genekeys"
    if not (d_gk.is_dir() and any(d_gk.glob("*.webp"))):
        _skip("M33_genekeys", "画像が0枚（ディレクトリなし or 空）")
    if d_gk.is_dir() and any(d_gk.glob("*.webp")):
        arch = json.loads((pkg / "data" / "genekeys_64_archetypes.json").read_text(encoding="utf-8"))["items"]
        want = {int(i["no"]): i["slug"] for i in arch}
        present = {}
        for f in d_gk.glob("*.webp"):
            try:
                present[int(f.name[:2])] = f.name
            except ValueError:
                continue
        ok = wrong = miss = 0
        problems = []
        for no, slug in sorted(want.items()):
            fn = present.get(no)
            if fn is None:
                miss += 1
                continue
            if _norm(Path(fn).stem).endswith(_norm(slug)):
                ok += 1
            else:
                wrong += 1
                if len(problems) < 6:
                    problems.append({"no": no, "expected_slug": slug, "found": fn})
        result["decks"]["M33_genekeys"] = {"total": len(want), "ok": ok, "wrong": wrong,
                                           "unresolved": miss, "problems": problems}
        print(f"[M33_genekeys] 全 {len(want):2d} 鍵 → 正しい画像 {ok:3d} / 誤り {wrong:3d} / 未解決 {miss:3d}")

    # ---- M02_seiza（12星座）/ M01_eto（12支）: 番号＋英名の一致 ----
    _SEIZA = [("牡羊座", "Aries"), ("牡牛座", "Taurus"), ("双子座", "Gemini"), ("蟹座", "Cancer"),
              ("獅子座", "Leo"), ("乙女座", "Virgo"), ("天秤座", "Libra"), ("蠍座", "Scorpio"),
              ("射手座", "Sagittarius"), ("山羊座", "Capricorn"), ("水瓶座", "Aquarius"), ("魚座", "Pisces")]
    # mts5.7: M08_blood は画像をオミットしたため監査対象から外し、M01_eto（12支）を追加
    _ETO = [("子", "Rat"), ("丑", "Ox"), ("寅", "Tiger"), ("卯", "Rabbit"),
            ("辰", "Dragon"), ("巳", "Snake"), ("午", "Horse"), ("未", "Goat"),
            ("申", "Monkey"), ("酉", "Rooster"), ("戌", "Dog"), ("亥", "Boar")]
    # mts5.8: 型D の小デッキ（ペンデュラム3・水晶玉1）も番号＋英名で検証
    _PENDULUM = {1: "Yes", 2: "No", 3: "Neutral"}
    _CRYSTALBALL = {1: "Scrying"}
    # mts5.9: クリスタル12石も番号＋英名で検証 / mts5.13: パワーストーン（誕生石）と画像共有し全21石へ拡充
    _CRYSTAL = {1: "Amethyst", 2: "ClearQuartz", 3: "RoseQuartz", 4: "Citrine",
                5: "Aventurine", 6: "LapisLazuli", 7: "Turquoise", 8: "Onyx",
                9: "Fluorite", 10: "Carnelian", 11: "Moonstone", 12: "Garnet",
                13: "Aquamarine", 14: "Diamond", 15: "Emerald", 16: "Pearl",
                17: "Ruby", 18: "Peridot", 19: "Sapphire", 20: "Opal", 21: "Topaz"}
    # mts5.10: アフリカ（開きの数 0〜8 の9枚）とタリスマン（固定1枚）も検証
    _AFRICAN = {i + 1: f"Open{i}" for i in range(9)}
    _TALISMAN = {1: "Talisman"}
    # mts5.13: メソポタミア天体オーメン（EAE 24枚）も番号＋slugで検証
    _MESO = {
        1: "CrescentMoon", 2: "CrownedMoon", 3: "EquinoctialSun", 4: "DarkenedMoon",
        5: "ClosedLunarHalo", 6: "BroadLunarHalo", 7: "MoonAndPleiades", 8: "StarInLunarHorn",
        9: "UnequalLunarHorns", 10: "SharpLunarHorn", 11: "FlamingSun", 12: "ObscuredSun",
        13: "JupiterAtSunrise", 14: "MorningStarVenus", 15: "EveningStarVenus", 16: "BlazingMars",
        17: "SaturnNearMoon", 18: "MercuryInSeason", 19: "EveningLunarEclipse", 20: "DarkEclipseDay",
        21: "ShootingStar", 22: "ThunderInClearSky", 23: "RainbowInSky", 24: "OppositionFullMoon"
    }
    # mts5.13: キリスト教的黙想（新約聖書24章句）も番号＋slugで検証
    _CHRISTIAN = {
        1: "LiliesOfTheField", 2: "OpenDoorAndKey", 3: "TreasureOfTheHeart",
        4: "ShepherdStaffAndWaters", 5: "DoveOfPeace", 6: "GoldenGrainOfWheat",
        7: "OverflowingChalice", 8: "HourglassOfGrace", 9: "OpenBookAndBrokenChain",
        10: "CalmingOfTheWaters", 11: "FallenSeedAndSprout", 12: "RefinerFireAndGold",
        13: "GoldenCenserOfPrayer", 14: "FlameOfCharity", 15: "AnchorOfHope",
        16: "RockOfRefuge", 17: "LightInEarthenVessel", 18: "TheTrueVine",
        19: "GoldenHarpOfPraise", 20: "WingsOfEagles", 21: "CelestialAstrolabe",
        22: "OilLampOfWisdom", 23: "BeaconOfFaith", 24: "GentleLambInHands"
    }
    # mts5.13: 籤占（アストラガロイ 4面）
    _ASTRAGALOI = {
        1: "Chios_1", 2: "Trias_3", 3: "Tetras_4", 4: "Stron_6"
    }
    # mts5.13: 肝占（バールートゥ 固定1枚）
    _HARUSPEX = {1: "ClayLiver"}
    # mts5.14: P6 古代託宣群（鳥占5変種・デルポイ5変種。結果と無関係のランダム表示）
    _ORNITH = {1: "HawkEast", 2: "DoveSouth", 3: "CrowWest", 4: "SwallowCircle", 5: "OwlNight"}
    _DELPHI = {1: "Tripod", 2: "LaurelCrown", 3: "CastaliaSpring", 4: "ZeusEagle", 5: "Omphalos"}
    for _deck, _want in (("M02_seiza", {i: en for i, (ja, en) in enumerate(_SEIZA, start=1)}),
                         ("M01_eto", {i: en for i, (ja, en) in enumerate(_ETO, start=1)}),
                         ("M29_pendulum", dict(_PENDULUM)),
                         ("M30_crystalball", dict(_CRYSTALBALL)),
                         ("M30_crystal", dict(_CRYSTAL)),
                         ("M29_african", dict(_AFRICAN)),
                         ("M30_talisman", dict(_TALISMAN)),
                         ("M30_meso", dict(_MESO)),
                         ("M30_christian", dict(_CHRISTIAN)),
                         ("M28_astragaloi", dict(_ASTRAGALOI)),
                         ("M30_haruspex", dict(_HARUSPEX)),
                         ("M30_ornith", dict(_ORNITH)),
                         ("M30_delphi", dict(_DELPHI))):
        d_dec = assets / _deck
        if not d_dec.is_dir() or not any(d_dec.glob("*.webp")):
            _skip(_deck, "画像が0枚（ディレクトリなし or 空）")
            continue
        present = {}
        for f in d_dec.glob("*.webp"):
            try:
                present[int(f.name[:2])] = f.name
            except ValueError:
                continue
        ok = wrong = miss = 0
        problems = []
        for no, name in sorted(_want.items()):
            fn = present.get(no)
            if fn is None:
                miss += 1
                continue
            if _norm(Path(fn).stem).endswith(_norm(name)):
                ok += 1
            else:
                wrong += 1
                if len(problems) < 6:
                    problems.append({"no": no, "expected": name, "found": fn})
        result["decks"][_deck] = {"total": len(_want), "ok": ok, "wrong": wrong,
                                  "unresolved": miss, "problems": problems}
        _tail = "" if miss == 0 else "（生成進行中）"
        print(f"[{_deck:<10}] 全 {len(_want):2d} 枚 → 正しい画像 {ok:3d} / 誤り {wrong:3d} / 未解決 {miss:3d}{_tail}")

    # ---- 卦系（meihua / iching）: 64卦すべて ----
    for sub in ("M23_meihua", "M26_iching"):
        d = assets / sub
        if not d.is_dir():
            result["decks"][sub] = {"error": "assets dir not found"}
            _skip(sub, "assets ディレクトリがありません")
            continue
        ok = bad = miss = 0
        problems = []
        for hx in iching:
            no = hx["kingwen_no"]
            if sub == "M23_meihua":
                got = _find_meihua_image_file(no, d)
            else:
                cands = list(d.glob(f"{no:02d}_*.webp")) + list(d.glob(f"{no:02d}_*.jpg"))
                got = cands[0] if cands else None
            if got is None:
                miss += 1
                problems.append({"no": no, "name": hx["name_ja"], "issue": "unresolved"})
                continue
            if got.stem.startswith(f"{no:02d}_"):
                ok += 1
            else:
                bad += 1
                problems.append({"no": no, "name": hx["name_ja"], "got": got.name})
        result["decks"][sub] = {"total": 64, "ok": ok, "wrong": bad,
                                "unresolved": miss, "problems": problems[:12]}
        print(f"[{sub:10s}] 全 64 卦 → 正しい画像 {ok:3d} / 誤り {bad:3d} / 未解決 {miss:3d}")

    # ---- mts5.52（F-7）: 合否の集計・必須デッキの欠落・--strict の終了コード ----
    wrong_total = sum(int(v.get("wrong") or 0) for v in result["decks"].values())
    unresolved_total = sum(int(v.get("unresolved") or 0) for v in result["decks"].values())
    # カード系は結果JSONのキーがデッキID（tarot 等）なので、ディレクトリ名へ寄せて数える
    _alias = {"tarot": "M27_tarot", "marseille": "M27_marseille",
              "lenormand": "M27_lenormand", "cartomancy": "M27_cartomancy"}
    inspected = {_alias.get(k, k) for k, v in result["decks"].items()
                 if "error" not in v}
    missing_required = [d for d in REQUIRED_DECKS if d not in inspected]
    result["totals"] = {"wrong": wrong_total, "unresolved": unresolved_total,
                        "decks_inspected": len(inspected),
                        "decks_required": len(REQUIRED_DECKS),
                        "required_missing": missing_required,
                        "skipped": result["skipped"], "strict": bool(args.strict)}
    print(f"\n[合計] 誤り {wrong_total} / 未解決 {unresolved_total} / "
          f"検査したデッキ {len(inspected)}（対象 {len(REQUIRED_DECKS)}）"
          + (f"・未検査 {len(result['skipped'])}" if result["skipped"] else ""))
    if missing_required:
        print(f"[欠落] 必須デッキのうち検査できなかったもの: {', '.join(missing_required)}"
              "（assets/images の欠落。従来は無言でスキップしていました）")
    if args.strict and (wrong_total or unresolved_total or missing_required
                        or result["skipped"]):
        print("[不合格] --strict: 誤り・未解決・欠落があります")
    elif args.strict:
        print("[合格] --strict: 誤り0・未解決0・欠落0")
    else:
        print("[参考] 既定では終了コードに反映しません（--strict で不合格にできます）")

    out = ROOT / "verify" / "out_audit"
    out.mkdir(parents=True, exist_ok=True)
    name = pkg.name if pkg.name != "fortune_dataset" else "fortune_dataset"
    if "work" in pkg.parts:
        name = "mts47_original"
    path = out / f"{name}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[result] {path}")
    if args.strict and (wrong_total or unresolved_total or missing_required
                        or result["skipped"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
