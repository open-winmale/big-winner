"""波段·推荐区间：四条约束、择优排序、放宽标注、无解回退。

构造全部为关系型合成序列（价格序列本身即倍数序列，EPS=1 自洽），
不绑定任何单一公司的绝对量级。
"""
import statistics

from bigwinner.bigly.channel import population_stddev
from bigwinner.bigly.suggest import (MIN_TRADES, NEAR_LOW_CAP, UNDERWATER_CAP,
                                     _present, suggest_levels)


def bars_from_closes(closes):
    out = []
    for i, c in enumerate(closes):
        out.append({"date": f"d{i:03d}", "open": c * 0.995,
                    "high": c * 1.012, "low": c * 0.988, "close": c})
    return out


def chan(closes, current=None):
    """由倍数序列自洽构建通道（price==multiple，EPS=1）。"""
    avg = statistics.fmean(closes)
    sigma = population_stddev(closes)
    cur = current if current is not None else closes[-1]
    lower2 = max(0.0, avg - 2 * sigma)
    return {"metric_series_n": len(closes), "avg": avg, "median": statistics.median(closes),
            "min": min(closes), "max": max(closes), "pct": 0.5, "current": cur,
            "sigma": sigma, "lower2": lower2, "lower1": max(lower2, avg - sigma),
            "upper1": avg + sigma, "upper2": avg + 2 * sigma,
            "z": (cur - avg) / sigma, "zone": "normal", "coverage": 0.9}


# 双谷震荡：两次下探挖坑 + 两次修复 → 窗口内存在多次完整进出
WAVE = ([10.0, 9.7, 9.3, 8.9, 8.6, 8.4, 8.3, 8.6, 9.0, 9.4, 9.8, 10.1]
        + [10.0, 10.2, 10.1, 9.9]
        + [9.6, 9.2, 8.8, 8.5, 8.4, 8.7, 9.1, 9.5, 9.9, 10.2]) * 2 \
    + [10.0, 10.1, 10.0, 10.1, 10.0]


def test_suggest_respects_four_constraints():
    closes = WAVE
    bars = bars_from_closes(closes)
    sug = suggest_levels(bars, chan(closes), last_close=closes[-1], metric="pe")
    assert sug is not None
    c = sug["criteria"]
    assert c["buy_vs_avg"] <= 1e-9                       # 不高估
    assert c["near_low_pct"] <= NEAR_LOW_CAP + 1e-9      # 距最低点不要太远
    assert c["underwater_ratio"] <= UNDERWATER_CAP       # 亏损时间不要过长
    assert c["roundtrips_done"] >= MIN_TRADES            # 成交次数不要太少
    assert c["strict_ok"] is True
    assert sug["stats"]["hit_buy"] is True
    assert sug["stats"]["return_pct"] > 0
    assert "满足四条约束" in sug["note"]
    # 换算一致性：买价 = 现价 × 目标倍数 / 当前倍数；买点低于卖点
    assert sug["buy_multiple"] <= sug["sell_multiple"]
    last = closes[-1]
    assert sug["buy_price"] == sug["buy_multiple"] * last / last


def test_suggest_none_when_never_triggers():
    # 单边上行且起点即全程最低：所有 ≤均值 的买点价都高于窗口内任何 low
    closes = [90.0 + 15.0 * i / 59 for i in range(60)]
    bars = bars_from_closes(closes)
    ch = {"avg": 25.0, "current": 30.0, "sigma": 1.6, "lower2": 21.8,
          "lower1": 23.4, "upper1": 26.6, "upper2": 28.2, "min": 21.8,
          "max": 28.2, "median": 25.0, "pct": 0.9, "z": 3.1, "zone": "high",
          "coverage": 0.8, "metric_series_n": 60}
    # last_close=105：买点价上限 = 105×25/30 = 87.5 < 窗口最低 low 88.99
    assert suggest_levels(bars, ch, last_close=105.0) is None


def test_too_short_window_returns_none():
    closes = [10.0, 10.1, 10.2]
    assert suggest_levels(bars_from_closes(closes), chan(closes), 10.2) is None


def test_relaxed_note_when_strict_caps_unreachable():
    # 直测呈现层：放宽档选出的组合（0 次完整进出）须如实标注
    winner = (-0.05, -0.0, 0.6, 1.2, 8.0, 9.0, 8.0, 9.0,
              {"return_pct": -0.05, "holding_mdd": -0.2, "days_held": 30,
               "still_holding": True, "hit_sell": False, "sell_reason": None,
               "underwater_days": 36, "underwater_ratio": 0.6,
               "entries": 1, "roundtrips_done": 0, "stop_count": 0})
    ch = chan([10.0 - 0.02 * i for i in range(60)])
    out = _present(winner, ch, "pe", min_price=7.0, window_days=60,
                   caps=(None, None, 1))
    assert out["criteria"]["strict_ok"] is False
    assert "放宽" in out["note"]
    assert out["criteria"]["roundtrips_done"] == 0
    assert "完整进出 0 次" in out["note"]


def test_strict_ok_even_when_found_at_relaxed_step():
    # 放宽档找到的组合若实际满足严格上限（含 ≥2 次进出），仍按「满足四条约束」呈现
    winner = (0.2, -3.0, 0.1, 1.05, 8.0, 9.0, 8.0, 9.0,
              {"return_pct": 0.2, "holding_mdd": -0.1, "days_held": 10,
               "still_holding": False, "hit_sell": True, "sell_reason": "target",
               "underwater_days": 3, "underwater_ratio": 0.05,
               "entries": 3, "roundtrips_done": 3, "stop_count": 0})
    ch = chan([10.0 + 0.01 * i for i in range(60)])
    out = _present(winner, ch, "pe", min_price=7.6, window_days=60,
                   caps=(None, None, 1))
    assert out["criteria"]["strict_ok"] is True
    assert "满足四条约束" in out["note"]
