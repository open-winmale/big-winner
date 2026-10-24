"""兼容别名：等价于收息佬入口（bigwinner.shouxi.server）。

两个工具各自独立目录与入口：
    python -m bigwinner.shouxi   # 收息佬（:8787）
    python -m bigwinner.bigly    # 必赢佬（:8788）
"""
from bigwinner.shouxi.server import Handler, main  # noqa: F401

if __name__ == "__main__":
    raise SystemExit(main())
