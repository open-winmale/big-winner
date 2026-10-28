<script setup lang="ts">
import { computed } from 'vue';
import { useShouxi } from '@/features/shouxi/store';
import type { QualityRow } from '@/api/types';
import {
  DASH, ORG_TYPE_LABEL, abilityBand, confidenceLabel, fmtPct, fmtPrice,
  fmtPriceCcy,
} from '@/format';
import Modal from '@/components/ui/Modal.vue';
import MarketTag from '@/components/MarketTag.vue';
import EventRow from './EventRow.vue';

const store = useShouxi();
const emit = defineEmits<{ close: [] }>();

const open = computed({
  get: () => store.diagnoseOpen,
  set: (v: boolean) => { store.diagnoseOpen = v; },
});

const r = computed<QualityRow>(() => store.diagnose?.quality ?? ({ code: '', eligible: false } as QualityRow));
const profile = computed(() => store.diagnose?.profile || {});
const quote = computed(() => store.diagnose?.quote || {});
const band = computed(() => abilityBand(r.value.ability_score));

const orgForm = computed(() => profile.value.org_form
  || (store.diagnose?.market === 'hk' ? '—（港股暂无该标签）' : '—'));

/* ---- 支付能力分项条（按得分率填充） ---- */
const ABILITY_ITEMS: { key: string; label: string; weight: number }[] = [
  { key: 'cash', label: '现金流覆盖', weight: 35 },
  { key: 'payout', label: '分红率纪律', weight: 25 },
  { key: 'debt', label: '资产负债', weight: 20 },
  { key: 'stability', label: '盈利稳定性', weight: 20 },
];

function bandNotes(b: NonNullable<QualityRow['ability_bands']>[string] | undefined): string {
  if (!b) return '—';
  return [b.band, b.vs_industry, b.mix, b.note, b.cf_np_penalty,
    b.trend_penalty, b.ibd_penalty, b.quick_penalty, b.ocf_min,
    b.np_decline].filter(Boolean).join('；') || '—';
}

function barInfo(key: string): { has: boolean; pct: number; cls: string; score: string } {
  const b = r.value.ability_bands?.[key];
  const has = b?.score != null && !!b?.weight;
  if (!has) return { has: false, pct: 0, cls: '', score: '缺数据' };
  const pct = Math.max(0, Math.min(100, (b!.score! / b!.weight!) * 100));
  return {
    has: true, pct,
    cls: pct >= 70 ? 'good' : (pct >= 40 ? 'ok' : 'bad'),
    score: `${b!.score} / ${b!.weight}`,
  };
}

/* ---- 覆盖条（1.0x 基线，上限 2.5x） ---- */
const COV_MAX = 2.5;

function covInfo(v: number | null | undefined): { pct: number; cls: string } | null {
  if (v == null) return null;
  return {
    pct: (Math.min(v, COV_MAX) / COV_MAX) * 100,
    cls: v >= 1.5 ? 'good' : (v >= 1.0 ? 'ok' : 'bad'),
  };
}

/* ---- 近 5 年分红双柱（蓝=分红率，绿=每股分红） ---- */
const payoutCols = computed(() => {
  const row = r.value;
  const series = row.payout_series || [];
  const recurring = row.recurring_by_year || [];
  const dpsByYear: Record<number, number | null | undefined> = {};
  recurring.forEach((it) => { dpsByYear[it.year] = it.dps; });
  const years: number[] = [];
  const seen = new Set<number>();
  series.forEach((p) => { if (!seen.has(p.year)) { seen.add(p.year); years.push(p.year); } });
  recurring.forEach((it) => { if (!seen.has(it.year)) { seen.add(it.year); years.push(it.year); } });
  years.sort((a, b) => a - b);
  const shown = years.slice(-6);
  if (!shown.length) return [];
  const maxPayout = Math.max(0.001, ...series.map((p) => p.payout || 0));
  const maxDps = Math.max(0.001, ...shown.map((y) => dpsByYear[y] || 0));
  return shown.map((y) => {
    const payout = (series.find((p) => p.year === y) || {}).payout;
    const dps = dpsByYear[y];
    return {
      year: y,
      payout,
      dps,
      ph: payout != null ? Math.max(4, (payout / maxPayout) * 100) : 0,
      dh: dps != null ? Math.max(4, (dps / maxDps) * 100) : 0,
    };
  });
});
</script>

<template>
  <Modal v-model:open="open" title="分红持续性分析" width="860px"
         :hint="store.diagnoseCode + (store.diagnoseLoading ? ' · 取数中…' : '')"
         @close="emit('close')">
    <template v-if="store.diagnoseLoading">
      <div v-for="i in 5" :key="i" class="skeleton" style="margin:9px 0"></div>
    </template>

    <div v-else-if="store.diagnoseError" class="error">
      <strong>分析失败：</strong>{{ store.diagnoseError }}
    </div>

    <template v-else-if="store.diagnose">
      <!-- 头部 4 KPI -->
      <div class="kpis">
        <div class="kpi">
          <div class="label">股票</div>
          <div class="value" style="font-size:16px">
            {{ profile.name || store.diagnose.code }} <MarketTag :market="store.diagnose.market" />
          </div>
          <div class="sub">{{ store.diagnose.code }} · 现价 {{ fmtPriceCcy(quote.price, quote.currency) }}</div>
        </div>
        <div class="kpi">
          <div class="label">企业类型</div>
          <div class="value" style="font-size:16px">{{ orgForm }}</div>
          <div class="sub">
            {{ profile.industry ? profile.industry + ' · ' : '' }}{{ ORG_TYPE_LABEL[profile.org_type ?? 0] || '' }}
          </div>
        </div>
        <div class="kpi">
          <div class="label">股息率 / 分红率(TTM)</div>
          <div class="value" style="font-size:16px">
            {{ fmtPct(quote.yield_ttm) }} / {{ fmtPct(quote.payout_ttm, 1) }}
            <span v-if="store.diagnose.market === 'hk' && quote.payout_ttm != null"
                  class="currency-tag">待核验</span>
          </div>
          <div class="sub">上市 {{ profile.listing_date || '—' }}</div>
        </div>
        <div class="kpi">
          <div class="label">支付能力 / 分红意愿</div>
          <div class="value" style="font-size:16px">
            <template v-if="r.eligible && r.ability_score != null">
              {{ r.ability_score }} <span class="badge" :class="band.cls">{{ band.label }}</span>
            </template>
            <template v-else>{{ DASH }}</template>
            <span v-if="r.willingness_grade" class="badge"
                  :class="['A', 'B'].includes(r.willingness_grade) ? 'ok' : 'warn'">
              {{ r.willingness_grade }}
            </span>
          </div>
          <div class="sub">连续分红 {{ r.consecutive_years == null ? DASH : r.consecutive_years + ' 年' }}</div>
        </div>
      </div>

      <div v-if="r.flags && r.flags.length" style="margin:10px 0">
        <span v-for="f in r.flags" :key="f" class="badge warn" style="margin-right:6px">{{ f }}</span>
      </div>

      <!-- 分析主体 -->
      <template v-if="r.eligible">
        <h4 class="diag-sec">支付能力分项</h4>
        <div class="diag-bars">
          <div v-for="it in ABILITY_ITEMS" :key="it.key" class="diag-bar-row">
            <div class="diag-bar-label">{{ it.label }} <span class="muted">{{ it.weight }}%</span></div>
            <div class="diag-bar-track">
              <span v-if="barInfo(it.key).has" class="diag-bar-fill"
                    :class="barInfo(it.key).cls" :style="`width:${barInfo(it.key).pct}%`"></span>
            </div>
            <div class="diag-bar-score">{{ barInfo(it.key).score }}</div>
            <div class="diag-bar-note">{{ bandNotes(r.ability_bands?.[it.key]) }}</div>
          </div>
        </div>

        <h4 class="diag-sec">股息覆盖（1.0x = 分红刚好被现金流覆盖）</h4>
        <div class="diag-cov">
          <div v-for="it in [{ label: 'OCF 覆盖', value: r.ocf_cover, hint: '经营现金流 ÷ 分红' },
                             { label: 'FCF 覆盖', value: r.fcf_cover, hint: '自由现金流 ÷ 分红' }]"
               :key="it.label" class="diag-cov-row">
            <div class="diag-bar-label">{{ it.label }}</div>
            <template v-if="it.value == null">
              <div class="muted" style="font-size:12px">
                N/A{{ r.org_type !== 1 ? '（金融股不适用）' : '' }}
              </div>
            </template>
            <template v-else>
              <div class="diag-cov-track">
                <span class="diag-cov-fill" :class="covInfo(it.value)!.cls"
                      :style="`width:${covInfo(it.value)!.pct}%`"></span>
                <span class="diag-cov-mark" style="left:40%"></span>
              </div>
              <div class="diag-cov-val" :class="{ 'bad-text': it.value < 1 }">
                {{ it.value.toFixed(2) }}x
              </div>
            </template>
            <div class="muted" style="font-size:11px">{{ it.hint }}</div>
          </div>
        </div>

        <template v-if="payoutCols.length">
          <h4 class="diag-sec">近 5 年分红（蓝=分红率，绿=每股分红元）</h4>
          <div class="diag-chart">
            <div v-for="c in payoutCols" :key="c.year" class="diag-col">
              <div class="diag-col-bars">
                <div class="diag-col-bar payout" :style="`height:${c.ph}%`">
                  <span class="diag-col-val">{{ c.payout != null ? Math.round(c.payout * 100) + '%' : '' }}</span>
                </div>
                <div class="diag-col-bar dps" :style="`height:${c.dh}%`">
                  <span class="diag-col-val">{{ c.dps != null ? c.dps.toFixed(2) : '' }}</span>
                </div>
              </div>
              <div class="diag-col-year">{{ c.year }}</div>
            </div>
          </div>
          <div v-if="(r.specials || []).length" class="muted" style="font-size:11.5px;margin-top:6px">
            特别分红（不计入经常性口径）：{{ (r.specials || []).map((sp) =>
              `${sp.year} ${sp.kind || '特别'} ${fmtPrice(sp.dps)}`).join('、') }}
          </div>
        </template>

        <div class="muted" style="font-size:11.5px;margin-top:10px">
          资产负债率 {{ fmtPct(r.tl_rate, 1) }}<template v-if="r.tl_ind_avg">（行业均值 {{ fmtPct(r.tl_ind_avg, 1) }}）</template> ·
          ROE {{ fmtPct(r.roe, 1) }} ·
          现金转化 {{ r.cash_conversion == null ? DASH : r.cash_conversion.toFixed(2) }} ·
          置信度 {{ confidenceLabel(r.confidence) }}
        </div>
      </template>

      <div v-else class="muted" style="margin-top:10px;font-size:12.5px">
        暂不评分：{{ r.reason || '' }}
        <template v-if="r.payout_ttm != null">· 分红率(TTM) {{ fmtPct(r.payout_ttm, 1) }}</template>
        <template v-if="r.tl_rate != null">· 资产负债率 {{ fmtPct(r.tl_rate, 1) }}</template>
        <template v-if="r.roe != null">· ROE {{ fmtPct(r.roe, 1) }}</template>
      </div>

      <!-- 下一次分红 -->
      <template v-if="store.diagnose.next_event">
        <h4 class="diag-sec">下一次分红（观察口径）</h4>
        <div class="event-list">
          <EventRow :event="store.diagnose.next_event" no-action />
        </div>
      </template>

      <ul v-if="store.diagnose.notes && store.diagnose.notes.length" class="notes" style="margin-top:12px">
        <li v-for="n in store.diagnose.notes" :key="n">{{ n }}</li>
      </ul>
    </template>
  </Modal>
</template>
