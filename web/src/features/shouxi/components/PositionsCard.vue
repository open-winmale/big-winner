<script setup lang="ts">
import { computed, ref } from 'vue';
import { useShouxi } from '@/features/shouxi/store';
import { marketOf } from '@/format';
import MarketTag from '@/components/MarketTag.vue';
import SymbolSearch from '@/components/SymbolSearch.vue';

const store = useShouxi();

const placeholder = computed(() => store.currentMarket === 'hk'
  ? '搜索港股：代码 / 名称 / 拼音，如 00700、腾讯、txkg'
  : '搜索：代码 / 名称 / 拼音 / 缩写');

function onPick(item: { code: string; name: string; market?: string }): void {
  store.addPosition(item);
}

function onRaw(code: string): void {
  store.addPosition({ code, market: 'cn' });
}

/* ---- 持仓明细（折叠区） ---- */
const bulkBuyDate = ref('');
const bulkBuyOnlyEmpty = ref(true);
const bulkTax = ref<number | null>(null);

/** 自动载入提示里的「编辑持仓」：展开明细并滚过去（同旧版 getElementById 行为） */
function openDetails(): void {
  document.getElementById('positions-card')
    ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  const el = document.querySelector<HTMLDetailsElement>('#holdings-details');
  if (el) el.open = true;
}
defineExpose({ openDetails });

const noCostCount = computed(() =>
  store.positions.filter((p) => p.cost === '' || p.cost == null).length);

const taxPct = (v: number | string | ''): string => {
  if (v === '' || v == null) return '';
  const n = Number(v);
  return Number.isFinite(n) ? String(Number((n * 100).toFixed(4))) : '';
};
</script>

<template>
  <section class="card" id="positions-card">
    <div class="step-head">
      <span class="step-badge">1</span>
      <div>
        <h2>添加你的股票
          <span class="hint">{{ store.positions.length ? `${store.positions.length} 只标的` : '' }}</span>
        </h2>
        <p class="step-sub">选市场 → 搜索名称或代码 → 回车加入；成本 / 买入日在下方「持仓明细」补，成本和红利税会用到</p>
      </div>
    </div>

    <div class="search-row">
      <div class="market-tabs">
        <button class="market-tab" :class="{ active: store.currentMarket === 'cn' }"
                @click="store.currentMarket = 'cn'">A 股</button>
        <button class="market-tab" :class="{ active: store.currentMarket === 'hk' }"
                @click="store.currentMarket = 'hk'">港股</button>
      </div>
      <SymbolSearch :market="store.currentMarket" :placeholder="placeholder"
                    @pick="onPick" @raw="onRaw" />
    </div>

    <!-- chips -->
    <div v-if="store.positions.length" class="chips">
      <div v-for="(p, i) in store.positions" :key="marketOf(p) + ':' + p.code" class="chip">
        <MarketTag :market="marketOf(p)" />
        <span class="chip-code">{{ p.code }}</span>
        <span class="chip-name">{{ p.name }}</span>
        <input v-model="p.shares" class="chip-shares num" title="持股数" inputmode="numeric">
        <span class="chip-unit">股</span>
        <button class="chip-del" title="移除" @click="store.removeAt(i)">×</button>
      </div>
    </div>
    <div v-else class="empty-guide">
      <div class="guide-step"><span class="guide-no">1</span>上面搜索一只股票，回车加入</div>
      <div class="guide-step"><span class="guide-no">2</span>在胶囊里填上你持有的股数</div>
      <div class="guide-step"><span class="guide-no">3</span>透视表默认自动生成，改持仓后点「生成透视表」重算</div>
    </div>

    <details id="holdings-details" class="holdings-details">
      <summary>
        持仓明细：成本（选填）/ 买入日 / 税率覆盖
        <span v-if="store.positions.length" class="badge" :class="noCostCount ? 'warn' : 'ok'">
          成本 {{ store.positions.length - noCostCount }}/{{ store.positions.length }}（选填）
        </span>
      </summary>
      <template v-if="store.positions.length">
        <div class="toolbar holdings-bulk">
          <label>全部买入日 <input v-model="bulkBuyDate" type="date"></label>
          <label class="switch"><input v-model="bulkBuyOnlyEmpty" type="checkbox"> 仅填空白</label>
          <button class="ghost" @click="store.bulkBuyDate(bulkBuyDate, bulkBuyOnlyEmpty)">应用</button>
          <span class="muted">|</span>
          <label>全部税率
            <input v-model.number="bulkTax" type="number" min="0" max="100" step="0.1"
                   placeholder="如 20" style="width:74px"> %
          </label>
          <button class="ghost" @click="bulkTax != null && store.bulkTaxRate(bulkTax)">应用</button>
          <button class="ghost" @click="store.bulkTaxRate(null)">清空覆盖</button>
        </div>
        <div class="table-scroll">
          <table class="holdings-table">
            <thead><tr>
              <th>代码</th><th>名称</th><th class="num">股数</th>
              <th class="num">成本价 <span class="muted">(选填)</span></th>
              <th>买入日期</th><th class="num">税率覆盖 %</th><th></th>
            </tr></thead>
            <tbody>
              <tr v-for="(p, i) in store.positions" :key="marketOf(p) + ':' + p.code">
                <td class="sym-cell"><MarketTag :market="marketOf(p)" /> {{ p.code }}</td>
                <td>{{ p.name }}</td>
                <td class="num">
                  <input class="input-sm num" :value="p.shares" inputmode="numeric"
                         style="width:88px" @input="store.updateField(i, 'shares', ($event.target as HTMLInputElement).value)">
                </td>
                <td class="num">
                  <input class="input-sm num" :value="p.cost" inputmode="decimal"
                         :placeholder="marketOf(p) === 'hk' ? 'HKD' : '元'" style="width:88px"
                         @input="store.updateField(i, 'cost', ($event.target as HTMLInputElement).value)">
                </td>
                <td>
                  <input class="input-sm" type="date" :value="p.buy_date" style="width:140px"
                         @input="store.updateField(i, 'buy_date', ($event.target as HTMLInputElement).value)">
                </td>
                <td class="num">
                  <input class="input-sm num" :value="taxPct(p.tax_rate)" inputmode="decimal"
                         placeholder="自动" style="width:76px"
                         @input="store.updateField(i, 'tax_rate', ($event.target as HTMLInputElement).value)">
                </td>
                <td><button class="link" title="移除" @click="store.removeAt(i)">×</button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="muted" style="font-size:11.5px;margin-top:6px">
          成本价选填（按报价币种，港股 HKD），填了才有成本股息率与浮盈；
          买入日期默认今年 1 月 1 日，用于按持有时长估红利税；
          税率覆盖留空 = 按规则自动（A 股按持有期，港股默认 20%）。
        </div>
      </template>
      <div v-else class="muted" style="font-size:12.5px">先添加股票。</div>
    </details>

    <!-- 生成 -->
    <div class="run-row">
      <label class="switch" title="额外计算股息率历史分位、连续分红年数">
        <input v-model="store.deep" type="checkbox"> 深度分析（更全面，取数稍多）
      </label>
      <span class="spacer"></span>
      <button class="primary btn-lg" @click="store.runXray()">生成透视表</button>
    </div>
  </section>
</template>
