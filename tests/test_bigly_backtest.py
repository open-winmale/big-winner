"""波段·拨测状态机：规则逐条对齐（限价成交 / T+1 / 同日双触保守 / 持仓中）。"""
import pytest

from bigwinner.bigly.backtest import backtest_levels, max_drawdown


def bar(day, o, h, l, c):
    return {"date": day, "open": o, "high": h, "low": l, "close": c}


def test_full_round_trip():
    bars = [
        bar("01-01", 10.0, 10.5, 9.7, 10.0),   # 未触发（low > 买点）
        bar("01-02", 9.8, 10.2, 9.4, 9.9),    # low 9.4 ≤ 买点 9.5 → 触发
        bar("01-03", 10.1, 11.2, 10.0, 11.0),  # high 11.2 ≥ 卖点 11.0 → 止盈
    ]
    bt = backtest_levels(bars, buy_price=9.5, sell_price=11.0)
    assert bt["hit_buy"] and bt["hit_sell"]
    assert bt["buy_date"] == "01-02" and bt["buy_fill"] == 9.5
    assert bt["sell_reason"] == "target" and bt["sell_fill"] == 11.0
    assert bt["days_held"] == 1
    assert bt["return_pct"] == pytest.approx(11.0 / 9.5 - 1)
    assert bt["still_holding"] is False


def test_open_gap_fills_at_better_price():
    # 跳空低开：open 9.0 < 买点 9.5 → 按 open 成交（更优价）
    bars = [bar("01-01", 10.0, 10.5, 9.8, 10.0),
            bar("01-02", 9.0, 9.6, 8.9, 9.3)]
    bt = backtest_levels(bars, buy_price=9.5, sell_price=11.0)
    assert bt["buy_fill"] == 9.0
    # 跳空高开卖出：open 12 > 卖点 11 → 按 open 成交
    bars2 = bars + [bar("01-03", 12.0, 12.5, 11.5, 12.2)]
    bt2 = backtest_levels(bars2, buy_price=9.5, sell_price=11.0)
    assert bt2["sell_fill"] == 12.0


def test_never_triggers_reports_distance():
    bars = [bar("01-01", 20.0, 21.0, 19.5, 20.5),
            bar("01-02", 20.2, 20.8, 19.8, 20.4)]
    bt = backtest_levels(bars, buy_price=10.0, sell_price=30.0)
    assert bt["hit_buy"] is False and bt["hit_sell"] is False
    assert bt["distance_to_buy_pct"] == pytest.approx(10.0 / 20.4 - 1)


def test_t_plus_one_no_same_day_sell():
    # 买入当日（若同时触及止损位）：T+1 规则下当日不卖，次日才执行
    bars = [bar("01-01", 10.0, 10.5, 9.7, 10.0),   # 未触发（low 9.7 > 买点 9.5）
            bar("01-02", 9.0, 10.4, 8.8, 9.2),     # low≤买点触发；当日不判卖出
            bar("01-03", 8.5, 9.0, 8.0, 8.4)]      # 次日 low ≤ 止损 → 止损出场
    bt = backtest_levels(bars, buy_price=9.5, sell_price=12.0, stop_loss=8.5)
    assert bt["hit_buy"] and bt["sell_reason"] == "stop"
    assert bt["buy_date"] == "01-02" and bt["sell_date"] == "01-03"


def test_same_day_both_triggers_conservative_stop_first():
    bars = [bar("01-01", 10.0, 10.5, 9.7, 10.0),   # 未触发
            bar("01-02", 9.6, 10.2, 9.4, 9.9),     # 触发买入 @min(9.6,9.5)=9.5
            bar("01-03", 9.5, 12.0, 8.4, 9.0)]     # 同日：low≤止损 且 high≥止盈 → 保守先止损
    bt = backtest_levels(bars, buy_price=9.5, sell_price=11.5, stop_loss=8.5)
    assert bt["sell_reason"] == "stop"
    assert bt["sell_fill"] == 8.5


def test_still_holding_unrealized():
    bars = [bar("01-01", 10.0, 10.5, 9.5, 10.0),
            bar("01-02", 9.8, 10.2, 9.4, 9.9),
            bar("01-03", 10.0, 10.6, 9.9, 10.4)]  # 未到卖点，窗口末仍持仓
    bt = backtest_levels(bars, buy_price=9.5, sell_price=11.0)
    assert bt["still_holding"] is True and bt["hit_sell"] is False
    assert bt["return_pct"] == pytest.approx(10.4 / 9.5 - 1)


def test_no_stop_worst_drawdown_reported():
    bars = [bar("01-01", 10.0, 10.5, 9.7, 10.0),   # 未触发
            bar("01-02", 9.6, 10.2, 9.4, 9.9),     # 买入 @9.5
            bar("01-03", 8.6, 9.0, 7.6, 8.0),      # 深回撤：最低 7.6（收盘 8.0）
            bar("01-04", 8.2, 9.2, 8.0, 9.0)]      # 未到止盈、未设止损 → 仍持仓
    bt = backtest_levels(bars, buy_price=9.5, sell_price=11.0)
    assert bt["no_stop_worst_drawdown"] == pytest.approx(7.6 / 9.5 - 1)
    # 持仓期回撤按收盘计：峰 9.9 → 谷 8.0
    assert bt["holding_mdd"] == pytest.approx(8.0 / 9.9 - 1)


def test_max_drawdown_helper():
    assert max_drawdown([10.0, 12.0, 6.0, 11.0]) == pytest.approx(-0.5)


def test_underwater_days_counted():
    # 亏损持仓 = 窗口内持仓且收盘低于成交买价的交易日（衡量套牢时长）
    bars = [
        bar("01-01", 10.0, 10.5, 9.7, 10.0),   # 未触发
        bar("01-02", 9.6, 10.2, 9.4, 9.9),     # 买入 @9.5；收盘 9.9 ≥ 买价 → 不算
        bar("01-03", 9.0, 9.6, 8.8, 9.2),      # 收盘 9.2 < 9.5 → 亏损持仓
        bar("01-04", 9.1, 9.4, 8.9, 9.1),      # 亏损持仓
        bar("01-05", 9.0, 9.5, 8.9, 9.4),      # 亏损持仓
        bar("01-06", 9.5, 10.4, 9.4, 10.1),    # 收盘 10.1 ≥ 9.5 → 不算；未到卖点
    ]
    bt = backtest_levels(bars, buy_price=9.5, sell_price=11.0)
    assert bt["still_holding"] is True
    assert bt["underwater_days"] == 3
    assert bt["underwater_ratio"] == pytest.approx(3 / 6)


def test_underwater_none_when_never_bought():
    bars = [bar("01-01", 10.0, 10.5, 9.7, 10.0)]
    bt = backtest_levels(bars, buy_price=5.0, sell_price=20.0)
    assert bt["underwater_days"] is None and bt["underwater_ratio"] is None


def test_multi_roundtrips_reenter_after_target():
    # roundtrips=None：止盈出场后资金回笼，卖出次日可再次买入 → 两轮完整进出
    bars = [
        bar("01-01", 10.0, 10.5, 9.6, 10.0),  # 未触发（low 9.6 > 买点 9.5）
        bar("01-02", 9.4, 9.9, 9.3, 9.8),     # 第一轮买入 @9.4
        bar("01-03", 10.0, 11.2, 9.9, 11.0),  # 第一轮止盈 @11.0
        bar("01-04", 10.5, 10.9, 10.4, 10.8),  # 空仓（卖出次日才可再买）
        bar("01-05", 9.4, 9.8, 9.2, 9.5),     # 第二轮买入 @9.4
        bar("01-06", 10.0, 11.5, 9.9, 11.2),  # 第二轮止盈 @11.0
    ]
    bt = backtest_levels(bars, buy_price=9.5, sell_price=11.0, roundtrips=None)
    assert bt["entries"] == 2 and bt["roundtrips_done"] == 2
    assert bt["return_pct"] == pytest.approx((11.0 / 9.4) * (11.0 / 9.4) - 1)
    assert bt["days_held"] == 2  # 每轮各持仓 1 个交易日间隔
    assert bt["still_holding"] is False
    assert bt["sell_date"] == "01-06" and bt["sell_reason"] == "target"
    assert [e["type"] for e in bt["events"]] == ["buy", "sell", "buy", "sell"]
    # 默认 roundtrips=1 保持平台拨测语义：第一轮止盈即结束
    bt1 = backtest_levels(bars, buy_price=9.5, sell_price=11.0)
    assert bt1["entries"] == 1 and bt1["roundtrips_done"] == 1
    assert bt1["return_pct"] == pytest.approx(11.0 / 9.4 - 1)


def test_multi_roundtrips_stop_then_reenter():
    # 止损出场后同样可再入场；最后一次出场口径 = 第二轮的止盈
    bars = [
        bar("01-01", 10.0, 10.5, 9.6, 10.0),
        bar("01-02", 9.4, 9.9, 9.3, 9.8),     # 第一轮买入 @9.4
        bar("01-03", 9.0, 9.2, 8.4, 8.5),     # 止损 @8.5
        bar("01-04", 8.0, 8.6, 7.9, 8.4),     # 第二轮买入 @8.0
        bar("01-05", 9.5, 11.4, 9.4, 11.0),   # 第二轮止盈 @11.0
    ]
    bt = backtest_levels(bars, buy_price=9.5, sell_price=11.0,
                         stop_loss=8.5, roundtrips=None)
    assert bt["stop_count"] == 1 and bt["roundtrips_done"] == 2
    assert bt["hit_sell"] is True and bt["sell_reason"] == "target"
    assert bt["return_pct"] == pytest.approx((8.5 / 9.4) * (11.0 / 8.0) - 1)


def test_compare_multi_roundtrips_counts():
    from bigwinner.bigly.backtest import compare_with_hold

    bars = [
        bar("01-01", 10.0, 10.5, 9.6, 10.0),
        bar("01-02", 9.4, 9.9, 9.3, 9.8),
        bar("01-03", 10.0, 11.2, 9.9, 11.0),
        bar("01-04", 10.5, 10.9, 10.4, 10.8),
        bar("01-05", 9.4, 9.8, 9.2, 9.5),
        bar("01-06", 10.0, 11.5, 9.9, 11.2),
    ]
    bt = backtest_levels(bars, buy_price=9.5, sell_price=11.0, roundtrips=None)
    cmp_ = compare_with_hold(bars, bt)
    assert cmp_["swing"]["trades"] == 2
    # 持仓日合计 2 + 两轮的买卖日各 1 = 4 天持仓，空仓 2/6
    assert cmp_["swing"]["flat_ratio"] == pytest.approx(2 / 6)
