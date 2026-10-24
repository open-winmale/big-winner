"""买卖点换算 —— 最低/最高参考价位。

区间设置两种来源（与页面 UI 一致）：
  - 推荐区间（默认）：窗口内四条约束自动搜点（详见 suggest.py）；
  - 自定义区间：自填目标 PE/PB 倍数（如 PE 12/25、金融 PB 0.8/1.0）。
  通道低估线/高估线仅作推荐搜索无解时的内部回退，不作为手动来源。

换算：`价格 = 现价 × 目标倍数 / 当前倍数`（线性，隐含窗口内 EPS/BPS 恒定假设，
与平台 valuationPrice.impliedPrice 同式）。输出为统计描述，不构成投资建议。
"""
from __future__ import annotations


def implied_price(last_close: float | None, target: float | None,
                  current_multiple: float | None) -> float | None:
    """目标倍数 → 对应价格；任一输入缺失/非法返回 None。"""
    if not last_close or last_close <= 0:
        return None
    if not target or target <= 0 or not current_multiple or current_multiple <= 0:
        return None
    return last_close * target / current_multiple


def build_levels(hist: dict, channel: dict | None, last_close: float | None,
                 low: float | None = None, high: float | None = None) -> dict | None:
    """买卖参考价位。

    - low/high：用户估计的目标倍数；缺省用通道低估线(lower2)/高估线(upper2)。
    - 返回 price_map：通道各轨与均值/中位对应的价位，供图表标尺使用。
    """
    if not channel or not hist:
        return None
    current = hist.get("current")
    if not current or current <= 0:
        return None
    low_source = "user" if low is not None else "channel"
    high_source = "user" if high is not None else "channel"
    low_multiple = float(low) if low is not None else channel["lower2"]
    high_multiple = float(high) if high is not None else channel["upper2"]

    def _p(target: float | None) -> float | None:
        return implied_price(last_close, target, current)

    price_map = {key: _p(channel[key])
                 for key in ("lower2", "lower1", "upper1", "upper2")}
    price_map["avg"] = _p(channel["avg"])
    if channel.get("median") is not None:
        price_map["median"] = implied_price(last_close, channel["median"], current)

    buy_price = _p(low_multiple)
    sell_price = _p(high_multiple)
    distance_to_buy = (buy_price / last_close - 1) if buy_price and last_close else None
    distance_to_sell = (sell_price / last_close - 1) if sell_price and last_close else None
    return {
        "metric_current": current,
        "low_source": low_source,
        "high_source": high_source,
        "low_multiple": low_multiple,
        "high_multiple": high_multiple,
        "buy_price": buy_price,
        "sell_price": sell_price,
        "distance_to_buy_pct": distance_to_buy,
        "distance_to_sell_pct": distance_to_sell,
        "price_map": price_map,
        "assumption": "线性换算假设口径内 EPS/BPS 恒定；输出为统计描述，不构成投资建议",
    }
