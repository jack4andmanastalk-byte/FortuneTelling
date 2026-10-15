# -*- coding: utf-8 -*-
"""
Cell 2 計算バッチ（Phase 4後半）
- build_profile_facts(ni): プロファイル事実（profile_summary.json の facts）
- build_calc_results(ni, session_id, consultation, now, seed): 全占術の計算結果
- RNG系は make_seed(session_id, consultation, now, salt=calc_key) で再現可能に固定
- 各計算は safe() でラップし、1件失敗してもバッチ全体が落ちないようにする
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta

from .data import load_json
from .prompt import sanitize
from .profile import NormalizedInput
from .rng import make_seed
from .calc.eto import year_ganzhi_detailed
from .calc.zodiac import sun_sign_of, sun_sign_en
from .calc.kyusei import honmei_detail
from .calc.numerology import (life_path, name_number_pythagorean,
                              kabbalah_value, chaldean_value)
from .calc.weton import weton_detail
from .calc.jieqi import effective_year_for_lichun

JST = timezone(timedelta(hours=9))

TOKYO = (35.6895, 139.6917)



def resolve_place(birth) -> tuple:
    """出生地 → (lat, lon, note)。未対応は東京扱い

    ★DUP-02（2026-08-17）: 以前は batch.py 独自の _pref_coords を持っており、
      profile.resolve_place と二重管理になっていた（照合ルールも微妙に相違）。
      → 正規化済みの BirthInfo が保持する座標をそのまま使う。
    """
    if birth.place_unknown:
        return TOKYO[0], TOKYO[1], "（出生地が未入力・または未対応のため東京扱い）"
    return birth.place_lat, birth.place_lon, ""


def _hour_float(time_str: str) -> float:
    hh, mm = (time_str or "12:00").split(":")
    return int(hh) + int(mm) / 60


def _lichun_year(d: date) -> int:
    return effective_year_for_lichun(d)


def build_profile_facts(ni: NormalizedInput) -> dict:
    """プロファイル事実（サマリーの facts・全占術の共通土台）"""
    b = ni.birth
    y = _lichun_year(b.date)
    g = year_ganzhi_detailed(y)
    facts = {
        "太陽星座": sun_sign_of(b.date),
        "干支（年柱・立春基準）": g["ganzhi"],
        "十二支の動物": g["animal"],
        "九星気学（本命星）": honmei_detail(y)["honmei"],
        "数秘術（ライフパス）": life_path(b.date),
        "ウェトン": weton_detail(b.date)["weton_name"],
    }
    if ni.blood_type != "unknown":
        facts["血液型"] = f"{ni.blood_type}型"
    if ni.name_romaji:
        facts["氏名（ヘボン式）"] = ni.name_romaji
    if ni.name_kanji:
        # Stage Cへ入力氏名を正本として渡す。モデル指示に使われ得る文字列なので
        # 相談文と同じインジェクション対策を適用してから事実欄へ載せる。
        facts["氏名（漢字）"] = sanitize(ni.name_kanji)
    if ni.name_kana:
        facts["氏名（かな）"] = sanitize(ni.name_kana)
    if ni.partner:
        facts["相手の生年月日"] = ni.partner.date.isoformat()
    return facts


def build_calc_results(ni: NormalizedInput, session_id: str = "",
                       consultation: str = "", now: datetime | None = None,
                       rng_mode: str = "random") -> dict:
    """
    全占術の計算結果（calc_results）を一括生成。

    RNG系は rng_mode に応じて:
      - "random"（既定）: 毎回ランダム（本物の占い体験・クロスチェック決定）
      - "reproducible": make_seed(session_id, consultation, now, salt) で再現（テスト用）
    失敗した計算は {"error": ..., "note": ...} を返しバッチを継続する。
    """
    now = now or datetime.now(JST)
    b = ni.birth
    y = _lichun_year(b.date)
    lat, lon, place_note = resolve_place(b)
    hour = _hour_float(b.time)
    hour_int = int(b.time.split(":")[0])
    consult = consultation or "今日の運勢"

    def seed_for(key: str) -> int | None:
        if rng_mode == "reproducible":
            return make_seed(session_id, consultation, when=now, salt=key)
        return None  # ランダムモードではシードなし

    def safe(key: str, fn):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            return {"error": str(e), "note": "計算に失敗しました（β扱い・要調査）"}

    R = {}

    # ---- 対象日（今日の運勢モード用・⑦クロスチェック拡張） ----
    # 内部アンカーは常に実行日へフォールバック（計算は不変）。明示指定の検出は
    # 表示層が NormalizedInput.target_date から直接導出し、calc_results の
    # スキーマには手を入れない（mts4.1・B案統合）。
    target = ni.target_date or now.date()
    R["target_date"] = {"date": target.isoformat(), "is_today": target == now.date()}
    R["target_kanzashi"] = safe("target_kanzashi", lambda: _target_kanzashi(target))
    R["target_kyusei_day"] = safe("target_kyusei_day", lambda: _target_kyusei_day(target))
    R["target_weton"] = safe("target_weton", lambda: weton_detail(target))
    R["target_primbon"] = safe("target_primbon", lambda: _primbon_target(target))

    # ---- G1 基本プロファイル ----
    R["zodiac"] = safe("zodiac", lambda: {
        "sign": sun_sign_of(b.date), "sign_en": sun_sign_en(b.date.month, b.date.day),
        "date": b.date.isoformat()})
    R["eto"] = safe("eto", lambda: {
        "year": y, **year_ganzhi_detailed(y),
        "note": "立春基準（立春前は前年扱い）"})
    R["kyusei"] = safe("kyusei", lambda: {
        "year": y, **honmei_detail(y), "note": "立春基準"})
    R["numerology_birth"] = safe("numerology_birth", lambda: {
        "life_path": life_path(b.date), "date": b.date.isoformat()})
    lp = life_path(b.date)  # tantra/anka は同じ出生数ベース
    R["tantra"] = safe("tantra", lambda: {
        "number": lp % 11 or 11, "note": "タントラは11で一巡（1-11）。出生数ベース"})
    R["anka"] = safe("anka", lambda: {
        "number": lp, "note": "アンカ・シャーストラは惑星対応（1=太陽…9=火星）"})
    R["blood"] = safe("blood", lambda: {"type": ni.blood_type})

    # 動物占い（60種・別AI実装の数式を採用・検証済み 30/31一致）
    def _animal():
        from .calc.doubutsu import doubutsu_number
        n = doubutsu_number(b.date.year, b.date.month, b.date.day)
        # 60キャラ名CSVからキャラ名を引く（CSVはJSONでないため直接読む）
        import csv
        name = ""
        try:
            from .data import DATA_DIR
            with open(DATA_DIR / "doubutsu_60character.csv", encoding="utf-8-sig") as f:  # BOM対策
                reader = csv.DictReader(f)
                name_map = {int(r["number"]): r["character_name"] for r in reader}
            name = name_map.get(n, "")
        except Exception:
            name = ""
        return {"number": n, "character": name, "lichun_year": y,
                "note": "60種体系（12動物×5タイプ）・別AI実装の数式（2000年=54基準）を採用"}
    R["animal"] = safe("animal", _animal)

    # 六星占術（確定版・masanosuke.net公開値と照合済み）
    def _rokusei():
        from .calc.rokusei import rokusei_calc
        # 年運に加えて月運・日運も出す（対象日は now に合わせる）
        tgt = now.date() if hasattr(now, "date") else now
        r = rokusei_calc(b.date.year, b.date.month, b.date.day,
                         target_year=tgt.year, target=tgt)
        r["status"] = "ok"
        return r
    R["rokusei"] = safe("rokusei", _rokusei)
    R["weton"] = safe("weton", lambda: weton_detail(b.date))
    # プリンボン（確定版・ネプツヌ体系）
    def _primbon():
        from .calc.primbon import primbon_calc
        r = primbon_calc(b.date, birth=True)
        r["status"] = "ok"
        return r
    R["primbon"] = safe("primbon", _primbon)

    # パワーストーン・おみくじ・ジーンキーズ
    def _stones():
        from .data import load_json as _lj
        data = _lj("birthstones.json")
        bs = next(x for x in data["birthstones"] if x["month"] == b.date.month)
        sign = sun_sign_of(b.date)
        zs = next((x for x in data["zodiac_stones"] if x["sign"] == sign), None)
        return {"birthstone": bs["stone_ja"], "zodiac_stone": zs}
    R["stones"] = safe("stones", _stones)
    R["omikuji"] = safe("omikuji", lambda: _omikuji_draw(seed_for("omikuji"), rng_mode))
    # ジーンキーズ（確定・簡易版: 太陽ゲートのみ）
    def _genekeys():
        from .data import load_json as _lj2
        data = _lj2("genekeys_64.json")
        hd = _hd_sun_gate(b, hour, lat, lon)
        gate = hd["gate"]
        key = next((k for k in data["keys"] if k["gate"] == gate), None)
        return {
            "status": "ok",
            "sun_gate": hd,
            "key": key,
            "note": "簡易版（太陽ゲートのみ）。ギフト・シャドウはLLMがゲート名から解釈",
        }
    R["genekeys"] = safe("genekeys", _genekeys)

    # ---- G2 氏名系 ----
    def _strokes():
        # 統合画数辞書（KANJIDIC2 新字体画数 + Unihan 補完・約103,000字）を採用
        from .calc.seimei import strokes_of, seimei_calc
        if not ni.name_kanji:
            return {"status": "template", "note": "氏名（漢字）未入力"}
        parts = ni.name_kanji.replace(" ", "").replace("　", "")
        # 姓・名の分割（最後の1文字を「名」と仮定する簡易ルールは誤りを生むため、
        # 全角スペース区切り or 2文字以上なら 姓=先頭1〜n の判定は呼び出し側に委ねる。
        # ここでは「姓=先頭1文字 + 名=残り」を既定とし、missing を報告する）
        if " " in ni.name_kanji or "　" in ni.name_kanji:
            import re
            parts = re.split(r"[ 　]+", ni.name_kanji.strip())
            surname, given = parts[0], "".join(parts[1:])
        else:
            surname, given = parts[0], parts[1:]  # 簡易分割（姓1文字）
        calc = seimei_calc(surname, given)
        if calc["missing_chars"]:
            calc["note"] = f"辞書にない文字: {calc['missing_chars']}（Unihan補完でも未収録）"
        return calc
    R["seimei"] = safe("seimei", _strokes)
    if isinstance(R["seimei"], dict) and "status" not in R["seimei"]:
        R["seimei"]["status"] = "ok"
    R["numerology_name"] = safe("numerology_name", lambda: {
        "romaji": ni.name_romaji, "number": name_number_pythagorean(ni.name_romaji)})
    R["kabbalah"] = safe("kabbalah", lambda: {
        "romaji": ni.name_romaji, "number": kabbalah_value(ni.name_romaji),
        "note": "方式A（アルファベット数値）"})
    R["chaldean"] = safe("chaldean", lambda: {
        "romaji": ni.name_romaji, "number": chaldean_value(ni.name_romaji)})

    # ---- G3 命盤系 ----
    from .calc.bazi import bazi_paipan
    R["bazi"] = safe("bazi", lambda: bazi_paipan(
        b.date.year, b.date.month, b.date.day, hour_int, 0,
        lon_east=lon, apply_true_solar=True))
    from .calc.astrology import natal_chart, transit_chart, vedic_sidereal, to_jd, human_design
    R["western"] = safe("western", lambda: natal_chart(
        b.date.year, b.date.month, b.date.day, hour, lat, lon))
    R["natal"] = safe("natal", lambda: natal_chart(
        b.date.year, b.date.month, b.date.day, hour, lat, lon))
    if isinstance(R["western"], dict) and "error" not in R["western"]:
        R["transit"] = safe("transit", lambda: transit_chart(R["western"], now))
    else:
        R["transit"] = {"error": "western が計算できなかったためスキップ", "note": "β扱い"}
    R["vedic"] = safe("vedic", lambda: vedic_sidereal(
        to_jd(b.date.year, b.date.month, b.date.day, hour)))
    from .calc.ziwei import ziwei_chart
    R["ziwei"] = safe("ziwei", lambda: ziwei_chart(
        b.date.year, b.date.month, b.date.day, hour_int, gender=ni.birth.gender,
        as_of=now.date()))
    # 算命学（別AI実装・高尾流・lmp.jp実機と17/17一致・天中殺/大運対応）
    def _sanmei():
        from .calc.sanmeigaku import sanmeigaku_full
        full = sanmeigaku_full(b.date.year, b.date.month, b.date.day)
        return {"status": "ok", **full,
                "note": "高尾流（lmp.jp実機と17/17一致・別AI実装を採用）"}
    R["sanmei"] = safe("sanmei", _sanmei)

    # HD（本格版・human-design-py移植・26惑星ゲート）
    def _hd():
        from .calc.hd_full import calculate_chart, get_historical_offset
        if not ni.birth.place_unknown:
            try:
                utc_offset = get_historical_offset(
                    ni.birth.place_name, b.date.year, b.date.month, b.date.day,
                    hour_int, int(b.time.split(":")[1]) if ":" in b.time else 0)
            except Exception:
                utc_offset = 9.0
        else:
            utc_offset = 9.0  # 東京
        hd = calculate_chart(b.date.year, b.date.month, b.date.day,
                             hour_int, int(b.time.split(":")[1]) if ":" in b.time else 0,
                             utc_offset)
        hd["utc_offset"] = utc_offset
        hd["note"] = "本格版（human-design-py 移植・別AI実装で26/26ゲート検証済み）"
        return hd
    R["hd"] = safe("hd", _hd)

    # ---- G4 相談・抽選系（RNG はセッションシードで固定） ----
    from .calc.iching import cast as iching_cast
    R["iching"] = safe("iching", lambda: iching_cast(method="coin", seed=seed_for("iching"), mode=rng_mode))
    from .calc.liuyao import liuyao_paipan
    # mts5.50: 起卦時刻はエンジンの基準時刻（JST）を渡す。六神・空亡・神煞が
    # コンテナのローカル時刻（Kaggle＝UTC）に依存しないようにする。
    R["liuyao"] = safe("liuyao", lambda: liuyao_paipan(seed=seed_for("liuyao"),
                                                       rng_mode=rng_mode, when=now))
    from .calc.meihua import cast as meihua_cast
    R["meihua"] = safe("meihua", lambda: meihua_cast(source="text", text=consult))
    from .calc.qimen import qimen_pan
    R["qimen"] = safe("qimen", lambda: qimen_pan(
        now.year, now.month, now.day, now.hour, now.minute))
    from .calc.cards import draw
    R["tarot"] = safe("tarot", lambda: draw("tarot", count=10, spread="celtic_cross",
                                            seed=seed_for("tarot"), mode=rng_mode))
    R["marseille"] = safe("marseille", lambda: draw("marseille", count=3, spread="three",
                                                    seed=seed_for("marseille"), mode=rng_mode))
    R["lenormand"] = safe("lenormand", lambda: draw("lenormand", count=3, spread="three",
                                                    seed=seed_for("lenormand"), mode=rng_mode))
    R["kipper"] = safe("kipper", lambda: draw("kipper", count=5,
                                              seed=seed_for("kipper"), mode=rng_mode))
    R["oracle"] = safe("oracle", lambda: draw("oracle", count=3,
                                              seed=seed_for("oracle"), mode=rng_mode))
    R["angel"] = safe("angel", lambda: draw("angel", count=3,
                                            seed=seed_for("angel"), mode=rng_mode))
    R["cartomancy"] = safe("cartomancy", lambda: draw("cartomancy", count=5,
                                                      seed=seed_for("cartomancy"), mode=rng_mode))
    R["runes"] = safe("runes", lambda: draw("runes", count=3,
                                            seed=seed_for("runes"), mode=rng_mode))
    R["urbantarot"] = safe("urbantarot", lambda: {
        "tarot": draw("tarot", count=3, spread="three", seed=seed_for("urbantarot"), mode=rng_mode),
        "sun_sign": sun_sign_of(b.date)})

    # ---- G5 相性系 ----
    def _synastry():
        if ni.partner is None:
            return {"error": "相手情報なし", "note": "対象外"}
        p = ni.partner
        ph = _hour_float(p.time)
        plat, plon, _ = resolve_place(p)
        mine = natal_chart(b.date.year, b.date.month, b.date.day, hour, lat, lon)
        theirs = natal_chart(p.date.year, p.date.month, p.date.day, ph, plat, plon)
        # 相互アスペクト（太陽・月・ASC・金星を代表に）
        pairs = []
        for a_name in ("太陽", "月", "金星"):
            for b_name in ("太陽", "月", "金星"):
                d = abs(mine["planets"][a_name]["lon"] - theirs["planets"][b_name]["lon"]) % 360
                d = min(d, 360 - d)
                for angle, aname in ((0, "コンジャンクション"), (60, "セクスタイル"),
                                     (90, "スクエア"), (120, "トライン"), (180, "オポジション")):
                    orb = 8.0 if (a_name == "月" or b_name == "月") else 6.0
                    if abs(d - angle) <= orb:
                        pairs.append({"p1": a_name, "p2": b_name, "aspect": aname,
                                      "angle": angle, "orb": round(abs(d - angle), 2)})
                        break
        return {"aspects": pairs, "mine": mine, "theirs": theirs}
    R["synastry"] = safe("synastry", _synastry)
    # パリミチャム（確定版・タミルPorutham簡易実装）
    def _parimicham():
        if ni.partner is None:
            return {"status": "unavailable", "note": "相手情報なし"}
        from .calc.parimicham import parimicham_calc
        r = parimicham_calc(
            {"date": b.date.isoformat()},
            {"date": ni.partner.date.isoformat()},
            role1="本人", role2="相手")
        r["status"] = "ok"
        return r
    R["parimicham"] = safe("parimicham", _parimicham)

    # 御縁のある神さま Top10（疑似オラクル・M31）
    def _deities():
        from .calc.deities import draw_deities
        f = build_profile_facts(ni)
        f["_consultation"] = consultation or ""
        tgt = ni.target_date or now.date()
        return draw_deities(f, target=tgt, seed=seed_for("deities"),
                            rng_mode=rng_mode)
    R["deities"] = safe("deities", _deities)

    # テキスト抽選型（おみくじ方式）: 実在テキストを1件引いて解釈の起点にする
    from .calc.textdraw import draw_omen, draw_verse
    R["meso_omen"] = safe("meso_omen",
                          lambda: draw_omen(seed=seed_for("meso_omen"),
                                            rng_mode=rng_mode))
    R["bible_verse"] = safe("bible_verse",
                            lambda: draw_verse(seed=seed_for("bible_verse"),
                                               rng_mode=rng_mode))

    # ---- G6 のうち抽選を持つもの ----
    from .calc.pendulum import swing, throw_cowrie
    from .calc.omikuji import throw_astragaloi
    R["pendulum"] = safe("pendulum", lambda: swing(seed=seed_for("pendulum"), mode=rng_mode))
    R["cowrie"] = safe("cowrie", lambda: throw_cowrie(seed=seed_for("cowrie"), mode=rng_mode))
    R["astragaloi"] = safe("astragaloi", lambda: throw_astragaloi(seed=seed_for("astragaloi"), mode=rng_mode))

    return R


# ---- 内部ヘルパー ----
def _omikuji_draw(seed: int | None, rng_mode: str = "random") -> dict:
    from .calc.omikuji import draw_omikuji
    return draw_omikuji(seed=seed, mode=rng_mode)


def _primbon_target(d: date) -> dict:
    """対象日のプリンボン（吉凶・過ごし方）"""
    from .calc.primbon import primbon_calc
    r = primbon_calc(d, birth=False)
    r["status"] = "ok"
    return r


def _target_kanzashi(d: date) -> dict:
    """対象日の干支（四柱の日柱基準）"""
    import sxtwl
    gan = "甲乙丙丁戊己庚辛壬癸"
    zhi = "子丑寅卯辰巳午未申酉戌亥"
    day = sxtwl.fromSolar(d.year, d.month, d.day)
    yg, yz = day.getYearGZ().tg, day.getYearGZ().dz
    mg, mz = day.getMonthGZ().tg, day.getMonthGZ().dz
    dg, dz = day.getDayGZ().tg, day.getDayGZ().dz
    return {
        "date": d.isoformat(),
        "year": gan[yg] + zhi[yz],
        "month": gan[mg] + zhi[mz],
        "day": gan[dg] + zhi[dz],
    }


def _target_kyusei_day(d: date) -> dict:
    """対象日の日命星（簡易計算・[要検証]）
    方式: 日干支の60甲子番号 n（甲子=0）から 日命星 = (n % 9) + 1（甲子日=一白水星）
    ※ 日命星の算出法は流派により異なるためβ扱い（注記付き）
    """
    import sxtwl
    gan = "甲乙丙丁戊己庚辛壬癸"
    zhi = "子丑寅卯辰巳午未申酉戌亥"
    names = ["一白水星", "二黒土星", "三碧木星", "四緑木星", "五黄土星",
             "六白金星", "七赤金星", "八白土星", "九紫火星"]
    day = sxtwl.fromSolar(d.year, d.month, d.day)
    dg, dz = day.getDayGZ().tg, day.getDayGZ().dz
    for n in range(60):
        if n % 10 == dg and n % 12 == dz:
            idx = n
            break
    star_no = (idx % 9) + 1  # 甲子=0 → 一白
    return {
        "date": d.isoformat(),
        "day_ganzhi": gan[dg] + zhi[dz],
        "day_star": names[star_no - 1],
        "method": "甲子起算方式（甲子=一白・(六十甲子番号 mod 9)+1）",
        "note": "日命星の算出は流派により異なる（本実装は甲子起算方式を確定・簡易）",
    }


def _hd_sun_gate(b, hour: float, lat: float, lon: float) -> dict:
    from .calc.astrology import human_design
    hd = human_design(b.date.year, b.date.month, b.date.day, hour, lat, lon)
    return {"gate": hd["sun"]["gate"], "line": hd["sun"]["line"],
            "gate_name": hd["sun"]["gate_name"]}
