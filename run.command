#!/bin/bash
# big-winner 日常启动（macOS）：双击运行，门户 http://127.0.0.1:8787
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
    echo "[run] 未检测到 Python 3.10+。请先双击 setup.command 完成安装。"
    exit 1
fi
exec "$PY" run.py "$@"
