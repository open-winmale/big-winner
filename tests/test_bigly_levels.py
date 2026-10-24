"""波段·买卖点换算：通道回退默认 / 自定义区间透传 / 线性换算数学 / 容错。"""
import pytest

from bigwinner.bigly import levels as lv

BAND = {"lower2": 10.0, "lower1": 15.0, "upper1": 25.0, "upper2": 30.0,
        "avg": 20.0, "median": 19.0}


def _hist(current=20.0):
    return {"current": current}


def test_channel_rail_defaults():
    out = lv.build_levels(_hist(20.0), BAND, last_close=10.0)
    assert out["low_source"] == "channel" and out["high_source"] == "channel"
    assert out["buy_price"] == pytest.approx(5.0)    # 10 × 10/20
    assert out["sell_price"] == pytest.approx(15.0)  # 10 × 30/20
    assert out["price_map"]["avg"] == pytest.approx(10.0)
    assert "EPS/BPS 恒定" in out["assumption"]


def test_user_estimates_passthrough():
    out = lv.build_levels(_hist(20.0), BAND, last_close=10.0, low=12.0, high=24.0)
    assert out["low_source"] == "user" and out["high_source"] == "user"
    assert out["buy_price"] == pytest.approx(6.0)    # 10 × 12/20
    assert out["sell_price"] == pytest.approx(12.0)  # 10 × 24/20


def test_distance_to_levels():
    out = lv.build_levels(_hist(25.0), BAND, last_close=12.5,
                          low=10.0, high=30.0)
    # 买价 = 12.5 × 10/25 = 5 → 距离 = 5/12.5 - 1 = -0.6
    assert out["distance_to_buy_pct"] == pytest.approx(-0.6)
    # 卖价 = 12.5 × 30/25 = 15 → 距离 = 15/12.5 - 1 = 0.2
    assert out["distance_to_sell_pct"] == pytest.approx(0.2)


def test_implied_price_guards():
    assert lv.implied_price(None, 10, 20) is None
    assert lv.implied_price(10, 0, 20) is None
    assert lv.implied_price(10, 15, None) is None
    assert lv.implied_price(10, 15, 20) == pytest.approx(7.5)


def test_missing_current_returns_none():
    assert lv.build_levels({"current": None}, BAND, last_close=10.0) is None
    assert lv.build_levels({"current": 0}, BAND, last_close=10.0) is None


def test_zero_current_multiple_guard():
    # current ≤ 0（异常数据）→ implied_price 保护返回 None
    out = lv.build_levels({"current": 0.0}, BAND, last_close=10.0)
    assert out is None
