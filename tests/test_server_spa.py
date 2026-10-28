"""网页版 SPA 托管：web_dist 存在时 / 出 SPA、旧 /tools/ 链接 302 到 hash 路由。

用 tmp_path 伪造最小 web_dist（index.html + 一个带 hash 的 js），
不依赖前端构建产物是否在本地存在。
"""
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
def spa_env(tmp_path_factory):
    web_dist = tmp_path_factory.mktemp("web_dist")
    (web_dist / "index.html").write_text(
        "<!doctype html><title>SPA</title>"
        '<script src="./assets/index-test.js"></script>', encoding="utf-8")
    assets = web_dist / "assets"
    assets.mkdir()
    (assets / "index-test.js").write_text("console.log('spa')", encoding="utf-8")

    web_dist_orig = srv.WEB_DIST
    srv.WEB_DIST = web_dist
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    srv.WEB_DIST = web_dist_orig


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ARG002
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _get(url):
    req = urllib.request.Request(url)
    try:
        with _OPENER.open(req, timeout=5) as r:
            return r.status, r.read().decode("utf-8"), r.headers
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8"), exc.headers


def test_spa_index_served_at_root(spa_env):
    base = spa_env
    status, html, headers = _get(base + "/")
    assert status == 200
    assert "SPA" in html
    assert "text/html" in headers["Content-Type"]


def test_spa_asset_served(spa_env):
    base = spa_env
    status, body, headers = _get(base + "/assets/index-test.js")
    assert status == 200
    assert "console.log" in body
    assert "javascript" in headers["Content-Type"]


def test_legacy_tool_url_redirects_to_hash_route(spa_env):
    base = spa_env
    for path, target in (
        ("/tools/dividend-xray/", "/#/shouxi"),
        ("/tools/bigly/", "/#/bigly"),
        ("/tools/screener/", "/#/screener"),
        ("/setup.html", "/#/setup"),
    ):
        status, _, headers = _get(base + path)
        assert status == 302, path
        assert headers["Location"] == target, path


def test_api_unaffected_in_spa_mode(spa_env):
    base = spa_env
    status, body, headers = _get(base + "/api/health")
    assert status == 200
    assert json.loads(body)["ok"] is True
    assert "application/json" in headers["Content-Type"]


def test_unknown_tool_still_404_in_spa_mode(spa_env):
    base = spa_env
    status, _, _ = _get(base + "/tools/nope/")
    assert status == 404
