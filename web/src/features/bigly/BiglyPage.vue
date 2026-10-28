<script setup lang="ts">
/* 波段：估值通道 · 买卖点参考 · 拨测回看。
   交互同旧版 bigly.html：指标/窗口切换即重载整链；银行默认 PB（手动选过指标则不再自动改）；
   推荐区间自动回拨；自定义区间/止损手动回拨。 */
import { computed, onMounted, ref } from 'vue';
import { api, errText, isAuthErrorText } from '@/api/client';
import type { BiglyBacktestResult, BiglyChannelResult } from '@/api/types';
import {
  fmtPctSigned, pctText, pctileText, ZONE_TEXT,
} from '@/format';
import SymbolSearch from '@/components/SymbolSearch.vue';
import ChannelChart from './components/ChannelChart.vue';
import { useApp } from '@/store/useApp';

const app = useApp();

/* 控制条已移除；标的经 ① 卡内搜索切换，指标随选票名称自动 PE/PB，窗口固定半年 */
const sym = ref('600519');
const symName = ref<string | null>(null);
const metric = ref<'pe' | 'pb'>('pe');
const manualMetric = ref(false);  // 手动选过指标 → 换票不自动改
const winRange = ref<'6m' | '1y' | '2y'>('6m');
const winLabel = computed(() =>
  ({ '6m': '半年', '1y': '1年', '2y': '2年' })[winRange.value] ?? winRange.value);

const source = ref<'suggest' | 'user'>('suggest');
const userLow = ref<number | null>(null);
const userHigh = ref<number | null>(null);
const stop = ref<number | null>(null);

const loadNote = ref('');
const btNote = ref('');
const channelData = ref<BiglyChannelResult | null>(null);
const btData = ref<BiglyBacktestResult | null>(null);

const demo = ref(false);

/* 联想没带来名称时按代码查目录补齐（目录不可用则拿不到，不猜测） */
async function resolveSymName(): Promise<void> {
  if (symName.value || !sym.value) return;
  const code = sym.value;
  const mkt = /^hk\./i.test(code) || (/^\d{1,5}$/.test(code) && code.length !== 6) ? 'hk' : 'cn';
  try {
    const d = await api.biglySymbols(code, mkt);
    const hit = (d.results || []).find(
      (r) => (r.code || '').replace(/\D/g, '') === code.replace(/\D/g, ''));
    if (hit) symName.value = hit.name || null;
  } catch { /* 保持无名，不阻塞加载 */ }
}

async function load(): Promise<void> {
  loadNote.value = '加载中…';
  btData.value = null;
  await resolveSymName();
  // 按名称切默认估值：银行 → PB；手动选过指标则尊重手动（换新票重置为自动）
  if (!manualMetric.value) {
    if (symName.value && symName.value.includes('银行')) metric.value = 'pb';
    else if (symName.value) metric.value = 'pe';
  }
  try {
    channelData.value = await api.biglyChannel({
      symbol: sym.value, metric: metric.value, window: winRange.value,
    });
  } catch (e) {
    loadNote.value = errText(e);
    return;
  }
  if (channelData.value.error) {
    loadNote.value = channelData.value.error;
    return;
  }
  demo.value = !!channelData.value.demo;
  loadNote.value = `已加载 ${channelData.value.symbol}${symName.value ? ' · ' + symName.value : ''}`
    + (demo.value ? '（演示数据）' : '');
  void autoBacktest();
}

/* 自动模式：后端先搜索推荐区间，再按推荐值回拨（无推荐时回退通道轨） */
async function autoBacktest(): Promise<void> {
  btNote.value = '搜索推荐区间并回拨…';
  try {
    btData.value = await api.biglyBacktest({
      symbol: sym.value, metric: metric.value, window: winRange.value,
    });
  } catch (e) {
    btNote.value = errText(e);
    return;
  }
  if (btData.value.error) { btNote.value = btData.value.error; return; }
  btNote.value = '';
}

/* ---- 搜索联想 ---- */
function onPick(item: { code: string; name: string }): void {
  sym.value = item.code;
  symName.value = item.name || null;
  void load();
}

function onRaw(code: string): void {
  sym.value = code;
  symName.value = null;
  void load();
}

/* ---- 买卖点（来源切换 + 自定义倍数换算） ---- */
const levels = computed(() => channelData.value?.levels);

const buyPrice = computed<number | null>(() => {
  const L = levels.value;
  if (!L?.buy_price) return null;
  if (source.value === 'user' && userLow.value) {
    return L.buy_price / L.low_multiple * userLow.value;
  }
  return L.buy_price ?? null;
});

const sellPrice = computed<number | null>(() => {
  const L = levels.value;
  if (!L?.sell_price) return null;
  if (source.value === 'user' && userHigh.value) {
    return L.sell_price / L.high_multiple * userHigh.value;
  }
  return L.sell_price ?? null;
});

const nearLowText = computed(() => {
  const c = btData.value?.suggest?.criteria;
  if (!c) return '';
  return (c.near_low_pct >= 0 ? '+' : '−') + Math.abs(c.near_low_pct * 100).toFixed(1) + '%';
});

/* 距现价（表格列） */
const distText = (price: number | null) =>
  price && channelData.value?.last_close
    ? fmtPctSigned(price / channelData.value.last_close - 1) : '—';
const buyBarText = computed(() => distText(buyPrice.value));
const sellBarText = computed(() => distText(sellPrice.value));

/* ---- 手动回拨 ---- */
async function runBacktest(): Promise<void> {
  if (!channelData.value) { btNote.value = '请先加载通道'; return; }
  const buy = buyPrice.value;
  const sell = sellPrice.value;
  if (!buy || !sell) { btNote.value = '买卖价位无效'; return; }
  btNote.value = '回拨中…';
  const payload: Parameters<typeof api.biglyBacktest>[0] = {
    symbol: sym.value, metric: metric.value, window: winRange.value,
    buy, sell,
  };
  if (stop.value && stop.value > 0) payload.stop = stop.value;
  try {
    btData.value = await api.biglyBacktest(payload);
  } catch (e) {
    btNote.value = errText(e);
    return;
  }
  if (btData.value.error) { btNote.value = btData.value.error; return; }
  btNote.value = '';
}

/* ---- 分布 / 回测展示 ---- */
const fmtDate = (d?: string | null) => d ? String(d).slice(5) : '—';

const zoneRow = (label: string, d?: { days: number; ratio?: number | null } | null) =>
  ({ label, text: d && d.ratio != null ? `${d.days} 天 · ${(d.ratio * 100).toFixed(0)}%` : '—' });

const extremes = computed(() => channelData.value?.extremes || {});

onMounted(() => { void load(); });
</script>

<template>
  <main class="wrap">
    <div class="page-head">
      <h1>分析历史数据计算低估区间，<span class="warn">避免追高导致收益少、回撤深、体验差</span></h1>
      <div class="page-sub-row">
        <p>三步看懂波段：① 看估值通道，判断现在贵不贵 → ② 设买卖区间 → ③ 用历史数据回放验证。</p>
        <span style="display:inline-flex;align-items:center;gap:10px">
          <span>指标
            <span class="seg">
              <button :class="{ active: metric === 'pe' }" @click="metric = 'pe'; manualMetric = true; load()">PE</button>
              <button :class="{ active: metric === 'pb' }" @click="metric = 'pb'; manualMetric = true; load()">PB</button>
            </span>
          </span>
          <span>窗口
            <span class="seg">
              <button :class="{ active: winRange === '6m' }" @click="winRange = '6m'; load()">半年</button>
              <button :class="{ active: winRange === '1y' }" @click="winRange = '1y'; load()">1 年</button>
              <button :class="{ active: winRange === '2y' }" @click="winRange = '2y'; load()">2 年</button>
            </span>
          </span>
          <SymbolSearch endpoint="bigly" initial-text="600519" keep-picked
                        placeholder="代码 / 名称 / 拼音"
                        @pick="onPick" @raw="onRaw" />
        </span>
      </div>
    </div>

    <!-- ① 通道主图 -->
    <section class="card">
      <div class="step-head">
        <span class="step-badge">1</span>
        <div>
          <h2>看估值通道</h2>
          <p class="step-sub">{{ sym }}{{ symName ? ' · ' + symName : '' }} ·
            {{ metric.toUpperCase() }} · {{ winLabel }}窗口 · 当前估值相对历史位置；
            色带 = ±1σ / ±2σ 区间，红绿虚线 = ±2σ 轨，琥珀虚线 = 均值，靛蓝虚线 = 中位；底部滑杆可缩放回看</p>
        </div>
      </div>
      <p v-if="loadNote" class="meta">{{ loadNote }}
        <button v-if="isAuthErrorText(loadNote)" class="link"
                @click="app.openKeyDialog()">🔑 配置 Key</button>
      </p>
      <ChannelChart v-if="channelData" :series="channelData.series"
                    :channel="channelData.channel" :metric="channelData.metric" />
    </section>

    <!-- ② 状态条 -->
    <div v-if="channelData" class="kpis">
      <div class="kpi"><div class="label">当前倍数</div>
        <div class="value">{{ channelData.channel.current.toFixed(2) }}</div></div>
      <div class="kpi"><div class="label">窗口内分位</div>
        <div class="value">{{ pctileText(channelData.channel.pct) }}</div></div>
      <div class="kpi"><div class="label">z 值 / 分区</div>
        <div class="value">{{ channelData.channel.z >= 0 ? '+' : '' }}{{ channelData.channel.z.toFixed(2) }} ·
          {{ ZONE_TEXT[channelData.channel.zone] }}</div></div>
      <div class="kpi"><div class="label">±2σ 覆盖率</div>
        <div class="value">{{ pctText(channelData.channel.coverage) }}</div></div>
      <div class="kpi"><div class="label">min / 中位 / max</div>
        <div class="value" style="font-size:15px">
          {{ channelData.channel.min.toFixed(2) }} / {{ channelData.channel.median?.toFixed(2) ?? '—' }} /
          {{ channelData.channel.max.toFixed(2) }}
        </div></div>
    </div>

    <!-- ④ 买卖点卡（表格化） -->
    <section v-if="channelData" class="card">
      <div class="step-head">
        <span class="step-badge">2</span>
        <div>
          <h2>设置买卖点</h2>
          <p class="step-sub">默认推荐区间（不高估、距最低点不太远、亏损时间不过长、成交次数不过少）；
             也可切换自定义区间，自填低买 / 高卖倍数</p>
        </div>
      </div>
      <div style="margin-bottom:10px">
        <span class="seg">
          <button :class="{ active: source === 'suggest' }" @click="source = 'suggest'">推荐区间</button>
          <button :class="{ active: source === 'user' }" @click="source = 'user'">自定义区间</button>
        </span>
      </div>
      <div v-if="source === 'user'" style="margin-bottom:10px">
        <label>低买倍数 <input v-model.number="userLow" type="number" step="0.1" style="width:80px"></label>
        <label style="margin-left:12px">高卖倍数 <input v-model.number="userHigh" type="number" step="0.1" style="width:80px"></label>
      </div>
      <div v-if="levels">
        <table class="lv">
          <thead>
            <tr><th>方向</th><th class="num">估值指标</th><th class="num">对应股价（元）</th><th class="num">距现价</th></tr>
          </thead>
          <tbody>
            <tr>
              <td>买入</td>
              <td class="num">{{ metric.toUpperCase() }} {{ btData?.suggest && source === 'suggest'
                ? btData.suggest.buy_multiple.toFixed(2) : levels.low_multiple.toFixed(2) }}</td>
              <td class="num buy-price">{{ buyPrice ? buyPrice.toFixed(2) : '—' }}</td>
              <td class="num">{{ buyBarText }}</td>
            </tr>
            <tr>
              <td>卖出</td>
              <td class="num">{{ metric.toUpperCase() }} {{ btData?.suggest && source === 'suggest'
                ? btData.suggest.sell_multiple.toFixed(2) : levels.high_multiple.toFixed(2) }}</td>
              <td class="num sell-price">{{ sellPrice ? sellPrice.toFixed(2) : '—' }}</td>
              <td class="num">{{ sellBarText }}</td>
            </tr>
          </tbody>
        </table>
        <template v-if="source === 'suggest' && btData?.suggest">
          <div class="chips" :class="{ relax: !btData.suggest.criteria.strict_ok }">
            ✓ 不高估（{{ metric.toUpperCase() }} 买点 {{ btData.suggest.buy_multiple.toFixed(2) }}
            ≤ 均值 {{ channelData.channel.avg.toFixed(2) }}）
            · 距窗口最低收盘 {{ nearLowText }}{{ btData.suggest.criteria.near_low_pct > 0.15 ? '（放宽）' : '' }}
            · 亏损持仓占比 {{ (btData.suggest.criteria.underwater_ratio * 100).toFixed(0) }}%{{ btData.suggest.criteria.underwater_ratio > 0.35 ? '（放宽）' : '' }}
            · 完整进出 {{ btData.suggest.criteria.roundtrips_done }} 次{{ btData.suggest.criteria.roundtrips_done < 2 ? '（放宽）' : '' }}
          </div>
          <p class="meta">该区间本窗口回放：收益
            <b>{{ fmtPctSigned(btData.suggest.stats?.return_pct) }}</b> ·
            回撤 {{ pctText(btData.suggest.stats?.mdd) }} ·
            持仓 {{ btData.suggest.stats?.days_held != null ? btData.suggest.stats.days_held + ' 天' : '—' }}</p>
        </template>
      </div>
      <div style="margin-top:12px;border-top:1px dashed var(--line);padding-top:10px">
        <label>止损价（可选）<input v-model.number="stop" type="number" step="0.01" style="width:90px"></label>
        <button class="primary" style="margin-left:12px" @click="runBacktest">开始回拨</button>
        <span class="meta">{{ btNote }}</span>
      </div>
    </section>

    <!-- ⑤ 区间分布与极值 -->
    <section v-if="channelData" class="card">
      <div class="step-head">
        <span class="step-badge">📊</span>
        <div>
          <h2>区间分布与极值</h2>
          <p class="step-sub">窗口内逐日统计：估值三区分布 · 股价相对当前买卖点 · 距极值溢出</p>
        </div>
      </div>
      <div class="dist3">
        <div>
          <h3>估值倍数（窗口 {{ channelData.channel.zones ? channelData.channel.zones.n + ' 日' : '—' }}）</h3>
          <table class="mini">
            <tbody>
              <tr><td>低于低估线 {{ channelData.channel.lower2.toFixed(2) }}</td>
                <td class="num">{{ zoneRow('', channelData.channel.zones?.below_low).text }}</td></tr>
              <tr><td>通道内（±2σ）</td>
                <td class="num">{{ zoneRow('', channelData.channel.zones?.inside).text }}</td></tr>
              <tr><td>高于高估线 {{ channelData.channel.upper2.toFixed(2) }}</td>
                <td class="num">{{ zoneRow('', channelData.channel.zones?.above_high).text }}</td></tr>
            </tbody>
          </table>
        </div>
        <div>
          <h3>股价 × 买卖点（{{ btData?.price_stats ? `窗口 ${btData.price_stats.n} 日` : '回拨后展示' }}）</h3>
          <table class="mini">
            <tbody>
              <template v-if="btData?.price_stats">
                <tr><td>低于买点 {{ btData.price_stats.buy_price.toFixed(2) }}</td>
                  <td class="num">{{ zoneRow('', btData.price_stats.below_buy).text }}</td></tr>
                <tr><td>买点 ~ 卖点之间</td>
                  <td class="num">{{ zoneRow('', btData.price_stats.inside).text }}</td></tr>
                <tr><td>高于卖点 {{ btData.price_stats.sell_price.toFixed(2) }}</td>
                  <td class="num">{{ zoneRow('', btData.price_stats.above_sell).text }}</td></tr>
              </template>
              <tr v-else><td class="meta">回拨后按当前买卖点统计。</td></tr>
            </tbody>
          </table>
        </div>
        <div>
          <h3>股价极值（收盘口径）</h3>
          <table class="mini">
            <tbody>
              <tr><td>最低 {{ extremes.low ? extremes.low.price.toFixed(2) : '—' }}（{{ fmtDate(extremes.low?.date) }}）</td>
                <td class="num">{{ extremes.low?.premium_pct != null
                  ? `现价溢价 +${(extremes.low.premium_pct * 100).toFixed(1)}%` : '—' }}</td></tr>
              <tr><td>最高 {{ extremes.high ? extremes.high.price.toFixed(2) : '—' }}（{{ fmtDate(extremes.high?.date) }}）</td>
                <td class="num">{{ extremes.high?.discount_pct != null
                  ? `现价距高点 ${(extremes.high.discount_pct * 100).toFixed(1)}%` : '—' }}</td></tr>
              <tr><td>现价</td>
                <td class="num">{{ extremes.last_close != null ? extremes.last_close.toFixed(2) : '—' }}</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <!-- ⑥ 拨测结果 -->
    <section v-if="btData" class="card">
      <div class="step-head">
        <span class="step-badge">3</span>
        <div>
          <h2>拨测结果：波段 vs 长持</h2>
          <p class="step-sub">同窗口历史回放；长持基准 = 首日收盘买入持有至窗口末（不含现金收益）</p>
        </div>
      </div>
      <table class="cmp">
        <tr>
          <th>维度</th>
          <th>{{ btData.suggest ? '波段（推荐区间）' : '波段（你的买卖点）' }}</th>
          <th>长持（同期一动不动）</th><th>差值</th>
        </tr>
        <tr>
          <td>区间收益</td>
          <td :class="{ win: (btData.compare?.delta?.return_spread ?? -1) >= 0 }">
            {{ fmtPctSigned(btData.compare?.swing?.return_pct) }}</td>
          <td :class="{ win: (btData.compare?.delta?.return_spread ?? -1) < 0 }">
            {{ fmtPctSigned(btData.compare?.hold?.return_pct) }}</td>
          <td>{{ btData.compare?.delta?.return_spread != null
            ? fmtPctSigned(btData.compare.delta.return_spread) : '—' }}</td>
        </tr>
        <tr>
          <td>最大回撤</td>
          <td>{{ pctText(btData.compare?.swing?.mdd) }}</td>
          <td>{{ pctText(btData.compare?.hold?.mdd) }}</td>
          <td>{{ btData.compare?.delta?.mdd_spread != null
            ? fmtPctSigned(btData.compare.delta.mdd_spread) : '—' }}</td>
        </tr>
        <tr>
          <td>持仓天数</td>
          <td>{{ btData.compare?.swing?.days_held ?? '—' }}
            （空仓 {{ pctText(btData.compare?.swing?.flat_ratio) }}）</td>
          <td>{{ btData.compare?.hold?.days || '—' }} 天（100%）</td>
          <td>—</td>
        </tr>
        <tr>
          <td>触发</td>
          <td>{{ btData.backtest.hit_buy
            ? `${btData.backtest.roundtrips_done || 0} 次完整进出 · 首买 ${btData.backtest.buy_date}${btData.backtest.still_holding ? '（窗口末仍持仓）' : ''}`
            : '未触发买入' }}</td>
          <td>—</td><td>—</td>
        </tr>
        <tr v-if="btData.suggest && btData.backtest.underwater_days != null">
          <td>亏损持仓</td>
          <td colspan="3">{{ btData.backtest.underwater_days }} / {{ btData.backtest.window?.bars }} 个交易日
            （收盘低于买价）</td>
        </tr>
        <tr v-if="btData.backtest.sell_reason === 'stop'">
          <td>止损</td>
          <td colspan="3" class="red-note">已触发（{{ btData.backtest.sell_date }}）</td>
        </tr>
      </table>
      <p v-if="btData.compare?.verdict" class="verdict">{{ btData.compare.verdict }}</p>
      <p v-if="btData.backtest.no_stop_worst_drawdown != null" class="red-note">
        未设止损：持有期最差浮亏曾达 {{ pctText(btData.backtest.no_stop_worst_drawdown) }}。
      </p>
      <details v-if="(btData?.backtest.events || []).length" class="evt">
        <summary>交易记录（{{ (btData?.backtest.events ?? []).length }} 笔{{ btData?.backtest.still_holding ? '，窗口末仍持仓' : '' }}）</summary>
        <table class="mini">
          <thead><tr><th>日期</th><th>操作</th><th class="num">成交价（元）</th></tr></thead>
          <tbody>
            <tr v-for="(e, i) in btData?.backtest.events || []" :key="`${e.date}-${e.type}-${i}`">
              <td>{{ e.date ?? '—' }}</td>
              <td>{{ e.type === 'buy' ? '买入' : e.type === 'sell' ? '止盈卖出' : '止损卖出' }}</td>
              <td class="num">{{ Number(e.price).toFixed(2) }}</td>
            </tr>
          </tbody>
        </table>
      </details>
      <p class="meta">免责声明：本结果为统计描述与历史回放，不构成投资建议；买卖点由你自己设定与负责。</p>
    </section>

    <div class="foot">
      <p class="foot-disclaimer">⚠️ <b>免责声明：</b>本工具输出<b>统计描述与历史回放</b>，不构成任何投资建议；
        买卖点由你自己设定与负责。历史表现不代表未来。</p>
      <div class="foot-body">
        <b>算法说明</b>：估值通道 = 均值 ± Nσ（σ 为窗口内总体标准差 ÷N，下轨截 0），与平台 web「估值通道」同源；
        买卖点换算 = 现价 × 目标倍数 / 当前倍数（隐含口径内 EPS/BPS 恒定）。窗口 6 个月/1/2/3 年（上限 3 年），
        默认半年，进页自动加载。
        <b>推荐区间</b> = 窗口内穷举候选买卖倍数组合，须满足四条约束：买点不高于均值（不高估）、
        买入价距窗口最低收盘 ≤15%（距最低点不要太远）、亏损持仓日占窗口 ≤35%（亏损时间不要过长）、
        完整进出 ≥2 次（成交次数不要太少）；在满足约束的组合中按多轮回放收益择优（同收益取进出更多者），
        无组合满足时逐级放宽并如实标注，全程无完整进出则回退通道轨。
        <b>回放规则</b>：日 low≤买点触发买入（成交 min(open,买点)）；持仓日 high≥卖点止盈（max(open,卖点)）、
        low≤止损止损（min(open,止损)）；同日双触发按保守先止损；T+1 买入当日不卖；
        止盈/止损出场后资金回笼，卖出次日可再次买入，回放窗口内全部进出；
        多轮收益按各轮复利（空仓期收益 0，不含现金利息）。
        <b>简化假设</b>：不含涨跌停与成交量约束；qfq 前复权口径已消除除权跳空；
        数据以上市公司公告与平台数据源为准。
      </div>
    </div>
  </main>
</template>

<style scoped>
.foot-disclaimer {
  background: rgba(220, 38, 38, .10); border: 1px solid rgba(220, 38, 38, .35);
  color: #dc2626; border-radius: 10px; padding: 10px 12px; margin: 0 0 12px;
  font-size: 12.5px; font-weight: 700;
}
.foot-disclaimer b { color: #dc2626; }
.foot[open] summary::after { content: " ‹"; }
.foot-body { margin-top: 10px; }
.lv { width: 100%; border-collapse: collapse; font-size: 13.5px; margin-top: 12px; }
.lv th {
  text-align: left; font-weight: 400; color: var(--text-2, #475569);
  padding: 6px 4px; border-bottom: 1px solid var(--line); white-space: nowrap;
}
.lv td { padding: 8px 4px; border-bottom: 1px solid var(--line); }
.lv td.num, .lv th.num { text-align: right; white-space: nowrap; }
.lv td:first-child { font-weight: 600; }
.evt { margin-top: 12px; }
.evt summary {
  cursor: pointer; font-size: 12.5px; font-weight: 600; color: var(--text); list-style: none;
}
.evt summary::-webkit-details-marker { display: none; }
.evt summary::after { content: " ›"; color: var(--text-2, #64748b); }
.evt[open] summary::after { content: " ‹"; }
.evt .mini { margin-top: 8px; }
.pain-action {
  margin: 12px 0 0; border-left: 3px solid var(--accent);
  background: rgba(37, 99, 235, .06); border-radius: 8px; padding: 10px 12px;
  font-size: 13.5px; line-height: 1.75;
}
.pain-action .brand { color: var(--accent); }
.page-head h1 .warn { color: #dc2626; }
.page-sub-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.page-sub-row p { margin: 0; }
.page-sub-row :deep(input) { width: 150px; }
.banner {
  background: #fef2f2; border: 1px solid #fecaca; border-left: 4px solid #dc2626;
  color: #b91c1c; padding: 10px 14px; border-radius: 8px; margin: 12px 0;
  font-size: 13.5px; font-weight: 650;
}
.banner b { font-weight: 750; }
.seg {
  display: inline-flex; border: 1px solid var(--line); border-radius: 8px; overflow: hidden;
}
.seg button {
  border: none; background: var(--surface); padding: 6px 14px; font-size: 13px;
  color: var(--text); cursor: pointer;
}
.seg button.active { background: var(--accent); color: #fff; font-weight: 560; }
.kpis { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin: 14px 0; }
@media (max-width: 1080px) {
  .duo { grid-template-columns: 1fr; }
  .kpis { grid-template-columns: repeat(2, 1fr); }
}
.red-note { color: #dc2626; font-weight: 600; }
.buy-price { color: #16a34a; }
.sell-price { color: #dc2626; }
.cmp { width: 100%; border-collapse: collapse; font-size: 13.5px; }
.cmp th, .cmp td { border: 1px solid var(--line); padding: 7px 10px; text-align: center; }
.cmp th { background: var(--accent-soft); color: var(--accent-hover); }
.cmp td.win { background: #ecfdf5; font-weight: 640; color: #047857; }
.dist3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 18px; }
@media (max-width: 1080px) { .dist3 { grid-template-columns: 1fr; } }
.dist3 h3 { margin: 0 0 6px; font-size: 13.5px; }
.mini { width: 100%; border-collapse: collapse; font-size: 13px; }
.mini td { padding: 5px 2px; border-bottom: 1px dashed var(--line); }
.mini td.num { text-align: right; font-weight: 600; white-space: nowrap; }
.verdict { margin-top: 8px; font-size: 13px; color: #475569; }
.foot { color: #64748b; font-size: 12.5px; margin-top: 18px; line-height: 1.7; }
.chips {
  font-size: 12.5px; line-height: 1.7; border-radius: 8px; padding: 6px 10px; margin: 8px 0;
  background: #ecfdf5; color: #047857;
}
.chips.relax { background: #fffbeb; color: #92400e; }
</style>
