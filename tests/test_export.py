"""CSV 导出列与币种口径测试（离线）。"""
from __future__ import annotations

import csv
import io

import pytest

from bigwinner.export import HEADERS, xray_csv
from bigwinner.fetchers import FakeFetcher
from bigwinner.tools.dividend_xray import Position, analyze


def build_result():
    fetcher = FakeFetcher(
        prices={"600000": 10.0, "hk.00700": 382.40},
        yields={"600000": 0.05, "hk.00700": 0.01373},
        payouts={"600000": 0.60, "hk.00700": 0.2052},
        dps={"600000": 0.5, "hk.00700": 5.30},
        eps={"600000": 1.0, "hk.00700": 25.902},
        fx={"HKD": 0.85},
    )
    return analyze([
        Position(code="600000", shares=1000, cost=8.0),
        Position(code="hk.00700", shares=1000, cost=400.0, market="hk"),
    ], fetcher)


def test_csv_headers_and_currency_columns():
    text = xray_csv(build_result())
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == HEADERS
    assert len(rows[0]) == 19

    hk = next(r for r in rows if r[0] == "hk.00700")
    assert hk[2] == "hk"
    assert hk[3] == "HKD"
    assert float(hk[7]) == pytest.approx(382400 * 0.85)   # 市值(CNY)
    assert hk[10] == "CNY"                                # 利润币种
    assert float(hk[16]) == pytest.approx(5300 * 0.85)    # 年息(CNY)

    total = rows[-1]
    assert total[0] == "合计"
    assert total[3] == "CNY"
    assert float(total[7]) == pytest.approx(10000 + 382400 * 0.85)
    assert float(total[16]) == pytest.approx(500 + 5300 * 0.85)


def test_csv_leaves_missing_values_blank():
    fetcher = FakeFetcher(prices={"600000": 10.0})
    result = analyze([Position(code="600000", shares=1000)], fetcher)
    rows = list(csv.reader(io.StringIO(xray_csv(result))))
    row = rows[1]
    assert row[11] == ""          # 每股股息缺失
    assert row[13] == ""          # 成本股息率缺失
    assert row[15] == ""          # 年息缺失
