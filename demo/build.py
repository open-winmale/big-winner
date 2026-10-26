"""构建在线演示静态站：python demo/build.py → demo/site/

原理：把 src/bigwinner 的全部 Python 源码打进 python-bundle.js，页面在浏览器里
用 Pyodide 执行真实服务端代码（demo 模式、罐头数据），pybridge.js 拦截 /api/*
与 /export/* 请求转发给同一套 HANDLERS —— 与 pytest / 本地服务零逻辑分叉。

Pyodide 运行时与 ECharts 会下载到 site/vendor/ 内（有本地缓存），线上全部
同源加载、不依赖 jsdelivr/unpkg —— 国内访问不再被 CDN 卡住。构建需要联网。

产物为纯静态文件，可托管于任何静态服务（GitHub Pages / 本地 http.server）。
"""
from __future__ import annotations

import json
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
SHOUXI_WEB = SRC / "bigwinner" / "shouxi" / "web"
BIGLY_WEB = SRC / "bigwinner" / "bigly" / "web"
OUT = Path(__file__).resolve().parent / "site"
CACHE = Path(__file__).resolve().parent / ".vendor-cache"

PYODIDE_VER = "v0.26.4"
PYODIDE_BASE = f"https://cdn.jsdelivr.net/pyodide/{PYODIDE_VER}/full/"
ECHARTS_URL = "https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"

#: Pyodide 页面加载所需的发行文件（loadPackage 所需的 lock 与包文件动态解析）
PYODIDE_FILES = ("pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm",
                 "python_stdlib.zip", "pyodide-lock.json")


def _fetch(url: str, dest: Path) -> None:
    """下载到 site 目标位置（带 demo/.vendor-cache 二级缓存，重构建不重下）。"""
    if dest.exists() and dest.stat().st_size > 0:
        return
    cached = CACHE / dest.name
    if not cached.exists() or cached.stat().st_size == 0:
        cached.parent.mkdir(parents=True, exist_ok=True)
        print(f"  下载 {url}")
        with urllib.request.urlopen(url, timeout=180) as resp, \
                cached.open("wb") as fh:
            shutil.copyfileobj(resp, fh)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(cached, dest)


def _replace(html: str, pairs: list[tuple[str, str]], label: str) -> str:
    for old, new in pairs:
        if old not in html:
            raise SystemExit(f"{label}: 未找到待替换片段：\n{old}")
        html = html.replace(old, new)
    return html


def build_python_bundle() -> str:
    files: dict[str, str] = {}
    for py in sorted((SRC / "bigwinner").rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        files[py.relative_to(SRC).as_posix()] = py.read_text(encoding="utf-8")
    return "window.PY_FILES = " + json.dumps(files, ensure_ascii=False) + ";\n"


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "assets").mkdir(parents=True)

    # ---- vendor：Pyodide 运行时 + ECharts（同源加载，不依赖外部 CDN）----
    print("vendor 运行时文件：")
    for name in PYODIDE_FILES:
        _fetch(PYODIDE_BASE + name, OUT / "vendor" / "pyodide" / name)
    lock = json.loads(
        (OUT / "vendor" / "pyodide" / "pyodide-lock.json").read_text("utf-8"))
    sqlite_fn = lock["packages"]["sqlite3"]["file_name"]
    _fetch(PYODIDE_BASE + sqlite_fn, OUT / "vendor" / "pyodide" / sqlite_fn)
    _fetch(ECHARTS_URL, OUT / "vendor" / "echarts.min.js")

    # ---- Python 源码打包 ----
    (OUT / "python-bundle.js").write_text(build_python_bundle(), encoding="utf-8")

    # ---- 静态资源 ----
    pybridge = (Path(__file__).parent / "pybridge.js").read_text(encoding="utf-8")
    # demo 站运行时走同源 vendor/，本地服务（--demo）源文件保持 CDN 不变
    pybridge = pybridge.replace(
        "const PYODIDE_BASE = 'https://cdn.jsdelivr.net/pyodide/v0.26.4/full/';",
        "const PYODIDE_BASE = 'vendor/pyodide/';")
    (OUT / "pybridge.js").write_text(pybridge, encoding="utf-8")
    shutil.copy(SHOUXI_WEB / "assets" / "base.css", OUT / "assets" / "base.css")
    shutil.copy(SHOUXI_WEB / "assets" / "trial_key.js", OUT / "assets" / "trial_key.js")
    for shot in ("shot-dividend-xray.png", "shot-bigly.png"):
        shutil.copy(SHOUXI_WEB / "assets" / shot, OUT / "assets" / shot)

    # ---- 收息佬 app.js：导出改为浏览器内生成 CSV ----
    app_js = (SHOUXI_WEB / "assets" / "app.js").read_text(encoding="utf-8")
    app_js = _replace(app_js, [(
        "window.location.href = '/export/xray.csv?positions=' + q;",
        "if (window.__demoExport) { window.__demoExport('positions=' + q); } "
        "else { window.location.href = '/export/xray.csv?positions=' + q; }",
    )], "app.js")
    (OUT / "assets" / "app.js").write_text(app_js, encoding="utf-8")

    # ---- 门户首页 ----
    index = (SHOUXI_WEB / "index.html").read_text(encoding="utf-8")
    index = _replace(index, [
        ('href="/assets/base.css"', 'href="assets/base.css"'),
        ("<title>收息佬工具集 · A 股与港股小工具</title>",
         "<title>收息佬工具集 · 在线演示</title>"),
        ('<a href="/setup.html" style="font-size:13px" class="setup-link">配置我的 Key →</a>',
         '<span class="badge ok">在线演示 · 内置样例数据</span>'),
        ('href="/tools/dividend-xray/"', 'href="shouxi.html"'),
        ('href="/tools/bigly/"', 'href="bigly.html"'),
        ('src="/assets/shot-', 'src="assets/shot-'),
    ], "index.html")
    (OUT / "index.html").write_text(index, encoding="utf-8")

    # ---- 收息佬页 ----
    DEMO_NOTE = ('<div style="background:#eff6ff;border:1px solid #bfdbfe;'
                 'border-radius:8px;padding:8px 12px;font-size:13px;color:#1d4ed8;'
                 'margin:10px 0">▶ 在线演示模式：页面内所有行情、分红、估值均为'
                 '<b>内置样例数据</b>（非实时、仅供体验）；本地部署后自动使用真实数据。'
                 '首次加载运行时稍慢，之后有浏览器缓存。</div>')
    shouxi = (SHOUXI_WEB / "dividend_xray.html").read_text(encoding="utf-8")
    shouxi = _replace(shouxi, [
        ('href="/assets/base.css"', 'href="assets/base.css"'),
        ("<title>持仓收息透视表 · 收息佬</title>",
         "<title>持仓收息透视表 · 收息佬 · 在线演示</title>"),
        ('<main class="wrap">', '<main class="wrap">\n' + DEMO_NOTE),
        ('<script src="/assets/app.js"></script>',
         '<script src="pybridge.js"></script>\n'
         '<script src="python-bundle.js"></script>\n'
         '<script src="assets/app.js"></script>'),
    ], "shouxi.html")
    (OUT / "shouxi.html").write_text(shouxi, encoding="utf-8")

    # ---- 波段页 ----
    bigly = (BIGLY_WEB / "bigly.html").read_text(encoding="utf-8")
    bigly = _replace(bigly, [
        ('href="/assets/base.css"', 'href="assets/base.css"'),
        ('<main class="wrap">', '<main class="wrap">\n' + DEMO_NOTE),
        ('<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>',
         '<script src="vendor/echarts.min.js"></script>\n'
         '<script src="pybridge.js"></script>\n'
         '<script src="python-bundle.js"></script>'),
        ("</title>", " · 在线演示</title>",),
    ], "bigly.html")
    (OUT / "bigly.html").write_text(bigly, encoding="utf-8")

    n_py = len(list((SRC / "bigwinner").rglob("*.py")))
    print(f"demo/site/ 构建完成（{n_py} 个 Python 模块已打包）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
