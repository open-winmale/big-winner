"""快捷过筛：把一串 A 股代码按一组明码条件过一遍，输出带数字的判定行。

设计取向：
- 条件固定为「息 + 势」一组检查项，每条一句话介绍 + 公开阈值，不做自由
  拼凑的黑箱布尔矩阵，也不做深度评分——结果列表里的数字本身就是入选证据。
- 判定尽量在本地对真实数字做（阈值出处见各条件）；SDK 布尔筛子只用在
  本地算不出来的「股息稳定」一项（bonus.screen_stable_yield，口径由
  数据源定义，页面如实标注）。
- 缺失显式：取不到的字段为 None，相关条件记「数据不足」，绝不冒充不通过。

取数成本：每票 3 次 HTTP（快照 eval + 65 根 qfq 日 K + 分红历史），
勾「股息稳定」+1 次。
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable

from bigwinner.shouxi.tools.dividend_xray import (
    PAYOUT_HEALTHY,
    PAYOUT_OVER,
    consecutive_years,
)

#: 一次性取足 65 根日 K：MA60 上行需要 61 根（今昨两个 60 日均线）
BARS_N = 65

#: 条件阈值（小数口径；出处随条件写进 intro/README）
MIN_YIELD = 0.03        # 与高股息池同口径（$BONUS_RATE_TTM_LAST >= 0.03）
MIN_DIV_YEARS = 3       # 与分红质量硬旗标「连续分红 <3 年」同源
MAX_CHG20D = 0.10       # 近 20 日涨幅上限：剔除被短线爆炒的票


# ---------------------------------------------------------------- 条件注册表


@dataclass(frozen=True)
class Condition:
    id: str
    name: str              # 条件名（勾选标签 / 未过原因）
    intro: str             # 一句话介绍（页面展示原文）
    group: str             # "dividend"（息）| "trend"（势）
    column: str            # 结果列表对应的数字字段（metrics 键）
    default: bool          # 默认是否勾选
    check: Callable[[dict[str, Any]], bool | None]


def _num_check(key: str, ok: Callable[[float], bool]) -> Callable[[dict[str, Any]], bool | None]:
    def check(metrics: dict[str, Any]) -> bool | None:
        value = metrics.get(key)
        return None if value is None else ok(value)
    return check


CONDITIONS: list[Condition] = [
    Condition(
        id="yield_ge3", name="股息率 ≥ 3%",
        intro="TTM 口径，与平台高股息池一致",
        group="dividend", column="yield_ttm", default=True,
        check=_num_check("yield_ttm", lambda v: v >= MIN_YIELD),
    ),
    Condition(
        id="payout_30_70", name="派息率 30%–70%",
        intro="分红拿得出、留得住；超 100% 危险",
        group="dividend", column="payout_ttm", default=True,
        check=_num_check("payout_ttm",
                         lambda v: PAYOUT_HEALTHY[0] <= v <= PAYOUT_HEALTHY[1]),
    ),
    Condition(
        id="div_years_ge3", name="连续分红 ≥ 3 年",
        intro="近年未断供（完整财年口径）",
        group="dividend", column="div_years", default=True,
        check=_num_check("div_years", lambda v: v >= MIN_DIV_YEARS),
    ),
    Condition(
        id="stable_yield", name="股息稳定",
        intro="数据源判定，口径未公开",
        group="dividend", column="stable", default=False,
        check=lambda m: m.get("stable"),
    ),
    Condition(
        id="above_ma20", name="站上 MA20",
        intro="现价高于 20 日均线（前复权）",
        group="trend", column="dist_ma20", default=False,
        check=_num_check("dist_ma20", lambda v: v > 0),
    ),
    Condition(
        id="ma60_up", name="MA60 上行",
        intro="中期趋势向上（60 日均线今高于昨）",
        group="trend", column="ma60_up", default=False,
        check=lambda m: m.get("ma60_up"),
    ),
    Condition(
        id="chg20_le10", name="近 20 日涨幅 ≤ 10%",
        intro="未被短线爆炒",
        group="trend", column="chg20d", default=False,
        check=_num_check("chg20d", lambda v: v <= MAX_CHG20D),
    ),
]

#: 条件 id → 注册表项（校验用）
_CONDITION_BY_ID = {c.id: c for c in CONDITIONS}

#: 默认勾选集（「收息」三条）
DEFAULT_CONDITIONS = [c.id for c in CONDITIONS if c.default]

#: 条件分组顺序与中文名（页面渲染顺序）
GROUPS = (("dividend", "息"), ("trend", "势"))


def conditions_public() -> list[dict[str, Any]]:
    """给前端/文档的条件清单（不含判定函数）。"""
    return [{"id": c.id, "name": c.name, "intro": c.intro, "group": c.group,
             "column": c.column, "default": c.default}
            for c in CONDITIONS]


def validate_conditions(raw: Any) -> list[str]:
    """校验前端传来的条件 id 列表：空/缺省回默认集，未知 id 显式报错。"""
    if raw is None or raw == []:
        return list(DEFAULT_CONDITIONS)
    if not isinstance(raw, (list, tuple)):
        raise ValueError("conditions 必须是数组")
    seen: list[str] = []
    for cid in raw:
        if cid not in _CONDITION_BY_ID:
            raise ValueError(f"未知条件：{cid}")
        if cid not in seen:
            seen.append(cid)
    return seen


# ---------------------------------------------------------------- 数字计算


def recent_consecutive_years(rows: list[dict[str, Any]],
                             today: date | None = None) -> int:
    """连续分红年数（口径同透视表倒推），但「连续」必须是还在连续：

    最近一次分红的报告期早于前年（当前年 −2）即视为已断供，按 0 计。
    放宽两年是因为年报分红滞后：次年上半财年，常规分红的最新报告期
    通常是前一年。
    """
    years = sorted(
        {int(r["sas"][:4]) for r in rows
         if r.get("sas") and str(r["sas"])[:4].isdigit()},
        reverse=True,
    )
    if not years:
        return 0
    if years[0] < (today or date.today()).year - 2:
        return 0
    return consecutive_years(rows)


def bars_metrics(bars: list[dict[str, Any]]) -> dict[str, Any]:
    """从升序日 K 算技术面数字：现价 / MA20 / 距 MA20 / MA60 上行 / 近 20 日涨幅。

    简单均线、前复权收盘；根数不足的项目为 None（不猜）。
    """
    closes = [float(b["close"]) for b in bars
              if isinstance(b, dict) and b.get("close") is not None]
    out: dict[str, Any] = {"close": None, "ma20": None, "dist_ma20": None,
                           "ma60_up": None, "chg20d": None}
    if not closes:
        return out
    out["close"] = closes[-1]
    if len(closes) >= 20:
        ma20 = sum(closes[-20:]) / 20.0
        out["ma20"] = ma20
        out["dist_ma20"] = closes[-1] / ma20 - 1.0
    if len(closes) >= 61:
        ma60 = sum(closes[-60:]) / 60.0
        ma60_prev = sum(closes[-61:-1]) / 60.0
        out["ma60_up"] = ma60 > ma60_prev
    if len(closes) >= 21:
        out["chg20d"] = closes[-1] / closes[-21] - 1.0
    return out


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- 单票判定


def evaluate_stock(source: Any, symbol: str, condition_ids: list[str]) -> dict[str, Any]:
    """取数 → 算数字 → 逐条件判定。

    passed 三态：True 全过；False 有未过（failed 列出断点条件与数字）；
    None 数据不足（勾选条件里有取不到数的，绝不冒充不通过）。
    单项取数失败不拖垮其余数字，错误原文进 errors。
    """
    conditions = [_CONDITION_BY_ID[cid] for cid in condition_ids]
    errors: dict[str, str] = {}

    def fetch(key: str, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - 单项失败降级为缺失，错误如实带出
            errors[key] = f"{type(exc).__name__}: {exc}"
            return None

    snap = fetch("snapshot", lambda: source.snapshot(symbol))
    snap = snap if isinstance(snap, dict) else {}
    bars = fetch("bars", lambda: source.bars(symbol))
    rows = fetch("dividend_rows", lambda: source.dividend_rows(symbol))

    metrics: dict[str, Any] = {
        "name": snap.get("name") or None,
        "yield_ttm": _num(snap.get("yield_ttm")),
        "payout_ttm": _num(snap.get("payout_ttm")),
        # 取数失败（None）≠ 真没有分红记录（空表 = 0 年），二者不能混
        "div_years": None if rows is None else recent_consecutive_years(rows),
        **bars_metrics(bars or []),
    }
    if any(c.id == "stable_yield" for c in conditions):
        metrics["stable"] = fetch("stable_yield",
                                  lambda: source.stable_yield(symbol))

    checks = {c.id: c.check(metrics) for c in conditions}
    failed = [{"id": c.id, "name": c.name, "column": c.column,
               "value": metrics.get(c.column)}
              for c in conditions if checks[c.id] is False]
    if failed:
        passed: bool | None = False
    elif any(v is None for v in checks.values()):
        passed = None
    else:
        passed = True

    return {
        "symbol": symbol,
        "name": metrics["name"],
        "metrics": metrics,
        "checks": checks,
        "passed": passed,
        "failed": failed,
        "errors": errors or None,
    }


# ---------------------------------------------------------------- 数据源


_SNAPSHOT_XS = (
    "return {"
    '"name": $NAME,'
    '"yield_ttm": $BONUS_RATE_TTM_LAST,'
    '"payout_ttm": $BONUS_TTM_RATE_LAST'
    "}"
)


class FinpipeScreenerSource:
    """真实取数（finpipe SDK，仅 A 股口径）。"""

    demo = False

    def __init__(self, client: Any | None = None) -> None:
        if client is None:
            try:
                import finpipe  # noqa: PLC0415 - 延迟导入，未安装也能启动服务
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "未安装 finpipe。请先：git clone "
                    "https://github.com/open-winmale/finpipe，"
                    "再 pip install -e ./finpipe（MIT 开源）。"
                ) from exc
            client = finpipe.Client.from_env()
        self._cli = client

    def snapshot(self, symbol: str) -> dict[str, Any]:
        """名称 + TTM 股息率/派息率，一次 eval（指标码与透视表同源）。"""
        data = self._cli.eval_result(_SNAPSHOT_XS, symbol=symbol)
        return data if isinstance(data, dict) else {}

    def bars(self, symbol: str, n: int = BARS_N) -> list[dict[str, Any]]:
        """qfq 日 K，按日期升序返回（MA/涨幅口径与波段一致）。"""
        rows = self._cli.call("kline.query_bars_adj", sym=symbol,
                              limit=n, adj="qfq")
        if not isinstance(rows, list):
            return []
        return sorted(rows, key=lambda r: str(r.get("date", "")))

    def dividend_rows(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        """分红历史（sas 归一口径与透视表一致），供连续年数倒推。"""
        rows = self._cli.dividend.history(symbol, limit=limit) or []
        out = []
        for r in rows:
            row = dict(r)
            if not row.get("sas"):
                row["sas"] = row.get("ex_date") or row.get("ex_div") or ""
            out.append(row)
        return out

    def stable_yield(self, symbol: str) -> bool | None:
        """股息稳定（SDK bonus.screen_stable_yield；口径由数据源定义）。"""
        return bool(self._cli.dividend.screen_stable_yield(symbol))


class FakeScreenerSource:
    """离线 demo / 测试：确定性罐头，同代码永远同结果。

    已知代码用编排表（量级近似、页面有 DEMO 徽章）；其他代码按代码种子
    合成，保证任意输入都能演示交互。
    """

    demo = True

    #: 编排表：默认三条件下正好覆盖 全过 / 派息超限 / 股息率不够 / 无分红 各形态
    _TABLE: dict[str, dict[str, Any]] = {
        "600519": {"name": "贵州茅台", "yield_ttm": 0.034, "payout_ttm": 0.52,
                   "years": 9, "chg20d": 0.06, "stable": True},
        "600900": {"name": "长江电力", "yield_ttm": 0.031, "payout_ttm": 0.74,
                   "years": 8, "chg20d": 0.01, "stable": True},
        "601398": {"name": "工商银行", "yield_ttm": 0.048, "payout_ttm": 0.30,
                   "years": 12, "chg20d": -0.02, "stable": True},
        "000858": {"name": "五粮液", "yield_ttm": 0.042, "payout_ttm": 0.85,
                   "years": 7, "chg20d": -0.05, "stable": True},
        "601318": {"name": "中国平安", "yield_ttm": 0.052, "payout_ttm": 0.48,
                   "years": 11, "chg20d": 0.03, "stable": True},
        "300750": {"name": "宁德时代", "yield_ttm": 0.006, "payout_ttm": 0.18,
                   "years": 2, "chg20d": 0.15, "stable": False},
        "002415": {"name": "海康威视", "yield_ttm": 0.028, "payout_ttm": 0.55,
                   "years": 6, "chg20d": -0.08, "stable": True},
        "688981": {"name": "中芯国际", "yield_ttm": 0.0, "payout_ttm": 0.0,
                   "years": 0, "chg20d": 0.11, "stable": False},
    }

    @staticmethod
    def _seed(code: str) -> int:
        return sum((i + 1) * ord(ch) for i, ch in enumerate(code))

    def _spec(self, code: str) -> dict[str, Any]:
        table = self._TABLE.get(code)
        if table is not None:
            return table
        s = self._seed(code)
        return {
            "name": None,
            "yield_ttm": round(0.005 + (s % 55) / 1000, 4),   # 0.5% ~ 5.9%
            "payout_ttm": round(0.15 + (s % 80) / 100, 2),    # 15% ~ 94%
            "years": s % 12,
            "chg20d": round(((s >> 2) % 30 - 12) / 100, 4),   # -12% ~ +17%
            "stable": s % 3 == 0,
        }

    def snapshot(self, symbol: str) -> dict[str, Any]:
        spec = self._spec(symbol)
        return {"name": spec["name"], "yield_ttm": spec["yield_ttm"],
                "payout_ttm": spec["payout_ttm"]}

    def bars(self, symbol: str, n: int = BARS_N) -> list[dict[str, Any]]:
        spec = self._spec(symbol)
        s = self._seed(symbol)
        rng = random.Random(s)
        price = round(8 + (s % 90) + ((s >> 3) % 100) / 100, 2)
        # 反推起点，让末段 20 日的累计涨幅 ≈ spec 的 chg20d（MA/涨幅可复算）
        start = price / (1.0 + spec["chg20d"])
        closes: list[float] = []
        c = start
        for _ in range(max(n, 21)):
            closes.append(round(c, 3))
            c *= 1.0 + rng.uniform(-0.012, 0.012)
        closes[-1] = price
        today = date.today()
        return [
            {"date": (today - timedelta(days=len(closes) - 1 - i)).isoformat(),
             "close": closes[i]}
            for i in range(len(closes))
        ]

    def dividend_rows(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        spec = self._spec(symbol)
        this_year = date.today().year
        return [{"sas": f"{this_year - i}-06-30", "dps": 0.1}
                for i in range(min(spec["years"], limit))]

    def stable_yield(self, symbol: str) -> bool:
        return bool(self._spec(symbol)["stable"])
