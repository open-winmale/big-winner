import { ref, watch } from 'vue';
import { defineStore } from 'pinia';
import { api, errText, type PositionPayload, type TaxOptions } from '@/api/client';
import type {
  CalendarResult, DiagnoseResult, LedgerResult, QualityResult,
  SymbolItem, XrayResult,
} from '@/api/types';
import { chipKey, marketOf, normalizePosition, type Position } from '@/format';

export type CalendarMode = 'positions' | 'codes' | 'market';

export function eventInHorizon(
  e: { is_plan?: boolean; days_to_ex?: number | null; days_to_pay?: number | null;
       days_to_cash?: number | null; stage: string },
  horizon: number,
): boolean {
  if (e.is_plan) return true;
  if (e.days_to_ex != null && e.days_to_ex >= 0 && e.days_to_ex <= horizon) return true;
  if (e.days_to_pay != null && e.days_to_pay >= 0 && e.days_to_pay <= horizon) return true;
  if (e.stage === '已到账' && e.days_to_cash != null) {
    return e.days_to_cash >= -Math.min(30, horizon) && e.days_to_cash <= 0;
  }
  if (e.stage === '已除权待到账' && e.days_to_pay != null && e.days_to_pay >= 0) return true;
  return false;
}

export const useShouxi = defineStore('shouxi', () => {
  /* ---------------- 持仓 ---------------- */
  const positions = ref<Position[]>([]);
  const currentMarket = ref<'cn' | 'hk'>('cn');
  const autoNote = ref('');
  const autoNoteHasSet = ref(false);

  function posPayload(p: Position): PositionPayload {
    return {
      code: p.code,
      market: marketOf(p),
      name: p.name || null,
      shares: p.shares,
      cost: p.cost,
      buy_date: p.buy_date || '',
      tax_rate: (p.tax_rate === '' || p.tax_rate == null) ? null : Number(p.tax_rate),
    };
  }

  function addPosition(p: { code: string; market?: string; name?: string; shares?: number | string }): boolean {
    const key = chipKey({ code: p.code, market: p.market });
    if (positions.value.some((x) => chipKey(x) === key)) return false;
    positions.value.push(normalizePosition({
      code: p.code, market: p.market, name: p.name, shares: p.shares ?? 1000,
    }));
    return true;
  }

  function removeAt(idx: number): void {
    positions.value.splice(idx, 1);
  }

  function updateField(idx: number, field: 'shares' | 'cost' | 'buy_date' | 'tax_rate', value: string): void {
    const p = positions.value[idx];
    if (!p) return;
    if (field === 'tax_rate') {
      const n = Number(value);
      p.tax_rate = (value === '' || !Number.isFinite(n)) ? '' : n / 100;
    } else {
      p[field] = value;
    }
  }

  function bulkBuyDate(day: string, onlyEmpty: boolean): void {
    if (!day) return;
    positions.value.forEach((p) => { if (!onlyEmpty || !p.buy_date) p.buy_date = day; });
  }

  function bulkTaxRate(pct: number | null): void {
    positions.value.forEach((p) => { p.tax_rate = pct == null ? '' : pct / 100; });
  }

  /* ---------------- 自动载入 / 示例持仓 ---------------- */
  async function autoLoad(): Promise<void> {
    if (positions.value.length) return;
    try {
      const d = await api.positionsLatest();
      const set = d.set;
      if (set && Array.isArray(set.positions) && set.positions.length) {
        positions.value = set.positions.map((p) => normalizePosition(p as never));
        autoNote.value =
          `已自动载入「${set.name}」 · ${positions.value.length} 只 · 更新于 ${set.updated_at || ''}`;
        autoNoteHasSet.value = true;
        void runXray();
        void loadCalendar('positions');
        return;
      }
      seed();
    } catch {
      seed();
    }
  }

  function seed(): void {
    positions.value = [normalizePosition({
      code: '600036', market: 'cn', name: '招商银行', shares: 1000,
    })];
    autoNote.value = '示例持仓：招商银行 · 1,000 股（仅本次会话）';
    autoNoteHasSet.value = false;
    void runXray();
    void loadCalendar('positions');
  }

  /* ---------------- 持仓透视 ---------------- */
  const deep = ref(false);
  const xray = ref<XrayResult | null>(null);
  const xrayLoading = ref(false);
  const xrayError = ref('');

  async function runXray(): Promise<void> {
    if (!positions.value.length) { xray.value = null; return; }
    xrayLoading.value = true;
    xrayError.value = '';
    try {
      xray.value = await api.dividendXray({
        positions: positions.value.map(posPayload), deep: deep.value,
      });
    } catch (e) {
      xrayError.value = e instanceof Error ? e.message : String(e);
    } finally {
      xrayLoading.value = false;
    }
  }

  /* ---------------- 分红质量 ---------------- */
  const qualityPanelVisible = ref(false);
  const quality = ref<QualityResult | null>(null);
  const qualityLoading = ref(false);
  const qualityError = ref('');

  async function openQuality(): Promise<void> {
    qualityPanelVisible.value = true;
    if (!positions.value.length) { quality.value = null; return; }
    qualityLoading.value = true;
    qualityError.value = '';
    try {
      quality.value = await api.dividendQuality({
        positions: positions.value.map(posPayload),
      });
    } catch (e) {
      qualityError.value = errText(e);
    } finally {
      qualityLoading.value = false;
    }
  }

  /* ---------------- 诊股弹层 ---------------- */
  const diagnoseOpen = ref(false);
  const diagnoseCode = ref('');
  const diagnose = ref<DiagnoseResult | null>(null);
  const diagnoseLoading = ref(false);
  const diagnoseError = ref('');

  async function openDiagnose(code: string): Promise<void> {
    diagnoseOpen.value = true;
    diagnoseCode.value = code;
    diagnose.value = null;
    diagnoseError.value = '';
    diagnoseLoading.value = true;
    try {
      diagnose.value = await api.diagnose({ code });
    } catch (e) {
      diagnoseError.value = errText(e);
    } finally {
      diagnoseLoading.value = false;
    }
  }

  /* ---------------- 分红日历 ---------------- */
  const calendarMode = ref<CalendarMode>('positions');
  const calendarHorizon = ref(30);
  const calendarMarket = ref<'cn' | 'hk'>('cn');
  const calendarData = ref<CalendarResult | null>(null);
  const calendarLoading = ref(false);
  const calendarError = ref('');
  const calendarWatchlist = ref<SymbolItem[] | []>([]);
  const importingGroups = ref(false);
  const watchlistGroups = ref<{ name: string; symbols?: { code?: string }[] }[] | null>(null);

  let marketCache: { at: number; data: CalendarResult } | null = null;
  let marketPreviewInflight: Promise<CalendarResult | null> | null = null;

  /** 持仓视图没有未来事件时，市场高股息池的预览块 */
  const marketPreview = ref<CalendarResult | null>(null);
  const marketPreviewLoading = ref(false);
  const marketPreviewError = ref('');

  function calendarPayload(mode: CalendarMode): Record<string, unknown> {
    if (mode === 'market') {
      return { mode: 'market', market: calendarMarket.value, limit: 120, tax: taxPayload() };
    }
    if (mode === 'codes') {
      return { mode: 'codes', codes: calendarWatchlist.value, tax: taxPayload() };
    }
    return { mode: 'positions', positions: positions.value.map(posPayload), tax: taxPayload() };
  }

  async function loadCalendar(mode: CalendarMode): Promise<void> {
    if (mode === 'positions' && !positions.value.length) {
      calendarMode.value = 'positions';
      calendarData.value = null;
      return;
    }
    calendarMode.value = mode;
    // 市场池 5 分钟缓存：刚拉过同一市场就直接复用
    if (mode === 'market' && marketCache
        && (marketCache.data.market || 'cn') === calendarMarket.value
        && Date.now() - marketCache.at < 300000) {
      calendarData.value = marketCache.data;
      calendarError.value = '';
      return;
    }
    calendarLoading.value = true;
    calendarError.value = '';
    try {
      const d = await api.calendar(calendarPayload(mode));
      if (mode === 'market') {
        calendarMarket.value = (d.market || calendarMarket.value) as 'cn' | 'hk';
        marketCache = { at: Date.now(), data: d };
      }
      calendarData.value = d;
    } catch (e) {
      calendarError.value = errText(e);
    } finally {
      calendarLoading.value = false;
    }
  }

  /** 持仓没有未来事件 → 拉市场池预览（先于用户点「高股息池」） */
  async function ensureMarketPreview(): Promise<void> {
    const markets = new Set(positions.value.map((p) => marketOf(p)));
    const previewMarket: 'cn' | 'hk' = (markets.size === 1 && markets.has('hk')) ? 'hk' : 'cn';
    calendarMarket.value = previewMarket;
    if (marketCache && (marketCache.data.market || 'cn') === previewMarket) {
      marketPreview.value = marketCache.data;
      marketPreviewLoading.value = false;
      return;
    }
    if (marketPreviewInflight) return;
    marketPreviewLoading.value = true;
    marketPreviewError.value = '';
    marketPreviewInflight = api.calendar({
      mode: 'market', market: previewMarket, limit: 120, tax: taxPayload(),
    }).then((d) => {
      marketCache = { at: Date.now(), data: d };
      return d;
    }).catch((e) => {
      marketPreviewError.value = errText(e);
      return null;
    }).finally(() => { marketPreviewInflight = null; });
    const d = await marketPreviewInflight;
    marketPreviewLoading.value = false;
    if (d) marketPreview.value = d;
  }

  async function showWatchlistGroups(): Promise<void> {
    importingGroups.value = true;
    try {
      const d = await api.watchlistGroups();
      watchlistGroups.value = d.groups || [];
    } catch (e) {
      watchlistGroups.value = [];
      calendarError.value = errText(e);
    } finally {
      importingGroups.value = false;
    }
  }

  function importGroup(g: { name: string; symbols?: { code?: string }[] }): void {
    calendarWatchlist.value = (g.symbols || []) as SymbolItem[];
    void loadCalendar('codes');
  }

  /* ---------------- 记账 ---------------- */
  const ledgerOpen = ref(false);
  const ledgerYear = ref('');
  const ledgerTax = ref<TaxOptions>({ mode: 'auto', flat_rate: null, year_rates: {} });
  const ledgerData = ref<LedgerResult | null>(null);
  const ledgerLoading = ref(false);
  const ledgerError = ref('');

  function taxPayload(): TaxOptions {
    return {
      mode: ledgerTax.value.mode,
      flat_rate: ledgerTax.value.flat_rate,
      year_rates: ledgerTax.value.year_rates,
    };
  }

  function openLedger(): void {
    if (!positions.value.length) return;
    ledgerOpen.value = true;
    ledgerYear.value = '';
    ledgerTax.value = { mode: 'auto', flat_rate: null, year_rates: {} };
    ledgerData.value = null;
    void fetchLedger();
  }

  function closeLedger(): void {
    ledgerOpen.value = false;
    ledgerData.value = null;
  }

  function setTaxMode(mode: TaxOptions['mode']): void {
    ledgerTax.value.mode = mode;
    if (mode === 'flat' && ledgerTax.value.flat_rate == null) {
      ledgerTax.value.flat_rate = 0.20;
    }
    void fetchLedger();
  }

  async function fetchLedger(): Promise<void> {
    if (!ledgerOpen.value) return;
    ledgerLoading.value = true;
    ledgerError.value = '';
    try {
      const d = await api.ledger({
        positions: positions.value.map(posPayload),
        year: ledgerYear.value || null,
        tax: taxPayload(),
      });
      if (!ledgerOpen.value) return;
      ledgerData.value = d;
      // 持仓变化导致所选年份消失：重置为全部历史并再取一次
      const years = (d.available_years || []).map(String);
      if (ledgerYear.value && !years.includes(ledgerYear.value)) {
        ledgerYear.value = '';
        void fetchLedger();
      }
    } catch (e) {
      if (ledgerOpen.value) {
        ledgerError.value = errText(e);
      }
    } finally {
      ledgerLoading.value = false;
    }
  }

  /* ---------------- 联动：持仓变化 → 账本/日历防抖刷新 ---------------- */
  let ledgerTimer: ReturnType<typeof setTimeout> | null = null;
  let calendarTimer: ReturnType<typeof setTimeout> | null = null;

  watch(positions, () => {
    if (ledgerOpen.value) {
      if (ledgerTimer) clearTimeout(ledgerTimer);
      ledgerTimer = setTimeout(() => void fetchLedger(), 300);
    }
    if (calendarMode.value === 'positions') {
      if (calendarTimer) clearTimeout(calendarTimer);
      calendarTimer = setTimeout(() => {
        if (!positions.value.length) { calendarData.value = null; return; }
        void loadCalendar('positions');
      }, 500);
    }
  }, { deep: true });

  return {
    positions, currentMarket, autoNote, autoNoteHasSet,
    autoLoad, seed,
    addPosition, removeAt, updateField, bulkBuyDate, bulkTaxRate, posPayload,
    deep, xray, xrayLoading, xrayError, runXray,
    qualityPanelVisible, quality, qualityLoading, qualityError, openQuality,
    diagnoseOpen, diagnoseCode, diagnose, diagnoseLoading, diagnoseError, openDiagnose,
    calendarMode, calendarHorizon, calendarMarket, calendarData, calendarLoading,
    calendarError, calendarWatchlist, marketPreview, marketPreviewLoading,
    marketPreviewError, importingGroups, watchlistGroups,
    loadCalendar, ensureMarketPreview, showWatchlistGroups, importGroup,
    ledgerOpen, ledgerYear, ledgerTax, ledgerData, ledgerLoading, ledgerError,
    openLedger, closeLedger, setTaxMode, fetchLedger, taxPayload,
  };
});
