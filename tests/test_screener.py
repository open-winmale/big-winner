"""筛选工具单测：策略注册表、自定义组合、通道解析与降级、罐头确定性。

全部离线：FakeScreenerSource / 桩 runner，不触网、不走 wm.sh。
"""
from __future__ import annotations

import pytest

from bigwinner.shouxi.tools import screener as scr


# ---------------------------------------------------------------- 注册表


def test_registry_ids_unique_and_complete():
    ids = [s.id for s in scr.STRATEGIES]
    assert len(ids) == len(set(ids))
    assert {"high_yield_3", "high_yield_6", "graham", "high_yield_hk"} <= set(ids)
    for s in scr.STRATEGIES:
        assert s.intro and s.columns and s.conditions
        assert s.market in ("cn", "hk")
        assert s.order[0] in {c[0] for c in s.columns}


def test_get_strategy_unknown_rejected():
    with pytest.raises(ValueError, match="未知策略"):
        scr.get_strategy("nope")
    with pytest.raises(ValueError, match="未知策略"):
        scr.get_strategy(None)
    assert scr.get_strategy("graham").name.startswith("格雷厄姆")


def test_clamp_limit():
    assert scr.clamp_limit(None) == 50
    assert scr.clamp_limit("30") == 30
    assert scr.clamp_limit(500) == 200
    assert scr.clamp_limit(0) == 1
    assert scr.clamp_limit("abc") == 50


# ---------------------------------------------------------------- 自定义组合


def test_build_custom_empty_rejected():
    with pytest.raises(ValueError, match="至少填一个条件"):
        scr.build_custom({})
    with pytest.raises(ValueError, match="至少填一个条件"):
        scr.build_custom({"yield_gte": "", "pe_lt": None})


def test_build_custom_percent_tolerance_and_conditions():
    s = scr.build_custom({"yield_gte": "3", "pe_lt": "15"})
    assert s.conditions[0]["field"] == "$BONUS_RATE_TTM_LAST"
    assert s.conditions[0]["value"]["scalar"]["value"] == "0.03"
    pe_conds = [c for c in s.conditions if c["field"] == "$PE_TTM_LAST"]
    assert [c["operator"] for c in pe_conds] == ["GTE", "LT"]   # 正盈利下界 + 上限
    assert [c[0] for c in s.columns] == ["$BONUS_RATE_TTM_LAST", "$PE_TTM_LAST"]
    assert s.order == ("$PE_TTM_LAST", "asc")     # 估值列升序


def test_to_ratio():
    assert scr._to_ratio("3") == 0.03
    assert scr._to_ratio("0.03") == 0.03
    assert scr._to_ratio("abc") is None
    assert scr._to_ratio("-1") is None


def test_graham_excludes_negative_pe():
    """亏损股的负 PE 不满足「0<PE<15」——格雷厄姆要的是便宜且盈利。"""
    graham = scr.get_strategy("graham")
    loser = scr._Stock("600000", "亏损股", -5.0, 0.5, 0.05, 0.5)
    assert scr._match(loser, graham.conditions) is False
    cheap = scr._Stock("600001", "便宜股", 14.9, 1.4, 0.05, 0.5)
    assert scr._match(cheap, graham.conditions) is True


def test_build_custom_pe_adds_positive_floor():
    s = scr.build_custom({"pe_lt": "15"})
    pe_conds = [c for c in s.conditions if c["field"] == "$PE_TTM_LAST"]
    assert [c["operator"] for c in pe_conds] == ["GTE", "LT"]


# ---------------------------------------------------------------- 通道解析


class StubRunner:
    """桩 wm runner：回一个 rows 包裹结构，记录入参。"""

    def __init__(self, rows=None, fail=False):
        self.rows = rows if rows is not None else [
            {"values": {"$SYMBOL": "sh.601939", "$NAME": "建设银行",
                        "$BONUS_RATE_TTM_LAST": "0.052"}},
            {"values": {"$SYMBOL": "601398", "$NAME": "工商银行",
                        "$BONUS_RATE_TTM_LAST": "0.049"}},
            {"$SYMBOL": "601088", "$NAME": "中国神华",
             "$BONUS_RATE_TTM_LAST": 0.058},          # 无 values 包裹也能解析
            {"values": {"$SYMBOL": "601939", "$NAME": "重复票",
                        "$BONUS_RATE_TTM_LAST": "0.052"}},
        ]
        self.fail = fail
        self.calls = []

    def __call__(self, skill, args, timeout):
        self.calls.append({"skill": skill, "args": args, "timeout": timeout})
        if self.fail:
            raise RuntimeError("找不到 wm.sh")
        return {"data": {"rows": self.rows}}


def test_platform_source_parses_and_normalizes():
    runner = StubRunner()
    src = scr.PlatformScreenerSource(runner=runner)
    strategy = scr.get_strategy("high_yield_3")
    rows = src.run_strategy(strategy, 50)

    call = runner.calls[0]
    assert call["skill"] == "wm-screen-index"
    assert call["args"]["market"] == "cn"
    assert call["args"]["top_n"] == 50
    assert call["args"]["fields"][:2] == ["$SYMBOL", "$NAME"]
    assert call["args"]["conditions"][0]["field"] == "$BONUS_RATE_TTM_LAST"

    assert [r["code"] for r in rows] == ["601939", "601398", "601088"]  # 去重 + 归一
    assert rows[0]["values"]["$BONUS_RATE_TTM_LAST"] == pytest.approx(0.052)


def test_platform_source_hk_code_and_topn_clamp():
    runner = StubRunner(rows=[
        {"values": {"$SYMBOL": "hk.00883", "$NAME": "中国海洋石油",
                    "$BONUS_RATE_TTM_LAST": "0.078"}},
    ])
    src = scr.PlatformScreenerSource(runner=runner)
    rows = src.run_strategy(scr.get_strategy("high_yield_hk"), 999)
    assert rows[0]["code"] == "hk.00883"
    assert runner.calls[0]["args"]["top_n"] == 200          # 钳制
    assert runner.calls[0]["args"]["market"] == "hk"


def test_run_screen_unavailable_degrades():
    src = scr.PlatformScreenerSource(runner=StubRunner(fail=True))
    out = scr.run_screen(src, scr.get_strategy("graham"), 50)
    assert "unavailable" in out and "RuntimeError" in out["unavailable"]
    assert out["rows"] == []
    assert out["strategy"]["id"] == "graham"
    assert [c["key"] for c in out["columns"]] == ["$PE_TTM_LAST", "$PB_TTM_LAST"]


def test_run_screen_sorts_by_order():
    src = scr.FakeScreenerSource()

    out = scr.run_screen(src, scr.get_strategy("high_yield_3"), 50)
    yields = [r["values"]["$BONUS_RATE_TTM_LAST"] for r in out["rows"]]
    assert yields == sorted(yields, reverse=True)

    out = scr.run_screen(src, scr.get_strategy("graham"), 50)
    pes = [r["values"]["$PE_TTM_LAST"] for r in out["rows"]]
    assert pes == sorted(pes)                               # 格雷厄姆按 PE 升序


# ---------------------------------------------------------------- 罐头语义


def test_fake_high_yield_rows_meet_threshold():
    out = scr.run_screen(scr.FakeScreenerSource(),
                         scr.get_strategy("high_yield_3"), 50)
    assert out["rows"]
    for r in out["rows"]:
        assert r["values"]["$BONUS_RATE_TTM_LAST"] >= 0.03


def test_fake_graham_rows_meet_both_conditions():
    out = scr.run_screen(scr.FakeScreenerSource(), scr.get_strategy("graham"), 50)
    assert out["rows"]
    for r in out["rows"]:
        assert r["values"]["$PE_TTM_LAST"] < 15
        assert r["values"]["$PB_TTM_LAST"] < 1.5


def test_fake_hk_strategy_uses_hk_table():
    out = scr.run_screen(scr.FakeScreenerSource(),
                         scr.get_strategy("high_yield_hk"), 50)
    assert out["rows"]
    assert all(r["code"].startswith("hk.") for r in out["rows"])


def test_fake_source_deterministic():
    a = scr.FakeScreenerSource().run_strategy(scr.get_strategy("graham"), 50)
    b = scr.FakeScreenerSource().run_strategy(scr.get_strategy("graham"), 50)
    assert a == b
