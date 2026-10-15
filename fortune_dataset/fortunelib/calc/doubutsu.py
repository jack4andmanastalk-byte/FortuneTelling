
# 動物占い（60種体系）計算モジュール
_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
def is_leap(y): return (y % 4 == 0 and y % 100 != 0) or (y % 400 == 0)
def _base(y):
    # 2000年=54 を起点に前後へ
    if y == 2000: return 54
    if y > 2000: return (_base(y-1) + 365 + (1 if is_leap(y-1) else 0)) % 60
    return (_base(y+1) - 365 - (1 if is_leap(y) else 0)) % 60
def year_month_value(y, m):
    days = _DAYS[:]
    if is_leap(y): days[1] = 29
    return (_base(y) + sum(days[:m-1])) % 60
def doubutsu_number(y, m, d):
    n = (year_month_value(y, m) + d) % 60
    return 60 if n == 0 else n
