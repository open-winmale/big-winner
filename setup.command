#!/bin/bash
# big-winner 安装引导（macOS）：确保 Python 3.10+ 后进入安装向导。
# 双击运行即可；被 Gatekeeper 拦截时：右键 → 打开 → 打开。命令口径见 AGENTS.md。
cd "$(dirname "$0")" || exit 1

pyok() { "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' >/dev/null 2>&1; }

PY=""
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1 && pyok "$cand"; then
        PY="$cand"
        break
    fi
done

if [ -z "$PY" ]; then
    echo "[setup] 未检测到 Python 3.10+。"
    if command -v brew >/dev/null 2>&1; then
        echo "[setup] 检测到 Homebrew，尝试 brew install python@3.12（可能需要几分钟）..."
        if brew install python@3.12; then
            PY="python3.12"
        fi
    elif command -v xcode-select >/dev/null 2>&1 && xcode-select --install 2>/dev/null; then
        echo "[setup] 已弹出苹果官方「命令行工具」安装窗口（内含 Python）。"
        echo "        安装完成后，请重新双击本文件继续。"
        exit 1
    fi
fi

if [ -z "$PY" ] || ! pyok "$PY"; then
    echo "[setup] 未能自动准备好 Python 3.10+。请手动安装："
    echo "  1. 打开 https://www.python.org/downloads/ 下载 macOS 安装包并安装"
    echo "  2. 装完后重新双击本文件"
    exit 1
fi

echo "[setup] Python: $PY ($("$PY" --version 2>&1))"
exec "$PY" setup_wizard.py "$@"
