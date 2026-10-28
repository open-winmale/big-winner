/* 类型化 API 客户端：与 bigwinner.shouxi 的 17 个 POST handler + GET 端点一一对应。
   错误契约：非 200 → body.error（ToolError 原样文案），原样抛给 UI 展示。
   Pages 只读演示构建（--mode pages）时全部请求改走 static.ts 静态层。 */
import type {
  AppInfo, BiglyBacktestResult, BiglyChannelResult, BiglyMeta, CalendarResult,
  DiagnoseResult, KeySaveResult, KeyStatus, LedgerResult, PositionsLatestResult,
  PositionsListResult, PositionsLoadResult, QualityResult, ScreenerResult,
  SnapshotItem, SymbolSearchResult, ToolInfo, WatchlistDiffResult,
  WatchlistGroupsResult, WatchlistPushResult, XrayResult,
} from './types';
import { openGuide, staticGet, staticRequest } from './static';

/** Pages 构建标记：vite build --mode pages */
export const PAGES_MODE = import.meta.env.MODE === 'pages';

export interface PositionPayload {
  code: string;
  market: string;
  name?: string | null;
  shares: number | string;
  cost?: number | string | null;
  buy_date?: string | null;
  tax_rate?: number | null;
}

export interface TaxOptions {
  mode: 'auto' | 'flat' | 'by_year';
  flat_rate?: number | null;
  year_rates?: Record<string, number>;
}

export class ApiError extends Error {
  status: number;
  hint?: string;
  disclaimer?: string;
  constructor(message: string, status: number, hint?: string, disclaimer?: string) {
    super(message);
    this.status = status;
    this.hint = hint;
    this.disclaimer = disclaimer;
  }
}

/** 展示用错误文案：后端带了 hint（如「若为 401/403，请配置自己的 AppID…」）就附在括号里 */
export function errText(e: unknown): string {
  if (!(e instanceof ApiError)) return e instanceof Error ? e.message : String(e);
  return e.hint ? `${e.message}（${e.hint}）` : e.message;
}

/** 错误文案是否指向凭证问题（401/403/配 Key 引导）——用于显示「配置 Key」入口 */
export function isAuthErrorText(t: string): boolean {
  return /401|403|AppID|Key 配置|自己的 Key/.test(t);
}

async function getJson<T>(url: string): Promise<T> {
  const resp = await fetch(url);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const body = data as { error?: string; hint?: string; disclaimer?: string };
    throw new ApiError(body.error || `HTTP ${resp.status}`, resp.status,
      body.hint, body.disclaimer);
  }
  return data as T;
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const resp = await fetch('/api/' + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const err = data as { error?: string; hint?: string; disclaimer?: string };
    throw new ApiError(err.error || `HTTP ${resp.status}`, resp.status,
      err.hint, err.disclaimer);
  }
  return data as T;
}

/** POST 统一入口：pages 构建走静态层，其余走同源 /api */
function request<T>(path: string, body?: Record<string, unknown>): Promise<T> {
  if (PAGES_MODE) return staticRequest<T>(path, body);
  return postJson<T>(path, body);
}

/** GET 统一入口：pages 构建走静态层，其余走同源 /api */
function requestGet<T>(path: string): Promise<T> {
  if (PAGES_MODE) return staticGet<T>(path);
  return getJson<T>(path);
}

export const api = {
  /* ---- GET ---- */
  appinfo: () => requestGet<AppInfo>('/api/appinfo'),
  tools: () => requestGet<{ tools: ToolInfo[]; demo: boolean }>('/api/tools'),
  health: () => requestGet<{ ok: boolean; demo: boolean; time: string }>('/api/health'),
  symbols: (q: string, market: string) =>
    requestGet<SymbolSearchResult>(
      `/api/symbols?q=${encodeURIComponent(q)}&market=${encodeURIComponent(market)}`),
  biglySymbols: (q: string, market = 'cn') =>
    requestGet<SymbolSearchResult>(
      `/api/bigly/symbols?q=${encodeURIComponent(q)}&market=${encodeURIComponent(market)}`),
  biglyMeta: () => requestGet<BiglyMeta>('/api/bigly/meta'),
  exportXrayCsv: (positions: unknown): void => {
    if (PAGES_MODE) {
      // 只读演示没有后端可生成 CSV：引导本地运行
      openGuide();
      return;
    }
    // 后端生成 UTF-8 BOM CSV（Excel 直开），走浏览器下载
    window.location.href =
      '/export/xray.csv?positions=' + encodeURIComponent(JSON.stringify(positions));
  },

  /* ---- POST handlers ---- */
  keyStatus: () => request<KeyStatus>('key-status'),
  keySave: (payload: { client_id: string; client_secret: string }) =>
    request<KeySaveResult>('key-save', payload),
  keyClear: () => request<KeySaveResult>('key-clear'),
  dividendXray: (payload: { positions: PositionPayload[]; deep: boolean }) =>
    request<XrayResult>('dividend-xray', payload),
  dividendQuality: (payload: { positions: PositionPayload[] }) =>
    request<QualityResult>('dividend-quality', payload),
  ledger: (payload: { positions: PositionPayload[]; year?: string | null; tax: TaxOptions }) =>
    request<LedgerResult>('ledger', payload),
  calendar: (payload: Record<string, unknown>) =>
    request<CalendarResult>('calendar', payload),
  diagnose: (payload: { code: string; name?: string }) =>
    request<DiagnoseResult>('diagnose', payload),
  screener: (payload: Record<string, unknown>) =>
    request<ScreenerResult>('screener', payload),
  positionsSave: (payload: { name: string; positions: unknown[] }) =>
    request<{ ok: boolean; name: string; n: number }>('positions-save', payload),
  positionsList: () => request<PositionsListResult>('positions-list'),
  positionsLoad: (payload: { name: string }) =>
    request<PositionsLoadResult>('positions-load', payload),
  positionsLatest: () => request<PositionsLatestResult>('positions-latest'),
  snapshots: () => request<{ history: SnapshotItem[] }>('snapshots'),
  watchlistDiff: (payload: { group: string; positions: unknown[] }) =>
    request<WatchlistDiffResult>('watchlist-diff', payload),
  watchlistPush: (payload: { group: string; positions: unknown[] }) =>
    request<WatchlistPushResult>('watchlist-push', payload),
  watchlistGroups: () => request<WatchlistGroupsResult>('watchlist-groups'),
  biglyChannel: (payload: { symbol: string; metric: string; window: string }) =>
    request<BiglyChannelResult>('bigly/channel', payload),
  biglyBacktest: (payload: {
    symbol: string; metric: string; window: string;
    buy?: number; sell?: number; stop?: number;
  }) => request<BiglyBacktestResult>('bigly/backtest', payload),
};
