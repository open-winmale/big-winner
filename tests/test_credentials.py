"""credentials 模块：页面保存 Key 的本机库存取（save/load/clear/has_custom）。

库文件由 conftest 的 autouse 夹具指向 tmp_path，用例不感知真实 data/ 路径。
"""
from __future__ import annotations

from bigwinner.common import credentials
from bigwinner.common.fetchers import has_own_credentials


def test_save_load_roundtrip():
    assert credentials.load() is None
    assert credentials.has_custom() is False

    credentials.save("cid-1", "sec-1")
    assert credentials.load() == ("cid-1", "sec-1")
    assert credentials.has_custom() is True

    credentials.save("cid-2", "sec-2")  # 覆盖保存（换 Key）
    assert credentials.load() == ("cid-2", "sec-2")


def test_clear():
    assert credentials.clear() is False  # 本没有
    credentials.save("cid", "sec")
    assert credentials.clear() is True
    assert credentials.load() is None
    assert credentials.has_custom() is False


def test_persists_across_connections(tmp_path):
    """落库即持久：关连接再重开（模拟服务重启）后仍可读。"""
    db = tmp_path / "fptools.db"
    credentials.save("cid", "sec")
    credentials.set_db_path(None)
    credentials.set_db_path(db)
    assert credentials.load() == ("cid", "sec")


def test_has_own_credentials_prefers_db(monkeypatch, tmp_path):
    """库里有 Key 即视为自有凭证，env/文件都不用配。"""
    for var in ("WMSHARE_CLIENT_ID", "OPEN_PLATFORM_CLIENT_ID",
                "WMSHARE_CLIENT_SECRET", "OPEN_PLATFORM_CLIENT_SECRET"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert has_own_credentials() is False

    credentials.save("cid", "sec")
    assert has_own_credentials() is True
