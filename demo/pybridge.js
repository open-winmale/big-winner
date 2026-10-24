/* 浏览器内演示桥：用 Pyodide 跑真实的服务端 Python（与 pytest 同一套 HANDLERS），
   拦截页面里的 /api/* 与 /export/* 请求，免后端、免安装。
   由 demo/build.py 注入到 demo 页面（先于页面自身脚本加载）。 */
(function () {
  'use strict';
  var PYODIDE_BASE = 'https://cdn.jsdelivr.net/pyodide/v0.26.4/full/';

  var overlay = document.createElement('div');
  overlay.style.cssText =
    'position:fixed;inset:0;z-index:9999;display:flex;flex-direction:column;' +
    'align-items:center;justify-content:center;gap:10px;background:rgba(248,250,252,.96);' +
    "font:14px/1.6 -apple-system,'PingFang SC','Microsoft YaHei',sans-serif;color:#334155;";
  overlay.innerHTML =
    '<div style="font-size:15px;font-weight:600">正在加载浏览器内演示环境…</div>' +
    '<div style="color:#64748b">首次约 10–20 秒（下载 Python 运行时），之后全部本地计算</div>' +
    '<div id="bigdemo-status" style="color:#94a3b8;font-size:12px"></div>';
  document.addEventListener('DOMContentLoaded', function () {
    document.body.appendChild(overlay);
  });
  if (document.body) document.body.appendChild(overlay);

  function setStatus(t) {
    var el = overlay.querySelector('#bigdemo-status');
    if (el) el.textContent = t;
  }

  var readyPromise = null;
  var apiFn = null;

  var BOOTSTRAP = [
    'import json, sys',
    'sys.path.insert(0, "/src")',
    'import bigwinner.shouxi.server as srv',
    'from urllib.parse import parse_qs',
    'srv.RUNTIME.demo = True',
    '',
    'def _csv_export(query):',
    '    items = json.loads((parse_qs(query).get("positions") or ["[]"])[0])',
    '    positions = srv.fetchers.positions_from_payload(items)',
    '    if not positions:',
    '        return 400, {"error": "没有有效持仓"}',
    '    result = srv.t1.analyze(positions, srv.RUNTIME.fetcher(), deep=False)',
    '    return 200, "\\ufeff" + srv.xray_csv(result)',
    '',
    'def _route(method, path, query, body_text):',
    '    if method == "GET":',
    '        if path == "/api/tools":',
    '            return 200, {"tools": [{k: v for k, v in t.items() if k not in ("page", "web_dir")} for t in srv.TOOLS.values()], "demo": True}',
    '        if path == "/api/health":',
    '            return 200, {"ok": True, "demo": True}',
    '        if path in ("/api/symbols", "/api/bigly/symbols"):',
    '            q = (parse_qs(query).get("q") or [""])[0]',
    '            market = (parse_qs(query).get("market") or ["cn"])[0]',
    '            return 200, {"results": srv.DIRECTORY.search(q, market, limit=8), "total": len(srv.DIRECTORY), "as_of": srv.DIRECTORY.freshness(market)}',
    '        if path == "/api/bigly/meta":',
    '            return 200, {"tool": srv.TOOLS["bigly"], "demo": True}',
    '        if path == "/export/xray.csv":',
    '            return _csv_export(query)',
    '    if method == "POST" and path.startswith("/api/"):',
    '        slug = path[len("/api/"):].removesuffix("/run")',
    '        fn = srv.HANDLERS.get(slug)',
    '        if not fn:',
    '            return 404, {"error": "unknown: " + slug}',
    '        try:',
    '            payload = json.loads(body_text or "{}")',
    '        except Exception:',
    '            return 400, {"error": "请求体不是合法 JSON"}',
    '        try:',
    '            return 200, fn(payload)',
    '        except srv.ToolError as e:',
    '            return 400, {"error": str(e)}',
    '    return 404, {"error": "not found"}',
    '',
    'def demo_api(method, path, query, body_text):',
    '    try:',
    '        status, payload = _route(method, path, query, body_text)',
    '    except Exception as e:',
    '        status, payload = 500, {"error": type(e).__name__ + ": " + e}',
    '    if isinstance(payload, str):',
    '        body = payload',
    '    else:',
    '        body = json.dumps(payload, ensure_ascii=False, default=str)',
    '    return json.dumps([status, body])',
  ].join('\n');

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = src;
      s.onload = resolve;
      s.onerror = function () { reject(new Error('加载失败: ' + src)); };
      document.head.appendChild(s);
    });
  }

  function fsWrite(py, rel, text) {
    var path = '/src/' + rel;
    var dir = path.slice(0, path.lastIndexOf('/'));
    var parts = dir.split('/');
    var cur = '';
    for (var i = 0; i < parts.length; i++) {
      cur += parts[i] + '/';
      if (parts[i] && !py.FS.analyzePath(cur).exists) py.FS.mkdir(cur);
    }
    py.FS.writeFile(path, text);
  }

  function init() {
    return loadScript(PYODIDE_BASE + 'pyodide.js')
      .then(function () {
        setStatus('Python 运行时已下载，正在初始化…');
        return loadPyodide({ indexURL: PYODIDE_BASE });
      })
      .then(function (py) {
        setStatus('正在载入工具代码…');
        return py.loadPackage('sqlite3').then(function () { return py; });
      })
      .then(function (py) {
        var files = window.PY_FILES || {};
        Object.keys(files).forEach(function (rel) { fsWrite(py, rel, files[rel]); });
        py.runPython(BOOTSTRAP);
        apiFn = py.globals.get('demo_api');
      });
  }

  function ready() {
    if (!readyPromise) {
      readyPromise = init();
      readyPromise.then(function () {
        overlay.remove();
        document.dispatchEvent(new CustomEvent('bigdemo-ready'));
      }, function (e) {
        setStatus('加载失败：' + e.message + '（请检查网络后刷新重试）');
      });
    }
    return readyPromise;
  }

  var origFetch = window.fetch ? window.fetch.bind(window) : null;
  window.fetch = function (input, init) {
    var url = typeof input === 'string' ? input : (input && input.url) || '';
    var mApi = url.match(/\/api\/(.*)$/);
    var mCsv = url.match(/\/export\/xray\.csv(\?.*)?$/);
    if (!mApi && !mCsv) return origFetch(input, init);
    return ready().then(function () {
      var u = new URL(url, location.href);
      var raw = apiFn((init && init.method) || 'GET', u.pathname,
        u.search.replace(/^\?/, ''), (init && init.body) ? String(init.body) : '');
      var pair = JSON.parse(raw);
      var ctype = (mCsv && pair[0] === 200)
        ? 'text/csv; charset=utf-8'
        : 'application/json; charset=utf-8';
      return new Response(pair[1], { status: pair[0], headers: { 'Content-Type': ctype } });
    });
  };

  /* 透视表导出：demo 页里 app.js 的导出逻辑被 build.py 替换为调用此函数 */
  window.__demoExport = function (query) {
    return ready().then(function () {
      var raw = apiFn('GET', '/export/xray.csv', query || '', '');
      var pair = JSON.parse(raw);
      var blob = new Blob([pair[1]], { type: 'text/csv;charset=utf-8' });
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'xray_demo.csv';
      document.body.appendChild(a);
      a.click();
      a.remove();
    });
  };

  ready();
  window.BigDemo = { ready: ready };
})();
