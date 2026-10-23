"""server.run_calendar / positions-latest / Store.latest_position_set 测试。"""
from __future__ import annotations

import pytest

import fptools.server as srv
from fptools.fetchers import FakeFetcher
from fptools.store import Store


@pytest.fixture(autouse=True)
def fake_runtime(monkeypatch):
    class FakeScreener:
        def high_yield(self, market="cn", limit=120):
            return []  # 走 FakeFetcher 的 high_yield_symbols 兜底

    monkeypatch.setattr(srv, "SCREENER", FakeScreener())
    fetcher = FakeFetcher(
        prices={"600900": 28.1, "hk.00700": 382.4},
        yields={"600900": 0.0338, "hk.00700": 0.01373},
        history={
            "600900": [
                {"sas": "2025-12-31", "ex_date": "2026-07-15",
                 "record_date": "2026-07-14", "pay": "2026-07-30",
                 "dps": 1.0, "status": "实施"},
                {"sas": "2026-06-30", "ex_date": "2026-11-15",
                 "record_date": "2026-11-14", "pay": "2026-11-30",
                 "dps": 1.0, "status": "预案", "kind": "中期"},
            ],
            "hk.00700": [
                {"sas": "2025-12-31", "ex_date": "2026-05-20",
                 "record_date": "2026-05-19", "pay": "2026-06-05",
                 "dps": 5.3, "status": "实施", "ccy": "HKD"},
                {"sas": "2026-06-30", "ex_date": "2026-11-20",
                 "record_date": "2026-11-19", "pay": "2026-12-05",
                 "dps": 5.3, "status": "预案", "kind": "中期", "ccy": "HKD"},
            ],
        },
        fx={"HKD": 0.85},
    )
    monkeypatch.setattr(srv.RUNTIME, "_fetcher", fetcher)


def test_run_calendar_positions():
    data = srv.run_calendar({
        "positions": [
            {"code": "600900", "market": "cn", "shares": 1000,
             "cost": 25, "buy_date": "2024-01-01", "name": "长江电力"},
            {"code": "hk.00700", "market": "hk", "shares": 1000,
             "cost": 400, "buy_date": "2024-01-01", "name": "腾讯控股"},
        ],
        "tax": {"mode": "auto"},
    })
    assert data["mode"] == "positions"
    codes = {e["code"] for e in data["events"]}
    assert codes == {"600900", "hk.00700"}
    assert data["summary"]["annual_dividend"] == pytest.approx(5505.0)
    assert data["summary"]["next_30_ex_net"] == pytest.approx(1000.0 + 3604.0)
    hk = next(e for e in data["events"] if e["market"] == "hk")
    assert hk["currency"] == "HKD"
    assert hk["tax_source"] == "hk_default"


def test_run_calendar_codes_is_observation_pool():
    data = srv.run_calendar({
        "mode": "codes",
        "codes": ["600900", "hk.00700"],
        "market": "cn",
    })
    assert data["mode"] == "codes"
    assert len(data["events"]) == 2
    assert all(e["shares"] == 0 for e in data["events"])
    assert all(e["gross"] is None for e in data["events"])


def test_run_calendar_market_pool():
    data = srv.run_calendar({"mode": "market", "market": "cn"})
    assert data["mode"] == "market"
    assert data["market"] == "cn"
    assert data["events"]


def test_run_calendar_rejects_bad_mode_and_empty_positions():
    with pytest.raises(srv.ToolError):
        srv.run_calendar({"mode": "bogus"})
    with pytest.raises(srv.ToolError):
        srv.run_calendar({"positions": []})


def test_store_latest_position_set(tmp_path):
    store = Store(tmp_path / "test.db")
    assert store.latest_position_set() is None
    store.save_positions("主仓", [{"code": "600900", "shares": 1000}])
    store.save_positions("观察", [{"code": "00700", "shares": 100}])
    latest = store.latest_position_set()
    assert latest is not None
    assert latest["name"] == "观察"
    assert latest["positions"][0]["code"] == "00700"


def test_stock_screener_parses_screen_rows(monkeypatch):
    from fptools import watchlist_sync

    monkeypatch.setattr(watchlist_sync, "_run_skill",
                        lambda *args, **kwargs: {"data": {"result": {"rows": [{
                            "values": {
                                "$SYMBOL": "600519",
                                "$NAME": "贵州茅台",
                                "$BONUS_RATE_TTM_LAST": 0.04,
                            }
                        }]}}})
    out = watchlist_sync.StockScreener().high_yield("cn", 10)
    assert out == [{
        "code": "600519",
        "market": "cn",
        "name": "贵州茅台",
        "yield_ttm": 0.04,
    }]
