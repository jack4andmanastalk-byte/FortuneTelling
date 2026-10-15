"""クリスタル・ヒーリング／パワーストーンの石プール（mts5.60 で切り出し）。

もともと `html_report.py` の中に定数として持っていた「素材画像のある21石」を、
**プロンプト（鑑定文を書くモデルへの候補リスト）と HTML の画像解決で同じ表を使う**ために
モジュールへ移しました。片方だけ増減すると「本文が名指しした石の画像が無い」状態が
再発するため（mts5.58 の実機で `M30_crystal` の画像が1枚欠けた原因）、**唯一の正本**にします。

- 1〜12: クリスタル12石（mts5.9）
- 13〜21: 誕生石の追加9石（mts5.13）
- 素材は `assets/images/M30_crystal/NN_EnglishName.webp`（パワーストーン M12_stone と共用）
"""

#: (番号, 和名, 英名, 別名（照合に使う小文字トークン）)
CRYSTAL_STONES = [
    (1, "アメジスト", "Amethyst", ("amethyst",)),
    (2, "水晶", "Clear Quartz", ("clear quartz", "clearquartz", "rock crystal")),
    (3, "ローズクォーツ", "Rose Quartz", ("rose quartz", "rosequartz")),
    (4, "シトリン", "Citrine", ("citrine",)),
    (5, "アベンチュリン", "Aventurine", ("aventurine",)),
    (6, "ラピスラズリ", "Lapis Lazuli", ("lapis lazuli", "lapislazuli")),
    (7, "ターコイズ", "Turquoise", ("turquoise",)),
    (8, "オニキス", "Onyx", ("onyx",)),
    (9, "フローライト", "Fluorite", ("fluorite",)),
    (10, "カーネリアン", "Carnelian", ("carnelian",)),
    (11, "ムーンストーン", "Moonstone", ("moonstone",)),
    (12, "ガーネット", "Garnet", ("garnet",)),
    (13, "アクアマリン", "Aquamarine", ("aquamarine",)),
    (14, "ダイヤモンド", "Diamond", ("diamond", "ダイヤ")),
    (15, "エメラルド", "Emerald", ("emerald",)),
    (16, "パール", "Pearl", ("pearl", "真珠")),
    (17, "ルビー", "Ruby", ("ruby", "紅玉")),
    (18, "ペリドット", "Peridot", ("peridot",)),
    (19, "サファイア", "Sapphire", ("sapphire", "青玉")),
    (20, "オパール", "Opal", ("opal", "蛋白石")),
    (21, "トパーズ", "Topaz", ("topaz", "黄玉")),
]

#: 鑑定文に書いてよい石名の一覧（プロンプトへ埋め込む。mts5.60）
STONE_NAME_LIST_JA = "、".join(f"{ja}（{en}）" for _n, ja, en, _a in CRYSTAL_STONES)


def stone_ja_en(no: int) -> tuple:
    """石番号 → (和名, 英名)。未知なら空文字。"""
    return next(((j, e) for n, j, e, _a in CRYSTAL_STONES if n == no), ("", ""))


def stone_no_for_ja(name: str) -> int:
    """和名 → 石番号（無ければ 0）。"""
    return next((n for n, j, _e, _a in CRYSTAL_STONES if j == name), 0)


def resolve_stone_in_text(text: str) -> int:
    """鑑定文に現れた石名（和名・英名）を石番号へ解決する。

    出現位置が先のものを優先し、同位置なら長い名前（例: ローズクォーツ > クォーツ）を採る。
    どの石にも一致しなければ 0（＝画像を出さない）。
    """
    if not text:
        return 0
    low = text.lower()
    hits: list[tuple[int, int, int]] = []
    for no, ja, _en, alts in CRYSTAL_STONES:
        for token in (ja, *alts):
            idx = text.find(token) if token == ja else low.find(token.lower())
            if idx >= 0:
                hits.append((idx, -len(token), no))
    if not hits:
        return 0
    return min(hits)[2]
