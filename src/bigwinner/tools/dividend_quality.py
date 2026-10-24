"""分红质量：经营数据对股息的覆盖 + 分红率 + 分红连续性/意愿双轴评估。

范围纪律（数据不满足的不做）：
- 只对 **A 股非金融**（org_type == 1）产出评分；
- 金融股（银行/保险/证券）与港股：`eligible=false`，只展示已有指标，
  不产出 FCF 覆盖/合成分；
- 实控人/机构/北向/质押/分红政策文本/回购金额：SDK 无稳定数据，一律不做；
- 缺失显式化：任何字段取不到都是 None + missing 记录，绝不静默填 0。

口径：
- 分红率 = 现金分红 / 归母净利润（不是股息率；股息率 = 每股股息 / 股价）；
- 覆盖统一用净利润做桥：`ocf_cover = (NCFO/NPTS) / payout`，避免分红币种
  与报表币种混算；
- FCF 覆盖仅非金融（平台对金融股 `$FCF_TTM` 返回 nil）；
- 评分权重公开可复现；硬旗标（超额分红/覆盖不足/高股息陷阱/连续性差等）
  与评分分离。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Sequence

#: 平台现有分红筛选阈值（与 bonus.screen_* / style.xs 一致）
PAYOUT_HEALTHY = (0.30, 0.70)
PAYOUT_OVER = 1.0
PAYOUT_LOW = 0.20
CF_NP_MIN = 0.8          # dividend_sustainable 概念的 OCF/NP 门槛
TL_RATE_SOFT = 0.45      # style.xs 稳定分门槛
YIELD_TRAP = 0.06        # 高股息陷阱的股息率门槛

#: 企业性质（org_type）
ORG_GENERAL = 1
ORG_BANK = 2
ORG_INSURANCE = 3
ORG_SECURITIES = 4

#: 连续分红档位
STABLE_YEARS = 5

#: 取消类状态关键词
CANCELLED_WORDS = ("取消", "否决", "不分配", "终止")
SPECIAL_WORDS = ("特别",)


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _props(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    props = row.get("props") or row.get("Props")
    if isinstance(props, dict) and props:
        return props
    return row


def _pick(row: Any, props: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in props and props[key] not in (None, ""):
            return props[key]
        if isinstance(row, dict) and key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _safe_div(num: float | None, den: float | None) -> float | None:
    if num is None or not den:
        return None
    return num / den


def _series_to_pairs(value: Any) -> list[tuple[int, float]]:
    """[{year, value}] → [(year, value)]，去掉无效点。"""
    out: list[tuple[int, float]] = []
    for item in value or []:
        if isinstance(item, dict):
            year = item.get("year")
            val = _num(item.get("value"))
            if year and val is not None:
                out.append((int(year), val))
    out.sort(reverse=True)
    return out


def completed_years(pairs: Sequence[tuple[int, float]],
                    today: date) -> list[tuple[int, float]]:
    """只保留完整年度（排除当年——当年报告期未走完）。"""
    return [(y, v) for y, v in pairs if y and y < today.year]


# ---------------------------------------------------------------- 分红率


def payout_stats(pairs: Sequence[tuple[int, float]], today: date,
                 payout_lyr: float | None) -> dict[str, Any]:
    """从年度分红率序列算均值/最低/趋势（只用完整年度）。"""
    completed = completed_years(pairs, today)
    years = [y for y, _ in completed]
    vals = [v for _, v in completed]
    recent3 = vals[:3]
    out: dict[str, Any] = {
        "payout_lyr": payout_lyr,
        "payout_years": years,
        "payout_series": [{"year": y, "payout": v} for y, v in completed],
        "payout_3y_avg": (sum(recent3) / len(recent3)) if len(recent3) >= 2 else None,
        "payout_3y_min": min(recent3) if recent3 else None,
        "payout_5y_avg": (sum(vals[:5]) / len(vals[:5])) if len(vals) >= 3 else None,
        "payout_5y_min": min(vals[:5]) if vals else None,
        "n_years": len(completed),
    }
    if len(recent3) >= 3 and recent3[0] is not None:
        # 趋势：最新两年均值 vs 前两年均值（抗单年噪声）
        newest = (recent3[0] + (recent3[1] if len(recent3) > 1 else recent3[0])) / 2
        older = (recent3[-1] + (recent3[1] if len(recent3) > 2 else recent3[-1])) / 2
        if older:
            delta = (newest - older) / older
            out["payout_trend"] = "up" if delta > 0.1 else (
                "down" if delta < -0.1 else "flat")
        else:
            out["payout_trend"] = None
    else:
        out["payout_trend"] = None
    return out


# ---------------------------------------------------------------- 连续性


def dividend_continuity(rows: Sequence[Any], today: date) -> dict[str, Any]:
    """从原始分红行归集：连续年数、近年削减、特别分红、经常性年度金额。

    rows：原始 store 行（props 含 分红/TOTAL_DIVIDEND/状态/分红类型/财报时间），
    也兼容规范化扁平行（dps/ex_date/sas）。
    """
    by_year: dict[int, dict[str, Any]] = {}
    specials: list[dict[str, Any]] = []
    for row in rows or []:
        props = _props(row)
        status = _text(_pick(row, props, "状态", "status"))
        if any(w in status for w in CANCELLED_WORDS):
            continue
        dps = _num(_pick(row, props, "分红", "dps"))
        if dps is None or dps <= 0:
            continue
        fin = _text(_pick(row, props, "财报时间", "sas", "period"))
        year = int(fin[:4]) if len(fin) >= 4 and fin[:4].isdigit() else None
        ex = _text(_pick(row, props, "除权除息日", "ex_div", "ex_date"))
        if year is None and len(ex) >= 4 and ex[:4].isdigit():
            year = int(ex[:4])
        if year is None:
            continue
        kind = _text(_pick(row, props, "分红类型", "kind"))
        content = _text(_pick(row, props, "内容", "content"))
        is_special = any(w in kind for w in SPECIAL_WORDS) or \
            any(w in content for w in SPECIAL_WORDS)
        entry = by_year.setdefault(year, {"dps_sum": 0.0, "count": 0,
                                          "special": False})
        if is_special:
            entry["special"] = True
            specials.append({"year": year, "kind": kind or "特别",
                             "content": content, "dps": dps})
            continue  # 特别分红不进经常性口径
        entry["dps_sum"] += dps
        entry["count"] += 1

    years = sorted(by_year, reverse=True)
    current_year = today.year
    # 连续年数：从最近一个完整年度（去年）往回数
    consecutive = 0
    expected = current_year - 1
    for year in years:
        if year == expected:
            consecutive += 1
            expected -= 1
        elif year < expected:
            break

    # 削减：最近两个**完整年度**的经常性每股分红，下降超过 30%
    # （当年报告期未走完，不参与，避免误报）
    recurring = [
        {"year": y, "dps": round(by_year[y]["dps_sum"], 4),
         "count": by_year[y]["count"], "special": by_year[y]["special"]}
        for y in years
    ]
    completed = [r for r in recurring if r["year"] < current_year]
    cut_recent = False
    if len(completed) >= 2 and completed[0]["dps"] and completed[1]["dps"]:
        change = (completed[0]["dps"] - completed[1]["dps"]) / completed[1]["dps"]
        cut_recent = change < -0.30

    return {
        "consecutive_years": consecutive,
        "years": years,
        "recurring_by_year": recurring,
        "specials": specials,
        "cut_recent": cut_recent,
        "n_years": len(years),
    }


# ---------------------------------------------------------------- 单票评估


@dataclass
class QualityRow:
    """单票分红质量结果。"""

    code: str
    name: str
    market: str = "cn"
    eligible: bool = False          # 是否产出评分
    reason: str = ""                # 不可评分原因（金融股/港股/数据不足）
    org_type: int | None = None
    org_form: str | None = None     # 企业类型（央企子公司/地方国有企业/大型民企…；港股无）
    # 分红率
    yield_ttm: float | None = None
    payout_ttm: float | None = None
    payout_lyr: float | None = None
    payout_3y_avg: float | None = None
    payout_3y_min: float | None = None
    payout_5y_avg: float | None = None
    payout_5y_min: float | None = None
    payout_trend: str | None = None
    # 覆盖
    earnings_cover: float | None = None
    ocf_cover: float | None = None
    fcf_cover: float | None = None
    cash_conversion: float | None = None
    ocf_3y_min: float | None = None
    capex_ratio: float | None = None
    npts_ttm: float | None = None
    ncfo_ttm: float | None = None
    fcf_ttm: float | None = None
    # 债务/盈利
    tl_rate: float | None = None
    tl_ind_avg: float | None = None
    ibd_rate: float | None = None
    quick: float | None = None
    roe: float | None = None
    roic: float | None = None
    npts_yoy: float | None = None
    # 结构（仅展示）
    free_holder_sum: float | None = None
    exec_hold: float | None = None
    has_buyback: bool | None = None
    # 连续性
    consecutive_years: int | None = None
    cut_recent: bool = False
    n_div_years: int | None = None
    payout_series: list[dict[str, Any]] = field(default_factory=list)
    recurring_by_year: list[dict[str, Any]] = field(default_factory=list)
    specials: list[dict[str, Any]] = field(default_factory=list)
    # 评分
    ability_score: float | None = None      # 支付能力 0–100
    ability_bands: dict[str, Any] = field(default_factory=dict)
    willingness_grade: str | None = None    # 分红意愿 A/B/C/D
    willingness_score: float | None = None
    confidence: str = ""                    # high / medium / low
    flags: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def _band(value: float | None, points: Sequence[tuple[float, float]]) -> float | None:
    """分段线性打分：points 为 [(阈值, 得分)]，从高到低；低于最低阈值 0 分。"""
    if value is None:
        return None
    for threshold, score in points:
        if value >= threshold:
            return score
    return 0.0


def _cash_score(row: QualityRow) -> tuple[float | None, dict[str, Any]]:
    """现金流覆盖 35 分。"""
    detail: dict[str, Any] = {}
    fcf_pts = _band(row.fcf_cover, [(2.0, 35.0), (1.5, 30.0), (1.0, 18.0)])
    ocf_pts = _band(row.ocf_cover, [(1.5, 35.0), (1.2, 28.0), (1.0, 16.0)])
    if fcf_pts is None and ocf_pts is None:
        detail["note"] = "现金流覆盖缺失"
        return None, detail
    # 两项都有 → FCF 为主（更严）、OCF 托底：取 0.6/0.4 加权
    if fcf_pts is not None and ocf_pts is not None:
        score = fcf_pts * 0.6 + ocf_pts * 0.4
        detail["mix"] = "FCF 60% + OCF 40%"
    else:
        score = fcf_pts if fcf_pts is not None else ocf_pts
        detail["mix"] = "FCF" if fcf_pts is not None else "OCF"
    if row.cash_conversion is not None:
        if row.cash_conversion < 0.6:
            score -= 5.0
            detail["cf_np_penalty"] = f"OCF/NP={row.cash_conversion:.2f} 偏低，扣 5"
    return max(0.0, score), detail


def _payout_score(row: QualityRow) -> tuple[float | None, dict[str, Any]]:
    """分红率纪律 25 分。"""
    detail: dict[str, Any] = {}
    payout = row.payout_lyr if row.payout_lyr is not None else row.payout_ttm
    if payout is None:
        detail["note"] = "分红率缺失"
        return None, detail
    if payout > PAYOUT_OVER:
        return 0.0, {**detail, "band": f"分红率 {payout:.0%} > 100%，超额分红"}
    if payout >= PAYOUT_HEALTHY[0] and payout <= PAYOUT_HEALTHY[1]:
        base = 25.0
        detail["band"] = f"分红率 {payout:.0%} 在健康区间 30%–70%"
    elif payout < PAYOUT_LOW:
        base = 18.0
        detail["band"] = f"分红率 {payout:.0%} 偏低（<20%），保守"
    elif payout < PAYOUT_HEALTHY[0]:
        base = 21.0
        detail["band"] = f"分红率 {payout:.0%} 偏低（20%–30%）"
    else:
        base = 17.0
        detail["band"] = f"分红率 {payout:.0%} 偏紧（70%–100%）"
    # 3 年趋势恶化扣分
    if row.payout_trend == "up" and payout > PAYOUT_HEALTHY[1]:
        base -= 4.0
        detail["trend_penalty"] = "分红率偏高且仍在抬升，扣 4"
    return max(0.0, base), detail


def _debt_score(row: QualityRow) -> tuple[float | None, dict[str, Any]]:
    """资产负债 20 分。"""
    detail: dict[str, Any] = {}
    tl = row.tl_rate
    if tl is None:
        detail["note"] = "资产负债率缺失"
        return None, detail
    ref = row.tl_ind_avg
    if ref:
        # 相对行业：高于行业均值 10pp 以上开始扣
        excess = tl - ref
        score = 20.0 if excess <= 0 else (14.0 if excess <= 0.10 else 8.0)
        detail["vs_industry"] = f"{tl:.0%} vs 行业 3 年均值 {ref:.0%}"
    else:
        score = _band(1 - tl, [(1 - TL_RATE_SOFT, 20.0), (1 - 0.60, 14.0)])
        detail["vs_industry"] = "行业均值缺失，按绝对阈值"
    if row.ibd_rate is not None and row.ibd_rate > 0.35:
        score -= 3.0
        detail["ibd_penalty"] = f"有息负债率 {row.ibd_rate:.0%} 偏高，扣 3"
    if row.quick is not None and row.quick < 0.8:
        score -= 3.0
        detail["quick_penalty"] = f"速动比率 {row.quick:.2f} 偏低，扣 3"
    return max(0.0, score), detail


def _stability_score(row: QualityRow) -> tuple[float | None, dict[str, Any]]:
    """盈利稳定性 20 分。"""
    detail: dict[str, Any] = {}
    parts: list[float] = []
    # 现金转化质量
    cf = row.cash_conversion
    if cf is not None:
        parts.append(_band(cf, [(1.0, 10.0), (0.8, 8.0), (0.6, 4.0)]) or 0.0)
    # 3 年最低 OCF 为正
    if row.ocf_3y_min is not None:
        parts.append(5.0 if row.ocf_3y_min > 0 else 0.0)
        if row.ocf_3y_min <= 0:
            detail["ocf_min"] = "3 年最低经营现金流 ≤ 0"
    # 盈利增长
    yoy = row.npts_yoy
    if yoy is not None:
        parts.append(_band(yoy, [(0.0, 5.0), (-0.15, 3.0)]) or 0.0)
        if yoy < -0.15:
            detail["np_decline"] = f"归母净利 TTM 同比 {yoy:.0%}"
    if not parts:
        detail["note"] = "稳定性数据缺失"
        return None, detail
    return min(20.0, sum(parts)), detail


def _willingness(row: QualityRow, cont: dict[str, Any]) -> tuple[str | None, float | None]:
    """分红意愿 A–D：连续性 55% + 分红率趋势 30% + 金额/特别分红 15%。"""
    years = cont.get("consecutive_years")
    if years is None and not cont.get("years"):
        return None, None
    # 连续性 55
    if years >= 10:
        c = 55.0
    elif years >= 5:
        c = 44.0
    elif years >= 3:
        c = 30.0
    elif years >= 1:
        c = 14.0
    else:
        c = 0.0
    # 分红率趋势 30
    trend = row.payout_trend
    payout = row.payout_lyr if row.payout_lyr is not None else row.payout_ttm
    if trend == "flat":
        t = 30.0
    elif trend == "up":
        t = 30.0 if (payout is not None and payout <= PAYOUT_HEALTHY[1]) else 20.0
    elif trend == "down":
        t = 15.0
    else:
        t = 22.0  # 数据不足给中性偏下
    # 金额趋势/特别分红 15
    m = 15.0
    if row.cut_recent:
        m = 0.0
    elif row.specials:
        m = 8.0
    score = c + t + m
    if score >= 85:
        grade = "A"
    elif score >= 65:
        grade = "B"
    elif score >= 40:
        grade = "C"
    else:
        grade = "D"
    return grade, score


def evaluate(code: str, name: str, market: str, metrics: dict[str, Any],
             hist_rows: Sequence[Any], today: date | None = None) -> QualityRow:
    """单票质量评估。metrics 取自 fetcher.quality_metrics；hist_rows 为原始分红行。"""
    ref = today or date.today()
    row = QualityRow(code=code, name=name, market=market)
    org_type = metrics.get("org_type")
    row.org_type = int(org_type) if org_type is not None else None
    form = metrics.get("org_form")
    row.org_form = str(form) if form else None

    if market != "cn":
        row.reason = "港股分红率/FCF 口径待核验，暂不评分"
        return row
    if row.org_type in (ORG_BANK, ORG_INSURANCE, ORG_SECURITIES):
        row.reason = {ORG_BANK: "银行股暂不评分（FCF 不适用）",
                      ORG_INSURANCE: "保险股暂不评分（FCF 不适用）",
                      ORG_SECURITIES: "证券股暂不评分（FCF 不适用）"}[row.org_type]
        # 金融股仍展示已有指标
        row.yield_ttm = _num(metrics.get("yield_ttm"))
        row.payout_ttm = _num(metrics.get("payout_ttm"))
        row.payout_lyr = _num(metrics.get("payout_lyr"))
        row.tl_rate = _num(metrics.get("tl_rate"))
        row.tl_ind_avg = _num(metrics.get("ind_tl_3y_avg"))
        row.roe = _num(metrics.get("roe"))
        return row

    # ---- 展示字段 ----
    row.yield_ttm = _num(metrics.get("yield_ttm"))
    row.payout_ttm = _num(metrics.get("payout_ttm"))
    row.payout_lyr = _num(metrics.get("payout_lyr"))
    row.npts_ttm = _num(metrics.get("npts_ttm"))
    row.ncfo_ttm = _num(metrics.get("ncfo_ttm"))
    row.fcf_ttm = _num(metrics.get("fcf_ttm"))
    row.cash_conversion = _num(metrics.get("cf_np"))
    row.ocf_3y_min = _num(metrics.get("ncfo_3y_min"))
    row.tl_rate = _num(metrics.get("tl_rate"))
    row.tl_ind_avg = _num(metrics.get("ind_tl_3y_avg"))
    row.ibd_rate = _num(metrics.get("ibd_rate"))
    row.quick = _num(metrics.get("quick"))
    row.roe = _num(metrics.get("roe"))
    row.roic = _num(metrics.get("roic"))
    row.npts_yoy = _num(metrics.get("npts_yoy"))
    row.free_holder_sum = _num(metrics.get("free_holder_sum"))
    row.exec_hold = _num(metrics.get("exec_hold"))
    bb = metrics.get("has_buyback")
    row.has_buyback = bool(bb) if bb is not None else None

    # ---- 年度序列 ----
    payout_pairs = _series_to_pairs(metrics.get("payout_lyr_series"))
    stats = payout_stats(payout_pairs, ref, row.payout_lyr)
    if row.payout_3y_avg is None:
        row.payout_3y_avg = stats["payout_3y_avg"]
    if row.payout_5y_avg is None:
        row.payout_5y_avg = stats["payout_5y_avg"]
    if row.payout_3y_min is None:
        row.payout_3y_min = stats["payout_3y_min"]
    if row.payout_5y_min is None:
        row.payout_5y_min = stats["payout_5y_min"]
    row.payout_trend = stats["payout_trend"]
    row.payout_series = stats["payout_series"][:6]

    cont = dividend_continuity(hist_rows, ref)
    row.consecutive_years = cont["consecutive_years"]
    row.cut_recent = cont["cut_recent"]
    row.n_div_years = cont["n_years"]
    row.recurring_by_year = cont["recurring_by_year"][:6]
    row.specials = cont["specials"]

    # ---- 覆盖（净利润做桥）----
    row.earnings_cover = (1.0 / row.payout_lyr) if row.payout_lyr else None
    if row.earnings_cover is None and row.payout_ttm:
        row.earnings_cover = 1.0 / row.payout_ttm
    ratio_ocf = _safe_div(row.ncfo_ttm, row.npts_ttm) \
        if (row.npts_ttm is not None and row.npts_ttm > 0) else None
    ratio_fcf = _safe_div(row.fcf_ttm, row.npts_ttm) \
        if (row.npts_ttm is not None and row.npts_ttm > 0) else None
    payout_for_cover = row.payout_lyr or row.payout_ttm
    row.ocf_cover = _safe_div(ratio_ocf, payout_for_cover) \
        if ratio_ocf is not None and payout_for_cover else None
    row.fcf_cover = _safe_div(ratio_fcf, payout_for_cover) \
        if ratio_fcf is not None and payout_for_cover else None
    if row.ncfo_ttm and row.fcf_ttm is not None and row.ncfo_ttm > 0:
        row.capex_ratio = (row.ncfo_ttm - row.fcf_ttm) / row.ncfo_ttm

    # ---- 资格与缺失 ----
    core_missing: list[str] = []
    if row.payout_lyr is None and row.payout_ttm is None:
        core_missing.append("分红率")
    if row.ncfo_ttm is None or row.npts_ttm is None:
        core_missing.append("经营现金流/净利润")
    if row.fcf_ttm is None:
        row.missing.append("FCF")
    if row.tl_rate is None:
        core_missing.append("资产负债率")
    if core_missing:
        row.missing.extend(core_missing)
        row.reason = "核心数据缺失：" + "、".join(core_missing)
        row.confidence = "low"
        return row

    row.eligible = True

    # ---- 硬旗标 ----
    flags: list[str] = []
    payout_eff = row.payout_lyr if row.payout_lyr is not None else row.payout_ttm
    if payout_eff is not None and payout_eff > PAYOUT_OVER:
        flags.append("分红率超 100%（超额分红）")
    if row.ocf_cover is not None and row.ocf_cover < 1.0:
        flags.append("分红超过经营现金流")
    if row.fcf_cover is not None and row.fcf_cover < 1.0:
        flags.append("分红超过自由现金流")
    if (row.yield_ttm is not None and row.yield_ttm >= YIELD_TRAP
            and row.ability_score is not None and row.ability_score < 50):
        flags.append("高股息陷阱风险")
    if row.consecutive_years is not None and row.consecutive_years < 3:
        flags.append(f"连续分红仅 {row.consecutive_years} 年")
    if row.cut_recent:
        flags.append("近两年分红金额削减超 30%")
    if (row.npts_ttm is not None and row.npts_ttm < 0) or \
            (row.ncfo_ttm is not None and row.ncfo_ttm < 0):
        flags.append("净利润或经营现金流为负")
    if row.specials:
        flags.append(f"含 {len(row.specials)} 笔特别分红（已从经常性口径剔除）")
    row.flags = flags

    # ---- 支付能力 ----
    cash_pts, cash_detail = _cash_score(row)
    payout_pts, payout_detail = _payout_score(row)
    debt_pts, debt_detail = _debt_score(row)
    stab_pts, stab_detail = _stability_score(row)
    parts = [p for p in (cash_pts, payout_pts, debt_pts, stab_pts) if p is not None]
    weights = {"cash": 35.0, "payout": 25.0, "debt": 20.0, "stability": 20.0}
    score: float | None = None
    if parts:
        got = 0.0
        full = 0.0
        mapping = [
            (cash_pts, weights["cash"], "cash", cash_detail),
            (payout_pts, weights["payout"], "payout", payout_detail),
            (debt_pts, weights["debt"], "debt", debt_detail),
            (stab_pts, weights["stability"], "stability", stab_detail),
        ]
        for pts, weight, key, detail in mapping:
            if pts is None:
                row.missing.append({"cash": "现金流覆盖", "payout": "分红率",
                                    "debt": "资产负债", "stability": "盈利稳定性"}[key])
                continue
            detail["score"] = round(pts, 1)
            detail["weight"] = weight
            got += pts / weight * weight
            full += weight
        score = got / full * 100.0 if full else None
        row.ability_bands = {
            "cash": cash_detail, "payout": payout_detail,
            "debt": debt_detail, "stability": stab_detail,
        }
    row.ability_score = round(score, 1) if score is not None else None

    # ---- 高股息陷阱（评分出来后复查）----
    if row.yield_ttm is not None and row.yield_ttm >= YIELD_TRAP \
            and row.ability_score is not None and row.ability_score < 50 \
            and "高股息陷阱风险" not in row.flags:
        row.flags.append("高股息陷阱风险")

    # ---- 意愿 ----
    grade, wscore = _willingness(row, cont)
    row.willingness_grade = grade
    row.willingness_score = round(wscore, 1) if wscore is not None else None

    # ---- 置信度 ----
    conf_issues = sum(1 for label in ("现金流覆盖", "分红率", "资产负债", "盈利稳定性")
                      if label in row.missing)
    if conf_issues == 0 and row.n_div_years is not None and row.n_div_years >= 3:
        row.confidence = "high"
    elif conf_issues <= 1:
        row.confidence = "medium"
    else:
        row.confidence = "low"
    if row.specials:
        row.confidence = "medium" if row.confidence == "high" else "low"
    return row


def summarize(rows: Sequence[QualityRow]) -> dict[str, Any]:
    """组合汇总：可评分数量、平均支付能力、意愿分布、旗标计数。"""
    eligible = [r for r in rows if r.eligible and r.ability_score is not None]
    scored = [r for r in eligible if r.confidence != "low"]
    avg_ability = (sum(r.ability_score for r in scored) / len(scored)) \
        if scored else None
    grades = {"A": 0, "B": 0, "C": 0, "D": 0}
    for r in eligible:
        if r.willingness_grade in grades:
            grades[r.willingness_grade] += 1
    def avg(attr: str) -> float | None:
        vals = [getattr(r, attr) for r in scored if getattr(r, attr) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None
    return {
        "eligible_count": len(eligible),
        "scored_count": len(scored),
        "skipped": [r.code for r in rows if not r.eligible],
        "avg_ability": round(avg_ability, 1) if avg_ability is not None else None,
        "willingness": grades,
        "coverage_thin": sum(
            1 for r in rows
            if (r.fcf_cover is not None and r.fcf_cover < 1.0)
            or (r.ocf_cover is not None and r.ocf_cover < 1.0)),
        "yield_trap": sum(1 for r in rows if "高股息陷阱风险" in r.flags),
        "over_payout": sum(1 for r in rows
                           if (r.payout_lyr or 0) > PAYOUT_OVER
                           or (r.payout_ttm or 0) > PAYOUT_OVER),
        "avg_payout_ttm": avg("payout_ttm"),
        "avg_ocf_cover": avg("ocf_cover"),
        "avg_fcf_cover": avg("fcf_cover"),
        "avg_tl_rate": avg("tl_rate"),
    }


def build_quality(
    positions: list[dict[str, Any]],
    metrics_by_code: dict[str, dict[str, Any]],
    hist_by_code: dict[str, list[dict[str, Any]]],
    today: date | None = None,
) -> dict[str, Any]:
    """主入口：positions + 每票指标 + 每票历史 → 质量行 + 汇总。"""
    ref = today or date.today()
    rows: list[QualityRow] = []
    for pos in positions:
        code = str(pos.get("code") or "").strip()
        if not code:
            continue
        market = str(pos.get("market") or "cn")
        metrics = metrics_by_code.get(code)
        if (metrics is None or not metrics) and market == "cn":
            row = QualityRow(code=code, name=str(pos.get("name") or code),
                             market=market)
            row.reason = "质量指标未取到"
            row.confidence = "low"
            rows.append(row)
            continue
        row = evaluate(code, str(pos.get("name") or code), market,
                       metrics or {}, hist_by_code.get(code) or [], ref)
        rows.append(row)
    data = {
        "rows": rows,
        "summary": summarize(rows),
        "notes": [
            "评分只覆盖 A 股非金融；金融股（FCF 不适用）与港股（分红率/FCF 口径待核验）只展示指标，不评分。",
            "分红率 = 现金分红 ÷ 归母净利润；股息率 = 每股股息 ÷ 股价。覆盖统一用净利润做桥，避免币种混算。",
            "权重：现金流覆盖 35% + 分红率纪律 25% + 资产负债 20% + 盈利稳定性 20%；分红意愿 = 连续性 55% + 分红率趋势 30% + 金额/特别分红 15%。",
            "本工具只做描述性统计，不构成投资建议，也不预测分红削减。",
        ],
    }
    return data
