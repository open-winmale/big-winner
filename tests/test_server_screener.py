"""门户级集成：筛选页与 /api/screener 在 --demo 模式全走通（真线程服务）。"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import bigwinner.shouxi.server as srv


@pytest.fixture(scope="module")
def base_url():
    srv.RUNTIME.demo = True
    srv._SCREENER_DATA = None   # 强制按 demo 重建筛选取数实例
    # 本模块测旧多页托管；本机构建过网页版时（web_dist 存在）强制走 legacy 分支
    web_dist_orig = srv.WEB_DIST
    srv.WEB_DIST = web_dist_orig.parent / "__no_spa__"
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    srv.WEB_DIST = web_dist_orig
    srv.RUNTIME.demo = False
    srv._SCREENER_DATA = None


def _get_text(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode("utf-8")


def _get_json(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


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
    assert "选股" in html and "开始选股" in html and "格雷厄姆" in html


def test_index_lists_screener(base_url):
    status, html = _get_text(base_url + "/")
    assert status == 200
    assert "/tools/screener/" in html


def test_api_tools_lists_screener_without_internal_keys(base_url):
    status, body = _get_json(base_url + "/api/tools")
    assert status == 200
    entry = next(t for t in body["tools"] if t["slug"] == "screener")
    assert entry["title"] == "选股"
    assert "page" not in entry and "web_dir" not in entry


def test_api_screener_high_yield_demo(base_url):
    status, body = _post(base_url + "/api/screener", {"strategy": "high_yield_3"})
    assert status == 200
    assert body["demo"] is True
    assert body["strategy"]["id"] == "high_yield_3"
    assert body["columns"][0]["key"] == "$BONUS_RATE_TTM_LAST"
    assert body["rows"]
    for row in body["rows"]:
        assert row["values"]["$BONUS_RATE_TTM_LAST"] >= 0.03
    assert "disclaimer" in body


def test_api_screener_graham_demo(base_url):
    status, body = _post(base_url + "/api/screener", {"strategy": "graham"})
    assert status == 200
    assert body["rows"]
    for row in body["rows"]:
        assert row["values"]["$PE_TTM_LAST"] < 15
        assert row["values"]["$PB_TTM_LAST"] < 1.5
    pe_list = [r["values"]["$PE_TTM_LAST"] for r in body["rows"]]
    assert pe_list == sorted(pe_list)                    # PE 升序


def test_api_screener_custom_demo(base_url):
    status, body = _post(base_url + "/api/screener",
                         {"custom": {"yield_gte": "3", "pe_lt": "15"}, "limit": 30})
    assert status == 200
    assert body["strategy"]["id"] == "custom"
    assert body["limit"] == 30
    for row in body["rows"]:
        assert row["values"]["$BONUS_RATE_TTM_LAST"] >= 0.03
        assert row["values"]["$PE_TTM_LAST"] < 15


def test_api_screener_limit_clamped(base_url):
    status, body = _post(base_url + "/api/screener",
                         {"strategy": "high_yield_3", "limit": 9999})
    assert status == 200
    assert body["limit"] == 200


def test_api_screener_rejects_unknown_strategy(base_url):
    for bad in ("nope", None):
        status, body = _post(base_url + "/api/screener", {"strategy": bad})
        assert status == 400
        assert "未知策略" in body["error"]


def test_api_screener_rejects_empty_custom(base_url):
    status, body = _post(base_url + "/api/screener", {"custom": {}})
    assert status == 400
    assert "至少填一个条件" in body["error"]


def test_screener_data_real_mode_builds_platform_source():
    """真实模式的数据源必须存在且可构造（回归：改名后 server 仍引用旧类名）。"""
    srv.RUNTIME.demo = False
    srv._SCREENER_DATA = None
    try:
        data = srv.screener_data()
        assert isinstance(data, srv.scr.PlatformScreenerSource)
    finally:
        srv._SCREENER_DATA = None
