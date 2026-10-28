"""单端口 Web 服务：每个小工具一个独立 HTML 页 + 一个 JSON 计算接口。

`/` 是工具总览页；收息佬与波段都挂在本进程（波段另保留独立入口
`python -m bigwinner.bigly` :8788，二者互不影响）。

启动：
    PYTHONPATH=src python -m bigwinner.server              # 真实取数（需 wmshare）
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
#: 网页版 SPA（web/ 前端 `npm run build` 的产物）。存在时优先托管：
#: hash 路由只有 / 一个入口，旧 /tools/<slug>/ 链接 302 到对应 hash 页面。
WEB_DIST = WEB_DIR.parent / "web_dist"

#: 旧多页路由 → SPA hash 路由（推广帖里的旧链接保持可用）
_SPA_REDIRECTS = {
    "dividend-xray": "shouxi",
    "bigly": "bigly",
    "screener": "screener",
}

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
        "title": "选股",
        "tagline": "预置策略 · 一键全市场 —— 格雷厄姆、高股息，条件与数字都摆给你看",
        "page": "screener.html",
    },
}

DISCLAIMER = (
    "本工具仅做持仓数据的统计聚合，不构成任何投资建议；"
    "数据来自 wmshare，最终以上市公司公告为准；历史分红不代表未来。"
)


class ToolError(Exception):
    """可预期的业务错误，会原样返回给前端展示。"""


# ---------------------------------------------------------------- 取数实例


class Runtime:
    """惰性持有取数实例，避免未安装 wmshare 时服务起不来。"""

    def __init__(self, demo: bool = False) -> None:
        self.demo = demo
        self._fetcher: Any = None

    def fetcher(self) -> Any:
        if self._fetcher is None:
            if self.demo:
                self._fetcher = fetchers.FakeFetcher(**_demo_data())
            else:
                self._fetcher = fetchers.CachedFetcher(fetchers.WmshareFetcher())
        return self._fetcher

    def rekey(self, client_id: str, client_secret: str) -> bool:
        """热切换到用户自己的 Key。成功返回 True，凭证无效返回 False。"""
        if self.demo:
            return False  # demo 模式不接真实 Key
        import wmshare  # noqa: PLC0415
        try:
            probe = wmshare.Client(client_id=client_id, client_secret=client_secret)
            probe.call("kline.query_bars", sym="600036", limit=1)  # 真实验证
        except Exception:  # noqa: BLE001 - 凭证错/网络错都不切换
            return False
        inner = getattr(self._fetcher, "inner", None)
        if inner is not None:  # CachedFetcher 包着 WmshareFetcher
            inner.rekey(client_id, client_secret)
            self._fetcher._store.clear()  # 旧 Key 的缓存全部作废
        else:
            self._fetcher = fetchers.CachedFetcher(
                fetchers.WmshareFetcher(client=probe))
        return True


RUNTIME = Runtime()
DIRECTORY = SymbolDirectory()
STORE = Store()
WATCHLIST = WatchlistSync()
SCREENER = StockScreener()

_BIGLY_DATA: Any = None


def bigly_data() -> Any:
    """波段的取数实例，首次请求时才构造（demo→罐头数据，真实→wmshare SDK），
    未安装 wmshare 不影响服务启动。"""
    global _BIGLY_DATA
    if _BIGLY_DATA is None:
        _BIGLY_DATA = bigly_srv.build_data(RUNTIME.demo)
    return _BIGLY_DATA


_SCREENER_DATA: Any = None


def screener_data() -> Any:
    """筛选工具的取数实例（demo→确定性罐头，真实→wmshare，仅 A 股口径）。"""
    global _SCREENER_DATA
    if _SCREENER_DATA is None:
        if RUNTIME.demo:
            _SCREENER_DATA = scr.FakeScreenerSource()
        else:
            _SCREENER_DATA = scr.PlatformScreenerSource()
    return _SCREENER_DATA


_DEMO_SNAPSHOT: dict[str, Any] | None = None


def _demo_snapshot() -> dict[str, Any] | None:
    """真实数据静态快照（scripts/bake_demo_data.py 生成），懒加载一次。"""
    global _DEMO_SNAPSHOT
    if _DEMO_SNAPSHOT is None:
        path = Path(__file__).resolve().parent / "demo_data.json"
        if path.exists():
            try:
                _DEMO_SNAPSHOT = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 - 快照损坏则退回内置样例
                _DEMO_SNAPSHOT = {}
    return _DEMO_SNAPSHOT or None


def _demo_data() -> dict[str, Any]:
    """demo 模式数据：真实数据的静态快照（非实时）。

    价格 / 股息率 / 分红史都是生成当日真实接口返回——演示要经得起看，
    只是时间冻结在快照日。配置 wmshare Key 即变实时：演示模式下
    「验证并换 Key」通过后会直接热切换，无需重启（见 key_save）。
    快照文件缺失时退回内置最小样例，保证 --demo 永远能起。
    """
    snap = _demo_snapshot()
    if snap and snap.get("tables"):
        return snap["tables"]
    return _demo_data_fallback()


def _demo_data_fallback() -> dict[str, Any]:
    """内置兜底样例（快照 JSON 缺失/损坏时才用到）。

    与正式快照同口径：只覆盖贵州茅台一只示例。演示看门面足够，
    其余标的如实缺数据并引导换 Key——绝不合成别的股票假价格。
    """
    code = "600519"
    payout = 0.799
    eps = 70.3
    npts = eps * 1.2e9
    ncfo = npts * 1.05
    series = [{"year": y, "value": round(payout * (1 + (2025 - y) * 0.02), 4)}
              for y in range(2025, 2019, -1)]
    quality = {
        "payout_ttm": payout, "payout_lyr": payout,
        "payout_3y_avg": round(payout * 0.97, 4),
        "payout_5y_avg": round(payout * 0.94, 4),
        "payout_3y_min": round(payout * 0.9, 4),
        "payout_5y_min": round(payout * 0.85, 4),
        "payout_trend": "flat",
        "yield_ttm": 0.0396,
        "ncfo_ttm": ncfo, "fcf_ttm": ncfo * 0.8,
        "cf_np": 1.05, "ncfo_3y_min": ncfo * 0.9, "cfo_kind": 1,
        "npts_ttm": npts, "npts_yoy": 0.06,
        "roe": 0.12, "roic": 0.10,
        "tl_rate": 0.35,
        "ibd_rate": 0.13,
        "quick": 1.2,
        "ld": 1.5,
        "setl": -(npts * 0.3),
        "org_type": 1,
        "org_form": "地方国有企业",
        "free_holder_sum": 0.48, "exec_hold": 0.008,
        "has_buyback": True,
        "ind_tl_3y_avg": 0.44, "ind_roe_3y_avg": 0.10,
        "ind_yield_3y_avg": 0.035,
        "payout_lyr_series": series,
        "bonus_series": [{"year": s["year"], "value": npts * s["value"]}
                         for s in series],
        "yield_series": [{"year": s["year"],
                          "value": 0.0396 * (1 + (2025 - s["year"]) * 0.02)}
                         for s in series],
    }
    return {
        "prices": {code: 1420.0},
        "yields": {code: 0.0396},
        "payouts": {code: payout},
        "dps": {code: 56.2},
        "eps": {code: eps},
        "pct10y": {code: 0.28},
        "quality": {code: quality},
        "names": {code: "贵州茅台"},
        "history": {
            code: [
                # 2026 已实施（今年已收）
                {"sas": "2025-12-31", "ex_date": "2026-07-15",
                 "record_date": "2026-07-14", "pay": "2026-07-30",
                 "dps": 56.0, "status": "实施", "kind": "年度",
                 "content": "10派56元(含税)"},
                # 2026 中期预案（未来 30 天内除权，演示日历）
                {"sas": "2026-06-30", "ex_date": "2026-11-15",
                 "record_date": "2026-11-14", "pay": "2026-11-30",
                 "dps": 59.5, "status": "预案", "kind": "中期",
                 "content": "10派59.5元(含税)"},
                *[
                    {"sas": f"{y}-06-30", "ex_date": f"{y}-07-15", "dps": 47.0}
                    for y in range(2025, 2019, -1)
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


def _reset_auth_note() -> None:
    """每次新生成前清掉凭证错误标记：横幅只反映最近一次取数。"""
    clear = getattr(RUNTIME.fetcher(), "clear_auth_error", None)
    if clear is not None:
        clear()


def _attach_auth_note(result: dict[str, Any]) -> dict[str, Any]:
    """本次取数遇到凭证类错误（Key 无效/过期）时在结果上显式标注。

    实时模式下各票取数失败是单票隔离的，页面只会看到成片「—」；
    这个字段让前端能区分「真没数据」和「数据源拒绝了请求」。
    demo 模式（FakeFetcher）没有该字段，永不触发。
    """
    note = getattr(RUNTIME.fetcher(), "auth_error", None)
    if note:
        result["auth_error"] = note
    return result


def run_dividend_xray(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("positions") or []
    if not items:
        raise ToolError("请先填入至少一行持仓")
    if len(items) > t1.MAX_POSITIONS:
        raise ToolError(f"单次最多 {t1.MAX_POSITIONS} 个标的，当前 {len(items)} 个")

    positions = fetchers.positions_from_payload(items)
    if not positions:
        raise ToolError("没有识别到有效持仓行（代码非空、股数为正整数）")
    _reset_auth_note()
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
    return _attach_auth_note(data)


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
    _reset_auth_note()
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
    return _attach_auth_note(data)


def run_calendar(payload: dict[str, Any]) -> dict[str, Any]:
    """分红日历：positions（我的持仓）/ codes（关注池）/ market（高股息池）。"""
    from bigwinner.shouxi.tools import calendar as cal_mod

    mode = str(payload.get("mode") or "positions").strip().lower()
    if mode not in ("positions", "codes", "market"):
        raise ToolError("日历模式不正确（positions/codes/market）")

    fetcher = RUNTIME.fetcher()
    _reset_auth_note()
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
            if RUNTIME.demo:
                raise ToolError(
                    "演示快照只覆盖示例标的，高股息池需要实时数据——"
                    "配置自己的 Key 即可查看全市场。")
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
    return _attach_auth_note(data)


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
    _reset_auth_note()
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
    return _attach_auth_note(out)


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
    _reset_auth_note()
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

    return _attach_auth_note({
        "code": item_code,
        "market": market,
        "profile": profile,
        "quote": quote,
        "quality": quality_out,
        "next_event": next_event,
        "notes": notes,
        "disclaimer": DISCLAIMER,
        "demo": RUNTIME.demo,
    })


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
    env_id = (os.environ.get("WMSHARE_CLIENT_ID")
              or os.environ.get("OPEN_PLATFORM_CLIENT_ID"))
    custom = bool(env_id) or \
        Path.home().joinpath(".wmshare", "credentials.env").exists()
    return {"custom": custom, "demo": RUNTIME.demo}


def _write_credentials(cid: str, sec: str) -> None:
    """Key 落盘 ~/.wmshare/credentials.env（权限 600，不回显）。"""
    cred = Path.home() / ".wmshare" / "credentials.env"
    cred.parent.mkdir(parents=True, exist_ok=True)
    cred.write_text(
        f"WMSHARE_CLIENT_ID={cid}\nWMSHARE_CLIENT_SECRET={sec}\n",
        encoding="utf-8")
    cred.chmod(0o600)


def key_save(payload: dict[str, Any]) -> dict[str, Any]:
    """页面直接保存 Key：写 ~/.wmshare/credentials.env + 验证。

    真实模式：验证通过立即热切换，缓存作废。
    演示模式：验证通过后直接热切换为实时取数（wmshare 可用即可），无需重启；
    未安装 wmshare 时只落盘并如实提示。换 Key 的入口任何模式下都可用。
    安全：响应不回显 Key；写文件权限 600；验证失败不落地。
    """
    global _BIGLY_DATA, _SCREENER_DATA
    cid = str(payload.get("client_id") or "").strip()
    sec = str(payload.get("client_secret") or "").strip()
    if not cid or not sec:
        raise ToolError("client_id 与 client_secret 都必填")

    if RUNTIME.demo:
        try:
            import wmshare  # noqa: PLC0415
        except ImportError:
            _write_credentials(cid, sec)
            return {"ok": True, "message": "Key 已保存（本机未安装 wmshare，"
                    "跳过在线验证）~/.wmshare/credentials.env。安装 wmshare 后"
                    "重启真实模式即生效。"}
        try:
            probe = wmshare.Client(client_id=cid, client_secret=sec)
            probe.call("kline.query_bars", sym="600036", limit=1)  # 真实验证
        except Exception:  # noqa: BLE001 - 凭证错/网络错都不落地
            raise ToolError("Key 验证失败：请检查是否复制完整（client_id + "
                            "api-key）。旧文件未受影响。") from None
        _write_credentials(cid, sec)
        # 热切换：复用刚验证过的 client 转实时取数，波段/筛选取数实例也重建
        RUNTIME._fetcher = fetchers.CachedFetcher(
            fetchers.WmshareFetcher(client=probe))
        RUNTIME.demo = False
        _BIGLY_DATA = None
        _SCREENER_DATA = None
        return {"ok": True, "message": "Key 已验证并生效：已切换为实时数据，"
                "无需重启。"}

    ok = RUNTIME.rekey(cid, sec)
    if not ok:
        raise ToolError("Key 验证失败：请检查是否复制完整（client_id + api-key）。"
                        "旧 Key 未受影响，工具仍用原凭证。")
    _write_credentials(cid, sec)
    return {"ok": True, "message": "Key 已验证并保存（~/.wmshare/credentials.env），"
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
        # SPA 模式：web/ 前端构建产物存在时优先托管（API 与导出路由不受影响）
        if (WEB_DIST / "index.html").is_file():
            if route == "/":
                self._send_html(WEB_DIST / "index.html")
                return
            if route == "/setup.html":
                self._send_redirect("/#/setup")
                return
            if route.startswith("/assets/"):
                asset = WEB_DIST / "assets" / Path(route[len("/assets/"):]).name
                if asset.is_file():
                    self._send_asset(asset)
                    return
            if route.startswith("/tools/"):
                slug = route[len("/tools/"):].strip("/")
                target = _SPA_REDIRECTS.get(slug)
                if target:
                    self._send_redirect(f"/#/{target}")
                    return
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
            info: dict[str, Any] = {"demo": RUNTIME.demo,
                                    "setup_url": "/setup.html"}
            if RUNTIME.demo:
                snap = _demo_snapshot()
                if snap and snap.get("as_of"):
                    info["demo_as_of"] = snap["as_of"]
                names = _demo_data().get("names") or {}
                info["demo_symbols"] = [{"code": c, "name": n}
                                        for c, n in names.items()]
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
        self._send_asset(path)

    def _send_asset(self, path: Path) -> None:
        ctype = {
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".mjs": "application/javascript; charset=utf-8",
            ".html": "text/html; charset=utf-8",
            ".png": "image/png",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
            ".woff2": "font/woff2",
            ".json": "application/json; charset=utf-8",
        }.get(path.suffix, "application/octet-stream")
        self._send(200, path.read_bytes(), ctype)

    def _send_redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

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
                        help="使用内置样例数据，无需 wmshare 凭证")
    args = parser.parse_args(argv)
    RUNTIME.demo = args.demo
    auto_demo = False
    if not args.demo and not fetchers.has_own_credentials():
        # 体验 Key 路径已下线：没有自己的 Key 不再蹭 SDK 内置共享池，直接进演示
        RUNTIME.demo = True
        auto_demo = True

    host = "127.0.0.1"
    print(f"\n  收息佬（big-winner）  →  http://{host}:{args.port}")
    print(f"  模式：{'demo（真实数据快照）' if RUNTIME.demo else '真实取数（wmshare）'}")
    if auto_demo:
        as_of = (_demo_snapshot() or {}).get("as_of")
        print(f"  未检测到自己的 Key，已进入演示模式（历史快照"
              + (f"，截止 {as_of}" if as_of else "") + "，非实时）。")
        print(f"  配置自己的 Key 后页面内「换 Key」即变实时："
              f"http://{host}:{args.port}/#/setup")
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
