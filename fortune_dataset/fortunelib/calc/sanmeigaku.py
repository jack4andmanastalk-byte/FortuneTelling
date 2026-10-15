# -*- coding: utf-8 -*-
"""
算命学（高尾流・人体星図）Python実装
- 参照: lmp.jp 算命学人体星図（高尾流の配置と二十八元）
- 干支計算: lunar_python（節入り・立春基準）
- 十大主星: 日干から見た十神 → 主星対応表
- 十二大従星: 日干と地支の十二運 → 従星対応表
- 人体星図配置: 高尾流（頭=年干, 右手=日支蔵干, 胸=月支蔵干, 腹=月干, 左手=年支蔵干 /
                  左肩=年支, 左足=月支, 右足=日支）
"""
from datetime import datetime, date
from lunar_python import Solar

# ---------- 基本テーブル（lmp.jpのJSから抽出・検証済み） ----------

STEMS = ['甲','乙','丙','丁','戊','己','庚','辛','壬','癸']
BRANCHES = ['子','丑','寅','卯','辰','巳','午','未','申','酉','戌','亥']

STEM_ELEM = {'甲':'木','乙':'木','丙':'火','丁':'火','戊':'土','己':'土','庚':'金','辛':'金','壬':'水','癸':'水'}
STEM_POLAR = {'甲':'陽','乙':'陰','丙':'陽','丁':'陰','戊':'陽','己':'陰','庚':'陽','辛':'陰','壬':'陽','癸':'陰'}

# 五行の相生（この五行が生む先）・相剋（この五行が剋す先）
SHENG = {'木':'火','火':'土','土':'金','金':'水','水':'木'}
KE    = {'木':'土','土':'水','水':'火','火':'金','金':'木'}

# 十大主星: 十神 → 主星（lmp.jp zcテーブル）
JUSHIN_TO_STAR = {
    '比肩':'貫索星','劫財':'石門星','食神':'鳳閣星','傷官':'調舒星',
    '偏財':'禄存星','正財':'司禄星','偏官':'車騎星','正官':'牽牛星',
    '偏印':'龍高星','印綬':'玉堂星',
}

# 十二運の順序（lmp.jp Bcテーブル）
JUNIUN = ['長生','沐浴','冠帯','建禄','帝旺','衰','病','死','墓','絶','胎','養']

# 十二運 → 従星（lmp.jp Vcテーブル）
JUNIUN_TO_STAR = {
    '胎':'天報星','養':'天印星','長生':'天貴星','沐浴':'天恍星','冠帯':'天南星',
    '建禄':'天禄星','帝旺':'天将星','衰':'天堂星','病':'天胡星','死':'天極星',
    '墓':'天庫星','絶':'天馳星',
}

# 従星のエネルギー（lmp.jp Hcテーブル）
STAR_ENERGY = {
    '天将星':12,'天禄星':11,'天南星':10,'天貴星':9,'天堂星':8,'天恍星':7,
    '天印星':6,'天庫星':5,'天胡星':4,'天報星':3,'天極星':2,'天馳星':1,
}

# 五行の長生（十二運の起点）: 干 → 支（lmp.jp Wcテーブル）
CHOSEI = {'甲':'亥','乙':'午','丙':'寅','丁':'酉','戊':'寅','己':'酉','庚':'巳','辛':'子','壬':'申','癸':'卯'}

# 二十八元（蔵干深浅）: 支 → [(干, 日数), ...]（lmp.jp Ycテーブル）
ZOZAN = {
    '子':[('癸',30)],
    '丑':[('癸',9),('辛',3),('己',18)],
    '寅':[('戊',7),('丙',7),('甲',16)],
    '卯':[('乙',30)],
    '辰':[('乙',9),('癸',3),('戊',18)],
    '巳':[('戊',7),('庚',7),('丙',16)],
    '午':[('己',20),('丁',10)],
    '未':[('丁',9),('乙',3),('己',18)],
    '申':[('戊',9),('壬',7),('庚',16)],
    '酉':[('辛',30)],
    '戌':[('辛',9),('丁',3),('戊',18)],
    '亥':[('甲',7),('壬',23)],
}

# 12節（年回りの起点となる節・lmp.jp Zcテーブル）
JIE = ['立春','啓蟄','清明','立夏','芒種','小暑','立秋','白露','寒露','立冬','大雪','小寒']
# 月支 → 節（寅月=立春 ... 丑月=小寒）
BRANCH_TO_JIE = {'寅':'立春','卯':'啓蟄','辰':'清明','巳':'立夏','午':'芒種','未':'小暑',
                 '申':'立秋','酉':'白露','戌':'寒露','亥':'立冬','子':'大雪','丑':'小寒'}


# ---------- 基本計算 ----------

def mod_pos(a, n):
    return (a % n + n) % n

def jushin(day_stem, target_stem):
    """十神: 日干から見た対象干の十神（標準ルール）"""
    if day_stem == target_stem:
        return '比肩'
    de, dtg = STEM_ELEM[day_stem], STEM_ELEM[target_stem]
    same_polar = STEM_POLAR[day_stem] == STEM_POLAR[target_stem]
    if de == dtg:
        return '比肩' if same_polar else '劫財'
    if SHENG[de] == dtg:      # 日干が生む
        return '食神' if same_polar else '傷官'
    if SHENG[dtg] == de:      # 日干を生む
        return '偏印' if same_polar else '印綬'
    if KE[de] == dtg:         # 日干が剋す
        return '偏財' if same_polar else '正財'
    if KE[dtg] == de:         # 日干を剋す
        return '偏官' if same_polar else '正官'
    raise ValueError(f"十神計算エラー: {day_stem} vs {target_stem}")

def jun_iun(day_stem, branch):
    """十二運: 日干と支 → 十二運名（高尾流 = lmp.jp 実装）"""
    start = CHOSEI[day_stem]
    n = BRANCHES.index(start)
    r = BRANCHES.index(branch)
    if STEM_POLAR[day_stem] == '陽':
        idx = mod_pos(r - n, 12)
    else:
        idx = mod_pos(n - r, 12)
    return JUNIUN[idx]

def zozan_kanshi(branch, days_elapsed):
    """蔵干（二十八元・蔵干深浅）: 節入りからの経過日数で決定"""
    total = 0
    for stem, days in ZOZAN[branch]:
        total += days
        if days_elapsed < total:
            return stem
    return ZOZAN[branch][-1][0]


# ---------- 干支・節入り計算（lunar_python） ----------

def get_pillars(year, month, day):
    """年柱・月柱・日柱を取得（節入り基準・立春基準）"""
    solar = Solar.fromYmd(year, month, day)
    lunar = solar.getLunar()
    ec = lunar.getEightChar()
    # 年柱・月柱・日柱（getYear/getMonth/getDay は節入り基準）
    return {
        'year': ec.getYear(),
        'month': ec.getMonth(),
        'day': ec.getDay(),
        'lunar_month': lunar.getMonth(),
        'lunar_day': lunar.getDay(),
    }

# 簡体字 → 日本語 節名マップ（lunar_python は簡体字キーを返す）
CN_TO_JP = {'立春':'立春','惊蛰':'啓蟄','清明':'清明','立夏':'立夏','芒种':'芒種',
            '小暑':'小暑','立秋':'立秋','白露':'白露','寒露':'寒露','立冬':'立冬',
            '大雪':'大雪','小寒':'小寒'}

def get_jie_days_elapsed(year, month, day):
    """属する節（getPrevJie）の節入りからの経過日数"""
    solar = Solar.fromYmd(year, month, day)
    lunar = solar.getLunar()
    prev_jie = lunar.getPrevJie()          # 対象日が属する節（JieQiオブジェクト）
    jie_solar = prev_jie.getSolar()        # 節入り日時（Solarオブジェクト）
    if jie_solar is None:
        return 0
    jie_date = date(jie_solar.getYear(), jie_solar.getMonth(), jie_solar.getDay())
    birth = date(year, month, day)
    elapsed = (birth - jie_date).days
    if elapsed < 0:
        return 0
    return elapsed


# ---------- 人体星図（高尾流配置） ----------

def human_star_chart(year, month, day):
    """算命学 人体星図（高尾流）を計算して返す"""
    pillars = get_pillars(year, month, day)
    y_stem, y_branch = pillars['year'][0], pillars['year'][1]
    m_stem, m_branch = pillars['month'][0], pillars['month'][1]
    d_stem, d_branch = pillars['day'][0], pillars['day'][1]

    days_elapsed = get_jie_days_elapsed(year, month, day)

    # 蔵干（年支・月支・日支）
    z_yr = zozan_kanshi(y_branch, days_elapsed)
    z_mo = zozan_kanshi(m_branch, days_elapsed)
    z_dy = zozan_kanshi(d_branch, days_elapsed)

    # 十大主星（5か所）
    main = [
        {'position':'頭',  'star': JUSHIN_TO_STAR[jushin(d_stem, y_stem)], 'source': y_stem},
        {'position':'右手','star': JUSHIN_TO_STAR[jushin(d_stem, z_dy)],  'source': z_dy},
        {'position':'胸',  'star': JUSHIN_TO_STAR[jushin(d_stem, z_mo)],  'source': z_mo},
        {'position':'腹',  'star': JUSHIN_TO_STAR[jushin(d_stem, m_stem)], 'source': m_stem},
        {'position':'左手','star': JUSHIN_TO_STAR[jushin(d_stem, z_yr)],  'source': z_yr},
    ]

    # 十二大従星（3か所: 年支・月支・日支の十二運）
    def follower(pos, branch):
        stage = jun_iun(d_stem, branch)
        star = JUNIUN_TO_STAR[stage]
        return {'position': pos, 'star': star, 'stage': stage, 'branch': branch, 'energy': STAR_ENERGY[star]}

    follow = [
        follower('左肩', y_branch),
        follower('左足', m_branch),
        follower('右足', d_branch),
    ]

    center = main[2]['star']  # 胸 = 中心星
    total_energy = sum(f['energy'] for f in follow)

    return {
        '陰占': {
            '年柱': f"{y_stem}{y_branch}",
            '月柱': f"{m_stem}{m_branch}",
            '日柱': f"{d_stem}{d_branch}",
            '日干': d_stem,
            '節入り経過日数': days_elapsed,
        },
        '十大主星': main,
        '十二大従星': follow,
        '中心星': center,
        '総エネルギー': total_energy,
    }


def format_chart(year, month, day):
    r = human_star_chart(year, month, day)
    lines = []
    lines.append(f"【算命学 人体星図】{year}-{month:02d}-{day:02d}")
    lines.append(f"陰占: 年柱={r['陰占']['年柱']} 月柱={r['陰占']['月柱']} 日柱={r['陰占']['日柱']} 日干={r['陰占']['日干']}")
    lines.append("十大主星:")
    for m in r['十大主星']:
        lines.append(f"  {m['position']}: {m['star']} (源: {m['source']})")
    lines.append("十二大従星:")
    for f in r['十二大従星']:
        lines.append(f"  {f['position']}: {f['star']} ({f['stage']}) エネルギー={f['energy']}")
    lines.append(f"中心星: {r['中心星']}")
    lines.append(f"総エネルギー: {r['総エネルギー']}")
    return '\n'.join(lines)


if __name__ == '__main__':
    for (y,m,d) in [(1980,3,10),(1990,1,1),(2000,8,16),(1985,6,15),(1975,12,31)]:
        print(format_chart(y,m,d))
        print()


# ---------- 天中殺（空亡・旬ベース） ----------

# 旬（60甲子の10区切り）→ 天中殺（空亡）2支
# 甲子旬→戌亥, 甲戌旬→申酉, 甲申旬→午未, 甲午旬→辰巳, 甲辰旬→寅卯, 甲寅旬→子丑
XUN_TO_TENCHU = {
    '甲子': ['戌', '亥'], '甲戌': ['申', '酉'], '甲申': ['午', '未'],
    '甲午': ['辰', '巳'], '甲辰': ['寅', '卯'], '甲寅': ['子', '丑'],
}
# 天中殺タイプ名（6タイプ）
TENCHU_TYPES = ['子丑', '寅卯', '辰巳', '午未', '申酉', '戌亥']


def xun_first(day_gz):
    """日柱の干支から、属する旬の最初の干支（甲子〜甲寅）を求める"""
    gan = list('甲乙丙丁戊己庚辛壬癸')
    zhi = list('子丑寅卯辰巳午未申酉戌亥')
    jz = [gan[i % 10] + zhi[i % 12] for i in range(60)]
    idx = jz.index(day_gz)
    xun_start = idx - (idx % 10)
    return jz[xun_start]


def tenchusatsu(day_gz):
    """天中殺（空亡）: 日柱の干支から2支（6タイプ）を返す
    例: 甲子旬（甲子〜癸酉）→ 戌亥
    ※ lmp.jp・Wikipedia等で確認: 算命学の天中殺 = 四柱推命の空亡（旬ベース）"""
    xun = xun_first(day_gz)
    branches = XUN_TO_TENCHU[xun]
    type_name = ''.join(branches)
    return {
        '日柱': day_gz,
        '旬': xun,
        '天中殺': branches,
        'タイプ': type_name,
    }


# ---------- 大運（10年運・十二大従星の巡り） ----------

# 十二運の順序（順方向: 長生→養）
# 陽干: 順方向に進行 / 陰干: 逆方向に進行
JUNIUN_ORDER = ['長生', '沐浴', '冠帯', '建禄', '帝旺', '衰', '病', '死', '墓', '絶', '胎', '養']


def daiun(day_stem, month_branch, years=12):
    """算命学 大運（10年運）: 月支の十二運を起点に、10年ごとに十二大従星が巡る
    - 起点: 日干から見た月支の十二運（= 月支の従星）
    - 進行: 陽干は順方向（長生→…→養）、陰干は逆方向（養→…→長生）
    - 0歳から10年ごとに切替（立運の扱いは流派により差異あり・参考実装）
    ※ lmp.jp は大運非対応のため、検証は十二運→従星の対応（既検証17/17と同一テーブル）に基づく"""
    start_stage = jun_iun(day_stem, month_branch)  # 月支の十二運
    start_idx = JUNIUN_ORDER.index(start_stage)
    direction = 1 if STEM_POLAR[day_stem] == '陽' else -1  # 陽干順・陰干逆

    periods = []
    for i in range(years):
        stage_idx = (start_idx + direction * i) % 12
        stage = JUNIUN_ORDER[stage_idx]
        star = JUNIUN_TO_STAR[stage]
        energy = STAR_ENERGY[star]
        periods.append({
            '年齢': f"{i * 10}〜{i * 10 + 9}歳",
            '十二運': stage,
            '従星': star,
            'エネルギー': energy,
        })
    return {
        '日干': day_stem,
        '月支': month_branch,
        '起点の十二運': start_stage,
        '進行方向': '順（陽干）' if direction == 1 else '逆（陰干）',
        '大運': periods,
    }


# 天中殺・大運を組み込んだ統合算命学鑑定
def sanmeigaku_full(year, month, day):
    """算命学 完全版: 人体星図 + 天中殺 + 大運"""
    chart = human_star_chart(year, month, day)
    day_gz = chart['陰占']['日柱']
    day_stem = chart['陰占']['日干']
    month_branch = chart['陰占']['月柱'][1]
    tc = tenchusatsu(day_gz)
    du = daiun(day_stem, month_branch)
    chart['天中殺'] = tc
    chart['大運'] = du
    return chart
