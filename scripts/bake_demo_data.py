#!/usr/bin/env python3
"""把真实数据烘成 demo 静态快照：python scripts/bake_demo_data.py

用 wmshare 真实凭证取贵州茅台的行情 / 股息 / 分红史 / 质量指标，
写入 src/bigwinner/shouxi/demo_data.json。demo 模式加载这份快照：
数字全部真实，只是冻结在生成当日（非实时）。快照只覆盖这一只示例——
体验就是「看茅台的演示」，其余标的引导用户换自己的 Key 变实时。

约 6 次 wmshare 调用，生成一次即可，数值过期（几个月后）重跑刷新。
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bigwinner.common.fetchers import WmshareFetcher  # noqa: E402
from bigwinner.shouxi.tools import dividend_xray as xray_mod  # noqa: E402

#: 快照只覆盖一只示例（贵州茅台）：演示讲清楚工具长什么样就够了，
#: 其余标的在页面里引导换自己的 Key 看实时全市场。
CODES = ["600519"]

OUT = (Path(__file__).resolve().parent.parent / "src" / "bigwinner"
       / "shouxi" / "demo_data.json")


def main() -> int:
    fetcher = WmshareFetcher()
    calls = 0

    print("行情（现价）…")
    prices = fetcher.prices(CODES)
    calls += len(CODES)

    print("股息快照（股息率 / 分红率 TTM）…")
    snaps = fetcher.dividend_snapshot(CODES)
    calls += len(CODES)
    yields = {c: (s or {}).get("yield_ttm") for c, s in snaps.items()}
    payouts = {c: (s or {}).get("payout_ttm") for c, s in snaps.items()}

    print("指标（每股分红 / EPS / 股息率 10 年分位）…")
    dps: dict[str, float | None] = {}
    eps: dict[str, float | None] = {}
    pct10y: dict[str, float | None] = {}
    for c in CODES:
        got = fetcher.metrics(c, [xray_mod.METRIC_DPS_TTM,
                                  xray_mod.METRIC_EPS_TTM,
                                  xray_mod.METRIC_YIELD_PCT_10Y])
        calls += 1
        dps[c] = (got or {}).get(xray_mod.METRIC_DPS_TTM)
        eps[c] = (got or {}).get(xray_mod.METRIC_EPS_TTM)
        pct10y[c] = (got or {}).get(xray_mod.METRIC_YIELD_PCT_10Y)

    print("分红质量指标（A 股；港股无此口径）…")
    quality: dict[str, dict] = {}
    for c in CODES:
        quality[c] = fetcher.quality_metrics(c)
        calls += 1

    print("名称档案…")
    names: dict[str, str] = {}
    for c in CODES:
        try:
            profile = fetcher.profile_metrics(c) or {}
            if profile.get("name"):
                names[c] = str(profile["name"])
        except Exception as exc:  # noqa: BLE001 - 单票失败不阻塞
            print(f"  ! {c} 档案失败：{exc}")
        calls += 1

    print("分红历史（近 80 条）…")
    history: dict[str, list[dict]] = {}
    for c in CODES:
        try:
            history[c] = fetcher.dividend_rows(c, limit=80) or []
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {c} 分红史失败：{exc}")
            history[c] = []
        calls += 1

    print("汇率…")
    hkd = fetcher.fx_to_cny("HKD")
    calls += 1
    fx = {"HKD": hkd} if hkd else {"HKD": 0.85}

    missing = [c for c in CODES if prices.get(c) is None]
    payload = {
        "as_of": date.today().isoformat(),
        "note": "真实数据的静态快照（scripts/bake_demo_data.py 生成），非实时；"
                "配置 wmshare Key 即变实时。",
        "tables": {
            "prices": prices, "yields": yields, "payouts": payouts,
            "dps": dps, "eps": eps, "pct10y": pct10y,
            "quality": quality, "names": names, "history": history, "fx": fx,
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"\n已写入 {OUT}")
    print(f"调用约 {calls} 次；快照日 {payload['as_of']}；"
          f"价格缺失 {len(missing)} 只{'：' + ','.join(missing) if missing else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
