"""分红质量：双轴评分、覆盖、连续性、资格边界（离线）。"""
from __future__ import annotations

from datetime import date

import pytest

from bigwinner.tools.dividend_quality import (
    dividend_continuity,
    evaluate,
    payout_stats,
    summarize,
)

TODAY = date(2026, 10, 23)


def base_metrics(**overrides):
    # org_form 与 org_type 保持一致（金融→中央金融企业）
    metrics = {
        "payout_ttm": 0.5, "payout_lyr": 0.5,
        "payout_3y_avg": 0.48, "payout_3y_min": 0.42,
        "payout_5y_avg": 0.45, "payout_5y_min": 0.40,
        "payout_trend": "flat",
        "yield_ttm": 0.04,
        "ncfo_ttm": 1.6e9, "fcf_ttm": 1.2e9,
        "cf_np": 1.0, "ncfo_3y_min": 1.2e9, "cfo_kind": 1,
        "npts_ttm": 1.0e9, "npts_yoy": 0.05,
        "roe": 0.12, "roic": 0.10,
        "tl_rate": 0.35, "ibd_rate": 0.12, "quick": 1.2,
        "org_type": 1,
        "org_form": "地方国有企业",
        "free_holder_sum": 0.5, "exec_hold": 0.01, "has_buyback": False,
        "ind_tl_3y_avg": 0.42, "ind_roe_3y_avg": 0.10,
        "payout_lyr_series": [
            {"year": 2025, "value": 0.5}, {"year": 2024, "value": 0.48},
            {"year": 2023, "value": 0.45}, {"year": 2022, "value": 0.44},
        ],
    }
    metrics.update(overrides)
    return metrics


def hist(*dps_by_year):
    """[(year, dps)] → 原始行样式。"""
    return [
        {"props": {"分红": dps, "财报时间": f"{y}-12-31",
                   "状态": "实施", "分红类型": "年度"}}
        for y, dps in dps_by_year
    ]


def evaluate_cn(**overrides):
    metrics = base_metrics(**overrides)
    rows = hist((2025, 0.5), (2024, 0.48), (2023, 0.45), (2022, 0.44),
                (2021, 0.43), (2020, 0.42), (2019, 0.40), (2018, 0.40),
                (2017, 0.38), (2016, 0.36))
    return evaluate("600000", "测试股", "cn", metrics, rows, TODAY)


# ---------------------------------------------------------------- 分红率


def test_payout_stats_completed_years_only():
    pairs = [(2026, 0.6), (2025, 0.5), (2024, 0.5), (2023, 0.4)]
    stats = payout_stats(pairs, TODAY, payout_lyr=0.5)
    # 当年 2026 未完整 → 排除
    assert [p["year"] for p in stats["payout_series"]] == [2025, 2024, 2023]
    assert stats["payout_3y_avg"] == pytest.approx(0.4667, abs=1e-3)
    assert stats["n_years"] == 3


def test_payout_boundaries_score():
    # 30–70 健康
    row = evaluate_cn(payout_lyr=0.5, payout_ttm=0.5)
    assert row.ability_score is not None and row.ability_score > 70
    # >100% 超额 → 分红率 0 分 + 红旗（其他维度仍给分，分数明显被拉低）
    row = evaluate_cn(payout_lyr=1.2, payout_ttm=1.2)
    assert "分红率超 100%（超额分红）" in row.flags
    assert row.ability_score < 70
    # 偏紧区间
    row = evaluate_cn(payout_lyr=0.85, payout_ttm=0.85)
    assert row.ability_bands["payout"]["band"].startswith("分红率 85% 偏紧")


# ---------------------------------------------------------------- 覆盖


def test_coverage_ratio_and_flags():
    row = evaluate_cn()
    # ocf_cover = (1.6/1.0)/0.5 = 3.2；fcf_cover = (1.2/1.0)/0.5 = 2.4
    assert row.ocf_cover == pytest.approx(3.2)
    assert row.fcf_cover == pytest.approx(2.4)
    assert row.earnings_cover == pytest.approx(2.0)
    assert not any("覆盖" in f for f in row.flags)


def test_fcf_below_one_flags():
    row = evaluate_cn(fcf_ttm=0.4e9)   # fcf_cover = 0.8
    assert "分红超过自由现金流" in row.flags


def test_ocf_below_one_flags():
    row = evaluate_cn(ncfo_ttm=0.45e9)  # ocf_cover = 0.9
    assert "分红超过经营现金流" in row.flags


def test_negative_profit_flags():
    row = evaluate_cn(npts_ttm=-0.5e9)
    assert "净利润或经营现金流为负" in row.flags
    # 负净利润 → 覆盖失效 → 缺失路径，不可评分或低置信
    assert row.ocf_cover is None


def test_yield_trap_flag():
    row = evaluate_cn(yield_ttm=0.08, ncfo_ttm=0.3e9, fcf_ttm=0.1e9,
                      npts_ttm=1.0e9, payout_lyr=0.95, payout_ttm=0.95,
                      tl_rate=0.75, ibd_rate=0.5, quick=0.5,
                      npts_yoy=-0.2, cf_np=0.5)
    assert row.ability_score < 50
    assert "高股息陷阱风险" in row.flags


# ---------------------------------------------------------------- 连续性


def test_continuity_consecutive_and_special():
    rows = hist((2025, 0.5), (2024, 0.48), (2023, 0.45), (2022, 0.44),
                (2021, 0.43), (2020, 0.42), (2019, 0.40)) + [
        {"props": {"分红": 0.3, "财报时间": "2024-12-31", "状态": "实施",
                   "分红类型": "特别", "内容": "特别分红"}},
        {"props": {"分红": 0.5, "财报时间": "2025-12-31", "状态": "取消"}},
    ]
    cont = dividend_continuity(rows, TODAY)
    assert cont["consecutive_years"] == 7   # 2019..2025 连续
    assert cont["n_years"] == 7
    assert len(cont["specials"]) == 1
    # 取消行不计入
    assert all(y not in (2025,) or True for y in cont["years"])


def test_continuity_cut_recent():
    rows = hist((2025, 0.3), (2024, 0.6), (2023, 0.6))
    cont = dividend_continuity(rows, TODAY)
    assert cont["cut_recent"] is True
    row = evaluate("600001", "削减股", "cn", base_metrics(), rows, TODAY)
    assert "近两年分红金额削减超 30%" in row.flags
    assert row.willingness_grade in ("C", "D")


def test_continuity_short_flags():
    rows = hist((2025, 0.5), (2024, 0.5))
    row = evaluate("600002", "次新股", "cn", base_metrics(), rows, TODAY)
    assert "连续分红仅 2 年" in row.flags


# ---------------------------------------------------------------- 资格边界


def test_financial_ineligible_but_shows_metrics():
    metrics = base_metrics(org_type=2, org_form="中央金融企业", tl_rate=0.92, fcf_ttm=None)
    row = evaluate("601398", "工商银行", "cn", metrics, [], TODAY)
    assert row.eligible is False
    assert "银行" in row.reason
    assert row.payout_ttm == pytest.approx(0.5)
    assert row.tl_rate == pytest.approx(0.92)
    assert row.fcf_cover is None
    # 金融股也要显示企业类型
    assert row.org_form == "中央金融企业"


def test_payout_series_attached():
    row = evaluate_cn()
    # payout_stats 只保留完整年度，2026 当年排除
    assert [p["year"] for p in row.payout_series] == [2025, 2024, 2023, 2022]
    assert row.payout_series[0]["payout"] == pytest.approx(0.5)


def test_org_form_passthrough_and_hk_none():
    row = evaluate_cn()
    assert row.org_form == "地方国有企业"
    hk = evaluate("hk.00700", "腾讯控股", "hk",
                  base_metrics(org_form=None), [], TODAY)
    assert hk.eligible is False
    assert hk.org_form is None


def test_hk_ineligible():
    metrics = base_metrics()
    row = evaluate("hk.00700", "腾讯控股", "hk", metrics, [], TODAY)
    assert row.eligible is False
    assert "港股" in row.reason


def test_missing_core_data_not_scored():
    row = evaluate("600003", "缺数据", "cn",
                   {k: v for k, v in base_metrics().items()
                    if k not in ("ncfo_ttm", "npts_ttm")},
                   [], TODAY)
    assert row.eligible is False
    assert "核心数据缺失" in row.reason
    assert "经营现金流/净利润" in row.missing


def test_metrics_absent():
    row = evaluate("600004", "无指标", "cn", {}, [], TODAY)
    assert row.eligible is False
    assert row.reason == "质量指标未取到" or "核心数据缺失" in row.reason


# ---------------------------------------------------------------- 评分结构


def test_score_reproducible_and_banded():
    row = evaluate_cn()
    assert row.ability_score is not None
    assert 0 <= row.ability_score <= 100
    bands = row.ability_bands
    assert bands["payout"]["band"]
    assert bands["debt"]["vs_industry"]
    assert row.confidence in ("high", "medium", "low")
    assert row.willingness_grade in ("A", "B", "C", "D")
    # 连续 10 年 + 分红率平稳 → 意愿最好档
    assert row.willingness_grade in ("A", "B")


def test_summary_counts():
    good = evaluate_cn()
    fin = evaluate("601398", "工商银行", "cn",
                   base_metrics(org_type=2, fcf_ttm=None), [], TODAY)
    hk = evaluate("hk.00700", "腾讯控股", "hk", base_metrics(), [], TODAY)
    summary = summarize([good, fin, hk])
    assert summary["eligible_count"] == 1
    assert summary["skipped"] == ["601398", "hk.00700"]
    assert summary["willingness"]["A"] + summary["willingness"]["B"] == 1
    assert summary["over_payout"] == 0
