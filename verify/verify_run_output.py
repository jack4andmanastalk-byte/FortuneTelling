# -*- coding: utf-8 -*-
"""実行成果物（Kaggle の results ZIP / HTML レポート）の画像埋め込み検証

目的:
  本番実行で「結果の内容」と「埋め込まれた画像」がずれていないかを機械的に確認する。
  runes の実例（2026-09-24 の実行で発見）: 位置1 ウンジョ（Wunjo）に対して 01_Fehu が
  埋め込まれていた（card_id=抽選順を石の番号と誤解した充当）。この種の誤充当は
  「キャプションの名前 ≠ 画像ファイル名」を突き合わせれば自動検出できる。

検証する4点:
  1. バイト一致      … 埋め込み画像が assets/images の納品画像と同一か（再エンコード/別画像の検出）
  2. 名前の整合      … キャプションの名前トークンが画像ファイル名に現れるか（誤充当の検出）
  3. 網羅            … **欠落の検出**（mts5.52）。キャプションが 0 件なら不合格。実行の生JSON
                       があるデッキは画像が 1 枚以上あること、カード系は引いた枚数以上あることを検査。
                       `--expect-images`／`--expect-decks` で明示の期待値も指定できる。
  4. 型Cの内容        … calc 再生成との画素照合（豆腐＝文字欠けは**1文字でも**検出・mts5.52）

使い方:
  python3 verify/verify_run_output.py --html <report.html> --assets fortune_dataset/assets/images
  python3 verify/verify_run_output.py --results-zip <results.zip> \
      --assets fortune_dataset/assets/images [--json-out verify/out_audit/run_output_verify.json]

  # パッケージ（ソースのみの ZIP）だけで照合表を作る場合（画像なしZIPでも可・mts5.6 で対応）
  python3 verify/verify_run_output.py --results-zip <results.zip> \
      --assets fortune_dataset/assets/images --pkg /home/user/fortune_dataset.zip

  # 期待値を明示する場合（例: Kaggle手順書の87枚・48デッキ）
  python3 verify/verify_run_output.py --results-zip <results.zip> \
      --assets fortune_dataset/assets/images --pkg fortune_dataset \
      --expect-images 87 --expect-decks 48

`--pkg` は **cwd 相対でなくても解決できます**（mts5.52）。指定値・スクリプト基準・`--assets` から
逆算した位置を順に試し、`data/*.json` と `fortunelib/chartdraw.py` の**両方**が読めた場所を使います。
どこにも解決できない場合、型Cの画像がある実行では**警告ではなく exit 2 で停止**します
（従来は「警告して続行」＝型C 22 枚が誤って『納品画像と一致しない』になっていました）。

終了コード（mts5.52）:
  0 = 合格（不合格なし。`--strict` なら警告もなし）
  1 = 不合格（画像の不一致／照合不能／網羅の欠落。`--strict` では警告も不合格）
  2 = 検証を実施できない（型Cの照合に必要な fortunelib・画像アセットを解決できない）
  ※ トーン・レイアウト・読み物版・デッキ数の下限は「■ 警告」として表示
    （既定では終了コードに影響しません。`--strict` で不合格にできます）。

注意: デッキ別の枚数は**キャプションの見出し**（【梅花易数】【易】…）で帰属させます。
  M23_meihua と M26_iching は64枚がバイト同一（同じ卦の絵を両デッキで共用）のため、
  画像ハッシュからの逆引きだけでは両者を区別できません（mts5.4 で修正）。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

IMG_EXT = {".webp", ".jpg", ".jpeg", ".png"}
PAIR_RE = re.compile(
    r'<img src="data:image/(\w+);base64,([A-Za-z0-9+/=]+)"[^>]*>\s*'
    r'<div class="fortune-image-caption">(.*?)</div>', re.S)
CJK_RUN = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]{2,}")
LATIN_TOKEN = re.compile(r"[A-Za-z]{4,}")
# 英字＋数字のトークン（例: Open3）。英字だけの LATIN_TOKEN では数字が落ちるため別に拾う（mts5.10）。
# アフリカの「開き N 枚（OpenN）」のように**番号で誤りを検出したい**キャプションで必要。
ALNUM_TOKEN = re.compile(r"[A-Za-z]{2,}\d+")
# 名前ではない語（キャプションの見出し・型名など）は照合対象から外す
STOPWORDS = {"type", "types", "the", "of", "and", "position", "card", "cards", "key", "keys"}
# キャプション見出し → デッキの対応（デッキ別枚数の集計に使う）
# なぜ必要か（mts5.4 で修正）: M23_meihua と M26_iching は**64枚がバイト同一**（同じ卦の絵を両デッキで共用）ため、
# 画像ハッシュからの逆引きでは「梅花易数の本卦」と「易の本卦」を区別できず、デッキ別の枚数が入れ替わって
# 表示されていた（バイト一致・名前整合の判定自体は正しい）。キャプションの見出しを優先して帰属させる。
CAPTION_DECK = [
    ("梅花易数", "M23_meihua"),
    ("【易】", "M26_iching"),
    ("タロット", "M27_tarot"),
    ("マルセイユ", "M27_marseille"),
    ("レノルマン", "M27_lenormand"),
    ("カルトマンシー", "M27_cartomancy"),
    ("キッパー", "M27_kipper"),
    ("ルーン", "M27_runes"),
    ("オラクル", "M27_oracle"),
    ("エンジェル", "M27_angel"),
    ("おみくじ", "M28_omikuji"),
    ("動物占い", "M09_animal"),
    ("ジーンキーズ", "M33_genekeys"),
    ("星座占い", "M02_seiza"),
    ("干支", "M01_eto"),
    ("ペンデュラム", "M29_pendulum"),
    ("水晶玉", "M30_crystalball"),
    ("クリスタル", "M30_crystal"),
    ("アフリカ占い", "M29_african"),
    ("タリスマン", "M30_talisman"),
    ("鳥占", "M30_ornith"),          # mts5.14: P6 古代託宣群
    ("デルポイの託宣", "M30_delphi"),  # mts5.14: P6 古代託宣群
    # M08_blood（血液型）は mts5.7 で画像をオミットしたため帰属先から外した（下の OMITTED_DECKS を参照）
]

# 画像を**意図的にオミットしたデッキ**（mts5.7 のユーザー決定）。旧い実行結果には画像が残っているため
# 「納品画像と一致しない」になるが、これは想定内なので問題（problems）ではなく参考として報告する。
OMITTED_DECKS = {
    "血液型": "M08_blood（血液型は mts5.7 で画像をオミット。原画は assets_bases/blood/_clean に退避）",
}


def norm(text: str) -> str:
    """英数字だけを残して小文字化（ファイル名・名前トークンの比較用）"""
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


ESC_STEM = re.compile(r"^(?:\d{1,2}_)?((?:U[0-9a-fA-F]{4})+)$")
RANK_JA = {"エース": "Ace", "ジャック": "Jack", "クイーン": "Queen", "キング": "King"}
SUIT_JA = {"H": "Hearts", "D": "Diamonds", "S": "Spades", "C": "Clubs"}


def decode_escaped_stem(stem: str) -> str:
    """M23_meihua / M26_iching のファイル名（例 10_U5929U6fa4U5c65）を漢字へ復号する。

    これらは卦名を U+XXXX の連なりで持つため、キャプションの漢字と直接照合できる
    （mts5.4 で追加。以前は「判定不能」として素通りしていた）。
    """
    m = ESC_STEM.match(stem)
    if not m:
        return ""
    return "".join(chr(int(x, 16)) for x in re.findall(r"U([0-9a-fA-F]{4})", m.group(1)))


def pkg_data_loader(pkg):
    """パッケージ直下（**ディレクトリ**または**ZIP**）から `data/<name>` を読む関数を返す。

    mts5.6 で ZIP にも対応した（ソースのみの ZIP は画像を含まないため、ZIP単体でも
    照合表を作れるようにするため）。読めない場合は None を返す。
    """
    if pkg is None:
        return None
    p = Path(pkg)
    # ディレクトリ指定は、`data/` が直下にある場合と、配布ZIPと同じ二重階層
    # （`<pkg>/fortune_dataset/data/…`）の場合の両方を受け付ける（mts5.10 で追加。
    # 「リポジトリ直下」を指定しがちで、そのとき照合表が空になり
    # 和名だけのキャプションが判定不能に落ちていた）。
    for base in (p, p / "fortune_dataset"):
        if base.is_dir() and (base / "data").is_dir():
            def _load(name, _base=base):
                try:
                    return json.loads((_base / "data" / name).read_text(encoding="utf-8"))
                except Exception:
                    return None
            return _load
    if p.is_file() and p.suffix.lower() in (".zip", ".txt"):
        try:
            z = zipfile.ZipFile(p)
            names = z.namelist()
        except Exception:
            return None
        # ZIP はトップに `fortune_dataset/` が入る構成（`fortune_dataset/fortune_dataset/data/…`）も
        # あるため、`*/data/<name>` の末尾一致で探す。
        def _load(name):
            tail = f"/data/{name}"
            for n in names:
                if n.endswith(tail):
                    try:
                        return json.loads(z.read(n).decode("utf-8"))
                    except Exception:
                        return None
            return None
        return _load
    return None


def _pkg_lib_dir(pkg) -> Path | None:
    """`fortunelib` を import できるディレクトリを返す（mts5.52）。"""
    if pkg is None:
        return None
    p = Path(pkg)
    if p.is_dir():
        for c in (p, p / "fortune_dataset"):
            if (c / "fortunelib" / "chartdraw.py").is_file():
                return c
    return None


def pkg_is_usable(pkg) -> bool:
    """`--pkg` の候補として「data/*.json と fortunelib の**両方**が読める」か（mts5.52）。

    片方しか読めない組み合わせは、型Cの再生成照合が静かに落ちて
    「納品画像と一致しない」という**誤報**になるため候補にしない（F-2）。
    """
    return pkg_data_loader(pkg) is not None and _pkg_lib_dir(pkg) is not None


def _pkg_candidates(explicit, assets, script_dir: Path) -> list[Path]:
    """`--pkg` の解決候補を優先順に並べる（mts5.52・F-2）。

    指定があるとき（**その指定の中でだけ**探す。勝手に別のパッケージへは移らない）:
      指定値（cwd 相対）→ 指定値 + `/fortune_dataset` → スクリプト基準の同じ相対位置。
    指定が無いとき（自動解決）: `--assets` から逆算 → cwd 相対の慣用名 → スクリプト基準。
    """
    cands: list[Path] = []

    def add(p):
        if p is None:
            return
        q = Path(p)
        if q not in cands:
            cands.append(q)

    if explicit:
        base = Path(explicit)
        root = script_dir.parent                      # リポジトリ直下
        add(base)
        add(base / "fortune_dataset")
        add(root / base)
        add(root / base / "fortune_dataset")
    else:
        if assets is not None:
            a = Path(assets)
            add(a.parent)                             # …/<pkg>/assets/images → …/<pkg>
            if a.parent.name == "assets":
                add(a.parent.parent / "fortune_dataset")
                add(a.parent.parent)
        for rel in ("fortune_dataset", "fortune_dataset/fortune_dataset", "."):
            add(Path(rel))
        add(script_dir.parent)
        add(script_dir.parent / "fortune_dataset")
    return cands


_ZIP_KEEP_TOP = ("fortunelib", "data", "assets")


def _materialize_zip_pkg(zpath) -> Path | None:
    """ZIP の中のパッケージを一時ディレクトリへ展開し、`fortunelib` を import できる形にする（mts5.52）。

    ZIP 単体では `fortunelib` を import できないため、型Cの再生成照合ができず
    「納品画像と一致しない」という誤報になっていた（F-2 の一因）。
    展開するのは fortunelib・data・assets/fonts・assets/images だけで、終了時に削除する。
    """
    import atexit
    import shutil
    import tempfile
    try:
        z = zipfile.ZipFile(zpath)
        names = z.namelist()
    except Exception:
        return None
    roots = {n[: -len("fortunelib/chartdraw.py")] for n in names
             if n.endswith("fortunelib/chartdraw.py")}
    if not roots:
        return None
    root = sorted(roots, key=len)[0]
    try:
        tmp = Path(tempfile.mkdtemp(prefix="vro_pkg_"))
    except Exception:
        return None
    atexit.register(shutil.rmtree, tmp, True)
    for n in names:
        if not n.startswith(root) or n.endswith("/"):
            continue
        rel = n[len(root):]
        top = rel.split("/", 1)[0]
        if top not in _ZIP_KEEP_TOP:
            continue
        if top == "assets" and not (rel.startswith("assets/fonts/")
                                    or rel.startswith("assets/images/")):
            continue
        try:
            dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(z.read(n))
        except Exception:
            continue
    return tmp if (tmp / "fortunelib" / "chartdraw.py").is_file() else None


def resolve_pkg(explicit, assets, script_dir: Path | None = None) -> tuple[Path | None, list[Path]]:
    """(使える pkg, 試した候補) を返す（mts5.52・F-2 の推奨①）。

    実行ディレクトリに依存せず、**data と fortunelib の両方が読めた最初の候補**を使う。
    どれも読めなければ None（呼び出し側が「警告」か「exit 2」を決める）。
    """
    script_dir = script_dir or Path(__file__).resolve().parent
    tried = _pkg_candidates(explicit, assets, script_dir)
    for c in tried:
        if pkg_is_usable(c):
            return c, tried
        if Path(c).is_file():                      # ZIP は一時展開してから判定（mts5.52）
            mat = _materialize_zip_pkg(c)
            if mat is not None and pkg_is_usable(mat):
                return mat, tried
    return None, tried


def build_name_tables(pkg) -> dict[str, dict]:
    """package の data/*.json から「和名 → 英名 / 番号 / 型」の照合表を作る（mts5.4 で追加）。

    目的: キャプションが和名だけのデッキ（キッパー・レノルマン・カルトマンシー・
    オラクル・エンジェル・おみくじ・血液型）でも「キャプション ⇄ 画像ファイル名」を
    検証できるようにする。データが読めない場合は空表を返し、従来どおり判定不能に落とす。
    """
    tables: dict[str, dict] = {"ja2en": dict(FIXED_JA2EN), "ja2en_by_deck": {},
                               "card": {}, "omikuji": {},
                               "seiza": zodiac_table(_pkg_lib_dir(pkg))}   # mts5.64
    _load = pkg_data_loader(pkg)
    if _load is None:
        return tables

    for fn in ("kipper_36.json", "lenormand_36.json", "oracle_44.json", "angel_44.json"):
        items = _load(fn)
        if isinstance(items, list):
            deck = FILE_TO_DECK.get(fn)
            bucket = tables["ja2en_by_deck"].setdefault(deck, {}) if deck else None
            for x in items:
                ja, en = x.get("name_ja"), x.get("name_en") or ""
                if ja and en:
                    en0 = en.split("・")[0].strip()
                    tables["ja2en"].setdefault(ja, en0)
                    if bucket is not None:
                        # mts5.51: 同名カード（例「思いやり」＝oracle 40 Compassion／
                        # angel 43 Kindness）を取り違えないよう、デッキ別にも持つ。
                        bucket.setdefault(ja, en0)

    for x in (_load("cartomancy_52.json") or []):
        ja = x.get("name_ja")
        if not ja:
            continue
        rank = RANK_JA.get(x.get("rank_name"), None)
        if rank is None:
            try:
                rank = f"{int(x.get('rank_name')):02d}"
            except (TypeError, ValueError):
                continue
        suit = SUIT_JA.get(x.get("suit"))
        if suit:
            tables["card"][ja] = f"{rank}_of_{suit}"

    for i, x in enumerate(_load("omikuji_12.json") or [], start=1):
        if x.get("level"):
            tables["omikuji"][x["level"]] = i
    return tables


def check_caption_by_tables(caption: str, stem: str, tables: dict,
                            decoded: str) -> bool | None:
    """和名だけのキャプションを照合する。True=一致 / False=不一致 / None=判定不能

    照合の順序:
      1) U+エスケープ名（卦名）との照合（例: 本卦：天澤履 → 10_U5929U6fa4U5c65）
      2) 和名 → 英名（キッパー・レノルマン・オラクル・エンジェル）
      3) 和名 → ファイル名（カルトマンシー: ハートのエース → Ace_of_Hearts）
      4) おみくじ: 段階名 → 12段階の番号（ファイル名の先頭2桁）
      5) 血液型: 「Type X」の型字
    表のキーは**キャプションへの部分一致**で探す（「家」「鎌」のような1文字の和名や
    「ダイヤの2」のような数字混じりの名前でも拾えるようにするため。mts5.4 で修正）。
    """
    runs = CJK_RUN.findall(caption)
    target = norm(stem)

    # 1) U+エスケープ名（卦名）との照合
    if decoded and any(r in decoded for r in runs):
        return True

    matched_any = bool(decoded)

    # 2) 和名 → 英名（デッキ固有の対応を優先。mts5.51）
    deck = next((d for mark, d in CAPTION_DECK if mark in caption), None)
    pairs = list(tables.get("ja2en_by_deck", {}).get(deck, {}).items()) if deck else []
    seen = {ja for ja, _ in pairs}
    pairs.extend((ja, en) for ja, en in tables["ja2en"].items() if ja not in seen)
    for ja, en in pairs:
        if ja and ja in caption:
            matched_any = True
            if en and norm(en) in target:
                return True

    # 3) 和名 → ファイル名（カルトマンシー）
    for ja, base in tables["card"].items():
        if ja and ja in caption:
            matched_any = True
            if norm(base) == target:
                return True

    # 4) おみくじ: 段階名 → 番号
    for ja, no in tables["omikuji"].items():
        if ja and ja in caption:
            matched_any = True
            if stem[:2] == f"{no:02d}":
                return True

    # 5) 血液型: 「Type X」の型字
    if "血液型" in caption:
        m = re.search(r"Type\s*([ABO]{1,2})", caption)
        if m:
            matched_any = True
            if norm(stem).endswith(norm(m.group(1))):
                return True

    # 6) 対応表に載っている名前がキャプションにあったのに一致しなければ「不一致」
    return False if matched_any else None


# 実装側（html_report の _PENDULUM_ORDER・assets/images/M30_pendulum のファイル名）と
# 同じ対応。**キャプションの英名が 4 文字未満（Yes / No）だと英名トークン経路で拾えない**ため、
# 表に固定で持たせて「キャプション ⇄ ファイル名」を検証できるようにする（mts5.8）。
# mts5.51: 和名→英名のデッキ別表を作るための対応（同名カードの衝突対策）
FILE_TO_DECK = {
    "kipper_36.json": "M27_kipper",
    "lenormand_36.json": "M27_lenormand",
    "oracle_44.json": "M27_oracle",
    "angel_44.json": "M27_angel",
}

FIXED_JA2EN = {
    "肯定": "Yes",
    "否定": "No",
    "中立・保留": "Neutral",
    "中立": "Neutral",
    "粘土肝模型": "ClayLiver",  # mts5.15: 肝占（和名だけのキャプション用）
}

# mts5.15: キリスト教的黙想のキャプション「【キリスト教的黙想】{ref}（{theme}）」⇄ ファイル名の照合表
# （data/bible_verses.json 正本と完全合致）
CHRISTIAN_REF = [
    ("マタイ 6:34", 1, "LiliesOfTheField"),
    ("マタイ 7:7", 2, "OpenDoorAndKey"),
    ("マタイ 6:21", 3, "TreasureOfTheHeart"),
    ("マタイ 11:28", 4, "ShepherdStaffAndWaters"),
    ("マタイ 5:9", 5, "DoveOfPeace"),
    ("マルコ 4:28", 6, "GoldenGrainOfWheat"),
    ("ルカ 6:38", 7, "OverflowingChalice"),
    ("ルカ 12:25", 8, "HourglassOfGrace"),
    ("ヨハネ 8:32", 9, "OpenBookAndBrokenChain"),
    ("ヨハネ 14:27", 10, "CalmingOfTheWaters"),
    ("ヨハネ 12:24", 11, "FallenSeedAndSprout"),
    ("ローマ 5:3-4", 12, "RefinerFireAndGold"),
    ("ローマ 12:12", 13, "GoldenCenserOfPrayer"),
    ("コリント一 13:4", 14, "FlameOfCharity"),
    ("コリント一 13:7", 15, "AnchorOfHope"),
    ("コリント一 10:13", 16, "RockOfRefuge"),
    ("コリント二 12:9", 17, "LightInEarthenVessel"),
    ("ガラテヤ 6:9", 18, "TheTrueVine"),
    ("ピリピ 4:6", 19, "GoldenHarpOfPraise"),
    ("ピリピ 4:13", 20, "WingsOfEagles"),
    ("使徒 1:7", 21, "CelestialAstrolabe"),
    ("ヤコブ 1:19", 22, "OilLampOfWisdom"),
    ("ヘブル 11:1", 23, "BeaconOfFaith"),
    ("ペテロ一 5:7", 24, "GentleLambInHands"),
]

# mts5.15: 籤占（アストラガロイ）の出目⇄ファイル名の照合表
ASTRAGALOI_VALUE = {1: (1, "Chios_1"), 3: (2, "Trias_3"), 4: (3, "Tetras_4"), 6: (4, "Stron_6")}

# mts5.64: 星座占い（M02_seiza）の和名 → (番号, 英名)。
# **英名が3文字の獅子座（Leo）だと**、下の英名トークン経路（4文字以上）で拾えず、
# 照合表にも星座が無かったため、**正しい画像が「キャプションの和名が対応しない」と
# 誤報**されていました（mts5.63 の実機＝`demo_asakura_riko` は太陽星座が獅子座。
# 前回 mts5.62 は牡牛座（Taurus＝6文字）だったため偶然通り、潜在していました）。
# 正本は実装側の `fortunelib/calc/zodiac.py`（SIGNS／SIGNS_EN）と
# `fortunelib/html_report.py` の `_SEIZA_ORDER` で、**同じ並び**です
# （読み込めればそちらを優先し、読めない環境ではこの表を使います）。
ZODIAC_FALLBACK: dict[str, tuple[int, str]] = {
    "牡羊座": (1, "Aries"), "牡牛座": (2, "Taurus"), "双子座": (3, "Gemini"),
    "蟹座": (4, "Cancer"), "獅子座": (5, "Leo"), "乙女座": (6, "Virgo"),
    "天秤座": (7, "Libra"), "蠍座": (8, "Scorpio"), "射手座": (9, "Sagittarius"),
    "山羊座": (10, "Capricorn"), "水瓶座": (11, "Aquarius"), "魚座": (12, "Pisces"),
    # 中国語・別表記（実装側の表記ゆれを吸収）
    "白羊座": (1, "Aries"), "金牛座": (2, "Taurus"), "処女座": (6, "Virgo"),
    "天蝎座": (8, "Scorpio"), "人馬座": (9, "Sagittarius"), "磨羯座": (10, "Capricorn"),
    "宝瓶座": (11, "Aquarius"), "双魚座": (12, "Pisces"),
}


def zodiac_table(lib_dir: Path | None) -> dict[str, tuple[int, str]]:
    """星座の和名 → (番号, 英名)。**実装側の正本を優先**して読む（mts5.64）。

    `fortunelib/calc/zodiac.py` の `SIGNS`（月日つき）と `SIGNS_EN`、
    `fortunelib/html_report.py` の `_SEIZA_ORDER`（番号順）から組み立てます。
    どちらも読めない場合は `ZODIAC_FALLBACK` を使います（検証は続行できる）。
    """
    if lib_dir is not None:
        try:
            import importlib
            sys.path.insert(0, str(lib_dir))
            try:
                zodiac_mod = importlib.import_module("fortunelib.calc.zodiac")
                signs_en = dict(getattr(zodiac_mod, "SIGNS_EN", {}) or {})
                order = [ja for _m, _d, ja in getattr(zodiac_mod, "SIGNS", [])]  # 1/20 開始＝山羊座…
                # SIGNS は「1/20 水瓶座」から始まるので、番号は牡羊座＝1 になるよう回す
                if order:
                    i = order.index("牡羊座") if "牡羊座" in order else 0
                    order = order[i:] + order[:i]
                table = {}
                for no, ja in enumerate(order, start=1):
                    en = signs_en.get(ja)
                    if ja and en:
                        table[ja] = (no, en)
                for ja, (fallback_no, en) in ZODIAC_FALLBACK.items():
                    table.setdefault(ja, (fallback_no, en))
                if table:
                    return table
            finally:
                try:
                    sys.path.remove(str(lib_dir))
                except ValueError:
                    pass
        except Exception:
            pass
    return dict(ZODIAC_FALLBACK)


def verify_caption(caption: str, asset: Path | None, tables: dict) -> tuple[str, str]:
    """キャプション ⇄ 画像の対応を検証し (判定, 詳細) を返す。

    判定: "ok"（一致）/ "bad"（誤充当）/ "unknown"（判定不能）
    照合は 2 経路:
      A) キャプションに英名トークン（4文字以上）があればファイル名と突き合わせる
         → ルーンの誤充当（位置1 ウンジョ に 01_Fehu）はこの経路で検出される
      A0) デッキ固有の数値規則（アフリカの「開き N 枚（OpenM）」→ 番号 M+1。mts5.10）
      B) 和名だけのキャプションは data/*.json の対応表・卦名の復号で突き合わせる
         → キッパー/レノルマン/カルトマンシー/オラクル/エンジェル/おみくじ/血液型/易/梅花
    """
    if asset is None:
        return "unknown", ""
    # 鳥占（mts5.14）: 画像は5変種から意図的ランダム（おみくじ感覚・ユーザー決定）で
    # キャプション内容と対応しない → 名前照合の対象外（バイト一致のみで担保）。
    if "【鳥占】" in caption:
        return "unknown", ""
    stem = asset.stem
    fname = norm(stem)

    # デッキ固有の**数値規則**（mts5.10）。英名トークンの照合より先に判定する。
    # アフリカ: キャプション「開き N 枚（OpenM）」→ ファイル番号は M+1、かつ N == M であること。
    # （英字だけの LATIN_TOKEN では `Open4` の数字が落ちるため、番号の取り違えを見逃していた）
    m_afr = re.search(r"開き\s*(\d+)\s*枚（Open(\d+)）", caption)
    if m_afr:
        ja_n, en_n = int(m_afr.group(1)), int(m_afr.group(2))
        if ja_n != en_n:
            return "bad", f"開きの数がキャプション内で不一致（{ja_n} と {en_n}）"
        if stem[:2] != f"{en_n + 1:02d}" or norm(f"Open{en_n}") not in norm(stem):
            return "bad", (f"開き {ja_n} 枚の画像は {en_n + 1:02d}_Open{en_n} であるべき"
                           f"（実際は {asset.name}）")
        return "ok", ""

    # デッキ固有の規則（mts5.12）: タロット等の「（正位置）（逆位置）」注記を外し、
    # カード名の**末尾の英字語**で照合する。英名が3文字（Sun / The Sun など）だと
    # LATIN_TOKEN（4文字以上）で拾えず「判定不能」に落ちていた（mts5.11 の実行検証で判明:
    # 「【タロット】自分自身 The Sun（逆位置）」→ 19_Sun.jpg が判定不能）。
    if re.search(r"（(?:正位置|逆位置)）", caption):
        base = re.sub(r"（(?:正位置|逆位置)）", "", caption)
        words = re.findall(r"[A-Za-z]{3,}", base)
        if words:
            cand = norm(words[-1])
            if cand in fname:
                return "ok", ""
            return "bad", f"カード名 {words[-1]} が {asset.name} と一致しない"

    # mts5.15: メソポタミア天体オーメン「EAE-NN」→ ファイル番号 NN（数値規則）
    m_eae = re.search(r"EAE-(\d{2})", caption)
    if m_eae:
        if stem[:2] == m_eae.group(1):
            return "ok", ""
        return "bad", f"EAE-{m_eae.group(1)} の画像は {m_eae.group(1)}_ で始まるべき（実際は {asset.name}）"

    # mts5.15: 籤占「第K骨：Nの目」→ 出目 N に対応するファイル（数値規則）
    m_ast = re.search(r"第\d+骨：(\d+)の目", caption)
    if m_ast:
        v = int(m_ast.group(1))
        if v in ASTRAGALOI_VALUE:
            no, name = ASTRAGALOI_VALUE[v]
            if stem[:2] == f"{no:02d}" and norm(name) in fname:
                return "ok", ""
            return "bad", f"{v}の目の画像は {no:02d}_{name} であるべき（実際は {asset.name}）"
        return "unknown", ""

    # mts5.15: キリスト教的黙想「{ref}（{theme}）」→ 番号＋slug（照合表）
    for ref, no, slug in CHRISTIAN_REF:
        if ref and ref in caption:
            if stem[:2] == f"{no:02d}" and norm(slug) in fname:
                return "ok", ""
            return "bad", f"{ref} の画像は {no:02d}_{slug} であるべき（実際は {asset.name}）"

    # mts5.64: 星座占い「【星座占い】獅子座（Leo）7/23 - 8/22」。
    # 英名が3文字（Leo）だと下の英名トークン経路（4文字以上）で拾えないため、
    # **和名・英名・番号の3点**で検証する（和名と英名の食い違いも検出する）。
    if "星座占い" in caption:
        for ja, (no, en) in (tables.get("seiza") or ZODIAC_FALLBACK).items():
            if ja in caption:
                m_en = re.search(r"[（(]([A-Za-z]{3,})[）)]", caption)
                if m_en and norm(m_en.group(1)) != norm(en):
                    return "bad", (f"キャプションの英名 {m_en.group(1)} が {ja}（{en}）と"
                                   f"一致しない（実際は {asset.name}）")
                if stem[:2] == f"{no:02d}" and norm(en) in fname:
                    return "ok", ""
                return "bad", (f"{ja} の画像は {no:02d}_{en} であるべき"
                               f"（実際は {asset.name}）")
        return "unknown", ""

    toks = [x for x in LATIN_TOKEN.findall(caption) if x.lower() not in STOPWORDS]
    if toks:
        if any(t.lower() in fname for t in toks):
            # 英字＋数字（Open3 等）は数字まで含めて検証する（誤った枚数・番号を検出）
            for a in ALNUM_TOKEN.findall(caption):
                if norm(a) not in fname:
                    return "bad", f"番号付きトークン {a} が {asset.name} と一致しない"
            return "ok", ""
        return "bad", f"英名トークン {toks} が {asset.name} に見つからない"
    verdict = check_caption_by_tables(caption, stem, tables, decode_escaped_stem(stem))
    if verdict is True or any(r in stem for r in CJK_RUN.findall(caption)):
        return "ok", ""
    if verdict is False:
        return "bad", f"キャプションの和名が {asset.name} と対応しない"
    return "unknown", ""


def load_asset_index(assets_root: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for p in assets_root.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMG_EXT:
            name = p.name.split(".", 2)
            stem = norm(p.stem)
            index.setdefault(stem, p)
    return index


def load_hash_index(assets_root: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for p in assets_root.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMG_EXT:
            index.setdefault(hashlib.sha256(p.read_bytes()).hexdigest(), p)
    return index


# ---- 型C 動的検証（mts5.16） ---------------------------------------------
# 型Cチャートは実行時に calc から描画されるため納品画像とバイト一致しない。
# 代わりに results の *_raw.json の calc から chartdraw で再生成し、
# ピクセル差の許容範囲内で照合する（フォントは同梱サブセットで決定的）。
# 長い見出しを先に（【数秘術（氏名）】が【数秘術】に先勝ちするため）
TYPEC_CAPTION_SLUG = [
    ("【九星気学】", "M03_kyusei"),
    ("【カバラ数秘術】", "M06_kabbalah"),
    ("【数秘術（氏名）】", "M05_numerology_name"),
    ("【カルデア数秘術】", "M07_chaldean"),
    ("【タントラ数秘術】", "M04_tantra"),
    ("【アンカ・シャーストラ】", "M04_anka"),
    ("【六星占術】", "M10_rokusei"),
    ("【ウェトン】", "M14_weton"),
    ("【プリンボン・ジャワ】", "M13_primbon"),
    ("【姓名判断】", "M16_seimei"),
    ("【四柱推命】", "M17_bazi"),
    ("【ヴェーダ占星術】", "M19_vedic"),
    ("【算命学】", "M21_sanmei"),
    ("【奇門遁甲】", "M24_qimen"),
    ("【西洋占星術】", "M18_western"),
    ("【ネイタル占星術】", "M18_natal"),
    ("【トランジット】", "M18_transit"),
    ("【シナストリー】", "M18_synastry"),
    ("【紫微斗数】", "M20_ziwei"),
    ("【ヒューマンデザイン】", "M25_hd"),
    ("【パリミチャム】", "M15_parimicham"),
    ("【数秘術】", "M04_numerology_birth"),
]


def _zip_read_raw(z, slug: str) -> dict | None:
    want = f"{slug}_raw.json"
    for n in z.namelist():
        if n.endswith(want) and n.count(want) == 1:
            try:
                data = json.loads(z.read(n).decode("utf-8"))
                return (data.get("result") or {}).get("calc") or None
            except Exception:
                return None
    return None


def _reverse_multi(table: dict) -> dict:
    """英語→日本語の表を「日本語 → 英語の集合」に反転する（多対一を保持）。

    素朴な `{v: k for k, v in table.items()}` は**同じ日本語に複数の英語が
    対応する場合に後勝ちで1つに潰れる**（mts5.61 で見つかった誤報の原因）。
    """
    out: dict[str, set] = {}
    for en, ja in table.items():
        out.setdefault(ja, set()).add(en)
    return out


def _ja_matches(reverse: dict, ja: str, expected) -> bool:
    """日本語ラベル `ja` が `expected`（英語値）を指しうるか。

    未知のラベルは英語がそのまま書かれている場合があるため、直接比較も許す。
    """
    return expected in reverse.get(ja, set()) or ja == expected


def _typec_caption_calc_match(slug: str, caption: str, calc: dict,
                             pkg=None) -> bool | None:
    """キャプション内の数値⇄calc の整合（True/False。解釈不能なら None）"""
    if slug == "M03_kyusei":
        m = re.search(r"(\d{4})年生・本命星：(\S+)", caption)
        if not m:
            return None
        return (int(m.group(1)) == calc.get("year")
                and m.group(2) == calc.get("honmei"))
    if slug == "M04_numerology_birth":
        m = re.search(r"運命数(\d+)（(\d{4}-\d{2}-\d{2})生）", caption)
        if not m:
            return None
        return (int(m.group(1)) == calc.get("life_path")
                and m.group(2) == calc.get("date"))
    if slug == "M06_kabbalah":
        m = re.search(r"【カバラ数秘術】(\S+) → (\d+)", caption)
        if not m:
            return None
        return (m.group(1) == str(calc.get("romaji", "")).upper()
                and int(m.group(2)) == calc.get("number"))
    # ---- mts5.17: バッチ1 ----
    if slug == "M05_numerology_name":
        m = re.search(r"氏名数(\d+)（([A-Z]+(?: [A-Z]+)*)）", caption)
        if not m:
            return None
        return (int(m.group(1)) == calc.get("number")
                and m.group(2) == str(calc.get("romaji", "")).upper())
    if slug == "M07_chaldean":
        m = re.search(r"カルデア数(\d+)（([A-Z]+(?: [A-Z]+)*)）", caption)
        if not m:
            return None
        return (int(m.group(1)) == calc.get("number")
                and m.group(2) == str(calc.get("romaji", "")).upper())
    if slug == "M04_tantra":
        m = re.search(r"タントラ数(\d+)", caption)
        if not m:
            return None
        return int(m.group(1)) == calc.get("number")
    if slug == "M04_anka":
        m = re.search(r"アンカ数(\d+)", caption)
        if not m:
            return None
        if int(m.group(1)) != calc.get("number"):
            return False
        m2 = re.search(r"支配星：(\S+)", caption)
        if m2:
            try:
                if str(pkg) not in sys.path:
                    sys.path.insert(0, str(pkg))
                from fortunelib import chartdraw
                return m2.group(1) == chartdraw.ANKA_PLANETS.get(
                    int(calc.get("number")), "")
            except Exception:
                return None
        return True
    if slug == "M10_rokusei":
        m = re.search(r"【六星占術】(.+?)／年運：(.+?)（(\d{4})）", caption)
        if not m:
            return None
        return (m.group(1) == calc.get("type")
                and m.group(2) == calc.get("cycle")
                and int(m.group(3)) == calc.get("target_year"))
    if slug == "M14_weton":
        m = re.search(r"【ウェトン】(.+)", caption)
        if not m:
            return None
        return m.group(1) == calc.get("weton_name")
    if slug == "M13_primbon":
        m = re.search(r"【プリンボン・ジャワ】(.+?)／ネプトゥ(\d+)", caption)
        if not m:
            return None
        return (m.group(1) == calc.get("weton")
                and int(m.group(2)) == calc.get("neptu_total"))
    # ---- mts5.18: バッチ2 ----
    if slug == "M16_seimei":
        m = re.search(r"五格 天(\d+)・人(\d+)・地(\d+)・外(\d+)・総(\d+)", caption)
        if not m:
            return None
        fg = calc.get("five_grilles") or {}
        return [int(m.group(i)) for i in range(1, 6)] == [
            fg.get(k) for k in ("天格", "人格", "地格", "外格", "総格")]
    if slug == "M17_bazi":
        m = re.search(r"年柱(\S{2})／月柱(\S{2})／日柱(\S{2})／時柱(\S{2})"
                      r"・日主：(\S)（(\S)・(陽|陰)）", caption)
        if not m:
            return None
        p4 = calc.get("pillars") or {}
        dm = calc.get("day_master") or {}
        return (m.group(1) == p4.get("year") and m.group(2) == p4.get("month")
                and m.group(3) == p4.get("day") and m.group(4) == p4.get("hour")
                and m.group(5) == dm.get("gan") and m.group(6) == dm.get("wuxing")
                and m.group(7) == dm.get("yinyang"))
    if slug == "M19_vedic":
        m = re.search(r"月：(白羊座|金牛座|双子座|蟹座|獅子座|処女座|天秤座|天蝎座|"
                      r"人馬座|磨羯座|水瓶座|双魚座)・(.+)（パダ(\d+)）", caption)
        if not m:
            return None
        moon = (calc.get("planets") or {}).get("月") or {}
        return (m.group(1) == moon.get("sign")
                and m.group(2) == moon.get("nakshatra")
                and int(m.group(3)) == moon.get("nakshatra_pada"))
    if slug == "M21_sanmei":
        m = re.search(r"中心星：(\S+?)／総エネルギー(\d+)", caption)
        if not m:
            return None
        return (m.group(1) == calc.get("中心星")
                and int(m.group(2)) == calc.get("総エネルギー"))
    if slug == "M24_qimen":
        m = re.search(r"【奇門遁甲】(.+?)／値使：(.+)門・(\S+)宮", caption)
        if not m:
            return None
        zf = calc.get("zhifu_zhishi") or {}
        zs_pal = (zf.get("值使門宮") or [None, None])[-1]
        men = calc.get("men") or {}
        return (m.group(1) == calc.get("paiju") and m.group(3) == zs_pal
                and m.group(2) == men.get(zs_pal))
    # ---- mts5.19: 西洋占星術系 ----
    if slug in ("M18_western", "M18_natal"):
        m = re.search(r"太陽：(.+?)／月：(.+?)／ASC：(.+)", caption)
        if not m:
            return None
        pl = calc.get("planets") or {}
        hs = calc.get("houses") or {}
        return (m.group(1) == (pl.get("太陽") or {}).get("sign")
                and m.group(2) == (pl.get("月") or {}).get("sign")
                and m.group(3) == hs.get("asc_sign"))
    if slug == "M18_transit":
        m = re.search(r"太陽：(.+?)／月：(.+?)／アスペクト(\d+)件", caption)
        if not m:
            return None
        tp = calc.get("transit_planets") or {}
        return (m.group(1) == (tp.get("太陽") or {}).get("sign")
                and m.group(2) == (tp.get("月") or {}).get("sign")
                and int(m.group(3)) == len(calc.get("aspects_to_natal") or []))
    if slug == "M18_synastry":
        m = re.search(r"アスペクト(\d+)件(?:・(.+)×(.+) (.+))?", caption)
        if not m:
            return None
        asp = calc.get("aspects") or []
        if int(m.group(1)) != len(asp):
            return False
        if asp:
            return (m.group(2) == asp[0]["p1"] and m.group(3) == asp[0]["p2"]
                    and m.group(4) == asp[0]["aspect"])
        return m.group(2) is None
    # ---- mts5.20: B群残 ----
    if slug == "M20_ziwei":
        m = re.search(r"【紫微斗数】(.+?)・命宮：(.+?)／身宮：(.+)", caption)
        if not m:
            return None
        return (m.group(1) == calc.get("five_elements_class")
                and m.group(2) == calc.get("soul_palace")
                and m.group(3) == calc.get("body_palace"))
    if slug == "M25_hd":
        m = re.search(r"【ヒューマンデザイン】(.+?)・権威：(.+?)・(\d+/\d+)", caption)
        if not m:
            return None
        try:
            if str(pkg) not in sys.path:
                sys.path.insert(0, str(pkg))
            from fortunelib import chartdraw
            tj = _reverse_multi(chartdraw._HD_TYPE_JA)
            aj = _reverse_multi(chartdraw._HD_AUTH_JA)
        except Exception:
            return None
        # mts5.61: 逆引きは**多対一**を許す。`_HD_AUTH_JA` は Ego と Self-Projected が
        # どちらも「自己」で、素朴な逆引きだと後勝ちで Self-Projected になり、
        # 権威=Ego の鑑定が「キャプションと calc が不一致」と**誤報**されていました
        # （実機 mts5.60・人物 demo_morimoto_haruka で初めて当たりました）。
        return (_ja_matches(tj, m.group(1), calc.get("type"))
                and _ja_matches(aj, m.group(2), calc.get("authority"))
                and m.group(3) == calc.get("profile"))
    if slug == "M15_parimicham":
        m = re.search(r"【パリミチャム】([\d.]+)/([\d.]+)・(.+)", caption)
        if not m:
            return None
        try:
            return (float(m.group(1)) == float(calc.get("score"))
                    and float(m.group(2)) == float(calc.get("score_max"))
                    and m.group(3) == calc.get("verdict"))
        except (TypeError, ValueError):
            return None
    return None


def _mean_diff(got, img) -> float:
    from PIL import ImageChops as _ImageChops
    diff = _ImageChops.difference(got, img.convert("RGB")).convert("L")
    hist = diff.histogram()
    total = sum(hist) or 1
    return sum(i * c for i, c in enumerate(hist)) / total


def _diff_fraction(a, b, tol: int = 12) -> float:
    """2画像で「差のある画素」の割合（0.0〜1.0）

    mts5.32 追加。**文字が1つ欠ける程度の差は平均差では見えない**（キャンバスの
    大半は背景のため平均差は1〜2にしかならない）ので、画素の割合で見る。
    """
    from PIL import ImageChops as _ImageChops
    diff = _ImageChops.difference(a, b).convert("L")
    # tol 以下はノイズ（WebP 非可逆）とみなす
    mask = diff.point(lambda v: 255 if v > tol else 0)
    hist = mask.histogram()
    total = sum(hist) or 1
    return hist[255] / total


# 1文字ぶんの豆腐（mts5.52・F-4）の判定定数。実測（mts5.50 の型C 22枚）:
#   正常な納品画像 → 0 画素 / 1グリフだけ豆腐 → 14 画素（M15「ガ」・型C描画画素 1,711 の 0.8%）。
# 「フォント無し描画の方が近い」画素が下限（10画素）以上かつ描画画素の 0.2% 以上なら豆腐と判定。
MIN_FONT_CLOSER_PX = 10
FONT_CLOSER_RATIO = 0.002
FONT_CLOSER_MARGIN = 8      # 画素ごとの差の余裕（WebP 非可逆のノイズ対策）
FONT_CLOSER_TOL = 96        # 「CJKを描いている画素」とみなす差


def font_missing_trigger(n_closer: int, n_strokes: int) -> bool:
    """「1文字ぶんの豆腐」と判定するか（mts5.52・F-4 の判定式）。

    実測（mts5.50 の型C 22枚）: 正常 0 画素 / 1グリフ豆腐 14 画素（描画画素 1,711）で分離。
    下限（10画素）と割合（0.2%）の**両方**を満たすときだけ豆腐と判定する（誤検出防止）。
    """
    return n_closer >= max(MIN_FONT_CLOSER_PX, FONT_CLOSER_RATIO * n_strokes)


def _font_closer_stats(got, img, no_cjk, tol: int = FONT_CLOSER_TOL,
                       margin: int = FONT_CLOSER_MARGIN) -> tuple[int, float, int]:
    """CJK文字の画素のうち「フォント無し描画の方が近い」画素の (数, 割合, 描画画素数)。

    mts5.52 追加（F-4）。全文字が豆腐になる場合は `diff_font < mean` で検出できるが、
    **1文字だけ**が豆腐の場合は画像全体で見ると差が薄まり、平均差（閾 8.0）にも
    画素不一致率（閾 1.0%）にも収まってしまう（実測: 平均差 0.03 / 0.03%）。
    そこで「フォント無し描画で消える画素＝CJKを描いている画素」だけを取り出し、
    画素ごとに実行時画像がどちらに近いかを数える（実機 0 画素 / 1グリフ豆腐 14 画素）。
    """
    from PIL import ImageChops as _ImageChops
    d = _ImageChops.difference(img.convert("L"), no_cjk.convert("L"))
    gc = _ImageChops.difference(got.convert("RGB"), img).convert("L")
    gt = _ImageChops.difference(got.convert("RGB"), no_cjk).convert("L")
    def _pix(im):                       # Pillow 14 で getdata は廃止予定（新しいAPIを優先）
        getter = getattr(im, "get_flattened_data", None) or im.getdata
        return list(getter())

    pd, pc, pt = _pix(d), _pix(gc), _pix(gt)
    strokes = [i for i, v in enumerate(pd) if v > tol]
    if not strokes:
        return 0, 0.0, 0
    n = sum(1 for i in strokes if pt[i] + margin < pc[i])
    return n, n / len(strokes), len(strokes)


def _render_without_cjk(chartdraw, slug: str, calc: dict, extra: dict | None):
    """同梱CJKフォントを使わずに描画した比較用画像（mts5.28）。

    Kaggle にフォントが無い場合（＝本番で豆腐になる状態）と同じ条件を再現する。
    戻り値 (img, 元の状態に戻す関数)。
    """
    saved = (chartdraw._BUNDLED_FONT, list(chartdraw._FALLBACK_FONTS),
             dict(chartdraw._font_cache), chartdraw._font_source)

    def _restore():
        chartdraw._BUNDLED_FONT, chartdraw._FALLBACK_FONTS = saved[0], saved[1]
        chartdraw._font_cache.clear()
        chartdraw._font_cache.update(saved[2])
        chartdraw._font_source = saved[3]

    try:
        from pathlib import Path as _Path
        chartdraw._font_cache.clear()
        chartdraw._BUNDLED_FONT = _Path("/nonexistent")   # 同梱フォントを無効化
        chartdraw._FALLBACK_FONTS = []                    # システムフォントも無効化
        img, _c = chartdraw.render_for_slug(slug, calc, extra)
        return img, _restore
    except Exception:
        _restore()
        return None, lambda: None


def typec_dynamic_verify(caption: str, raw_bytes: bytes, results_zip,
                         pkg, max_mean_diff: float = 8.0,
                         max_diff_fraction: float = 0.01) -> tuple[str | None, str, str]:
    """型Cキャプションの埋め込み画像を3段階で照合。
      1) キャプション⇄calc の数値整合（取り違えの検出）
      2) calc 再生成画像とのピクセル近接（無関係画像の検出。WebP 非可逆のため平均差・緩い閾）
      3) **CJKフォント欠落（豆腐□□□）の検出**（mts5.28 追加）
         ＝「フォント無しで描いた画像」の方が実行時画像に近い場合は豆腐と判定する。
         フォント欠落は文字だけで画素の大半は背景のため平均差では閾内に隠れる
         （2026-09-26 の mts5.27 実機で実際に素通りした）。
      0) **描く文字が同梱フォントにあるか**（mts5.32 追加）＝文字の欠落は平均差では
         見えないため（2026-09-27 のデーヴァナーガリー数字の欠落がまさにこれ）、
         「実際に描く文字 × フォントのグリフ」を厳密に突き合わせる。
      4) **画素差の割合**（mts5.32 追加）＝再生成画像と大きく違う場合の検出。
      5) **1文字ぶんの豆腐**（mts5.52 追加・F-4）＝上の 3) は「全部豆腐」しか見つけられず、
         1文字だけ欠けた場合は平均差 0.03／画素率 0.03% で閾内に隠れた。
         CJKを描いている画素だけを取り出して画素ごとに判定する（`_font_closer_stats`）。
    ("ok"/"bad"/None, slug, detail) を返す。
    None＝型Cではない（slug が None）／results ZIP なし／**照合に必要な材料が無い**
    （生JSON・再生成画像が作れない）。detail に理由を入れるので、呼び出し側で
    「照合不能（unverifiable）」として計上できる（mts5.52・F-2 の推奨③）。"""
    slug = next((s for m, s in TYPEC_CAPTION_SLUG if caption.startswith(m)), None)
    if slug is None or results_zip is None:
        return None, "", ""
    try:
        import io as _io
        from PIL import Image as _Image
        z = zipfile.ZipFile(results_zip)
        calc = _zip_read_raw(z, slug)
        if calc is None:
            return None, slug, f"results ZIP に {slug}_raw.json が無いため照合できません"
        match = _typec_caption_calc_match(slug, caption, calc, pkg)
        if match is False:
            return "bad", slug, "キャプションと calc が不一致"
        extra = None
        if slug == "M04_numerology_birth":
            extra = _zip_read_raw(z, "M04_numerology_name")
        # mts5.52: 二重階層（<pkg>/fortune_dataset/fortunelib）でも import できるようにする
        lib_dir = _pkg_lib_dir(pkg) or Path(pkg)
        if str(lib_dir) not in sys.path:
            sys.path.insert(0, str(lib_dir))
        from fortunelib import chartdraw
        # --- 0) 文字の実体チェック（mts5.32）: 描く文字が同梱フォームに無い＝文字が消える ---
        try:
            miss = chartdraw.missing_glyphs_for(slug, calc, extra)
        except Exception:
            miss = []
        if miss:
            shown = "、".join(f"{ch}（{role}）" for role, ch in miss[:8])
            return ("bad", slug,
                    f"同梱フォントに無い文字を描こうとしています（{len(miss)}件: {shown}）。"
                    "tools/build_chart_fonts.py でフォントを再生成してください")
        img, _cap = chartdraw.render_for_slug(slug, calc, extra)
        if img is None:
            return None, slug, ("再生成画像を作れないため照合できません"
                                "（fortunelib か assets の不足）")
        try:
            got = _Image.open(_io.BytesIO(raw_bytes)).convert("RGB")
        except Exception:
            return "bad", slug, "埋め込み画像を開けません（データが破損しています）"
        if got.size != img.size:
            return "bad", slug, f"寸法が一致しない（{got.size} ≠ {img.size}）"
        mean = _mean_diff(got, img)
        # --- 3) フォント欠落（豆腐）判定: フォント無し描画の方が近ければ豆腐 ---
        no_cjk, _restore = _render_without_cjk(chartdraw, slug, calc, extra)
        if no_cjk is not None:
            try:
                diff_font = _mean_diff(got, no_cjk)
            finally:
                _restore()
            if diff_font < mean:
                return ("bad", slug,
                        "CJKフォント欠落の疑い（型Cの文字が豆腐になっている。"
                        "assets/fonts の同梱フォントを確認）")
            # --- 3b) 1文字ぶんの豆腐（mts5.52・F-4）-----------------------------
            # 全文字豆腐は上の `diff_font < mean` で検出できるが、1文字だけの豆腐は
            # 画像全体では差が薄まり、平均差（閾 8.0）にも画素率（閾 1.0%）にも収まる
            # （実測: 平均差 0.03・0.03%）。CJKを描いている画素だけで判定する。
            n_closer, _ratio, n_strokes = _font_closer_stats(got, img, no_cjk)
            if font_missing_trigger(n_closer, n_strokes):
                return ("bad", slug,
                        f"CJKフォント欠落の疑い（CJKを描く{n_strokes}画素のうち"
                        f"{n_closer}画素がフォント無し描画に近い＝1文字以上が豆腐。"
                        "実行環境の assets/fonts を確認）")
        if mean > max_mean_diff:
            return "bad", slug, f"再生成画像との差が大きい（平均差 {mean:.2f} > {max_mean_diff}）"
        # --- 4) 画素差の割合（mts5.32 追加）: 平均差では見えない「大きな食い違い」用 ---
        frac = _diff_fraction(got, img, tol=24)
        if frac > max_diff_fraction:
            pct = frac * 100
            return ("bad", slug,
                    f"実行時画像と再生成画像が大きく違います（画素の {pct:.1f}% が不一致）")
        return "ok", slug, ""
    except Exception as e:
        return None, slug, f"照合中に例外（{type(e).__name__}）"


def read_html(args) -> str:
    if args.html:
        return Path(args.html).read_text(encoding="utf-8")
    z = zipfile.ZipFile(args.results_zip)
    cands = [n for n in z.namelist() if n.endswith(".html")]
    if not cands:
        raise SystemExit("results-zip に .html がありません")
    return z.read(cands[0]).decode("utf-8")


# ---------------------------------------------------------------
# mts5.22: Stage D トーン化の検証
# ---------------------------------------------------------------
_TONE_NUM = re.compile(r"\d+(?:\.\d+)?")
_TONE_LEN = (0.45, 1.7)


def _load_tone_lib(pkg):
    """pkg（ディレクトリ）から fortunelib.tone を読み込む（失敗時は None）。

    セグメント分割のロジックを**同じコード**で使い直すため import する
    （ZIP pkg は弱めチェックに降级される）。
    """
    import sys
    if not pkg:
        return None
    p = Path(pkg)
    if not p.is_dir():
        return None
    for cand in (p / "fortune_dataset", p):
        if (cand / "fortunelib" / "tone.py").is_file():
            sp = str(cand)
            if sp not in sys.path:
                sys.path.insert(0, sp)
            try:
                from fortunelib import tone
                return tone
            except Exception:
                return None
    return None


def _strip_tags(html: str) -> str:
    import html as _html
    t = re.sub(r"<[^>]+>", "", html or "")
    return _html.unescape(t)



def _tone_std_units(z, base: str) -> dict:
    """結果ZIPから標準（標準トーン）のユニット本文を収集する"""
    std: dict = {}
    names = z.namelist()

    def _read(rel: str):
        want = base + rel
        for n in names:
            if n == want:
                try:
                    return z.read(n).decode("utf-8")
                except Exception:
                    return None
        return None

    def _strip(md: str) -> str:
        # とっさに footer/H1 を落とす（collect_units と同等の簡易版）
        for mark in ("※ 本結果はエンターテインメント", "※ 本レポートはエンターテインメント"):
            i = md.find(mark)
            if i > 0:
                cut = md.rfind("---", 0, i)
                md = md[:cut if cut > 0 else i]
                break
        md = re.sub(r"^#\s+.+$", "", md, count=1, flags=re.M)
        return md.strip()

    t = _read("synthesis_report.md")
    if t:
        std["synthesis"] = _strip(t)
    for n in names:
        if not n.startswith(base) or not n.endswith(".md"):
            continue
        rel = n[len(base):]
        if rel.startswith("cluster_reports/AXIS_") and rel.endswith(".md"):
            stem = rel.rsplit("/", 1)[1][:-3]
            uid = "axis_" + stem[len("AXIS_"):]
            std[uid] = _strip(_read(rel) or "")
        elif rel.startswith("cluster_reports/") and rel.endswith(".md") \
                and not rel[len("cluster_reports/"):].startswith("AXIS_"):
            stem = rel.rsplit("/", 1)[1][:-3]
            std[f"cluster_{stem}"] = _strip(_read(rel) or "")
        elif rel.startswith("results/") and "_raw" not in rel and rel.endswith(".md"):
            stem = rel.rsplit("/", 1)[1][:-3]
            std[stem] = _strip(_read(rel) or "")
    return {k: v for k, v in std.items() if v}


# ---- mts5.58: 標準タブ（口調の元テキスト）の字数 ----------------------
# fortunelib/synthesis.py の FINAL_CHARS と一致させる（テストで突合する）。
STD_BAND = (4000, 5300)          # 最終レポート（Flash 本文）の検証レンジ（mts5.60: 上限を 5,300 へ）
STD_INSTRUCT_BAND = (4800, 5200)  # プロンプトに書く指示レンジ（mts5.60: 下限 4,800・上限 5,200）


def std_chars_breakdown(md: str) -> dict:
    """標準タブ（統合レポート）の字数を内訳つきで返す（mts5.58）。

    - total    : 標準タブ全体＝**口調変換の元テキスト**の文字数（collect_units と同じ）
    - flash    : 最終統合（Flash が書いた本文）の文字数
    - toc      : 軸サマリー・分野別中間レポート（決定論的な目次）
    - profile / deities : 見出し・プロファイル（決定論的）と御縁のある神さま
    `synthesis_report.md` の構造（write_synthesis_file が書く形）に依存する。
    """
    import re as _re
    from pathlib import Path as _Path          # noqa: F401  （意図を明示）
    text = (md or "").replace("\r\n", "\n")
    total = len(text.strip())
    out = {"total": total, "flash": 0, "toc": 0, "profile": 0, "deities": 0,
           "band": list(STD_BAND), "instruct": list(STD_INSTRUCT_BAND)}
    # 御縁のある神さまの節（末尾）
    i_dei = text.find("\n## 御縁のある神さま")
    head = text[:i_dei] if i_dei > 0 else text
    out["deities"] = len(text) - len(head)
    # 軸サマリー以降は決定論的な目次
    i_toc = head.find("\n## 軸サマリー")
    if i_toc > 0:
        out["toc"] = len(head) - i_toc
        head = head[:i_toc]
    # ヘッダ＋プロファイルは「---」で終わる（write_synthesis_file の head）
    i_prof = head.find("\n## あなたのプロファイル")
    if i_prof >= 0:
        i_sep = head.find("\n---\n", i_prof)
        if i_sep > 0:
            out["profile"] = i_sep + len("\n---\n")
            head = head[i_sep + len("\n---\n"):]
    # 目次の直前の区切り（---）は本文ではないので数えない
    body = head.strip()
    if body.endswith("---"):
        body = body[:-3].rstrip("\n ")
        if body.endswith("---"):
            body = body[:-3].rstrip("\n ")
    out["flash"] = len(body)
    # mts5.68: 読み物版の元テキスト＝標準タブ全体 − ご相談の引用 − 目次（ファイル一覧）。
    # 製品（fortunelib.tone.omake_source_text）と同じ規則で数える（読めない環境は簡易版）。
    out["consultation"], out["omake_source"] = _omake_source_chars(text)
    return out


def _omake_source_chars(text: str) -> tuple[int, int]:
    """(ご相談の引用の字数, 読み物版の元テキストの字数) を返す（mts5.68）。

    製品の `fortunelib.tone.omake_source_text` が読めればそれを使い（＝基準が必ず一致）、
    読めない環境では同じ規則の簡易版で数える。
    """
    try:
        from fortunelib.tone import omake_source_text as _ost   # type: ignore
        src, info = _ost(text)
        return int(info.get("consultation") or 0), len(src)
    except Exception:
        pass
    import re as _re
    s = (text or "").replace("\r\n", "\n")
    n_cons = 0
    m = _re.search(r"^\*\*ご相談\*\*: .*?(?=\n\n|\Z)\n*", s, _re.M | _re.S)
    if m:
        n_cons = len(m.group(0).strip())
        s = s[:m.start()] + s[m.end():]
    toc_re = _re.compile(r"^## (?:軸サマリー|分野別の中間レポート)\n.*?(?=^## |\Z)", _re.M | _re.S)
    while True:
        m = toc_re.search(s)
        if not m:
            break
        s = s[:m.start()] + s[m.end():]
    s = _re.sub(r"(?:\n---\n\s*){2,}", "\n---\n\n", s).strip()
    return n_cons, len(s)


def check_std_chars(md: str) -> list:
    """標準本文（Flash）が仕様の帯に入っているかを確かめる（mts5.58）。

    返り値は警告の一覧（**不合格にはしない**＝引用した実行でも止めない）。
    """
    b = std_chars_breakdown(md)
    lo, hi = STD_BAND
    warns = []
    n = b["flash"]
    if n and not (lo <= n <= hi):
        warns.append({"caption": "（標準）", "kind": "chars",
                      "detail": f"標準本文（最終統合）が {n}字で仕様の帯 "
                                f"{lo}〜{hi}字の外。標準本文の字数を調整してください"})
    return warns


def std_chars_line(n: int, band, instruct) -> str:
    """標準本文の字数を1行にする（mts5.65: 「下限まで／上限まで」は帯の外のときだけ）。

    内側（帯の中）でも「下限まで 0字」と出ていて紛らわしかったため、
    帯の**外**のときにだけ不足／超過を数字で示す。帯の中は「＝内側」だけ。
    """
    lo, hi = band
    i_lo, i_hi = instruct
    tail = f"指示は {i_lo}〜{i_hi}字）"
    if lo <= n <= hi:
        return f"標準本文 : {n}字（仕様 {lo}〜{hi}字＝内側・{tail}"
    gap = f"下限まで {lo - n}字" if n < lo else f"上限まで {n - hi}字"
    return f"標準本文 : {n}字（仕様 {lo}〜{hi}字＝外・{gap}／{tail}"


def html_std_chars(html: str) -> int:
    """HTML の標準タブ（id="synthesis-body"）の文字数を数える（mts5.58）。

    results.zip が無いときの簡易計測。タグを除いた**見えている文字**を数える
    （入れ子の div は深さを追って閉じ位置を決める）。取れなければ 0。
    """
    if not html:
        return 0
    # 開きタグの最後（>）までを読み飛ばす（属性の途中で切らない）
    m = re.search(r'<div[^>]*id="synthesis-body"[^>]*>', html)
    if not m:
        return 0
    body = html[m.end():]
    depth, i = 1, 0
    tag = re.compile(r"</?div\b[^>]*>", re.I)
    while depth > 0:
        t = tag.search(body, i)
        if not t:
            break
        depth += -1 if t.group(0).startswith("</") else 1
        i = t.end()
    seg = body[:i] if depth == 0 else body
    import html as _html_mod
    seg = re.sub(r"<(script|style)\b.*?</\1>", "", seg, flags=re.S | re.I)
    txt = _html_mod.unescape(re.sub(r"<[^>]+>", "", seg))
    return len(re.sub(r"\s+", "", txt))


def _verify_omake(z, base: str, manifest: dict, omake_id: str,
                  out: dict) -> dict:
    """読み物版（scope=synthesis・自由変換）の検証（mts5.29）。

    自由変換なので長さ比・数値の多重集合一致は**要求しない**。
    代わりに次を確かめる:
      1. ok のトーンは units.json に読み物版本文が入っている
      2. 分量が極端でない（元の 40〜160%。元は標準本文の文字数）
      3. マニフェストに記録された「元に無い数値」を情報として出す
      4. 他ユニット（個別占術など）の成果が混ざっていない
    """
    out["mode"] = "omake"
    out["tones"] = {}
    # 標準本文（統合レポート）の文字数（mts5.58: 内訳も測る）
    std_len = 0
    std_md = ""
    zname = [n for n in z.namelist() if n.endswith("synthesis_report.md")]
    if zname:
        try:
            std_md = z.read(zname[0]).decode("utf-8")
            std_len = len(std_md)
        except Exception:
            std_len = 0
    out["std_chars"] = std_len
    # mts5.58: 標準タブ＝口調の元テキストの字数（毎回表示する）
    _std = _tone_std_units(z, base).get("synthesis") or ""
    out["std"] = std_chars_breakdown(_std)
    out["std"]["raw_md"] = len(std_md)
    out["std_warnings"] = check_std_chars(_std)
    # mts5.68: 製品が分量の基準にした元テキスト（manifest.source_chars）と突合する。
    # 旧版（〜mts5.67）の manifest には無い＝その場合は標準タブ全体が基準だった旨を残す。
    _src_m = manifest.get("source_chars")
    out["std"]["manifest_source_chars"] = _src_m
    if isinstance(_src_m, int) and _std:
        _diff = abs(int(_src_m) - int(out["std"]["omake_source"]))
        if _diff > 8:
            out["problems"].append(
                f"読み物版の元テキストの字数が食い違います: 製品 {_src_m}字 ↔ 検証器 "
                f"{out['std']['omake_source']}字（ご相談・目次の除外規則がずれている可能性）")
    for tid, entry in (manifest.get("tones") or {}).items():
        if tid == "standard":
            continue
        t = {"ok": 0, "fallback": 0, "bad": 0}
        t["status"] = (entry or {}).get("status")
        t["chars"] = (entry or {}).get("chars")
        t["ratio"] = (entry or {}).get("ratio")
        t["numbers_new"] = (entry or {}).get("numbers_new") or []
        # mts5.56: 口調の弁別（試行回数・指標・未達）を情報として出す
        t["attempts"] = (entry or {}).get("attempts")
        t["style"] = (entry or {}).get("discrimination") or None
        units_json = {}
        up_name = base + f"tone_reports/{tid}/units.json"
        for n in z.namelist():
            if n == up_name:
                try:
                    units_json = json.loads(z.read(n).decode("utf-8"))
                except Exception:
                    pass
        if t["status"] == "fallback":
            t["fallback"] = 1
            if units_json:
                t["bad"] = 1
                out["problems"].append(
                    f"{tid}: フォールバックなのに units.json に内容がある")
            out["tones"][tid] = t
            continue
        if t["status"] != "ok":
            t["bad"] = 1
            out["problems"].append(f"{tid}: 未知のステータス {t['status']}")
            out["tones"][tid] = t
            continue
        txt = units_json.get(omake_id)
        if not (isinstance(txt, str) and txt.strip()):
            t["bad"] = 1
            out["problems"].append(f"{tid}: 読み物版の本文が units.json に無い")
            out["tones"][tid] = t
            continue
        # 他のユニットが混ざっていないこと（範囲外の成果を持ち込まない）
        extra = [k for k in units_json if k != omake_id]
        if extra:
            t["bad"] = 1
            out["problems"].append(
                f"{tid}: 読み物版以外のユニットが混入 {extra[:3]}")
            out["tones"][tid] = t
            continue
        if std_len:
            ratio = len(txt) / std_len
            if not (0.4 <= ratio <= 1.6):
                t["bad"] = 1
                out["problems"].append(
                    f"{tid}: 読み物版の分量が極端（元の {ratio * 100:.0f}%）")
                out["tones"][tid] = t
                continue
        t["ok"] = 1
        out["tones"][tid] = t
        # mts5.56: 口調の指定に未達のまま採用された本文は「警告」として残す
        # （生成は止めない＝不合格にはしない。モックの記録は対象外）
        style = t.get("style") or {}
        if style.get("enforced") is not False:
            for _p in (style.get("problems") or []):
                out["problems"].append(f"{tid}: 口調の指定に未達（{_p}）")
    # mts5.56: トーン同士の類似度（似すぎの検出）
    out["discrimination"] = manifest.get("discrimination") or None
    if any(x.get("ok") for x in out["tones"].values()):
        out["omake_ok"] = True
    return out


def verify_tones(html: str, results_zip: str | None, pkg: str | None = None) -> dict | None:
    """Stage D（トーン化）の検証（mts5.24: データ部そのまま＋本文セグメント）。

    manifest が無ければ None（この実行は前 mts5.21 以前）。
    検証内容:
      1. ok ユニット: segments.json のデータ部が原文と一致（verbatim）
         ＋ 各セグメントの長さ比 0.45〜1.7・数値多重集合一致・見出しなし
         ＋ データ部の数値が units.json HTML に存在
      2. HTML: tonebar / tb-btn / tone-data JSON / data-unit の整合
    """
    out: dict = {"manifest": False, "tones": {}, "html": {}, "problems": []}
    z = None
    base = ""
    # mts5.46: results.zip が無くても、統合レポート内の読み物版切替UIを報告する。
    if (not (results_zip and Path(results_zip).is_file())
            and ('id="omake-data"' in html or 'id="synthesis-switcher"' in html)):
        om = re.search(
            r'<script type="application/json" id="omake-data">(.*?)</script>',
            html, re.S)
        n_tones = 0
        if om:
            try:
                n_tones = len(json.loads(
                    om.group(1).replace("<\\/", "</")).get("omake") or {})
            except Exception as e:
                out["problems"].append(f"読み物版データJSONをパースできません: {e}")
        has_switcher = 'id="synthesis-switcher"' in html
        has_body = 'id="synthesis-body"' in html
        standard_default = bool(re.search(
            r'<button[^>]*id="synthesis-tab-standard"[^>]*aria-pressed="true"',
            html, re.S))
        n_buttons = len(re.findall(r'class="[^"]*\bsynthesis-view-btn\b[^"]*"', html))
        legacy_card = 'class="card omake-card"' in html
        out.update({"mode": "omake-html", "html_only": True,
                    "std_html_chars": html_std_chars(html),
                    "html": {"synthesis_switcher": has_switcher,
                             "synthesis_body": has_body,
                             "standard_default": standard_default,
                             "legacy_omake_card": legacy_card,
                             "variants_json": bool(om), "variants": n_tones,
                             "buttons": n_buttons},
                    "tones": {}})
        if not out["html"]["variants_json"]:
            out["problems"].append("統合レポート内の読み物版JSONがありません")
        if not has_switcher or not has_body:
            out["problems"].append("統合レポートの表示切替UIまたは本文枠がありません")
        if n_buttons < 2:
            out["problems"].append("統合レポートの切替ボタンが2未満です")
        if not standard_default:
            out["problems"].append("初期表示の「標準」ボタンが選択状態ではありません")
        if legacy_card:
            out["problems"].append("旧レイアウトの独立した読み物版カードが残っています")
        if "正確な内容・数値" not in html or "正本" not in html:
            out["problems"].append("標準レポートが正本である旨の注記が見当たりません")
        return out
    if results_zip and Path(results_zip).is_file():
        z = zipfile.ZipFile(results_zip)
        man_name = next(
            (n for n in z.namelist()
             if n.endswith("tone_reports/tone_manifest.json")), None)
        if not man_name:
            return None
        out["manifest"] = True
        base = man_name[:man_name.rfind("tone_reports/")]
        try:
            manifest = json.loads(z.read(man_name).decode("utf-8"))
        except Exception as e:
            out["problems"].append(f"tone_manifest.json を読めません: {e}")
            return out
        out["scope"] = manifest.get("scope")
        out["target_units"] = len(manifest.get("target_units") or [])
        out["n_target_units"] = manifest.get("n_target_units")
        # mts5.29: scope="synthesis" は読み物版（自由変換）＝別形式で検証する。
        # セグメント分割・長さ比・数値多重集合の照合は行わない（設計どおり）。
        omake_id = manifest.get("omake_unit_id") or "synthesis_omake"
        is_omake = (manifest.get("scope") == "synthesis") or any(
            (e or {}).get("mode") == "omake"
            for e in (manifest.get("tones") or {}).values())
        if is_omake:
            # 自由変換（読み物版）は専用の検証へ。以降の HTML 検証は共通。
            _verify_omake(z, base, manifest, omake_id, out)
        tone_lib = _load_tone_lib(pkg)
        splits: dict | None = None
        kinds: dict = {}
        if tone_lib is not None:
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                for n in z.namelist():
                    if not n.startswith(base):
                        continue
                    rel = n[len(base):]
                    if rel.startswith("tone_reports/"):
                        continue
                    if not (n.endswith(".md") or n.endswith(".json")):
                        continue
                    dest = Path(td) / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(z.read(n))
                units = tone_lib.collect_units(td)
                kinds = {u["id"]: u.get("kind") for u in units}
                splits = {u["id"]: tone_lib.split_unit(u) for u in units}
        for tid, entry in ({} if is_omake else
                           (manifest.get("tones") or {})).items():
            if tid == "standard":
                continue
            t = {"ok": 0, "fallback": 0, "bad": 0}
            units_json, segs_json = {}, {}
            for n in z.namelist():
                if n == base + f"tone_reports/{tid}/units.json":
                    try:
                        units_json = json.loads(z.read(n).decode("utf-8"))
                    except Exception:
                        pass
                elif n == base + f"tone_reports/{tid}/segments.json":
                    try:
                        segs_json = json.loads(z.read(n).decode("utf-8"))
                    except Exception:
                        pass
            for uid, st in (entry.get("units") or {}).items():
                # mts5.27: 対象範囲の整合（scope=narrative は物語系のみのはず）
                if (out.get("scope") == "narrative" and kinds
                        and kinds.get(uid) not in (tone_lib.NARRATIVE_KINDS
                                                   if tone_lib else
                                                   ("synthesis", "axis", "cluster"))):
                    out["problems"].append(
                        f"{tid}/{uid}: scope=narrative なのに物語系以外が対象"
                        f"（kind={kinds.get(uid)}）")
                if st == "fallback":
                    t["fallback"] += 1
                    continue
                if st != "ok":
                    t["bad"] += 1
                    out["problems"].append(f"{tid}/{uid}: 未知のステータス {st}")
                    continue
                uhtml = units_json.get(uid)
                if not (isinstance(uhtml, str) and uhtml.strip()):
                    t["bad"] += 1
                    out["problems"].append(f"{tid}/{uid}: units.json に本文がない")
                    continue
                html_txt = _strip_tags(uhtml)
                info = segs_json.get(uid)
                if splits is not None:
                    sp = splits.get(uid)
                    if sp is None:
                        t["bad"] += 1
                        out["problems"].append(f"{tid}/{uid}: 標準本文が見つからない")
                        continue
                    if info is None:
                        t["bad"] += 1
                        out["problems"].append(f"{tid}/{uid}: segments.json に無い")
                        continue
                    if (info.get("data_pre") != sp["data_pre"]
                            or info.get("data_post") != sp["data_post"]):
                        t["bad"] += 1
                        out["problems"].append(f"{tid}/{uid}: データ部が改変されている")
                        continue
                    failed = False
                    for sg in sp["segments"]:
                        ot = sg["text"]
                        nt = ((info.get("segments") or {}).get(sg["id"]) or "").strip()
                        if not nt:
                            t["bad"] += 1
                            out["problems"].append(f"{tid}/{uid}/{sg['id']}: セグメント空")
                            failed = True
                            break
                        ratio = len(nt) / max(1, len(ot))
                        if not (_TONE_LEN[0] <= ratio <= _TONE_LEN[1]):
                            t["bad"] += 1
                            out["problems"].append(
                                f"{tid}/{uid}/{sg['id']}: 長さ比 {ratio:.2f}"
                                f"（内容の欠落・追加の疑い）")
                            failed = True
                            break
                        o, n2 = _TONE_NUM.findall(ot), _TONE_NUM.findall(nt)
                        if Counter(o) != Counter(n2):
                            t["bad"] += 1
                            out["problems"].append(
                                f"{tid}/{uid}/{sg['id']}: 数値不一致（元{o}／新{n2}）")
                            failed = True
                            break
                        if re.search(r"(?m)^\s*#\s", nt):
                            t["bad"] += 1
                            out["problems"].append(f"{tid}/{uid}/{sg['id']}: 見出しが混入")
                            failed = True
                            break
                    if failed:
                        continue
                    for nm in set(_TONE_NUM.findall(sp["data_pre"] + sp["data_post"])):
                        if nm not in html_txt:
                            t["bad"] += 1
                            out["problems"].append(
                                f"{tid}/{uid}: HTML にデータ部の数値 {nm} が無い")
                            break
                    else:
                        t["ok"] += 1
                else:
                    if info is None:
                        t["bad"] += 1
                        out["problems"].append(f"{tid}/{uid}: segments.json に無い")
                        continue
                    segs = info.get("segments") or {}
                    if not segs or any(not (v or "").strip() for v in segs.values()):
                        t["bad"] += 1
                        out["problems"].append(f"{tid}/{uid}: セグメント欠落・空")
                        continue
                    if any(re.search(r"(?m)^\s*#\s", v) for v in segs.values()):
                        t["bad"] += 1
                        out["problems"].append(f"{tid}/{uid}: 見出しが混入")
                        continue
                    data_nums = set(_TONE_NUM.findall(
                        (info.get("data_pre") or "") + (info.get("data_post") or "")))
                    if any(nm not in html_txt for nm in data_nums):
                        t["bad"] += 1
                        out["problems"].append(f"{tid}/{uid}: HTML にデータ部の数値が無い")
                        continue
                    t["ok"] += 1
            out["tones"][tid] = t
    # ---- HTML 側の整合 ----
    has_bar = 'class="tonebar"' in html
    out["html"]["tonebar"] = has_bar
    out["html"]["buttons"] = len(re.findall(r'class="[^"]*tb-btn[^"]*"', html))
    out["html"]["units"] = len(re.findall(r'class="tone-text" data-unit="', html))
    if out.get("mode") == "omake":
        # mts5.46: 読み物版は統合本文を切り替える。独立カードは作らない。
        out["html"]["legacy_omake_card"] = (
            'id="omake"' in html or 'class="card omake-card"' in html)
        out["html"]["synthesis_switcher"] = 'id="synthesis-switcher"' in html
        out["html"]["synthesis_body"] = 'id="synthesis-body"' in html
        out["html"]["standard_default"] = bool(re.search(
            r'<button[^>]*id="synthesis-tab-standard"[^>]*aria-pressed="true"',
            html, re.S))
        om = re.search(
            r'<script type="application/json" id="omake-data">(.*?)</script>',
            html, re.S)
        out["html"]["omake_json"] = bool(om)
        if om:
            try:
                payload = json.loads(om.group(1).replace("<\\/", "</"))
                out["html"]["omake_tones"] = len(payload.get("omake") or {})
            except Exception as e:
                out["problems"].append(f"読み物版データJSONをパースできません: {e}")
        if not out["html"]["synthesis_switcher"] or not out["html"]["synthesis_body"]:
            n_ok = sum(1 for t in out["tones"].values() if t.get("ok"))
            if n_ok:
                out["problems"].append(
                    "読み物版の成果はあるが統合レポート内の表示切替UIがない（再生成が必要）")
        if not out["html"]["omake_json"] and out.get("omake_ok"):
            out["problems"].append("読み物版の成果はあるが HTML に読み物版JSONがありません")
        if not out["html"]["standard_default"]:
            out["problems"].append("統合レポートの初期表示が「標準」ではありません")
        if out["html"]["legacy_omake_card"]:
            out["problems"].append("旧レイアウトの独立した読み物版カードが残っています")
        if "正確な内容・数値" not in html or "正本" not in html:
            out["problems"].append("読み物版の注記（標準が正本）が見当たりません")
        out["html"]["tonebar"] = out["html"]["synthesis_switcher"]
        return out                      # 読み物版は専用の切替UIで検査済み
    m = re.search(
        r'<script type="application/json" id="tone-data">(.*?)</script>',
        html, re.S)
    out["html"]["json"] = False
    if m:
        try:
            payload = json.loads(m.group(1).replace("<\\/", "</"))
            out["html"]["json"] = True
            out["html"]["json_tones"] = len(payload.get("tones") or {})
            out["html"]["json_units"] = sum(
                len((t.get("units") or {})) for t in
                (payload.get("tones") or {}).values())
        except Exception as e:
            out["problems"].append(f"tone-data JSON をパースできません: {e}")
    if has_bar:
        if not m:
            out["problems"].append("tonebar はあるが tone-data JSON が無い")
        elif out["html"]["buttons"] < 2:
            out["problems"].append("tonebar ボタンが 2 未満")
    elif out["manifest"]:
        n_with_units = sum(
            1 for tid, t in out["tones"].items() if t.get("ok", 0) > 0)
        if n_with_units > 0:
            out["problems"].append(
                "トーン成果はあるが HTML に tonebar がない（再生成が必要）")
    return out

# ---------------------------------------------------------------
# mts5.69: 冒頭動画カード（同梱の固定動画・目次の直前）の検証
# ---------------------------------------------------------------
INTRO_CARD_ID = "intro-video"
INTRO_ONLINE_LABEL = "オンラインからも視聴できます"
_INTRO_B64 = re.compile(r'data:video/mp4;base64,([A-Za-z0-9+/=]+)')
INTRO_REPORT: dict = {}


def _intro_config(assets: Path) -> dict | None:
    """assets/images（または assets・video 自身）から assets/video/intro_video.json を読む。"""
    assets = Path(assets)
    for c in (assets, assets / "video", assets.parent / "video"):
        f = c / "intro_video.json"
        try:
            if not f.is_file():
                continue
            cfg = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return None
        if isinstance(cfg, dict):
            cfg["_dir"] = str(c)
            return cfg
    return None


def verify_intro_video(html: str, assets: Path) -> dict:
    """冒頭動画カードを検証する（fortunelib に依存しない独立実装）。

    規則（製品 `fortunelib/intro_video.py` と同じ）:
      * カード `id="intro-video"` は `<nav class="toc">` より**前**にある
      * 動画の data URI は文書全体で **1 部だけ**（JS が Blob に変換して再生する設計）
      * 復号した動画の SHA-256 が同梱の原本（assets/video/<file>）または設定の sha256 と一致
      * 「オンラインからも視聴できます」の案内と、設定の online_url へのリンクがある
      * autoplay は付けない
    カードが無いとき: Dataset に設定があれば**警告**（Cell N2 の EMBED_INTRO_VIDEO=False なら想定内）、
    設定も無ければ旧構成として何も言わない。
    """
    cfg = _intro_config(Path(assets))
    out = {"present": False, "config": bool(cfg), "problems": [], "warnings": [], "line": ""}
    i_card = html.find(f'id="{INTRO_CARD_ID}"')
    i_toc = html.find('<nav class="toc">')
    if i_card < 0:
        if cfg:
            out["warnings"].append({"caption": "（冒頭動画）", "kind": "intro-video",
                                    "detail": "冒頭動画カードが HTML にありません（Dataset には "
                                              "assets/video/intro_video.json がある＝Cell N2 の "
                                              "EMBED_INTRO_VIDEO=False で実行したなら想定内）"})
            out["line"] = "  冒頭動画   : なし（同梱あり＝OFF で実行？）"
        else:
            out["line"] = "  冒頭動画   : なし（同梱なし＝mts5.68 以前の構成）"
        return out
    out["present"] = True
    seg = html[i_card:(i_toc if i_toc > i_card else len(html))]
    before = i_toc > i_card
    copies = len(_INTRO_B64.findall(html))
    m = _INTRO_B64.search(seg)
    sha = None
    nbytes = 0
    if m:
        try:
            raw = base64.b64decode(m.group(1), validate=True)
            sha, nbytes = hashlib.sha256(raw).hexdigest(), len(raw)
        except Exception:
            sha, nbytes = None, 0
    want = ""
    ref = "なし"
    if cfg:
        f = Path(cfg.get("_dir", "")) / str(cfg.get("file") or "")
        if cfg.get("file") and f.is_file():
            want = hashlib.sha256(f.read_bytes()).hexdigest()
            ref = f"原本 {f.name}"
        elif cfg.get("sha256"):
            want = str(cfg["sha256"]).lower()
            ref = "設定の sha256"
    label_ok = INTRO_ONLINE_LABEL in seg
    url = str((cfg or {}).get("online_url") or "")
    url_ok = (f'href="{url}"' in seg or f"href=\"{url.replace('&', '&amp;')}\"" in seg) if url else bool(
        re.search(r'<a href="https?://[^"]+" target="_blank"', seg))
    autoplay = " autoplay" in seg[:seg.find("<source") if "<source" in seg else len(seg)]
    poster = ' poster="data:image/' in seg
    script = "getElementById('iv-player')" in seg
    P = out["problems"]
    if not before:
        P.append({"caption": "（冒頭動画）", "kind": "intro-video",
                  "detail": "冒頭動画カードが目次（nav.toc）の前にありません"})
    if copies == 0 or sha is None:
        P.append({"caption": "（冒頭動画）", "kind": "intro-video",
                  "detail": "動画の data URI が埋め込まれていない／復号できません"})
    elif copies != 1:
        P.append({"caption": "（冒頭動画）", "kind": "intro-video",
                  "detail": f"動画の data URI が {copies} 部あります（1 部だけ持つ設計）"})
    sha_state = "未照合"
    if sha and want:
        if sha == want:
            sha_state = "一致"
        else:
            sha_state = "不一致"
            P.append({"caption": "（冒頭動画）", "kind": "intro-video",
                      "detail": f"埋め込み動画の SHA-256 が{ref}と一致しません"
                                f"（HTML {sha[:12]}… / {ref} {want[:12]}…）"})
    if not label_ok:
        P.append({"caption": "（冒頭動画）", "kind": "intro-video",
                  "detail": f"「{INTRO_ONLINE_LABEL}」の案内がありません"})
    if not url_ok:
        P.append({"caption": "（冒頭動画）", "kind": "intro-video",
                  "detail": "オンライン版（YouTube）へのリンクがない／設定の online_url と一致しません"})
    if autoplay:
        P.append({"caption": "（冒頭動画）", "kind": "intro-video",
                  "detail": "video タグに autoplay が付いています（自動再生はしない設計）"})
    if not script:
        out["warnings"].append({"caption": "（冒頭動画）", "kind": "intro-video",
                                "detail": "Blob 再生用のスクリプトがありません（iOS Safari で再生できない恐れ）"})
    out.update({"before_toc": before, "copies": copies, "sha256": sha, "bytes": nbytes,
                "sha_state": sha_state, "online_label": label_ok, "online_url_ok": url_ok,
                "poster": poster, "script": script, "autoplay": autoplay})
    out["line"] = (f"  冒頭動画   : 有（{nbytes / 1e6:.2f}MB・SHA {sha_state}（{ref}）・"
                   f"目次の{'前' if before else '後!'}・オンライン案内 {'有' if label_ok else '無'}・"
                   f"URL {'一致' if url_ok else '不一致'}・data URI {copies}部・"
                   f"poster {'有' if poster else '無'}・JS {'有' if script else '無'}）")
    return out


def _json_payload(pairs, ok_bytes, miss_bytes, byte_unverified, name_ok, name_bad,
                  unverifiable, decks, problems, warnings_, omitted, tone_rep, args) -> dict:
    """`--json-out` に書く内容（mts5.52: warnings / strict / expected / exit を追加）。"""
    return {
        "images": len(pairs), "byte_ok": ok_bytes, "byte_miss": miss_bytes,
        "byte_unverified": byte_unverified,
        "name_ok": name_ok, "name_bad": name_bad, "unverifiable": unverifiable,
        "decks": decks, "problems": problems, "warnings": list(warnings_),
        "omitted": omitted, "tones": tone_rep,
        "intro_video": INTRO_REPORT or None,          # mts5.69
        "strict": bool(args.strict),
        "expected": {"images": args.expect_images, "decks": args.expect_decks},
        "exit": _exit_code(problems, warnings_, args.strict),
    }


def _exit_code(problems, warnings_, strict: bool) -> int:
    """mts5.52（F-3）: 不合格があれば 1。警告は `--strict` のときだけ 1。"""
    if problems:
        return 1
    if strict and warnings_:
        return 1
    return 0


def _print_findings(problems, warnings_) -> None:
    """「■ 不合格」「■ 警告」「■ 問題なし」を出し分ける（mts5.52・F-3）。

    従来はトーン・レイアウトの問題も `■ 問題` と表示しながら exit 0 だったため、
    人が読むと失敗・自動化は exit を信じると見逃し、という食い違いがあった。
    """
    def _one(p) -> str:
        if isinstance(p, str):
            text = p if len(p) <= 72 else p[:72] + "…"
            return f"  [警告] {text}"
        label = str(p.get("kind", "?"))
        cap = str(p.get("caption", ""))
        detail = str(p.get("detail", ""))
        line = f"  [{label}]"
        if cap:
            line += " " + (cap if len(cap) <= 60 else cap[:60] + "…")
        if detail:
            line += " … " + (detail if len(detail) <= 100 else detail[:100] + "…")
        return line

    if problems:
        print(f"\n■ 不合格（{len(problems)}件）")
        for x in problems:
            print(_one(x))
    if warnings_:
        print(f"\n■ 警告（{len(warnings_)}件・合否には影響しません。"
              "--strict で不合格にできます）")
        for x in warnings_:
            print(_one(x))
    if not problems and not warnings_:
        print("\n■ 問題なし")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", default=None)
    ap.add_argument("--results-zip", default=None)
    ap.add_argument("--assets", default="fortune_dataset/assets/images")
    ap.add_argument("--pkg", default=None,
                    help="検証用データのあるパッケージ（ディレクトリまたはZIP）。"
                         "省略時は --assets・cwd・スクリプト位置から自動解決（mts5.52）")
    ap.add_argument("--json-out", default=None, help="結果をJSONで保存")
    ap.add_argument("--strict", action="store_true",
                    help="警告（トーン・レイアウト・読み物版・網羅の下限）も不合格にする（mts5.52）")
    ap.add_argument("--expect-images", type=int, default=None,
                    help="この実行で期待する画像枚数（例 87）。指定すると厳密に照合（mts5.52）")
    ap.add_argument("--expect-decks", type=int, default=None,
                    help="この実行で期待するデッキ数（例 48）。指定すると厳密に照合（mts5.52）")
    args = ap.parse_args()
    if not (args.html or args.results_zip):
        raise SystemExit("--html または --results-zip を指定してください")

    assets = Path(args.assets)
    # ---- mts5.52（F-2）: --pkg を実行ディレクトリに依存せず自動解決する ----
    pkg, pkg_tried = resolve_pkg(args.pkg, assets)
    if pkg is None:
        pkg = Path(args.pkg) if args.pkg else (assets.parent.parent if assets.parent.name == "assets" else None)
    tables = build_name_tables(pkg)
    lib_dir = _pkg_lib_dir(pkg)
    print(f"  パッケージ : {pkg if pkg else '（未解決）'}"
          + ("（fortunelib OK）" if lib_dir else "（fortunelib を読めないため型Cは照合不能）"))
    if lib_dir is None:
        # mts5.51 の警告を維持しつつ、行き先を示す。型Cの画像がある実行では下で exit 2。
        print(f"  [警告] --pkg {args.pkg or '(未指定)'} では検証情報を十分に読めません"
              f"（data/*.json: {'OK' if pkg_data_loader(pkg) else '読めない'}・"
              f"fortunelib: 読めない）。型Cの再生成照合と和名→英名の照合が"
              "『不一致／判定不能』に落ちることがあります。"
              "ローカルのリポジトリ直下からは --pkg fortune_dataset、"
              "Kaggle/ZIP展開後は --pkg fortune_dataset/fortune_dataset か、"
              "--assets に <pkg>/assets/images を渡して --pkg を省略してください")
    hash_index = load_hash_index(assets)
    html = read_html(args)
    pairs = PAIR_RE.findall(html)

    # ---- mts5.52（F-2②）: 型Cの照合に必要な材料が無いなら「警告して続行」ではなく exit 2 ----
    # 実行ディレクトリと --pkg の組み合わせ次第で型C 22枚が『納品画像と一致しない』という
    # 誤報（exit 1）になっていた経路を、そもそも判定不能として止める。
    has_typec = any(caption.startswith(m) for _fmt, _b64, caption in pairs
                    for m, _slug in TYPEC_CAPTION_SLUG)
    pkg_images = (lib_dir / "assets" / "images") if lib_dir else None
    if args.results_zip and has_typec and (lib_dir is None or pkg_images is None
                                           or not pkg_images.is_dir()):
        print("\n■ 不合格: 型Cの照合ができません（検証環境の不足。成果物の欠陥ではありません）")
        if lib_dir is None:
            print("  --pkg として使える場所が見つかりませんでした（試した候補: "
                  + "、".join(str(c) for c in pkg_tried) + "）")
        else:
            print(f"  型Cの基準画像がありません（{pkg_images}）")
        print("  → リポジトリ直下なら --pkg fortune_dataset、ZIP展開後なら"
              " --pkg fortune_dataset/fortune_dataset を指定するか、"
              " --assets に <pkg>/assets/images を渡して --pkg を省略してください"
              "（画像を含まない ZIP では型Cを検証できません）")
        return 2

    ok_bytes = miss_bytes = 0
    name_ok = name_bad = unverifiable = 0
    decks: dict[str, int] = {}
    problems: list[dict] = []      # 不合格（既定で exit 1）
    warnings_: list[dict] = []     # 警告（--strict で exit 1。mts5.52・F-3）
    omitted = 0
    notes: list[dict] = []
    typec_unverifiable = 0
    byte_unverified = 0

    for fmt, b64, caption in pairs:
        raw = base64.b64decode(b64)
        h = hashlib.sha256(raw).hexdigest()
        asset = hash_index.get(h)
        deck_from_caption = next((d for mark, d in CAPTION_DECK if mark in caption), None)
        tc_is_typec = any(caption.startswith(m) for m, _s in TYPEC_CAPTION_SLUG)
        # 型C（mts5.16）: 納品画像とバイト不一致でも calc 再生成で照合しうる
        tc_verdict, tc_slug, tc_detail = (None, "", "")
        if asset is None:
            tc_verdict, tc_slug, tc_detail = typec_dynamic_verify(
                caption, raw, args.results_zip, pkg)
        # mts5.52（F-2③）: 型Cで「照合できない」場合は『不一致』ではなく『照合不能』に計上する。
        # 材料（生JSON・再生成画像）が無いのが実行ごとの事情なら不合格のまま（fail-safe は維持）。
        tc_unverifiable = (asset is None and tc_is_typec and tc_verdict is None
                           and bool(args.results_zip))
        if asset or tc_verdict == "ok":
            ok_bytes += 1
            deck = deck_from_caption or (asset.parent.name if asset else tc_slug)
            decks[deck] = decks.get(deck, 0) + 1
        elif tc_unverifiable:
            byte_unverified += 1
            typec_unverifiable += 1
            deck = deck_from_caption or tc_slug or "?"
            decks[deck] = decks.get(deck, 0) + 1
            problems.append({"caption": caption, "kind": "typec_unverifiable",
                             "detail": tc_detail or "型Cの照合ができません"})
        else:
            omitted_mark = next((m for m in OMITTED_DECKS if m in caption), None)
            if omitted_mark:
                # オミット済みデッキの画像（旧い実行結果にのみ現れる）。想定内として参考に回す。
                omitted += 1
                notes.append({"caption": caption, "kind": "omitted",
                              "detail": OMITTED_DECKS[omitted_mark]})
            else:
                miss_bytes += 1
                deck = deck_from_caption or "?"
                problems.append({"caption": caption, "kind": "bytes",
                                 "detail": f"納品画像と一致しない（{len(raw)/1024:.1f}KB）"})

        if tc_verdict in ("ok", "bad"):
            verdict = tc_verdict
            detail = "" if tc_verdict == "ok" else (
                tc_detail or "型C 動的照合（calc 再生成）で不一致")
        elif tc_unverifiable:
            verdict, detail = "unverifiable", (tc_detail or "型Cの照合ができません")
        else:
            verdict, detail = verify_caption(caption, asset, tables)
        if verdict == "ok":
            name_ok += 1
        elif verdict == "bad":
            name_bad += 1
            # mts5.52: 型Cの画素照合で落ちた場合は kind を分ける（従来は name に混ざっていた）
            problems.append({"caption": caption,
                             "kind": "typec" if tc_verdict == "bad" else "name",
                             "detail": detail})
        elif not tc_unverifiable:
            # 日本語名はファイル名が英字のことが多い（例: 遠い地平・希望 -> 36_DistantHorizons）ため判定不能扱い
            unverifiable += 1

    print(f"画像埋め込み: {len(pairs)} 枚")
    print(f"  バイト一致 : {ok_bytes} / 不一致 {miss_bytes}"
          + (f" / 照合不能 {byte_unverified}（型Cの材料不足）" if byte_unverified else ""))
    print(f"  名前の整合 : 一致 {name_ok} / 不一致 {name_bad} / 判定不能 {unverifiable}"
          + (f"（うち型Cの照合不能 {typec_unverifiable}）" if typec_unverifiable else ""))
    if omitted:
        print(f"  オミット済み: {omitted}（想定内・下の［参考］を参照）")
    print("  デッキ別   : " + ", ".join(f"{k}×{v}" for k, v in sorted(decks.items())))

    # ---- mts5.52（F-1・F-5）: 期待値の機械照合。0件は異常として扱う ----
    # 従来は「HTMLに入っているものだけ」を見ており、画像1枚・デッキ丸ごと・全キャプションを
    # 消しても 0 枚・74 枚で『問題なし』exit 0 になっていた（期待値と突き合わせていなかった）。
    if not pairs:
        problems.append({"caption": "（全体）", "kind": "coverage",
                         "detail": "画像が1枚も埋め込まれていません（キャプション0件）。"
                                   "HTML生成の失敗か、画像埋め込みの全欠落です"})
    elif not decks:
        problems.append({"caption": "（全体）", "kind": "coverage",
                         "detail": "デッキ別の集計が0件です（キャプションはあるが画像が無い）"})
    if args.expect_images is not None and len(pairs) != args.expect_images:
        problems.append({"caption": "（全体）", "kind": "coverage",
                         "detail": f"画像枚数が期待と一致しません"
                                   f"（実行 {len(pairs)} / 期待 {args.expect_images}）"})
    if args.expect_decks is not None and len(decks) != args.expect_decks:
        problems.append({"caption": "（全体）", "kind": "coverage",
                         "detail": f"デッキ数が期待と一致しません"
                                   f"（実行 {len(decks)} / 期待 {args.expect_decks}）"})
    ver_exp = None
    _loader = pkg_data_loader(pkg)
    if _loader is not None:
        _ver = _loader("dataset_version.json")
        if isinstance(_ver, dict):
            ver_exp = (_ver.get("expected") or {})
            print(f"  版印       : {_ver.get('build_id', '?')}"
                  f"（期待: slugs {ver_exp.get('slugs')}・deities {ver_exp.get('deities')}"
                  f"・tests {ver_exp.get('tests')}・image_decks {ver_exp.get('image_decks')}）")
    if args.expect_decks is None and ver_exp and ver_exp.get("image_decks"):
        _ed = int(ver_exp["image_decks"])
        if len(decks) < _ed:
            warnings_.append({"caption": "（全体）", "kind": "coverage",
                              "detail": f"デッキ数が版印より少ない（実行 {len(decks)}"
                                        f" / 版印 {_ed}）。デッキが丸ごと欠けている可能性"
                                        "（--expect-decks か --strict で不合格にできます）"})

    # ---- mts5.69: 冒頭動画カード（同梱の固定動画・目次の直前）----
    _iv = verify_intro_video(html, assets)
    INTRO_REPORT.clear()
    INTRO_REPORT.update({k: v for k, v in _iv.items() if k not in ("problems", "warnings")})
    print(_iv["line"])
    problems.extend(_iv["problems"])
    warnings_.extend(_iv["warnings"])

    # ---- mts5.22: トーン化（Stage D）の検証 ----
    tone_rep = verify_tones(html, args.results_zip, str(pkg) if pkg else None)
    if tone_rep is not None and tone_rep.get("mode") == "omake-html":
        h = tone_rep.get("html") or {}
        print("  読み物版切替: 統合レポートの表示UI（results.zip なしのため"
              "本文照合は省略）")
        print(f"    HTML     : 切替UI={'有' if h.get('synthesis_switcher') else '無'}・"
              f"標準初期={'有' if h.get('standard_default') else '無'}・"
              f"ボタン{h.get('buttons', 0)}・"
              f"読み物版JSON={'有' if h.get('variants_json') else '無'}・"
              f"読み物版{h.get('variants', 0)}種")
        _hsc = tone_rep.get("std_html_chars") or 0
        if _hsc:
            _lo, _hi = STD_BAND
            print(f"    標準本文 : HTML から {_hsc}字（仕様の帯 {_lo}〜{_hi}字。"
                  "results.zip なしのため本文の内訳は省略）")
        warnings_.extend(tone_rep["problems"])      # mts5.52: トーンは「警告」（F-3）
        _print_findings(problems, warnings_)
        return _exit_code(problems, warnings_, args.strict)

    if tone_rep is not None and tone_rep.get("mode") == "omake":
        print("  読み物版   : 統合レポート本文の切替タブ（標準を初期表示）")
        _std = tone_rep.get("std") or {}
        if _std:
            _lo, _hi = _std.get("band") or (0, 0)
            _n = _std.get("flash") or 0
            print("    " + std_chars_line(_n, (_lo, _hi), tuple(_std["instruct"])))
            print(f"              標準タブ全体 {_std.get('total')}字"
                  f"＝本文{_n}＋プロファイル{_std.get('profile')}＋目次{_std.get('toc')}＋"
                  f"神々{_std.get('deities')}")
            # mts5.68: 読み物版の分量基準＝標準タブ全体 − ご相談 − 目次
            _ms = _std.get("manifest_source_chars")
            _base_note = (f"製品の基準 {_ms}字と一致" if isinstance(_ms, int)
                          and abs(int(_ms) - int(_std.get("omake_source") or 0)) <= 8
                          else (f"製品の基準 {_ms}字" if isinstance(_ms, int)
                                else "旧版の実行＝製品は標準タブ全体を基準にしていた"))
            print(f"              読み物版の元テキスト {_std.get('omake_source')}字"
                  f"＝標準タブ全体 − ご相談 {_std.get('consultation')}字 − 目次"
                  f"{_std.get('toc')}字（{_base_note}）")
        else:
            _h = tone_rep.get("std_html_chars") or 0
            if _h:
                print(f"    標準本文 : HTML から {_h}字（results.zip なしのため"
                      "仕様の帯との照合は省略）")
        for tid, t in sorted(tone_rep["tones"].items()):
            print(f"    {tid:9s}: {t.get('status')}・{t.get('chars')}字"
                  f"（元の{(t.get('ratio') or 0) * 100:.0f}%）"
                  + (f"・元に無い数値 {len(t['numbers_new'])}件"
                     if t.get("numbers_new") else "")
                  + (f"・{t['attempts']}試行" if t.get("attempts") else ""))
            st = t.get("style") or {}
            if st.get("avg_sentence_chars") is not None:
                print(f"             口調: 丁寧体{(st.get('polite_ratio') or 0) * 100:.0f}%"
                      f"・平均{st['avg_sentence_chars']:.0f}字"
                      f"・目印語{st.get('marker_total')}個"
                      f"・標準類似{(st.get('similarity') or 0) * 100:.0f}%"
                      + (f"・未達{len(st['problems'])}件" if st.get("problems") else ""))
        _pair = (tone_rep.get("discrimination") or {})
        if _pair.get("pairwise"):
            print("    トーン間 : " + "／".join(
                f"{k.replace('|', ' と ')} {(v or 0) * 100:.0f}%"
                for k, v in _pair["pairwise"].items())
                + f"（上限 {(_pair.get('pair_sim_max') or 0) * 100:.0f}%）")
        h = tone_rep.get("html") or {}
        print(f"    HTML     : 切替UI={'有' if h.get('synthesis_switcher') else '無'}・"
              f"本文枠={'有' if h.get('synthesis_body') else '無'}・"
              f"標準初期={'有' if h.get('standard_default') else '無'}・"
              f"旧カード={'有' if h.get('legacy_omake_card') else '無'}・"
              f"読み物版{h.get('omake_tones', 0)}種・データJSON={'有' if h.get('omake_json') else '無'}")
        warnings_.extend(tone_rep["problems"])      # mts5.52: トーンは「警告」（F-3）
        warnings_.extend(tone_rep.get("std_warnings") or [])   # mts5.58: 標準本文の字数
        if notes:
            print("\n［参考］画像をオミットしたデッキ（想定内・問題ではありません）")
            for n in notes:
                print(f"  {n['caption']} … {n['detail']}")
        _print_findings(problems, warnings_)
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(
                _json_payload(pairs, ok_bytes, miss_bytes, byte_unverified, name_ok,
                              name_bad, unverifiable, decks, problems, warnings_,
                              omitted, tone_rep, args), ensure_ascii=False, indent=1) + "\n",
                encoding="utf-8")
        return _exit_code(problems, warnings_, args.strict)

    if tone_rep is None:
        print("  トーン化   : 未生成（tone_manifest.json なし＝前バージョンか Stage D スキップ）")
    else:
        print("  トーン化   : " +
              " / ".join(
                  f"{tid} ok{t['ok']}" + (f"/fb{t['fallback']}" if t["fallback"] else "")
                  + (f"/bad{t['bad']}" if t["bad"] else "")
                  for tid, t in sorted(tone_rep["tones"].items()))
              or "（トーンなし）")
        if tone_rep.get("scope"):
            print(f"    範囲     : {tone_rep['scope']}"
                  f"（対象ユニット {tone_rep.get('target_units')}件"
                  + ("・対象外は標準のまま）" if tone_rep["scope"] == "narrative"
                     else "）"))
        h = tone_rep["html"]
        print(f"    HTML     : tonebar={'有' if h['tonebar'] else '無'}・"
              f"ボタン{h['buttons']}・tone-data JSON={'有' if h['json'] else '無'}・"
              f"JSON内トーン{h.get('json_tones', 0)}・"
              f"data-unit要素{h['units']}")
        warnings_.extend(tone_rep["problems"])      # mts5.52: トーンは「警告」（F-3）
    if notes:
        print("\n［参考］画像をオミットしたデッキ（想定内・問題ではありません）")
        for n in notes:
            print(f"  {n['caption']} … {n['detail']}")
    _print_findings(problems, warnings_)
    if args.json_out:
        # mts5.51: ここに `import json` を置くと json が関数ローカル扱いになり、
        # 同じ関数の前半（読み物版の分岐）の json.dumps が UnboundLocalError で
        # 落ちていた。モジュール先頭の import を使う。
        Path(args.json_out).write_text(json.dumps(
            _json_payload(pairs, ok_bytes, miss_bytes, byte_unverified, name_ok,
                          name_bad, unverifiable, decks, problems, warnings_,
                          omitted, tone_rep, args), ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
    return _exit_code(problems, warnings_, args.strict)


if __name__ == "__main__":
    sys.exit(main())
