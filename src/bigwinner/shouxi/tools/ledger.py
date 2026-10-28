"""分红记账：把"我该收到多少钱"算清楚（含红利税），并与历史除权对账。

税规则：
- A 股（个人投资者，差别化红利税）按**买入日→除权日**的持有时长估算：
    ≤1 个月        20%
    1 个月 ~ 1 年  10%
    >1 年          0%（现行政策暂免）
  实际在卖出时补缴/免征，本工具给的是估算值。
- 港股：港股通/H 股默认按 20% 预扣；本地券商、红筹等口径可能不同，
  可在页面上按单票/年度/统一税率覆盖。港股不套用 A 股持有期分档。
- 未填买入日：按 20% 保守估算，并标记 estimated。
- 买入日之前的除权记录不会计入（那时还没持股）。

数据来源：wmshare `bonus.query_list`（ex_date/pay_date/dps 真实披露值）。
用户只输入：代码 + 股数 + （可选）买入日期/税率。不做任何猜测填充。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

#: A 股差别化红利税档位（小数口径）
TAX_SHORT = 0.20
TAX_MID = 0.10
TAX_LONG = 0.0
#: 港股通/H 股默认预扣率；不是持有期分档
HK_DEFAULT_TAX = 0.20

#: 允许的计税方式
TAX_MODES = ("auto", "flat", "by_year")


def _parse_day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        text = str(value).strip()[:10].replace("/", "-")
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_rate(value: Any) -> float | None:
    """税率归一：接受小数或百分数；非法/空返回 None。"""
    if value is None or value == "":
        return None
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return None
    if rate > 1:
        rate /= 100.0
    return max(0.0, min(1.0, rate))


def _market_of(item: dict[str, Any]) -> str:
    market = str(item.get("market") or "").strip().lower()
    code = str(item.get("code") or "").strip()
    low = code.lower()
    # 代码形态优先：避免历史档案里 market 标错时把港股当 A 股
    if low.startswith(("hk.", "hk:")) or low.endswith(".hk"):
        return "hk"
    digits = "".join(ch for ch in code if ch.isdigit())
    if len(digits) == 5:
        return "hk"
    if market in ("cn", "hk", "us"):
        return market
    return "cn"


def _row_status(row: dict[str, Any]) -> str:
    status = row.get("status") or row.get("状态")
    if status:
        return str(status)
    props = row.get("props") or row.get("Props")
    if isinstance(props, dict):
        return str(props.get("状态") or "")
    return ""


def dividend_tax_ratio(buy: date | None, ex_day: date) -> float:
    """A 股按持有时长返回估算税率（0/0.1/0.2）；buy 缺失按 20% 保守估。"""
    if buy is None:
        return TAX_SHORT
    days = (ex_day - buy).days
    if days <= 30:
        return TAX_SHORT
    if days <= 365:
        return TAX_MID
    return TAX_LONG


def _resolve_tax(
    pos_rate: float | None,
    mode: str,
    flat_rate: float | None,
    year_rates: dict[str, float | None],
    market: str,
    buy: date | None,
    ex_day: date,
) -> tuple[float, str]:
    """税源优先级：单票覆盖 > 年度覆盖 > 统一税率 > 自动规则。"""
    if pos_rate is not None:
        return pos_rate, "position"
    if mode == "flat" and flat_rate is not None:
        return flat_rate, "flat"
    if mode == "by_year":
        rate = year_rates.get(str(ex_day.year))
        if rate is not None:
            return rate, "year"
    if market == "hk":
        return HK_DEFAULT_TAX, "hk_default"
    if buy is None:
        return TAX_SHORT, "fallback"
    return dividend_tax_ratio(buy, ex_day), "auto"


def resolve_tax_ratio(
    market: str,
    buy: date | None,
    ex_day: date,
    *,
    pos_rate: float | None = None,
    mode: str = "auto",
    flat_rate: float | None = None,
    year_rates: dict[str, float | None] | None = None,
) -> tuple[float, str]:
    """公开的税率决策入口（日历/试算复用，口径与账本完全一致）。"""
    return _resolve_tax(pos_rate, mode, flat_rate, year_rates or {},
                        market, buy, ex_day)


def parse_day(value: Any) -> date | None:
    """公开日期解析（支持 2026/05/20、ISO 时间、2099 占位由调用方过滤）。"""
    return _parse_day(value)


def parse_rate(value: Any) -> float | None:
    """公开税率解析（小数或百分数）。"""
    return _parse_rate(value)


def _sum_optional(values: list[float]) -> float:
    return round(sum(values), 2)


def build_ledger(
    positions: list[dict[str, Any]],
    rows_by_code: dict[str, list[dict[str, Any]]],
    year: int | None = None,
    tax: dict[str, Any] | None = None,
    fx: dict[str, float | None] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """按年度汇总每票的"应收股息"。

    positions: [{code, shares, market?, buy_date?, tax_rate?, name?}]
    rows_by_code: wmshare dividend.history 的原始行（已归一 sas 别名亦可）
    year: 只看该除权年份；None = 全部历史
    tax: {mode: auto|flat|by_year, flat_rate, year_rates: {年份: 税率}}
    fx: {币种: 兑 CNY 汇率}；CNY 恒为 1
    today: 账本只统计已除权记录（未来预案不计入），默认今天
    """
    ref = today or date.today()
    tax_opts = tax or {}
    mode = str(tax_opts.get("mode") or "auto").strip().lower()
    if mode not in TAX_MODES:
        mode = "auto"
    flat_rate = _parse_rate(tax_opts.get("flat_rate"))
    year_rates = {
        str(k): _parse_rate(v)
        for k, v in (tax_opts.get("year_rates") or {}).items()
    }
    fx = fx or {"CNY": 1.0}

    per_stock: list[dict[str, Any]] = []
    available_years: set[int] = set()
    skipped_before_buy = 0
    fx_missing_codes: list[str] = []
    year_buckets: dict[int, dict[str, float | int]] = {}

    total_gross_cny = 0.0
    total_tax_cny = 0.0
    total_net_cny = 0.0
    total_events = 0
    cny_events = 0

    for pos in positions:
        code = str(pos.get("code", "")).strip()
        try:
            shares = int(float(pos.get("shares") or 0))
        except (TypeError, ValueError):
            continue
        if not code or shares <= 0:
            continue

        market = _market_of(pos)
        currency = "HKD" if market == "hk" else "CNY"
        fx_rate = 1.0 if currency == "CNY" else (fx or {}).get(currency)
        buy = _parse_day(pos.get("buy_date"))
        pos_rate = _parse_rate(pos.get("tax_rate"))

        rows = rows_by_code.get(code)
        if rows is None:
            # 兼容入参是裸码/带前缀两种写法
            digits = "".join(ch for ch in code if ch.isdigit())
            variants = [digits, digits.zfill(5), f"hk.{digits.zfill(5)}"]
            for variant in variants:
                if variant in rows_by_code:
                    rows = rows_by_code[variant]
                    break
        rows = rows or []

        events: list[dict[str, Any]] = []
        gross_native = tax_native = net_native = 0.0
        gross_cny = tax_cny_val = net_cny_val = 0.0
        has_cny = False

        for row in rows:
            ex_day = _parse_day(row.get("ex_date") or row.get("ex_div"))
            dps = row.get("dps")
            if not ex_day or dps is None:
                continue
            # 历史账本只统计已除权记录；未来预案不算"这些年分到多少钱"
            if ex_day > ref:
                continue
            status = _row_status(row)
            if any(word in status for word in ("取消", "否决", "不分配", "终止")):
                continue
            if buy is not None and ex_day < buy:
                skipped_before_buy += 1
                continue
            available_years.add(ex_day.year)
            if year is not None and ex_day.year != year:
                continue

            ratio, source = _resolve_tax(
                pos_rate, mode, flat_rate, year_rates, market, buy, ex_day)
            g = shares * float(dps)
            t = g * ratio
            n = g - t
            holding_days = (ex_day - buy).days if buy is not None else None

            g_cny = g * fx_rate if fx_rate is not None else None
            t_cny = t * fx_rate if fx_rate is not None else None
            n_cny = n * fx_rate if fx_rate is not None else None
            if n_cny is not None:
                has_cny = True
                cny_events += 1
            total_events += 1

            events.append({
                "ex_date": ex_day.isoformat(),
                "sas": row.get("sas", ""),
                "dps": float(dps),
                "gross": round(g, 2),
                "tax_ratio": ratio,
                "tax": round(t, 2),
                "net": round(n, 2),
                "currency": currency,
                "fx_to_cny": fx_rate,
                "gross_cny": round(g_cny, 2) if g_cny is not None else None,
                "tax_cny": round(t_cny, 2) if t_cny is not None else None,
                "net_cny": round(n_cny, 2) if n_cny is not None else None,
                "holding_days": holding_days,
                "tax_source": source,
                "estimated": source in ("fallback", "hk_default"),
            })
            gross_native += g
            tax_native += t
            net_native += n
            if g_cny is not None:
                gross_cny += g_cny
                tax_cny_val += t_cny or 0.0
                net_cny_val += n_cny or 0.0
                bucket = year_buckets.setdefault(
                    ex_day.year, {"gross": 0.0, "tax": 0.0, "net": 0.0, "events": 0})
                bucket["gross"] += g_cny
                bucket["tax"] += t_cny or 0.0
                bucket["net"] += n_cny or 0.0
                bucket["events"] += 1

        if events and not has_cny:
            fx_missing_codes.append(code)

        events.sort(key=lambda e: e["ex_date"], reverse=True)
        per_stock.append({
            "code": code,
            "name": pos.get("name") or code,
            "market": market,
            "currency": currency,
            "fx_to_cny": fx_rate,
            "shares": shares,
            "buy_date": buy.isoformat() if buy else None,
            "events": events,
            "gross": round(gross_native, 2),
            "tax": round(tax_native, 2),
            "net": round(net_native, 2),
            "gross_cny": round(gross_cny, 2) if has_cny else None,
            "tax_cny": round(tax_cny_val, 2) if has_cny else None,
            "net_cny": round(net_cny_val, 2) if has_cny else None,
        })
        if has_cny:
            total_gross_cny += gross_cny
            total_tax_cny += tax_cny_val
            total_net_cny += net_cny_val

    per_stock.sort(
        key=lambda s: s["net_cny"] if s["net_cny"] is not None else s["net"],
        reverse=True,
    )

    by_year = [
        {
            "year": y,
            "gross": round(b["gross"], 2),
            "tax": round(b["tax"], 2),
            "net": round(b["net"], 2),
            "tax_ratio": (b["tax"] / b["gross"]) if b["gross"] else None,
            "events": int(b["events"]),
        }
        for y, b in sorted(year_buckets.items(), reverse=True)
    ]

    notes = [
        "税额为估算：A 股按买入日到除权日的持有时长（≤1月 20%、1月–1年 10%、"
        ">1年 0%）；港股默认 20%（港股通/H 股口径，可覆盖）；"
        "未填买入日按 20% 保守估算；实际以券商扣税为准。",
    ]
    if skipped_before_buy:
        notes.append(f"买入日之前的 {skipped_before_buy} 笔除权记录已忽略（当时尚未持股）。")
    if any(s["market"] == "hk" for s in per_stock):
        hk_rate = fx.get("HKD") if fx else None
        if hk_rate:
            notes.append(f"港股金额按 HKD→CNY {hk_rate:.4f} 折算为合计；逐票明细仍为 HKD。")
        else:
            notes.append("未取到 HKD→CNY 汇率：港股未计入 CNY 合计，逐票明细仍为 HKD。")
    if fx_missing_codes:
        notes.append(f"以下标的缺汇率，未计入 CNY 合计：{'、'.join(fx_missing_codes)}")

    # 没有任何事件 → 0 是客观的；有事件但全缺汇率 → None（不能把缺失当 0）
    if total_events == 0:
        totals = (0.0, 0.0, 0.0)
    elif cny_events == 0:
        totals = (None, None, None)
    else:
        totals = (
            _sum_optional([total_gross_cny]),
            _sum_optional([total_tax_cny]),
            _sum_optional([total_net_cny]),
        )

    return {
        "year": year,
        "stocks": per_stock,
        "total_gross": totals[0],
        "total_tax": totals[1],
        "total_net": totals[2],
        "total_currency": "CNY",
        "by_year": by_year,
        "available_years": sorted(available_years, reverse=True),
        "skipped_before_buy": skipped_before_buy,
        "fx_hkd_cny": (fx or {}).get("HKD"),
        "tax": {
            "mode": mode,
            "flat_rate": flat_rate,
            "year_rates": year_rates,
        },
        "note": " ".join(notes),
    }
