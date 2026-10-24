"""波段独立入口：python -m bigwinner.bigly（:8788，--demo 支持离线样例）。"""
import sys

from bigwinner.bigly.server import main

if __name__ == "__main__":
    sys.exit(main())
