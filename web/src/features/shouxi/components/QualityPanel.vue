<script setup lang="ts">
import { computed, ref } from 'vue';
import { useShouxi } from '@/features/shouxi/store';
import type { QualityRow } from '@/api/types';
import {
  DASH, abilityBand, confidenceLabel, fmtMoney, fmtPct, fmtPrice,
  fmtSigned, signClass, PAYOUT_TREND_ARROW,
} from '@/format';
import MarketTag from '@/components/MarketTag.vue';

const store = useShouxi();
const expanded = ref<number | null>(null);

const summary = computed(() => store.quality?.summary || {});
const skippedCount = computed(() => (summary.value.skipped || []).length);

const kpis = computed(() => {
  const s = summary.value;
  return [
    { label: '可评分标的', value: `${s.scored_count || 0} / ${s.eligible_count || 0}`,
      sub: skippedCount.value ? `另 ${skippedCount.value} 只暂不评分` : 'A 股非金融' },
    { label: '平均支付能力', value: s.avg_ability != null ? String(s.avg_ability) : '—',
      sub: s.avg_ability != null ? abilityBand(s.avg_ability).label : '—' },
    { label: '分红意愿',
      value: (['A', 'B', 'C', 'D'] as const).map((g) => `${g}:${s.willingness?.[g] || 0}`).join(' '),
      sub: '连续性 / 趋势 / 资本动作' },
    { label: '覆盖不足', value: String(s.coverage_thin || 0), sub: 'FCF 或 OCF 覆盖 < 1' },
    { label: '高股息陷阱', value: String(s.yield_trap || 0),
      sub: '股息率 ≥ 6% 且支付能力 < 50' },
    { label: '平均分红率(TTM)', value: fmtPct(s.avg_payout_ttm, 1),
      sub: `平均 OCF 覆盖 ${s.avg_ocf_cover != null ? s.avg_ocf_cover.toFixed(2) + 'x' : '—'}` },
  ];
});

function toggleRow(i: number, e: MouseEvent): void {
  if ((e.target as HTMLElement).closest('.btn-analyze')) return;
  expanded.value = expanded.value === i ? null : i;
}

/* 明细里的注释串（与旧版 bandLine 拼接口径一致） */
function bandNotes(b: NonNullable<QualityRow['ability_bands']>[string] | undefined): string {
  if (!b) return '—';
  return [b.band, b.vs_industry, b.mix, b.note, b.cf_np_penalty,
    b.trend_penalty, b.ibd_penalty, b.quick_penalty, b.ocf_min,
    b.np_decline].filter(Boolean).join('；') || '—';
}

const BAND_ITEMS: [string, string, string][] = [
  ['cash', '现金流覆盖', '35%'],
  ['payout', '分红率纪律', '25%'],
  ['debt', '资产负债', '20%'],
  ['stability', '盈利稳定性', '20%'],
];
</script>

<template>
  <div class="card" id="quality-panel">
    <template v-if="store.qualityLoading">
      <div class="card-head">
        <h2>分红质量分析</h2>
        <span class="hint">每票 1 次指标 + 每市场 1 次分红历史；约 10–30 秒，5 分钟缓存</span>
      </div>
      <div v-for="i in 5" :key="i" class="skeleton" style="margin:9px 0"></div>
    </template>

    <div v-else-if="store.qualityError" class="card">
      <div class="error"><strong>分红质量取数失败：</strong>{{ store.qualityError }}</div>
    </div>

    <div v-else-if="store.quality">
      <div class="card-head">
        <h2>分红质量分析</h2>
        <span class="hint">只对 A 股非金融评分；点击行展开分项与近 5 年明细</span>
      </div>
      <div class="kpis">
        <div v-for="(k, i) in kpis" :key="i" class="kpi">
          <div class="label">{{ k.label }}</div>
          <div class="value">{{ k.value }}</div>
          <div class="sub">{{ k.sub }}</div>
        </div>
      </div>

      <div class="table-scroll" style="margin-top:14px">
        <table class="quality-table">
          <thead><tr>
            <th>代码</th><th>名称</th><th class="num">股息率</th>
            <th class="num">分红率(TTM)</th><th class="num">分红率(财年)</th>
            <th class="num">3年均值</th><th class="num">趋势</th><th class="num">连续分红</th>
            <th class="num">OCF覆盖</th><th class="num">FCF覆盖</th><th class="num">资产负债率</th>
            <th>支付能力</th><th>分红意愿</th><th>说明</th>
          </tr></thead>
          <tbody>
            <template v-for="(r, i) in store.quality.rows" :key="r.code">
              <tr class="quality-row" @click="toggleRow(i, $event)">
                <td><MarketTag :market="r.market" /> {{ r.code }}</td>
                <td>{{ r.name }}
                  <span v-if="r.org_form" class="currency-tag">{{ r.org_form }}</span>
                </td>
                <td class="num">{{ fmtPct(r.yield_ttm) }}</td>
                <td class="num">{{ fmtPct(r.payout_ttm, 1) }}</td>
                <td class="num">{{ fmtPct(r.payout_lyr, 1) }}</td>
                <td class="num">{{ fmtPct(r.payout_3y_avg, 1) }}</td>
                <td class="num">{{ r.payout_trend == null ? '—' : (PAYOUT_TREND_ARROW[r.payout_trend] || r.payout_trend) }}</td>
                <td class="num">{{ r.consecutive_years == null ? DASH : r.consecutive_years + ' 年' }}</td>
                <td class="num">{{ r.ocf_cover == null ? (r.eligible ? DASH : 'N/A') : r.ocf_cover.toFixed(2) + 'x' }}</td>
                <td class="num">{{ r.fcf_cover == null ? (r.org_type === 1 ? DASH : 'N/A') : r.fcf_cover.toFixed(2) + 'x' }}</td>
                <td class="num">{{ fmtPct(r.tl_rate, 1) }}</td>
                <td>
                  <span v-if="r.eligible" class="badge" :class="abilityBand(r.ability_score).cls">
                    {{ abilityBand(r.ability_score).label }} {{ r.ability_score }}
                  </span>
                  <span v-else class="badge">暂不评分</span>
                </td>
                <td>
                  <span v-if="r.willingness_grade" class="badge"
                        :class="['A', 'B'].includes(r.willingness_grade) ? 'ok' : 'warn'">
                    {{ r.willingness_grade }}
                  </span>
                  <template v-else>{{ DASH }}</template>
                </td>
                <td style="white-space:nowrap">
                  <template v-if="r.eligible">
                    <span class="muted">{{ confidenceLabel(r.confidence) }}</span>
                    <div v-if="r.flags && r.flags.length" style="margin-top:2px">
                      <span v-for="f in r.flags" :key="f" class="badge warn">{{ f }}</span>
                    </div>
                  </template>
                  <span v-else class="muted">{{ r.reason || '' }}</span>
                  <button class="btn-analyze" title="分红持续性分析"
                          @click="store.openDiagnose(r.code)">
                    <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="M1 8h3l2-5 3 10 2-5h4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>分析
                  </button>
                </td>
              </tr>
              <tr v-if="expanded === i" class="quality-detail">
                <td colspan="14">
                  <div class="quality-detail-body">
                    <div class="quality-cols">
                      <div>
                        <h4>支付能力分项（权重公开可复现）</h4>
                        <ul class="notes">
                          <li v-for="[key, label, weight] in BAND_ITEMS" :key="key">
                            <strong>{{ label }}</strong>（{{ weight }}）：{{ bandNotes(r.ability_bands?.[key]) }}
                          </li>
                        </ul>
                        <h4>覆盖计算</h4>
                        <ul class="notes">
                          <li>归母净利 TTM {{ fmtMoney(r.npts_ttm) }} · 经营现金流 {{ fmtMoney(r.ncfo_ttm) }} ·
                              FCF {{ r.fcf_ttm == null ? 'N/A' : fmtMoney(r.fcf_ttm) }}</li>
                          <li>盈利覆盖 {{ r.earnings_cover == null ? '—' : r.earnings_cover.toFixed(2) + 'x' }} ·
                              现金转化 OCF/NP {{ r.cash_conversion == null ? '—' : r.cash_conversion.toFixed(2) }} ·
                              资本开支占比 {{ r.capex_ratio == null ? '—' : fmtPct(r.capex_ratio, 0) }}</li>
                          <li>ROE {{ fmtPct(r.roe, 1) }} · ROIC {{ fmtPct(r.roic, 1) }} ·
                              净利同比 <span :class="signClass(r.npts_yoy)">{{ fmtSigned(r.npts_yoy) }}</span></li>
                          <li>有息负债率 {{ fmtPct(r.ibd_rate, 1) }} ·
                              速动 {{ r.quick == null ? '—' : r.quick.toFixed(2) }}</li>
                        </ul>
                      </div>
                      <div>
                        <h4>近 5 年经常性每股分红（特别分红另列）</h4>
                        <table>
                          <thead><tr><th>年度</th><th class="num">每股(元)</th>
                            <th class="num">笔数</th><th>口径</th></tr></thead>
                          <tbody>
                            <tr v-if="!(r.recurring_by_year || []).length">
                              <td colspan="4" class="muted">无记录</td></tr>
                            <tr v-for="y in r.recurring_by_year || []" :key="y.year">
                              <td>{{ y.year }}</td>
                              <td class="num">{{ fmtPrice(y.dps) }}</td>
                              <td class="num">{{ y.count }}</td>
                              <td><span v-if="y.special" class="badge warn">含特别</span>
                                <template v-else>·</template></td>
                            </tr>
                          </tbody>
                        </table>
                        <div style="margin-top:6px">
                          特别分红：{{ (r.specials || []).length
                            ? '' : '—' }}<span v-for="sp in r.specials || []" :key="sp.year"
                            class="badge warn" style="margin-right:4px">
                            {{ sp.year }} {{ sp.kind || '特别' }} {{ fmtPrice(sp.dps) }}</span>
                        </div>
                        <h4 style="margin-top:12px">股本结构（仅展示）</h4>
                        <ul class="notes">
                          <li>前十大流通股东合计 {{ fmtPct(r.free_holder_sum, 1) }} ·
                              管理层持股 {{ fmtPct(r.exec_hold, 1) }}</li>
                          <li>近 6 个月回购：{{ r.has_buyback == null ? '—' : (r.has_buyback ? '有' : '无') }}</li>
                          <li class="muted">实控人/机构/北向/质押：SDK 暂无稳定数据，未纳入</li>
                        </ul>
                        <h4 style="margin-top:12px">数据说明</h4>
                        <div>
                          <span v-if="!(r.missing || []).length">无</span>
                          <span v-for="m in r.missing || []" :key="m" class="badge warn"
                                style="margin-right:4px">{{ m }}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
      <ul v-if="store.quality.notes && store.quality.notes.length" class="notes" style="margin-top:12px">
        <li v-for="n in store.quality.notes" :key="n">{{ n }}</li>
      </ul>
    </div>

    <div v-else class="empty">先添加持仓再分析</div>
  </div>
</template>
