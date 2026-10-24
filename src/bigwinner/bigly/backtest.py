"""拨测回看 + 波段/长持对比 + 安全边界统计。

拨测规则（全部成文，与平台自选页「买卖点拨测」语义对齐的透明简化版）：
  1. 数据为 qfq 前复权已收盘日 K，按日期升序；
  2. 买入触发：某日 low ≤ buy_price → 当日成交，成交价 = min(open, buy_price)
     （限价单语义，开盘更低按更优价）；
  3. 止盈：持仓期日 high ≥ sell_price → 成交 = max(open, sell_price)；
     止损：持仓期日 low ≤ stop_loss → 成交 = min(open, stop_loss)；
  4. 同日双触发按保守处理（先止损）；T+1：买入当日不触发卖出；
  5. 窗口结束仍持仓 → 输出浮动收益；未触发买入 → 输出当前距买点距离；
  6. 简化假设：不含涨跌停与成交量约束；qfq 口径已消除除权跳空。

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
                    stop_loss: float | None = None) -> dict:
    """对窗口内日 K 回放用户设定的一组买卖点（含可选止损）。"""
    events: list[dict] = []
    if not bars:
        return _empty(bars, events)

    pos_i = None
    buy_fill = None
    holding_closes: list[float] = []
    holding_highs: list[float] = []
    holding_lows: list[float] = []
    exit_i = None
    sell_reason = None
    sell_fill = None

    for i, bar in enumerate(bars):
        low = float(bar.get("low") or 0.0)
        high = float(bar.get("high") or 0.0)
        close = float(bar.get("close") or 0.0)
        if pos_i is None:
            if buy_price and low <= buy_price:
                buy_fill = min(float(bar.get("open") or buy_price), buy_price)
                pos_i = i
                holding_closes = [close]
                holding_highs = [high]
                holding_lows = [low]
                events.append({"type": "buy", "date": bar.get("date"),
                               "price": round(buy_fill, 4)})
            continue
        # T+1：买入当日不触发卖出（pos_i 在本循环先前 bar 设置才会进入卖出判定）
        holding_closes.append(close)
        holding_highs.append(high)
        holding_lows.append(low)
        hit_stop = stop_loss is not None and low <= stop_loss
        hit_target = high >= sell_price
        if hit_stop:  # 同日双触发按保守：先止损
            sell_fill = min(float(bar.get("open") or stop_loss), stop_loss)
            exit_i, sell_reason = i, "stop"
            events.append({"type": "stop", "date": bar.get("date"),
                           "price": round(sell_fill, 4)})
            break
        if hit_target:
            sell_fill = max(float(bar.get("open") or sell_price), sell_price)
            exit_i, sell_reason = i, "target"
            events.append({"type": "sell", "date": bar.get("date"),
                           "price": round(sell_fill, 4)})
            break

    if pos_i is None:
        out = _empty(bars, events)
        last = float(bars[-1].get("close") or 0.0)
        out["distance_to_buy_pct"] = (buy_price / last - 1.0) if last > 0 else None
        return out

    still_holding = exit_i is None
    holding_days = (exit_i if exit_i is not None else len(bars) - 1) - pos_i
    exit_fill = sell_fill if sell_fill is not None else holding_closes[-1]
    return_pct = exit_fill / buy_fill - 1.0 if buy_fill else None
    holding_mdd = max_drawdown(holding_closes, entry=buy_fill)
    no_stop_worst = None
    if stop_loss is None:
        # 无止损：持有期最差浮亏（以最低价计）
        worst_low = min(holding_lows) if holding_lows else None
        no_stop_worst = (worst_low / buy_fill - 1.0) if buy_fill and worst_low else None
    out = {
        "hit_buy": True,
        "buy_date": bars[pos_i].get("date"),
        "buy_fill": buy_fill,
        "hit_sell": exit_i is not None,
        "sell_date": bars[exit_i].get("date") if exit_i is not None else None,
        "sell_reason": sell_reason,
        "sell_fill": sell_fill,
        "still_holding": still_holding,
        "days_held": holding_days,
        "return_pct": return_pct,
        "holding_high": max(holding_highs) if holding_highs else None,
        "holding_low": min(holding_lows) if holding_lows else None,
        "holding_mdd": holding_mdd,
        "no_stop_worst_drawdown": no_stop_worst,
        "events": events,
        "window": {"start": bars[0].get("date"), "end": bars[-1].get("date"),
                   "bars": len(bars)},
    }
    if still_holding:
        out["unrealized_pct"] = return_pct
    return out


def _empty(bars: list[dict], events: list[dict]) -> dict:
    return {
        "hit_buy": False, "buy_date": None, "buy_fill": None,
        "hit_sell": False, "sell_date": None, "sell_reason": None, "sell_fill": None,
        "still_holding": False, "days_held": None, "return_pct": None,
        "holding_high": None, "holding_low": None, "holding_mdd": None,
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
        held = (bt.get("days_held") or 0) + 1  # 买入日与出场日均算持仓
        flat_ratio = (total - held) / total if total else 0.0
    swing_return = bt.get("return_pct")
    spread = (swing_return - hold_return) if swing_return is not None else None
    mdd_spread = None
    if swing_return is not None and bt.get("holding_mdd") is not None:
        mdd_spread = bt["holding_mdd"] - hold_mdd
    verdict = None
    if spread is not None:
        verb = "跑赢" if spread >= 0 else "跑输"
        verdict = (f"本窗口内，波段较长持{verb} {abs(spread) * 100:.1f} 个百分点"
                   f"（历史回放，不代表未来）。")
    return {
        "swing": {"return_pct": swing_return, "mdd": bt.get("holding_mdd"),
                  "days_held": bt.get("days_held"),
                  "flat_ratio": flat_ratio,
                  "trades": 1 if bt.get("hit_sell") else 0,
                  "stop_hit": bt.get("sell_reason") == "stop"},
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
