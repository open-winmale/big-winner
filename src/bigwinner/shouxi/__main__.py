"""收息佬独立入口：python -m bigwinner.shouxi（:8787，--demo 支持离线样例）。"""
import sys

from bigwinner.shouxi.server import main

if __name__ == "__main__":
    sys.exit(main())
