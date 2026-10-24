"""分红记账税档/覆盖/币种测试（离线）。"""
from __future__ import annotations

from datetime import date

import pytest

from bigwinner.tools.ledger import (
    HK_DEFAULT_TAX,
    build_ledger,
    dividend_tax_ratio,
)


def rows(*dates: str, dps: float = 1.0) -> list[dict]:
    return [{"ex_date": d, "sas": d, "dps": dps} for d in dates]


def pos(code="600000", shares=1000, market="cn", buy_date=None, tax_rate=None):
    return {
        "code": code, "shares": shares, "market": market,
        "buy_date": buy_date, "tax_rate": tax_rate, "name": code,
    }


# ---------------------------------------------------------------- 分档


def test_a_share_holding_period_tiers():
    buy = date(2024, 1, 1)
    assert dividend_tax_ratio(buy, date(2024, 1, 31)) == pytest.approx(0.20)   # 30 天
    assert dividend_tax_ratio(buy, date(2024, 2, 1)) == pytest.approx(0.10)    # 31 天
    assert dividend_tax_ratio(buy, date(2024, 12, 31)) == pytest.approx(0.10)  # 365 天
    assert dividend_tax_ratio(buy, date(2025, 1, 1)) == pytest.approx(0.0)     # 366 天
    assert dividend_tax_ratio(None, date(2024, 1, 1)) == pytest.approx(0.20)


def test_a_share_tax_varies_by_event_date():
    data = build_ledger(
        [pos(buy_date="2024-01-01")],
        {"600000": rows("2024-01-15", "2024-06-01", "2025-06-01")},
    )
    by_date = {e["ex_date"]: e for e in data["stocks"][0]["events"]}
    assert by_date["2024-01-15"]["tax_ratio"] == pytest.approx(0.20)
    assert by_date["2024-06-01"]["tax_ratio"] == pytest.approx(0.10)
    assert by_date["2025-06-01"]["tax_ratio"] == pytest.approx(0.0)
    assert by_date["2025-06-01"]["tax_source"] == "auto"


def test_missing_buy_date_falls_back_to_20_and_is_estimated():
    data = build_ledger([pos()], {"600000": rows("2024-06-01")})
    event = data["stocks"][0]["events"][0]
    assert event["tax_ratio"] == pytest.approx(0.20)
    assert event["tax_source"] == "fallback"
    assert event["estimated"] is True


# ---------------------------------------------------------------- 买入日之前


def test_events_before_buy_are_skipped():
    data = build_ledger(
        [pos(buy_date="2024-01-01")],
        {"600000": rows("2023-06-01", "2024-06-01")},
    )
    assert data["skipped_before_buy"] == 1
    assert [e["ex_date"] for e in data["stocks"][0]["events"]] == ["2024-06-01"]
    assert any("买入日之前" in n for n in data["note"].split())


# ---------------------------------------------------------------- 年份与汇总


def test_year_filter_and_available_years():
    data = build_ledger(
        [pos(buy_date="2024-01-01")],
        {"600000": rows("2023-06-01", "2024-06-01", "2025-06-01")},
        year=2024,
    )
    assert [e["ex_date"] for e in data["stocks"][0]["events"]] == ["2024-06-01"]
    # 2023 的除权在买入日之前，不该出现在可选年份里
    assert data["available_years"] == [2025, 2024]
    assert [b["year"] for b in data["by_year"]] == [2024]
    assert data["by_year"][0]["events"] == 1


def test_position_override_beats_global_and_year():
    base = [pos(buy_date="2024-01-01", tax_rate=0.05)]
    data = build_ledger(
        base, {"600000": rows("2024-06-01")},
        tax={"mode": "flat", "flat_rate": 0.12, "year_rates": {"2024": 0.15}},
    )
    event = data["stocks"][0]["events"][0]
    assert event["tax_ratio"] == pytest.approx(0.05)
    assert event["tax_source"] == "position"
    assert event["estimated"] is False


def test_year_override_beats_flat_and_auto():
    data = build_ledger(
        [pos(buy_date="2024-01-01")],
        {"600000": rows("2024-06-01", "2025-06-01")},
        tax={"mode": "by_year", "year_rates": {"2024": 0.15}},
    )
    by_date = {e["ex_date"]: e for e in data["stocks"][0]["events"]}
    assert by_date["2024-06-01"]["tax_ratio"] == pytest.approx(0.15)
    assert by_date["2024-06-01"]["tax_source"] == "year"
    # 没配置的年份继续走自动规则（>1 年 → 0%）
    assert by_date["2025-06-01"]["tax_ratio"] == pytest.approx(0.0)
    assert by_date["2025-06-01"]["tax_source"] == "auto"


def test_flat_override_applies_to_all_events():
    data = build_ledger(
        [pos(buy_date="2024-01-01")],
        {"600000": rows("2024-06-01", "2025-06-01")},
        tax={"mode": "flat", "flat_rate": 0.12},
    )
    assert all(e["tax_ratio"] == pytest.approx(0.12)
               for e in data["stocks"][0]["events"])
    assert all(e["tax_source"] == "flat" for e in data["stocks"][0]["events"])


# ---------------------------------------------------------------- 港股与币种


def test_hk_uses_flat_default_not_holding_period():
    data = build_ledger(
        [pos(code="hk.00700", market="hk", buy_date="2020-01-01")],
        {"hk.00700": rows("2024-06-01", dps=5.3)},
        fx={"CNY": 1.0, "HKD": 0.85},
    )
    event = data["stocks"][0]["events"][0]
    assert event["tax_ratio"] == pytest.approx(HK_DEFAULT_TAX)
    assert event["tax_source"] == "hk_default"
    assert event["estimated"] is True
    assert event["currency"] == "HKD"
    assert event["gross"] == pytest.approx(5300.0)
    assert event["gross_cny"] == pytest.approx(4505.0)
    assert data["stocks"][0]["gross_cny"] == pytest.approx(4505.0)
    assert data["total_gross"] == pytest.approx(4505.0)


def test_mixed_currency_totals_are_cny():
    data = build_ledger(
        [
            pos(code="600000", shares=1000, buy_date="2024-01-01"),
            pos(code="hk.00700", shares=1000, market="hk", buy_date="2024-01-01"),
        ],
        {
            "600000": rows("2024-06-01", dps=1.0),
            "hk.00700": rows("2024-06-01", dps=5.3),
        },
        fx={"CNY": 1.0, "HKD": 0.5},
    )
    assert data["total_gross"] == pytest.approx(1000 * 1.0 + 1000 * 5.3 * 0.5)
    assert data["total_currency"] == "CNY"
    assert data["fx_hkd_cny"] == pytest.approx(0.5)
    assert any("HKD→CNY" in s for s in data["note"].split("。"))


def test_missing_fx_leaves_totals_none_but_keeps_native_detail():
    data = build_ledger(
        [pos(code="hk.00700", shares=1000, market="hk", buy_date="2024-01-01")],
        {"hk.00700": rows("2024-06-01", dps=5.3)},
        fx={"CNY": 1.0, "HKD": None},
    )
    assert data["stocks"][0]["events"][0]["gross"] == pytest.approx(5300.0)
    assert data["stocks"][0]["events"][0]["gross_cny"] is None
    assert data["total_gross"] is None
    assert data["total_net"] is None
    assert any("缺汇率" in n for n in data["note"].split("。"))


def test_empty_history_returns_zero_totals():
    data = build_ledger([pos()], {"600000": []})
    assert data["total_gross"] == 0.0
    assert data["total_net"] == 0.0
    assert data["stocks"][0]["events"] == []
