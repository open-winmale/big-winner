"""推荐买卖区间 —— 窗口内穷举候选组合，按四条约束过滤后择优。

四条约束（全部为窗口内可验证的历史事实，描述性、不构成投资建议）：
  1. 不高估：买点倍数 ≤ 窗口均值（候选网格上界即均值，结构性保证）；
  2. 距最低点不要太远：买入参考价 ≤ 窗口最低收盘价 × (1+15%)；
  3. 亏损时间不要过长：窗口内「持仓且收盘低于成交买价」的交易日占比 ≤ 35%；
  4. 成交次数不要太少：窗口内完整进出（买入→止盈/止损出场）≥ 2 次——
     一年只成交一次的区间对波段没有意义。

组合按窗口内**多轮进出回放**评估（止盈/止损后资金回笼、卖出次日可再买），
过滤后按「波段收益大 → 进出次数多 → 亏损占比小 → 距最低点近」择优。
无组合同时满足时逐级放宽（约束 2、3 依次 30%/50%，约束 4 降到 ≥1 次，
最后只保留「不高估 + 真实触发 + 至少 1 次完整进出」），并在结果里如实
标注放宽项；全程无完整进出则返回 None，由调用方回退通道轨。
"""
from __future__ import annotations

from bigwinner.bigly import backtest as bt_mod
from bigwinner.bigly.levels import implied_price

NEAR_LOW_CAP = 0.15     # 买入价距窗口最低收盘的上限（放宽档 0.30）
UNDERWATER_CAP = 0.35   # 亏损持仓日占窗口比上限（放宽档 0.50）
MIN_TRADES = 2          # 完整进出次数下限（放宽档 1）
# 逐级放宽：（距最低上限, 亏损占比上限, 最少完整进出次数）
_RELAX_LADDER = ((NEAR_LOW_CAP, UNDERWATER_CAP, MIN_TRADES),
                 (0.30, 0.50, MIN_TRADES),
                 (None, None, 1))
_N_BUY, _N_SELL = 8, 5


def _linspace(a: float, b: float, n: int) -> list[float]:
    if n < 2 or b <= a:
        return [a]
    step = (b - a) / (n - 1)
    return [a + step * i for i in range(n)]


def suggest_levels(bars: list[dict], channel: dict, last_close: float | None,
                   metric: str = "pe") -> dict | None:
    """在窗口内搜索满足约束的买卖倍数组合。

    bars 为已收盘 qfq 日 K（升序）；channel 为估值通道；组合以多轮进出回放
    评估；返回 None 表示窗口内找不到有完整进出的组合（如单边走势）。
    """
    if not bars or not isinstance(channel, dict):
        return None
    current = channel.get("current")
    avg = channel.get("avg")
    if not current or not avg or current <= 0 or avg <= 0 or not last_close:
        return None
    closes = [float(b["close"]) for b in bars if b.get("close")]
    if len(closes) < 20:
        return None
    min_price = min(closes)
    window_days = len(bars)

    buys = _linspace(max(0.0, float(channel.get("lower2") or 0.0)), float(avg), _N_BUY)
    sells = _linspace(float(avg), float(channel.get("upper2") or avg * 1.1), _N_SELL)

    winner = None
    caps = _RELAX_LADDER[-1]
    for caps in _RELAX_LADDER:
        winner = _search(bars, buys, sells, current, last_close, min_price,
                         window_days, caps)
        if winner is not None:
            break
    if winner is None:
        return None
    return _present(winner, channel, metric, min_price, window_days, caps)


def _search(bars: list[dict], buys: list[float], sells: list[float],
            current: float, last_close: float, min_price: float,
            window_days: int, caps: tuple):
    near_cap, uw_cap, min_trades = caps
    ranked: list[tuple] = []
    for bm in buys:
        buy_price = implied_price(last_close, bm, current)
        if not buy_price:
            continue
        if near_cap is not None and buy_price > min_price * (1.0 + near_cap):
            continue
        for sm in sells:
            if sm <= bm:
                continue
            sell_price = implied_price(last_close, sm, current)
            if not sell_price:
                continue
            bt = bt_mod.backtest_levels(bars, buy_price, sell_price, roundtrips=None)
            if not bt.get("hit_buy"):
                continue
            trades = bt.get("roundtrips_done") or 0
            if trades < min_trades:
                continue
            uw = bt.get("underwater_ratio")
            if uw_cap is not None and (uw is None or uw > uw_cap):
                continue
            ret = bt.get("return_pct")
            ranked.append((-(ret if ret is not None else 0.0), -trades,
                           uw or 0.0, buy_price / min_price,
                           bm, sm, buy_price, sell_price, bt))
    if not ranked:
        return None
    ranked.sort(key=lambda r: (r[0], r[1], r[2], r[3]))
    return ranked[0]


def _present(winner: tuple, channel: dict, metric: str, min_price: float,
             window_days: int, caps: tuple) -> dict:
    _, _, _, _, bm, sm, buy_price, sell_price, bt = winner
    avg = float(channel["avg"])
    near = buy_price / min_price - 1.0
    uw = bt.get("underwater_ratio") or 0.0
    trades = bt.get("roundtrips_done") or 0
    strict_ok = (caps == _RELAX_LADDER[0]
                 or (near <= NEAR_LOW_CAP and uw <= UNDERWATER_CAP
                     and trades >= MIN_TRADES))
    near_txt = f"{'+' if near >= 0 else '−'}{abs(near) * 100:.1f}%"
    parts = [
        f"买点 {metric.upper()} {bm:.2f} ≤ 均值 {avg:.2f}（不高估）",
        f"买入价距窗口最低收盘 {near_txt}",
        f"亏损持仓占比 {uw * 100:.0f}%（{bt.get('underwater_days') or 0}/{window_days} 个交易日）",
        f"窗口内完整进出 {trades} 次",
    ]
    if strict_ok:
        note = "窗口内满足四条约束的组合中收益最优：" + "；".join(parts) + "。"
    else:
        note = ("窗口内没有组合同时满足四条约束，已放宽「距最低点 ≤15%」「亏损占比 ≤35%」"
                "或「完整进出 ≥2 次」后择优（仍要求不高估、真实触发）："
                + "；".join(parts) + "。")
    return {
        "buy_multiple": bm,
        "sell_multiple": sm,
        "buy_price": buy_price,
        "sell_price": sell_price,
        "stats": {
            "hit_buy": bt.get("hit_buy"),
            "return_pct": bt.get("return_pct"),
            "mdd": bt.get("holding_mdd"),
            "days_held": bt.get("days_held"),
            "still_holding": bt.get("still_holding"),
            "hit_sell": bt.get("hit_sell"),
            "sell_reason": bt.get("sell_reason"),
            "underwater_days": bt.get("underwater_days"),
            "underwater_ratio": bt.get("underwater_ratio"),
            "entries": bt.get("entries"),
            "roundtrips_done": trades,
            "stop_count": bt.get("stop_count"),
        },
        "criteria": {
            "buy_vs_avg": bm - avg,
            "near_low_pct": near,
            "underwater_ratio": uw,
            "roundtrips_done": trades,
            "window_days": window_days,
            "strict_ok": strict_ok,
        },
        "note": note,
    }
