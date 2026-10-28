"""全局测试夹具。"""
from __future__ import annotations

import pytest

from bigwinner.common import credentials


@pytest.fixture(autouse=True)
def _isolated_credentials_db(tmp_path):
    """凭证库一律指向临时文件：测试绝不读写开发机的 data/fptools.db。"""
    credentials.set_db_path(tmp_path / "fptools.db")
    yield
    credentials.set_db_path(None)
