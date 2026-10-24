"""必赢佬·区间分布与极值：估值三区分布、股价×买卖点三区、距极值溢价。

构造全部为关系型合成序列，不绑定任何单一公司的绝对量级。
"""
import pytest

from bigwinner.bigly.backtest import price_extremes, price_zone_stats
from bigwinner.bigly.channel import zone_counts

BAND = {"lower2": 8.0, "upper2": 12.0}


def bar(day, close, low=None, high=None):
    return {"date": day, "open": close, "high": high or close * 1.01,
            "low": low or close * 0.99, "close": close}


# ---- 估值倍数三区分布 ----

def test_zone_counts_three_zones():
    # 边界值 8.0/12.0 计入通道内（与 coverage 同口径）
    vals = [7.9, 8.0, 9.0, 12.0, 12.1, 9.5, 7.0, 13.0]
    z = zone_counts(vals, BAND)
    assert z["n"] == 8
    assert z["below_low"]["days"] == 2      # 7.9, 7.0
    assert z["inside"]["days"] == 4         # 8.0, 9.0, 12.0, 9.5
    assert z["above_high"]["days"] == 2     # 12.1, 13.0
    assert z["below_low"]["ratio"] == pytest.approx(0.25)
    assert z["above_high"]["ratio"] == pytest.approx(0.25)


def test_zone_counts_empty():
    z = zone_counts([], BAND)
    assert z["n"] == 0 and z["below_low"]["ratio"] is None


# ---- 股价极值 ----

def test_price_extremes_premium_and_discount():
    bars = [bar("d01", 10.0), bar("d02", 9.0), bar("d03", 11.0),
            bar("d04", 9.5), bar("d05", 10.2)]
    ex = price_extremes(bars, last_close=10.2)
    assert ex["low"]["price"] == 9.0 and ex["low"]["date"] == "d02"
    assert ex["low"]["premium_pct"] == pytest.approx(10.2 / 9.0 - 1)   # 现价较最低溢出
    assert ex["high"]["price"] == 11.0 and ex["high"]["date"] == "d03"
    assert ex["high"]["discount_pct"] == pytest.approx(10.2 / 11.0 - 1)  # 距高点折价
    assert ex["last_close"] == 10.2


def test_price_extremes_empty():
    assert price_extremes([]) is None


# ---- 股价 × 买卖点三区分布 ----

def test_price_zone_stats_three_zones():
    bars = [bar("d01", 9.0),    # < 买点 9.5
            bar("d02", 10.0),   # 区间内
            bar("d03", 12.5),   # > 卖点 12.0
            bar("d04", 9.4),    # < 买点
            bar("d05", 11.0)]   # 区间内
    ps = price_zone_stats(bars, buy_price=9.5, sell_price=12.0, last_close=11.0)
    assert ps["n"] == 5
    assert ps["below_buy"]["days"] == 2
    assert ps["inside"]["days"] == 2
    assert ps["above_sell"]["days"] == 1
    assert ps["below_buy"]["ratio"] == pytest.approx(0.4)
    assert ps["extremes"]["low"]["premium_pct"] == pytest.approx(11.0 / 9.0 - 1)
    assert ps["buy_price"] == 9.5 and ps["sell_price"] == 12.0


def test_price_zone_stats_invalid_inputs():
    bars = [bar("d01", 10.0)]
    assert price_zone_stats(bars, None, 12.0) is None
    assert price_zone_stats([], 9.5, 12.0) is None
