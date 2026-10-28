/* 后端 API 类型 —— 字段与 bigwinner.shouxi server / tools 的返回契约对齐。
   约定：Optional 字段缺失时前端必须显式显示「—」，不猜测填 0。 */

export interface AppInfo {
  demo: boolean;
  setup_url?: string | null;
  /** 演示模式：真实数据快照的生成日期（非实时） */
  demo_as_of?: string | null;
  /** 演示模式：快照覆盖的示例标的（引导文案用） */
  demo_symbols?: { code: string; name: string }[] | null;
  /** GitHub Pages 只读演示构建（静态数据源，操作引导本地运行） */
  pages_demo?: boolean;
}

export interface ToolInfo {
  slug: string;
  title: string;
  tagline: string;
}

export interface SymbolItem {
  code: string;
  name: string;
  market?: string;
}

export interface SymbolSearchResult {
  results: SymbolItem[];
  total: number;
  as_of?: string | null;
}

export interface KeyStatus {
  custom: boolean;
  demo: boolean;
}

export interface KeySaveResult {
  ok: boolean;
  message: string;
}

/* ---------------- 持仓档案 / 快照 ---------------- */

export interface PositionSetMeta {
  name: string;
  n: number;
  updated_at: string;
}

export interface PositionsListResult {
  sets: PositionSetMeta[];
}

export interface PositionsLoadResult {
  name: string;
  positions: Record<string, unknown>[];
}

export interface PositionsLatestResult {
  set: {
    name: string;
    positions: Record<string, unknown>[];
    updated_at?: string;
  } | null;
}

export interface SnapshotItem {
  taken_at: string;
  n_positions: number;
  total_market_value?: number | null;
  total_dividend?: number | null;
  portfolio_yield?: number | null;
  mode?: string;
  deep?: boolean;
}

export interface SnapshotsResult {
  history: SnapshotItem[];
}

/* ---------------- 持仓透视 ---------------- */

export interface XrayRow {
  code: string;
  market?: string;
  name?: string | null;
  shares: number;
  price?: number | null;
  currency?: string;
  market_value?: number | null;
  weight?: number | null;
  eps_ttm?: number | null;
  dps_ttm?: number | null;
  div_yield?: number | null;
  cost_yield?: number | null;
  payout?: number | null;
  annual_dividend?: number | null;
  pnl_ratio?: number | null;
  missing?: string[];
  price_estimated?: boolean;
}

export interface XrayStability {
  payout_buckets?: Record<string, number>;
  cr3?: number | null;
  cr3_codes?: string[];
  stable_years_cover?: number | null;
  warnings?: string[];
}

export interface XrayResult {
  rows: XrayRow[];
  stability?: XrayStability;
  completeness?: string;
  notes?: string[];
  total_market_value?: number | null;
  total_dividend?: number | null;
  portfolio_yield?: number | null;
  portfolio_cost_yield?: number | null;
  total_profit?: number | null;
  portfolio_pnl?: number | null;
  portfolio_pnl_ratio?: number | null;
  generated_at?: string;
  fx_note?: string;
  total_currency?: string;
  disclaimer?: string;
  demo?: boolean;
  snapshot_saved?: boolean;
  /** 本次取数遇到凭证类错误（Key 无效/过期）——页面据此显示换 Key 横幅 */
  auth_error?: string;
}

/* ---------------- 分红质量 ---------------- */

export interface QualityBand {
  band?: string;
  vs_industry?: string;
  mix?: string;
  note?: string;
  cf_np_penalty?: string;
  trend_penalty?: string;
  ibd_penalty?: string;
  quick_penalty?: string;
  ocf_min?: string;
  np_decline?: string;
  score?: number | null;
  weight?: number | null;
}

export interface RecurringYear {
  year: number;
  dps?: number | null;
  count: number;
  special?: boolean;
}

export interface SpecialDiv {
  year: number;
  kind?: string;
  dps?: number | null;
}

export interface QualityRow {
  code: string;
  market?: string;
  name?: string;
  org_form?: string | null;
  org_type?: number | null;
  eligible: boolean;
  reason?: string;
  yield_ttm?: number | null;
  payout_ttm?: number | null;
  payout_lyr?: number | null;
  payout_3y_avg?: number | null;
  payout_5y_avg?: number | null;
  payout_trend?: string | null;
  consecutive_years?: number | null;
  ocf_cover?: number | null;
  fcf_cover?: number | null;
  tl_rate?: number | null;
  tl_ind_avg?: number | null;
  ability_score?: number | null;
  willingness_grade?: string | null;
  confidence?: string | null;
  flags?: string[];
  missing?: string[];
  ability_bands?: Record<string, QualityBand>;
  recurring_by_year?: RecurringYear[];
  specials?: SpecialDiv[];
  payout_series?: { year: number; payout?: number | null }[];
  /* 覆盖计算明细 */
  npts_ttm?: number | null;
  ncfo_ttm?: number | null;
  fcf_ttm?: number | null;
  earnings_cover?: number | null;
  cash_conversion?: number | null;
  capex_ratio?: number | null;
  roe?: number | null;
  roic?: number | null;
  npts_yoy?: number | null;
  ibd_rate?: number | null;
  quick?: number | null;
  /* 股本结构（仅展示） */
  free_holder_sum?: number | null;
  exec_hold?: number | null;
  has_buyback?: boolean | null;
}

export interface QualitySummary {
  scored_count?: number;
  eligible_count?: number;
  skipped?: unknown[];
  avg_ability?: number | null;
  willingness?: Partial<Record<'A' | 'B' | 'C' | 'D', number>>;
  coverage_thin?: number;
  yield_trap?: number;
  avg_payout_ttm?: number | null;
  avg_ocf_cover?: number | null;
}

export interface QualityResult {
  rows: QualityRow[];
  summary: QualitySummary;
  notes?: string[];
  disclaimer?: string;
  demo?: boolean;
}

/* ---------------- 分红日历 ---------------- */

export interface CalendarEvent {
  code: string;
  market?: string;
  name?: string;
  stage: string;
  status?: string;
  kind?: string;
  content?: string;
  ex_date?: string | null;
  record_date?: string | null;
  pay_date?: string | null;
  days_to_ex?: number | null;
  days_to_pay?: number | null;
  days_to_cash?: number | null;
  shares: number;
  gross?: number | null;
  dps?: number | null;
  currency?: string;
  yield_ttm?: number | null;
  is_plan?: boolean;
}

export interface CalendarResult {
  events: CalendarEvent[];
  summary?: {
    ex_count_30?: number;
    plan_count?: number;
  };
  mode: string;
  market?: string;
  disclaimer?: string;
}

/* ---------------- 记账 ---------------- */

export interface LedgerEvent {
  ex_date: string;
  dps?: number | null;
  gross?: number | null;
  tax?: number | null;
  net?: number | null;
  tax_ratio?: number | null;
  holding_days?: number | null;
  currency?: string;
  tax_source?: string;
  estimated?: boolean;
}

export interface LedgerStock {
  name?: string;
  code: string;
  market?: string;
  currency?: string;
  events: LedgerEvent[];
}

export interface LedgerYear {
  year: string | number;
  gross?: number | null;
  tax?: number | null;
  net?: number | null;
  tax_ratio?: number | null;
  events: number;
}

export interface LedgerResult {
  total_gross?: number | null;
  total_tax?: number | null;
  total_net?: number | null;
  total_currency?: string;
  by_year: LedgerYear[];
  stocks: LedgerStock[];
  available_years: (string | number)[];
  note?: string;
}

/* ---------------- 诊股 ---------------- */

export interface DiagnoseResult {
  code: string;
  market: string;
  profile: {
    name?: string;
    org_form?: string | null;
    org_type?: number | null;
    industry?: string | null;
    listing_date?: string | null;
  };
  quote: {
    price?: number | null;
    yield_ttm?: number | null;
    payout_ttm?: number | null;
    currency?: string;
  };
  quality: QualityRow;
  next_event?: CalendarEvent | null;
  notes?: string[];
  disclaimer?: string;
}

/* ---------------- 筛选 ---------------- */

export interface ScreenerColumn {
  key: string;
  label: string;
  fmt?: string;
}

export interface ScreenerRow {
  code: string;
  name?: string;
  values?: Record<string, number | null>;
}

export interface ScreenerResult {
  strategy?: { name?: string };
  columns?: ScreenerColumn[];
  rows?: ScreenerRow[];
  order?: { key: string; dir: 'asc' | 'desc' };
  limit?: number;
  unavailable?: string;
  error?: string;
  demo?: boolean;
}

/* ---------------- 观察池 ---------------- */

export interface WatchlistGroup {
  name: string;
  symbols?: { code?: string }[];
}

export interface WatchlistGroupsResult {
  groups: WatchlistGroup[];
}

export interface WatchlistDiffResult {
  group_exists: boolean;
  will_add: string[];
  already_in: string[];
}

export interface WatchlistPushResult {
  added: string[];
  already_in: string[];
  group_id?: string | null;
}

/* ---------------- 波段 ---------------- */

export interface BiglyChannel {
  current: number;
  pct?: number | null;
  z: number;
  zone: string;
  coverage?: number | null;
  min: number;
  median?: number | null;
  max: number;
  lower1: number;
  upper1: number;
  lower2: number;
  upper2: number;
  avg: number;
  zones?: {
    n: number;
    below_low?: { days: number; ratio?: number | null } | null;
    inside?: { days: number; ratio?: number | null } | null;
    above_high?: { days: number; ratio?: number | null } | null;
  } | null;
}

export interface BiglyLevels {
  buy_price?: number | null;
  sell_price?: number | null;
  low_multiple: number;
  high_multiple: number;
  metric_current: number;
  assumption?: string;
}

export interface BiglyChannelResult {
  symbol: string;
  metric: string;
  window: string;
  demo?: boolean;
  error?: string;
  last_close: number | null;
  channel: BiglyChannel;
  series: [number, number][];
  levels: BiglyLevels;
  safety?: {
    high_entry_drawdown?: {
      median_mdd: number;
      worst_mdd: number;
      sample_n: number;
    } | null;
    stop_reference?: number | null;
  };
  extremes?: {
    low?: { price: number; date?: string; premium_pct?: number | null } | null;
    high?: { price: number; date?: string; discount_pct?: number | null } | null;
    last_close?: number | null;
  };
  disclaimer?: string;
}

export interface BiglySuggest {
  buy_price: number;
  sell_price: number;
  buy_multiple: number;
  sell_multiple: number;
  criteria: {
    strict_ok: boolean;
    near_low_pct: number;
    underwater_ratio: number;
    roundtrips_done: number;
  };
  note?: string;
  stats?: { return_pct?: number | null; mdd?: number | null; days_held?: number | null };
}

export interface BiglyBacktestResult {
  symbol: string;
  metric: string;
  window: string;
  demo?: boolean;
  error?: string;
  suggest?: BiglySuggest | null;
  levels_used?: { buy_price: number; sell_price: number };
  backtest: {
    sell_reason?: string;
    sell_date?: string;
    hit_buy: boolean;
    roundtrips_done?: number;
    buy_date?: string;
    still_holding?: boolean;
    underwater_days?: number | null;
    no_stop_worst_drawdown?: number | null;
    window?: { bars?: number };
    events?: { type: string; date: string; price: number }[];
  };
  compare?: {
    swing?: { return_pct?: number | null; mdd?: number | null; days_held?: number | null; flat_ratio?: number | null };
    hold?: { return_pct?: number | null; mdd?: number | null; days?: number };
    delta?: { return_spread?: number | null; mdd_spread?: number | null };
    verdict?: string;
  };
  safety?: Record<string, unknown>;
  price_stats?: {
    n: number;
    buy_price: number;
    sell_price: number;
    below_buy?: { days: number; ratio?: number | null } | null;
    inside?: { days: number; ratio?: number | null } | null;
    above_sell?: { days: number; ratio?: number | null } | null;
  };
}

export interface BiglyMeta {
  tool: ToolInfo & { slug: string };
  demo: boolean;
}
