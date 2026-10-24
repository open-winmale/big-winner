"""server.run_diagnose：单票诊股（档案/企业类型/行情/质量/未来分红）离线测试。"""
from __future__ import annotations

import pytest

import fptools.server as srv
from fptools.fetchers import FakeFetcher


def quality_payload(**overrides):
    data = {
        "payout_ttm": 0.5, "payout_lyr": 0.5, "yield_ttm": 0.04,
        "ncfo_ttm": 1.6e9, "fcf_ttm": 1.2e9, "cf_np": 1.0,
        "ncfo_3y_min": 1.2e9, "cfo_kind": 1,
        "npts_ttm": 1.0e9, "npts_yoy": 0.05,
        "roe": 0.12, "roic": 0.10, "tl_rate": 0.35, "ibd_rate": 0.12,
        "quick": 1.2, "org_type": 1, "org_form": "地方国有企业",
        "free_holder_sum": 0.5, "exec_hold": 0.01, "has_buyback": False,
        "ind_tl_3y_avg": 0.42,
        "payout_lyr_series": [{"year": y, "value": 0.5}
                              for y in range(2025, 2020, -1)],
    }
    data.update(overrides)
    return data


@pytest.fixture(autouse=True)
def fake_runtime(monkeypatch):
    fetcher = FakeFetcher(
        prices={"600900": 28.1, "601398": 6.85, "hk.00700": 382.4},
        yields={"600900": 0.034, "601398": 0.051, "hk.00700": 0.0137},
        payouts={"600900": 0.71, "601398": 0.31, "hk.00700": 0.205},
        quality={
            "600900": quality_payload(),
            "601398": quality_payload(org_type=2, org_form="中央金融企业",
                                      tl_rate=0.92, fcf_ttm=None),
        },
        history={
            "600900": [
                {"props": {"分红": 0.9, "财报时间": f"{y}-12-31",
                           "状态": "实施", "分红类型": "年度",
                           "除权除息日": "2026-11-15" if y == 2025 else ""}}
                for y in range(2025, 2015, -1)
            ],
        },
        synthetic=False,
    )
    monkeypatch.setattr(srv.RUNTIME, "_fetcher", fetcher)


def test_diagnose_cn_eligible_stock():
    d = srv.run_diagnose({"code": "600900"})
    assert d["code"] == "600900"
    assert d["market"] == "cn"
    assert d["profile"]["org_form"] == "地方国有企业"
    assert d["profile"]["org_type"] == 1
    assert d["quote"]["price"] == pytest.approx(28.1)
    assert d["quality"]["eligible"] is True
    assert d["quality"]["ability_score"] is not None
    # 未来事件：hist 里 2025 财报行带 2026-11-15 除权日
    assert d["next_event"] is not None
    assert d["next_event"]["ex_date"] == "2026-11-15"


def test_diagnose_bank_shows_org_form_but_not_scored():
    d = srv.run_diagnose({"code": "601398"})
    assert d["quality"]["eligible"] is False
    assert "银行" in d["quality"]["reason"]
    assert d["profile"]["org_form"] == "中央金融企业"
    assert d["quality"]["tl_rate"] == pytest.approx(0.92)


def test_diagnose_hk_no_org_form():
    d = srv.run_diagnose({"code": "00700"})
    assert d["code"] == "hk.00700"
    assert d["market"] == "hk"
    assert d["profile"]["org_form"] is None
    assert d["quality"]["eligible"] is False
    assert "港股" in d["quality"]["reason"]
    assert any("港股" in n for n in d["notes"])


def test_diagnose_rejects_bad_code():
    with pytest.raises(srv.ToolError):
        srv.run_diagnose({"code": ""})
    with pytest.raises(srv.ToolError):
        srv.run_diagnose({"code": "ABC"})


def test_diagnose_isolated_failures(monkeypatch):
    def boom(code):
        raise RuntimeError("profile down")

    fetcher = srv.RUNTIME.fetcher()
    monkeypatch.setattr(fetcher, "profile_metrics", boom)
    d = srv.run_diagnose({"code": "600900"})
    assert d["profile"].get("name") in (None, "600900")  # 档案缺失但不阻塞
    assert any("档案" in n for n in d["notes"])
    assert d["quality"]["eligible"] is True  # 质量照常出分
