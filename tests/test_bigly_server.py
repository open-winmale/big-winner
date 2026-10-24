"""波段·独立服务：路由、--demo 离线、与收息佬互不影响、免责声明存在。"""
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
    assert "波段" in html and "echarts" in html


def test_channel_endpoint_demo(base_url):
    base, _ = base_url
    status, body = _post(base + "/api/bigly/channel",
                         {"symbol": "600519", "metric": "pb", "window": "3y"})
    assert status == 200
    assert body["demo"] is True
    assert {"lower2", "lower1", "upper1", "upper2", "z", "zone", "coverage"} <= set(body["channel"])
    assert body["channel"]["metric_series_n"] == 730
    assert body["levels"]["buy_price"] > 0
    # 区间分布与极值：三区计数完备、占比和为 1
    z = body["channel"]["zones"]
    assert z["below_low"]["days"] + z["inside"]["days"] + z["above_high"]["days"] == z["n"]
    assert abs(z["below_low"]["ratio"] + z["inside"]["ratio"] + z["above_high"]["ratio"] - 1) < 1e-9
    ex = body["extremes"]
    assert ex["low"]["price"] <= ex["high"]["price"]
    assert ex["low"]["premium_pct"] >= 0  # 现价不低于窗口最低收盘（溢出为正）


def test_channel_endpoint_6m_window(base_url):
    """半年窗口：demo 序列与日 K 都按窗口截断。"""
    base, _ = base_url
    status, body = _post(base + "/api/bigly/channel",
                         {"symbol": "600519", "metric": "pb", "window": "6m"})
    assert status == 200
    assert body["channel"]["metric_series_n"] == 122
    bars = DemoBiglyData().bars("600519", "6m")
    assert len(bars) == 130
    dates = [b["date"] for b in bars]
    assert dates == sorted(dates)  # 升序


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
    assert bt["roundtrips_done"] >= 1  # 窗口内多轮进出回放
    ps = body["price_stats"]
    assert ps["n"] == len(bars)
    assert ps["below_buy"]["days"] + ps["inside"]["days"] + ps["above_sell"]["days"] == ps["n"]
    cmp_ = body["compare"]
    assert cmp_["hold"]["return_pct"] is not None
    assert set(cmp_["delta"]) == {"return_spread", "mdd_spread"}
    assert "disclaimer" in body


def test_backtest_auto_mode_suggests_then_replays(base_url):
    """auto 模式：不传 buy/sell → 后端先搜推荐区间，再按推荐值多轮回拨。"""
    base, _ = base_url
    status, body = _post(base + "/api/bigly/backtest",
                         {"symbol": "600519", "metric": "pb", "window": "6m"})
    assert status == 200 and "error" not in body
    assert body["backtest"]["hit_buy"] is True
    assert body["compare"]["hold"]["return_pct"] is not None
    sug = body["suggest"]
    if sug is None:  # 窗口内无完整进出组合 → 回退通道轨
        assert body["levels_used"]["buy_price"] > 0
        return
    ch = sug["criteria"]
    assert ch["buy_vs_avg"] <= 1e-9          # 不高估
    # 回拨用的就是推荐区间的价，且与推荐统计同口径（多轮复利）
    assert body["levels_used"]["buy_price"] == pytest.approx(sug["buy_price"])
    assert body["backtest"]["roundtrips_done"] == sug["stats"]["roundtrips_done"]
    assert body["backtest"]["return_pct"] == pytest.approx(sug["stats"]["return_pct"])


def test_backtest_auto_mode_still_validates_metric(base_url):
    base, _ = base_url
    status, body = _post(base + "/api/bigly/backtest",
                         {"symbol": "600519", "metric": "rsi", "window": "1y"})
    assert body["error"] and "metric" in body["error"]


def test_real_fetcher_bars_sorted_ascending():
    """store 返回新在前；fetcher 必须转成旧→新升序（拨测状态机的前提）。"""
    from bigwinner.bigly.fetchers import FinpipeBiglyData

    class StubCli:
        max_limit = 100

        def call(self, name, **kw):
            assert name == "kline.query_bars_adj" and kw["adj"] == "qfq"
            return [{"date": "2026-10-23", "open": 3, "high": 3, "low": 3, "close": 3},
                    {"date": "2026-10-21", "open": 1, "high": 1, "low": 1, "close": 1},
                    {"date": "2026-10-22", "open": 2, "high": 2, "low": 2, "close": 2}]

    bars = FinpipeBiglyData(client=StubCli()).bars("600519", "1y")
    dates = [b["date"] for b in bars]
    assert dates == sorted(dates) == ["2026-10-21", "2026-10-22", "2026-10-23"]


def test_symbols_search_endpoint(base_url):
    """代码搜索：与收息佬共用离线代码目录（finpipe 未装时空结果不报错）。"""
    base, _ = base_url
    status, body = _get(base + "/api/bigly/symbols?q=maotai")
    body = json.loads(body)
    assert status == 200
    assert "results" in body and "total" in body
    if body["results"]:
        first = body["results"][0]
        assert {"code", "name", "market"} <= set(first)


def test_symbols_search_empty_query(base_url):
    base, _ = base_url
    status, body = _get(base + "/api/bigly/symbols?q=")
    body = json.loads(body)
    assert status == 200 and body["results"] == []


def test_shouxi_portal_registry():
    """单端口门户：波段已注册进收息佬 TOOLS，页面文件仍在波段包内。"""
    import bigwinner.shouxi.server as srv

    assert "dividend-xray" in srv.TOOLS
    entry = srv.TOOLS["bigly"]
    assert entry["page"] == "bigly.html"
    assert (srv.Path(entry["web_dir"]) / "bigly.html").is_file()


def test_appinfo_demo_reports_no_trial(base_url):
    """波段独立 server：demo 模式不消耗 Key，setup_url 为 None（无 setup 页）。"""
    base, _ = base_url
    with urllib.request.urlopen(base + "/api/appinfo") as r:
        info = json.load(r)
    assert info["demo"] is True and info["trial"] is False
    assert info["setup_url"] is None
