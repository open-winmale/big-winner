"""必赢佬·安全边界：高位介入回撤统计与买入位安全检查。"""
import pytest

from bigwinner.bigly.backtest import buy_safety_check, high_entry_drawdown_stats


def _trending_series():
    # 先涨到 100（高位），再腰斩到 50：高位（>75 分位）介入者必遭深回撤
    up = [60 + i * 4 for i in range(11)]          # 60..100（11 点）
    down = [100 - i * 5 for i in range(1, 11)]    # 95..50（10 点）
    return up + down


def test_high_entry_drawdown_stats_flags_deep_mdd():
    closes = _trending_series()
    st = high_entry_drawdown_stats(closes, ref_percentile=0.75)
    assert st is not None and st["sample_n"] >= 5
    # 高位介入的最差回撤应非常深（腰斩行情 → 接近 -50%）
    assert st["worst_mdd"] <= -0.45
    assert st["median_mdd"] <= -0.2


def test_low_percentile_ref_returns_none_when_samples_sparse():
    # ref=1.0 时几乎无样本 → 返回 None（样本 <5）
    closes = list(range(20, 40))
    assert high_entry_drawdown_stats(closes, ref_percentile=1.0) is None
    # 序列太短也返回 None
    assert high_entry_drawdown_stats([1.0, 2.0, 3.0], ref_percentile=0.5) is None


def test_buy_safety_check_flags_above_p75():
    closes = [float(v) for v in range(10, 30)]  # 单调上涨 10..29
    out = buy_safety_check(buy_price=28.0, channel=None, window_closes=closes)
    assert out["high"] is True
    assert any("75%" in r for r in out["reasons"])


def test_buy_safety_check_low_entry_is_calm():
    closes = [float(v) for v in range(10, 30)]
    out = buy_safety_check(buy_price=12.0, channel=None, window_closes=closes)
    assert out["high"] is False and out["reasons"] == []


def test_buy_safety_check_empty_guards():
    out = buy_safety_check(None, None, [])
    assert out == {"high": False, "reasons": []}


def test_upper1_price_comparison_marks_high():
    # 通道 +1σ=28（倍数）、current=20、现价 20 → +1σ 对应价 28；买入 28.5 > 28 → 高位
    closes = [float(v) for v in range(10, 30)]
    band = {"upper1": 28.0, "current": 20.0}
    out = buy_safety_check(buy_price=28.5, channel=band, window_closes=closes,
                           last_close=20.0)
    assert out["high"] is True
    assert any("+1σ" in r for r in out["reasons"])


def test_upper1_price_comparison_low_entry_is_calm():
    # 买入价低于 +1σ 对应价 → 不误判（坐标换算正确性回归）
    closes = [float(v) for v in range(10, 30)]
    band = {"upper1": 28.0, "current": 20.0}
    out = buy_safety_check(buy_price=20.0, channel=band, window_closes=closes,
                           last_close=20.0)
    assert out["high"] is False
