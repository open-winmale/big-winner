"""server.run_dividend_quality：资格边界、单票隔离、汇总（离线）。"""
from __future__ import annotations

import pytest

import bigwinner.shouxi.server as srv
from bigwinner.common.fetchers import FakeFetcher


def quality_payload(**overrides):
    data = {
        "payout_ttm": 0.5, "payout_lyr": 0.5,
        "yield_ttm": 0.04,
        "ncfo_ttm": 1.6e9, "fcf_ttm": 1.2e9, "cf_np": 1.0,
        "ncfo_3y_min": 1.2e9, "cfo_kind": 1,
        "npts_ttm": 1.0e9, "npts_yoy": 0.05,
        "roe": 0.12, "roic": 0.10,
        "tl_rate": 0.35, "ibd_rate": 0.12, "quick": 1.2,
        "org_type": 1, "free_holder_sum": 0.5, "exec_hold": 0.01,
        "has_buyback": False, "ind_tl_3y_avg": 0.42,
        "payout_lyr_series": [{"year": y, "value": 0.5}
                              for y in range(2025, 2020, -1)],
        "bonus_series": [{"year": y, "value": 5e8}
                         for y in range(2025, 2020, -1)],
        "yield_series": [{"year": y, "value": 0.04}
                         for y in range(2025, 2020, -1)],
    }
    data.update(overrides)
    return data


@pytest.fixture(autouse=True)
def fake_runtime(monkeypatch):
    fetcher = FakeFetcher(
        yields={"600000": 0.04, "601398": 0.05, "hk.00700": 0.0137},
        payouts={"600000": 0.5, "601398": 0.31, "hk.00700": 0.205},
        quality={
            "600000": quality_payload(),
            "601398": quality_payload(org_type=2, tl_rate=0.92, fcf_ttm=None),
        },
        history={
            "600000": [{"props": {"分红": 0.5, "财报时间": f"{y}-12-31",
                                  "状态": "实施", "分红类型": "年度"}}
                       for y in range(2025, 2015, -1)],
        },
        synthetic=False,
    )
    monkeypatch.setattr(srv.RUNTIME, "_fetcher", fetcher)


def test_quality_mixed_portfolio():
    data = srv.run_dividend_quality({
        "positions": [
            {"code": "600000", "market": "cn", "shares": 1000},
            {"code": "601398", "market": "cn", "shares": 1000},
            {"code": "hk.00700", "market": "hk", "shares": 1000},
        ],
    })
    by_code = {r["code"]: r for r in data["rows"]}
    assert by_code["600000"]["eligible"] is True
    assert by_code["600000"]["ability_score"] is not None
    assert by_code["601398"]["eligible"] is False
    assert "银行" in by_code["601398"]["reason"]
    assert by_code["hk.00700"]["eligible"] is False
    assert "港股" in by_code["hk.00700"]["reason"]

    summary = data["summary"]
    assert summary["eligible_count"] == 1
    assert summary["skipped"] == ["601398", "hk.00700"]
    assert summary["eligible_count"] + len(summary["skipped"]) == 3


def test_quality_per_symbol_failure_isolated(monkeypatch):
    def boom(code):
        if code == "600001":
            raise RuntimeError("eval failed")
        return quality_payload()

    fetcher = srv.RUNTIME.fetcher()
    monkeypatch.setattr(fetcher, "quality_metrics", boom)
    data = srv.run_dividend_quality({
        "positions": [
            {"code": "600000", "market": "cn", "shares": 1000},
            {"code": "600001", "market": "cn", "shares": 1000},
        ],
    })
    by_code = {r["code"]: r for r in data["rows"]}
    assert by_code["600000"]["eligible"] is True
    assert by_code["600001"]["eligible"] is False
    assert "质量指标未取到" in by_code["600001"]["reason"]


def test_quality_requires_positions():
    with pytest.raises(srv.ToolError):
        srv.run_dividend_quality({"positions": []})


def test_quality_series_flow_into_row():
    data = srv.run_dividend_quality({
        "positions": [{"code": "600000", "market": "cn", "shares": 1000}],
    })
    row = data["rows"][0]
    assert row["recurring_by_year"], "年度经常性分红应从历史行归集"
    assert row["consecutive_years"] == 10
    assert row["payout_3y_avg"] == pytest.approx(0.5)
