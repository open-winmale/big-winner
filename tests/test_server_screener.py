"""门户级集成：筛选页与 /api/screener 在 --demo 模式全走通（真线程服务）。"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import bigwinner.shouxi.server as srv


@pytest.fixture(scope="module")
def base_url():
    srv.RUNTIME.demo = True
    srv._SCREENER_DATA = None   # 强制按 demo 重建筛选取数实例
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    srv.RUNTIME.demo = False
    srv._SCREENER_DATA = None


def _get_text(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode("utf-8")


def _post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_screener_page_served(base_url):
    status, html = _get_text(base_url + "/tools/screener/")
    assert status == 200
    assert "筛选" in html and "开始过筛" in html


def test_index_lists_screener(base_url):
    status, html = _get_text(base_url + "/")
    assert status == 200
    assert "筛选" in html and "/tools/screener/" in html


def _get_json(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def test_api_tools_lists_screener_without_internal_keys(base_url):
    status, body = _get_json(base_url + "/api/tools")
    assert status == 200
    entry = next(t for t in body["tools"] if t["slug"] == "screener")
    assert entry["title"] == "筛选"
    assert "page" not in entry and "web_dir" not in entry


def test_api_screener_demo_run(base_url):
    status, body = _post(base_url + "/api/screener", {"symbol": "600519"})
    assert status == 200
    assert body["demo"] is True
    assert body["symbol"] == "600519"
    assert body["conditions"] == srv.scr.DEFAULT_CONDITIONS
    assert body["checks"]["yield_ge3"] is True
    assert body["passed"] is True
    assert "disclaimer" in body


def test_api_screener_custom_conditions(base_url):
    status, body = _post(base_url + "/api/screener",
                         {"symbol": "000858",
                          "conditions": ["yield_ge3", "stable_yield"]})
    assert status == 200
    assert set(body["checks"]) == {"yield_ge3", "stable_yield"}
    assert body["checks"]["stable_yield"] is True
    assert body["metrics"]["payout_ttm"] is None or isinstance(
        body["metrics"]["payout_ttm"], float)


def test_api_screener_rejects_non_a_share(base_url):
    for bad in ("AAPL", "00700", "6005190"):
        status, body = _post(base_url + "/api/screener", {"symbol": bad})
        assert status == 400
        assert "A 股 6 位" in body["error"]


def test_api_screener_rejects_unknown_condition(base_url):
    status, body = _post(base_url + "/api/screener",
                         {"symbol": "600519", "conditions": ["nope"]})
    assert status == 400
    assert "未知条件" in body["error"]


def test_api_screener_failed_stock_reports_breakpoint(base_url):
    status, body = _post(base_url + "/api/screener", {"symbol": "688981"})
    assert status == 200
    assert body["passed"] is False
    assert len(body["failed"]) == 3
    assert all({"id", "name", "column", "value"} <= set(f) for f in body["failed"])
