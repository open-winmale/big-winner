<script setup lang="ts">
import { computed, ref } from 'vue';
import { useShouxi } from '@/features/shouxi/store';
import {
  DASH, fmtMoney, fmtMoneyCcy, fmtPct, fmtPriceCcy, taxSourceLabel,
} from '@/format';
import MarketTag from '@/components/MarketTag.vue';

const store = useShouxi();

const hasHk = computed(() =>
  (store.ledgerData?.stocks || []).some((s) => s.currency === 'HKD'));

const effectiveRate = computed(() => {
  const d = store.ledgerData;
  if (!d) return null;
  if (d.total_gross != null && d.total_gross !== 0 && d.total_tax != null) {
    return d.total_tax / d.total_gross;
  }
  return null;
});

const totalEvents = computed(() =>
  (store.ledgerData?.stocks || []).reduce((n, s) => n + (s.events || []).length, 0));

const detailRows = computed(() => {
  const rows: {
    key: string; name: string; code: string; market: string; currency: string;
    ex_date: string; dps?: number | null; gross?: number | null;
    tax_ratio?: number | null; tax?: number | null; net?: number | null;
    holding_days?: number | null; tax_source?: string; estimated?: boolean;
  }[] = [];
  for (const s of store.ledgerData?.stocks || []) {
    for (const e of s.events || []) {
      rows.push({
        key: `${s.code}-${e.ex_date}-${rows.length}`,
        name: s.name || '', code: s.code, market: s.market || 'cn',
        currency: e.currency || s.currency || 'CNY',
        ex_date: e.ex_date, dps: e.dps, gross: e.gross, tax: e.tax, net: e.net,
        tax_ratio: e.tax_ratio, holding_days: e.holding_days,
        tax_source: e.tax_source, estimated: e.estimated,
      });
    }
  }
  return rows;
});

const noteParts = computed(() =>
  String(store.ledgerData?.note || '').split('。').map((s) => s.trim()).filter(Boolean));

function flatPct(v: number | null | undefined): string {
  return v == null ? '' : String(Number((v * 100).toFixed(4)));
}

function setFlat(v: number): void {
  store.ledgerTax.flat_rate = v / 100;
  void store.fetchLedger();
}

function getYearRate(year: string | number): string {
  return flatPct(store.ledgerTax.year_rates?.[String(year)]);
}

function setYearRate(year: string | number, raw: string): void {
  const rates = store.ledgerTax.year_rates ??= {};
  if (raw === '') delete rates[String(year)];
  else rates[String(year)] = Number(raw) / 100;
}

function applyAllYearRates(): void {
  if (bulkYearRate.value == null || Number.isNaN(bulkYearRate.value)) return;
  const rates = store.ledgerTax.year_rates ??= {};
  for (const y of store.ledgerData?.available_years || []) {
    rates[String(y)] = bulkYearRate.value / 100;
  }
  void store.fetchLedger();
}

const bulkYearRate = ref<number | null>(null);
</script>

<template>
  <div v-if="store.ledgerOpen" class="card ledger-card">
    <div class="card-head">
      <h2>分红记账</h2>
      <span class="hint">汇总按 CNY 折算；逐笔明细为原币。A 股按持有期，港股默认 20%（可改）</span>
      <span class="spacer"></span>
      <button class="ghost" style="padding:4px 10px;font-size:12.5px"
              @click="store.closeLedger()">收起</button>
    </div>

    <div class="ledger-controls">
      <div class="controls-row">
        <label>年份
          <select v-model="store.ledgerYear">
            <option value="">全部历史</option>
            <option v-for="y in store.ledgerData?.available_years || []" :key="String(y)"
                    :value="String(y)">{{ y }}</option>
          </select>
        </label>
        <label>计税方式
          <select :value="store.ledgerTax.mode"
                  @change="store.setTaxMode(($event.target as HTMLSelectElement).value as 'auto'|'flat'|'by_year')">
            <option value="auto">自动（A 股按持有时长 / 港股 20%）</option>
            <option value="flat">统一税率</option>
            <option value="by_year">分年度税率</option>
          </select>
        </label>
        <span class="muted" style="font-size:11.5px">单票覆盖优先于全局设置</span>
      </div>

      <div v-if="store.ledgerTax.mode === 'flat'" class="tax-extra">
        <label>税率
          <input :value="flatPct(store.ledgerTax.flat_rate)" type="number" min="0" max="100"
                 step="0.1" style="width:74px"
                 @input="store.ledgerTax.flat_rate = ($event.target as HTMLInputElement).value === '' ? null : Number(($event.target as HTMLInputElement).value) / 100">
        </label>
        <button class="ghost" @click="setFlat(20)">20%</button>
        <button class="ghost" @click="setFlat(10)">10%</button>
        <button class="ghost" @click="setFlat(0)">0%</button>
      </div>
      <div v-else-if="store.ledgerTax.mode === 'by_year'" class="tax-extra">
        <template v-if="(store.ledgerData?.available_years || []).length">
          <label>批量
            <input v-model.number="bulkYearRate" type="number" min="0" max="100" step="0.1"
                   placeholder="如 10" style="width:70px">
          </label>
          <button class="ghost" @click="applyAllYearRates">应用到所有年份</button>
          <div class="tax-year-grid">
            <label v-for="y in store.ledgerData?.available_years || []" :key="String(y)"
                   class="tax-year-item">{{ y }}
              <input :value="getYearRate(y)" type="number"
                     min="0" max="100" step="0.1" placeholder="自动"
                     @input="setYearRate(y, ($event.target as HTMLInputElement).value)">
            </label>
          </div>
        </template>
        <span v-else class="muted" style="font-size:12px">取到分红历史后可设置年度税率</span>
      </div>
    </div>

    <!-- KPI -->
    <div v-if="store.ledgerLoading" style="margin:8px 0">
      <div class="skeleton" style="margin:8px 0"></div>
      <div class="skeleton" style="margin:8px 0"></div>
    </div>
    <div v-else-if="store.ledgerError" class="error">
      <strong>记账失败：</strong>{{ store.ledgerError }}
    </div>
    <template v-else-if="store.ledgerData">
      <div class="kpis">
        <div class="kpi">
          <div class="label">税前股息</div>
          <div class="value">{{ fmtMoney(store.ledgerData.total_gross) }}</div>
          <div class="sub">{{ hasHk ? 'CNY 折算' : 'CNY' }}</div>
        </div>
        <div class="kpi">
          <div class="label">估算税额</div>
          <div class="value">{{ fmtMoney(store.ledgerData.total_tax) }}</div>
          <div class="sub">{{ hasHk ? 'CNY 折算' : 'CNY' }}</div>
        </div>
        <div class="kpi accent">
          <div class="label">税后净入</div>
          <div class="value">{{ fmtMoney(store.ledgerData.total_net) }}</div>
          <div class="sub">{{ hasHk ? 'CNY 折算' : 'CNY' }}</div>
        </div>
        <div class="kpi">
          <div class="label">实际税率</div>
          <div class="value">{{ fmtPct(effectiveRate) }}</div>
          <div class="sub">税额 ÷ 税前股息</div>
        </div>
      </div>

      <!-- 年度汇总 -->
      <div style="margin-top:16px">
        <div v-if="!(store.ledgerData.by_year || []).length" class="muted" style="font-size:13px">
          所选范围没有分红记录。
        </div>
        <template v-else>
          <div class="card-head" style="margin-bottom:8px">
            <h2 style="font-size:13px">年度汇总（{{ store.ledgerData.total_currency || 'CNY' }}）</h2>
            <span class="hint">默认只展示年度汇总，逐笔明细在下方折叠</span>
          </div>
          <div class="table-scroll">
            <table>
              <thead><tr><th>年份</th><th class="num">税前</th><th class="num">税</th>
                <th class="num">净入</th><th class="num">实际税率</th><th class="num">笔数</th></tr></thead>
              <tbody>
                <tr v-for="y in store.ledgerData.by_year" :key="String(y.year)">
                  <td>{{ y.year }}</td>
                  <td class="num">{{ fmtMoney(y.gross) }}</td>
                  <td class="num">{{ fmtMoney(y.tax) }}</td>
                  <td class="num strong">{{ fmtMoney(y.net) }}</td>
                  <td class="num">{{ fmtPct(y.tax_ratio) }}</td>
                  <td class="num">{{ y.events }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </div>

      <!-- 逐笔明细（折叠） -->
      <details class="ledger-detail">
        <summary>逐笔明细 <span class="muted">{{ totalEvents ? `（${totalEvents} 笔）` : '' }}</span></summary>
        <div style="margin-top:10px">
          <div v-if="!totalEvents" class="muted" style="font-size:13px">没有逐笔记录。</div>
          <div v-else class="scroll-box">
            <table>
              <thead><tr><th>股票</th><th>市场</th><th class="num">除权日</th><th class="num">每股</th>
                <th class="num">税前</th><th class="num">税率</th><th class="num">税</th>
                <th class="num">净入</th><th class="num">持有天数</th><th>计税</th></tr></thead>
              <tbody>
                <tr v-for="r in detailRows" :key="r.key">
                  <td>{{ r.name }} <span class="muted" style="font-size:11.5px">{{ r.code }}</span></td>
                  <td><MarketTag :market="r.market" />
                    <span class="currency-tag">{{ r.currency }}</span></td>
                  <td class="num">{{ r.ex_date }}</td>
                  <td class="num">{{ fmtPriceCcy(r.dps, r.currency) }}</td>
                  <td class="num">{{ fmtMoneyCcy(r.gross, r.currency) }}</td>
                  <td class="num">{{ r.tax_ratio != null ? (r.tax_ratio * 100).toFixed(0) + '%' : DASH }}</td>
                  <td class="num">{{ fmtMoneyCcy(r.tax, r.currency) }}</td>
                  <td class="num strong">{{ fmtMoneyCcy(r.net, r.currency) }}</td>
                  <td class="num">{{ r.holding_days == null ? DASH : r.holding_days }}</td>
                  <td><span class="badge">{{ taxSourceLabel(r.tax_source) }}</span>
                    <span v-if="r.estimated" class="badge warn">估算</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </details>

      <div v-if="noteParts.length" class="ledger-notes">
        <ul class="notes">
          <li v-for="(p, i) in noteParts" :key="i">{{ p }}。</li>
        </ul>
      </div>
    </template>
  </div>
</template>
