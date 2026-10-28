"""跨平台启动入口：python run.py（Windows / macOS / Linux 通用）。

等价于 `PYTHONPATH=src python -m bigwinner.shouxi` —— Windows 的 CMD 与
PowerShell 不支持 `VAR=value cmd` 前缀语法，本入口在代码里补上 src 路径，
三个平台一条命令。参数原样透传（--demo、--port 等）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from bigwinner.shouxi.server import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
