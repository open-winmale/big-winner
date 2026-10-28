<script setup lang="ts">
import { computed, watch } from 'vue';
import { eventInHorizon, useShouxi } from '@/features/shouxi/store';
import type { CalendarEvent } from '@/api/types';
import EventRow from './EventRow.vue';

const store = useShouxi();

const HORIZONS = [
  { days: 7, label: '今天 / 本周' },
  { days: 30, label: '未来 30 天' },
  { days: 90, label: '未来 90 天' },
  { days: 365, label: '未来 12 个月' },
];

/** 事件按视界过滤（is_plan 恒显示） */
const visibleEvents = computed<CalendarEvent[]>(() => {
  const d = store.calendarData;
  if (!d) return [];
  return (d.events || []).filter((e) => eventInHorizon(e, store.calendarHorizon));
});

const GROUP_ORDER: [string, string][] = [
  ['待除权', '待除权'], ['预案待定', '预案待定'],
  ['已除权待到账', '已除权待到账'], ['已到账', '已到账'], ['待定', '待定'],
];

const eventGroups = computed(() => {
  const d = store.calendarData;
  if (!d) return [];
  const events = visibleEvents.value;
  if (!events.length) return [];
  const groups: { stage: string; title: string; events: CalendarEvent[] }[] = [];
  for (const [stage, title] of GROUP_ORDER) {
    const group = events.filter((e) => e.stage === stage);
    if (group.length) groups.push({ stage, title, events: group });
  }
  return groups;
});

/** 持仓视图：该视界内没有任何未来事件 → 展示市场池预览 */
const needPreview = computed(() => {
  const d = store.calendarData;
  if (!d || d.mode !== 'positions') return false;
  return !visibleEvents.value.some((e) => FUTURE(e));
});

function FUTURE(e: CalendarEvent): boolean {
  return ['待除权', '已除权待到账', '预案待定'].includes(e.stage)
    && eventInHorizon(e, store.calendarHorizon);
}

const previewEvents = computed<CalendarEvent[]>(() => {
  const d = store.marketPreview;
  if (!d) return [];
  const order: Record<string, number> = { '待除权': 0, '已除权待到账': 1, '预案待定': 2 };
  return (d.events || [])
    .filter((e) => order[e.stage] !== undefined)
    .sort((a, b) => {
      const byStage = order[a.stage] - order[b.stage];
      if (byStage) return byStage;
      return String(a.ex_date || '9999-12-31')
        .localeCompare(String(b.ex_date || '9999-12-31'));
    })
    .slice(0, 6);
});

/* 持仓视图渲染完成后若需要市场预览则触发取数（视界切换也复查一次） */
watch(() => [needPreview.value, store.calendarHorizon] as const, ([v]) => {
  if (v) void store.ensureMarketPreview();
}, { immediate: true });

const positionTabsShown = computed(() =>
  store.calendarMode !== 'positions' && store.positions.length > 0);
</script>

<template>
  <div class="card calendar-card">
    <div class="card-head">
      <h2>分红日历</h2>
      <span class="hint">未来除权/到账与分红金额；预案单独标注。税后测算在「记账」</span>
      <span class="spacer"></span>
      <button class="ghost" style="padding:4px 10px;font-size:12.5px"
              @click="store.loadCalendar(store.calendarMode)">刷新</button>
    </div>
    <div class="toolbar calendar-tabs">
      <button v-for="h in HORIZONS" :key="h.days"
              :class="{ active: store.calendarHorizon === h.days }"
              @click="store.calendarHorizon = h.days">{{ h.label }}</button>
      <span class="spacer"></span>
      <button class="ghost" @click="store.calendarMarket = 'cn'; store.loadCalendar('market')">高股息池 · A 股</button>
      <button class="ghost" @click="store.calendarMarket = 'hk'; store.loadCalendar('market')">高股息池 · 港股</button>
      <button v-if="positionTabsShown" class="ghost" @click="store.loadCalendar('positions')">回到我的持仓</button>
    </div>

    <!-- 空态：没有持仓 -->
    <div v-if="store.calendarMode === 'positions' && !store.positions.length" class="calendar-empty">
      <div>还没有持仓。先添加股票，或看看高股息池里即将除权的票。</div>
      <div class="toolbar">
        <button class="ghost" @click="store.calendarMarket = 'cn'; store.loadCalendar('market')">高股息池 · A 股</button>
        <button class="ghost" @click="store.calendarMarket = 'hk'; store.loadCalendar('market')">高股息池 · 港股</button>
        <button class="ghost" @click="store.showWatchlistGroups()">从关注分组导入</button>
      </div>
      <div class="muted" style="font-size:11.5px;margin-top:8px">
        高股息池只展示已公告事件，不构成投资建议。
      </div>
    </div>

    <!-- 关注分组导入 -->
    <template v-else-if="store.importingGroups">
      <div class="skeleton" style="margin:8px 0"></div>
      <div class="skeleton" style="margin:8px 0"></div>
    </template>
    <template v-else-if="store.watchlistGroups !== null">
      <div class="card-head" style="margin:6px 0 10px">
        <h2 style="font-size:14px">选择关注分组作为观察池</h2>
        <span class="hint">不计算个人现金，只看即将除权/到账</span>
      </div>
      <template v-if="store.watchlistGroups.length">
        <div v-for="g in store.watchlistGroups" :key="g.name" class="toolbar" style="margin:6px 0">
          <span class="strong">{{ g.name }}</span>
          <span class="muted">{{ (g.symbols || []).length }} 只</span>
          <button class="link" @click="store.importGroup(g)">作为观察池</button>
        </div>
      </template>
      <div v-else class="calendar-empty">没有读取到关注分组；先在 winmale 创建分组。</div>
    </template>

    <!-- 日历主体 -->
    <template v-else>
      <template v-if="store.calendarLoading">
        <div class="skeleton" style="margin:8px 0"></div>
        <div class="skeleton" style="margin:8px 0"></div>
        <div class="skeleton" style="margin:8px 0"></div>
      </template>
      <div v-else-if="store.calendarError" class="error">
        <strong>日历取数失败：</strong>{{ store.calendarError }}
        <div style="margin-top:8px">高股息池不可用时，可以先导入关注分组或添加持仓。</div>
        <div class="toolbar" style="margin-top:8px">
          <button class="ghost" @click="store.calendarMarket = 'cn'; store.loadCalendar('market')">高股息池 · A 股</button>
          <button class="ghost" @click="store.calendarMarket = 'hk'; store.loadCalendar('market')">高股息池 · 港股</button>
          <button class="ghost" @click="store.showWatchlistGroups()">从关注分组导入</button>
        </div>
      </div>
      <template v-else-if="store.calendarData">
        <div v-if="store.calendarData.mode !== 'positions'" class="muted"
             style="font-size:11.5px;margin-top:8px">
          市场视图来自平台高股息选股池（股息率 ≥ 3%），只展示其中已公告的分红事件，不是全市场逐票扫描。
        </div>

        <template v-if="needPreview">
          <div class="muted" style="font-size:12.5px;margin:8px 0 0">
            你的持仓未来 {{ store.calendarHorizon }} 天没有已公告的分红事件；下面是市场高股息池的即将分红/预案。
          </div>
          <div class="market-preview">
            <template v-if="store.marketPreviewLoading">
              <div class="skeleton" style="margin:8px 0"></div>
              <div class="muted" style="font-size:11.5px;margin-top:6px">
                正在查市场高股息池的即将分红/预案（首次约 10–25 秒，之后 10 分钟缓存）…
              </div>
            </template>
            <div v-else-if="store.marketPreviewError" class="muted" style="font-size:12px">
              市场池加载失败：{{ store.marketPreviewError }}
            </div>
            <template v-else-if="store.marketPreview">
              <div v-if="!previewEvents.length" class="market-preview-empty">
                高股息池里当前没有已公告的即将分红/预案。
                <button class="link" @click="store.loadCalendar('market')">查看完整市场池</button>
              </div>
              <template v-else>
                <div class="card-head" style="margin:16px 0 8px">
                  <h3 style="font-size:13px;margin:0">
                    市场高股息池 · {{ store.marketPreview.market === 'hk' ? '港股' : 'A 股' }} · 即将分红 / 预案
                  </h3>
                  <span class="hint">
                    待除权 {{ store.marketPreview.summary?.ex_count_30 || 0 }} ·
                    预案待定 {{ store.marketPreview.summary?.plan_count || 0 }}
                  </span>
                  <span class="spacer"></span>
                  <button class="link" @click="store.loadCalendar('market')">查看全部</button>
                </div>
                <div class="event-list">
                  <EventRow v-for="e in previewEvents" :key="e.code + String(e.ex_date)"
                            :event="e" @analyze="store.openDiagnose" />
                </div>
                <div class="muted" style="font-size:11.5px;margin-top:6px">
                  来自高股息池（股息率 ≥ 3%），只列已公告事件，不是全市场逐票扫描。
                </div>
              </template>
            </template>
          </div>
        </template>

        <template v-else-if="eventGroups.length">
          <div class="event-groups">
            <div v-for="g in eventGroups" :key="g.stage" class="event-group">
              <h3>{{ g.title }} · {{ g.events.length }}</h3>
              <div class="event-list" :class="{ long: g.events.length > 8 }">
                <EventRow v-for="(e, i) in g.events" :key="e.code + String(e.ex_date) + i"
                          :event="e" @analyze="store.openDiagnose" />
              </div>
            </div>
          </div>
        </template>

        <div v-else class="calendar-empty" style="margin-top:12px">
          未来 {{ store.calendarHorizon }} 天没有已公告的分红事件。
          <template v-if="store.calendarData.mode === 'positions'">
            <div class="toolbar">
              <button class="ghost" @click="store.calendarMarket = 'cn'; store.loadCalendar('market')">看看高股息池 · A 股</button>
              <button class="ghost" @click="store.calendarMarket = 'hk'; store.loadCalendar('market')">高股息池 · 港股</button>
            </div>
            <div class="muted" style="font-size:11.5px;margin-top:6px">
              你的持仓没有已公告事件；市场高股息池里还有正在预案/待除权的公司。
            </div>
          </template>
          <div v-else class="muted" style="margin-top:6px">可切到「未来 12 个月」，或换 A/港股池。</div>
        </div>
      </template>
    </template>
  </div>
</template>
