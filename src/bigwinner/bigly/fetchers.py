"""必赢佬数据层：finpipe 取数与离线样例（Fetcher 可替换）。

真实模式经 finpipe SDK 取数（估值历史统计 / qfq 日 K / 现价）；3 年窗口约
730 个交易日，故客户端 max_limit 放宽到 800。演示模式（--demo）用确定性
罐头数据，无凭证、不联网即可看效果。
"""
from __future__ import annotations

import math
import random
from typing import Any

#: 窗口 → 日 K 根数（约 244 交易日/年，留余量）
WINDOW_BARS = {"6m": 130, "1y": 260, "2y": 510, "3y": 760}
#: 窗口 → demo 估值序列点数（demo 全量 730 点 ≈ 3 年）
_WINDOW_POINTS = {"6m": 122, "1y": 244, "2y": 488, "3y": 730}


class FinpipeBiglyData:
    """经 finpipe SDK 取数的真实数据源。"""

    demo = False

    def __init__(self, client: Any | None = None):
        import finpipe

        self._cli = client or finpipe.Client.from_env()
        try:
            self._cli.max_limit = max(self._cli.max_limit or 0, 800)
        except TypeError:  # max_limit=None 表示不限
            pass

    def hist_stats(self, symbol: str, metric: str, window: str) -> dict:
        return self._cli.valuation.hist_stats(symbol, metric=metric, window=window)

    def last_close(self, symbol: str) -> float | None:
        try:
            v = self._cli.indicator.get(symbol, "$CLOSE_LAST")
        except Exception:  # noqa: BLE001 - 个别标的缺失时降级为 None
            return None
        return float(v) if isinstance(v, (int, float)) else None

    def bars(self, symbol: str, window: str) -> list[dict]:
        rows = self._cli.call("kline.query_bars_adj", sym=symbol,
                              limit=WINDOW_BARS.get(window, 260), adj="qfq")
        if not isinstance(rows, list):
            return []
        # store 返回新在前；拨测状态机要求旧→新升序（ISO 日期字典序即可比）
        return sorted(rows, key=lambda r: str(r.get("date", "")))


class DemoBiglyData:
    """确定性罐头数据（600900 风格的 PB 通道 + 正弦叠加随机游走价格）。"""

    demo = True

    def __init__(self) -> None:
        import datetime as _dt

        self._today = _dt.date.today()
        rng = random.Random(20261023)
        # PB 历史序列：3 年 ≈ 730 点，均值 3.0、σ 0.26 的温和波动
        vals: list[float] = []
        v = 2.8
        for i in range(730):
            wave = 0.22 * math.sin(i / 47.0) + 0.08 * math.sin(i / 13.0)
            v = 3.0 + wave + (v - (3.0 + wave)) * 0.86 + rng.uniform(-0.03, 0.03)
            vals.append(round(max(v, 1.2), 4))
        t0 = 1698076800
        step = 86400
        self._series = [[t0 + i * step * 1.4, vals[i]] for i in range(730)]
        self._current = vals[-1]
        # 日 K：现价 15 元，按 PB 序列等比例反推（PB→价格线性），低开高走噪声
        self._bars: list[dict] = []
        n = 760
        for i in range(n):
            j = min(i * 730 // n, 729)
            base = vals[j] / self._current * 15.0
            drift = rng.uniform(-0.012, 0.013)
            close = round(base * (1 + drift), 3)
            o = round(base * (1 + rng.uniform(-0.006, 0.006)), 3)
            hi = round(max(o, close) * (1 + abs(rng.uniform(0, 0.008))), 3)
            lo = round(min(o, close) * (1 - abs(rng.uniform(0, 0.008))), 3)
            self._bars.append({"date": (self._today - _dt.timedelta(days=n - 1 - i)).isoformat(),
                               "open": o, "high": hi, "low": lo, "close": close})

    def hist_stats(self, symbol: str, metric: str, window: str) -> dict:
        n = _WINDOW_POINTS.get(window, 244)
        vals = [pt[1] for pt in self._series][-n:]
        pts = self._series[-n:]
        ordered = sorted(vals)
        mid = len(ordered) // 2
        median = ordered[mid]
        return {
            "avg": sum(vals) / len(vals),
            "current": vals[-1],
            "median": median,
            "min": ordered[0],
            "max": ordered[-1],
            "pct": sum(1 for v in vals if v <= vals[-1]) / len(vals),
            "count": len(vals),
            "series": [list(pt) for pt in pts],
        }

    def last_close(self, symbol: str) -> float | None:
        return self._bars[-1]["close"]

    def bars(self, symbol: str, window: str) -> list[dict]:
        return [dict(b) for b in self._bars[-WINDOW_BARS.get(window, 260):]]
