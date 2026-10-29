#!/usr/bin/env python3
"""跨平台安装向导：小白双击 setup.* 进来，手动/脚本/AI agent 用子命令。

无参数 = 交互向导（数据依赖 wmshare、新版界面构建、AppID/Key 录入，每步可
跳过）；子命令供脚本与 AI agent 非交互调用，命令口径唯一来源是 AGENTS.md：

    python setup_wizard.py doctor [--json]   环境体检（退出码 0=实时就绪，
                                             1=演示模式可启动，2=内部错误）
    python setup_wizard.py install-wmshare   安装数据依赖（Gitee→GitHub→ZIP）
    python setup_wizard.py build-web         构建网页版门户（需 Node ≥ 18.18）
    python setup_wizard.py set-key --client-id X --client-secret Y
                                             保存 Key（默认联网验证）

只依赖标准库；凭证读写复用 bigwinner.common.credentials（data/fptools.db，
与页面「数据源 Key」同库同口径）。
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))

WMSHARE_GITEE = "https://gitee.com/open-winmale/wmshare"
WMSHARE_GITHUB = "https://github.com/open-winmale/wmshare"
WEB_DIR = REPO_ROOT / "web"
WEB_DIST = REPO_ROOT / "src" / "bigwinner" / "shouxi" / "web_dist"
PIP_TIMEOUT = 600


# ---------------------------------------------------------------- 环境检测

def python_info() -> dict:
    ok = sys.version_info >= (3, 10)
    return {"version": platform.python_version(), "ok": ok}


def wmshare_info() -> dict:
    try:
        import wmshare  # noqa: PLC0415
    except ImportError:
        return {"installed": False, "version": None}
    version = getattr(wmshare, "__version__", None)
    return {"installed": True, "version": str(version) if version else "unknown"}


def node_info() -> dict:
    node = shutil.which("node")
    npm = shutil.which("npm")
    version = None
    if node:
        try:
            version = subprocess.run([node, "--version"], capture_output=True,
                                     text=True, timeout=15).stdout.strip()
        except Exception:  # noqa: BLE001 - 探测失败按未装处理
            version = None
    return {"installed": bool(node and version), "version": version,
            "npm": bool(npm)}


def web_dist_built() -> bool:
    return (WEB_DIST / "index.html").is_file()


def credential_source() -> str:
    """当前凭证来源：db | env | file | none（口径与 fetchers.has_own_credentials
    一致，只是区分了来源便于体检展示与 set-key 覆盖判断）。"""
    from bigwinner.common import credentials
    if credentials.has_custom():
        return "db"
    cid = os.environ.get("WMSHARE_CLIENT_ID") or os.environ.get("OPEN_PLATFORM_CLIENT_ID")
    if cid and (os.environ.get("WMSHARE_CLIENT_SECRET")
                or os.environ.get("OPEN_PLATFORM_CLIENT_SECRET")):
        return "env"
    if Path.home().joinpath(".wmshare", "credentials.env").is_file():
        return "file"
    return "none"


def build_report() -> dict:
    creds = credential_source()
    report = {
        "python": python_info(),
        "wmshare": wmshare_info(),
        "node": node_info(),
        "web_dist": {"built": web_dist_built(), "path": str(WEB_DIST)},
        "credentials": {"has": creds != "none", "source": creds},
    }
    report["mode"] = "live" if (report["credentials"]["has"]
                                and report["wmshare"]["installed"]) else "demo"
    hints = []
    if not report["wmshare"]["installed"]:
        hints.append("数据依赖未安装（实时取数需要）：python setup_wizard.py install-wmshare")
    if not report["credentials"]["has"]:
        hints.append("未配置 Key（将进演示模式）：python setup_wizard.py set-key ... "
                     "或启动后在页面右上角「数据源 Key」粘贴")
    if not report["web_dist"]["built"]:
        if report["node"]["installed"]:
            hints.append("新版界面未构建：python setup_wizard.py build-web（当前用经典多页界面）")
        else:
            hints.append("新版界面未构建且未装 Node ≥ 18.18（当前用经典多页界面，功能完整）")
    report["hints"] = hints
    return report


# ---------------------------------------------------------------- 子步骤执行

def wmshare_install_plan(has_git: bool) -> list[tuple[str, str | None]]:
    """wmshare 安装尝试序列：命令或 None（None = 下载 ZIP 方案，不依赖 git）。

    Gitee 优先（国内网络）；每级失败自动尝试下一级。
    """
    plan = []
    if has_git:
        plan.append(("pip install git+Gitee",
                     f"git+{WMSHARE_GITEE}.git"))
        plan.append(("pip install git+GitHub",
                     f"git+{WMSHARE_GITHUB}.git"))
    plan.append(("下载 ZIP 安装（Gitee，无需 git）", None))
    return plan


def _pip_install(target: str) -> tuple[bool, str]:
    cmd = [sys.executable, "-m", "pip", "install", target]
    print(f"    $ {' '.join(cmd)}")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=PIP_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, f"安装超时（>{PIP_TIMEOUT}s）"
    if proc.returncode == 0:
        return True, "安装成功"
    tail = (proc.stdout + proc.stderr).strip().splitlines()
    return False, tail[-1] if tail else f"pip 退出码 {proc.returncode}"


def install_wmshare_zip() -> tuple[bool, str]:
    """无 git 时：下载 Gitee ZIP 解压后 pip install 本地目录。"""
    url = f"{WMSHARE_GITEE}/repository/archive/main.zip"
    print(f"    $ 下载 {url}")
    try:
        with tempfile.TemporaryDirectory() as td:
            zpath = Path(td) / "wmshare.zip"
            with urllib.request.urlopen(url, timeout=120) as resp, \
                    open(zpath, "wb") as fh:
                fh.write(resp.read())
            with zipfile.ZipFile(zpath) as zf:
                zf.extractall(td)
            root = next(Path(td).rglob("pyproject.toml")).parent
            return _pip_install(str(root))
    except Exception as exc:  # noqa: BLE001 - 网络/解压任何失败都回落失败
        return False, f"ZIP 安装失败：{exc}"


def install_wmshare() -> tuple[bool, str]:
    has_git = shutil.which("git") is not None
    for label, target in wmshare_install_plan(has_git):
        print(f"  · 尝试 {label} ...")
        ok, msg = install_wmshare_zip() if target is None else _pip_install(target)
        if ok:
            info = wmshare_info()
            return True, (f"wmshare {info.get('version') or ''} 安装成功"
                          f"（{label}）")
        print(f"    失败：{msg}")
    return False, ("三级尝试均失败。请检查网络后重试，或手动安装："
                   f"git clone {WMSHARE_GITEE}.git && pip install -e ./wmshare")


def _version_lt(version: str, floor: tuple[int, ...]) -> bool:
    """语义化版本数值比较（'v9.3.1' < (18,18) 必须按数字比，不能按字符串）。"""
    try:
        parts = [int(p) for p in version.lstrip("v").split(".")[:len(floor)]]
    except ValueError:
        return False
    while len(parts) < len(floor):
        parts.append(0)
    return tuple(parts) < floor


def build_web() -> tuple[bool, str]:
    node = node_info()
    if not node["installed"]:
        return False, ("未检测到 Node ≥ 18.18。当前仍可用（经典多页界面）；"
                       "想用新版界面请先安装 Node：winget install OpenJS.NodeJS.LTS"
                       "（Windows）/ brew install node（macOS）/ "
                       "apt install nodejs npm（Linux），然后重跑 build-web")
    if node["version"] and _version_lt(node["version"], (18, 18)):
        return False, (f"Node 版本过低（{node['version']} < 18.18），请升级后重试")
    npm = shutil.which("npm")
    for args, title in ((["ci"], "安装前端依赖"), (["run", "build"], "构建")):
        cmd = [npm, *args]
        print(f"    $ npm {' '.join(args)}（{title}）")
        try:
            proc = subprocess.run(cmd, cwd=WEB_DIR, timeout=900)
        except subprocess.TimeoutExpired:
            return False, f"npm {args[0]} 超时"
        if proc.returncode != 0:
            return False, f"npm {args[0]} 失败（退出码 {proc.returncode}），见上方输出"
    return True, "构建完成，产物已写入 src/bigwinner/shouxi/web_dist/（刷新页面即生效）"


def validate_key(client_id: str, client_secret: str,
                 client_factory=None, timeout: int = 15) -> tuple[bool, str]:
    """与页面 key-save 同口径的在线验证：调一次真实行情探测。"""
    if client_factory is None:
        def client_factory(cid: str, sec: str):  # noqa: ANN001 - 默认用真实 SDK
            import wmshare  # noqa: PLC0415
            return wmshare.Client(client_id=cid, client_secret=sec)
    try:
        client = client_factory(client_id, client_secret)
        client.call("kline.query_bars", sym="600036", limit=1)
    except Exception as exc:  # noqa: BLE001 - 凭证错/网络错都不落地
        return False, f"验证失败：{exc}"
    return True, "Key 验证通过"


def set_key_guard(existing_source: str, force: bool) -> str | None:
    """set-key 前置守卫：返回拒绝原因，None = 放行（纯函数，便于测试）。"""
    if existing_source == "none":
        return None
    if force:
        return None
    return (f"本机已有凭证（来源：{existing_source}）。如需覆盖请加 --force；"
            "如只是查看现状请运行 doctor。")


def save_key(client_id: str, client_secret: str) -> None:
    from bigwinner.common import credentials
    credentials.save(client_id, client_secret)


# ---------------------------------------------------------------- 子命令

def cmd_doctor(as_json: bool) -> int:
    try:
        report = build_report()
    except Exception as exc:  # noqa: BLE001
        print(f"doctor 内部错误：{exc}", file=sys.stderr)
        return 2
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        py, wm, node = report["python"], report["wmshare"], report["node"]
        creds = report["credentials"]
        print(f"Python   {'✓' if py['ok'] else '✗'} {py['version']}"
              f"（要求 ≥ 3.10）")
        print(f"wmshare  {'✓' if wm['installed'] else '✗ 未安装'}"
              f"{' ' + wm['version'] if wm['version'] else ''}"
              f"{'（实时取数数据依赖）' if not wm['installed'] else ''}")
        print(f"Node     {'✓ ' + node['version'] if node['installed'] else '✗ 未安装'}"
              f"（可选，仅构建新版界面需要）")
        print(f"新版界面 {'✓ 已构建' if report['web_dist']['built'] else '✗ 未构建（经典多页界面，功能完整）'}")
        src = {"db": "本机数据库 data/fptools.db", "env": "环境变量",
               "file": "~/.wmshare/credentials.env", "none": "未配置"}
        print(f"数据源 Key {'✓ ' + src[creds['source']] if creds['has'] else '✗ 未配置'}")
        print(f"运行模式 {'实时（live）' if report['mode'] == 'live' else '演示（demo，历史快照）'}")
        for hint in report["hints"]:
            print(f"  → {hint}")
        print("启动：python run.py（门户 http://127.0.0.1:8787）")
    return 0 if report["mode"] == "live" else 1


def cmd_install_wmshare() -> int:
    if wmshare_info()["installed"]:
        print("wmshare 已安装，无需重复安装（doctor 可查看版本）。")
        return 0
    ok, msg = install_wmshare()
    print(("✓ " if ok else "✗ ") + msg)
    return 0 if ok else 1


def cmd_build_web() -> int:
    if web_dist_built():
        print("新版界面已构建过。如改过 web/ 源码想重新构建，请删除 "
              "src/bigwinner/shouxi/web_dist/ 后重跑，或直接 cd web && npm run build。")
        return 0
    ok, msg = build_web()
    print(("✓ " if ok else "✗ ") + msg)
    return 0 if ok else 1


def cmd_set_key(client_id: str, client_secret: str, no_verify: bool,
                force: bool) -> int:
    if not client_id or not client_secret:
        print("✗ --client-id 与 --client-secret 都必填", file=sys.stderr)
        return 1
    reason = set_key_guard(credential_source(), force)
    if reason:
        print(f"✗ {reason}", file=sys.stderr)
        return 1
    if no_verify:
        save_key(client_id, client_secret)
        print("✓ Key 已保存（按要求跳过在线验证）。")
        return 0
    if not wmshare_info()["installed"]:
        print("✗ 未安装 wmshare，无法在线验证。先运行 install-wmshare，"
              "或确认要跳过验证时加 --no-verify。", file=sys.stderr)
        return 1
    ok, msg = validate_key(client_id, client_secret)
    if not ok:
        print(f"✗ {msg}（Key 未保存；确认 Key 本身正确仍想保存可用 --no-verify）",
              file=sys.stderr)
        return 1
    save_key(client_id, client_secret)
    print("✓ Key 已验证并保存到 data/fptools.db。重启 python run.py 即为实时模式。")
    return 0


# ---------------------------------------------------------------- 交互向导

def ask(prompt: str, default_yes: bool) -> bool:
    suffix = "（Y/n）" if default_yes else "（y/N）"
    while True:
        raw = input(f"{prompt}{suffix}: ").strip().lower()
        if not raw:
            return default_yes
        if raw in ("y", "yes", "是"):
            return True
        if raw in ("n", "no", "否", "不"):
            return False
        print("  请输入 y 或 n")


def wizard_key_flow(done: list[str]) -> None:
    source = credential_source()
    src_name = {"db": "本机数据库", "env": "环境变量",
                "file": "~/.wmshare/credentials.env", "none": ""}
    if source != "none":
        if ask(f"已配置数据源 Key（来源：{src_name[source]}），要覆盖吗", False):
            pass
        else:
            done.append("数据源 Key：保留现有配置")
            return
    else:
        print("  未配置 Key。配置后为实时模式；跳过则自动进演示模式（历史快照），"
              "之后随时可在页面右上角「数据源 Key」粘贴配置。")
        if not ask("现在配置 AppID / api-key 吗", True):
            done.append("数据源 Key：跳过（页面随时可配）")
            return
    cid = input("  AppID（client_id，open.winmale.com 申请）: ").strip()
    if not cid:
        print("  已跳过（未输入 AppID）。")
        done.append("数据源 Key：跳过")
        return
    import getpass
    sec = getpass.getpass("  api-key（client_secret，输入不回显）: ").strip()
    if not sec:
        print("  已跳过（未输入 api-key）。")
        done.append("数据源 Key：跳过")
        return
    if not wmshare_info()["installed"]:
        save_key(cid, sec)
        done.append("数据源 Key：已保存（本机未安装 wmshare，跳过在线验证；"
                    "安装后重启即实时）")
        return
    while True:
        ok, msg = validate_key(cid, sec)
        if ok:
            save_key(cid, sec)
            done.append("数据源 Key：已验证并保存（实时模式）")
            return
        print(f"  ✗ {msg}")
        choice = input("  [1]重试 [2]仍要保存 [3]取消，选几（默认 1）: ").strip() or "1"
        if choice == "2":
            save_key(cid, sec)
            done.append("数据源 Key：已保存（未通过在线验证）")
            return
        if choice == "3":
            done.append("数据源 Key：取消（未保存）")
            return


def cmd_wizard() -> int:
    done: list[str] = []
    print("=" * 62)
    print("  big-winner（收息佬）安装向导 —— 每一步都可以跳过")
    print("=" * 62)
    try:
        # [1/4] 数据依赖
        print("\n[1/4] 数据依赖 wmshare（实时取数需要；跳过则用演示快照）")
        if wmshare_info()["installed"]:
            print(f"  ✓ 已安装（{wmshare_info()['version']}），跳过。")
            done.append("数据依赖 wmshare：已安装")
        elif ask("  未安装。自动安装吗", True):
            ok, msg = install_wmshare()
            print(f"  {'✓' if ok else '✗'} {msg}")
            done.append("数据依赖 wmshare：已安装" if ok
                        else "数据依赖 wmshare：安装失败（演示模式仍可用）")
        else:
            done.append("数据依赖 wmshare：跳过（演示模式）")

        # [2/4] 新版界面
        print("\n[2/4] 新版网页界面（单页导航、页面内换 Key；需 Node ≥ 18.18）")
        if web_dist_built():
            print("  ✓ 已构建，跳过。")
            done.append("新版界面：已构建")
        else:
            node = node_info()
            if node["installed"]:
                if ask(f"  检测到 Node {node['version']}。现在构建吗（首次约 1-2 分钟）", True):
                    ok, msg = build_web()
                    print(f"  {'✓' if ok else '✗'} {msg}")
                    done.append("新版界面：已构建" if ok else "新版界面：构建失败（经典界面兜底）")
                else:
                    done.append("新版界面：跳过（经典多页界面，功能完整）")
            else:
                print("  ✗ 未安装 Node，跳过构建。当前用经典多页界面（功能完整）；")
                print("    想用新版界面：winget install OpenJS.NodeJS.LTS（Windows）/")
                print("    brew install node（macOS）/ apt install nodejs npm（Linux），")
                print("    装好后重跑本向导或 make build-web。")
                done.append("新版界面：无 Node，跳过（经典界面兜底）")

        # [3/4] Key
        print("\n[3/4] 数据源 Key（AppID + api-key；open.winmale.com 免费申请）")
        wizard_key_flow(done)

        # [4/4] 收尾
        print("\n" + "=" * 62)
        print("  安装结果")
        print("=" * 62)
        for line in done:
            print(f"  · {line}")
        print("\n  启动：python run.py  →  http://127.0.0.1:8787")
        if ask("  现在启动吗", True):
            print("  （Ctrl+C 停止服务并退出）")
            return subprocess.call([sys.executable, str(REPO_ROOT / "run.py")])
        return 0
    except KeyboardInterrupt:
        print("\n\n向导已中断。已完成：")
        for line in done:
            print(f"  · {line}")
        print("随时重新运行：python setup_wizard.py")
        return 130


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="setup_wizard",
        description="big-winner 安装向导（无参数 = 交互向导；命令口径见 AGENTS.md）")
    sub = parser.add_subparsers(dest="cmd")
    p_doc = sub.add_parser("doctor", help="环境体检（0=实时就绪 1=演示可启动 2=错误）")
    p_doc.add_argument("--json", action="store_true", help="输出 JSON")
    sub.add_parser("install-wmshare", help="安装数据依赖 wmshare")
    sub.add_parser("build-web", help="构建网页版门户（需 Node ≥ 18.18）")
    p_key = sub.add_parser("set-key", help="保存数据源 Key（默认联网验证）")
    p_key.add_argument("--client-id", required=True)
    p_key.add_argument("--client-secret", required=True)
    p_key.add_argument("--no-verify", action="store_true",
                       help="跳过在线验证（wmshare 未装时或确认要直接保存）")
    p_key.add_argument("--force", action="store_true", help="覆盖已保存的 Key")
    args = parser.parse_args(argv)

    if args.cmd == "doctor":
        return cmd_doctor(args.json)
    if args.cmd == "install-wmshare":
        return cmd_install_wmshare()
    if args.cmd == "build-web":
        return cmd_build_web()
    if args.cmd == "set-key":
        return cmd_set_key(args.client_id, args.client_secret,
                           args.no_verify, args.force)
    return cmd_wizard()


if __name__ == "__main__":
    sys.exit(main())
