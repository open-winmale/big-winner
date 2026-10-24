"""必赢佬·独立服务：路由、--demo 离线、与收息佬互不影响、免责声明存在。"""
import json
import threading
import time
import urllib.request

import pytest

from bigwinner.bigly import server as bigly_srv
from bigwinner.bigly.fetchers import DemoBiglyData


@pytest.fixture(scope="module")
def base_url():
    data = DemoBiglyData()
    srv = bigly_srv.make_handler(data)
    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", port
    httpd.shutdown()


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode("utf-8")


def _post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def test_page_served_with_disclaimer_banner(base_url):
    base, _ = base_url
    status, html = _get(base + "/tools/bigly/")
    assert status == 200
    assert "免责声明" in html and "统计描述与历史回放" in html
    assert "必赢佬" in html and "echarts" in html


def test_channel_endpoint_demo(base_url):
    base, _ = base_url
    status, body = _post(base + "/api/bigly/channel",
                         {"symbol": "600519", "metric": "pb", "window": "3y"})
    assert status == 200
    assert body["demo"] is True
    assert {"lower2", "lower1", "upper1", "upper2", "z", "zone", "coverage"} <= set(body["channel"])
    assert body["channel"]["metric_series_n"] == 730
    assert body["levels"]["buy_price"] > 0


def test_channel_window_validation(base_url):
    base, _ = base_url
    status, body = _post(base + "/api/bigly/channel",
                         {"symbol": "600519", "metric": "pe", "window": "5y"})
    assert body["error"] and "3" in body["error"]  # 上限 3 年


def test_backtest_endpoint_with_stop(base_url):
    base, _ = base_url
    bars = DemoBiglyData().bars("600519", "3y")
    lows = [b["low"] for b in bars]
    highs = [b["high"] for b in bars]
    payload = {"symbol": "600519", "metric": "pb", "window": "3y",
               "buy": min(lows) * 1.02,   # 必命中买入
               "sell": max(highs) * 0.98,  # 必命中卖出
               "stop": min(lows) * 0.95}
    status, body = _post(base + "/api/bigly/backtest", payload)
    assert status == 200
    bt = body["backtest"]
    assert bt["hit_buy"] is True and bt["hit_sell"] is True
    assert bt["sell_reason"] == "target"
    assert bt["return_pct"] == pytest.approx(bt["sell_fill"] / bt["buy_fill"] - 1)
    cmp_ = body["compare"]
    assert cmp_["hold"]["return_pct"] is not None
    assert set(cmp_["delta"]) == {"return_spread", "mdd_spread"}
    assert "disclaimer" in body


def test_shouxi_server_module_untouched():
    """双工具隔离：收息佬模块照常导入，且必赢佬不在其 TOOLS 注册表里。"""
    import bigwinner.shouxi.server as srv

    assert "dividend-xray" in srv.TOOLS
    assert "bigly" not in srv.TOOLS
