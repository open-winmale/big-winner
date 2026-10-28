"""本地 SQLite 持久层：快照历史 + 持仓档案 + 同步记录。

设计：
- 零 ORM，标准库 sqlite3，单文件 `src/data/fptools.db`（gitignore；按本文件
  位置解析，即 bigwinner 包的上一级 data/ 目录）。
- 三张表：snapshots（每次生成的组合快照）、position_sets（持久化持仓档案，
  替代"每次重新搜索"）、sync_log（winmale 同步审计）。
- 历史快照是"超越 Excel"的核心：组合股息率/市值的时序曲线由此出。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "fptools.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    taken_at TEXT NOT NULL,            -- ISO 时间
    mode TEXT NOT NULL DEFAULT 'real', -- real | demo
    deep INTEGER NOT NULL DEFAULT 0,
    n_positions INTEGER NOT NULL,
    total_market_value REAL,
    total_dividend REAL,
    portfolio_yield REAL,
    total_profit REAL,
    payload TEXT NOT NULL              -- 完整结果 JSON（可重放渲染）
);
CREATE INDEX IF NOT EXISTS idx_snapshots_taken ON snapshots(taken_at);

CREATE TABLE IF NOT EXISTS position_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,         -- 档案名，如 "我的主仓"
    updated_at TEXT NOT NULL,
    positions TEXT NOT NULL            -- JSON: [{code,name,shares,cost}]
);

CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    synced_at TEXT NOT NULL,
    group_name TEXT NOT NULL,
    group_id TEXT,
    action TEXT NOT NULL,              -- create_and_push | push | diff
    n_symbols INTEGER NOT NULL,
    detail TEXT,                       -- JSON: 差异/回执摘要
    ok INTEGER NOT NULL DEFAULT 1
);
"""


class Store:
    """线程安全（服务为 ThreadingHTTPServer）的薄封装。"""

    def __init__(self, path: Path | None = None) -> None:
        path = path or _DEFAULT_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def _now(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S")

    # ---- 快照 ----
    def save_snapshot(self, result: dict[str, Any], deep: bool, mode: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO snapshots(taken_at, mode, deep, n_positions,"
                " total_market_value, total_dividend, portfolio_yield,"
                " total_profit, payload) VALUES (?,?,?,?,?,?,?,?,?)",
                (self._now(), mode, int(deep), len(result.get("rows") or []),
                 result.get("total_market_value"), result.get("total_dividend"),
                 result.get("portfolio_yield"), result.get("total_profit"),
                 json.dumps(result, ensure_ascii=False)))
            self._conn.commit()
            return int(cur.lastrowid)

    def snapshot_history(self, limit: int = 60) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, taken_at, mode, n_positions, total_market_value,"
                " total_dividend, portfolio_yield, total_profit"
                " FROM snapshots ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ---- 持仓档案 ----
    def save_positions(self, name: str, positions: list[dict[str, Any]]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO position_sets(name, updated_at, positions) VALUES (?,?,?)"
                " ON CONFLICT(name) DO UPDATE SET updated_at=excluded.updated_at,"
                " positions=excluded.positions",
                (name, self._now(), json.dumps(positions, ensure_ascii=False)))
            self._conn.commit()

    def load_positions(self, name: str) -> list[dict[str, Any]] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT positions FROM position_sets WHERE name=?", (name,)).fetchone()
        return json.loads(row["positions"]) if row else None

    def latest_position_set(self) -> dict[str, Any] | None:
        """最近更新的持仓档案 → 打开页面自动载入，省掉重复搜索。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT name, updated_at, positions FROM position_sets"
                " ORDER BY updated_at DESC, id DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return {
            "name": row["name"],
            "updated_at": row["updated_at"],
            "positions": json.loads(row["positions"]),
        }

    def list_position_sets(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT name, updated_at, positions FROM position_sets"
                " ORDER BY updated_at DESC").fetchall()
        return [{"name": r["name"], "updated_at": r["updated_at"],
                 "n": len(json.loads(r["positions"]))} for r in rows]

    # ---- 同步日志 ----
    def log_sync(self, group_name: str, group_id: str | None, action: str,
                 n_symbols: int, detail: dict[str, Any] | None = None,
                 ok: bool = True) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO sync_log(synced_at, group_name, group_id, action,"
                " n_symbols, detail, ok) VALUES (?,?,?,?,?,?,?)",
                (self._now(), group_name, group_id, action, n_symbols,
                 json.dumps(detail or {}, ensure_ascii=False), int(ok)))
            self._conn.commit()
