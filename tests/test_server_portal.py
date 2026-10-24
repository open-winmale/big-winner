"""单端口门户：收息佬 :8787 同时服务工具总览页 + 波段（离线 demo 测试）。

验证 --demo 下：总览页列出波段、/tools/bigly/ 页面与 API 全部走通、
注册表不外泄内部键；收息佬自己的页面不受 web_dir 改动影响。
"""
from __future__ import annotations

import json
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
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
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


def test_appinfo_demo_reports_no_trial(base_url):
    """demo 模式用罐头数据不消耗 Key：appinfo 恒 trial=False。"""
    with urllib.request.urlopen(base_url + "/api/appinfo") as r:
        info = json.load(r)
    assert info["demo"] is True and info["trial"] is False
    assert info["setup_url"] == "/setup.html"


def test_using_trial_key_env_fallback(monkeypatch):
    """finpipe 不可用时的退化路径：未显式配置即视为体验 Key。"""
    import sys

    from bigwinner.common.fetchers import using_trial_key

    class Cli:
        client_id = "someone"

    # 模拟未安装 finpipe：父子模块缓存都要置 None（全量跑时子模块可能已被先前的测试导入并缓存）
    monkeypatch.setitem(sys.modules, "finpipe", None)
    monkeypatch.setitem(sys.modules, "finpipe._experience", None)
    monkeypatch.delenv("FINPIPE_CLIENT_ID", raising=False)
    monkeypatch.delenv("OPEN_PLATFORM_CLIENT_ID", raising=False)
    assert using_trial_key(Cli()) is True
    monkeypatch.setenv("FINPIPE_CLIENT_ID", "mine")
    assert using_trial_key(Cli()) is False


def test_fetcher_uses_trial_key(monkeypatch):
    """自有凭证 → False；体验凭证 → True（比对 finpipe 内部体验凭证）。"""
    from bigwinner.common.fetchers import FinpipeFetcher, using_trial_key

    class Cli:
        def __init__(self, cid):
            self.client_id = cid

    monkeypatch.delenv("FINPIPE_CLIENT_ID", raising=False)
    monkeypatch.delenv("OPEN_PLATFORM_CLIENT_ID", raising=False)
    own = FinpipeFetcher(client=Cli("my-own"), hk_client=object())
    assert own.uses_trial_key() is False
    pytest.importorskip("finpipe")
    from finpipe._experience import credentials as _exp
    trial = FinpipeFetcher(client=Cli(_exp()[0]), hk_client=object())
    assert trial.uses_trial_key() is True
    assert using_trial_key(Cli("other")) is False
