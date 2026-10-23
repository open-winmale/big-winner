# finpipe-tools

> A 股 / 港股持仓收息、分红日历与记账 · **v1.0.0** ·
> [GitHub](https://github.com/deadkingyy/finpipe-tools)
>
> 一组围绕 A 股 / 港股持仓与分红的小工具。每个工具一个独立网页，数据来自
> [finpipe](https://github.com/open-winmale/finpipe)，只做事实与统计聚合。

---

## ⚠️ 许可与合规（请先读）

| | 许可 | 商业使用 |
|---|---|---|
| **本项目代码** | **MIT** | ✅ 允许 |
| **finpipe（数据依赖）** | [PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0) | ❌ **禁止，需另行授权** |

本项目是 source-available 的 finpipe 的**下游工具**。工具代码本身 MIT 可自由使用与改造，
但**只要通过 finpipe 取数，运行时即受非商业许可约束**。若你要做商业用途，
需先向 finpipe 维护方取得商业授权，或替换为自有数据源（`Fetcher` 是可替换接口）。

**本工具不提供、也永远不会提供任何买卖时点、目标价或仓位建议。**
输出全部为描述性统计，不代表投资建议；数据最终以上市公司公告为准。

---

## 快速开始

```bash
# 1) 安装 finpipe（源码安装，尚未发布 PyPI）
git clone https://github.com/open-winmale/finpipe.git && pip install -e ./finpipe

# 2) 启动本工具（单端口，无其他依赖）
cd finpipe-tools
PYTHONPATH=src python -m fptools.server
#   → http://127.0.0.1:8787
```

**没有凭证也能先看效果**（内置样例数据，不联网）：

```bash
PYTHONPATH=src python -m fptools.server --demo
```

配置自己的 AppID（内置体验额度是共享池，容易 429）：

```bash
export FINPIPE_CLIENT_ID=...
export FINPIPE_CLIENT_SECRET=...
# 或写入 ~/.finpipe/credentials.env
```

---

## 工具

| 工具 | 状态 | 说明 |
|---|---|---|
| [持仓收息透视表](/tools/dividend-xray/) | ✅ 可用 | A 股 / 港股持仓 → 组合总市值 / 总利润 / 总股息 / 组合股息率 / 成本股息率 + 派息稳定性看板 |
| 收息驾驶舱（透视表顶部） | ✅ 可用 | 自动载入最近持仓 → 未来 7/30/90/365 天除权与到账、税后现金、年息目标进度 |
| 分红记账（透视表内） | ✅ 可用 | 按除权历史算税前/税后股息；A 股按持有时长分档，港股默认 20%，支持单票/年度/统一税率覆盖 |
| 高股息池日历（无持仓） | ✅ 可用 | 平台高股息选股池 + 已公告分红事件；不是全市场逐票扫描，可切 A 股/港股 |
| 攒股纪律雷达 | 规划中 | 股息率历史分位 + 估值分位 + 派息可持续性的量化检查表 |
| 预测股息现金流 | 规划中 | 基于预测每股分红估算未来 12 个月现金流 |

### 持仓收息透视表 · 数据契约

每个字段都对应真实接口，取不到即留空并显式标注，不做猜测填充：

| 字段 | 来源 | 口径 |
|---|---|---|
| 现价 | `kline.query_bars(sym, 1)` | 原币；港股必须 `_raw=True`（HK volume 已是股，常规模式会触发手/股守护） |
| 股息率 / 派息率 | `bonus.snapshot_yield_ttm` / `snapshot_payout_ttm` | 小数；按市场分组批量取数 |
| 每股股息 | `indicator.metrics` → `$DPS_TTM_LAST_REAL` | 报价币种（港股 HKD） |
| 每股利润 | `indicator.metrics` → `$EPS_NPTS_TTM_LAST` | 财报币种（平台港股统一为 CNY） |
| 股息率 10 年分位 | `$PCT_BONUS_RATE_TTM_10Y_LAST` | 小数（深度模式） |
| 连续分红年数 | `bonus.query_list` 历史行本地倒推 | 年（无现成指标，深度模式） |
| 港股汇率 | `$CR_HKD_LAST` | HKD→CNY，仅用于组合合计 |
| 分红事件（日历） | `bonus.query_list`（`_raw=True`，按市场批量） | 状态/分红类型/股权登记日/除权日/到账日/dps |
| 最近持仓 | SQLite `position_sets` | 打开页面自动载入最近一份档案 |
| 高股息池（无持仓） | `wm-screen-index` conditions（`$BONUS_RATE_TTM_LAST >= 0.03`） | 观察池，只列已公告事件 |

**港股取数**：必须用 `market="hk"` 的 client + **5 位裸码**（如 `00700`）。
用默认 CN client 传 `hk.00700` 时，价格能正常返回（kline 内部会归一），但分红库会拼成
`hk.bonus.PROPS.HK.00700` 而查不到（真实 key 是 `hk.bonus.PROPS.00700`），指标层也会报错——
这就是"港股只有价格、没有分红/EPS"的根因。工具内部用 CN/HK 双 client 自动路由。

**币种纪律**：逐行金额保留报价币种（A 股 CNY、港股 HKD），组合合计统一折算为 CNY；
取不到汇率时该票不进合计并显式提示，绝不把 HKD 与 CNY 直接相加。

**调用量**：价格 1 次/票；股息快照 2 次/市场（失败才降级逐票）；指标标准模式 1 次/票、
深度模式再加 1 次历史/票。结果有 5 分钟 TTL 缓存。

### 分红记账 · 红利税口径

- A 股个人投资者差别化红利税，按**买入日→除权日**持有时长估算：
  ≤1 个月 20%；1 个月–1 年 10%；>1 年 0%（现行政策暂免）。
- 港股通/H 股默认 20% 预扣；本地券商、红筹等口径不同时，可在页面上按
  单票 / 年度 / 统一税率覆盖。港股不套用 A 股持有期分档。
- 未填买入日按 20% 保守估算并标「估算」；买入日之前的除权记录不计入。
- 税源优先级：单票覆盖 > 年度覆盖 > 统一税率 > 自动规则。
- 实际税额在卖出时由券商结算，本工具给的是估算值。

### 收息驾驶舱 · 分红日历

- **打开即用**：自动载入最近保存的持仓（`position_sets` 按 `updated_at` 取最新），
  不用每次重新搜索；「换一份」可切换档案。
- **未来 7/30/90/365 天**：股权登记日、除权日、到账日、方案状态（预案/实施/已执行）、
  税前/税后现金；预案单独标注，不计入「今年已收」。
- **预案待定**：董事会/股东大会预案即使没有确定日期也单独成组并计数；
  市场视图把它排在已到账之前，先用“未来有没有分红公司”回答用户。
- **持仓没有未来事件时**：自动加载市场高股息池的待除权/预案预览（前 6 条），
  不用再点按钮；首次约 10–25 秒（选股接口），之后 10 分钟缓存。
- **取数成本**：持仓/关注池用 `bonus.query_list` 按市场批量（一次 HTTP），
  保留原始 `状态/分红类型/股权登记日`；5 分钟缓存。
- **无持仓**：走平台高股息选股池（`wm-screen-index`，股息率 ≥ 3%），
  再批量查池内已公告的分红事件。**这不是全市场逐票扫描**；全市场日历需要
  平台侧物化 `bonus.CALENDAR` 日期表。该视图依赖 `wm.sh` 门面；没有配置时，
  持仓/关注池日历与透视表仍可正常使用。
- **年息目标**：TTM 年息 / 目标进度，以及按当前成本股息率估算还差多少本金。


---

## 设计原则

1. **单位纪律** —— 内部一律基础单位（比率小数、金额元），只在渲染层转百分比。
   杜绝 `0.0396` 被读成 `0.04%` 这类量级错误。
2. **缺失显式化** —— 取数失败或返回空，字段留 `—` 并记入该行「数据说明」，
   汇总展示数据完整度 `n/m`。绝不静默填 0。
3. **组合口径正确** —— 组合股息率按**市值加权**，不是各票算术平均；
   股息率/成本股息率只对有完整配对的标的计算，缺价/缺成本的票不污染分子分母。
4. **币种不混算** —— 逐行保留原币，组合合计统一折 CNY；缺汇率时宁可置空并提示。
5. **税口径透明** —— 税额是估算值，税源（自动/单票/年度/统一/港股默认）逐笔标注，可覆盖。
6. **可测试** —— 取数层 `Fetcher` 可替换，`FakeFetcher` 让全部逻辑离线可测。
7. **合规红线** —— 只描述事实（"CR3 = 61%"），不输出指令（"应分散持仓"）。

---

## 项目结构

```
src/fptools/
  server.py                  # 单端口 HTTP 服务（仅标准库）
  fetchers.py                # FinpipeFetcher（CN/HK 双市场）/ CachedFetcher / FakeFetcher
  export.py                  # CSV 导出纯函数（含币种/CNY 折算列）
  store.py                   # SQLite：快照 / 持仓档案 / 同步日志
  symbols.py                 # 离线代码目录搜索（cn/hk/us）
  watchlist_sync.py          # winmale 关注分组同步 + 高股息选股池（wm-screen-index）
  tools/
    dividend_xray.py         # T1 纯计算层（不依赖 HTTP 与 finpipe）
    ledger.py                # 分红记账：税档 / 覆盖 / 年度汇总
    calendar.py              # 分红日历：事件解析 / 税后现金 / 年息与目标
  web/
    index.html               # 工具总览
    dividend_xray.html       # T1 页面（驾驶舱 + 透视表 + 账本）
    assets/base.css, app.js
tests/
  test_dividend_xray.py
  test_ledger.py
  test_fetchers.py
  test_export.py
  test_calendar.py
  test_server_ledger.py
  test_server_calendar.py
```

新增一个工具：加 `tools/<name>.py` → 在 `server.py` 的 `TOOLS` 与 `HANDLERS`
各注册一条 → 加一个 `web/<name>.html`。

---

## 测试

```bash
PYTHONPATH=src python -m pytest tests -q     # 离线，不需要凭证
```

覆盖：加权口径、缺失不污染汇总、降级标注、连续年数边界、稳定性看板；
港股双市场路由、HKD/CNY 折算、税档与覆盖优先级、买入前事件过滤、CSV 列；
分红日历的事件解析/税后现金/年息目标/高股息池、最近持仓自动载入。

---

## 免责声明

本工具集仅做持仓数据的统计聚合，不构成任何投资建议；数据来自 finpipe，
最终以上市公司公告为准；历史分红不代表未来。投资有风险，决策需独立判断。
