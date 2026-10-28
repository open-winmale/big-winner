#!/usr/bin/env python3
"""烘 GitHub Pages 只读演示的计算结果：python scripts/bake_pages_demo.py

用 wmshare 真实凭证把「示例持仓（贵州茅台 1000 股）」的收息全套结果、
波段的通道/回放（PE/PB × 半年/1 年/2 年）、选股全策略的真实执行结果
烘成静态 JSON（web/public/pages-demo.json）。Pages 构建的前端加载它：
浏览真实数据的预烘结果；未烘焙的操作引导用户本地运行完整工具。

需要真实凭证（与 bake_demo_data.py 同一套）。约 40 次 wmshare 调用，
数值过期两个 bake 脚本一起重跑。
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bigwinner.bigly import server as bigly_srv  # noqa: E402
from bigwinner.shouxi import server as srv  # noqa: E402

OUT = (Path(__file__).resolve().parent.parent / "web" / "public"
       / "pages-demo.json")

#: 只读演示的示例持仓（与前端 positions-latest 静态返回严格一致）
SAMPLE_POSITIONS = [
    {"code": "600519", "market": "cn", "name": "贵州茅台", "shares": 1000},
]
BIGLY_METRICS = ["pe", "pb"]
BIGLY_WINDOWS = ["6m", "1y", "2y"]
#: 选股预置策略 + 一个常用自定义组合
STRATEGY_IDS = ["high_yield_3", "high_yield_6", "graham", "cheap_income",
                "below_pb", "payout_30_70", "high_yield_hk"]
CUSTOM_SPEC = {"yield_gte": "3", "pe_lt": "15", "pb_lt": "1.5"}


def canon_positions(items: list[dict]) -> str:
    """前端 static.ts 同款规范化键：代码/市场/股数/成本，排序后紧凑 JSON。"""
    rows = []
    for p in items:
        cost = p.get("cost")
        rows.append({
            "c": str(p.get("code") or "").strip(),
            "m": str(p.get("market")
                     or ("hk" if str(p.get("code", "")).lower().startswith("hk")
                         else "cn")),
            "s": int(p.get("shares") or 0),
            "k": None if cost in (None, "") else float(cost),
        })
    rows.sort(key=lambda r: (r["m"], r["c"]))
    return json.dumps(rows, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def canon_custom(spec: dict) -> str:
    """自定义组合的规范化键：键排序 + 紧凑序列化（同 TS JSON.stringify）。"""
    return json.dumps(spec, sort_keys=True, separators=(",", ":"))


def main() -> int:
    # 真实模式取数；烘焙不写快照、不动观察池
    srv.RUNTIME.demo = False
    srv.STORE.save_snapshot = lambda *a, **k: None  # type: ignore[method-assign]

    entries: dict[str, list[dict]] = {}

    def add(handler: str, match: dict, fn) -> None:
        """执行并记录；失败跳过（Pages 上命中不了就走本地指引，天然降级）。"""
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001 - 单条失败不阻塞烘焙
            print(f"  ! {handler} {json.dumps(match, ensure_ascii=False)}"
                  f" → {type(exc).__name__}: {str(exc)[:80]}，跳过")
            return
        entries.setdefault(handler, []).append({"match": match, "result": result})
        print(f"  · {handler} {json.dumps(match, ensure_ascii=False)}")

    pos_key = canon_positions(SAMPLE_POSITIONS)

    print("收息佬（示例持仓：贵州茅台 1000 股）…")
    add("dividend-xray", {"pos": pos_key, "deep": False},
        lambda: srv.run_dividend_xray({"positions": SAMPLE_POSITIONS,
                                       "deep": False}))
    add("dividend-quality", {"pos": pos_key},
        lambda: srv.run_dividend_quality({"positions": SAMPLE_POSITIONS}))
    add("diagnose", {"code": "600519"},
        lambda: srv.run_diagnose({"code": "600519", "name": "贵州茅台"}))
    add("ledger", {"pos": pos_key},
        lambda: srv.run_ledger({"positions": SAMPLE_POSITIONS, "year": None,
                                "tax": {"mode": "auto"}}))
    add("calendar", {"mode": "positions"},
        lambda: srv.run_calendar({"mode": "positions",
                                  "positions": SAMPLE_POSITIONS,
                                  "tax": {"mode": "auto"}}))
    add("calendar", {"mode": "market", "market": "cn"},
        lambda: srv.run_calendar({"mode": "market", "market": "cn",
                                  "limit": 120, "tax": {"mode": "auto"}}))
    add("calendar", {"mode": "market", "market": "hk"},
        lambda: srv.run_calendar({"mode": "market", "market": "hk",
                                  "limit": 120, "tax": {"mode": "auto"}}))

    print("波段（PE/PB × 半年/1 年/2 年，真实取数）…")
    data = bigly_srv.WmshareBiglyData()
    for metric in BIGLY_METRICS:
        for window in BIGLY_WINDOWS:
            match = {"symbol": "600519", "metric": metric, "window": window}
            add("bigly/channel", match,
                lambda m=dict(match): bigly_srv.run_channel(data, dict(m)))
            add("bigly/backtest", match,
                lambda m=dict(match): bigly_srv.run_backtest(data, dict(m)))

    print("选股（预置策略 + 自定义组合，真实执行）…")
    for sid in STRATEGY_IDS:
        add("screener", {"strategy": sid},
            lambda s=sid: srv.run_screener({"strategy": s, "limit": 50}))
    add("screener", {"custom": canon_custom(CUSTOM_SPEC)},
        lambda: srv.run_screener({"limit": 50, "custom": dict(CUSTOM_SPEC)}))

    payload = {
        "as_of": date.today().isoformat(),
        "note": "GitHub Pages 只读演示：真实数据的预烘结果（非实时）。"
                "未包含的操作引导用户本地运行完整工具。",
        "entries": entries,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    n = sum(len(v) for v in entries.values())
    print(f"\n已写入 {OUT}（{OUT.stat().st_size // 1024}KB，{n} 条结果，"
          f"快照日 {payload['as_of']}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
