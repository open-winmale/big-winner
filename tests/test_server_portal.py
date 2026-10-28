"""单端口门户：收息佬 :8787 同时服务工具总览页 + 波段（离线 demo 测试）。

验证 --demo 下：总览页列出波段、/tools/bigly/ 页面与 API 全部走通、
注册表不外泄内部键；收息佬自己的页面不受 web_dir 改动影响。
"""
from __future__ import annotations

import json
import pathlib  # noqa: F401 - monkeypatch "pathlib.Path.home" 字符串目标的可读性提示
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import bigwinner.shouxi.server as srv
from bigwinner.bigly.fetchers import DemoBiglyData


@pytest.fixture(scope="module")
def base_url():
    srv.RUNTIME.demo = True
    srv._BIGLY_DATA = None  # 强制按 demo 重建波段取数实例
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
    srv._BIGLY_DATA = None


def _get_text(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode("utf-8")


def _get_json(url):
    status, text = _get_text(url)
    return status, json.loads(text)


def _post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def test_index_lists_both_tools(base_url):
    base = base_url
    status, html = _get_text(base + "/")
    assert status == 200
    assert "收息佬" in html and "/tools/dividend-xray/" in html
    assert "波段" in html and "/tools/bigly/" in html


def test_bigly_page_served_from_bigly_web_dir(base_url):
    """页面物理上仍在波段包内，只是被门户进程读出来发。"""
    base = base_url
    status, html = _get_text(base + "/tools/bigly/")
    assert status == 200
    assert "波段" in html and "echarts" in html


def test_dividend_xray_page_unaffected(base_url):
    base = base_url
    status, html = _get_text(base + "/tools/dividend-xray/")
    assert status == 200
    assert "收息佬" in html


def test_api_tools_lists_bigly_and_hides_internal_keys(base_url):
    base = base_url
    status, body = _get_json(base + "/api/tools")
    assert status == 200
    slugs = {t["slug"] for t in body["tools"]}
    assert {"dividend-xray", "bigly"} <= slugs
    for t in body["tools"]:
        assert "page" not in t and "web_dir" not in t


def test_bigly_meta_via_portal(base_url):
    base = base_url
    status, body = _get_json(base + "/api/bigly/meta")
    assert status == 200
    assert body["tool"]["title"] == "波段"
    assert body["demo"] is True


def test_bigly_symbols_via_portal(base_url):
    base = base_url
    status, body = _get_json(base + "/api/bigly/symbols?q=")
    assert status == 200
    assert "results" in body and "total" in body


def test_bigly_channel_via_portal(base_url):
    base = base_url
    status, body = _post(base + "/api/bigly/channel",
                         {"symbol": "600519", "metric": "pb", "window": "6m"})
    assert status == 200
    assert body["demo"] is True
    assert {"lower2", "lower1", "upper1", "upper2", "z", "zone"} <= set(body["channel"])
    assert body["levels"]["buy_price"] > 0


def test_bigly_backtest_auto_via_portal(base_url):
    base = base_url
    status, body = _post(base + "/api/bigly/backtest",
                         {"symbol": "600519", "metric": "pb", "window": "6m"})
    assert status == 200 and "error" not in body
    assert body["backtest"]["hit_buy"] is True
    assert "disclaimer" in body


def test_registry_entry_points_to_existing_page():
    """注册表里的 bigly 条目必须指向真实存在的页面文件。"""
    entry = srv.TOOLS["bigly"]
    page = srv.Path(entry["web_dir"]) / entry["page"]
    assert page.is_file()


def test_appinfo_demo_reports_snapshot(base_url):
    """demo 模式：appinfo 报告快照日期与示例标的，且不再有 trial 字段。"""
    with urllib.request.urlopen(base_url + "/api/appinfo") as r:
        info = json.load(r)
    assert info["demo"] is True
    assert info["setup_url"] == "/setup.html"
    assert "trial" not in info
    if "demo_as_of" in info:
        assert info["demo_symbols"], "报了截止日期就应报示例标的"


def test_has_own_credentials(monkeypatch, tmp_path):
    """只认显式配置：环境变量或 ~/.wmshare/credentials.env；SDK 体验凭证不算。"""
    from bigwinner.common.fetchers import has_own_credentials

    monkeypatch.delenv("WMSHARE_CLIENT_ID", raising=False)
    monkeypatch.delenv("OPEN_PLATFORM_CLIENT_ID", raising=False)
    monkeypatch.delenv("WMSHARE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("OPEN_PLATFORM_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert has_own_credentials() is False

    monkeypatch.setenv("WMSHARE_CLIENT_ID", "mine")
    monkeypatch.setenv("WMSHARE_CLIENT_SECRET", "mine-secret")
    assert has_own_credentials() is True

    monkeypatch.delenv("WMSHARE_CLIENT_ID", raising=False)
    monkeypatch.delenv("WMSHARE_CLIENT_SECRET", raising=False)
    cred = tmp_path / ".wmshare" / "credentials.env"
    cred.parent.mkdir()
    cred.write_text("WMSHARE_CLIENT_ID=x\nWMSHARE_CLIENT_SECRET=y\n")
    assert has_own_credentials() is True


def test_main_auto_demo_without_credentials(monkeypatch, capsys, tmp_path):
    """体验 Key 下线后：无自有凭证 + 无 --demo → main 自动进演示模式并在控制台注明。"""
    from bigwinner.common import fetchers

    for var in ("WMSHARE_CLIENT_ID", "OPEN_PLATFORM_CLIENT_ID",
                "WMSHARE_CLIENT_SECRET", "OPEN_PLATFORM_CLIENT_SECRET"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    class FakeServer:
        def __init__(self, addr, handler):
            pass

        def serve_forever(self):
            raise KeyboardInterrupt  # 起服务即退出，只验证启动路径与文案

    monkeypatch.setattr(srv, "ThreadingHTTPServer", FakeServer)

    assert srv.main(["--port", "8799"]) == 0
    out = capsys.readouterr().out
    assert "演示模式" in out
    assert "快照" in out
    assert srv.RUNTIME.demo is True
    srv.RUNTIME.demo = False


def test_main_real_mode_with_credentials(monkeypatch, capsys, tmp_path):
    """有自有凭证时不自动降级：照常进真实取数模式。"""
    monkeypatch.setenv("WMSHARE_CLIENT_ID", "mine")
    monkeypatch.setenv("WMSHARE_CLIENT_SECRET", "mine-secret")

    class FakeServer:
        def __init__(self, addr, handler):
            pass

        def serve_forever(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(srv, "ThreadingHTTPServer", FakeServer)

    assert srv.main(["--port", "8799"]) == 0
    out = capsys.readouterr().out
    assert "真实取数" in out
    assert srv.RUNTIME.demo is False
