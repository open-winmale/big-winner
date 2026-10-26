"""筛选工具单测：阈值边界、本地数字计算、连续年数口径、缺失显式。

全部离线：FakeScreenerSource / 桩 client，不触网。
"""
from __future__ import annotations

from datetime import date

import pytest

from bigwinner.shouxi.tools import screener as scr


# ---------------------------------------------------------------- 注册表


def test_default_conditions_are_dividend_three():
    assert scr.DEFAULT_CONDITIONS == ["yield_ge3", "payout_30_70", "div_years_ge3"]


def test_validate_conditions_default_and_dedup():
    assert scr.validate_conditions(None) == scr.DEFAULT_CONDITIONS
    assert scr.validate_conditions([]) == scr.DEFAULT_CONDITIONS
    assert scr.validate_conditions(["payout_30_70", "yield_ge3", "payout_30_70"]) == \
        ["payout_30_70", "yield_ge3"]


def test_validate_conditions_unknown_rejected():
    with pytest.raises(ValueError, match="未知条件"):
        scr.validate_conditions(["no_such_condition"])


def test_conditions_public_has_no_callable():
    for item in scr.conditions_public():
        assert set(item) == {"id", "name", "intro", "group", "column", "default"}


# ---------------------------------------------------------------- 阈值边界


def test_threshold_boundaries():
    m = {"yield_ttm": 0.03, "payout_ttm": 0.7, "div_years": 3,
         "dist_ma20": 0.0, "chg20d": 0.10, "stable": True}
    checks = {c.id: c.check(m) for c in scr.CONDITIONS}
    # 边界全部按「含端点」口径：≥3%、≤70%、≥3 年、≤10% 成立；贴在 MA20 上（dist=0）不算站上
    assert checks["yield_ge3"] is True
    assert checks["payout_30_70"] is True
    assert checks["div_years_ge3"] is True
    assert checks["chg20_le10"] is True
    assert checks["above_ma20"] is False
    assert checks["stable_yield"] is True


def test_threshold_out_of_range():
    m = {"yield_ttm": 0.029, "payout_ttm": 1.0, "div_years": 2,
         "dist_ma20": 0.01, "chg20d": 0.11, "stable": False}
    checks = {c.id: c.check(m) for c in scr.CONDITIONS}
    assert checks["yield_ge3"] is False
    assert checks["payout_30_70"] is False      # 100% 也超出 70% 上限（危险由前端标红）
    assert checks["div_years_ge3"] is False
    assert checks["chg20_le10"] is False
    assert checks["above_ma20"] is True
    assert checks["stable_yield"] is False


def test_missing_metric_is_none_not_false():
    checks = {c.id: c.check({}) for c in scr.CONDITIONS}
    assert all(v is None for v in checks.values())


# ---------------------------------------------------------------- 本地数字


def _linear_bars(n: int, step: float = 1.0) -> list[dict]:
    return [{"date": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}",
             "close": 100 + i * step} for i in range(n)]


def test_bars_metrics_full_window():
    m = scr.bars_metrics(_linear_bars(65))
    assert m["close"] == 164.0
    assert m["ma20"] == pytest.approx(sum(range(145, 165)) / 20)
    assert m["dist_ma20"] == pytest.approx(164 / 154.5 - 1)
    assert m["ma60_up"] is True          # 线性上升：今 MA60 > 昨 MA60
    assert m["chg20d"] == pytest.approx(164 / 144 - 1)


def test_bars_metrics_short_windows_degrade_to_none():
    few = scr.bars_metrics(_linear_bars(15))
    assert few["close"] == 114.0
    assert few["ma20"] is None and few["ma60_up"] is None and few["chg20d"] is None

    mid = scr.bars_metrics(_linear_bars(30))
    assert mid["ma20"] is not None
    assert mid["chg20d"] == pytest.approx(129 / 109 - 1)
    assert mid["ma60_up"] is None        # 61 根才够算今昨两个 MA60

    assert scr.bars_metrics([])["close"] is None


def test_recent_consecutive_years_streak():
    today = date(2026, 10, 26)
    rows = [{"sas": f"{y}-06-30"} for y in (2026, 2025, 2024)]
    assert scr.recent_consecutive_years(rows, today) == 3
    # 断一年就断：2026、2025、2023 → 连续只有 2
    rows_gap = [{"sas": f"{y}-06-30"} for y in (2026, 2025, 2023)]
    assert scr.recent_consecutive_years(rows_gap, today) == 2


def test_recent_consecutive_years_stale_means_zero():
    """「连续」必须是还在连续：最新报告期早于前年 = 已断供，按 0。"""
    today = date(2026, 10, 26)
    stale = [{"sas": f"{y}-06-30"} for y in (2022, 2021, 2020)]
    assert scr.recent_consecutive_years(stale, today) == 0
    # 年报分红滞后一年是常态：最新报告期 = 前年（2024）仍算在续
    lagging = [{"sas": f"{y}-06-30"} for y in (2024, 2023, 2022)]
    assert scr.recent_consecutive_years(lagging, today) == 3
    assert scr.recent_consecutive_years([], today) == 0


# ---------------------------------------------------------------- 单票判定


def test_evaluate_pass_with_fake_source():
    out = scr.evaluate_stock(scr.FakeScreenerSource(), "600519",
                             scr.DEFAULT_CONDITIONS)
    assert out["passed"] is True
    assert out["failed"] == []
    assert out["errors"] is None
    assert out["name"] == "贵州茅台"
    assert out["metrics"]["yield_ttm"] == pytest.approx(0.034)
    assert out["metrics"]["div_years"] >= 3


def test_evaluate_failed_carries_breakpoint():
    out = scr.evaluate_stock(scr.FakeScreenerSource(), "000858",
                             scr.DEFAULT_CONDITIONS)
    assert out["passed"] is False
    ids = [f["id"] for f in out["failed"]]
    assert ids == ["payout_30_70"]
    assert out["failed"][0]["column"] == "payout_ttm"
    assert out["failed"][0]["value"] == pytest.approx(0.85)


def test_evaluate_no_dividend_history_is_zero_not_none():
    """真取到空分红表 = 事实上的 0 年（未通过）；与取数失败（数据不足）不同。"""

    class BareSource(scr.FakeScreenerSource):
        def snapshot(self, symbol):
            return {"name": "无分红", "yield_ttm": 0.04, "payout_ttm": 0.5}

        def dividend_rows(self, symbol, limit=10):
            return []

    out = scr.evaluate_stock(BareSource(), "600000", scr.DEFAULT_CONDITIONS)
    assert out["metrics"]["div_years"] == 0
    assert out["passed"] is False


def test_evaluate_fetch_failure_is_insufficient_not_failed():
    """取数异常 → 对应条件数据不足（passed=None），绝不冒充不通过。"""

    class BrokenSource(scr.FakeScreenerSource):
        def snapshot(self, symbol):
            raise RuntimeError("boom")

    out = scr.evaluate_stock(BrokenSource(), "600000", scr.DEFAULT_CONDITIONS)
    assert out["passed"] is None
    assert out["failed"] == []
    assert "snapshot" in (out["errors"] or {})
    assert out["metrics"]["yield_ttm"] is None


def test_evaluate_stable_only_fetched_when_enabled():
    calls = {"stable": 0}

    class CountingSource(scr.FakeScreenerSource):
        def stable_yield(self, symbol):
            calls["stable"] += 1
            return True

    src = CountingSource()
    scr.evaluate_stock(src, "600519", scr.DEFAULT_CONDITIONS)
    assert calls["stable"] == 0                # 未勾选不取数（省额度）
    scr.evaluate_stock(src, "600519",
                       scr.DEFAULT_CONDITIONS + ["stable_yield"])
    assert calls["stable"] == 1


# ---------------------------------------------------------------- 数据源


def test_fake_source_deterministic():
    a = scr.FakeScreenerSource().bars("600000")
    b = scr.FakeScreenerSource().bars("600000")
    assert [x["close"] for x in a] == [x["close"] for x in b]
    assert len(a) >= scr.BARS_N


def test_finpipe_source_with_stub_client():
    """桩 client 验证真实源的调用形状：qfq 日 K 升序、sas 归一、稳定转布尔。"""

    class StubDividend:
        def history(self, sym, limit=50):
            return [{"ex_date": "2025-06-30"}, {"ex_date": "2024-06-30"},
                    {"ex_date": "2023-06-30"}]

        def screen_stable_yield(self, sym):
            return 1

    class StubCli:
        dividend = StubDividend()

        def eval_result(self, xs, symbol):
            assert "$BONUS_RATE_TTM_LAST" in xs
            return {"name": "桩票", "yield_ttm": "0.04", "payout_ttm": 0.5}

        def call(self, fn, **kw):
            assert fn == "kline.query_bars_adj" and kw["adj"] == "qfq"
            rows = [{"date": f"2026-01-{d:02d}", "close": 10.0 + d}
                    for d in range(1, 66)]
            return list(reversed(rows))       # store 新在前，源内须排升序

    src = scr.FinpipeScreenerSource(client=StubCli())
    assert src.snapshot("600000")["yield_ttm"] == "0.04"
    bars = src.bars("600000")
    assert bars[0]["date"] < bars[-1]["date"]
    rows = src.dividend_rows("600000")
    assert all(r["sas"] for r in rows)
    assert src.stable_yield("600000") is True

    out = scr.evaluate_stock(src, "600000",
                             ["yield_ge3", "payout_30_70", "div_years_ge3"])
    assert out["name"] == "桩票"
    assert out["metrics"]["div_years"] == 3
    assert out["passed"] is True
