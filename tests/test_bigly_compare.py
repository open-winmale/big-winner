"""必赢佬·波段 vs 长持对比：基准数学与差值方向。"""
import pytest

from bigwinner.bigly.backtest import backtest_levels, compare_with_hold


def bar(day, o, h, l, c):
    return {"date": day, "open": o, "high": h, "low": l, "close": c}


def test_hold_return_is_first_to_last_close():
    bars = [bar("01-01", 10.0, 10.5, 9.5, 10.0),
            bar("01-02", 10.0, 11.0, 9.8, 10.5),
            bar("01-03", 10.5, 11.5, 10.2, 12.0)]
    bt = backtest_levels(bars, buy_price=9.5, sell_price=11.0)
    cmp_ = compare_with_hold(bars, bt)
    assert cmp_["hold"]["return_pct"] == pytest.approx(12.0 / 10.0 - 1)
    assert cmp_["hold"]["days"] == 3


def test_swing_excludes_flat_period():
    # 触发后空仓期收益为 0：止盈后价格继续涨，与长持的差值应体现踏空
    bars = [bar("01-01", 10.0, 10.5, 9.5, 10.0),
            bar("01-02", 9.8, 10.2, 9.4, 9.9),    # 买入 @9.5
            bar("01-03", 10.0, 11.0, 9.9, 10.9),  # 止盈 @11.0
            bar("01-04", 11.5, 12.5, 11.2, 12.0)]  # 止盈后继续上涨（波段踏空）
    bt = backtest_levels(bars, buy_price=9.5, sell_price=11.0)
    cmp_ = compare_with_hold(bars, bt)
    assert cmp_["swing"]["return_pct"] == pytest.approx(11.0 / 9.5 - 1)
    assert cmp_["swing"]["flat_ratio"] == pytest.approx(0.25)
    assert cmp_["delta"]["return_spread"] == pytest.approx(
        cmp_["swing"]["return_pct"] - cmp_["hold"]["return_pct"])
    # 此例长持更强 → spread < 0
    assert cmp_["delta"]["return_spread"] < 0
    assert "跑输" in cmp_["verdict"]


def test_swing_beats_hold_verdict():
    # 深回撤行情：波段止盈离场 → 跑赢长持
    bars = [bar("01-01", 10.0, 10.5, 9.5, 10.0),
            bar("01-02", 9.8, 11.5, 9.4, 11.0),   # 买入并涨至止盈区
            bar("01-03", 11.0, 12.0, 10.9, 11.2),  # 止盈 @11.5 附近（open 11 ≤ 11.5→fill 11.5）
            bar("01-04", 9.0, 9.5, 8.0, 8.5)]      # 之后暴跌（长持承受）
    bt = backtest_levels(bars, buy_price=9.5, sell_price=11.5)
    cmp_ = compare_with_hold(bars, bt)
    assert cmp_["delta"]["return_spread"] > 0
    assert "跑赢" in cmp_["verdict"]


def test_never_bought_swing_return_is_none():
    bars = [bar("01-01", 20.0, 21.0, 19.5, 20.5),
            bar("01-02", 20.2, 20.8, 19.8, 20.4)]
    bt = backtest_levels(bars, buy_price=10.0, sell_price=30.0)
    cmp_ = compare_with_hold(bars, bt)
    assert cmp_["swing"]["return_pct"] is None
    assert cmp_["delta"]["return_spread"] is None
    assert cmp_["verdict"] is None
