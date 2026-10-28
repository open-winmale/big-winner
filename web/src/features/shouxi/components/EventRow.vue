<script setup lang="ts">
import { computed } from 'vue';
import type { CalendarEvent } from '@/api/types';
import { fmtInt, fmtMoneyCcy, fmtPct, fmtPriceCcy } from '@/format';
import MarketTag from '@/components/MarketTag.vue';

const props = withDefaults(defineProps<{
  event: CalendarEvent;
  noAction?: boolean;
}>(), { noAction: false });

const emit = defineEmits<{ analyze: [code: string] }>();

const stageCls = computed(() => {
  const s = props.event.stage;
  return s === '已到账' ? 'paid' : (s === '待除权' || s === '预案待定' ? 'pending' : '');
});

const dateLabel = computed(() => {
  const e = props.event;
  if (!e.ex_date && !e.pay_date) return { date: '待定', meta: '' };
  if (e.stage === '已到账' || e.stage === '已除权待到账') {
    return { date: (e.pay_date || e.ex_date || '').slice(5), meta: '到账' };
  }
  return { date: (e.ex_date || e.pay_date || '').slice(5), meta: '除权' };
});

const meta = computed(() => {
  const e = props.event;
  return [e.code, e.status, e.kind, e.content].filter(Boolean).join(' · ');
});

const timeline = computed(() => {
  const e = props.event;
  return `登记 ${e.record_date || '—'} · 除权 ${e.ex_date || '—'} · 到账 ${e.pay_date || '—'}`;
});

const amount = computed(() => {
  const e = props.event;
  if (e.shares > 0) {
    // 只展示事实金额：股数 × 每股股息（税前）；税后测算在「记账」里
    return {
      strong: fmtMoneyCcy(e.gross, e.currency),
      meta: `${fmtInt(e.shares)} 股 × ${fmtPriceCcy(e.dps, e.currency)}`,
    };
  }
  const extra = e.yield_ttm != null
    ? `${fmtPct(e.yield_ttm)} 股息率`
    : `${fmtPriceCcy(e.dps, e.currency)}/股`;
  return { strong: fmtPriceCcy(e.dps, e.currency), meta: extra };
});
</script>

<template>
  <div class="event-row">
    <div>
      <div class="date">{{ dateLabel.date }}</div>
      <div v-if="dateLabel.meta" class="meta">{{ dateLabel.meta }}</div>
      <div v-else class="meta">待定</div>
    </div>
    <div>
      <div class="name">
        {{ event.name }} <MarketTag :market="event.market" />
      </div>
      <div class="meta">{{ meta }}</div>
    </div>
    <div>
      <div><span class="stage" :class="stageCls">{{ event.stage }}</span></div>
      <div class="meta">{{ timeline }}</div>
    </div>
    <div class="amount">
      <div class="strong">{{ amount.strong }}</div>
      <div class="meta">{{ amount.meta }}</div>
    </div>
    <div v-if="!noAction" class="actions">
      <button class="btn-analyze" title="分红持续性分析" @click="emit('analyze', event.code)">
        <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="M1 8h3l2-5 3 10 2-5h4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>分析
      </button>
    </div>
  </div>
</template>
