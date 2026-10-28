<script setup lang="ts">
import { computed } from 'vue';
import { api } from '@/api/client';
import { useShouxi } from '@/features/shouxi/store';
import type { XrayResult } from '@/api/types';
import {
  DASH, fmtInt, fmtMoney, fmtMoneyCcy, fmtPct, fmtPrice, fmtPriceCcy,
  fmtSigned, fmtSignedMoney, signClass,
} from '@/format';
import MarketTag from '@/components/MarketTag.vue';

const props = defineProps<{ data: XrayResult }>();
const store = useShouxi();

const kpis = computed(() => {
  const d = props.data;
  const list: { label: string; value: string; sub: string; accent: boolean; signed?: boolean }[] = [
    { label: '组合总市值', value: fmtMoney(d.total_market_value),
      sub: d.fx_note ? 'CNY 折算 · 含港股' : 'CNY', accent: false },
    { label: '组合年股息', value: fmtMoney(d.total_dividend), sub: 'CNY', accent: true },
    { label: '组合股息率 · 市值加权', value: fmtPct(d.portfolio_yield), sub: '', accent: true },
    { label: '成本股息率', value: fmtPct(d.portfolio_cost_yield),
      sub: '总年息 ÷ 总成本 · 只汇总有成本的标的', accent: d.portfolio_cost_yield != null },
    { label: '组合总利润', value: fmtMoney(d.total_profit), sub: 'CNY · 财报币种折算', accent: false },
    { label: '浮动盈亏', value: fmtSignedMoney(d.portfolio_pnl),
      sub: 'CNY · 只汇总有成本的标的', accent: false, signed: true },
  ];
  return list;
});

const stability = computed(() => props.data.stability || {});
const payoutBuckets = computed(() =>
  Object.entries(stability.value.payout_buckets || {}));
const stabilityParts = computed(() => {
  const s = stability.value;
  const parts: { n: string; k: string }[] = [{
    n: s.cr3 != null ? (s.cr3 * 100).toFixed(0) + '%' : '—',
    k: '股息集中度 CR3' + (s.cr3_codes && s.cr3_codes.length ? '\n' + s.cr3_codes.join('、') : ''),
  }];
  if (s.stable_years_cover != null) {
    parts.push({
      n: (s.stable_years_cover * 100).toFixed(0) + '%',
      k: '连续分红≥5年\n市值占比',
    });
  }
  parts.push({ n: props.data.completeness || '—', k: '数据完整度' });
  return parts;
});
</script>

<template>
  <div>
    <!-- KPI -->
    <div style="margin:18px 0" class="kpis">
      <div v-for="(k, i) in kpis" :key="i" class="kpi" :class="{ accent: k.accent }">
        <div class="label">{{ k.label }}</div>
        <div class="value">
          <span v-if="k.signed" :class="signClass(data.portfolio_pnl)">{{ k.value }}</span>
          <template v-else>{{ k.value }}</template>
        </div>
        <div v-if="k.sub" class="sub">{{ k.sub }}</div>
      </div>
    </div>

    <!-- 透视表 -->
    <div class="card">
      <div class="card-head">
        <h2>持仓透视</h2>
        <span class="hint">生成于 {{ data.generated_at }}</span>
      </div>
      <div class="table-scroll">
        <table class="xray-table">
          <thead><tr>
            <th></th><th>代码</th><th>名称</th><th class="num">持股</th><th class="num">现价</th>
            <th class="num">市值(原币)</th><th class="num">占比</th><th class="num">每股利润</th>
            <th class="num">每股股息</th><th class="num">股息率</th><th class="num">成本股息率</th>
            <th class="num" title="现金分红 ÷ 归母净利润">分红率(TTM)</th>
            <th class="num">持仓年息(原币)</th><th class="num">浮动</th><th>数据说明</th>
          </tr></thead>
          <tbody>
            <tr v-for="r in data.rows" :key="r.code">
              <td class="cell-action">
                <button class="btn-analyze" title="分红持续性分析" @click="store.openDiagnose(r.code)">
                  <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="M1 8h3l2-5 3 10 2-5h4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>分析
                </button>
              </td>
              <td><MarketTag :market="r.market" /> {{ r.code }}</td>
              <td>
                {{ r.name || DASH }}
                <span v-if="r.market === 'hk'" class="currency-tag">HKD</span>
                <span v-if="r.price_estimated" class="badge warn">估价</span>
              </td>
              <td class="num">{{ fmtInt(r.shares) }}</td>
              <td class="num">{{ fmtPriceCcy(r.price, r.currency) }}</td>
              <td class="num">{{ fmtMoneyCcy(r.market_value, r.currency) }}</td>
              <td class="num">{{ fmtPct(r.weight, 1) }}</td>
              <td class="num">
                {{ fmtPrice(r.eps_ttm) }}
                <span v-if="r.market === 'hk' && r.eps_ttm != null" class="currency-tag">CNY</span>
              </td>
              <td class="num">{{ fmtPriceCcy(r.dps_ttm, r.currency) }}</td>
              <td class="num strong">{{ fmtPct(r.div_yield) }}</td>
              <td class="num strong">{{ fmtPct(r.cost_yield) }}</td>
              <td class="num">
                {{ fmtPct(r.payout, 1) }}
                <span v-if="r.market === 'hk' && r.payout != null" class="currency-tag">待核验</span>
              </td>
              <td class="num">{{ fmtMoneyCcy(r.annual_dividend, r.currency) }}</td>
              <td class="num"><span :class="signClass(r.pnl_ratio)">{{ fmtSigned(r.pnl_ratio) }}</span></td>
              <td>
                <template v-if="r.missing && r.missing.length">
                  <span v-for="m in r.missing" :key="m" class="badge warn">{{ m }}</span>
                </template>
                <span v-else class="muted">·</span>
              </td>
            </tr>
          </tbody>
          <tfoot><tr>
            <td></td><td colspan="4">合计（{{ data.total_currency || 'CNY' }}）</td>
            <td class="num">{{ fmtMoney(data.total_market_value) }}</td>
            <td class="num">100%</td>
            <td class="num">{{ DASH }}</td>
            <td class="num">{{ DASH }}</td>
            <td class="num">{{ fmtPct(data.portfolio_yield) }}</td>
            <td class="num">{{ fmtPct(data.portfolio_cost_yield) }}</td>
            <td class="num">{{ DASH }}</td>
            <td class="num">{{ fmtMoney(data.total_dividend) }}</td>
            <td class="num"><span :class="signClass(data.portfolio_pnl_ratio)">{{ fmtSigned(data.portfolio_pnl_ratio) }}</span></td>
            <td></td>
          </tr></tfoot>
        </table>
      </div>
      <div v-if="data.fx_note" class="muted" style="font-size:12px;margin-top:8px">{{ data.fx_note }}</div>
    </div>

    <!-- 接下来 -->
    <div class="toolbar" style="margin:14px 0">
      <span class="muted" style="font-size:13px">接下来：</span>
      <button class="ghost" @click="store.openLedger()">💰 算算这些年分到多少钱</button>
      <button class="ghost" @click="store.openQuality()">🛡 分红质量：现金流覆盖 / 分红率 / 连续性</button>
      <button class="ghost" @click="api.exportXrayCsv(store.positions)">⬇ 导出 Excel 表格</button>
    </div>

    <!-- 派息稳定性看板 -->
    <div class="card">
      <div class="card-head">
        <h2>派息稳定性看板</h2>
        <span class="hint">描述性统计，不构成任何操作建议</span>
      </div>
      <div class="buckets">
        <div v-for="(p, i) in stabilityParts" :key="i" class="bucket">
          <div class="n">{{ p.n }}</div>
          <div class="k" style="white-space:pre-line">{{ p.k }}</div>
        </div>
      </div>
      <template v-if="payoutBuckets.length">
        <div class="card-head" style="margin:18px 0 10px">
          <h2 style="font-size:13px">分红率分档（现金分红 ÷ 归母净利润）</h2>
        </div>
        <div class="buckets">
          <div v-for="[k, n] in payoutBuckets" :key="k" class="bucket">
            <div class="n">{{ n }}</div>
            <div class="k">{{ k }}</div>
          </div>
        </div>
      </template>
      <ul v-if="stability.warnings && stability.warnings.length" class="notes" style="margin-top:16px">
        <li v-for="w in stability.warnings" :key="w">{{ w }}</li>
      </ul>
      <ul v-if="data.notes && data.notes.length" class="notes"
          style="margin-top:12px;color:var(--text-3)">
        <li v-for="w in data.notes" :key="w">{{ w }}</li>
      </ul>
    </div>
  </div>
</template>
