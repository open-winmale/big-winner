# 筛选（screener）· UI/UX 设计稿 v1.0

> 预置策略 · 一键全市场选股 · 归属：收息佬门户 `/tools/screener/`
> 数据源：平台选股通道 `wm-screen-index` conditions（与平台 web「选股」同引擎）
> 演进留档：v0.1 宽度统计+单票过筛（否：统计不需要）；v0.2–v0.3 布尔筛子矩阵
> （否：掷骰子）；v0.4 攒息四问分层（否：过重）；v0.5 粘贴代码过筛（否：是过筛
> 不是选股）。v1.0 定稿：**选策略 → 全市场 → 选股列表 → 进观察池**。

## 1. 定位与人群

- 一句话：选一张策略卡，一键全市场选股；清单数字即入选证据，一键进观察池继续跟踪。
- 人群覆盖：攒息族（高股息/派息健康/股息改善族策略）、价值投资者（格雷厄姆简化、
  低估+高息、破净）、长尾（自定义组合 AND）；
- 合规：选股结果 ≠ 推荐，只描述事实；免责三处（红 banner / 页脚 / API `disclaimer`）。

## 2. 信息架构（单屏双卡）

```
[topbar]  筛选 · screener ······ [演示数据徽章]
[banner]  红底粗体免责：选股结果≠推荐
[page-head]  h1 筛选 screener + 副标题「预置策略 · 一键全市场……」
[Card ① 选股策略]
[Card ② 选股结果]
[footer]  通道说明 + 深度体检指引 + 免责
```

## 3. Card ① 选股策略

- 策略卡网格：桌面 2 列 / 移动 1 列；卡片 = button（键盘可达），radio 单选语义，
  选中 accent 描边 + soft 底。
- 卡片内容 = 「必要的策略介绍」前置：名称 + 一句话口径 + 徽章（市场、
  「平台选股 · 约 1 次查询」）：

| 卡 | 口径 |
|---|---|
| 高股息 ≥3% | TTM 股息率 ≥3%，与平台高股息池同口径 |
| 高股息 ≥6% | 深度高息，警惕价值陷阱 |
| 格雷厄姆（简化） | 0<PE(TTM)≤15 ∧ 市净率<1.5（蕴含 PE×PB<22.5；PE 下界排除亏损负 PE） |
| 低估值高息 | 0<PE(TTM)≤15 ∧ 股息率≥3% |
| 破净股 | 0<市净率<1，注意资产质量 |
| 派息率 30%–70% | 口径同分红质量方法论 |
| 港股高息 ≥6% | 港股通红利税默认预扣 20%，6% 覆盖税后 |
| 自定义组合 | 股息率/PE/市净率阈值 AND，留空即忽略 |

- 自定义卡选中展开输入面板（三个数字输入，`width:auto` 显式覆盖全局
  `input{width:100%}`，避免 v0.5 布局事故）；至少填一项，否则后端 400。
- 数量 Top N（30/50/100/200，默认 50）+ 开始选股 + 「预计 1 次查询」实时提示。
- 选择/输入/topn 存 localStorage（`screener_v2`），回车即选股。

## 4. Card ② 选股结果

- 汇总行：命中 N 只（top x，口径列名）；操作按钮：复制全部代码 / ➕加入观察池
  （demo 隐藏推池）。
- 表格：代码｜名称｜策略口径列（如 PE/市净率/股息率）——数字即入选证据；
  列服务端按策略排序（估值列升序、股息率列降序）；缺失「—」；
  代码单元格点击即复制（title 提示）；容器横向滚动。
- 状态完备：加载「全市场选股中…」/ 空态「没有符合条件的股票——条件可以放宽」/
  错误内联 / **不可用降级卡**（通道未配置时黄卡说明原因 + 建议先试其他策略），
  绝不静默。
- 推送观察池：POST /api/watchlist-push（group=「筛选·策略名」），成功 toast
  报新增/已存在数量，指向收息佬日历继续跟踪。

## 5. 后端契约

- `POST /api/screener {strategy|custom, limit}` →
  `{strategy:{id,name,intro,market}, columns:[{key,label,fmt}], rows:[{code,name,values}],
  order, limit, unavailable?, disclaimer, demo}`
- 条件编排在服务端注册表（`STRATEGIES` / `build_custom`），前端只传 id 与阈值；
  limit 1–200 钳制；未知策略 400。
- 通道：`wm-screen-index` conditions（INDICATOR 字段/操作符/阈值 + fields 投影 +
  top_n + market），实测 2026-10-26：`$PE_TTM_LAST` ✓ `$PB_TTM_LAST` ✓
  股息率 cn/hk ✓；finpipe 原生 index 积木 500（spec 变更）→ roadmap。

## 6. 视觉（base.css tokens）

- slate 底 / 白卡 / blue-600；卡片圆角 10px；选中态 accent + accent-soft 光圈；
- 全表 tabular-nums；本页无涨跌幅语义，不使用红绿；缺失/禁用用 slate 灰阶；
- 徽章 pill（surface-2）；降级卡 amber（#fffbeb/#92400e）；
- ≤768px：策略网格单列、结果表横向滚动。

## 7. 后续扩展（非本期）

「在平台打开」deeplink（通道响应自带 stock-picking 链接）· 趋势/动量全市场策略
（待 finpipe 二期 index_query）· 结果快照历史 · 更多条件字段（派息率分位等）
