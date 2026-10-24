"""拨测回看 + 波段/长持对比 + 安全边界统计。

拨测规则（全部成文，与平台自选页「买卖点拨测」语义对齐的透明简化版）：
  1. 数据为 qfq 前复权已收盘日 K，按日期升序；
  2. 买入触发：某日 low ≤ buy_price → 当日成交，成交价 = min(open, buy_price)
     （限价单语义，开盘更低按更优价）；
  3. 止盈：持仓期日 high ≥ sell_price → 成交 = max(open, sell_price)；
     止损：持仓期日 low ≤ stop_loss → 成交 = min(open, stop_loss)；
  4. 同日双触发按保守处理（先止损）；T+1：买入当日不触发卖出；
  5. roundtrips：出场后是否继续找下一次买入——
     1（默认，平台拨测语义）= 单次进出场即结束；
     None = 窗口内不限次数，止盈/止损出场后资金回笼，**卖出次日**方可再买；
  6. 窗口结束仍持仓 → 输出浮动收益；未触发买入 → 输出当前距买点距离；
  7. 简化假设：不含涨跌停与成交量约束；qfq 口径已消除除权跳空。

输出全部为历史统计与回放，不构成投资建议。
"""
from __future__ import annotations


def max_drawdown(closes: list[float], entry: float | None = None) -> float:
    """最大回撤（负数）。entry 给定时以 entry 为初始峰值（买入视角）。"""
    peak = float(entry) if entry is not None else None
    worst = 0.0
    for v in closes:
        if peak is None or v > peak:
            peak = float(v)
        if peak and peak > 0:
            worst = min(worst, v / peak - 1.0)
    return worst


def price_percentile(value: float, closes: list[float]) -> float:
    """值在序列中的位置分位（0~1，count(<=value)/n）。"""
    if not closes:
        return 0.0
    return sum(1 for v in closes if v <= value) / len(closes)


def backtest_levels(bars: list[dict], buy_price: float, sell_price: float,
                    stop_loss: float | None = None,
                    roundtrips: int | None = 1) -> dict:
    """对窗口内日 K 回放一组买卖点（含可选止损）。

    roundtrips=1 → 单次进出场（与平台拨测一致）；None → 窗口内不限次数
    （止盈/止损出场后资金回笼、卖出次日才可再买）；正整数 → 最多 N 次。

    多轮聚合口径：return_pct 为各轮复利（空仓期收益 0，不含现金利息）；
    days_held 为各轮持仓日合计；holding_mdd 取各轮最差；underwater 为各轮合计；
    buy_date/buy_fill 取首轮，sell_date/sell_reason/sell_fill 取最后一次完整出场。
    """
    events: list[dict] = []
    if not bars or not buy_price:
        return _empty(bars, events)

    legs: list[dict] = []
    n = len(bars)
    i = 0
    while i < n:
        # 找买入：low ≤ 买点 → min(open, 买点) 成交（限价单语义）
        while i < n and not (float(bars[i].get("low") or 0.0) <= buy_price):
            i += 1
        if i >= n:
            break
        bar = bars[i]
        buy_fill = min(float(bar.get("open") or buy_price), buy_price)
        events.append({"type": "buy", "date": bar.get("date"),
                       "price": round(buy_fill, 4)})
        holding_closes = [float(bar.get("close") or 0.0)]
        holding_highs = [float(bar.get("high") or 0.0)]
        holding_lows = [float(bar.get("low") or 0.0)]
        exit_i = None
        sell_reason = None
        sell_fill = None
        j = i + 1  # T+1：买入当日不判卖出
        while j < n:
            low = float(bars[j].get("low") or 0.0)
            high = float(bars[j].get("high") or 0.0)
            close = float(bars[j].get("close") or 0.0)
            holding_closes.append(close)
            holding_highs.append(high)
            holding_lows.append(low)
            hit_stop = stop_loss is not None and low <= stop_loss
            hit_target = high >= sell_price
            if hit_stop:  # 同日双触发按保守：先止损
                sell_fill = min(float(bars[j].get("open") or stop_loss), stop_loss)
                exit_i, sell_reason = j, "stop"
                events.append({"type": "stop", "date": bars[j].get("date"),
                               "price": round(sell_fill, 4)})
                break
            if hit_target:
                sell_fill = max(float(bars[j].get("open") or sell_price), sell_price)
                exit_i, sell_reason = j, "target"
                events.append({"type": "sell", "date": bars[j].get("date"),
                               "price": round(sell_fill, 4)})
                break
            j += 1
        legs.append({
            "pos_i": i, "exit_i": exit_i, "buy_fill": buy_fill,
            "sell_reason": sell_reason, "sell_fill": sell_fill,
            "holding_closes": holding_closes, "holding_highs": holding_highs,
            "holding_lows": holding_lows,
        })
        if roundtrips is not None and len(legs) >= roundtrips:
            break
        if exit_i is None:  # 窗口末仍持仓
            break
        i = exit_i + 1  # 卖出次日才可再买（保守）

    if not legs:  # 从未触发买入：输出当前距买点距离
        out = _empty(bars, events)
        last = float(bars[-1].get("close") or 0.0)
        out["distance_to_buy_pct"] = (buy_price / last - 1.0) if last > 0 else None
        return out

    first = legs[0]
    last_leg = legs[-1]
    completed = [l for l in legs if l["exit_i"] is not None]
    last_done = completed[-1] if completed else None
    days_held = sum((l["exit_i"] if l["exit_i"] is not None else n - 1) - l["pos_i"]
                    for l in legs)
    compounded = 1.0
    for l in legs:
        exit_fill = l["sell_fill"] if l["exit_i"] is not None else l["holding_closes"][-1]
        compounded *= 1.0 + (exit_fill / l["buy_fill"] - 1.0)
    # 亏损持仓：窗口内「持仓且收盘低于成交买价」的交易日合计（衡量套牢时长）
    underwater_days = sum(1 for l in legs for c in l["holding_closes"]
                          if c < l["buy_fill"])
    out = {
        "hit_buy": True,
        "buy_date": bars[first["pos_i"]].get("date"),
        "buy_fill": first["buy_fill"],
        "hit_sell": any(l["sell_reason"] == "target" for l in completed),
        "sell_date": bars[last_done["exit_i"]].get("date") if last_done else None,
        "sell_reason": last_done["sell_reason"] if last_done else None,
        "sell_fill": last_done["sell_fill"] if last_done else None,
        "still_holding": last_leg["exit_i"] is None,
        "days_held": days_held,
        "return_pct": compounded - 1.0,
        "entries": len(legs),
        "roundtrips_done": len(completed),
        "stop_count": sum(1 for l in completed if l["sell_reason"] == "stop"),
        "holding_high": max(v for l in legs for v in l["holding_highs"]),
        "holding_low": min(v for l in legs for v in l["holding_lows"]),
        "holding_mdd": min(max_drawdown(l["holding_closes"], entry=l["buy_fill"])
                           for l in legs),
        "underwater_days": underwater_days,
        "underwater_ratio": underwater_days / n if n else None,
        "no_stop_worst_drawdown": None,
        "events": events,
        "window": {"start": bars[0].get("date"), "end": bars[-1].get("date"),
                   "bars": n},
    }
    if stop_loss is None:
        # 无止损：持有期最差浮亏（以最低价计，取各轮相对首轮买价的最差）
        worst_low = min(v for l in legs for v in l["holding_lows"])
        if worst_low:
            out["no_stop_worst_drawdown"] = worst_low / first["buy_fill"] - 1.0
    if out["still_holding"]:
        out["unrealized_pct"] = out["return_pct"]
    return out


def price_extremes(bars: list[dict],
                   last_close: float | None = None) -> dict | None:
    """窗口极值：最低/最高收盘及其日期；现价较最低的溢价（溢出多少）、较最高的折价。"""
    pts = [(b.get("date"), float(b["close"])) for b in bars if b.get("close")]
    if not pts:
        return None
    lo_date, lo = min(pts, key=lambda t: t[1])
    hi_date, hi = max(pts, key=lambda t: t[1])
    last = last_close if last_close is not None else pts[-1][1]
    return {
        "low": {"price": lo, "date": lo_date,
                "premium_pct": (last / lo - 1.0) if lo > 0 else None},
        "high": {"price": hi, "date": hi_date,
                 "discount_pct": (last / hi - 1.0) if hi > 0 else None},
        "last_close": last,
    }


def price_zone_stats(bars: list[dict], buy_price: float | None,
                     sell_price: float | None,
                     last_close: float | None = None) -> dict | None:
    """收盘价相对买卖点的三区分布（天数+占比）+ 距窗口极值溢价。

    - 低于买点：收盘 < 买入参考价（历史上「挂单能成交」的日子）；
    - 高于卖点：收盘 > 卖出参考价（「能卖出」的日子）；
    - 区间内：介于买卖点之间。买卖点无效（sell ≤ buy）时区间口径失真，
      inside 按剩余天数兜底。
    """
    pts = [(b.get("date"), float(b["close"])) for b in bars if b.get("close")]
    n = len(pts)
    if not n or not buy_price or not sell_price:
        return None
    below = sum(1 for _, c in pts if c < buy_price)
    above = sum(1 for _, c in pts if c > sell_price)
    inside = max(0, n - below - above)

    def _pack(c: int) -> dict:
        return {"days": c, "ratio": c / n if n else None}

    out = {
        "n": n,
        "buy_price": buy_price,
        "sell_price": sell_price,
        "below_buy": _pack(below),
        "inside": _pack(inside),
        "above_sell": _pack(above),
        "extremes": price_extremes(bars, last_close),
    }
    return out


def _empty(bars: list[dict], events: list[dict]) -> dict:
    return {
        "hit_buy": False, "buy_date": None, "buy_fill": None,
        "hit_sell": False, "sell_date": None, "sell_reason": None, "sell_fill": None,
        "still_holding": False, "days_held": None, "return_pct": None,
        "entries": 0, "roundtrips_done": 0, "stop_count": 0,
        "holding_high": None, "holding_low": None, "holding_mdd": None,
        "underwater_days": None, "underwater_ratio": None,
        "no_stop_worst_drawdown": None, "events": events,
        "window": {"start": bars[0].get("date") if bars else None,
                   "end": bars[-1].get("date") if bars else None,
                   "bars": len(bars)},
    }


def compare_with_hold(bars: list[dict], bt: dict) -> dict:
    """波段（用户买卖点回放）vs 长持（首日收盘买入持有至窗口末）同窗对比。

    波段收益仅计持仓时段（空仓期收益为 0，不含现金利息）；长持全程满仓。
    """
    closes = [float(b["close"]) for b in bars if b.get("close")]
    if len(closes) < 2:
        return {}
    hold_return = closes[-1] / closes[0] - 1.0
    hold_mdd = max_drawdown(closes)
    flat_ratio = 0.0
    if bt.get("hit_buy"):
        total = len(bars)
        # 每轮买入日与出场日均算持仓：合计 = days_held + 轮数
        held = (bt.get("days_held") or 0) + max(bt.get("entries") or 1, 1)
        flat_ratio = (total - held) / total if total else 0.0
    swing_return = bt.get("return_pct")
    spread = (swing_return - hold_return) if swing_return is not None else None
    mdd_spread = None
    if swing_return is not None and bt.get("holding_mdd") is not None:
        mdd_spread = bt["holding_mdd"] - hold_mdd
    trades = bt.get("roundtrips_done")
    if trades is None:  # 兼容旧输出
        trades = 1 if bt.get("hit_sell") else 0
    verdict = None
    if spread is not None:
        verb = "跑赢" if spread >= 0 else "跑输"
        verdict = (f"本窗口内，波段较长持{verb} {abs(spread) * 100:.1f} 个百分点"
                   f"（历史回放，不代表未来）。")
    return {
        "swing": {"return_pct": swing_return, "mdd": bt.get("holding_mdd"),
                  "days_held": bt.get("days_held"),
                  "flat_ratio": flat_ratio,
                  "trades": trades,
                  "stop_hit": bt.get("stop_count", 0) > 0
                  or bt.get("sell_reason") == "stop"},
        "hold": {"return_pct": hold_return, "mdd": hold_mdd, "days": len(closes)},
        "delta": {"return_spread": spread, "mdd_spread": mdd_spread},
        "verdict": verdict,
    }


# ---- 安全边界（描述性统计；不阻止、不建议，只呈现历史事实） ----

def high_entry_drawdown_stats(closes: list[float],
                              ref_percentile: float) -> dict | None:
    """高位介入回撤统计：所有位置分位 ≥ ref_percentile 的交易日作为假想买点，
    各自此后持有的最大回撤分布。

    返回 {median_mdd, worst_mdd, sample_n}；样本不足返回 None。
    """
    n = len(closes)
    if n < 20 or not 0 <= ref_percentile <= 1:
        return None
    mdds: list[float] = []
    for i in range(n):
        entry = closes[i]
        if price_percentile(entry, closes) < ref_percentile:
            continue
        mdds.append(max_drawdown(closes[i:], entry=entry))
    if len(mdds) < 5:
        return None
    mdds.sort()
    mid = len(mdds) // 2
    median = mdds[mid] if len(mdds) % 2 else (mdds[mid - 1] + mdds[mid]) / 2.0
    return {"median_mdd": median, "worst_mdd": mdds[0], "sample_n": len(mdds)}


def buy_safety_check(buy_price: float | None, channel: dict | None,
                     window_closes: list[float],
                     last_close: float | None = None) -> dict:
    """买入位安全检查：高于通道 +1σ 对应价或窗口 p75 价即视为高位买入。

    注意坐标系：channel 是估值倍数（如 PB≈2.8），须先换算成价格
    （upper1_price = 现价 × upper1 / current）再与 buy_price 比较。
    """
    out: dict = {"high": False, "reasons": []}
    if not buy_price or not window_closes:
        return out
    if channel and channel.get("upper1") is not None and last_close:
        current = channel.get("current")
        if current and current > 0:
            upper1_price = last_close * channel["upper1"] / current
            if buy_price > upper1_price:
                out["high"] = True
                out["reasons"].append(
                    f"买入位高于通道 +1σ 对应价（{upper1_price:.2f} 元，z=+1）")
    p75 = sorted(window_closes)[int(len(window_closes) * 0.75) - 1] if len(window_closes) >= 4 else None
    if p75 and buy_price >= p75:
        out["high"] = True
        out["reasons"].append(f"买入位不低于窗口 75% 分位价（{p75:.2f}）")
    return out
