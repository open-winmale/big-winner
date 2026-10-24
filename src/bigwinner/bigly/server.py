"""波段独立 Web 服务：python -m bigwinner.bigly（:8788）。

与收息佬同款零依赖栈（标准库 http.server）；只挂波段自己的页面与计算接口，
两个工具的端口互不影响、可同时启动。输出全部为统计描述与历史回放，
不构成投资建议。
"""
from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from bigwinner.bigly import backtest as bt_mod
from bigwinner.bigly import channel as ch_mod
from bigwinner.bigly import levels as lv_mod
from bigwinner.bigly import suggest as sg_mod
from bigwinner.bigly.fetchers import DemoBiglyData, FinpipeBiglyData
from bigwinner.common.symbols import SymbolDirectory
from bigwinner.common.fetchers import using_trial_key

WEB_DIR = Path(__file__).resolve().parent / "web"

TOOL_META = {
    "slug": "bigly",
    "title": "波段",
    "tagline": "估值通道 · 买卖点参考 · 拨测回看 —— We're gonna win so much.",
}

_VALID_METRICS = ("pe", "pb", "ps", "pr")
_VALID_WINDOWS = ("6m", "1y", "2y", "3y")  # 上限 3 年，默认半年


def _pick(payload: dict, key: str, default=None):
    v = payload.get(key, default)
    return v


def run_channel(data, payload: dict) -> dict:
    symbol = str(_pick(payload, "symbol", "") or "").strip()
    metric = str(_pick(payload, "metric", "pe") or "pe")
    window = str(_pick(payload, "window", "6m") or "6m")
    low = _pick(payload, "low")
    high = _pick(payload, "high")
    if metric not in _VALID_METRICS:
        return {"error": f"metric 只支持 {list(_VALID_METRICS)}"}
    if window not in _VALID_WINDOWS:
        return {"error": f"window 只支持 {list(_VALID_WINDOWS)}（上限 3 年）"}
    if not symbol:
        return {"error": "缺少 symbol"}
    hist = data.hist_stats(symbol, metric, window)
    channel = ch_mod.build_channel(hist)
    if channel is None:
        return {"error": "该标的窗口内估值序列为空（如亏损期 PE 无数据）；可切换 pb 或调整窗口"}
    last_close = data.last_close(symbol)
    levels = lv_mod.build_levels(hist, channel, last_close, low=low, high=high)
    # 安全边界：高位介入回撤统计（用现价的位置分位）
    bars = data.bars(symbol, window)
    closes = [float(b["close"]) for b in bars if b.get("close")]
    ref_pct = channel.get("pct")
    high_stats = bt_mod.high_entry_drawdown_stats(closes, ref_pct) if closes else None
    return {
        "symbol": symbol,
        "metric": metric,
        "window": window,
        "demo": getattr(data, "demo", False),
        "last_close": last_close,
        "channel": channel,
        "series": ch_mod.series_points(hist),
        "levels": levels,
        "safety": {
            "high_entry_drawdown": high_stats,
            "stop_reference": min(closes) if closes else None,
        },
        "extremes": bt_mod.price_extremes(bars, last_close),
        "disclaimer": "统计描述与历史回放，不构成投资建议；买卖点由你自己设定与负责。",
    }


def run_backtest(data, payload: dict) -> dict:
    symbol = str(_pick(payload, "symbol", "") or "").strip()
    metric = str(_pick(payload, "metric", "pe") or "pe")
    window = str(_pick(payload, "window", "6m") or "6m")
    buy = _pick(payload, "buy")
    sell = _pick(payload, "sell")
    stop = _pick(payload, "stop")
    if not symbol:
        return {"error": "缺少 symbol"}
    # auto 模式：不传 buy/sell → 先在窗口内搜索推荐区间，再按推荐值回拨
    auto = buy is None and sell is None
    if not auto:
        for name, v in (("buy", buy), ("sell", sell)):
            try:
                fv = float(v)
            except (TypeError, ValueError):
                return {"error": f"{name} 不是有效数字"}
            if fv <= 0:
                return {"error": f"{name} 必须为正数"}
    if stop is not None:
        try:
            if float(stop) <= 0:
                return {"error": "stop 必须为正数"}
        except (TypeError, ValueError):
            return {"error": "stop 不是有效数字"}
    if metric not in _VALID_METRICS or window not in _VALID_WINDOWS:
        return {"error": "metric/window 参数不合法"}

    bars = data.bars(symbol, window)
    if not bars:
        return {"error": "窗口内无日 K 数据"}
    hist = data.hist_stats(symbol, metric, window)
    channel = ch_mod.build_channel(hist)
    last_close = data.last_close(symbol)
    suggestion = None
    if auto:
        if channel is None:
            return {"error": "该标的窗口内估值序列为空（如亏损期 PE 无数据）；可切换 pb 或调整窗口"}
        suggestion = sg_mod.suggest_levels(bars, channel, last_close, metric)
        if suggestion is not None:
            buy_f, sell_f = suggestion["buy_price"], suggestion["sell_price"]
        else:  # 窗口内无可触发组合 → 回退通道轨
            buy_f = lv_mod.implied_price(last_close, channel["lower2"], channel["current"])
            sell_f = lv_mod.implied_price(last_close, channel["upper2"], channel["current"])
            if not buy_f or not sell_f:
                return {"error": "无法确定买卖参考价"}
    else:
        buy_f, sell_f = float(buy), float(sell)

    # 窗口内多轮进出回放：止盈/止损后资金回笼、卖出次日可再买
    bt = bt_mod.backtest_levels(bars, buy_f, sell_f,
                                stop_loss=float(stop) if stop is not None else None,
                                roundtrips=None)
    cmp_ = bt_mod.compare_with_hold(bars, bt)
    # 安全检查：买入位是否处于高位（通道 +1σ 对应价 / 窗口 p75）
    closes = [float(b["close"]) for b in bars if b.get("close")]
    safety = bt_mod.buy_safety_check(buy_f, channel, closes, last_close=last_close)
    if bt.get("no_stop_worst_drawdown") is not None:
        safety["no_stop_worst_drawdown"] = bt["no_stop_worst_drawdown"]
    return {
        "symbol": symbol,
        "metric": metric,
        "window": window,
        "demo": getattr(data, "demo", False),
        "suggest": suggestion,
        "levels_used": {"buy_price": buy_f, "sell_price": sell_f},
        "backtest": bt,
        "compare": cmp_,
        "safety": safety,
        "price_stats": bt_mod.price_zone_stats(bars, buy_f, sell_f, last_close=last_close),
        "disclaimer": "统计描述与历史回放，不构成投资建议；买卖点由你自己设定与负责。",
    }


def build_data(demo: bool):
    return DemoBiglyData() if demo else FinpipeBiglyData()


def make_handler(data, directory: SymbolDirectory | None = None):  # noqa: C901 - 单文件服务的路由集中处
    directory = directory or SymbolDirectory()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # 安静
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _file(self, rel: str, ctype: str):
            p = WEB_DIR / rel
            if not p.is_file():
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            self._send(200, p.read_bytes(), ctype)

        def do_GET(self):  # noqa: N802
            path = urlparse(self.path).path
            if path in ("/", "/tools/bigly", "/tools/bigly/"):
                self._file("bigly.html", "text/html; charset=utf-8")
            elif path == "/assets/base.css":
                self._file("assets/base.css", "text/css; charset=utf-8")
            elif path == "/api/bigly/symbols":
                from urllib.parse import parse_qs
                query = parse_qs(urlparse(self.path).query)
                q = (query.get("q") or [""])[0]
                market = (query.get("market") or ["cn"])[0]
                self._json({"results": directory.search(q, market, limit=8),
                            "total": len(directory),
                            "as_of": directory.freshness(market)})
            elif path == "/api/appinfo":
                demo = bool(getattr(data, "demo", False))
                cli = getattr(data, "_cli", None)
                self._json({"demo": demo,
                            "trial": bool(not demo and cli is not None
                                          and using_trial_key(cli)),
                            "setup_url": None})
            elif path == "/api/bigly/meta":
                self._json({"tool": TOOL_META, "demo": getattr(data, "demo", False)})
            else:
                self._send(404, b"not found", "text/plain; charset=utf-8")

        def do_POST(self):  # noqa: N802
            path = urlparse(self.path).path
            if path not in ("/api/bigly/channel", "/api/bigly/backtest"):
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, json.JSONDecodeError):
                self._json({"error": "请求体不是合法 JSON"}, 400)
                return
            try:
                if path.endswith("/channel"):
                    self._json(run_channel(data, payload))
                else:
                    self._json(run_backtest(data, payload))
            except Exception as e:  # noqa: BLE001 - 网关错误统一转行内提示
                self._json({"error": f"{type(e).__name__}: {e}"}, 502)

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="波段（Bigly）独立 Web 服务")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--demo", action="store_true",
                        help="内置样例数据，无需凭证不联网")
    args = parser.parse_args(argv)
    data = build_data(args.demo)
    if not args.demo:
        print("提示：真实取数需要 finpipe 凭证（FINPIPE_CLIENT_ID/SECRET 或 "
              "~/.finpipe/credentials.env）；无凭证可加 --demo 看样例。", file=sys.stderr)
    print(f"波段 · http://{args.host}:{args.port}/tools/bigly/"
          + ("（演示数据）" if args.demo else ""), file=sys.stderr)
    ThreadingHTTPServer((args.host, args.port),
                        make_handler(data)).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
