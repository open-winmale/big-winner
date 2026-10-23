"""server.run_ledger 的入参归一/税率选项测试（离线，用 FakeFetcher）。"""
from __future__ import annotations

import pytest

import fptools.server as srv
from fptools.fetchers import FakeFetcher


@pytest.fixture(autouse=True)
def fake_runtime(monkeypatch):
    fetcher = FakeFetcher(
        history={
            "600519": [{"ex_date": "2024-06-20", "sas": "2023-12-31", "dps": 30.0}],
            "hk.00700": [{"ex_date": "2024-05-20", "sas": "2023:Q4", "dps": 3.4}],
        },
        fx={"HKD": 0.8},
    )
    monkeypatch.setattr(srv.RUNTIME, "_fetcher", fetcher)


def test_run_ledger_normalizes_hk_code_and_applies_flat_tax():
    data = srv.run_ledger({
        "positions": [{"code": "00700", "market": "hk", "shares": 1000,
                       "buy_date": "2020-01-01"}],
        "tax": {"mode": "flat", "flat_rate": 0.10},
    })
    stock = data["stocks"][0]
    assert stock["code"] == "hk.00700"
    assert stock["market"] == "hk"
    assert stock["currency"] == "HKD"
    event = stock["events"][0]
    assert event["tax_ratio"] == pytest.approx(0.10)
    assert event["tax_source"] == "flat"
    assert data["total_gross"] == pytest.approx(1000 * 3.4 * 0.8)


def test_run_ledger_accepts_percent_tax_rate():
    data = srv.run_ledger({
        "positions": [{"code": "600519", "market": "cn", "shares": 100,
                       "buy_date": "2020-01-01", "tax_rate": 20}],
    })
    assert data["stocks"][0]["events"][0]["tax_ratio"] == pytest.approx(0.20)


def test_run_ledger_rejects_bad_tax_mode_and_year():
    positions = [{"code": "600519", "shares": 100}]
    with pytest.raises(srv.ToolError):
        srv.run_ledger({"positions": positions, "tax": {"mode": "bogus"}})
    with pytest.raises(srv.ToolError):
        srv.run_ledger({"positions": positions, "year": "not-a-year"})


def test_run_ledger_requires_valid_positions():
    with pytest.raises(srv.ToolError):
        srv.run_ledger({"positions": [{"code": "", "shares": 0}]})
