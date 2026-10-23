"""分红日历：原始行解析、税后估算、事件窗口与汇总（离线）。"""
from __future__ import annotations

from datetime import date

import pytest

from fptools.tools.calendar import build_calendar

TODAY = date(2026, 10, 23)


def pos(code="600900", shares=1000, market="cn", buy_date="2024-01-01",
        cost=25.0, name="长江电力", tax_rate=None):
    return {
        "code": code, "market": market, "shares": shares, "cost": cost,
        "buy_date": buy_date, "name": name, "tax_rate": tax_rate,
    }


def raw(**props):
    return {"props": props}


def test_raw_props_plan_event_and_tax():
    rows = {"600900": [raw(**{
        "分红": 0.95,
        "除权除息日": "2026-11-15",
        "股权登记日": "2026-11-14",
        "分红到账日": "2026-11-30",
        "状态": "预案",
        "分红类型": "中期",
        "内容": "10派9.5元(含税)",
        "货币": "人民币",
    })]}
    data = build_calendar([pos()], rows, today=TODAY, fx={"CNY": 1.0})
    event = data["events"][0]
    assert event["ex_date"] == "2026-11-15"
    assert event["record_date"] == "2026-11-14"
    assert event["pay_date"] == "2026-11-30"
    assert event["status"] == "预案"
    assert event["kind"] == "中期"
    assert event["stage"] == "待除权"
    assert event["gross"] == pytest.approx(950.0)
    # 买入超过 1 年 → 0%
    assert event["tax_ratio"] == pytest.approx(0.0)
    assert event["net"] == pytest.approx(950.0)
    assert event["days_to_ex"] == 23
    assert event["days_to_pay"] == 38


def test_placeholder_ex_date_is_a_pending_plan():
    rows = {"600900": [raw(**{
        "分红": 0.95,
        "除权除息日": "2099-01-01",
        "公告日期": "2026-10-01",
        "状态": "预案",
        "分红类型": "中期",
    })]}
    data = build_calendar([pos()], rows, today=TODAY, fx={"CNY": 1.0})
    event = data["events"][0]
    assert event["ex_date"] is None
    assert event["is_plan"] is True
    assert event["stage"] == "预案待定"
    # 预案不进入已确定现金汇总
    assert data["summary"]["next_30_net"] is None
    assert data["summary"]["next_30_ex_net"] is None
    assert data["summary"]["plan_count"] == 1


def test_cancelled_and_pre_buy_rows_are_skipped():
    rows = {"600900": [
        raw(**{"分红": 1.0, "除权除息日": "2026-11-15", "状态": "取消"}),
        raw(**{"分红": 1.0, "除权除息日": "2023-06-01", "状态": "实施"}),
        raw(**{"分红": 1.0, "除权除息日": "2026-11-20", "状态": "实施"}),
    ]}
    data = build_calendar([pos()], rows, today=TODAY, fx={"CNY": 1.0})
    assert [e["ex_date"] for e in data["events"]] == ["2026-11-20"]


def test_hk_default_tax_and_fx():
    rows = {"hk.00700": [raw(**{
        "分红": 5.3,
        "除权除息日": "2026-11-20",
        "分红到账日": "2026-12-05",
        "状态": "预案",
        "货币": "HKD",
    })]}
    data = build_calendar(
        [pos(code="hk.00700", market="hk", cost=400.0, name="腾讯控股")],
        rows, today=TODAY, fx={"CNY": 1.0, "HKD": 0.85},
    )
    event = data["events"][0]
    assert event["currency"] == "HKD"
    assert event["tax_ratio"] == pytest.approx(0.20)
    assert event["tax_source"] == "hk_default"
    assert event["estimated"] is True
    assert event["gross"] == pytest.approx(5300.0)
    assert event["net"] == pytest.approx(4240.0)
    assert event["gross_cny"] == pytest.approx(4505.0)
    assert event["net_cny"] == pytest.approx(3604.0)


def test_received_ytd_ttm_and_cost_yield_are_cny():
    rows = {
        "600900": [
            raw(**{"分红": 1.0, "除权除息日": "2026-07-15",
                   "分红到账日": "2026-07-30", "状态": "实施"}),
            raw(**{"分红": 1.0, "除权除息日": "2026-11-15",
                   "分红到账日": "2026-11-30", "状态": "预案"}),
        ],
        "hk.00700": [
            raw(**{"分红": 5.3, "除权除息日": "2026-05-20",
                   "分红到账日": "2026-06-05", "状态": "实施", "货币": "HKD"}),
        ],
    }
    data = build_calendar(
        [pos(shares=1000), pos(code="hk.00700", market="hk", shares=1000,
                               cost=400.0, name="腾讯控股")],
        rows, today=TODAY, fx={"CNY": 1.0, "HKD": 0.85},
    )
    summary = data["summary"]
    # TTM: 1000*1.0 + 1000*5.3*0.85 = 5505
    assert summary["annual_dividend"] == pytest.approx(5505.0)
    # 已收: CN 1000 + HK 5300*0.85 = 5505 税前；HK 20% 税后 4505
    assert summary["received_ytd_gross"] == pytest.approx(5505.0)
    assert summary["received_ytd_net"] == pytest.approx(5505.0 - 1000 * 0.0 - 901.0)
    # 成本收益率只汇总有成本的票：annual 5505 / cost (25000 + 340000)
    assert summary["cost_yield"] == pytest.approx(5505.0 / 365000.0)


def test_ex_window_counts_upcoming_ex_even_if_cash_later():
    rows = {"600900": [raw(**{
        "分红": 1.0,
        "除权除息日": "2026-11-15",
        "分红到账日": "2026-12-31",
        "状态": "实施",
    })]}
    data = build_calendar([pos()], rows, today=TODAY, fx={"CNY": 1.0})
    assert data["summary"]["next_30_net"] is None       # 到账在 30 天后
    assert data["summary"]["next_30_ex_net"] == pytest.approx(1000.0)
    assert data["summary"]["event_count_30"] == 1
    assert data["summary"]["ex_count_30"] == 1


def test_market_mode_has_no_personal_cash():
    rows = {"600900": [raw(**{
        "分红": 1.0,
        "除权除息日": "2026-11-15",
        "分红到账日": "2026-11-30",
        "状态": "预案",
    })]}
    data = build_calendar(
        [pos(shares=0, cost=None)], rows, today=TODAY, fx={"CNY": 1.0})
    event = data["events"][0]
    assert event["dps"] == pytest.approx(1.0)
    assert event["gross"] is None and event["net"] is None
    assert data["summary"]["annual_dividend"] is None
