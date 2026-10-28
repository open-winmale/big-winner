/* 展示层格式化工具 —— 与旧版 app.js 的口径逐字对齐：
   缺失显式显示「—」，绝不填 0；金额 ≥1e4 转万、≥1e8 转亿。 */

export const DASH = '—';

export function isNum(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v);
}

export function ccyPrefix(ccy?: string | null): string {
  if (ccy === 'HKD') return 'HK$';
  if (ccy === 'USD') return 'US$';
  return '';
}

export function fmtMoney(v: number | null | undefined): string {
  if (!isNum(v)) return DASH;
  const abs = Math.abs(v);
  if (abs >= 1e8) return (v / 1e8).toFixed(2) + ' 亿';
  if (abs >= 1e4) return (v / 1e4).toFixed(2) + ' 万';
  return v.toFixed(2);
}

export function fmtPrice(v: number | null | undefined): string {
  return isNum(v) ? v.toFixed(2) : DASH;
}

export function fmtMoneyCcy(v: number | null | undefined, ccy?: string | null): string {
  return isNum(v) ? ccyPrefix(ccy) + fmtMoney(v) : DASH;
}

export function fmtPriceCcy(v: number | null | undefined, ccy?: string | null): string {
  return isNum(v) ? ccyPrefix(ccy) + v.toFixed(2) : DASH;
}

export function fmtPct(v: number | null | undefined, digits = 2): string {
  return isNum(v) ? (v * 100).toFixed(digits) + '%' : DASH;
}

export function fmtInt(v: number | null | undefined): string {
  return isNum(v) ? Number(v).toLocaleString('zh-CN') : DASH;
}

/** 带符号百分比（不含颜色，颜色用 signClass 在模板上加） */
export function fmtSigned(v: number | null | undefined): string {
  if (!isNum(v)) return DASH;
  return (v > 0 ? '+' : '') + (v * 100).toFixed(2) + '%';
}

export function fmtSignedMoney(v: number | null | undefined): string {
  if (!isNum(v)) return DASH;
  return (v > 0 ? '+' : '') + fmtMoney(v);
}

/** A 股习惯：红涨绿跌 */
export function signClass(v: number | null | undefined): string {
  if (!isNum(v) || v === 0) return '';
  return v > 0 ? 'up' : 'down';
}

/* ---------------- 市场 / 持仓 ---------------- */

export type Market = 'cn' | 'hk' | 'us';

export interface PositionLike {
  code: string;
  market?: string;
  name?: string;
  shares: number | string;
  cost?: number | string | null;
  buy_date?: string | null;
  tax_rate?: number | string | null;
}

export function marketFromCode(code: string, market?: string | null): Market {
  const m = String(market || '').toLowerCase();
  if (m === 'hk' || m === 'us') return m;
  const c = String(code || '').toLowerCase();
  if (c.startsWith('hk.')) return 'hk';
  if (/^\d{5}$/.test(c)) return 'hk';
  return 'cn';
}

export function marketOf(p: PositionLike): Market {
  return marketFromCode(p.code, p.market);
}

export function chipKey(p: { code: string; market?: string | null }): string {
  return marketFromCode(p.code, p.market) + ':' + p.code;
}

export function mktLabel(m?: string | null): string {
  return m === 'hk' ? '港' : (m === 'us' ? '美' : 'A');
}

export function taxSourceLabel(s?: string | null): string {
  return ({
    auto: '自动', position: '单票覆盖', year: '年度覆盖',
    flat: '统一税率', hk_default: '港股默认', fallback: '估算(缺买入日)',
  } as Record<string, string>)[s || ''] || s || '自动';
}

export function defaultBuyDate(): string {
  return `${new Date().getFullYear()}-01-01`;
}

/** 页面内部持仓行：税率统一存小数（''=不覆盖），买入日默认今年 1/1 */
export interface Position {
  code: string;
  market: Market;
  name: string;
  shares: number | string;
  cost: number | string | '';
  buy_date: string;
  tax_rate: number | string | '';
}

export function normalizePosition(p: PositionLike): Position {
  let tax: number | '' = '';
  if (p.tax_rate !== '' && p.tax_rate != null) {
    const n = Number(p.tax_rate);
    if (Number.isFinite(n)) tax = n > 1 ? n / 100 : n;
  }
  return {
    code: p.code,
    market: marketFromCode(p.code, p.market),
    name: p.name || '',
    shares: p.shares,
    cost: p.cost == null ? '' : p.cost,
    buy_date: p.buy_date || defaultBuyDate(),
    tax_rate: tax,
  };
}

/* ---------------- 分红质量 / 诊股 ---------------- */

export function abilityBand(score: number | null | undefined): { label: string; cls: string } {
  if (score == null) return { label: '—', cls: '' };
  if (score >= 80) return { label: '强', cls: 'ok' };
  if (score >= 60) return { label: '中', cls: 'ok' };
  if (score >= 40) return { label: '偏弱', cls: 'warn' };
  return { label: '弱', cls: 'warn' };
}

export function confidenceLabel(c?: string | null): string {
  return ({ high: '高', medium: '中', low: '低' } as Record<string, string>)[c || ''] || c || '—';
}

export const ORG_TYPE_LABEL: Record<number, string> = {
  1: '一般企业', 2: '银行', 3: '保险', 4: '证券',
};

export const PAYOUT_TREND_ARROW: Record<string, string> = { up: '↑', down: '↓', flat: '→' };

/* ---------------- 波段 ---------------- */

export const ZONE_TEXT: Record<string, string> = {
  belowLow: '低于低估线', low: '偏低', normal: '正常区间',
  high: '偏高', aboveHigh: '高于高估线',
};

export const ZONE_CLS: Record<string, string> = {
  belowLow: 'badge ok', low: 'badge ok', normal: 'badge',
  high: 'badge warn', aboveHigh: 'badge warn',
};

export function pctText(v: number | null | undefined, digits = 1): string {
  return isNum(v) ? (v * 100).toFixed(digits) + '%' : DASH;
}

export function pctileText(v: number | null | undefined): string {
  return isNum(v) ? (v * 100).toFixed(0) + '%' : DASH;
}

export function fmtPctSigned(v: number | null | undefined, digits = 1): string {
  if (!isNum(v)) return DASH;
  return (v >= 0 ? '+' : '') + (v * 100).toFixed(digits) + '%';
}
