"""取数层双市场路由测试：不需要 finpipe、不联网。

核心断言：港股必须走 market="hk" 的 client + 5 位裸码；A 股走默认 client。
这是线上"港股只有价格、没有分红/EPS"的根因，不能回归。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from bigwinner.common.fetchers import (
    FakeFetcher,
    FinpipeFetcher,
    _market,
    _query_code,
    positions_from_payload,
    sdk_symbol,
)
from bigwinner.shouxi.tools.dividend_xray import Position


class FakeIndicator:
    def __init__(self, market: str, calls: list) -> None:
        self.market = market
        self.calls = calls

    def get(self, code: str, metric_code: str):
        self.calls.append((self.market, "indicator.get", code, metric_code))
        if metric_code == "$CR_HKD_LAST":
            return 0.8501
        return {"$DPS_TTM_LAST_REAL": 5.3, "$EPS_NPTS_TTM_LAST": 25.902}.get(
            metric_code, 1.0)

    def metrics(self, code: str, metric_codes: list[str]):
        self.calls.append((self.market, "indicator.metrics", code, tuple(metric_codes)))
        return {c: self.get(code, c) for c in metric_codes}


class FakeDividend:
    def __init__(self, market: str, calls: list) -> None:
        self.market = market
        self.calls = calls

    def history(self, code: str, limit: int = 20):
        self.calls.append((self.market, "dividend.history", code, limit))
        return [{"sas": "2025:Q4", "ex_date": "2026-05-20", "dps": 5.3, "ccy": "HKD"}]


class FakeClient:
    def __init__(self, market: str, calls: list) -> None:
        self.market = market
        self.calls = calls
        self.indicator = FakeIndicator(market, calls)
        self.dividend = FakeDividend(market, calls)

    def call(self, name: str, **kw):
        self.calls.append((self.market, name, kw))
        if name == "kline.query_bars":
            return [{"close": 382.4 if self.market == "hk" else 10.0}]
        return None

    def call_batch(self, name: str, syms: list[str], on_error: str = "raise",
                   **kwargs):
        self.calls.append((self.market, "call_batch", name, tuple(syms), on_error))
        if name == "bonus.query_list":
            return SimpleNamespace(results={
                (f"HK.{s}" if self.market == "hk" else s): [{
                    "props": {
                        "分红": 5.3 if self.market == "hk" else 0.9,
                        "除权除息日": "2026-11-20",
                        "分红到账日": "2026-12-05",
                        "股权登记日": "2026-11-19",
                        "状态": "预案",
                        "分红类型": "中期",
                        "货币": "HKD" if self.market == "hk" else "人民币",
                    }
                }]
                for s in syms
            })
        # 故意回带 HK. 前缀，验证回包 key 能映射回入参 hk.00700
        return SimpleNamespace(results={
            f"HK.{s}" if self.market == "hk" else s:
                (0.01373 if name.endswith("yield_ttm") else 0.2052)
            for s in syms
        })

    def eval_result(self, xs: str, **kw):
        self.calls.append((self.market, "eval_result", kw))
        return [{
            "values": {
                "$SYMBOL": "600519" if self.market == "cn" else "00700",
                "$NAME": "测试标的",
                "$BONUS_RATE_TTM_LAST": 0.05,
            }
        }]


def test_market_and_query_code_normalization():
    assert _market("600519") == "cn"
    assert _market("hk.00700") == "hk"
    assert _market("HK.00700") == "hk"
    assert _market("00700") == "hk"
    assert _market("700") == "hk"
    assert _market("us.ADBE") == "us"
    assert _query_code("600519") == "600519"
    assert _query_code("sh.600519.SH") == "600519"
    assert _query_code("hk.00700") == "00700"
    assert _query_code("700") == "00700"
    assert _query_code("us.ADBE") == "ADBE"


def test_finpipe_fetcher_routes_hk_and_cn_to_separate_clients():
    calls: list = []
    cn = FakeClient("cn", calls)
    hk = FakeClient("hk", calls)
    fetcher = FinpipeFetcher(client=cn, hk_client=hk)

    prices = fetcher.prices(["600519", "hk.00700"])
    assert prices == {"600519": 10.0, "hk.00700": 382.4}
    # HK 必须用裸 5 位 + _raw=True；CN 不能带 _raw
    hk_price = [c for c in calls if c[1] == "kline.query_bars" and c[0] == "hk"][0]
    assert hk_price[2]["sym"] == "00700"
    assert hk_price[2]["_raw"] is True
    cn_price = [c for c in calls if c[1] == "kline.query_bars" and c[0] == "cn"][0]
    assert cn_price[2]["sym"] == "600519"
    assert "_raw" not in cn_price[2]

    snap = fetcher.dividend_snapshot(["600519", "hk.00700"])
    assert snap["hk.00700"]["yield_ttm"] == pytest.approx(0.01373)
    assert snap["hk.00700"]["payout_ttm"] == pytest.approx(0.2052)
    assert snap["600519"]["yield_ttm"] == pytest.approx(0.01373)

    assert fetcher.metric("hk.00700", "$DPS_TTM_LAST_REAL") == pytest.approx(5.3)
    assert fetcher.metrics("hk.00700", ["$DPS_TTM_LAST_REAL", "$EPS_NPTS_TTM_LAST"])[
        "$EPS_NPTS_TTM_LAST"] == pytest.approx(25.902)

    rows = fetcher.dividend_rows("hk.00700", limit=10)
    assert rows[0]["dps"] == pytest.approx(5.3)
    assert rows[0]["sas"] == "2025:Q4"

    assert fetcher.fx_to_cny("HKD") == pytest.approx(0.8501)
    assert fetcher.fx_to_cny("CNY") == 1.0


def test_snapshot_response_key_with_dotted_prefix_still_maps():
    calls: list = []
    fetcher = FinpipeFetcher(client=FakeClient("cn", calls),
                             hk_client=FakeClient("hk", calls))
    snap = fetcher.dividend_snapshot(["hk.00700"])
    assert "yield_ttm" in snap["hk.00700"]


def test_positions_from_payload_normalizes_hk_and_keeps_tax_fields():
    positions = positions_from_payload([
        {"code": "700", "market": "hk", "shares": "1000", "cost": "400",
         "buy_date": "2024-01-01", "tax_rate": "20"},
        {"code": "600519", "market": "cn", "shares": 100},
    ])
    assert positions[0].normalized_code() == "hk.00700"
    assert positions[0].market == "hk"
    assert positions[0].buy_date == "2024-01-01"
    assert positions[0].tax_rate == pytest.approx(0.20)
    assert positions[0].cost == pytest.approx(400.0)
    assert positions[1].normalized_code() == "600519"
    assert positions[1].market == "cn"


def test_position_infers_hk_from_bare_five_digit_code():
    pos = Position(code="00700", shares=100)
    assert pos.inferred_market() == "hk"
    assert pos.normalized_code() == "hk.00700"
    assert sdk_symbol({"code": "700", "market": "hk"}) == "hk.00700"


def test_fake_fetcher_supports_metrics_and_fx():
    fetcher = FakeFetcher(prices={"hk.00700": 382.4},
                          dps={"hk.00700": 5.3},
                          eps={"hk.00700": 25.9},
                          fx={"HKD": 0.8})
    assert fetcher.metrics("hk.00700", ["$DPS_TTM_LAST_REAL", "$EPS_NPTS_TTM_LAST"]) == {
        "$DPS_TTM_LAST_REAL": 5.3,
        "$EPS_NPTS_TTM_LAST": 25.9,
    }
    assert fetcher.fx_to_cny("HKD") == pytest.approx(0.8)
    assert fetcher.fx_to_cny("CNY") == 1.0


def test_dividend_rows_many_keeps_raw_status_and_maps_keys():
    calls: list = []
    fetcher = FinpipeFetcher(client=FakeClient("cn", calls),
                             hk_client=FakeClient("hk", calls))
    rows = fetcher.dividend_rows_many(["600519", "hk.00700"], limit=10)
    assert rows["600519"][0]["props"]["状态"] == "预案"
    assert rows["hk.00700"][0]["props"]["货币"] == "HKD"
    batch_calls = [c for c in calls if c[1] == "call_batch"
                   and c[2] == "bonus.query_list"]
    assert len(batch_calls) == 2  # CN/HK 各一次


def test_high_yield_symbols_uses_index_query():
    calls: list = []
    fetcher = FinpipeFetcher(client=FakeClient("cn", calls),
                             hk_client=FakeClient("hk", calls))
    pool = fetcher.high_yield_symbols("cn", limit=50)
    assert pool == [{
        "code": "600519",
        "market": "cn",
        "name": "测试标的",
        "yield_ttm": 0.05,
    }]
    assert any(c[1] == "eval_result" for c in calls)
