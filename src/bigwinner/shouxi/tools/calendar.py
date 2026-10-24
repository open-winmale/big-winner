"""分红日历：把「已公告/待实施」的分红事件整理成未来现金流。

数据来源是分红库原始行（含 `状态/分红类型/股权登记日/除权除息日/分红到账日`）。
计算层只做解析、过滤、税后估算与汇总，不依赖 HTTP / finpipe，可离线单测。

口径：
- 事件按「到账日 → 除权日 → 公告日」的现金时间排序；
- 预案/待定事件单独标注，不计入「今年已收」；
- A 股税按买入日→除权日估；港股默认 20%；与账本同一套优先级；
- 组合汇总折 CNY；逐行保留原币。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable

from bigwinner.shouxi.tools.ledger import parse_day, parse_rate, resolve_tax_ratio

#: 数据源占位日期（预案尚未确定除权日）
PLACEHOLDER_YEAR = 2099
#: 视为取消的状态关键词
CANCELLED_WORDS = ("取消", "否决", "不分配", "终止")
#: 最近已到账仍展示的天数
RECENT_PAID_DAYS = 45
#: 方案状态关键词
PLAN_WORDS = ("预案", "实施", "已执行", "已实施", "股东大会")


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _props(row: Any) -> dict[str, Any]:
    """取原始 store 行的 props；已是扁平行的直接返回自身。"""
    if not isinstance(row, dict):
        return {}
    props = row.get("props") or row.get("Props")
    if isinstance(props, dict) and props:
        return props
    return row


def _pick(row: Any, props: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in props and props[key] not in (None, ""):
            return props[key]
        if isinstance(row, dict) and key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _day(value: Any) -> date | None:
    day = parse_day(value)
    if day is None or day.year >= PLACEHOLDER_YEAR:
        return None
    return day


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _norm_ccy(value: Any, fallback: str) -> str:
    text = _text(value).upper()
    return {
        "港币": "HKD", "人民币": "CNY", "美元": "USD",
        "HKD": "HKD", "CNY": "CNY", "USD": "USD",
    }.get(text, fallback)


def _cancelled(status: str) -> bool:
    return any(word in status for word in CANCELLED_WORDS)


def _sas(row: Any, props: dict[str, Any]) -> str:
    direct = _text((row or {}).get("sas") if isinstance(row, dict) else "")
    if direct:
        return direct
    annual = (row or {}).get("annual") if isinstance(row, dict) else None
    sampling = (row or {}).get("sampling") if isinstance(row, dict) else None
    if annual and sampling:
        return f"{annual}:{sampling}"
    return _text(_pick(row, props, ("财报时间", "fin_time", "period")))


def _stage(ex: date | None, pay: date | None, status: str, today: date) -> str:
    if ex and ex > today:
        return "待除权"
    if ex and ex <= today and (pay is None or pay > today):
        return "已除权待到账"
    if pay and pay <= today:
        return "已到账"
    if not ex and any(word in status for word in PLAN_WORDS):
        return "预案待定" if "预案" in status else "待定"
    return "待定"


def _parse_event(
    row: Any,
    position: dict[str, Any],
    today: date,
    tax_mode: str,
    flat_rate: float | None,
    year_rates: dict[str, float | None],
    fx: dict[str, float | None],
) -> dict[str, Any] | None:
    props = _props(row)
    dps = _num(_pick(row, props, ("分红", "dps")))
    if dps is None or dps <= 0:
        return None

    ex = _day(_pick(row, props, ("除权除息日", "ex_div", "ex_date")))
    pay = _day(_pick(row, props, ("分红到账日", "pay", "pay_date")))
    record = _day(_pick(row, props, ("股权登记日", "record_date", "record")))
    announce = _day(_pick(row, props, ("公告日期", "announce", "announce_date")))
    status = _text(_pick(row, props, ("状态", "status")))
    kind = _text(_pick(row, props, ("分红类型", "kind")))
    content = _text(_pick(row, props, ("内容", "content")))
    if _cancelled(status):
        return None

    market = _text(position.get("market")) or "cn"
    currency = _norm_ccy(_pick(row, props, ("货币", "ccy")),
                         "HKD" if market == "hk" else "CNY")
    buy = parse_day(position.get("buy_date"))
    shares = int(position.get("shares") or 0)
    # 买入日之前已除权的分红，不是我的现金
    if buy is not None and ex is not None and ex < buy:
        return None

    cash_date = pay or ex or announce or today
    tax_ratio: float | None = None
    tax_source = ""
    gross = net = gross_cny = net_cny = None
    if shares > 0:
        ex_for_tax = ex or today
        tax_ratio, tax_source = resolve_tax_ratio(
            market, buy, ex_for_tax,
            pos_rate=parse_rate(position.get("tax_rate")),
            mode=tax_mode,
            flat_rate=flat_rate,
            year_rates=year_rates,
        )
        gross = shares * dps
        net = gross * (1 - tax_ratio)
        fx_rate = fx.get(currency)
        if fx_rate is not None:
            gross_cny = gross * fx_rate
            net_cny = net * fx_rate

    stage = _stage(ex, pay, status, today)
    estimated = (tax_source in ("fallback", "hk_default")) or ex is None
    is_plan = ex is None and pay is None
    days_to_ex = (ex - today).days if ex else None
    days_to_pay = (pay - today).days if pay else None
    days_to_cash = (cash_date - today).days if cash_date else None

    return {
        "code": _text(position.get("code")),
        "name": _text(position.get("name")) or _text(position.get("code")),
        "market": market,
        "currency": currency,
        "shares": shares,
        "dps": dps,
        "ccy": currency,
        "total": _num(_pick(row, props, ("TOTAL_DIVIDEND", "total"))),
        "yield_ttm": position.get("yield_ttm"),
        "status": status,
        "kind": kind,
        "content": content,
        "sas": _sas(row, props),
        "ex_date": ex.isoformat() if ex else None,
        "record_date": record.isoformat() if record else None,
        "pay_date": pay.isoformat() if pay else None,
        "announce_date": announce.isoformat() if announce else None,
        "cash_date": cash_date.isoformat() if cash_date else None,
        "stage": stage,
        "is_plan": is_plan,
        "days_to_ex": days_to_ex,
        "days_to_pay": days_to_pay,
        "days_to_cash": days_to_cash,
        "gross": round(gross, 2) if gross is not None else None,
        "net": round(net, 2) if net is not None else None,
        "gross_cny": round(gross_cny, 2) if gross_cny is not None else None,
        "net_cny": round(net_cny, 2) if net_cny is not None else None,
        "tax_ratio": tax_ratio,
        "tax_source": tax_source,
        "estimated": estimated,
        "fx_to_cny": fx.get(currency),
    }


def build_calendar(
    positions: list[dict[str, Any]],
    rows_by_code: dict[str, list[dict[str, Any]]],
    *,
    today: date | None = None,
    horizon_days: int = 365,
    tax: dict[str, Any] | None = None,
    fx: dict[str, float | None] | None = None,
) -> dict[str, Any]:
    """生成事件列表 + 现金流汇总。

    positions: [{code, name, market, shares, cost, buy_date, tax_rate}]
    rows_by_code: {code: 原始分红行}
    """
    ref = today or date.today()
    tax_opts = tax or {}
    tax_mode = str(tax_opts.get("mode") or "auto")
    flat_rate = parse_rate(tax_opts.get("flat_rate"))
    year_rates = {
        str(k): parse_rate(v)
        for k, v in (tax_opts.get("year_rates") or {}).items()
    }
    fx = dict(fx or {})
    fx.setdefault("CNY", 1.0)

    events: list[dict[str, Any]] = []
    seen: set[tuple[str, str, float, str]] = set()
    annual_total_cny = 0.0
    annual_with_cost_cny = 0.0
    cost_total_cny = 0.0
    received_gross_cny = 0.0
    received_net_cny = 0.0
    missing_buy = False
    missing_fx = False

    for position in positions:
        code = _text(position.get("code"))
        rows = rows_by_code.get(code) or []
        shares = int(position.get("shares") or 0)
        buy = parse_day(position.get("buy_date"))
        if shares > 0 and buy is None:
            missing_buy = True
        cost = _num(position.get("cost"))
        currency = "HKD" if _text(position.get("market")) == "hk" else "CNY"
        cost_cny: float | None = None
        if cost is not None and shares > 0:
            rate = fx.get(currency)
            if rate is not None:
                cost_cny = cost * shares * rate
        annual_native = 0.0
        annual_cny = 0.0

        for row in rows:
            event = _parse_event(row, position, ref, tax_mode, flat_rate,
                                 year_rates, fx)
            if event is None:
                continue
            key = (
                event["code"],
                event["ex_date"] or "",
                event["pay_date"] or "",
                event["dps"],
                event["sas"],
            )
            if key in seen:
                continue
            seen.add(key)

            ex = _day(event["ex_date"])
            pay = _day(event["pay_date"])
            announce = _day(event["announce_date"])
            cash = _day(event["cash_date"])

            # TTM 年息：过去 12 个月已除权的现金分红
            if shares > 0 and ex and ref - timedelta(days=365) <= ex <= ref:
                amount = shares * event["dps"]
                annual_native += amount
                fx_rate = event["fx_to_cny"]
                if fx_rate is not None:
                    annual_cny += amount * fx_rate
                else:
                    missing_fx = True

            # 今年已收：到账日优先，缺到账日用除权日
            if shares > 0:
                received_day = pay or ex
                if received_day and received_day.year == ref.year \
                        and received_day <= ref:
                    if event["gross_cny"] is None and event["gross"] is not None:
                        missing_fx = True
                    received_gross_cny += (event["gross_cny"] or 0.0)
                    received_net_cny += (event["net_cny"] or 0.0)

            # 是否进入事件列表：近期已到账、未来 horizon 内、或近期待定预案
            in_window = False
            if cash and ref - timedelta(days=RECENT_PAID_DAYS) <= cash <= ref + timedelta(days=horizon_days):
                in_window = True
            if ex and ref - timedelta(days=RECENT_PAID_DAYS) <= ex <= ref + timedelta(days=horizon_days):
                in_window = True
            plan_recent = (
                ex is None and pay is None
                and (announce is None or announce >= ref - timedelta(days=180))
                and any(word in event["status"] for word in PLAN_WORDS)
            )
            if plan_recent:
                in_window = True
            if in_window:
                events.append(event)

        if shares > 0:
            annual_total_cny += annual_cny
            if cost_cny is not None:
                annual_with_cost_cny += annual_cny
                cost_total_cny += cost_cny

    events.sort(key=lambda e: (
        e["cash_date"] or "9999-12-31",
        0 if e["stage"] != "已到账" else 1,
        e["code"],
    ))

    def _sum_window(days: int, field: str) -> float | None:
        vals = [
            e[field] for e in events
            if not e["is_plan"] and e[field] is not None
            and e["days_to_cash"] is not None
            and 0 <= e["days_to_cash"] <= days
        ]
        return round(sum(vals), 2) if vals else None

    def _sum_ex_window(days: int, field: str) -> float | None:
        vals = [
            e[field] for e in events
            if not e["is_plan"] and e[field] is not None
            and e["days_to_ex"] is not None
            and 0 <= e["days_to_ex"] <= days
        ]
        return round(sum(vals), 2) if vals else None

    def _count_window(days: int) -> int:
        return sum(
            1 for e in events
            if not e["is_plan"]
            and ((e["days_to_ex"] is not None and 0 <= e["days_to_ex"] <= days)
                 or (e["days_to_pay"] is not None and 0 <= e["days_to_pay"] <= days))
        )

    def _count_ex(days: int) -> int:
        return sum(
            1 for e in events
            if not e["is_plan"] and e["days_to_ex"] is not None
            and 1 <= e["days_to_ex"] <= days
        )

    upcoming = [
        e for e in events
        if not e["is_plan"] and e["cash_date"]
        and e["cash_date"] >= ref.isoformat()
        and e["stage"] != "已到账"
    ]
    next_event = upcoming[0] if upcoming else None
    plan_count = sum(
        1 for e in events
        if e["is_plan"] or e["stage"] in ("预案待定", "待定")
    )

    cost_yield = (annual_with_cost_cny / cost_total_cny) if cost_total_cny else None
    summary = {
        "annual_dividend": round(annual_total_cny, 2) if annual_total_cny else None,
        "annual_dividend_cny": round(annual_total_cny, 2) if annual_total_cny else None,
        "cost_yield": cost_yield,
        "received_ytd_gross": round(received_gross_cny, 2) if received_gross_cny else 0.0,
        "received_ytd_net": round(received_net_cny, 2) if received_net_cny else 0.0,
        "next_30_gross": _sum_window(30, "gross_cny"),
        "next_30_net": _sum_window(30, "net_cny"),
        "next_90_gross": _sum_window(90, "gross_cny"),
        "next_90_net": _sum_window(90, "net_cny"),
        "next_365_gross": _sum_window(365, "gross_cny"),
        "next_365_net": _sum_window(365, "net_cny"),
        "next_30_ex_gross": _sum_ex_window(30, "gross_cny"),
        "next_30_ex_net": _sum_ex_window(30, "net_cny"),
        "next_90_ex_gross": _sum_ex_window(90, "gross_cny"),
        "next_90_ex_net": _sum_ex_window(90, "net_cny"),
        "next_365_ex_gross": _sum_ex_window(365, "gross_cny"),
        "next_365_ex_net": _sum_ex_window(365, "net_cny"),
        "event_count_7": _count_window(7),
        "event_count_30": _count_window(30),
        "event_count_90": _count_window(90),
        "event_count_365": _count_window(365),
        "ex_count_7": _count_ex(7),
        "ex_count_30": _count_ex(30),
        "ex_count_90": _count_ex(90),
        "plan_count": plan_count,
        "next_event": next_event,
        "position_count": len(positions),
        "fx_hkd_cny": fx.get("HKD"),
    }

    notes = [
        "税额为估算：A 股按买入日到除权日持有时长（≤1月 20%、1月–1年 10%、"
        ">1年 0%）；港股默认 20%（港股通/H 股口径）；实际以券商结算为准。",
        "预案/待定事件不代表已确定现金，以实施公告和股权登记日为准；"
        "「今年已收」只统计已到账或已除权的记录。",
    ]
    if missing_buy:
        notes.append("部分持仓未填买入日，红利税按 20% 保守估算；可在持仓明细补买入日。")
    if missing_fx:
        notes.append("部分港股未取到 HKD→CNY 汇率，未计入 CNY 合计。")
    if any(p.get("shares", 0) == 0 for p in positions):
        notes.append("当前为观察池视图：只展示每股分红与日期，不计算个人现金。")

    return {
        "events": events,
        "summary": summary,
        "available_horizons": [7, 30, 90, 365],
        "notes": notes,
    }
