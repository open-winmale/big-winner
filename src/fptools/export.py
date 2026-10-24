"""CSV 导出：纯函数，便于离线测试（不依赖 HTTP 服务）。

列与页面透视表保持一致，并额外给出币种与 CNY 折算列：
港股逐行保留原币（HKD），合计统一为 CNY；缺数据留空，不填 0。
"""
from __future__ import annotations

import csv
import io
from typing import Any

HEADERS = [
    "代码", "名称", "市场", "币种", "持股", "现价",
    "市值(原币)", "市值(CNY)", "占比",
    "每股利润", "利润币种", "每股股息",
    "股息率", "成本股息率", "分红率(TTM)",
    "持仓年息(原币)", "持仓年息(CNY)", "浮动比例", "数据说明",
]


def xray_csv(result: Any) -> str:
    """把 PortfolioResult 转成 CSV 文本（不含 BOM，调用方按需加）。"""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(HEADERS)
    for row in result.rows:
        writer.writerow([
            row.code, row.name, row.market, row.currency, row.shares, row.price,
            row.market_value, row.market_value_cny, row.weight,
            row.eps_ttm, row.fin_currency, row.dps_ttm,
            row.div_yield, row.cost_yield, row.payout,
            row.annual_dividend, row.annual_dividend_cny, row.pnl_ratio,
            " / ".join(row.missing or []),
        ])
    writer.writerow([
        "合计", "", "", result.total_currency or "", "", "",
        "", result.total_market_value, 1.0,
        "", "", "",
        result.portfolio_yield, result.portfolio_cost_yield, "",
        "", result.total_dividend, result.portfolio_pnl_ratio, "",
    ])
    return buf.getvalue()
