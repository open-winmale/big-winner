/* GitHub Pages 只读演示的静态传输层（vite --mode pages 构建时启用）。
   命中 pages-demo.json 的预烘结果原样返回；只读接口静态直返；
   未命中或写操作 → 打开「本地运行指引」弹窗并抛 ApiError。
   匹配键的规范化必须与 scripts/bake_pages_demo.py 严格一致。 */
import { ref } from 'vue';
import { ApiError } from './client';
import type { PositionPayload } from './client';
import type { AppInfo, BiglyMeta, SymbolSearchResult, ToolInfo } from './types';

interface Entry { match: Record<string, unknown>; result: unknown; }
interface PagesDemoData {
  as_of: string;
  note: string;
  entries: Record<string, Entry[]>;
}

/** 本地运行指引弹窗的全局开关（LocalGuideModal 绑定；本地构建永远关闭） */
export const guideOpen = ref(false);

export function openGuide(): void {
  guideOpen.value = true;
}

let cache: PagesDemoData | null = null;
let loading: Promise<PagesDemoData> | null = null;

const SAMPLE_POSITION = { code: '600519', market: 'cn', name: '贵州茅台', shares: 1000 };

async function loadData(): Promise<PagesDemoData> {
  if (cache) return cache;
  if (!loading) {
    loading = fetch('pages-demo.json').then((r) => {
      if (!r.ok) throw new ApiError('演示数据加载失败（HTTP ' + r.status + '）', r.status);
      return r.json() as Promise<PagesDemoData>;
    }).then((d) => { cache = d; return d; });
  }
  return loading;
}

function asOf(): string {
  return cache?.as_of ?? '';
}

/** 与 bake 脚本 canon_positions 同款：代码/市场/股数/成本，排序后紧凑 JSON。
    对象键序必须与 python sort_keys=True 一致（c,k,m,s 字母序）。 */
function canonPositions(items: unknown[]): string {
  const rows = (items as PositionPayload[]).map((p) => ({
    c: String(p?.code ?? '').trim(),
    k: p?.cost === null || p?.cost === undefined || p?.cost === ''
      ? null : Number(p?.cost),
    m: String(p?.market
      ?? (String(p?.code ?? '').toLowerCase().startsWith('hk') ? 'hk' : 'cn')),
    s: Math.trunc(Number(p?.shares ?? 0)) || 0,
  })).sort((a, b) => (a.m + a.c).localeCompare(b.m + b.c));
  return JSON.stringify(rows);
}

/** 与 bake 脚本 canon_custom 同款：键排序后紧凑 JSON */
function canonCustom(spec: Record<string, unknown> | undefined): string {
  const out: Record<string, unknown> = {};
  for (const k of Object.keys(spec ?? {}).sort()) out[k] = (spec as Record<string, unknown>)[k];
  return JSON.stringify(out);
}

function matches(entry: Entry, payload: Record<string, unknown> | undefined): boolean {
  const body = payload ?? {};
  return Object.entries(entry.match).every(([key, want]) => {
    let got: unknown = body[key];
    if (key === 'pos') got = canonPositions((body.positions as unknown[]) ?? []);
    if (key === 'custom' && got && typeof got === 'object') {
      got = canonCustom(got as Record<string, unknown>);
    }
    return got !== undefined && String(got) === String(want);
  });
}

function guideError(): ApiError {
  openGuide();
  return new ApiError('只读在线演示未包含此操作：本地运行完整工具即可（页顶「本地运行」有命令）', 0);
}

/** POST 入口：只读命中 → 预烘结果；写操作 / 未命中 → 本地指引 */
export async function staticRequest<T>(path: string,
                                       payload?: Record<string, unknown>): Promise<T> {
  await loadData();
  const readonly: Record<string, unknown> = {
    'key-status': { custom: false, demo: true },
    'positions-latest': { set: { name: '示例持仓', updated_at: asOf(),
                                 positions: [SAMPLE_POSITION] } },
    'positions-list': { sets: [] },
    'snapshots': { history: [] },
    'watchlist-groups': { groups: [] },
  };
  if (path in readonly) return readonly[path] as T;

  const entries = cache?.entries[path];
  const hit = entries?.find((e) => matches(e, payload));
  if (hit) return hit.result as T;
  throw guideError();
}

/** GET 入口：档案类接口静态直返 */
export async function staticGet<T>(path: string): Promise<T> {
  await loadData();
  const [route, query = ''] = path.split('?');
  if (route === '/api/appinfo') return pagesAppInfo() as T;
  if (route === '/api/tools') {
    return { tools: [
      { slug: 'dividend-xray', title: '收息佬',
        tagline: '攒股收息驾驶舱：分红日历 · 持续性分析 · 税后记账' },
      { slug: 'bigly', title: '波段',
        tagline: '估值买卖点区间参考：通道 · 推荐区间 · 拨测回看' },
      { slug: 'screener', title: '选股',
        tagline: '预置策略 · 一键全市场 —— 条件与数字都摆给你看' },
    ], demo: true } as { tools: ToolInfo[]; demo: true } as T;
  }
  if (route === '/api/health') {
    return { ok: true, demo: true, time: 'pages-static' } as T;
  }
  if (route === '/api/bigly/meta') {
    return { tool: { slug: 'bigly', title: '波段',
                     tagline: '估值买卖点区间参考' },
             demo: false } as BiglyMeta as T;
  }
  if (route === '/api/symbols' || route === '/api/bigly/symbols') {
    const q = new URLSearchParams(query).get('q') ?? '';
    const hit = !q || '600519'.includes(q) || '贵州茅台'.includes(q)
      || 'gzmt'.includes(q.toLowerCase());
    const result: SymbolSearchResult = {
      results: hit ? [{ code: '600519', name: '贵州茅台', market: 'cn' }] : [],
      total: hit ? 1 : 0,
      as_of: asOf(),
    };
    return result as T;
  }
  throw guideError();
}

/** AppInfo 组装：静态 appinfo 的字段源（client.ts 与 useApp 复用） */
export function pagesAppInfo(): AppInfo {
  return {
    demo: true, setup_url: null,
    demo_as_of: asOf(),
    demo_symbols: [{ code: SAMPLE_POSITION.code, name: SAMPLE_POSITION.name }],
    pages_demo: true,
  };
}
