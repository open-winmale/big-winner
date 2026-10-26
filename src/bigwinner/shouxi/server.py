"""单端口 Web 服务：每个小工具一个独立 HTML 页 + 一个 JSON 计算接口。

`/` 是工具总览页；收息佬与波段都挂在本进程（波段另保留独立入口
`python -m bigwinner.bigly` :8788，二者互不影响）。

启动：
    PYTHONPATH=src python -m bigwinner.server              # 真实取数（需 finpipe）
    PYTHONPATH=src python -m bigwinner.server --demo       # 内置样例数据，无需凭证
    PYTHONPATH=src python -m bigwinner.server --port 8787

设计取舍：只用标准库 `http.server`，不引入 FastAPI/uvicorn —— 开源项目的
使用门槛越低越好，`python -m bigwinner.server` 一条命令就能跑起来。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bigwinner.bigly import server as bigly_srv
from bigwinner.common import fetchers
from bigwinner.common.export import xray_csv
from bigwinner.common.symbols import SymbolDirectory
from bigwinner.common.store import Store
from bigwinner.common.watchlist_sync import StockScreener, WatchlistSync
from bigwinner.shouxi.tools import dividend_xray as t1
from bigwinner.shouxi.tools import dividend_quality as dq
from bigwinner.shouxi.tools import ledger as ledger_mod
from bigwinner.shouxi.tools import screener as scr

WEB_DIR = Path(__file__).resolve().parent / "web"

#: 工具注册表：新增工具只需在这里加一条 + 一个 HTML + 一个 handler；
#: 页面不在本包 web/ 下时，用 web_dir 指到别处（如波段）
TOOLS: dict[str, dict[str, str]] = {
    "dividend-xray": {
        "title": "收息佬",
        "tagline": "攒股收息驾驶舱：分红日历 · 持续性分析 · 税后记账",
        "page": "dividend_xray.html",
    },
    "bigly": {
        "title": bigly_srv.TOOL_META["title"],
        "tagline": bigly_srv.TOOL_META["tagline"],
        "page": "bigly.html",
        "web_dir": str(bigly_srv.WEB_DIR),
    },
    "screener": {
        "title": "筛选",
        "tagline": "预置策略 · 一键全市场 —— 格雷厄姆、高股息，条件与数字都摆给你看",
        "page": "screener.html",
    },
}

DISCLAIMER = (
    "本工具仅做持仓数据的统计聚合，不构成任何投资建议；"
    "数据来自 finpipe，最终以上市公司公告为准；历史分红不代表未来。"
)


class ToolError(Exception):
    """可预期的业务错误，会原样返回给前端展示。"""


# ---------------------------------------------------------------- 取数实例


class Runtime:
    """惰性持有取数实例，避免未安装 finpipe 时服务起不来。"""

    def __init__(self, demo: bool = False) -> None:
        self.demo = demo
        self._fetcher: Any = None

    def fetcher(self) -> Any:
        if self._fetcher is None:
            if self.demo:
                self._fetcher = fetchers.FakeFetcher(**_demo_data())
            else:
                self._fetcher = fetchers.CachedFetcher(fetchers.FinpipeFetcher())
        return self._fetcher

    def rekey(self, client_id: str, client_secret: str) -> bool:
        """热切换到用户自己的 Key。成功返回 True，凭证无效返回 False。"""
        if self.demo:
            return False  # demo 模式不接真实 Key
        import finpipe  # noqa: PLC0415
        try:
            probe = finpipe.Client(client_id=client_id, client_secret=client_secret)
            probe.call("kline.query_bars", sym="600036", limit=1)  # 真实验证
        except Exception:  # noqa: BLE001 - 凭证错/网络错都不切换
            return False
        inner = getattr(self._fetcher, "inner", None)
        if inner is not None:  # CachedFetcher 包着 FinpipeFetcher
            inner.rekey(client_id, client_secret)
            self._fetcher._store.clear()  # 旧 Key 的缓存全部作废
        else:
            self._fetcher = fetchers.CachedFetcher(
                fetchers.FinpipeFetcher(client=probe))
        return True


RUNTIME = Runtime()
DIRECTORY = SymbolDirectory()
STORE = Store()
WATCHLIST = WatchlistSync()
SCREENER = StockScreener()

_BIGLY_DATA: Any = None


def bigly_data() -> Any:
    """波段的取数实例，首次请求时才构造（demo→罐头数据，真实→finpipe SDK），
    未安装 finpipe 不影响服务启动。"""
    global _BIGLY_DATA
    if _BIGLY_DATA is None:
        _BIGLY_DATA = bigly_srv.build_data(RUNTIME.demo)
    return _BIGLY_DATA


_SCREENER_DATA: Any = None


def screener_data() -> Any:
    """筛选工具的取数实例（demo→确定性罐头，真实→finpipe，仅 A 股口径）。"""
    global _SCREENER_DATA
    if _SCREENER_DATA is None:
        if RUNTIME.demo:
            _SCREENER_DATA = scr.FakeScreenerSource()
        else:
            _SCREENER_DATA = scr.FinpipeScreenerSource()
    return _SCREENER_DATA


def _demo_data() -> dict[str, Any]:
    """demo 模式的样例数据（口径与真实一致：比率小数、金额元）。

    20 只主流蓝筹，数值为 2026-10 量级的近似编排值——够演示交互与看板，
    不代表真实行情（页面右上角有 DEMO 徽章）。其他票如实缺失。
    """
    codes = ["600900", "601088", "600519", "601398", "000858",
             "600036", "601318", "000651", "600887", "601899",
             "600489", "000333", "600276", "601888", "000001",
             "601166", "600028", "601728", "600941", "601668"]

    prices = {
        "600900": 28.10, "601088": 41.20, "600519": 1420.0, "601398": 6.85,
        "000858": 118.40, "600036": 45.60, "601318": 52.30, "000651": 41.80,
        "600887": 27.50, "601899": 21.40, "600489": 13.20, "000333": 74.20,
        "600276": 46.90, "601888": 61.50, "000001": 11.60, "601166": 22.10,
        "600028": 6.20, "601728": 7.40, "600941": 108.50, "601668": 5.90,
        "hk.00700": 382.40,
    }
    yields = {
        "600900": 0.0338, "601088": 0.0521, "600519": 0.0396, "601398": 0.0512,
        "000858": 0.0461, "600036": 0.0482, "601318": 0.0345, "000651": 0.0564,
        "600887": 0.0412, "601899": 0.0321, "600489": 0.0448, "000333": 0.0487,
        "600276": 0.0298, "601888": 0.0215, "000001": 0.0532, "601166": 0.0495,
        "600028": 0.0552, "601728": 0.0428, "600941": 0.0465, "601668": 0.0488,
        "hk.00700": 0.01373,
    }
    payouts = {
        "600900": 0.710, "601088": 0.728, "600519": 0.799, "601398": 0.310,
        "000858": 0.650, "600036": 0.352, "601318": 0.285, "000651": 0.722,
        "600887": 0.705, "601899": 0.446, "600489": 0.630, "000333": 0.445,
        "600276": 0.510, "601888": 0.518, "000001": 0.285, "601166": 0.310,
        "600028": 0.680, "601728": 0.435, "600941": 0.730, "601668": 0.288,
        "hk.00700": 0.2052,
    }
    dps = {
        "600900": 0.95, "601088": 2.15, "600519": 56.2, "601398": 0.35,
        "000858": 5.46, "600036": 2.20, "601318": 1.80, "000651": 2.36,
        "600887": 1.13, "601899": 0.69, "600489": 0.59, "000333": 3.50,
        "600276": 1.40, "601888": 1.32, "000001": 0.62, "601166": 1.09,
        "600028": 0.34, "601728": 0.32, "600941": 5.05, "601668": 0.29,
        "hk.00700": 5.30,
    }
    eps = {
        "600900": 1.32, "601088": 2.95, "600519": 70.3, "601398": 1.05,
        "000858": 8.40, "600036": 5.85, "601318": 5.90, "000651": 3.10,
        "600887": 1.62, "601899": 1.50, "600489": 0.89, "000333": 7.60,
        "600276": 2.72, "601888": 2.42, "000001": 2.15, "601166": 3.45,
        "600028": 0.50, "601728": 0.72, "600941": 6.85, "601668": 1.00,
    }

    def _demo_quality(code: str) -> dict[str, Any]:
        """demo 质量指标：与 payouts/eps 同口径，金融股模拟 FCF 缺失。"""
        payout = payouts.get(code) or 0.5
        eps_ttm = eps.get(code) or 1.0
        financial = code in ("601398", "601318", "601166", "000001")
        npts = eps_ttm * 1.0e9
        ncfo = npts * (1.05 if not financial else 1.6)
        fcf = None if financial else ncfo * 0.8
        series = [{"year": y, "value": round(payout * (1 + (2025 - y) * 0.02), 4)}
                  for y in range(2025, 2019, -1)]
        return {
            "payout_ttm": payout, "payout_lyr": payout,
            "payout_3y_avg": round(payout * 0.97, 4),
            "payout_5y_avg": round(payout * 0.94, 4),
            "payout_3y_min": round(payout * 0.9, 4),
            "payout_5y_min": round(payout * 0.85, 4),
            "payout_trend": "flat",
            "yield_ttm": yields.get(code),
            "ncfo_ttm": ncfo, "fcf_ttm": fcf,
            "cf_np": 1.05, "ncfo_3y_min": ncfo * 0.9, "cfo_kind": 1,
            "npts_ttm": npts, "npts_yoy": 0.06,
            "roe": 0.12, "roic": 0.10,
            "tl_rate": 0.92 if financial else 0.35,
            "ibd_rate": 0.0 if financial else 0.13,
            "quick": None if financial else 1.2,
            "ld": None if financial else 1.5,
            "setl": None if financial else -(npts * 0.3),
            "org_type": 2 if financial else 1,
            "org_form": ("中央金融企业" if financial
                         else ("大型民企" if code in ("000858", "000651")
                               else "地方国有企业")),
            "free_holder_sum": 0.48, "exec_hold": 0.008,
            "has_buyback": code in ("600519", "000333"),
            "ind_tl_3y_avg": 0.44, "ind_roe_3y_avg": 0.10,
            "ind_yield_3y_avg": 0.035,
            "payout_lyr_series": series,
            "bonus_series": [{"year": s["year"], "value": npts * s["value"]}
                             for s in series],
            "yield_series": [{"year": s["year"],
                              "value": (yields.get(code) or 0.03) * (1 + (2025 - s["year"]) * 0.02)}
                             for s in series],
        }

    quality = {c: _demo_quality(c) for c in codes}

    names = {
        "600900": "长江电力", "601088": "中国神华", "600519": "贵州茅台",
        "601398": "工商银行", "000858": "五粮液", "600036": "招商银行",
        "601318": "中国平安", "000651": "格力电器", "600887": "伊利股份",
        "601899": "紫金矿业", "600489": "中金黄金", "000333": "美的集团",
        "600276": "恒瑞医药", "601888": "中国中免", "000001": "平安银行",
        "601166": "兴业银行", "600028": "中国石化", "601728": "中国电信",
        "600941": "中国移动", "601668": "中国建筑", "hk.00700": "腾讯控股",
    }

    return {
        "prices": prices,
        "yields": yields,
        "payouts": payouts,
        "dps": dps,
        "eps": {**eps, "hk.00700": 25.902},
        "quality": quality,
        "names": names,
        "pct10y": {
            "600900": 0.42, "601088": 0.61, "600519": 0.28, "601398": 0.77,
            "000858": 0.55, "600036": 0.72, "601318": 0.38, "000651": 0.83,
            "600887": 0.49, "601899": 0.33, "600489": 0.58, "000333": 0.66,
            "600276": 0.22, "601888": 0.15, "000001": 0.74, "601166": 0.69,
            "600028": 0.80, "601728": 0.52, "600941": 0.64, "601668": 0.71,
            "hk.00700": 1.0,
        },
        "history": {
            **{
                c: [
                    # 2026 已实施（今年已收）
                    {"sas": "2025-12-31", "ex_date": "2026-07-15",
                     "record_date": "2026-07-14", "pay": "2026-07-30",
                     "dps": 0.9, "status": "实施", "kind": "年度",
                     "content": "10派9元(含税)"},
                    # 2026 中期预案（未来 30 天内除权，演示日历）
                    {"sas": "2026-06-30", "ex_date": "2026-11-15",
                     "record_date": "2026-11-14", "pay": "2026-11-30",
                     "dps": 0.95, "status": "预案", "kind": "中期",
                     "content": "10派9.5元(含税)"},
                    *[
                        {"sas": f"{y}-06-30", "ex_date": f"{y}-07-15", "dps": 0.9}
                        for y in range(2025, 2019, -1)
                    ],
                ]
                for c in codes
            },
            # 港股：2026 已派 + 2026 中期预案，演示 HK 通道/币种/日历
            "hk.00700": [
                {"sas": "2025-12-31", "ex_date": "2026-05-20",
                 "record_date": "2026-05-19", "pay": "2026-06-05",
                 "dps": 5.30, "status": "实施", "kind": "年度",
                 "content": "派发年度股息"},
                {"sas": "2026-06-30", "ex_date": "2026-11-20",
                 "record_date": "2026-11-19", "pay": "2026-12-05",
                 "dps": 5.30, "status": "预案", "kind": "中期",
                 "content": "派发中期股息"},
                *[
                    {"sas": f"{y}-12-31", "ex_date": f"{y + 1}-05-20",
                     "dps": 5.30}
                    for y in range(2024, 2019, -1)
                ],
            ],
        },
    }


# ---------------------------------------------------------------- 业务 handler


def _fill_names(fetcher: Any, positions: list[Any]) -> None:
    """名称缺失的持仓直接查 profile（$NAME 不会有缺失）。

    只对没有名字的票逐票调用，已命名的跳过；单票失败不影响其余。
    """
    for p in positions:
        if p.name:
            continue
        fn = getattr(fetcher, "profile_metrics", None)
        if fn is None:
            return
        try:
            profile = fn(p.normalized_code()) or {}
        except Exception:  # noqa: BLE001 - 单票失败不影响其余
            continue
        if profile.get("name"):
            p.name = str(profile["name"])


def run_dividend_xray(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("positions") or []
    if not items:
        raise ToolError("请先填入至少一行持仓")
    if len(items) > t1.MAX_POSITIONS:
        raise ToolError(f"单次最多 {t1.MAX_POSITIONS} 个标的，当前 {len(items)} 个")

    positions = fetchers.positions_from_payload(items)
    if not positions:
        raise ToolError("没有识别到有效持仓行（代码非空、股数为正整数）")
    _fill_names(RUNTIME.fetcher(), positions)

    deep = bool(payload.get("deep"))
    result = t1.analyze(positions, RUNTIME.fetcher(), deep=deep)
    data = asdict(result)
    data["disclaimer"] = DISCLAIMER
    data["demo"] = RUNTIME.demo
    # 每次生成自动存快照（本地 SQLite）——历史趋势的原料
    try:
        STORE.save_snapshot(data, deep=deep,
                            mode="demo" if RUNTIME.demo else "real")
        data["snapshot_saved"] = True
    except Exception:  # noqa: BLE001 - 存档失败不影响主流程
        data["snapshot_saved"] = False
    return data


def save_positions(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ToolError("请给持仓档案起个名字")
    items = payload.get("positions")
    if items is None:
        raise ToolError("缺少 positions")
    STORE.save_positions(name, items)
    return {"ok": True, "name": name, "n": len(items)}


def list_positions(_: dict[str, Any]) -> dict[str, Any]:
    return {"sets": STORE.list_position_sets()}


def load_positions(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ToolError("请指定持仓档案名")
    positions = STORE.load_positions(name)
    if positions is None:
        raise ToolError(f"没有名为「{name}」的持仓档案")
    return {"name": name, "positions": positions}


def snapshot_history(_: dict[str, Any]) -> dict[str, Any]:
    return {"history": STORE.snapshot_history()}


def sync_diff(payload: dict[str, Any]) -> dict[str, Any]:
    codes = [str(p.get("code", "")).strip()
             for p in payload.get("positions") or []]
    codes = [c for c in codes if c]
    if not codes:
        raise ToolError("没有可同步的标的")
    group = str(payload.get("group") or "持仓透视").strip()
    return WATCHLIST.diff(group, codes)


def sync_push(payload: dict[str, Any]) -> dict[str, Any]:
    codes = [str(p.get("code", "")).strip()
             for p in payload.get("positions") or []]
    codes = [c for c in codes if c]
    if not codes:
        raise ToolError("没有可同步的标的")
    group = str(payload.get("group") or "持仓透视").strip()
    result = WATCHLIST.push(group, codes)
    STORE.log_sync(group, result.get("group_id"), "push",
                   len(codes), result, ok=True)
    return result


def _rate(value: Any) -> float | None:
    """税率归一：接受小数或百分数；非法/空返回 None。"""
    if value in (None, ""):
        return None
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return None
    if rate > 1:
        rate /= 100.0
    return max(0.0, min(1.0, rate))


def _tax_options(payload: dict[str, Any]) -> dict[str, Any]:
    """账本/日历共用的计税选项。"""
    tax_raw = payload.get("tax") or {}
    mode = str(tax_raw.get("mode") or "auto").strip().lower()
    if mode not in ledger_mod.TAX_MODES:
        raise ToolError("计税方式不正确（auto/flat/by_year）")
    year_rates: dict[str, float] = {}
    for k, v in (tax_raw.get("year_rates") or {}).items():
        rate = _rate(v)
        if rate is not None:
            year_rates[str(k)] = rate
    return {
        "mode": mode,
        "flat_rate": _rate(tax_raw.get("flat_rate")),
        "year_rates": year_rates,
    }


def run_ledger(payload: dict[str, Any]) -> dict[str, Any]:
    """分红记账：positions 需 code+shares（buy_date/market/tax_rate 可选）。"""
    raw_items = payload.get("positions") or []
    if not raw_items:
        raise ToolError("请先添加持仓")

    # 统一代码形态：HK → hk.00700（取数层再路由到 hk 市场 + 裸 5 位）
    items: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        code = fetchers.sdk_symbol(raw)
        if not code:
            continue
        item = dict(raw)
        item["code"] = code
        if not item.get("market"):
            item["market"] = "hk" if code.startswith("hk.") else "cn"
        items.append(item)
    valid = False
    for item in items:
        try:
            if int(float(item.get("shares") or 0)) > 0:
                valid = True
                break
        except (TypeError, ValueError):
            continue
    if not valid:
        raise ToolError("没有识别到有效持仓行（代码非空、股数为正整数）")

    year = payload.get("year")
    if year is not None and str(year).strip():
        try:
            year = int(year)
        except (TypeError, ValueError):
            raise ToolError("年份格式不正确")
    else:
        year = None

    tax = _tax_options(payload)

    fetcher = RUNTIME.fetcher()
    rows_by_code: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        code = item["code"]
        try:
            rows_by_code[code] = fetcher.dividend_rows(code, limit=100) or []
        except Exception:  # noqa: BLE001 - 单票历史失败 → 该票记为空并注明
            rows_by_code[code] = []

    fx: dict[str, float | None] = {"CNY": 1.0}
    if any(item.get("market") == "hk" for item in items):
        try:
            fn = getattr(fetcher, "fx_to_cny", None)
            fx["HKD"] = fn("HKD") if fn is not None else None
        except Exception:  # noqa: BLE001 - 汇率失败只影响合计
            fx["HKD"] = None

    data = ledger_mod.build_ledger(items, rows_by_code, year=year, tax=tax, fx=fx)
    data["disclaimer"] = DISCLAIMER
    return data


def run_calendar(payload: dict[str, Any]) -> dict[str, Any]:
    """分红日历：positions（我的持仓）/ codes（关注池）/ market（高股息池）。"""
    from bigwinner.shouxi.tools import calendar as cal_mod

    mode = str(payload.get("mode") or "positions").strip().lower()
    if mode not in ("positions", "codes", "market"):
        raise ToolError("日历模式不正确（positions/codes/market）")

    fetcher = RUNTIME.fetcher()
    items: list[dict[str, Any]] = []

    if mode == "market":
        market = "hk" if str(payload.get("market") or "cn").lower() == "hk" else "cn"
        try:
            pool_limit = max(1, min(int(payload.get("limit") or 120), 300))
        except (TypeError, ValueError):
            pool_limit = 120
        pool: list[dict[str, Any]] = []
        screener_error = ""
        if not RUNTIME.demo:
            try:
                pool = SCREENER.high_yield(market, pool_limit)
            except Exception as exc:  # noqa: BLE001 - 选股门面不可用 → 再试指数接口
                screener_error = f"{type(exc).__name__}: {exc}"[:200]
        if not pool:
            fn = getattr(fetcher, "high_yield_symbols", None)
            pool = fn(market, pool_limit) if fn is not None else []
        if not pool:
            detail = f"（{screener_error}）" if screener_error else ""
            raise ToolError(
                "高股息池没有取到数据（选股/指数接口可能不可用或额度不足）"
                f"{detail}；可先在持仓明细添加股票，或从关注分组导入观察池。")
        items = [
            {
                "code": p["code"],
                "market": p.get("market") or market,
                "shares": 0,
                "name": p.get("name"),
                "yield_ttm": p.get("yield_ttm"),
            }
            for p in pool
        ]
    elif mode == "codes":
        raw_codes = payload.get("codes") or []
        if not raw_codes:
            raise ToolError("没有可查询的代码")
        seen: set[str] = set()
        for raw in raw_codes:
            if isinstance(raw, dict):
                code = fetchers.sdk_symbol(raw)
                name = raw.get("name")
                yield_ttm = raw.get("yield_ttm")
            else:
                # 裸码自动判市场：6 位 A 股、5 位港股
                code = fetchers.sdk_symbol({"code": raw})
                name = None
                yield_ttm = None
            if not code or code in seen:
                continue
            seen.add(code)
            market = "hk" if code.startswith("hk.") else (
                "us" if code.startswith("us.") else "cn")
            items.append({
                "code": code, "market": market, "shares": 0,
                "name": name, "yield_ttm": yield_ttm,
            })
        if not items:
            raise ToolError("没有识别到有效代码")
    else:
        positions = fetchers.positions_from_payload(payload.get("positions") or [])
        if not positions:
            raise ToolError("没有识别到有效持仓行（代码非空、股数为正整数）")
        _fill_names(fetcher, positions)
        items = [
            {
                "code": p.normalized_code(),
                "market": p.inferred_market(),
                "shares": p.shares,
                "name": p.name,
                "cost": p.cost,
                "buy_date": p.buy_date,
                "tax_rate": p.tax_rate,
            }
            for p in positions
        ]

    codes = [item["code"] for item in items]
    try:
        row_limit = max(1, min(int(payload.get("limit") or 20), 80))
    except (TypeError, ValueError):
        row_limit = 20

    rows_by_code: dict[str, list[dict[str, Any]]] = {}
    many = getattr(fetcher, "dividend_rows_many", None)
    if many is not None:
        try:
            rows_by_code = many(codes, limit=row_limit) or {}
        except Exception:  # noqa: BLE001 - 批量失败再逐票兜底
            rows_by_code = {}
    if not rows_by_code:
        for code in codes:
            try:
                rows_by_code[code] = fetcher.dividend_rows(code, limit=row_limit) or []
            except Exception:  # noqa: BLE001
                rows_by_code[code] = []

    fx: dict[str, float | None] = {"CNY": 1.0}
    if any(item.get("market") == "hk" and (item.get("shares") or 0) > 0
           for item in items):
        try:
            fx_fn = getattr(fetcher, "fx_to_cny", None)
            fx["HKD"] = fx_fn("HKD") if fx_fn is not None else None
        except Exception:  # noqa: BLE001
            fx["HKD"] = None

    try:
        horizon_days = max(7, min(int(payload.get("horizon_days") or 365), 365))
    except (TypeError, ValueError):
        horizon_days = 365

    data = cal_mod.build_calendar(
        items, rows_by_code, horizon_days=horizon_days,
        tax=_tax_options(payload), fx=fx,
    )
    data["mode"] = mode
    if mode == "market" and items:
        data["market"] = items[0]["market"]
    data["disclaimer"] = DISCLAIMER
    return data


def positions_latest(_: dict[str, Any]) -> dict[str, Any]:
    """最近保存的持仓档案（打开页面自动载入）。"""
    return {"set": STORE.latest_position_set()}


def watchlist_groups(_: dict[str, Any]) -> dict[str, Any]:
    """winmale 关注分组（无持仓时作为观察池导入）。"""
    try:
        return {"groups": WATCHLIST.view_groups()}
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"读取关注分组失败：{exc}") from exc


def run_dividend_quality(payload: dict[str, Any]) -> dict[str, Any]:
    """分红质量：A 股非金融评分；金融股/港股只展示指标并说明原因。"""
    positions = fetchers.positions_from_payload(payload.get("positions") or [])
    if not positions:
        raise ToolError("请先添加持仓")
    if len(positions) > t1.MAX_POSITIONS:
        raise ToolError(f"单次最多 {t1.MAX_POSITIONS} 个标的，当前 {len(positions)} 个")

    fetcher = RUNTIME.fetcher()
    _fill_names(fetcher, positions)
    items: list[dict[str, Any]] = []
    for p in positions:
        code = p.normalized_code()
        items.append({
            "code": code,
            "market": p.inferred_market(),
            "name": p.name,
        })

    # 原始分红历史（连续性/特别分红），按市场批量
    hist_by_code: dict[str, list[dict[str, Any]]] = {}
    many = getattr(fetcher, "dividend_rows_many", None)
    if many is not None:
        try:
            hist_by_code = many([it["code"] for it in items], limit=80) or {}
        except Exception:  # noqa: BLE001 - 历史失败不阻塞主分析
            hist_by_code = {}
    for it in items:
        hist_by_code.setdefault(it["code"], [])

    metrics_by_code: dict[str, dict[str, Any]] = {}
    for it in items:
        code = it["code"]
        if it["market"] != "cn":
            continue  # 港股：eligible=false，无需取质量指标
        try:
            fn = getattr(fetcher, "quality_metrics", None)
            metrics_by_code[code] = fn(code) if fn is not None else {}
        except Exception:  # noqa: BLE001 - 单票失败隔离
            metrics_by_code[code] = {}

    data = dq.build_quality(items, metrics_by_code, hist_by_code)
    rows_out = []
    for row in data["rows"]:
        item = {
            k: v for k, v in row.__dict__.items()
            if k not in ("recurring_by_year", "specials", "ability_bands")
        }
        item["recurring_by_year"] = row.recurring_by_year
        item["specials"] = row.specials
        item["ability_bands"] = row.ability_bands
        rows_out.append(item)
    out = {
        "rows": rows_out,
        "summary": data["summary"],
        "notes": data["notes"],
        "disclaimer": DISCLAIMER,
        "demo": RUNTIME.demo,
    }
    return out


def run_diagnose(payload: dict[str, Any]) -> dict[str, Any]:
    """单票诊股：档案（含企业类型）+ 行情股息 + 分红质量 + 未来分红事件。

    按需使用，不依赖持仓；shares=0 观察口径，无个人现金。
    任一区块失败不阻塞其他区块，缺失显式标注。
    """
    raw = str(payload.get("code") or "").strip()
    if not raw:
        raise ToolError("请输入股票代码（A 股 6 位 / 港股 5 位）")
    item_code = fetchers.sdk_symbol({"code": raw})
    if not item_code or not "".join(ch for ch in item_code if ch.isdigit()):
        raise ToolError("代码格式不正确：A 股 6 位数字 / 港股 5 位数字")
    market = "hk" if item_code.startswith("hk.") else "cn"
    name_hint = str(payload.get("name") or "").strip() or None

    fetcher = RUNTIME.fetcher()
    notes: list[str] = []

    # 1) 档案（含企业类型；CN/HK 都可用，org_form 仅 CN）
    profile: dict[str, Any] = {}
    fn = getattr(fetcher, "profile_metrics", None)
    if fn is not None:
        try:
            profile = fn(item_code) or {}
        except Exception as exc:  # noqa: BLE001
            notes.append(f"档案取数失败：{type(exc).__name__}")
    name = profile.get("name") or name_hint or item_code
    profile.setdefault("name", name)

    # 2) 行情与股息快照（快照也带名称，档案失败时兜底）
    quote: dict[str, Any] = {"currency": "HKD" if market == "hk" else "CNY"}
    try:
        prices = fetcher.prices([item_code]) or {}
        quote["price"] = prices.get(item_code)
    except Exception:  # noqa: BLE001
        quote["price"] = None
        notes.append("现价取数失败")
    try:
        snap = (fetcher.dividend_snapshot([item_code]) or {}).get(item_code) or {}
        quote["yield_ttm"] = snap.get("yield_ttm")
        quote["payout_ttm"] = snap.get("payout_ttm")
        if quote["yield_ttm"] == 0 and quote["payout_ttm"] == 0 and market == "cn":
            notes.append("股息快照为 0，可能无分红记录或数据缺失")
    except Exception:  # noqa: BLE001
        quote["yield_ttm"] = quote["payout_ttm"] = None
        notes.append("股息快照取数失败")

    # 3) 分红质量（复用 evaluate；金融/港股自动不评分）
    hist_rows: list[dict[str, Any]] = []
    try:
        hist_rows = fetcher.dividend_rows(item_code, limit=80) or []
    except Exception:  # noqa: BLE001
        notes.append("分红历史取数失败")
    metrics: dict[str, Any] = {}
    if market == "cn":
        try:
            qfn = getattr(fetcher, "quality_metrics", None)
            metrics = qfn(item_code) if qfn is not None else {}
        except Exception:  # noqa: BLE001
            metrics = {}
    quality_row = dq.evaluate(item_code, name, market, metrics, hist_rows)
    if quote.get("yield_ttm") is not None and quality_row.yield_ttm is None:
        quality_row.yield_ttm = quote["yield_ttm"]
    quality_out = {
        k: v for k, v in quality_row.__dict__.items()
        if k not in ("recurring_by_year", "specials", "ability_bands")
    }
    quality_out["recurring_by_year"] = quality_row.recurring_by_year
    quality_out["specials"] = quality_row.specials
    quality_out["ability_bands"] = quality_row.ability_bands

    # 4) 未来分红事件（观察口径，shares=0）
    next_event = None
    from bigwinner.shouxi.tools import calendar as cal_mod
    try:
        cal = cal_mod.build_calendar(
            [{"code": item_code, "market": market, "shares": 0, "name": name}],
            {item_code: hist_rows}, fx={"CNY": 1.0})
        upcoming = [e for e in cal.get("events", [])
                    if e.get("stage") in ("待除权", "已除权待到账", "预案待定")]
        next_event = upcoming[0] if upcoming else None
        if not upcoming:
            notes.append("暂无已公告的未来分红事件")
    except Exception:  # noqa: BLE001
        notes.append("分红日历取数失败")

    if market == "hk" and not profile.get("org_form"):
        notes.append("企业类型仅 A 股提供，港股暂无该标签")

    return {
        "code": item_code,
        "market": market,
        "profile": profile,
        "quote": quote,
        "quality": quality_out,
        "next_event": next_event,
        "notes": notes,
        "disclaimer": DISCLAIMER,
        "demo": RUNTIME.demo,
    }


def run_screener(payload: dict[str, Any]) -> dict[str, Any]:
    """筛选 · 预置策略全市场选股：{strategy|custom, limit} → {columns, rows}。

    通道不可用（未装 wm.sh 等）→ 200 + unavailable + 原因，页面降级展示。
    """
    limit = scr.clamp_limit(payload.get("limit"))
    try:
        custom = payload.get("custom")
        strategy = scr.build_custom(custom) if custom is not None \
            else scr.get_strategy(payload.get("strategy"))
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    result = scr.run_screen(screener_data(), strategy, limit)
    result["disclaimer"] = DISCLAIMER
    result["demo"] = RUNTIME.demo
    return result


def key_status(_: dict[str, Any]) -> dict[str, Any]:
    """当前凭证状态：是否用着自己的 Key（只回布尔与来源，绝不回 Key 本体）。"""
    custom = bool(os.environ.get("FINPIPE_CLIENT_ID")) or \
        Path.home().joinpath(".finpipe", "credentials.env").exists()
    return {"custom": custom, "demo": RUNTIME.demo}


def key_save(payload: dict[str, Any]) -> dict[str, Any]:
    """页面直接保存 Key：写 ~/.finpipe/credentials.env + 热切换验证。

    安全：响应不回显 Key；写文件权限 600；失败不落地。
    """
    cid = str(payload.get("client_id") or "").strip()
    sec = str(payload.get("client_secret") or "").strip()
    if not cid or not sec:
        raise ToolError("client_id 与 client_secret 都必填")
    ok = RUNTIME.rekey(cid, sec)
    if not ok:
        raise ToolError("Key 验证失败：请检查是否复制完整（client_id + api-key）。"
                        "旧 Key 未受影响，工具仍用原凭证。")
    cred = Path.home() / ".finpipe" / "credentials.env"
    cred.parent.mkdir(parents=True, exist_ok=True)
    cred.write_text(
        f"FINPIPE_CLIENT_ID={cid}\nFINPIPE_CLIENT_SECRET={sec}\n",
        encoding="utf-8")
    cred.chmod(0o600)
    return {"ok": True, "message": "Key 已验证并保存（~/.finpipe/credentials.env），"
                                   "额度从此独立。缓存已清空，立即生效。"}


HANDLERS = {
    "dividend-xray": run_dividend_xray,
    "dividend-quality": run_dividend_quality,
    "positions-save": save_positions,
    "positions-list": list_positions,
    "positions-load": load_positions,
    "positions-latest": positions_latest,
    "snapshots": snapshot_history,
    "watchlist-diff": sync_diff,
    "watchlist-push": sync_push,
    "watchlist-groups": watchlist_groups,
    "ledger": run_ledger,
    "calendar": run_calendar,
    "diagnose": run_diagnose,
    "screener": run_screener,
    "key-status": key_status,
    "key-save": key_save,
    # 波段：复用其纯函数 API，data 用本进程的惰性实例
    "bigly/channel": lambda payload: bigly_srv.run_channel(bigly_data(), payload),
    "bigly/backtest": lambda payload: bigly_srv.run_backtest(bigly_data(), payload),
}


# ---------------------------------------------------------------- HTTP


class Handler(BaseHTTPRequestHandler):
    server_version = "bigwinner/1.1"

    # ---- 基础 ----
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")

    def _send_html(self, path: Path) -> None:
        if not path.exists():
            self._send(404, b"<h1>404</h1>", "text/html; charset=utf-8")
            return
        self._send(200, path.read_bytes(), "text/html; charset=utf-8")

    def log_message(self, fmt: str, *args: Any) -> None:  # 精简日志
        sys.stderr.write("  %s %s\n" % (self.address_string(), fmt % args))

    # ---- GET ----
    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if route == "/":
            self._send_html(WEB_DIR / "index.html")
        elif route == "/setup.html":
            self._send_html(WEB_DIR / "setup.html")
        elif route.startswith("/assets/"):
            self._serve_asset(route[len("/assets/"):])
        elif route.startswith("/tools/"):
            slug = route[len("/tools/"):].strip("/")
            tool = TOOLS.get(slug)
            if not tool:
                self._send(404, b"<h1>404</h1>", "text/html; charset=utf-8")
                return
            self._send_html(Path(tool.get("web_dir", WEB_DIR)) / tool["page"])
        elif route == "/api/appinfo":
            info: dict[str, Any] = {"demo": RUNTIME.demo, "trial": False,
                                    "setup_url": "/setup.html"}
            if not RUNTIME.demo:
                f = RUNTIME.fetcher()
                inner = getattr(f, "inner", f)
                uses = getattr(inner, "uses_trial_key", None)
                info["trial"] = bool(uses()) if uses else False
            self._send_json(200, info)
        elif route == "/api/tools":
            self._send_json(200, {"tools": [
                {"slug": s, **{k: v for k, v in t.items()
                               if k not in ("page", "web_dir")}}
                for s, t in TOOLS.items()
            ], "demo": RUNTIME.demo})
        elif route == "/api/symbols":
            from urllib.parse import parse_qs
            query = urlparse(self.path).query
            q = (parse_qs(query).get("q") or [""])[0]
            market = (parse_qs(query).get("market") or ["cn"])[0]
            self._send_json(200, {"results": DIRECTORY.search(q, market, limit=8),
                                  "total": len(DIRECTORY),
                                  "as_of": DIRECTORY.freshness(market)})
        elif route == "/api/bigly/symbols":  # 波段页面的取码接口，同 DIRECTORY
            from urllib.parse import parse_qs
            query = urlparse(self.path).query
            q = (parse_qs(query).get("q") or [""])[0]
            market = (parse_qs(query).get("market") or ["cn"])[0]
            self._send_json(200, {"results": DIRECTORY.search(q, market, limit=8),
                                  "total": len(DIRECTORY),
                                  "as_of": DIRECTORY.freshness(market)})
        elif route == "/api/bigly/meta":
            self._send_json(200, {"tool": bigly_srv.TOOL_META,
                                  "demo": getattr(bigly_data(), "demo", False)})
        elif route == "/api/health":
            self._send_json(200, {"ok": True, "demo": RUNTIME.demo,
                                  "time": datetime.now().isoformat(timespec="seconds")})
        elif route == "/export/xray.csv":
            self._export_csv(urlparse(self.path).query)
        else:
            self._send(404, b"<h1>404</h1>", "text/html; charset=utf-8")

    def _export_csv(self, query: str) -> None:
        """GET /export/xray.csv?positions=<urlencoded json> —— 透视表导出 CSV。

        Excel 打开不乱码：UTF-8 with BOM。与页面同一 analyze 调用，数字真实；
        港股逐行原币 + CNY 折算列，缺失留空。
        """
        from urllib.parse import parse_qs
        try:
            items = json.loads((parse_qs(query).get("positions") or ["[]"])[0])
        except json.JSONDecodeError:
            self._send_json(400, {"error": "positions 参数不是合法 JSON"})
            return
        positions = fetchers.positions_from_payload(items)
        if not positions:
            self._send_json(400, {"error": "没有有效持仓"})
            return
        result = t1.analyze(positions, RUNTIME.fetcher(), deep=False)

        body = b"\xef\xbb\xbf" + xray_csv(result).encode("utf-8")  # BOM
        fname = f"xray_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition",
                         f"attachment; filename=\"{fname}\"")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_asset(self, name: str) -> None:
        path = WEB_DIR / "assets" / Path(name).name
        if not path.exists():
            self._send(404, b"", "text/plain")
            return
        ctype = {"css": "text/css; charset=utf-8",
                 "png": "image/png"}.get(path.suffix.lstrip("."),
                                          "application/javascript; charset=utf-8")
        self._send(200, path.read_bytes(), ctype)

    # ---- POST ----
    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if not route.startswith("/api/"):
            self._send_json(404, {"error": "not found"})
            return
        slug = route[len("/api/"):].removesuffix("/run")
        handler = HANDLERS.get(slug)
        if not handler:
            self._send_json(404, {"error": f"未知工具：{slug}"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("请求体必须是 JSON 对象")
            data = handler(payload)
        except ToolError as exc:
            self._send_json(400, {"error": str(exc), "disclaimer": DISCLAIMER})
            return
        except Exception as exc:  # noqa: BLE001 - 兜底，但错误信息如实回传
            self._send_json(500, {
                "error": f"{type(exc).__name__}: {exc}",
                "hint": "若为 401/403，请配置自己的 AppID；若为 429，请稍后重试",
                "disclaimer": DISCLAIMER,
            })
            return
        self._send_json(200, data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="收息佬（big-winner）单端口 Web 服务")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--demo", action="store_true",
                        help="使用内置样例数据，无需 finpipe 凭证")
    args = parser.parse_args(argv)
    RUNTIME.demo = args.demo

    host = "127.0.0.1"
    print(f"\n  收息佬（big-winner）  →  http://{host}:{args.port}")
    print(f"  模式：{'demo（样例数据）' if args.demo else '真实取数（finpipe）'}")
    for slug, tool in TOOLS.items():
        print(f"   · {tool['title']:<12} http://{host}:{args.port}/tools/{slug}/")
    print("\n  Ctrl+C 退出\n")
    try:
        ThreadingHTTPServer((host, args.port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n  已退出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
