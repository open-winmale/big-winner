"""页面保存的 wmshare Key 的本机存取：data/fptools.db 的 credentials 表。

为什么存数据库而不是 ~/.wmshare/credentials.env：Key 与快照/持仓同库管理，
路径由代码解析，无跨操作系统差异；data/ 已 gitignore，不会误提交。SDK 层的
环境变量/凭证文件源保持只读兼容，优先级：本库 > 环境变量 > 凭证文件。
明文存储与原凭证文件同级——分享 data/fptools.db 前应先 clear()。
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

_DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "fptools.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS credentials (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    client_id TEXT NOT NULL,
    client_secret TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
#: 测试注入点：非 None 时库文件指向它（经 set_db_path 切换，会重置连接）
db_path: Path | None = None


def set_db_path(path: Path | None) -> None:
    """切换库文件并关闭已开连接（测试隔离用；生产代码勿调）。"""
    global db_path, _conn
    with _lock:
        db_path = path
        if _conn is not None:
            _conn.close()
            _conn = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        path = db_path or _DEFAULT_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(path), check_same_thread=False)
        _conn.execute(_SCHEMA)
        _conn.commit()
    return _conn


def load() -> tuple[str, str] | None:
    """读已保存的 Key；没有返回 None。绝不写日志、不回显 secret。"""
    with _lock:
        row = _get_conn().execute(
            "SELECT client_id, client_secret FROM credentials WHERE id = 1"
        ).fetchone()
    return (str(row[0]), str(row[1])) if row else None


def save(client_id: str, client_secret: str) -> None:
    """保存/覆盖 Key（页面保存前已完成在线验证，本函数不做校验）。"""
    with _lock:
        _get_conn().execute(
            "INSERT OR REPLACE INTO credentials(id, client_id, client_secret,"
            " updated_at) VALUES (1, ?, ?, ?)",
            (client_id, client_secret, time.strftime("%Y-%m-%dT%H:%M:%S")))
        _get_conn().commit()


def clear() -> bool:
    """清除已保存的 Key；本没有则返回 False。"""
    with _lock:
        cur = _get_conn().execute("DELETE FROM credentials WHERE id = 1")
        _get_conn().commit()
    return cur.rowcount > 0


def has_custom() -> bool:
    """库里是否存着自己的 Key（启动判定与 key_status 共用）。"""
    with _lock:
        row = _get_conn().execute("SELECT 1 FROM credentials WHERE id = 1").fetchone()
    return row is not None
