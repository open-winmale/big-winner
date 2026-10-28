"""取数适配器：把 wmshare 的原始响应归一成 `dividend_xray.Fetcher` 协议。

生产用 `WmshareFetcher`（外面可套 `CachedFetcher` 省额度），测试用 `FakeFetcher`。
"""
from __future__ import annotations

import time
from typing import Any, Iterable, Sequence

from bigwinner.shouxi.tools.dividend_xray import Fetcher


def has_own_credentials() -> bool:
    """本机是否配置了自己的 wmshare 凭证（环境变量或 ~/.wmshare/credentials.env）。

    只认显式配置——SDK 内置的共享体验 AppID 不算数：工具已下线体验 Key
    路径，无自有凭证时服务应进演示模式而不是悄悄蹭共享池。
    """
    import os
    from pathlib import Path

    cid = os.environ.get("WMSHARE_CLIENT_ID") or os.environ.get("OPEN_PLATFORM_CLIENT_ID")
    if cid and (os.environ.get("WMSHARE_CLIENT_SECRET")
                or os.environ.get("OPEN_PLATFORM_CLIENT_SECRET")):
        return True
    return Path.home().joinpath(".wmshare", "credentials.env").is_file()


def _digits(code: str) -> str:
    """归一成 6 位数字键，容忍 SDK 返回 sh.600900.SH 之类写法。"""
    d = "".join(ch for ch in str(code) if ch.isdigit())
    return d[-6:] if len(d) >= 6 else str(code)


def _num(value: Any) -> float | None:
    """把 SDK 回包里的数字/数字字符串转 float；无法转换返回 None。"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _market(code: str) -> str:
    """从代码形态推断市场（cn | hk | us）。

    A 股恒为 6 位数字，港股 5 位（可带 hk. 前缀），美股字母代码。
    这里只做路由判定，不改变用户看到的代码。
    """
    raw = str(code).strip()
    low = raw.lower()
    if low.startswith(("hk.", "hk:")) or low.endswith(".hk"):
        return "hk"
    if low.startswith(("us.", "us:")) or low.endswith(".us"):
        return "us"
    if low.startswith(("cn.", "sh.", "sz.", "bj.")) or low.endswith((".sh", ".sz", ".bj")):
        return "cn"
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits and digits == raw and len(digits) <= 5:
        return "hk"
    if raw.isalpha():
        return "us"
    return "cn"


def _query_code(code: str) -> str:
    """转成 SDK/市场引擎要的裸码：CN 6 位、HK 5 位、US 大写字母。"""
    market = _market(code)
    raw = str(code).strip()
    if market == "hk":
        digits = "".join(ch for ch in raw if ch.isdigit())
        if not digits:
            return raw
        return (digits[-5:] if len(digits) > 5 else digits).zfill(5)
    if market == "us":
        return raw.replace(":", ".").split(".")[-1].upper()
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits[-6:] if len(digits) >= 6 else digits


def _snapshot_key(key: Any, market: str) -> str:
    """把批量回包的 key 归一到入参形态：CN 6 位、HK 5 位。"""
    if market == "hk":
        digits = "".join(ch for ch in str(key) if ch.isdigit())
        return (digits[-5:] if len(digits) > 5 else digits).zfill(5) if digits else str(key)
    return _digits(str(key))


class WmshareFetcher:
    """真实取数。wmshare 延迟导入，未安装时给出可操作提示。

    双市场：A 股走默认 client（market=cn）；港股必须走 market="hk" 的
    client + 5 位裸码。原因（实测）：分红库按 ``bonus.PROPS.<sym>`` 拼 key，
    CN client 拿到 ``HK.00700`` 会查成 ``hk.bonus.PROPS.HK.00700``，真实 key
    是 ``hk.bonus.PROPS.00700``，于是分红历史为空、股息率/派息率返回 0；
    指标层同样需要 hk 市场，否则 EPS 直接 500。

    价格走 `kline.query_bars(sym, 1)`（最新一根日 K 收盘价）而非
    `batch_live`——实测后者依赖的 memo.cacheset/assign 在体验 AppID
    策略下被 403 拒绝，前者全 AppID 可用。
    """

    def __init__(self, client: Any | None = None,
                 hk_client: Any | None = None) -> None:
        if client is None:
            try:
                import wmshare  # noqa: PLC0415 - 延迟导入，未安装也能启动服务
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "未安装 wmshare。请先：git clone https://github.com/open-winmale/wmshare，"
                    "再 pip install -e ./wmshare（非商业许可）。"
                ) from exc
            client = wmshare.Client.from_env()
        self.cli = client
        self._hk_client = hk_client
        self._hk_tried = hk_client is not None
        self._hk_error: str | None = None
        #: 最近一次取数中出现的凭证类异常（advisory；handler 透传给前端展示）
        self.auth_error: str | None = None
        self._fx_cache: dict[str, float | None] = {}

    def note_auth_error(self, exc: BaseException) -> None:
        """疑似凭证类异常 → 记到 auth_error；只做提示，不改变取数行为。

        识别口径：SDK 的 AuthError、HTTP 401/403、文案含「凭证」等。
        由 handler 在每次新生成前 clear、结束后读取——横幅只反映最近一次取数。
        """
        name = type(exc).__name__
        text = str(exc)
        low = text.lower()
        if (name in ("AuthError", "AuthenticationError", "PermissionError")
                or "401" in text or "403" in text
                or "凭证" in text or "token" in low
                or "unauthorized" in low or "forbidden" in low):
            self.auth_error = f"{name}: {text[:120]}"

    def clear_auth_error(self) -> None:
        self.auth_error = None

    def hk_cli(self) -> Any | None:
        """港股 client：懒加载，失败返回 None（港股字段显式缺失即可）。"""
        if self._hk_client is None and not self._hk_tried:
            self._hk_tried = True
            try:
                import wmshare  # noqa: PLC0415
                self._hk_client = wmshare.Client.from_env(market="hk")
            except Exception as exc:  # noqa: BLE001 - 港股通道失败不拖垮 A 股
                self._hk_error = f"{type(exc).__name__}: {exc}"
                self.note_auth_error(exc)
        return self._hk_client

    def _cli_for(self, code: str) -> Any | None:
        market = _market(code)
        if market == "hk":
            return self.hk_cli()
        if market == "us":
            return None
        return self.cli

    def rekey(self, client_id: str, client_secret: str) -> None:
        """热切换凭证：用页面保存的 Key 重建 CN/HK 客户端（无需重启服务）。"""
        import wmshare  # noqa: PLC0415
        self.cli = wmshare.Client(client_id=client_id, client_secret=client_secret)
        self._hk_client = wmshare.Client(
            client_id=client_id, client_secret=client_secret, market="hk")
        self._hk_tried = True
        self.auth_error = None  # 新 Key 新开始

    def prices(self, codes: Sequence[str]) -> dict[str, float | None]:
        """最新收盘价。

        A 股走常规模式；港股的 volume 已是股（不是手），常规模式会触发
        volume×close≈amount 守护报错——实测必须 `_raw=True` 取原始行读 close。
        单票失败隔离，缺价显示 —。
        """
        out: dict[str, float | None] = {}
        for code in codes:
            market = _market(code)
            try:
                cli = self._cli_for(code)
                if cli is None:
                    out[code] = None
                    continue
                if market == "hk":
                    bars = cli.call("kline.query_bars", sym=_query_code(code),
                                    limit=1, _raw=True) or []
                else:
                    bars = cli.call("kline.query_bars", sym=_query_code(code),
                                    limit=1) or []
                out[code] = _num(bars[0].get("close")) if bars else None
            except Exception as exc:  # noqa: BLE001
                self.note_auth_error(exc)
                out[code] = None
        return out

    def _batch(self, cli: Any, fn: str, syms: list[str], **kwargs: Any) -> Any:
        """一次 HTTP 批量；任一标的失败再降级逐标的，避免整批丢数据。"""
        try:
            return cli.call_batch(fn, syms, on_error="raise", **kwargs)
        except Exception as exc:  # noqa: BLE001
            self.note_auth_error(exc)
            try:
                return cli.call_batch(fn, syms, on_error="skip", **kwargs)
            except Exception as exc2:  # noqa: BLE001
                self.note_auth_error(exc2)
                return None

    def dividend_snapshot(self, codes: Sequence[str]) -> dict[str, dict[str, float | None]]:
        """股息率/派息率快照，按市场分组批量取数。"""
        out: dict[str, dict[str, float | None]] = {c: {} for c in codes}
        groups: dict[str, list[str]] = {"cn": [], "hk": []}
        for code in codes:
            market = _market(code)
            if market in groups:
                groups[market].append(code)

        for market, group in groups.items():
            if not group:
                continue
            cli = self.cli if market == "cn" else self.hk_cli()
            if cli is None:
                continue
            query = {_query_code(c): c for c in group}
            for field_name, fn in (
                ("yield_ttm", "bonus.snapshot_yield_ttm"),
                ("payout_ttm", "bonus.snapshot_payout_ttm"),
            ):
                batch = self._batch(cli, fn, list(query))
                if batch is None:
                    continue
                for key, value in (batch.results or {}).items():
                    norm = _snapshot_key(key, market)
                    code = query.get(norm)
                    if code is None:
                        # 大小写差异（HK.00700 vs hk.00700）
                        for q, orig in query.items():
                            if q.lower() == str(key).lower():
                                code = orig
                                break
                    if code is not None:
                        out[code][field_name] = _num(value)
        return out

    def metric(self, code: str, metric_code: str) -> float | None:
        market = _market(code)
        cli = self._cli_for(code)
        if cli is None:
            return None
        try:
            return cli.indicator.get(_query_code(code), metric_code)
        except Exception as exc:  # noqa: BLE001 - 记录后照常上抛（上层单票隔离）
            self.note_auth_error(exc)
            raise

    def metrics(self, code: str, metric_codes: Sequence[str]) -> dict[str, float | None]:
        """一次取多个指标（港股 EPS/DPS/分位合并为一次请求）。"""
        cli = self._cli_for(code)
        if cli is None:
            return {c: None for c in metric_codes}
        try:
            got = cli.indicator.metrics(_query_code(code), list(metric_codes)) or {}
        except Exception as exc:  # noqa: BLE001 - 记录后照常上抛（上层单票隔离）
            self.note_auth_error(exc)
            raise
        if not isinstance(got, dict):
            return {c: None for c in metric_codes}
        out: dict[str, float | None] = {}
        for metric_code in metric_codes:
            value = got.get(metric_code)
            out[metric_code] = value if isinstance(value, str) else _num(value)
        return out

    def dividend_rows(self, code: str, limit: int = 50) -> list[dict[str, Any]]:
        cli = self._cli_for(code)
        if cli is None:
            return []
        try:
            rows = cli.dividend.history(_query_code(code), limit=limit) or []
        except Exception as exc:  # noqa: BLE001 - 记录后照常上抛（上层单票隔离）
            self.note_auth_error(exc)
            raise
        # friendly 层返回的日期字段是 ex_date/pay_date/announce，计算层统一吃 sas
        out = []
        for r in rows:
            row = dict(r)
            if not row.get("sas"):
                row["sas"] = row.get("ex_date") or row.get("ex_div") or ""
            out.append(row)
        return out

    def dividend_rows_many(self, codes: Sequence[str],
                           limit: int = 20) -> dict[str, list[dict[str, Any]]]:
        """一次批量取多票分红历史（原始行，保留状态/登记日/到账日）。

        `bonus.query_list` 支持 sym + limit，`call_batch` 可以按市场打包成一次
        HTTP；港股/ A 股分开，因为引擎的 market 是 client 级的。
        失败时退回逐票规范化历史，至少保留日期和金额。
        """
        out: dict[str, list[dict[str, Any]]] = {}
        groups: dict[str, list[str]] = {"cn": [], "hk": []}
        for code in codes:
            market = _market(code)
            if market in groups:
                groups[market].append(code)

        for market, group in groups.items():
            if not group:
                continue
            cli = self.cli if market == "cn" else self.hk_cli()
            if cli is None:
                continue
            query = {_query_code(c): c for c in group}
            batch = self._batch(cli, "bonus.query_list", list(query),
                                limit=limit, _raw=True)
            if batch is None:
                continue
            for key, rows in (batch.results or {}).items():
                norm = _snapshot_key(key, market)
                code = query.get(norm)
                if code is None:
                    for q, original in query.items():
                        if q.lower() == str(key).lower():
                            code = original
                            break
                if code is not None:
                    out[code] = rows or []

        for code in codes:
            if code in out:
                continue
            try:
                out[code] = self.dividend_rows(code, limit)
            except Exception:  # noqa: BLE001
                out[code] = []
        return out

    def high_yield_symbols(self, market: str = "cn",
                           limit: int = 120) -> list[dict[str, Any]]:
        """高股息池（观察池兜底）：指数 where 砖 + 字段预加载。

        这是“无持仓看市场”的轻量方案：只取高股息池，不扫全市场。
        指数接口不可用时返回 []，由上层提示用户导入关注分组/持仓。
        """
        market = "hk" if str(market).lower() == "hk" else "cn"
        cli = self.cli if market == "cn" else self.hk_cli()
        if cli is None:
            return []
        symbol = "600519" if market == "cn" else "00700"
        xs = (
            'idx := bonus.index_field_load(LatestIndexKey(), '
            'bonus.index_fields_basic())\n'
            'ids := INDEX_QUERY_SPEC(idx, {"where": bonus.index_where_high_yield(), '
            '"order": EXPRSTR($BONUS_RATE_TTM_LAST), "order_desc": true, '
            f'"limit": {int(limit)}, "result": "row_ids"}})\n'
            'return INDEX_ROW_VALUES_MANY(idx, ids)["rows"]'
        )
        try:
            rows = cli.eval_result(xs, symbol=symbol) or []
        except Exception as exc:  # noqa: BLE001 - 指数接口不可用 → 空池
            self.note_auth_error(exc)
            return []
        if isinstance(rows, dict):
            rows = rows.get("rows") or []

        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            vals = row.get("values")
            if not isinstance(vals, dict) or not vals:
                vals = row
            raw_sym = vals.get("$SYMBOL") or vals.get("symbol")
            if not raw_sym:
                continue
            bare = _query_code(raw_sym)
            if not bare:
                continue
            code = f"hk.{bare}" if market == "hk" else bare
            if code in seen:
                continue
            seen.add(code)
            out.append({
                "code": code,
                "market": market,
                "name": str(vals.get("$NAME") or vals.get("name") or code),
                "yield_ttm": _num(vals.get("$BONUS_RATE_TTM_LAST")
                                  or vals.get("yield")),
            })
        return out

    def fx_to_cny(self, currency: str) -> float | None:
        """报价币种→CNY。HKD 走平台 `$CR_HKD_LAST`（港币兑人民币）。"""
        ccy = (currency or "CNY").strip().upper()
        if ccy == "CNY":
            return 1.0
        if ccy != "HKD":
            return None
        if "HKD" in self._fx_cache:
            return self._fx_cache["HKD"]
        cli = self.hk_cli()
        rate = None
        if cli is not None:
            try:
                rate = cli.indicator.get("00700", "$CR_HKD_LAST")
            except Exception as exc:  # noqa: BLE001 - 汇率失败只影响折算
                self.note_auth_error(exc)
                rate = None
        self._fx_cache["HKD"] = _num(rate)
        return self._fx_cache["HKD"]

    def quality_metrics(self, code: str) -> dict[str, Any]:
        """分红质量指标包：标量指标 + 年度分红率/分红金额/股息率序列。

        一次自定义 eval（每票 1 次 HTTP）。code 必须在目录里；序列通过
        `RANGE(ITER(...))` 取年度点。失败时返回 {}，由上层显式标注缺失。
        """
        cli = self._cli_for(code)
        if cli is None or _market(code) != "cn":
            return {}
        bare = _query_code(code)
        xs = (
            "return {"
            '"scalars": {'
            '"payout_ttm": $BONUS_TTM_RATE_LAST,'
            '"payout_lyr": $BONUS_LYR_RATE_LAST,'
            '"payout_3y_avg": $BONUS_RATE_3Y_AVG_LAST,'
            '"payout_5y_avg": $BONUS_RATE_5Y_AVG_LAST,'
            '"payout_3y_min": $BONUS_RATE_3Y_MIN_LAST,'
            '"payout_5y_min": $BONUS_RATE_5Y_MIN_LAST,'
            '"bonus_trend": $BONUS_3Y_TREND_LAST,'
            '"yield_ttm": $BONUS_RATE_TTM_LAST,'
            '"ncfo_ttm": $NCFO_TTM_LAST,'
            '"fcf_ttm": $FCF_TTM,'
            '"cf_np": $CF_NP_RATIO_LAST,'
            '"ncfo_3y_min": $NCFO_3Y_MIN_LAST,'
            '"cfo_kind": $CF_KIND_CODE_3Y_LAST,'
            '"npts_ttm": $NPTS_TTM_LAST,'
            '"npts_yoy": $NPTS_TTM_YOY_LAST,'
            '"roe": $ROE_TTM_LAST,'
            '"roic": $ROIC_TTM_LAST,'
            '"tl_rate": $TL_RATE_LAST,'
            '"ibd_rate": $IBD_RATE_LAST,'
            '"quick": $QUICK_RATIO_LAST,'
            '"ld": $LD,'
            '"setl": $SETL,'
            '"org_type": $ORG_ORGTYPE,'
            '"org_form": $ORG_FORM_TAG,'
            '"free_holder_sum": $FREE_HOLDER_SUM_RATIO_LAST,'
            '"exec_hold": $EXECUTIVE_HOLD_RATIO_LAST,'
            '"has_buyback": $HAS_BUYBACK_6M,'
            '"ind_tl_3y_avg": $CUR_IND_TL_RATE_3Y_AVG_LAST,'
            '"ind_roe_3y_avg": $CUR_IND_ROE_3Y_AVG_LAST,'
            '"ind_yield_3y_avg": $CUR_IND_BONUS_RATE_3Y_AVG_LAST'
            "},"
            '"payout_lyr_series": RANGE(ITER($BONUS_LYR_RATE, annual)),'
            '"bonus_series": RANGE(ITER($BONUS_TTM, annual)),'
            '"yield_series": RANGE(ITER($BONUS_RATE_TTM, annual))'
            "}"
        )
        try:
            data = cli.eval_result(xs, symbol=bare)
        except Exception as exc:  # noqa: BLE001 - 单票质量取数失败 → 上层显式缺失
            self.note_auth_error(exc)
            return {}
        if not isinstance(data, dict):
            return {}
        scalars = data.get("scalars") if isinstance(data.get("scalars"), dict) else {}

        def _pair_list(value: Any) -> list[dict[str, Any]]:
            """年度序列归一：[[v, year], ...] / [{...}] → [{year, value}]。"""
            out: list[dict[str, Any]] = []
            if not isinstance(value, list):
                return out
            for item in value:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    out.append({"value": _num(item[0]),
                                "year": int(item[1]) if item[1] else None})
                elif isinstance(item, dict):
                    v = item.get("value", item.get("v"))
                    y = item.get("year", item.get("annual", item.get("y")))
                    out.append({"value": _num(v),
                                "year": int(y) if y else None})
            return out

        return {
            **{k: (_num(v) if not isinstance(v, (str, bool)) else v)
               for k, v in scalars.items()},
            "payout_lyr_series": _pair_list(data.get("payout_lyr_series")),
            "bonus_series": _pair_list(data.get("bonus_series")),
            "yield_series": _pair_list(data.get("yield_series")),
        }

    def profile_metrics(self, code: str) -> dict[str, Any]:
        """公司档案：名称/行业/企业性质/企业类型/上市日期（CN/HK 都可用）。

        `$ORG_FORM_TAG`（央企子公司/地方国有企业/大型民企等）仅 A 股有值，
        港股返回 null；不在 SDK 目录里，必须走 eval。
        """
        cli = self._cli_for(code)
        if cli is None:
            return {}
        market = _market(code)
        if market not in ("cn", "hk"):
            return {}
        xs = (
            'return {'
            '"name": $NAME,'
            '"industry": $ORG_INDUSTRY_NAME,'
            '"org_type": $ORG_ORGTYPE,'
            '"org_form": $ORG_FORM_TAG,'
            '"listing_date": $ORG_LISTINGDATE'
            "}"
        )
        try:
            data = cli.eval_result(xs, symbol=_query_code(code))
        except Exception as exc:  # noqa: BLE001 - 档案失败 → 上层显式缺失
            self.note_auth_error(exc)
            return {}
        if not isinstance(data, dict):
            return {}
        org_type = data.get("org_type")
        return {
            "name": str(data.get("name")) if data.get("name") else None,
            "industry": str(data.get("industry")) if data.get("industry") else None,
            "org_type": int(org_type) if org_type is not None else None,
            "org_form": str(data.get("org_form")) if data.get("org_form") else None,
            "listing_date": str(data.get("listing_date"))[:10]
                if data.get("listing_date") else None,
        }



class CachedFetcher:
    """给任意 Fetcher 套一层 TTL 缓存 —— 交互式页面反复点按钮也不烧额度。"""

    def __init__(self, inner: Fetcher, ttl: float = 300.0) -> None:
        self.inner = inner
        self.ttl = ttl
        self._store: dict[tuple[str, Any], tuple[float, Any]] = {}

    @property
    def auth_error(self) -> str | None:
        """透传内层的凭证错误标记（FakeFetcher 无此属性 → None）。"""
        return getattr(self.inner, "auth_error", None)

    def clear_auth_error(self) -> None:
        clear = getattr(self.inner, "clear_auth_error", None)
        if clear is not None:
            clear()

    def _memo(self, key: tuple[str, Any], producer: Any) -> Any:
        now = time.time()
        hit = self._store.get(key)
        if hit and now - hit[0] < self.ttl:
            return hit[1]
        value = producer()
        self._store[key] = (now, value)
        return value

    def prices(self, codes: Sequence[str]) -> dict[str, float | None]:
        return self._memo(("prices", tuple(codes)), lambda: self.inner.prices(codes))

    def dividend_snapshot(self, codes: Sequence[str]) -> dict[str, dict[str, float | None]]:
        return self._memo(("snap", tuple(codes)), lambda: self.inner.dividend_snapshot(codes))

    def metric(self, code: str, metric_code: str) -> float | None:
        return self._memo(("metric", (code, metric_code)),
                          lambda: self.inner.metric(code, metric_code))

    def metrics(self, code: str, metric_codes: Sequence[str]) -> dict[str, float | None]:
        def produce() -> dict[str, float | None]:
            fn = getattr(self.inner, "metrics", None)
            if fn is not None:
                return fn(code, list(metric_codes))
            return {c: self.inner.metric(code, c) for c in metric_codes}

        return self._memo(("metrics", (code, tuple(metric_codes))), produce)

    def dividend_rows(self, code: str, limit: int = 50) -> list[dict[str, Any]]:
        return self._memo(("rows", (code, limit)),
                          lambda: self.inner.dividend_rows(code, limit))

    def dividend_rows_many(self, codes: Sequence[str],
                           limit: int = 20) -> dict[str, list[dict[str, Any]]]:
        def produce() -> dict[str, list[dict[str, Any]]]:
            fn = getattr(self.inner, "dividend_rows_many", None)
            if fn is not None:
                return fn(list(codes), limit)
            return {c: self.inner.dividend_rows(c, limit) for c in codes}

        return self._memo(("rows_many", tuple(codes), limit), produce)

    def high_yield_symbols(self, market: str = "cn",
                           limit: int = 120) -> list[dict[str, Any]]:
        def produce() -> list[dict[str, Any]]:
            fn = getattr(self.inner, "high_yield_symbols", None)
            return fn(market, limit) if fn is not None else []

        return self._memo(("hy", market, limit), produce)

    def fx_to_cny(self, currency: str) -> float | None:
        ccy = (currency or "CNY").strip().upper()

        def produce() -> float | None:
            fn = getattr(self.inner, "fx_to_cny", None)
            if fn is not None:
                return fn(ccy)
            return 1.0 if ccy == "CNY" else None

        return self._memo(("fx", ccy), produce)

    def quality_metrics(self, code: str) -> dict[str, Any]:
        def produce() -> dict[str, Any]:
            fn = getattr(self.inner, "quality_metrics", None)
            return fn(code) if fn is not None else {}

        return self._memo(("quality", code), produce)

    def profile_metrics(self, code: str) -> dict[str, Any]:
        def produce() -> dict[str, Any]:
            fn = getattr(self.inner, "profile_metrics", None)
            return fn(code) if fn is not None else {}

        return self._memo(("profile", code), produce)


class FakeFetcher:
    """离线测试/demo 用。

    两种工作方式：
    1. 指定了固定数据集（prices/yields/...）→ 按表返回，miss 即 None。
       供单测断言缺失路径；demo 模式也用这个——miss 时前端如实提示
       "demo 模式仅内置示例股票"，**绝不合成假价格**：编造的数字对懂行的
       用户是毒药（茅台 213 元、招行 185 元一眼假），比"无数据"更糟。
    2. synthetic=True → 对任意代码生成确定性合成数据。仅限测试使用，
       demo 默认不开。
    """

    def __init__(
        self,
        prices: dict[str, float] | None = None,
        yields: dict[str, float] | None = None,
        payouts: dict[str, float] | None = None,
        dps: dict[str, float] | None = None,
        eps: dict[str, float] | None = None,
        pct10y: dict[str, float] | None = None,
        history: dict[str, list[dict[str, Any]]] | None = None,
        fx: dict[str, float] | None = None,
        quality: dict[str, dict[str, Any]] | None = None,
        names: dict[str, str] | None = None,
        synthetic: bool = False,
    ) -> None:
        self.synthetic = synthetic
        self.prices_data = prices or {}
        self.yields = yields or {}
        self.payouts = payouts or {}
        self.dps = dps or {}
        self.eps = eps or {}
        self.pct10y = pct10y or {}
        self.history_data = history or {}
        self.quality_data = quality or {}
        self.names = names or {}
        # demo/测试的默认汇率：1 HKD ≈ 0.85 CNY
        self.fx = fx if fx is not None else {"HKD": 0.85}

    # ---- 合成数据（确定性：同代码永远同结果）----
    def _seed(self, code: str) -> int:
        return sum((i + 1) * ord(ch) for i, ch in enumerate(code))

    def _synthetic(self, code: str) -> dict[str, Any]:
        """由代码生成量级合理的合成数据。价格 5~300 元、股息率 1%~7% 等。"""
        s = self._seed(code)
        price = round(5 + (s % 295) + ((s >> 3) % 100) / 100, 2)
        div_yield = round(0.01 + (s % 60) / 10000, 4)          # 1.0% ~ 7.0%
        payout = round(0.25 + (s % 55) / 100, 2)               # 25% ~ 80%
        dps = round(price * div_yield, 3)
        eps = round(dps / payout, 3) if payout else 0.0
        pct10y = round((s % 90) / 100, 2)                      # 0% ~ 90% 分位
        years = 3 + (s % 8)                                    # 连续 3~10 年
        hist = [{"sas": f"{y}-06-30", "dps": dps} for y in range(2025, 2025 - years, -1)]
        return {"price": price, "yield": div_yield, "payout": payout,
                "dps": dps, "eps": eps, "pct10y": pct10y, "history": hist}

    def prices(self, codes: Sequence[str]) -> dict[str, float | None]:
        if self.synthetic:
            return {c: (self.prices_data.get(c) or self._synthetic(c)["price"])
                    for c in codes}
        return {c: self.prices_data.get(c) for c in codes}

    def dividend_snapshot(self, codes: Sequence[str]) -> dict[str, dict[str, float | None]]:
        def snap(c: str) -> dict[str, float | None]:
            yield_ttm = self.yields.get(c)
            payout_ttm = self.payouts.get(c)
            if self.synthetic and yield_ttm is None:
                syn = self._synthetic(c)
                yield_ttm = syn["yield"]
                payout_ttm = self.payouts.get(c, syn["payout"])
            return {"yield_ttm": yield_ttm, "payout_ttm": payout_ttm}

        return {c: snap(c) for c in codes}

    def metric(self, code: str, metric_code: str) -> float | None:
        if metric_code.endswith("DPS_TTM_LAST_REAL"):
            fixed = self.dps.get(code)
            if fixed is not None:
                return fixed
            return self._synthetic(code)["dps"] if self.synthetic else None
        if metric_code.endswith("EPS_NPTS_TTM_LAST"):
            fixed = self.eps.get(code)
            if fixed is not None:
                return fixed
            return self._synthetic(code)["eps"] if self.synthetic else None
        if metric_code.endswith("PCT_BONUS_RATE_TTM_10Y_LAST"):
            fixed = self.pct10y.get(code)
            if fixed is not None:
                return fixed
            return self._synthetic(code)["pct10y"] if self.synthetic else None
        return None

    def metrics(self, code: str, metric_codes: Sequence[str]) -> dict[str, float | None]:
        return {c: self.metric(code, c) for c in metric_codes}

    def fx_to_cny(self, currency: str) -> float | None:
        ccy = (currency or "CNY").strip().upper()
        if ccy == "CNY":
            return 1.0
        return self.fx.get(ccy)

    def dividend_rows(self, code: str, limit: int = 50) -> list[dict[str, Any]]:
        fixed = self.history_data.get(code)
        if fixed:
            return fixed
        return self._synthetic(code)["history"] if self.synthetic else []

    def dividend_rows_many(self, codes: Sequence[str],
                           limit: int = 20) -> dict[str, list[dict[str, Any]]]:
        return {c: self.dividend_rows(c, limit) for c in codes}

    def quality_metrics(self, code: str) -> dict[str, Any]:
        """demo/测试的质量指标：显式 quality 表优先，否则合成确定性数据。"""
        if _market(code) != "cn":
            return {}
        fixed = self.quality_data.get(code)
        if fixed is not None:
            return fixed
        if not self.synthetic:
            return {}
        payout = self.payouts.get(code) or self._synthetic(code)["payout"]
        eps_ttm = self.eps.get(code) or self._synthetic(code)["eps"]
        npts = eps_ttm * 100_000_000        # 假设 1 亿股 → TTM 净利润
        ncfo = npts * 1.05                  # 现金转化 1.05
        fcf = ncfo * 0.8
        s = self._seed(code)
        org_type = 2 if code in ("601398", "601318", "601166", "600028") else 1
        if org_type == 2:
            fcf = None
        series = [
            {"year": y, "value": round(payout * (1 + ((y % 3) - 1) * 0.05), 4)}
            for y in range(2025, 2019, -1)
        ]
        return {
            "payout_ttm": payout,
            "payout_lyr": payout,
            "payout_3y_avg": round(payout * 0.98, 4),
            "payout_5y_avg": round(payout * 0.95, 4),
            "payout_3y_min": round(payout * 0.85, 4),
            "payout_5y_min": round(payout * 0.8, 4),
            "bonus_trend": "up" if s % 2 == 0 else "flat",
            "yield_ttm": self.yields.get(code),
            "ncfo_ttm": ncfo,
            "fcf_ttm": fcf,
            "cf_np": 1.05,
            "ncfo_3y_min": ncfo * 0.85,
            "cfo_kind": 1,
            "npts_ttm": npts,
            "npts_yoy": 0.06,
            "roe": 0.12,
            "roic": 0.10,
            "tl_rate": 0.35 if org_type == 1 else 0.92,
            "ibd_rate": 0.15 if org_type == 1 else 0.0,
            "quick": 1.2 if org_type == 1 else None,
            "ld": 1.5 if org_type == 1 else None,
            "setl": -(npts * 0.3) if org_type == 1 else None,
            "org_type": org_type,
            "org_form": ("中央金融企业" if org_type == 2
                         else ("大型民企" if s % 3 == 0 else "地方国有企业")),
            "free_holder_sum": 0.45,
            "exec_hold": 0.01,
            "has_buyback": s % 3 == 0,
            "ind_tl_3y_avg": 0.42,
            "ind_roe_3y_avg": 0.10,
            "ind_yield_3y_avg": 0.035,
            "payout_lyr_series": series,
            "bonus_series": [
                {"year": it["year"], "value": round(npts * it["value"], 0)}
                for it in series
            ],
            "yield_series": [
                {"year": it["year"],
                 "value": round((self.yields.get(code) or 0.03) * (1 + (2025 - it["year"]) * 0.02), 4)}
                for it in series
            ],
        }

    def profile_metrics(self, code: str) -> dict[str, Any]:
        """demo/测试的档案：名称取 quality 显式表或合成，org_form 仅 CN。"""
        market = _market(code)
        if market not in ("cn", "hk"):
            return {}
        q = self.quality_data.get(code)
        if q is not None:
            org_type = q.get("org_type")
            org_form = q.get("org_form")
        elif self.synthetic and market == "cn":
            s = self._seed(code)
            org_type = 2 if code in ("601398", "601318", "601166", "600028") else 1
            org_form = ("中央金融企业" if org_type == 2
                        else ("大型民企" if s % 3 == 0 else "地方国有企业"))
        else:
            org_type = org_form = None
        return {
            "name": self.names.get(code),
            "industry": None,
            "org_type": org_type,
            "org_form": org_form if market == "cn" else None,
            "listing_date": None,
        }

    def high_yield_symbols(self, market: str = "cn",
                           limit: int = 120) -> list[dict[str, Any]]:
        out = []
        for code, yield_ttm in self.yields.items():
            code_market = "hk" if str(code).lower().startswith("hk.") else "cn"
            if code_market != ("hk" if str(market).lower() == "hk" else "cn"):
                continue
            out.append({
                "code": code,
                "market": code_market,
                "name": code,
                "yield_ttm": yield_ttm,
            })
        out.sort(key=lambda item: item.get("yield_ttm") or 0, reverse=True)
        return out[:limit]


def _sdk_symbol(item: dict[str, Any]) -> str:
    """把持仓行转成 SDK 认识的代码：CN 裸 6 位、HK 5 位带 hk. 前缀。

    取数层会再按市场路由：HK 用 market="hk" 的 client + 裸 5 位码。
    这里保留前缀是为了让显示/CSV 能一眼区分 A/H。
    """
    code = str(item.get("code", "")).strip()
    market = str(item.get("market") or "").strip().lower()
    if not market:
        market = _market(code)
    if market == "hk":
        digits = "".join(ch for ch in code if ch.isdigit())
        return "hk." + (digits[-5:].zfill(5) if digits else code)
    if market == "us":
        return "us." + code.replace(":", ".").split(".")[-1].upper()
    digits = "".join(ch for ch in code if ch.isdigit())
    return digits[-6:] if len(digits) >= 6 else code.replace(":", ".")


def sdk_symbol(item: dict[str, Any]) -> str:
    """公开别名：server/ledger 也用同一套代码归一。"""
    return _sdk_symbol(item)


def positions_from_payload(items: Iterable[dict[str, Any]]) -> list[Any]:
    """把前端 JSON 转成 Position 列表，非法行直接跳过（由调用方提示）。

    Position.code 存 SDK/展示形式（hk.00700）；market、买入日、税率覆盖
    一并保留，供红利税与成本股息率使用。
    """
    from bigwinner.shouxi.tools.dividend_xray import Position  # 局部导入避免循环

    out: list[Position] = []
    for item in items:
        code = str(item.get("code", "")).strip()
        if not code:
            continue
        try:
            shares = int(float(item.get("shares") or 0))
        except (TypeError, ValueError):
            continue
        if shares <= 0:
            continue
        market = str(item.get("market") or "").strip().lower() or _market(code)
        cost_raw = item.get("cost")
        cost = float(cost_raw) if cost_raw not in (None, "") else None
        tax_raw = item.get("tax_rate")
        tax_rate = None
        if tax_raw not in (None, ""):
            try:
                tax_rate = float(tax_raw)
            except (TypeError, ValueError):
                tax_rate = None
            if tax_rate is not None and tax_rate > 1:
                tax_rate /= 100.0  # 容忍页面传百分数
        pos = Position(
            code=_sdk_symbol({**item, "market": market}),
            shares=shares,
            cost=cost,
            name=(item.get("name") or "").strip() or None,
            market=market,
            buy_date=str(item.get("buy_date") or "").strip() or None,
            tax_rate=tax_rate,
        )
        out.append(pos)
    return out

    return out
