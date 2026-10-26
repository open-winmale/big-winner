"""选股筛选：预置策略一键全市场选股，输出带数字的选股清单。

设计取向：
- 策略 = 注册表里的一张卡：名称 + 一句话口径 + 条件列表 + 结果列 + 排序。
  全部走平台选股通道 `wm-screen-index` 的 conditions action（任意 INDICATOR
  条件、市场参数、fields 投影、top_n），与平台 web「选股」同一引擎——实测
  `$PE_TTM_LAST` / `$PB_TTM_LAST` / 股息率(cn+hk) 均可用（2026-10-26）。
  finpipe 原生 index 积木实测已 500（spec 契约变更，缺 fields），列 roadmap。
- 输出 = rows + columns：数字本身就是入选证据；缺失显式 None，不冒充。
- 通道不可用（未装 wm.sh 等）→ unavailable + 原因，页面降级，绝不静默。
- 选股结果 ≠ 推荐；格雷厄姆为简化口径（PE<15 ∧ PB<1.5，数学上蕴含
  经典的 PE×PB<22.5），完整格雷厄姆条款（流动比率/盈利年限等）数据源
  暂无全市场字段，如实标注。

调用量：每策略 1 次 wm 查询（top_n 即返回条数上限）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

#: 平台选股 skill 名（与高股息池日历同一条通道）
_SKILL = "wm-screen-index"

#: top_n 边界（与 StockScreener.high_yield 同口径）
MIN_LIMIT, MAX_LIMIT, DEFAULT_LIMIT = 1, 200, 50


# ---------------------------------------------------------------- 策略注册表


@dataclass(frozen=True)
class Strategy:
    id: str
    name: str
    intro: str                      # 一句话口径（卡片展示原文）
    market: str                     # "cn" | "hk"
    columns: tuple[tuple[str, str, str], ...]   # (字段码, 列名, fmt: pct|num)
    conditions: tuple[dict[str, Any], ...]
    order: tuple[str, str]          # (字段码, "desc"|"asc") 结果排序
    cost: int = 1                   # 预计查询次数


def _ind(field: str, label: str, op: str, value: Any) -> dict[str, Any]:
    return {"type": "INDICATOR", "field": field, "label": label,
            "operator": op, "value": {"scalar": {"value": str(value)}}}


#: 结果列的常用字段
_YIELD = ("$BONUS_RATE_TTM_LAST", "股息率", "pct")
_PE = ("$PE_TTM_LAST", "PE(TTM)", "num")
_PB = ("$PB_TTM_LAST", "市净率", "num")
_PAYOUT = ("$BONUS_TTM_RATE_LAST", "派息率", "pct")

STRATEGIES: list[Strategy] = [
    Strategy(
        id="high_yield_3", name="高股息 ≥3%",
        intro="TTM 股息率不低于 3%，与平台高股息池同口径",
        market="cn", columns=(_YIELD,), order=(_YIELD[0], "desc"),
        conditions=(_ind("$BONUS_RATE_TTM_LAST", "股息率TTM", "GTE", 0.03),),
    ),
    Strategy(
        id="high_yield_6", name="高股息 ≥6%",
        intro="TTM 股息率不低于 6%，深度高息——警惕价值陷阱，入选后先做体检",
        market="cn", columns=(_YIELD,), order=(_YIELD[0], "desc"),
        conditions=(_ind("$BONUS_RATE_TTM_LAST", "股息率TTM", "GTE", 0.06),),
    ),
    Strategy(
        id="graham", name="格雷厄姆（简化）",
        intro="盈利为正（0<PE≤15）且市净率<1.5，经典价值派安全边际筛（蕴含 PE×PB<22.5）",
        market="cn", columns=(_PE, _PB), order=(_PE[0], "asc"),
        conditions=(_ind("$PE_TTM_LAST", "PE(TTM)", "GTE", 0),
                    _ind("$PE_TTM_LAST", "PE(TTM)", "LT", 15),
                    _ind("$PB_TTM_LAST", "市净率", "LT", 1.5)),
    ),
    Strategy(
        id="cheap_income", name="低估值高息",
        intro="盈利为正（0<PE≤15）且股息率≥3%，低估值与现金流的交集",
        market="cn", columns=(_PE, _YIELD), order=(_YIELD[0], "desc"),
        conditions=(_ind("$PE_TTM_LAST", "PE(TTM)", "GTE", 0),
                    _ind("$PE_TTM_LAST", "PE(TTM)", "LT", 15),
                    _ind("$BONUS_RATE_TTM_LAST", "股息率TTM", "GTE", 0.03)),
    ),
    Strategy(
        id="below_pb", name="破净股",
        intro="0<市净率<1，市值低于净资产——注意资产质量，入选后先做体检",
        market="cn", columns=(_PB, _YIELD), order=(_PB[0], "asc"),
        conditions=(_ind("$PB_TTM_LAST", "市净率", "GTE", 0),
                    _ind("$PB_TTM_LAST", "市净率", "LT", 1)),
    ),
    Strategy(
        id="payout_30_70", name="派息率 30%–70%",
        intro="分红拿得出、留得住的健康区间（口径同分红质量方法论）",
        market="cn", columns=(_PAYOUT, _YIELD), order=(_PAYOUT[0], "desc"),
        conditions=(_ind("$BONUS_TTM_RATE_LAST", "派息率TTM", "GTE", 0.3),
                    _ind("$BONUS_TTM_RATE_LAST", "派息率TTM", "LTE", 0.7)),
    ),
    Strategy(
        id="high_yield_hk", name="港股高息 ≥6%",
        intro="港股通红利税默认预扣 20%，6% 起步覆盖税后",
        market="hk", columns=(_YIELD,), order=(_YIELD[0], "desc"),
        conditions=(_ind("$BONUS_RATE_TTM_LAST", "股息率TTM", "GTE", 0.06),),
    ),
]

_STRATEGY_BY_ID = {s.id: s for s in STRATEGIES}

#: 自定义组合可用的条件输入（页面渲染依据）：key -> (字段码, 标签, fmt, op, 列)
CUSTOM_FIELDS = {
    "yield_gte": ("$BONUS_RATE_TTM_LAST", "股息率 ≥", "pct", "GTE", _YIELD),
    "pe_lt": ("$PE_TTM_LAST", "PE(TTM) <", "num", "LT", _PE),
    "pb_lt": ("$PB_TTM_LAST", "市净率 <", "num", "LT", _PB),
}


def strategies_public() -> list[dict[str, Any]]:
    """给前端/文档的策略清单。"""
    return [{"id": s.id, "name": s.name, "intro": s.intro, "market": s.market,
             "columns": [{"key": k, "label": l, "fmt": f} for k, l, f in s.columns],
             "cost": s.cost}
            for s in STRATEGIES]


def get_strategy(raw: Any) -> Strategy:
    if raw not in _STRATEGY_BY_ID:
        raise ValueError(f"未知策略：{raw}")
    return _STRATEGY_BY_ID[raw]


def clamp_limit(raw: Any) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return max(MIN_LIMIT, min(MAX_LIMIT, n))


def _to_ratio(value: Any) -> float | None:
    """容忍百分数/小数两种写法：>1 视为百分数。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v > 1:
        v /= 100.0
    return v if v > 0 else None


def build_custom(spec: dict[str, Any]) -> Strategy:
    """把页面「自定义组合」的数字输入编成临时策略（条件 AND）。

    三个输入全部留空 = 没有条件，显式报错（不静默放行全市场）。
    """
    if not isinstance(spec, dict):
        raise ValueError("custom 必须是对象")
    conds: list[dict[str, Any]] = []
    columns: list[tuple[str, str, str]] = []
    ratio = _to_ratio(spec.get("yield_gte"))
    if ratio is not None:
        conds.append(_ind("$BONUS_RATE_TTM_LAST", "股息率TTM", "GTE", round(ratio, 4)))
        columns.append(_YIELD)
    pe = _to_ratio(spec.get("pe_lt"))
    if pe is not None:
        conds.append(_ind("$PE_TTM_LAST", "PE(TTM)", "GTE", 0))  # 排除亏损负 PE
        conds.append(_ind("$PE_TTM_LAST", "PE(TTM)", "LT", round(pe, 2)))
        columns.append(_PE)
    pb = _to_ratio(spec.get("pb_lt"))
    if pb is not None:
        conds.append(_ind("$PB_TTM_LAST", "市净率", "GTE", 0))   # 排除负净资产
        conds.append(_ind("$PB_TTM_LAST", "市净率", "LT", round(pb, 2)))
        columns.append(_PB)
    if not conds:
        raise ValueError("自定义组合至少填一个条件（股息率 / PE / 市净率）")
    order_col = columns[-1]
    return Strategy(
        id="custom", name="自定义组合",
        intro="按你填的阈值 AND 组合，全市场执行",
        market="cn", columns=tuple(columns),
        order=(order_col[0],
               "asc" if order_col[0].startswith(("$PE", "$PB")) else "desc"),
        conditions=tuple(conds),
    )


# ---------------------------------------------------------------- 执行


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class PlatformScreenerSource:
    """平台选股通道（wm-screen-index conditions），与平台 web 选股同引擎。

    鉴权/token/重试复用 watchlist_sync 的 wm.sh 门面；未装 wm.sh 时
    run_strategy 抛错，由 run_screen 转成 unavailable 降级。
    """

    demo = False

    def __init__(self, runner: Callable[[str, dict[str, Any], int], dict] | None = None) -> None:
        self._runner = runner

    def _skill_runner(self) -> Callable[[str, dict[str, Any], int], dict]:
        if self._runner is not None:
            return self._runner
        from bigwinner.common.watchlist_sync import _run_skill
        return _run_skill

    def run_strategy(self, strategy: Strategy, limit: int) -> list[dict[str, Any]]:
        from bigwinner.common.watchlist_sync import _find

        fields = ["$SYMBOL", "$NAME"] + [c[0] for c in strategy.columns]
        args = {"action": "conditions", "market": strategy.market,
                "top_n": max(MIN_LIMIT, min(int(limit), MAX_LIMIT)),
                "fields": fields, "conditions": list(strategy.conditions)}
        data = self._skill_runner()(_SKILL, args, timeout=90)
        rows = _find(data, "rows") or []
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows if isinstance(rows, list) else []:
            vals = row.get("values") if isinstance(row, dict) else None
            if not isinstance(vals, dict) or not vals:
                vals = row if isinstance(row, dict) else {}
            raw = vals.get("$SYMBOL") or vals.get("symbol") or ""
            digits = "".join(ch for ch in str(raw) if ch.isdigit())
            if not digits:
                continue
            code = ("hk." + digits[-5:].zfill(5)) if strategy.market == "hk" \
                else digits[-6:]
            if code in seen:
                continue
            seen.add(code)
            out.append({
                "code": code,
                "name": str(vals.get("$NAME") or vals.get("name") or code),
                "values": {key: _num(vals.get(key))
                           for key, _, _ in strategy.columns},
            })
        return out


def run_screen(source: Any, strategy: Strategy, limit: int) -> dict[str, Any]:
    """执行策略：rows + columns；通道失败 → unavailable 降级（绝不 500）。"""
    meta = {
        "strategy": {"id": strategy.id, "name": strategy.name,
                     "intro": strategy.intro, "market": strategy.market},
        "columns": [{"key": k, "label": l, "fmt": f}
                    for k, l, f in strategy.columns],
        "order": {"key": strategy.order[0], "dir": strategy.order[1]},
        "limit": limit,
    }
    try:
        rows = source.run_strategy(strategy, limit)
    except Exception as exc:  # noqa: BLE001 - 通道失败如实降级
        return {**meta, "unavailable": f"{type(exc).__name__}: {exc}", "rows": []}
    key, direction = strategy.order
    col_keys = {k for k, _, _ in strategy.columns}
    sort_field = key if key in col_keys else (
        strategy.columns[0][0] if strategy.columns else None)
    if sort_field:
        rows.sort(key=lambda r: r["values"].get(sort_field)
                  if r["values"].get(sort_field) is not None
                  else (float("-inf") if direction == "desc" else float("inf")),
                  reverse=direction == "desc")
    return {**meta, "rows": rows}


# ---------------------------------------------------------------- 离线罐头


@dataclass(frozen=True)
class _Stock:
    code: str
    name: str
    pe: float | None
    pb: float | None
    yield_ttm: float | None
    payout: float | None


#: demo 罐头（量级近似的编排值；页面有「演示数据」徽章）
_TABLE: tuple[_Stock, ...] = (
    _Stock("601939", "建设银行", 4.8, 0.58, 0.052, 0.30),
    _Stock("601288", "农业银行", 5.1, 0.62, 0.048, 0.31),
    _Stock("601398", "工商银行", 5.0, 0.57, 0.049, 0.30),
    _Stock("601088", "中国神华", 12.6, 1.42, 0.058, 0.72),
    _Stock("600028", "中国石化", 8.9, 0.68, 0.051, 0.65),
    _Stock("601857", "中国石油", 9.8, 0.92, 0.044, 0.52),
    _Stock("600941", "中国移动", 14.2, 1.38, 0.046, 0.71),
    _Stock("600018", "上港集团", 9.2, 0.81, 0.041, 0.44),
    _Stock("601006", "大秦铁路", 11.4, 0.83, 0.062, 0.78),
    _Stock("000898", "鞍钢股份", None, 0.49, 0.031, 0.86),
    _Stock("600808", "马钢股份", None, 0.55, 0.028, 0.92),
    _Stock("600519", "贵州茅台", 20.5, 7.9, 0.034, 0.52),
    _Stock("300750", "宁德时代", 24.1, 4.6, 0.006, 0.18),
)

_HK_TABLE: tuple[_Stock, ...] = (
    _Stock("hk.00883", "中国海洋石油", 6.4, 1.05, 0.078, 0.44),
    _Stock("hk.01088", "中国神华能源", 7.8, 0.95, 0.069, 0.73),
    _Stock("hk.00939", "汇丰控股", 7.2, 0.86, 0.072, 0.61),
    _Stock("hk.00005", "香港上海汇丰银行", None, None, None, None),
)


def _pool(stock: _Stock) -> dict[str, float | None]:
    return {"$BONUS_RATE_TTM_LAST": stock.yield_ttm, "$PE_TTM_LAST": stock.pe,
            "$PB_TTM_LAST": stock.pb, "$BONUS_TTM_RATE_LAST": stock.payout}


def _match(stock: _Stock, conditions) -> bool:
    """缺失字段视为不满足（不冒充通过，语义与显式缺失展示一致）。"""
    pool = _pool(stock)
    for cond in conditions:
        value = pool.get(cond["field"])
        if value is None:
            return False
        want = float(cond["value"]["scalar"]["value"])
        op = cond["operator"]
        if op == "GTE" and not value >= want:
            return False
        if op == "LTE" and not value <= want:
            return False
        if op == "LT" and not value < want:
            return False
    return True


class FakeScreenerSource:
    """离线 demo / 测试：同一张编排表按条件过滤（与真实语义一致），确定性。"""

    demo = True

    def run_strategy(self, strategy: Strategy, limit: int) -> list[dict[str, Any]]:
        table = _HK_TABLE if strategy.market == "hk" else _TABLE
        rows = [{"code": s.code, "name": s.name,
                 "values": {k: _pool(s).get(k) for k, _, _ in strategy.columns}}
                for s in table if _match(s, strategy.conditions)]
        return rows[:max(MIN_LIMIT, min(int(limit), MAX_LIMIT))]
