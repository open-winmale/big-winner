"""取数适配器：把 finpipe 的原始响应归一成 `dividend_xray.Fetcher` 协议。

生产用 `FinpipeFetcher`（外面可套 `CachedFetcher` 省额度），测试用 `FakeFetcher`。
"""
from __future__ import annotations

import time
from typing import Any, Iterable, Sequence

from fptools.tools.dividend_xray import Fetcher


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


class FinpipeFetcher:
    """真实取数。finpipe 延迟导入，未安装时给出可操作提示。

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
                import finpipe  # noqa: PLC0415 - 延迟导入，未安装也能启动服务
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "未安装 finpipe。请先：pip install -e /path/to/openwm，"
                    "或从源码安装 wm-finpipe（非商业许可）。"
                ) from exc
            client = finpipe.Client.from_env()
        self.cli = client
        self._hk_client = hk_client
        self._hk_tried = hk_client is not None
        self._hk_error: str | None = None
        self._fx_cache: dict[str, float | None] = {}

    def hk_cli(self) -> Any | None:
        """港股 client：懒加载，失败返回 None（港股字段显式缺失即可）。"""
        if self._hk_client is None and not self._hk_tried:
            self._hk_tried = True
            try:
                import finpipe  # noqa: PLC0415
                self._hk_client = finpipe.Client.from_env(market="hk")
            except Exception as exc:  # noqa: BLE001 - 港股通道失败不拖垮 A 股
                self._hk_error = f"{type(exc).__name__}: {exc}"
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
        import finpipe  # noqa: PLC0415
        self.cli = finpipe.Client(client_id=client_id, client_secret=client_secret)
        self._hk_client = finpipe.Client(
            client_id=client_id, client_secret=client_secret, market="hk")
        self._hk_tried = True
        self._hk_error = None
        self._fx_cache.clear()

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
            except Exception:  # noqa: BLE001
                out[code] = None
        return out

    @staticmethod
    def _batch(cli: Any, fn: str, syms: list[str], **kwargs: Any) -> Any:
        """一次 HTTP 批量；任一标的失败再降级逐标的，避免整批丢数据。"""
        try:
            return cli.call_batch(fn, syms, on_error="raise", **kwargs)
        except Exception:  # noqa: BLE001
            try:
                return cli.call_batch(fn, syms, on_error="skip", **kwargs)
            except Exception:  # noqa: BLE001
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
        return cli.indicator.get(_query_code(code), metric_code)

    def metrics(self, code: str, metric_codes: Sequence[str]) -> dict[str, float | None]:
        """一次取多个指标（港股 EPS/DPS/分位合并为一次请求）。"""
        cli = self._cli_for(code)
        if cli is None:
            return {c: None for c in metric_codes}
        got = cli.indicator.metrics(_query_code(code), list(metric_codes)) or {}
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
        rows = cli.dividend.history(_query_code(code), limit=limit) or []
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
        except Exception:  # noqa: BLE001 - 指数接口不可用 → 空池
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
            except Exception:  # noqa: BLE001 - 汇率失败只影响折算
                rate = None
        self._fx_cache["HKD"] = _num(rate)
        return self._fx_cache["HKD"]



class CachedFetcher:
    """给任意 Fetcher 套一层 TTL 缓存 —— 交互式页面反复点按钮也不烧额度。"""

    def __init__(self, inner: Fetcher, ttl: float = 300.0) -> None:
        self.inner = inner
        self.ttl = ttl
        self._store: dict[tuple[str, Any], tuple[float, Any]] = {}

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
        if self.synthetic:
            return {c: ({"yield_ttm": self.yields.get(c),
                         "payout_ttm": self.payouts.get(c)}
                        if c in self.yields else
                        {"yield_ttm": self._synthetic(c)["yield"],
                         "payout_ttm": self._synthetic(c)["payout"]})
                    for c in codes}
        return {
            c: {"yield_ttm": self.yields.get(c), "payout_ttm": self.payouts.get(c)}
            for c in codes
        }

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
    from fptools.tools.dividend_xray import Position  # 局部导入避免循环

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
