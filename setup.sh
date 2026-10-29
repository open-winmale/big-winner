#!/bin/sh
# big-winner 安装引导（Linux）：确保 Python 3.10+（含 pip）后进入安装向导。
# 命令口径见 AGENTS.md。
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
    echo "[setup] 未检测到 Python 3.10+，尝试用系统包管理器安装（需要 sudo）..."
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update && sudo apt-get install -y python3 python3-pip
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y python3 python3-pip
    elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -S --noconfirm python python-pip
    else
        echo "[setup] 未识别的包管理器。请手动安装 Python ≥ 3.10 与 pip 后重试。"
        exit 1
    fi
    for cand in python3 python; do
        if command -v "$cand" >/dev/null 2>&1 && pyok "$cand"; then
            PY="$cand"
            break
        fi
    done
fi

if [ -z "$PY" ]; then
    echo "[setup] 未能自动安装 Python 3.10+。请按发行版手册安装后重新运行本脚本。"
    exit 1
fi

# pip 缺失会让向导装 wmshare 一步失败，先补齐
if ! "$PY" -m pip --version >/dev/null 2>&1; then
    echo "[setup] 检测到 pip 缺失，尝试安装..."
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get install -y python3-pip
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y python3-pip
    elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -S --noconfirm python-pip
    fi
fi

echo "[setup] Python: $PY ($("$PY" --version 2>&1))"
exec "$PY" setup_wizard.py "$@"
