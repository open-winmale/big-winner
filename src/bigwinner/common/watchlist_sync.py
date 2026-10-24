"""winmale 持仓分组同步：把工具里的持仓推到 winmale 关注列表分组。

实现走 wm-skillhub 统一门面 `wm.sh run wm-watchlist`（禁止自拼 HTTP——
鉴权、token 刷新、重试都在门面里）。wm.sh 路径解析顺序：
  1) env WM_SH
  2) ~/work/gzh-workbench/scripts/wm.sh（本机软链→skillhub，与源同版）
  3) ~/work/src/end/skillhub/skills/wm-skillhub/scripts/wm.sh

流程（安全第一）：
  diff  —— view 远端分组，算"要加/不用动"，不写任何东西
  push —— group_create(缺组时) + group_add 增量并入；绝不删远端标的
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

_WM_SH_CANDIDATES = [
    os.environ.get("WM_SH", ""),
    str(Path.home() / "work/gzh-workbench/scripts/wm.sh"),
    str(Path.home() / "work/src/end/skillhub/skills/wm-skillhub/scripts/wm.sh"),
]


def _wm_sh() -> str:
    for c in _WM_SH_CANDIDATES:
        if c and Path(c).exists():
            return c
    raise RuntimeError(
        "找不到 wm.sh（winmale 门面）。设置环境变量 WM_SH 指向 "
        "skillhub 的 skills/wm-skillhub/scripts/wm.sh")


def _run_skill(skill: str, args: dict[str, Any], timeout: int = 60) -> dict[str, Any]:
    """执行 skillhub 统一门面；鉴权/token 刷新/重试都由 wm.sh 负责。"""
    cmd = ["bash", _wm_sh(), "run", skill,
           json.dumps({"args": args}, ensure_ascii=False), "--result"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"wm.sh 失败：{(proc.stderr or proc.stdout)[:300]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"wm.sh 返回非 JSON：{proc.stdout[:200]}") from exc


def _find(obj: Any, key: str) -> Any:
    """在嵌套回执里递归找 key（wm.sh 的包裹层级不保证稳定）。"""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = _find(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find(v, key)
            if found is not None:
                return found
    return None


class WatchlistSync:
    """wm-watchlist 的薄包装。每次调用都是独立子进程（token 刷新由 wm.sh 自理）。"""

    def _run(self, args: dict[str, Any], timeout: int = 60) -> dict[str, Any]:
        return _run_skill("wm-watchlist", args, timeout)

    @staticmethod
    def _find(obj: Any, key: str) -> Any:
        """在嵌套回执里递归找 key（wm.sh 的包裹层级不保证稳定）。"""
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            for v in obj.values():
                found = WatchlistSync._find(v, key)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for v in obj:
                found = WatchlistSync._find(v, key)
                if found is not None:
                    return found
        return None

    # ---- 远端读取 ----

    def view_groups(self) -> list[dict[str, Any]]:
        """返回 [{id, name, symbols: [code,...]}]。"""
        data = self._run({"action": "view"})
        groups = self._find(data, "groups") or []
        out = []
        for g in groups:
            out.append({
                "id": g.get("id", ""),
                "name": g.get("name", ""),
                "symbols": [s.get("symbol", "") for s in g.get("symbols") or []],
            })
        return out

    # ---- 同步 ----

    def diff(self, group_name: str, codes: list[str]) -> dict[str, Any]:
        """计算推送差异：哪些票已在组里、哪些会被加入。不写远端。"""
        groups = self.view_groups()
        target = next((g for g in groups if g["name"] == group_name), None)
        existing = set(target["symbols"]) if target else set()
        incoming = [c for c in codes if c not in existing]
        return {
            "group_name": group_name,
            "group_exists": target is not None,
            "group_id": target["id"] if target else None,
            "already_in": sorted(existing & set(codes)),
            "will_add": incoming,
            "remote_only": sorted(existing - set(codes)),  # 仅提示，不会被删
        }

    def push(self, group_name: str, codes: list[str]) -> dict[str, Any]:
        """把 codes 增量并入分组（建组若缺）；不删除远端多余标的。

        返回 {group_id, added, already_in}。
        """
        d = self.diff(group_name, codes)
        added: list[str] = []
        group_id = d["group_id"]
        if not d["group_exists"]:
            r = self._run({"action": "group_create",
                           "group_name": group_name, "symbols": d["will_add"]})
            group_id = self._find(r, "group_id") or ""
            added = list(d["will_add"])
        elif d["will_add"]:
            r = self._run({"action": "group_add",
                           "group_id": group_id, "symbols": d["will_add"]})
            apply_receipt = self._find(r, "apply") or {}
            added = list(d["will_add"])
            _ = apply_receipt  # 回执仅存档
        return {"group_id": group_id, "added": added,
                "already_in": d["already_in"], "remote_only": d["remote_only"]}


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class StockScreener:
    """平台选股门面：给「无持仓看市场」提供高股息观察池。

    走 `wm-screen-index` 的 conditions action（和 skillhub 同一条鉴权/门面），
    不手搓 HTTP；结果再交给分红库按日期过滤。选股接口不可用时返回空列表，
    由上层降级到关注分组/持仓。
    """

    def __init__(self, ttl: float = 600.0) -> None:
        self.ttl = ttl
        self._cache: dict[tuple[str, int], tuple[float, list[dict[str, Any]]]] = {}

    def high_yield(self, market: str = "cn", limit: int = 120) -> list[dict[str, Any]]:
        market = "hk" if str(market).lower() == "hk" else "cn"
        try:
            top_n = max(1, min(int(limit), 200))
        except (TypeError, ValueError):
            top_n = 120
        cache_key = (market, top_n)
        hit = self._cache.get(cache_key)
        if hit and time.time() - hit[0] < self.ttl:
            return hit[1]
        args = {
            "action": "conditions",
            "market": market,
            "top_n": top_n,
            "fields": ["$SYMBOL", "$NAME", "$BONUS_RATE_TTM_LAST"],
            "conditions": [{
                "type": "INDICATOR",
                "field": "$BONUS_RATE_TTM_LAST",
                "label": "股息率TTM",
                "operator": "GTE",
                "value": {"scalar": {"value": "0.03"}},
            }],
        }
        data = _run_skill("wm-screen-index", args, timeout=60)
        rows = _find(data, "rows") or []
        if not isinstance(rows, list):
            return []
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            vals = row.get("values")
            if not isinstance(vals, dict) or not vals:
                vals = row
            raw_sym = vals.get("$SYMBOL") or vals.get("symbol")
            digits = "".join(ch for ch in str(raw_sym or "") if ch.isdigit())
            if not digits:
                continue
            code = digits[-6:] if market == "cn" else "hk." + digits[-5:].zfill(5)
            if code in seen:
                continue
            seen.add(code)
            out.append({
                "code": code,
                "market": market,
                "name": str(vals.get("$NAME") or vals.get("name") or code),
                "yield_ttm": _num(vals.get("$BONUS_RATE_TTM_LAST")
                                  or vals.get("yield")),
            })
        if out:
            self._cache[cache_key] = (time.time(), out)
        return out
