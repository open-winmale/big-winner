"""波段·估值通道：与平台 web「估值通道」算法数值对齐（percentileBand.ts 同例）。"""
import math

import pytest

from bigwinner.bigly import channel as ch


def test_band_levels_matches_frontend_fixture():
    # 前端 percentileBand.test.ts 同例：(avg=18, σ=3) → {12, 15, 21, 24}
    band = ch.band_levels(18, 3)
    assert band == {"lower2": 12.0, "lower1": 15.0, "upper1": 21.0, "upper2": 24.0}


def test_band_lower_clamped_to_zero():
    # 均值−2σ < 0 时下轨截 0，且 lower1 ≥ lower2
    band = ch.band_levels(1.0, 1.0)
    assert band["lower2"] == 0.0
    assert band["lower1"] >= band["lower2"]
    assert band["upper1"] == pytest.approx(2.0)
    assert band["upper2"] == pytest.approx(3.0)


def test_band_rejects_bad_input():
    assert ch.band_levels(18, 0) is None
    assert ch.band_levels(18, None) is None


def test_population_stddev_is_divided_by_n():
    # 总体口径 ÷N：[0, 2, 4] 的均值 2、方差 8/3
    s = ch.population_stddev([0.0, 2.0, 4.0])
    assert s == pytest.approx(math.sqrt(8 / 3))


def test_resolve_stddev_prefers_engine_value():
    assert ch.resolve_stddev(0.5, [1, 2, 3]) == 0.5
    assert ch.resolve_stddev(None, [0.0, 2.0, 4.0]) == pytest.approx(math.sqrt(8 / 3))


def _hist(values, current=None, stddev=None):
    cur = values[-1] if current is None else current
    ordered = sorted(values)
    n = len(ordered)
    pct = sum(1 for v in values if v <= cur) / n
    return {"avg": sum(values) / n, "current": cur,
            "median": ordered[n // 2], "min": ordered[0], "max": ordered[-1],
            "pct": pct, "count": n, "stddev": stddev,
            "series": [[1698076800 + i * 86400, v] for i, v in enumerate(values)]}


def test_build_channel_zone_and_coverage():
    values = [10.0, 12.0, 14.0, 16.0, 18.0]  # avg=14、σ≈2.828；current=14 → normal
    h = _hist(values, current=14.0)
    c = ch.build_channel(h)
    sigma = math.sqrt(8.0)
    assert c["sigma"] == pytest.approx(sigma)
    assert c["z"] == pytest.approx(0.0, abs=1e-9)  # current == avg
    assert c["zone"] == "normal"
    assert c["coverage"] == 1.0  # 全部落在 ±2σ 内
    assert c["metric_series_n"] == 5


def test_build_channel_zone_edges():
    values = [10.0, 12.0, 14.0, 16.0, 18.0]
    sigma = math.sqrt(8.0)
    high = ch.build_channel(_hist(values, current=14 + 2 * sigma + 0.1))
    assert high["zone"] == "aboveHigh"
    low = ch.build_channel(_hist(values, current=max(0.0, 14 - 2 * sigma - 0.1)))
    assert low["zone"] == "belowLow"


def test_build_channel_empty_when_no_valuation():
    assert ch.build_channel({"avg": None, "current": None, "series": []}) is None
    assert ch.build_channel(None) is None
