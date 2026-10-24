"""T1 · 持仓收息透视表 —— 纯计算层（不依赖 HTTP，可单测）。

设计原则：
1. **单位纪律**：内部一律使用 SDK 基础单位（比率=小数、金额=元、股数=股），
   只在渲染层转成百分比，杜绝 0.0396 → 0.04% 这类量级错误。
2. **取数可注入**：所有数据经 `Fetcher` 协议获取，测试用 `FakeFetcher`，
   生产用 `FinpipeFetcher`。计算层不认识 finpipe。
3. **缺失显式化**：任何字段取不到都是 `None`，并记入 `Row.missing`，
   绝不静默填 0 或猜值。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, Sequence

# ---------------------------------------------------------------- 数据契约

#: 指标码（全部经离线目录实测存在）
METRIC_DPS_TTM = "$DPS_TTM_LAST_REAL"          # 最近一年每股分红总额(元)
METRIC_EPS_TTM = "$EPS_NPTS_TTM_LAST"          # 归母每股收益 TTM(元)
METRIC_YIELD_PCT_10Y = "$PCT_BONUS_RATE_TTM_10Y_LAST"  # 股息率 10 年分位
METRIC_YIELD_5Y_AVG = "$BONUS_RATE_5Y_AVG_LAST"        # 近 5 年股息率均值

#: 派息率分档阈值（小数口径）
PAYOUT_HEALTHY = (0.30, 0.70)
PAYOUT_OVER = 1.0
PAYOUT_LOW = 0.20

#: 低于此标的数时，集中度指标恒等于 100%，不具参考意义，不产生预警
CR3_MIN_POSITIONS = 4

#: 连续分红达到此年数视为「派息底盘稳」
STABLE_YEARS = 5

#: 单次请求允许的最大标的数（保护额度）
MAX_POSITIONS = 30


class Fetcher(Protocol):
    """取数协议。实现方负责把 finpipe 的原始响应归一成本文件约定的形状。"""

    def prices(self, codes: Sequence[str]) -> dict[str, float | None]:
        """一次拿全部现价（元）。缺失的代码对应 None。"""

    def dividend_snapshot(self, codes: Sequence[str]) -> dict[str, dict[str, float | None]]:
        """一次拿全部 {code: {"yield_ttm": 小数, "payout_ttm": 小数}}。"""

    def metric(self, code: str, metric_code: str) -> float | None:
        """取单个指标，失败返回 None。"""

    def dividend_rows(self, code: str, limit: int = 50) -> list[dict[str, Any]]:
        """分红历史行，至少含 sas / dps 字段。"""

    def dividend_rows_many(self, codes: Sequence[str],
                           limit: int = 20) -> dict[str, list[dict[str, Any]]]:
        """一次取多票分红历史（日历用；缺失的代码对应空列表）。"""

    def high_yield_symbols(self, market: str = "cn",
                           limit: int = 120) -> list[dict[str, Any]]:
        """高股息池（无持仓日历兜底）；取不到返回空列表。"""

    def metrics(self, code: str, metric_codes: Sequence[str]) -> dict[str, float | None]:
        """一次取多个指标；缺失的代码对应 None。"""

    def fx_to_cny(self, currency: str) -> float | None:
        """报价币种→CNY 汇率；CNY 恒为 1，取不到返回 None。"""


# ---------------------------------------------------------------- 数据结构


@dataclass
class Position:
    """用户输入的一行持仓。"""

    code: str
    shares: int
    cost: float | None = None      # 成本价（报价币种/股），可空
    name: str | None = None        # 可空，缺省显示代码
    market: str = "cn"             # cn | hk | us
    buy_date: str | None = None    # 买入日 YYYY-MM-DD（红利税估算用）
    tax_rate: float | None = None  # 手动税率覆盖（小数），None=按规则

    def inferred_market(self) -> str:
        """推断市场：显式 market 优先；hk./.hk 或 5 位纯数字视为港股。

        A 股代码恒为 6 位，港股恒为 5 位，所以 5 位数字可以安全地判为港股。
        """
        market = (self.market or "").strip().lower()
        code = str(self.code).strip()
        low = code.lower()
        if low.startswith("hk.") or low.endswith(".hk"):
            return "hk"
        if market in ("hk", "us"):
            return market
        digits = "".join(ch for ch in code if ch.isdigit())
        if len(digits) == 5 and not low.startswith(("sh.", "sz.", "bj.", "cn.")):
            return "hk"
        return "cn"

    def normalized_code(self) -> str:
        """计算层/取数层用的代码。

        A 股裸 6 位；港股 hk.00700（5 位补零）；美股 us.ADBE。
        FinpipeFetcher 会按前缀路由，并对港股再剥成裸码 + market=hk。
        """
        market = self.inferred_market()
        code = str(self.code).strip()
        if market == "hk":
            digits = "".join(ch for ch in code if ch.isdigit())
            return "hk." + (digits[-5:].zfill(5) if digits else code)
        if market == "us":
            bare = code.replace(":", ".").split(".")[-1].upper()
            return "us." + bare
        digits = "".join(ch for ch in code if ch.isdigit())
        return digits[-6:] if len(digits) >= 6 else code.strip()


@dataclass
class Row:
    """单票取数 + 计算结果。"""

    code: str
    name: str
    shares: int
    cost: float | None
    price: float | None
    market: str = "cn"                  # cn | hk | us
    currency: str = "CNY"               # 报价币种：价格/市值/股息/成本/浮盈
    fin_currency: str = "CNY"           # 财报币种：EPS/利润（港股平台统一为 CNY）
    fx_to_cny: float | None = 1.0       # 报价币种→CNY；缺失时该票不进组合合计
    price_estimated: bool = False       # 现价缺失、用成本估算
    market_value: float | None = None   # 市值（原币）
    market_value_cny: float | None = None
    weight: float | None = None         # 组合占比（小数，按 CNY 市值）
    eps_ttm: float | None = None        # 每股利润 TTM（财报币种）
    dps_ttm: float | None = None        # 每股股息 TTM（报价币种）
    div_yield: float | None = None      # 股息率（小数）
    payout: float | None = None         # 派息率（小数）
    yield_pct_10y: float | None = None  # 股息率 10 年分位（小数）
    annual_dividend: float | None = None       # 该票年股息（原币）
    annual_dividend_cny: float | None = None   # 折 CNY
    total_profit: float | None = None          # 归母利润（财报币种；平台港股为 CNY）
    pnl: float | None = None                   # 浮盈（原币）
    pnl_cny: float | None = None               # 浮盈（CNY）
    pnl_ratio: float | None = None             # 浮盈比例（小数）
    cost_basis_cny: float | None = None        # 持仓成本（CNY）
    cost_yield: float | None = None            # 成本股息率 = dps_ttm / cost
    consecutive_years: int | None = None       # 连续分红年数（deep 模式）
    missing: list[str] = field(default_factory=list)        # 全部缺失字段
    missing_core: list[str] = field(default_factory=list)   # 核心字段缺失（计入完整度）


@dataclass
class Stability:
    """组合稳定性看板 —— 本工具相对市面记账小程序的核心增量。"""

    cr3: float | None = None                    # 前三大派息票股息占比
    cr3_codes: list[str] = field(default_factory=list)
    stable_years_cover: float | None = None     # 连续≥5 年的票的市值占比
    payout_buckets: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class PortfolioResult:
    rows: list[Row]
    total_market_value: float | None
    total_cost: float | None
    total_profit: float | None        # 「总利润」
    total_dividend: float | None      # 「总股息」
    portfolio_yield: float | None     # 组合股息率（市值加权，非算术平均）
    portfolio_cost_yield: float | None  # 组合成本股息率 = 总年息 / 总成本
    portfolio_pnl: float | None
    portfolio_pnl_ratio: float | None
    stability: Stability
    completeness: str                 # 形如 "19/20"
    generated_at: str
    total_currency: str = "CNY"       # 汇总币种（组合合计统一折 CNY）
    fx_note: str | None = None        # 汇率说明（有港股时才出现）
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- 算法


def consecutive_years(rows: Sequence[dict[str, Any]]) -> int:
    """从分红历史行倒推连续分红年数。

    目录里没有「连续分红年数」现成指标（离线检索「连续」命中 0），
    必须本地按 `sas`（报告期，形如 2025-12-31）年度去重后倒推。

    >>> consecutive_years([{"sas": "2025-06-30"}, {"sas": "2024-06-30"}])
    2
    >>> consecutive_years([{"sas": "2025-06-30"}, {"sas": "2022-06-30"}])
    1
    >>> consecutive_years([])
    0
    """
    years = sorted(
        {int(r["sas"][:4]) for r in rows if r.get("sas") and str(r["sas"])[:4].isdigit()},
        reverse=True,
    )
    if not years:
        return 0
    count, current = 1, years[0]
    for year in years[1:]:
        if year == current - 1:
            count += 1
            current = year
        else:
            break
    return count


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or not denominator:
        return None
    return numerator / denominator


def analyze(
    positions: Sequence[Position],
    fetcher: Fetcher,
    deep: bool = False,
) -> PortfolioResult:
    """主入口：取数 → 逐票计算 → 组合汇总 → 稳定性看板。

    币种纪律：逐行金额保留报价币种（A 股 CNY、港股 HKD），组合合计统一
    折算为 CNY；取不到汇率时该票不进合计并显式提示，绝不混币相加。
    """
    notes: list[str] = []
    if not positions:
        return PortfolioResult(
            rows=[], total_market_value=None, total_cost=None, total_profit=None,
            total_dividend=None, portfolio_yield=None, portfolio_pnl=None,
            portfolio_cost_yield=None,
            portfolio_pnl_ratio=None, stability=Stability(), completeness="0/0",
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
            notes=["没有输入任何持仓"],
        )

    codes = [p.normalized_code() for p in positions]

    # --- 批量取数（各 1 次请求）---
    price_map = _guard(fetcher.prices, codes, {}, notes, "现价")
    snap_map = _guard(fetcher.dividend_snapshot, codes, {}, notes, "股息快照")

    rows: list[Row] = []
    for pos, code in zip(positions, codes):
        market = pos.inferred_market()
        row = Row(
            code=code,
            name=pos.name or code,
            shares=pos.shares,
            cost=pos.cost,
            price=price_map.get(code),
            market=market,
            currency="HKD" if market == "hk" else "CNY",
            fin_currency="CNY",  # 数据源港股财报在平台已统一折算为 CNY
        )
        if row.currency == "CNY":
            row.fx_to_cny = 1.0
        else:
            row.fx_to_cny = _fx_to_cny(fetcher, row.currency)
            if row.fx_to_cny is None:
                row.missing.append("汇率")

        snap = snap_map.get(code) or {}
        row.div_yield = snap.get("yield_ttm")
        row.payout = snap.get("payout_ttm")

        metric_codes = [METRIC_DPS_TTM, METRIC_EPS_TTM]
        labels = {METRIC_DPS_TTM: "每股股息", METRIC_EPS_TTM: "每股利润"}
        if deep:
            metric_codes.append(METRIC_YIELD_PCT_10Y)
            labels[METRIC_YIELD_PCT_10Y] = "股息率分位"
        values = _guard_metrics(
            fetcher, code, metric_codes, row, labels,
            core={METRIC_DPS_TTM, METRIC_EPS_TTM},
        )
        row.dps_ttm = values.get(METRIC_DPS_TTM)
        row.eps_ttm = values.get(METRIC_EPS_TTM)

        if deep:
            row.yield_pct_10y = values.get(METRIC_YIELD_PCT_10Y)
            hist = _guard_one(fetcher.dividend_rows, code, 50, row, "分红历史") or []
            row.consecutive_years = consecutive_years(hist) if hist else None

        # --- 价格缺失降级：用成本估算，并显式标注 ---
        if row.price is None and row.cost is not None:
            row.price = row.cost
            row.price_estimated = True
            row.missing.append("现价(用成本估算)")
            row.missing_core.append("现价")

        # --- 派生计算（原币）---
        if row.price is not None:
            row.market_value = row.shares * row.price
        if row.dps_ttm is not None:
            row.annual_dividend = row.shares * row.dps_ttm
        if row.eps_ttm is not None:
            row.total_profit = row.shares * row.eps_ttm   # 财报币种（港股为 CNY）
        if row.cost is not None and row.price is not None:
            row.pnl = (row.price - row.cost) * row.shares
            row.pnl_ratio = _safe_div(row.price - row.cost, row.cost)
        # 成本股息率：攒股收息党的"我的收益率"——分红相对我的成本，与市价无关
        if row.dps_ttm is not None and row.cost:
            row.cost_yield = _safe_div(row.dps_ttm, row.cost)

        # --- 折算 CNY（组合合计用）---
        fx = row.fx_to_cny
        row.market_value_cny = _mul(row.market_value, fx)
        row.annual_dividend_cny = _mul(row.annual_dividend, fx)
        row.pnl_cny = _mul(row.pnl, fx)
        cost_basis = row.cost * row.shares if row.cost is not None else None
        row.cost_basis_cny = _mul(cost_basis, fx)

        rows.append(row)

    # --- 组合汇总（CNY）---
    total_mv = _sum(r.market_value_cny for r in rows)
    total_cost = _sum(r.cost_basis_cny for r in rows)
    total_div = _sum(r.annual_dividend_cny for r in rows)
    total_profit = _sum(r.total_profit for r in rows)

    for row in rows:
        row.weight = _safe_div(row.market_value_cny, total_mv)

    # 配对口径：分子分母必须来自同一批标的，缺价/缺成本的票不能只进分子
    mv_pairs = [
        (r.market_value_cny, r.annual_dividend_cny)
        for r in rows
        if r.market_value_cny is not None and r.annual_dividend_cny is not None
    ]
    portfolio_yield = _safe_div(
        sum(d for _, d in mv_pairs), sum(m for m, _ in mv_pairs)
    ) if mv_pairs else None

    cost_pairs = [
        (r.cost_basis_cny, r.annual_dividend_cny)
        for r in rows
        if r.cost_basis_cny is not None and r.annual_dividend_cny is not None
    ]
    portfolio_cost_yield = _safe_div(
        sum(d for _, d in cost_pairs), sum(c for c, _ in cost_pairs)
    ) if cost_pairs else None

    pnl_values = [r.pnl_cny for r in rows if r.pnl_cny is not None]
    portfolio_pnl = sum(pnl_values) if pnl_values else None
    portfolio_pnl_ratio = _safe_div(portfolio_pnl, total_cost)

    # --- 汇率与口径说明 ---
    fx_rows = [r for r in rows if r.currency != "CNY"]
    fx_note = None
    if fx_rows:
        rates = {r.currency: r.fx_to_cny for r in fx_rows if r.fx_to_cny is not None}
        if rates:
            rate_txt = "；".join(f"{ccy}→CNY {rate:.4f}" for ccy, rate in rates.items())
            fx_note = f"组合汇总按 {rate_txt} 折算；港股逐行金额为原币"
        else:
            fx_note = "未取到 HKD→CNY 汇率：港股不参与组合合计，逐行仍按 HKD 显示"
        notes.append(fx_note)
        missing_fx = [r.code for r in fx_rows if r.fx_to_cny is None]
        if missing_fx:
            notes.append(f"以下标的未取到汇率，未计入组合合计：{'、'.join(missing_fx)}")
        notes.append(
            "港股口径：价格/股息为 HKD，每股利润为财报币种（平台统一为 CNY）；"
            "股息率与派息率采用平台快照口径"
        )

    if total_mv is not None and any(r.market_value_cny is None for r in rows):
        notes.append("部分标的缺现价，组合占比与股息率按有价标的计算")
    if any(r.cost is None for r in rows):
        notes.append("部分标的未填成本，成本股息率与浮动盈亏只汇总有成本的标的")

    # --- 稳定性看板 ---
    stability = _build_stability(rows, total_div, total_mv, deep)

    # 完整度按「核心字段」统计：深度字段缺失不该把核心数据判成不完整
    complete = sum(1 for r in rows if not r.missing_core)
    return PortfolioResult(
        rows=rows,
        total_market_value=total_mv,
        total_cost=total_cost,
        total_profit=total_profit,
        total_dividend=total_div,
        portfolio_yield=portfolio_yield,
        portfolio_cost_yield=portfolio_cost_yield,
        portfolio_pnl=portfolio_pnl,
        portfolio_pnl_ratio=portfolio_pnl_ratio,
        stability=stability,
        completeness=f"{complete}/{len(rows)}",
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        total_currency="CNY",
        fx_note=fx_note,
        notes=notes,
    )


def _build_stability(
    rows: list[Row], total_div: float | None, total_mv: float | None, deep: bool
) -> Stability:
    st = Stability()

    # 股息集中度 CR3（按 CNY 年息，避免 HKD/CNY 混算）
    ranked = sorted(
        (r for r in rows if r.annual_dividend_cny is not None),
        key=lambda r: r.annual_dividend_cny or 0,
        reverse=True,
    )
    if ranked and total_div:
        top3 = ranked[:3]
        st.cr3 = sum(r.annual_dividend_cny or 0 for r in top3) / total_div
        st.cr3_codes = [r.name for r in top3]

    # 派息率分档：70%-100% 是「高但未超额」，值得单独看，不混进"其他"
    buckets = {
        "超额(>100%)": 0, "偏高(70%-100%)": 0, "健康(30%-70%)": 0,
        "偏低(20%-30%)": 0, "保守(<20%)": 0,
    }
    for r in rows:
        if r.payout is None:
            continue
        if r.payout > PAYOUT_OVER:
            buckets["超额(>100%)"] += 1
        elif r.payout > PAYOUT_HEALTHY[1]:
            buckets["偏高(70%-100%)"] += 1
        elif r.payout >= PAYOUT_HEALTHY[0]:
            buckets["健康(30%-70%)"] += 1
        elif r.payout >= PAYOUT_LOW:
            buckets["偏低(20%-30%)"] += 1
        else:
            buckets["保守(<20%)"] += 1
    st.payout_buckets = {k: v for k, v in buckets.items() if v}

    # 连续分红覆盖（仅 deep，按 CNY 市值）
    if deep and total_mv:
        stable_mv = sum(
            r.market_value_cny or 0
            for r in rows
            if (r.consecutive_years or 0) >= STABLE_YEARS
        )
        st.stable_years_cover = stable_mv / total_mv

    # 预警（描述性，不给操作指令）
    if st.cr3 is not None:
        if len(ranked) < CR3_MIN_POSITIONS:
            st.warnings.append(
                f"仅 {len(ranked)} 只有派息数据的标的，集中度 CR3 参考意义有限"
            )
        elif st.cr3 > 0.6:
            st.warnings.append(
                f"股息集中度 CR3={st.cr3:.0%}，前三大派息来源为 "
                f"{'、'.join(st.cr3_codes)}"
            )
    over = [r.name for r in rows if r.payout is not None and r.payout > PAYOUT_OVER]
    if over:
        st.warnings.append(f"派息率超过 100% 的标的：{'、'.join(over)}")
    missing_yield = [r.name for r in rows if r.div_yield is None]
    if missing_yield:
        st.warnings.append(f"以下标的未取到股息率：{'、'.join(missing_yield)}")

    return st


# ---------------------------------------------------------------- 小工具


def _sum(values: Any) -> float | None:
    """只对非 None 求和；全空返回 None（而不是 0，避免失真）。"""
    vals = [v for v in values if v is not None]
    return sum(vals) if vals else None


def _guard(fn: Any, arg: Any, fallback: Any, notes: list[str], label: str) -> Any:
    """批量取数失败时降级，但必须显式告知用户。"""
    try:
        result = fn(arg)
        return result if result is not None else fallback
    except Exception as exc:  # noqa: BLE001 - 取数层异常一律降级
        notes.append(f"{label}批量取数失败：{type(exc).__name__}: {exc}")
        return fallback


def _guard_one(fn: Any, code: str, arg: Any, row: Row, label: str,
               core: bool = False) -> Any:
    """单票取数：抛异常 **或返回 None** 都记入 row.missing。

    只把"取不到"和"真的是 0"区分开，用户才能判断那个 `—` 是数据缺失
    还是客观为零——这是本工具的信用底线。

    `core=True` 的字段（现价 / 每股股息 / 每股利润）额外计入 `missing_core`，
    只有它们决定「数据完整度」，避免深度字段拖低核心口径。
    """
    try:
        value = fn(code, arg)
    except Exception:  # noqa: BLE001
        row.missing.append(label)
        if core:
            row.missing_core.append(label)
        return None
    if value is None:
        row.missing.append(label)
        if core:
            row.missing_core.append(label)
    return value


def _mul(value: float | None, factor: float | None) -> float | None:
    """乘汇率；任一为空则返回 None（不把缺失当 0）。"""
    if value is None or factor is None:
        return None
    return value * factor


def _fx_to_cny(fetcher: Any, currency: str) -> float | None:
    """取报价币种→CNY 汇率；CNY 恒为 1，其他币种缺失返回 None。"""
    if (currency or "").upper() == "CNY":
        return 1.0
    fn = getattr(fetcher, "fx_to_cny", None)
    if fn is None:
        return None
    try:
        return fn(currency)
    except Exception:  # noqa: BLE001 - 汇率失败只影响折算
        return None


def _guard_metrics(
    fetcher: Any,
    code: str,
    metric_codes: Sequence[str],
    row: Row,
    labels: dict[str, str],
    core: set[str],
) -> dict[str, float | None]:
    """批量取指标；批量失败或某项为空时退回单指标，并显式记录缺失。

    指标层是港股数据的关键路径：CN client + hk.00700 会 500/None，
    所以这里既负责降级，也负责把"取不到"和"真的是 0"分开。
    """
    values: dict[str, float | None] = {}
    batch = getattr(fetcher, "metrics", None)
    if batch is not None:
        try:
            got = batch(code, list(metric_codes)) or {}
            if isinstance(got, dict):
                values = {c: got.get(c) for c in metric_codes}
        except Exception:  # noqa: BLE001 - 批量失败 → 逐项回退
            values = {}

    single = getattr(fetcher, "metric", None)
    for metric_code in metric_codes:
        if values.get(metric_code) is not None:
            continue
        if single is None:
            values[metric_code] = None
            continue
        try:
            values[metric_code] = single(code, metric_code)
        except Exception:  # noqa: BLE001
            values[metric_code] = None

    for metric_code in metric_codes:
        if values.get(metric_code) is None:
            label = labels.get(metric_code, metric_code)
            row.missing.append(label)
            if metric_code in core:
                row.missing_core.append(label)
    return values
