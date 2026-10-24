"""构建在线演示静态站：python demo/build.py → demo/site/

原理：把 src/bigwinner 的全部 Python 源码打进 python-bundle.js，页面在浏览器里
用 Pyodide 执行真实服务端代码（demo 模式、罐头数据），pybridge.js 拦截 /api/*
与 /export/* 请求转发给同一套 HANDLERS —— 与 pytest / 本地服务零逻辑分叉。

产物为纯静态文件，可托管于任何静态服务（GitHub Pages / 本地 http.server）。
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
SHOUXI_WEB = SRC / "bigwinner" / "shouxi" / "web"
BIGLY_WEB = SRC / "bigwinner" / "bigly" / "web"
OUT = Path(__file__).resolve().parent / "site"


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

    # ---- Python 源码打包 ----
    (OUT / "python-bundle.js").write_text(build_python_bundle(), encoding="utf-8")

    # ---- 静态资源 ----
    shutil.copy(Path(__file__).parent / "pybridge.js", OUT / "pybridge.js")
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
    shouxi = (SHOUXI_WEB / "dividend_xray.html").read_text(encoding="utf-8")
    shouxi = _replace(shouxi, [
        ('href="/assets/base.css"', 'href="assets/base.css"'),
        ("<title>持仓收息透视表 · 收息佬</title>",
         "<title>持仓收息透视表 · 收息佬 · 在线演示</title>"),
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
        ('<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>',
         '<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>\n'
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
