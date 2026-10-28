<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { api, ApiError } from '@/api/client';
import { fmtMoney, fmtPct, normalizePosition } from '@/format';
import { useShouxi } from '@/features/shouxi/store';
import CalendarCard from '@/features/shouxi/components/CalendarCard.vue';
import PositionsCard from '@/features/shouxi/components/PositionsCard.vue';
import XrayResult from '@/features/shouxi/components/XrayResult.vue';
import QualityPanel from '@/features/shouxi/components/QualityPanel.vue';
import LedgerPanel from '@/features/shouxi/components/LedgerPanel.vue';
import DiagnoseModal from '@/features/shouxi/components/DiagnoseModal.vue';
import Modal from '@/components/ui/Modal.vue';
import { useApp } from '@/store/useApp';

const store = useShouxi();
const app = useApp();

onMounted(() => { void store.autoLoad(); });

/* ---------------- 结果区错误提示（429 → 引导配 Key） ---------------- */
const isRateError = (): boolean => {
  const msg = store.xrayError;
  return msg.includes('429') || msg.includes('限流') || msg.includes('limit');
};

/** 演示模式：持仓里有快照外的标的（必然缺数据）→ 引导换 Key */
const demoOutside = computed(() =>
  app.hasDemoOutside(store.positions.map((p) => p.code)));

/** 自动载入提示里的「编辑持仓」：滚到持仓卡并展开明细（同旧版行为） */
function editPositions(): void {
  document.getElementById('positions-card')
    ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  const el = document.querySelector<HTMLDetailsElement>('#holdings-details');
  if (el) el.open = true;
}

/* ---------------- 更多：存档 / 载入 / 历史 ---------------- */
const dialog = ref<'' | 'save' | 'load' | 'history'>('');
const moreOpen = ref(false);
const saveName = ref('');
const saveResult = ref('');
const loadSets = ref<{ name: string; n: number; updated_at: string }[]>([]);
const history = ref<{
  taken_at: string; n_positions: number;
  total_market_value?: number | null; total_dividend?: number | null;
  portfolio_yield?: number | null;
}[]>([]);

async function openLoad(): Promise<void> {
  dialog.value = 'load';
  try {
    const d = await api.positionsList();
    loadSets.value = d.sets || [];
  } catch (e) {
    saveResult.value = e instanceof Error ? e.message : String(e);
  }
}

async function doSave(): Promise<void> {
  const name = saveName.value.trim();
  if (!name) { saveResult.value = '请给持仓档案起个名字'; return; }
  try {
    await api.positionsSave({ name, positions: store.positions });
    saveResult.value = `已保存「${name}」（${store.positions.length} 只）`;
  } catch (e) {
    saveResult.value = e instanceof ApiError ? e.message : String(e);
  }
}

async function doLoad(name: string): Promise<void> {
  try {
    const d = await api.positionsLoad({ name });
    store.positions = (d.positions || []).map((p) => normalizePosition(p as never));
    dialog.value = '';
    void store.runXray();
    void store.loadCalendar('positions');
  } catch (e) {
    saveResult.value = e instanceof ApiError ? e.message : String(e);
  }
}

async function openHistory(): Promise<void> {
  dialog.value = 'history';
  try {
    const d = await api.snapshots();
    history.value = (d.history || []).filter((x) => x.mode === 'real');
  } catch (e) {
    saveResult.value = e instanceof Error ? e.message : String(e);
  }
}
</script>

<template>
  <main class="wrap">
    <div class="page-head">
      <h1>收息佬</h1>
      <p>分红日历 · 持续性分析 · 税后记账 —— 攒股收息，一页看清。</p>
      <p class="auto-note">
        {{ store.autoNote }}
        <template v-if="store.autoNote">
          <button class="link" @click="openLoad">换一份</button>
          <button class="link" @click="editPositions">编辑持仓</button>
        </template>
      </p>
    </div>

    <!-- 收息驾驶舱 -->
    <CalendarCard />

    <!-- 添加持仓 -->
    <PositionsCard />

    <!-- 结果区 -->
    <div id="result">
      <div v-if="store.xrayLoading" class="card" style="margin-top:18px">
        <div class="card-head"><h2>正在取数…</h2></div>
        <div v-for="i in 6" :key="i" class="skeleton" style="margin:9px 0"></div>
      </div>
      <div v-else-if="store.xrayError" class="error" style="margin-top:18px">
        <strong>取数失败：</strong>{{ store.xrayError }}
        <div style="margin-top:8px;color:var(--text-2)">
          <template v-if="isRateError()">
            数据源的小时额度已用完。
            <button class="link" @click="app.openKeyDialog()">🔑 立即配置自己的 Key</button>
            （两分钟，额度独立）；或等下一个整点自动恢复。
          </template>
          <template v-else>
            401/403 → <button class="link" @click="app.openKeyDialog()">检查 Key 配置</button>。
          </template>
        </div>
      </div>
      <template v-else-if="store.xray">
        <div v-if="demoOutside" class="demo-outside">
          演示快照只覆盖示例标的，其余股票没有数据。配置自己的 Key 即解锁全市场实时数据。
          <button class="link" @click="app.openKeyDialog()">🔑 换 Key</button>
        </div>
        <XrayResult :data="store.xray" />
      </template>
      <div v-else-if="!store.positions.length" class="empty" style="margin-top:18px">请先添加持仓</div>
    </div>

    <!-- 分红质量 -->
    <QualityPanel v-if="store.qualityPanelVisible" />

    <!-- 记账 -->
    <LedgerPanel />

    <!-- 更多（次要功能折叠） -->
    <section class="card more-card">
      <button class="link" @click="moreOpen = !moreOpen">
        {{ moreOpen ? '▾ 收起' : '▸ 更多：持仓单管理 · 生成记录 · 数据导出' }}
      </button>
      <div v-if="moreOpen" style="margin-top:12px">
          <p class="muted more-explain">
            · <strong>持仓单</strong>：把当前股票清单存在本机，下次打开免重新搜索<br>
            · <strong>生成记录</strong>：每次生成自动留档，回看历史组合数据<br>
            · <strong>导出 CSV</strong>：把透视表下载成 Excel 能打开的表格
          </p>
          <div class="toolbar">
            <button class="ghost" @click="dialog = 'save'; saveResult = ''">存为持仓单</button>
            <button class="ghost" @click="openLoad">打开持仓单</button>
            <button class="ghost" @click="openHistory">生成记录</button>
            <button class="ghost" @click="api.exportXrayCsv(store.positions)">导出 CSV (Excel)</button>
          </div>
        </div>
    </section>

    <div class="footer">
      <div>本工具仅做持仓数据的统计聚合，不构成任何投资建议；数据来自 wmshare，最终以上市公司公告为准；历史分红不代表未来。</div>
      <div style="margin-top:6px">收息佬（big-winner） · MIT 开源 · 数据由 wmshare 提供（PolyForm Noncommercial，仅限非商业使用）</div>
    </div>

    <!-- 诊股弹层 -->
    <DiagnoseModal @close="store.diagnoseOpen = false" />

    <!-- 存为持仓单 -->
    <Modal :open="dialog === 'save'" title="保存持仓档案" width="480px"
           @close="dialog = ''">
      <div class="toolbar">
        <input v-model="saveName" placeholder="档案名，如：主仓" style="max-width:240px"
               @keyup.enter="doSave">
        <button class="primary" @click="doSave">保存</button>
        <button class="ghost" @click="dialog = ''">取消</button>
      </div>
      <div v-if="saveResult" style="margin-top:10px">
        <span class="badge ok">{{ saveResult }}</span>
      </div>
    </Modal>

    <!-- 打开持仓单 -->
    <Modal :open="dialog === 'load'" title="载入持仓档案" width="520px"
           @close="dialog = ''">
      <div v-if="!loadSets.length" class="muted">
        还没有保存过档案。先「存为持仓单」。
      </div>
      <div v-for="s in loadSets" :key="s.name" class="toolbar" style="margin:6px 0">
        <span class="strong">{{ s.name }}</span>
        <span class="muted">{{ s.n }} 只 · {{ s.updated_at }}</span>
        <button class="link" @click="doLoad(s.name)">载入</button>
      </div>
      <div v-if="saveResult" class="error" style="margin-top:10px">{{ saveResult }}</div>
    </Modal>

    <!-- 生成记录 -->
    <Modal :open="dialog === 'history'" title="组合快照历史" hint="每次生成自动存档"
           width="640px" @close="dialog = ''">
      <div v-if="!history.length" class="muted">
        还没有快照。生成一次透视表后会自动存档。
      </div>
      <table v-else>
        <thead><tr><th>时间</th><th class="num">标的</th>
          <th class="num">总市值</th><th class="num">总年息</th><th class="num">组合股息率</th></tr></thead>
        <tbody>
          <tr v-for="x in history" :key="x.taken_at">
            <td>{{ x.taken_at }}</td>
            <td class="num">{{ x.n_positions }}</td>
            <td class="num">{{ fmtMoney(x.total_market_value) }}</td>
            <td class="num">{{ fmtMoney(x.total_dividend) }}</td>
            <td class="num strong">{{ fmtPct(x.portfolio_yield) }}</td>
          </tr>
        </tbody>
      </table>
    </Modal>
  </main>
</template>

<style scoped>
/* 演示快照外标的的换 Key 引导条（amber 警示，同 DemoBanner 家族） */
.demo-outside {
  margin-top: 18px;
  padding: 9px 14px;
  border: 1px solid #fde68a;
  border-radius: 10px;
  background: var(--warn-soft);
  color: var(--text-2);
  font-size: 13px;
}
</style>
