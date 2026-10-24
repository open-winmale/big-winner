"""T1 持仓收息透视表 —— 离线单测（不需要 finpipe、不联网）。

覆盖的是最容易出错、也最容易被内行看穿的地方：加权口径、缺失处理、降级标注。
"""
from __future__ import annotations

import pytest

from bigwinner.fetchers import FakeFetcher
from bigwinner.tools.dividend_xray import Position, analyze, consecutive_years


def make_fetcher() -> FakeFetcher:
    """两只票：A 大市值低股息，B 小市值高股息 —— 专测加权 vs 算术平均。"""
    return FakeFetcher(
        prices={"600000": 10.0, "600001": 100.0},
        yields={"600000": 0.05, "600001": 0.02},
        payouts={"600000": 0.60, "600001": 1.20},
        dps={"600000": 0.5, "600001": 2.0},
        eps={"600000": 1.0, "600001": 5.0},
        history={
            "600000": [{"sas": f"{y}-06-30"} for y in range(2025, 2019, -1)],
            "600001": [{"sas": "2025-06-30"}, {"sas": "2022-06-30"}],
        },
    )


# ---------------------------------------------------------------- 连续年数


def test_consecutive_years_normal_and_broken():
    assert consecutive_years([{"sas": "2025-06-30"}, {"sas": "2024-06-30"}]) == 2
    assert consecutive_years([{"sas": "2025-06-30"}, {"sas": "2022-06-30"}]) == 1
    assert consecutive_years([]) == 0
    assert consecutive_years([{"sas": None}]) == 0


def test_consecutive_years_dedup_same_year():
    """同一年两次分红（中期+年度）只算一年。"""
    rows = [{"sas": "2025-12-31"}, {"sas": "2025-06-30"}, {"sas": "2024-06-30"}]
    assert consecutive_years(rows) == 2


# ---------------------------------------------------------------- 加权口径


def test_portfolio_yield_is_value_weighted_not_arithmetic():
    """核心：组合股息率必须是市值加权。

    A：10000 股 × 10 元 = 10 万，年息 5000 元
    B：1000 股 × 100 元 = 10 万，年息 2000 元
    市值各半 → 组合股息率 = 7000 / 200000 = 3.5%
    算术平均会错算成 (5%+2%)/2 = 3.5% … 这里刻意让权重不等再验一次。
    """
    fetcher = make_fetcher()
    # A 买 20000 股（市值 20 万），B 买 1000 股（市值 10 万）→ 权重 2:1
    positions = [Position(code="600000", shares=20000), Position(code="600001", shares=1000)]
    result = analyze(positions, fetcher)

    # 加权：(20000*0.5 + 1000*2.0) / (20000*10 + 1000*100) = 12000 / 300000 = 4.0%
    assert result.portfolio_yield == pytest.approx(0.04, abs=1e-9)
    # 算术平均是 (5% + 2%) / 2 = 3.5% —— 必须不同，否则说明写错了
    assert result.portfolio_yield != pytest.approx(0.035, abs=1e-9)
    assert result.total_dividend == pytest.approx(12000.0)
    assert result.total_market_value == pytest.approx(300000.0)


def test_weights_sum_to_one():
    result = analyze([Position(code="600000", shares=1000),
                      Position(code="600001", shares=1000)], make_fetcher())
    total = sum(r.weight for r in result.rows if r.weight is not None)
    assert total == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------- 缺失与降级


def test_missing_price_falls_back_to_cost_and_is_flagged():
    """现价取不到时用成本估算，但必须显式标注，不能假装是真实价。"""
    fetcher = FakeFetcher(
        prices={"600000": None}, yields={"600000": 0.05}, payouts={"600000": 0.6},
        dps={"600000": 0.5}, eps={"600000": 1.0},
    )
    result = analyze([Position(code="600000", shares=1000, cost=9.0)], fetcher)
    row = result.rows[0]
    assert row.price == 9.0
    assert row.price_estimated is True
    assert "现价(用成本估算)" in row.missing
    assert result.completeness == "0/1"


def test_missing_metric_does_not_poison_totals():
    """缺少每股股息的票，不能被当成 0 拉低组合股息率的分母口径。"""
    fetcher = FakeFetcher(
        prices={"600000": 10.0, "600001": 100.0},
        yields={"600000": 0.05}, payouts={"600000": 0.6},
        dps={"600000": 0.5},          # 600001 的 dps 缺失
        eps={"600000": 1.0, "600001": 5.0},
    )
    result = analyze([Position(code="600000", shares=1000),
                      Position(code="600001", shares=1000)], fetcher)
    missing_row = next(r for r in result.rows if r.code == "600001")
    assert missing_row.dps_ttm is None
    assert missing_row.annual_dividend is None
    assert "每股股息" in missing_row.missing
    # 总股息只算有数据的那只
    assert result.total_dividend == pytest.approx(500.0)


def test_empty_positions_is_explicit():
    result = analyze([], make_fetcher())
    assert result.completeness == "0/0"
    assert result.notes and "没有输入" in result.notes[0]


# ---------------------------------------------------------------- 稳定性看板


def test_stability_cr3_and_warnings():
    fetcher = make_fetcher()
    # A 派息远高于 B，CR3 无意义（只有 2 只），但超额派息预警应命中 600001
    result = analyze([Position(code="600000", shares=1000),
                      Position(code="600001", shares=1000)], fetcher, deep=True)
    assert result.stability.cr3 is not None
    assert result.stability.cr3 == pytest.approx(1.0)  # 只有两只，前 3 大即全部
    joined = " ".join(result.stability.warnings)
    assert "100%" in joined            # 派息率超 100% 的预警
    # 只有 2 只有派息数据 → CR3 恒为 1.0，不应产出集中度预警（只给中性说明）
    assert "CR3=" not in joined
    assert "参考意义有限" in joined
    assert result.stability.payout_buckets.get("超额(>100%)") == 1
    assert result.stability.payout_buckets.get("健康(30%-70%)") == 1


def test_payout_bucket_splits_high_but_not_over():
    """70%-100% 单独成档，不能混进"其他"。"""
    fetcher = FakeFetcher(
        prices={"600000": 10.0, "600001": 10.0, "600002": 10.0},
        payouts={"600000": 0.85, "600001": 0.50, "600002": 0.10},
        dps={"600000": 0.5, "600001": 0.5, "600002": 0.5},
        eps={"600000": 1.0, "600001": 1.0, "600002": 1.0},
    )
    result = analyze([Position(code=c, shares=1000)
                      for c in ("600000", "600001", "600002")], fetcher)
    assert result.stability.payout_buckets == {
        "偏高(70%-100%)": 1, "健康(30%-70%)": 1, "保守(<20%)": 1,
    }


def test_completeness_counts_only_core_fields():
    """深度字段（如股息率分位）缺失不该把核心数据判成不完整。"""
    fetcher = make_fetcher()   # 没有 pct10y → 深度模式下分位必然缺失
    positions = [Position(code="600000", shares=1000)]
    deep = analyze(positions, fetcher, deep=True)
    assert deep.rows[0].yield_pct_10y is None
    assert "股息率分位" in deep.rows[0].missing       # 仍然展示给用户
    assert deep.completeness == "1/1"                 # 但不拉低核心完整度


def test_cr3_warning_appears_with_enough_positions():
    """≥4 只票时 CR3 才有意义。"""
    fetcher = FakeFetcher(
        prices={f"60000{i}": 10.0 for i in range(5)},
        dps={"600000": 5.0, "600001": 0.1, "600002": 0.1, "600003": 0.1, "600004": 0.1},
        eps={f"60000{i}": 1.0 for i in range(5)},
    )
    result = analyze([Position(code=f"60000{i}", shares=1000) for i in range(5)], fetcher)
    joined = " ".join(result.stability.warnings)
    assert "集中度" in joined
    assert result.stability.cr3 > 0.9


def test_stable_years_cover_only_in_deep_mode():
    fetcher = make_fetcher()
    positions = [Position(code="600000", shares=1000), Position(code="600001", shares=1000)]
    assert analyze(positions, fetcher, deep=True).stability.stable_years_cover is not None
    assert analyze(positions, fetcher, deep=False).stability.stable_years_cover is None


def test_consecutive_years_value_in_deep_mode():
    result = analyze([Position(code="600000", shares=1000),
                      Position(code="600001", shares=1000)], make_fetcher(), deep=True)
    by_code = {r.code: r.consecutive_years for r in result.rows}
    assert by_code["600000"] == 6
    assert by_code["600001"] == 1


# ---------------------------------------------------------------- 浮盈


def test_pnl_and_ratio():
    result = analyze([Position(code="600000", shares=1000, cost=8.0)], make_fetcher())
    row = result.rows[0]
    assert row.pnl == pytest.approx(2000.0)
    assert row.pnl_ratio == pytest.approx(0.25)
    assert result.portfolio_pnl == pytest.approx(2000.0)


# ---------------------------------------------------------------- 港股与币种


def test_hk_row_uses_hkd_native_and_cny_totals():
    """港股：价格/股息/成本是 HKD，组合合计折 CNY；EPS 是财报币种 CNY。"""
    fetcher = FakeFetcher(
        prices={"hk.00700": 382.40},
        yields={"hk.00700": 0.01373},
        payouts={"hk.00700": 0.2052},
        dps={"hk.00700": 5.30},
        eps={"hk.00700": 25.902},
        fx={"HKD": 0.85},
    )
    result = analyze([Position(code="hk.00700", shares=1000, cost=400.0,
                               market="hk")], fetcher)
    row = result.rows[0]
    assert row.market == "hk"
    assert row.currency == "HKD"
    assert row.fin_currency == "CNY"
    assert row.fx_to_cny == pytest.approx(0.85)
    assert row.market_value == pytest.approx(382400.0)
    assert row.market_value_cny == pytest.approx(325040.0)
    assert row.annual_dividend == pytest.approx(5300.0)
    assert row.annual_dividend_cny == pytest.approx(4505.0)
    assert row.cost_yield == pytest.approx(5.3 / 400)
    assert row.total_profit == pytest.approx(25902.0)
    assert result.total_market_value == pytest.approx(325040.0)
    assert result.total_dividend == pytest.approx(4505.0)
    assert result.portfolio_yield == pytest.approx(4505.0 / 325040.0)
    assert result.portfolio_cost_yield == pytest.approx(4505.0 / (400 * 1000 * 0.85))
    assert result.fx_note and "HKD→CNY" in result.fx_note


def test_hk_missing_fx_does_not_poison_totals():
    fetcher = FakeFetcher(
        prices={"hk.00700": 382.40},
        yields={"hk.00700": 0.01373},
        dps={"hk.00700": 5.30},
        eps={"hk.00700": 25.902},
        fx={"HKD": None},
    )
    result = analyze([Position(code="hk.00700", shares=1000, market="hk")], fetcher)
    row = result.rows[0]
    assert row.fx_to_cny is None
    assert row.market_value == pytest.approx(382400.0)
    assert row.market_value_cny is None
    assert row.annual_dividend_cny is None
    assert result.total_market_value is None
    assert result.portfolio_yield is None
    assert any("HKD→CNY" in n for n in result.notes)
    assert "汇率" in row.missing


def test_missing_price_does_not_inflate_portfolio_yield():
    """有股息的票缺价时，不能只进分子、不进分母。"""
    fetcher = FakeFetcher(
        prices={"600000": 10.0},
        dps={"600000": 0.5, "600001": 2.0},
        eps={"600000": 1.0, "600001": 5.0},
    )
    result = analyze([Position(code="600000", shares=1000),
                      Position(code="600001", shares=1000)], fetcher)
    # 只有 600000 同时有价与股息 → 500 / 10000 = 5%
    assert result.portfolio_yield == pytest.approx(0.05)


def test_missing_cost_does_not_inflate_cost_yield():
    """缺成本的票不能只贡献股息、不贡献成本。"""
    result = analyze(
        [Position(code="600000", shares=1000, cost=10.0),
         Position(code="600001", shares=1000)],
        make_fetcher(),
    )
    # 600000：股息 500、成本 10000 → 5%；600001 缺成本，不参与
    assert result.portfolio_cost_yield == pytest.approx(0.05)
    assert result.portfolio_pnl == pytest.approx(0.0)
