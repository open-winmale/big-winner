"""估值通道算法 —— 镜像平台 web「估值通道」（winmale-v2 percentileBand.ts）。

- 通道画在估值倍数坐标上：均值 ± Nσ；σ 为窗口序列的**总体标准差（÷N）**，
  引擎返回 stddev 时优先使用；下轨截 0（PE/PB 不为负）。
- 当前位置用 z=(current−avg)/σ 描述，分五档：belowLow / low / normal / high / aboveHigh。
- 覆盖率 = 窗口内落在 ±2σ 通道内的交易日占比。

输入为 wmshare `cli.valuation.hist_stats` 的输出：
``{avg, current, median, min, max, pct, count, series: [[unix秒, 值], ...]}``。
"""
from __future__ import annotations

import math
from typing import Any

ZONES = ("belowLow", "low", "normal", "high", "aboveHigh")


def population_stddev(values: list[float]) -> float | None:
    """总体标准差（÷N，与平台口径一致）；空序列返回 None。"""
    n = len(values)
    if n == 0:
        return None
    mean = sum(values) / n
    return math.sqrt(sum((v - mean) ** 2 for v in values) / n)


def resolve_stddev(stddev: float | None, series: list[float]) -> float | None:
    """有效 σ：引擎返回合法值则用之，否则从序列现算（镜像 resolveStddev）。"""
    if stddev is not None and math.isfinite(stddev) and stddev > 0:
        return float(stddev)
    return population_stddev(series)


def band_levels(avg: float, stddev: float) -> dict[str, float] | None:
    """四条轨：低估线(−2σ，截 0)/−1σ/+1σ/高估线(+2σ)。镜像 computeBandLevels。"""
    if avg is None or stddev is None:
        return None
    if not (math.isfinite(avg) and math.isfinite(stddev)) or stddev <= 0:
        return None
    lower2 = max(0.0, avg - 2.0 * stddev)
    lower1 = max(lower2, avg - stddev)
    return {"lower2": lower2, "lower1": lower1,
            "upper1": avg + stddev, "upper2": avg + 2.0 * stddev}


def zone_of(current: float, band: dict[str, float]) -> str:
    """当前位置五档（镜像 bandZoneOf：轨外/轨内按 ±1σ/±2σ 划分）。"""
    if current > band["upper2"]:
        return "aboveHigh"
    if current > band["upper1"]:
        return "high"
    if current >= band["lower1"]:
        return "normal"
    if current >= band["lower2"]:
        return "low"
    return "belowLow"


def coverage_within_band(values: list[float], band: dict[str, float]) -> float:
    """±2σ 通道内交易日占比（0~1）。"""
    if not values:
        return 0.0
    inside = sum(1 for v in values if band["lower2"] <= v <= band["upper2"])
    return inside / len(values)


def zone_counts(values: list[float], band: dict[str, float]) -> dict:
    """估值倍数三区分布（天数+占比）：低于低估线 / 通道内（±2σ，含轨上）/ 高于高估线。

    与 coverage 同口径（轨上一点计入通道内）；n 为窗口内序列点数。
    """
    n = len(values)
    below = sum(1 for v in values if v < band["lower2"])
    above = sum(1 for v in values if v > band["upper2"])
    inside = n - below - above

    def _pack(c: int) -> dict:
        return {"days": c, "ratio": (c / n) if n else None}

    return {"n": n, "below_low": _pack(below), "inside": _pack(inside),
            "above_high": _pack(above)}


def _series_values(hist: dict) -> list[float]:
    return [float(pt[1]) for pt in (hist.get("series") or []) if len(pt) >= 2]


def build_channel(hist: dict) -> dict | None:
    """由 hist_stats 输出构建通道与位置描述。

    估值序列为空（如亏损期 PE 全缺）时返回 None，由调用方决定降级文案。
    """
    if not isinstance(hist, dict):
        return None
    avg, current = hist.get("avg"), hist.get("current")
    if avg is None or current is None:
        return None
    series = _series_values(hist)
    sigma = resolve_stddev(hist.get("stddev"), series)
    band = band_levels(float(avg), sigma)
    if band is None:
        return None
    z = (float(current) - float(avg)) / sigma if sigma and sigma > 0 else 0.0
    return {
        "metric_series_n": len(series),
        "avg": float(avg),
        "median": hist.get("median"),
        "min": hist.get("min"),
        "max": hist.get("max"),
        "pct": hist.get("pct"),
        "current": float(current),
        "sigma": sigma,
        **band,
        "z": z,
        "zone": zone_of(float(current), band),
        "coverage": coverage_within_band(series, band),
        "zones": zone_counts(series, band),
    }


def series_points(hist: dict) -> list[list[Any]]:
    """原始序列点（[[unix秒, 值], ...]）供图表绘制；无序列返回空表。"""
    if not isinstance(hist, dict):
        return []
    return [list(pt) for pt in (hist.get("series") or []) if len(pt) >= 2]
