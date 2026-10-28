"""股票代码搜索：直接复用 wmshare 离线目录的全市场代码表（cn 5375 / hk 2655 / us 5687）。

零网络、零额度；wmshare 未安装时降级为「仅 6 位代码直输」，服务照常可用。
"""
from __future__ import annotations

from typing import Any

# 搜索请求在 demo / 无 wmshare 环境下的空结果提示
_UNAVAILABLE: list[dict[str, str]] = []


class SymbolDirectory:
    """包一层 wmshare Catalog.symbols_search，统一 demo 降级语义。"""

    def __init__(self) -> None:
        self._cat: Any = None
        self._tried = False

    def _catalog(self) -> Any:
        if not self._tried:
            self._tried = True
            try:
                import wmshare  # noqa: PLC0415
                self._cat = wmshare.load()
            except Exception:  # noqa: BLE001 - 未安装即降级
                self._cat = None
        return self._cat

    def search(self, query: str, market: str = "cn", limit: int = 8) -> list[dict[str, str]]:
        cat = self._catalog()
        if cat is None:
            return _UNAVAILABLE
        return [
            {"code": r["code"], "name": r["name"], "market": r["market"]}
            for r in cat.symbols_search(query, market, limit=limit)
        ]

    def freshness(self, market: str = "cn") -> str | None:
        """代码目录新鲜度（快照日期）。"""
        cat = self._catalog()
        if cat is None:
            return None
        try:
            return cat.symbols_freshness(market).get("as_of")
        except Exception:  # noqa: BLE001
            return None

    def __len__(self) -> int:
        cat = self._catalog()
        if cat is None:
            return 0
        return sum(cat.symbols_count(m) for m in ("cn", "hk", "us"))
