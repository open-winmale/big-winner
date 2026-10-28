<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { api, errText, isAuthErrorText } from '@/api/client';
import type { ScreenerResult } from '@/api/types';
import { useApp } from '@/store/useApp';

const app = useApp();

interface Strat {
  id: string;
  name: string;
  market: string;
  intro: string;
}

const STRATS: Strat[] = [
  { id: 'high_yield_3', name: '高股息 ≥3%', market: 'A 股',
    intro: 'TTM 股息率不低于 3%，与平台高股息池同口径' },
  { id: 'high_yield_6', name: '高股息 ≥6%', market: 'A 股',
    intro: 'TTM 股息率不低于 6%，深度高息——警惕价值陷阱，入选后先做体检' },
  { id: 'graham', name: '格雷厄姆（简化）', market: 'A 股',
    intro: 'PE(TTM)<15 且市净率<1.5，经典价值派安全边际筛（蕴含 PE×PB<22.5）' },
  { id: 'cheap_income', name: '低估值高息', market: 'A 股',
    intro: 'PE(TTM)<15 且股息率≥3%，低估值与现金流的交集' },
  { id: 'below_pb', name: '破净股', market: 'A 股',
    intro: '市净率低于 1，市值低于净资产——注意资产质量，入选后先做体检' },
  { id: 'payout_30_70', name: '派息率 30%–70%', market: 'A 股',
    intro: '分红拿得出、留得住的健康区间（口径同分红质量方法论）' },
  { id: 'high_yield_hk', name: '港股高息 ≥6%', market: '港股',
    intro: '港股通红利税默认预扣 20%，6% 起步覆盖税后' },
  { id: 'custom', name: '自定义组合', market: 'A 股',
    intro: '按你填的阈值 AND 组合，全市场执行（股息率 / PE / 市净率）' },
];

const sel = ref('high_yield_3');
const topn = ref('50');
const custom = ref({ yield_gte: '', pe_lt: '', pb_lt: '' });
const running = ref(false);
const result = ref<ScreenerResult | null>(null);
const runHint = ref('');
const pushToast = ref('');
const pushToastBad = ref(false);
const copyToast = ref('');
const copyToastBad = ref(false);

const SAVE_KEY = 'screener_v2';

function save(): void {
  try {
    localStorage.setItem(SAVE_KEY, JSON.stringify({
      sel: sel.value, topn: topn.value, custom: { ...custom.value },
    }));
  } catch { /* 隐私模式忽略 */ }
}

function restore(): void {
  try {
    const saved = JSON.parse(localStorage.getItem(SAVE_KEY) || 'null');
    if (!saved) return;
    if (saved.sel && STRATS.some((s: Strat) => s.id === saved.sel)) sel.value = saved.sel;
    if (saved.topn) topn.value = saved.topn;
    if (saved.custom) {
      custom.value = {
        yield_gte: saved.custom.yield_gte || '',
        pe_lt: saved.custom.pe_lt || '',
        pb_lt: saved.custom.pb_lt || '',
      };
    }
  } catch { /* 忽略 */ }
}

async function run(): Promise<void> {
  if (running.value) return;
  const payload: Record<string, unknown> = { limit: parseInt(topn.value, 10) || 50 };
  if (sel.value === 'custom') payload.custom = { ...custom.value };
  else payload.strategy = sel.value;
  running.value = true;
  runHint.value = '';
  pushToast.value = '';
  result.value = null;
  save();
  try {
    result.value = await api.screener(payload);
  } catch (e) {
    runHint.value = '请求失败：' + errText(e);
  } finally {
    running.value = false;
  }
}

function fmtCell(kind: string | undefined, v: number | null | undefined): string {
  if (v === null || v === undefined) return '—';
  if (kind === 'pct') return (v * 100).toFixed(2) + '%';
  return Number(v).toFixed(2);
}

const orderColLabel = (): string => {
  const d = result.value;
  if (!d?.order?.key) return '';
  const col = (d.columns || []).find((c) => c.key === d.order!.key);
  return col ? `按${col.label}${d.order.dir === 'asc' ? '升序' : '降序'}` : '';
};

async function copyText(text: string, ok: (success: boolean) => void): Promise<void> {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      ok(true);
    } catch { ok(false); }
    return;
  }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    const success = document.execCommand('copy');
    ta.remove();
    ok(success);
  } catch { ok(false); }
}

function copyAll(): void {
  const codes = (result.value?.rows || []).map((r) => r.code);
  copyText(codes.join(', '), (success) => {
    copyToast.value = success ? `已复制 ${codes.length} 个代码` : '复制失败';
    copyToastBad.value = !success;
  });
}

function copyOne(code: string): void {
  copyText(code, (success) => {
    copyToast.value = success ? `已复制 ${code}` : '复制失败';
    copyToastBad.value = !success;
  });
}

async function pushWatchlist(): Promise<void> {
  const strategyName = result.value?.strategy?.name || '选股';
  const codes = (result.value?.rows || []).map((r) => r.code);
  pushToast.value = '推送中…';
  pushToastBad.value = false;
  try {
    const d = await api.watchlistPush({
      group: '选股·' + strategyName,
      positions: codes.map((c) => ({ code: c })),
    });
    pushToast.value =
      `已写入分组「${d.group_id ? '已同步' : '已创建/更新'}」：新增 ${(d.added || []).length} 只，已存在 ` +
      `${(d.already_in || []).length} 只。打开收息佬即可监控这些票的分红日历。`;
  } catch (e) {
    pushToast.value = '推送失败：' + errText(e);
    pushToastBad.value = true;
  }
}

onMounted(restore);
</script>

<template>
  <main class="wrap">
    <div class="banner">
      ⚠️ <b>免责声明：</b>选股结果为<b>事实性筛选</b>，不构成任何投资建议；
      <b>选股 ≠ 推荐</b>，买卖决策由你自己负责。
    </div>

    <div class="page-head">
      <h1>选股 <span style="font-size:15px;color:#64748b">screener</span></h1>
      <p>预置策略 · 一键全市场 —— 格雷厄姆、高股息等策略一句话讲清口径，
         选股清单的数字就是入选证据。</p>
    </div>

    <!-- 策略 -->
    <section class="card">
      <div class="strat-grid">
        <button v-for="s in STRATS" :key="s.id" type="button" class="strat"
                :class="{ sel: s.id === sel }" @click="sel = s.id; save()">
          <h3>{{ s.name }}</h3>
          <p>{{ s.intro }}</p>
          <div class="tags">
            <span class="tag">{{ s.market }}</span>
            <span class="tag">平台选股 · 约 1 次查询</span>
          </div>
        </button>
      </div>

      <div class="custom-panel" :class="{ show: sel === 'custom' }">
        条件可留空，至少填一项；同一策略内条件为 AND 关系。<br>
        <label>股息率 ≥ <input v-model="custom.yield_gte" class="mini-input" inputmode="decimal"
               placeholder="如 3 或 0.03"> %</label>
        <label style="margin-left:16px">PE(TTM) ≤ <input v-model="custom.pe_lt" class="mini-input"
               inputmode="decimal" placeholder="如 15"></label>
        <label style="margin-left:16px">市净率 ≤ <input v-model="custom.pb_lt" class="mini-input"
               inputmode="decimal" placeholder="如 1.5"></label>
      </div>

      <div class="run-row">
        <span>数量
          <select v-model="topn" class="topn" @change="save()">
            <option>30</option><option>50</option>
            <option>100</option><option>200</option>
          </select>
        </span>
        <button class="run-btn" :disabled="running" @click="run">开始选股</button>
        <span class="quota">预计 1 次查询（top {{ topn }}）</span>
      </div>
      <div v-if="runHint" class="toast bad">{{ runHint }}
        <button v-if="isAuthErrorText(runHint)" class="link"
                @click="app.openKeyDialog()">🔑 配置 Key</button>
      </div>
    </section>

    <!-- 结果 -->
    <section class="card" style="margin-top:16px">
      <div v-if="result && !result.error && !result.unavailable" class="result-sum">
        「{{ result.strategy?.name || '' }}」命中
        <b class="pass">{{ (result.rows || []).length }}</b>
        只（top {{ result.limit || '' }}{{ orderColLabel() ? '，' + orderColLabel() : '' }}）
      </div>

      <div v-if="running" class="empty loading">全市场选股中…</div>

      <div v-else-if="result?.error" class="degrade">{{ result.error }}</div>
      <div v-else-if="result?.unavailable" class="degrade">
        <b>该策略暂不可用</b>：{{ result.unavailable }}<br>
        全市场通道需要已配置 wm.sh（平台门面）。可以先试「高股息 ≥3%」
        等其他策略，或本地运行真实模式。选股结果 ≠ 推荐。
      </div>

      <template v-else-if="result">
        <div v-if="!(result.rows || []).length" class="empty">
          没有符合条件的股票——条件可以放宽一点
        </div>
        <div v-else class="table-scroll">
          <table class="grid">
            <thead>
              <tr>
                <th>代码</th><th>名称</th>
                <th v-for="c in result.columns || []" :key="c.key">{{ c.label }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in result.rows || []" :key="r.code">
                <td class="code" title="点击复制" @click="copyOne(r.code)">{{ r.code }}</td>
                <td class="name">{{ r.name || '—' }}</td>
                <td v-for="c in result.columns || []" :key="c.key">
                  {{ fmtCell(c.fmt, (r.values || {})[c.key]) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="(result.rows || []).length" style="margin-top:10px">
          <button type="button" class="sum-btn" @click="copyAll">复制全部代码</button>
          <button v-if="!result.demo" type="button" class="sum-btn" style="margin-left:8px"
                  @click="pushWatchlist">➕ 加入观察池</button>
          <span v-if="result.demo" class="tag">演示模式不推送观察池</span>
        </div>
      </template>
      <div v-else class="empty">选一张策略卡，点「开始选股」</div>

      <div v-if="copyToast" class="toast" :class="{ bad: copyToastBad }">{{ copyToast }}</div>
      <div v-if="pushToast" class="toast" :class="{ bad: pushToastBad }">{{ pushToast }}</div>

      <div class="foot-note">
        「—」为取数缺失；结果按所选策略口径排序。全市场通道与平台 web「选股」同源
        （需已配置 wm.sh；未配置时页面会如实提示）。选股结果 ≠ 推荐；
        深度体检请用「收息佬 · 分红质量 / 持续性分析」。
      </div>
    </section>

    <div class="footer">
      <div>数据来自平台选股引擎与 wmshare；历史选股结果不代表未来；最终以上市公司公告为准。</div>
    </div>
  </main>
</template>

<style scoped>
.banner {
  background: #fef2f2; border: 1px solid #fecaca; border-left: 4px solid #dc2626;
  color: #b91c1c; padding: 10px 14px; border-radius: 8px; margin: 12px 0;
  font-size: 13.5px; font-weight: 650;
}
.banner b { font-weight: 750; }
.strat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 4px; }
@media (max-width: 768px) { .strat-grid { grid-template-columns: 1fr; } }
.strat {
  border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; cursor: pointer;
  background: var(--surface); text-align: left; font: inherit; color: inherit;
  transition: border-color .15s, box-shadow .15s;
}
.strat:hover { border-color: var(--line-strong); }
.strat.sel { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-soft); }
.strat h3 { margin: 0; font-size: 14.5px; font-weight: 650; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.strat p { margin: 6px 0 0; font-size: 12.5px; color: var(--text-2); line-height: 1.55; }
.strat .tags { display: flex; gap: 6px; margin-top: 9px; flex-wrap: wrap; }
.tag {
  font-size: 11px; padding: 2px 8px; border-radius: 99px;
  background: var(--surface-2); color: var(--text-3);
}
.custom-panel {
  display: none; border: 1px dashed var(--line-strong); border-radius: 10px;
  padding: 12px 14px; margin-top: 12px; font-size: 13.5px;
}
.custom-panel.show { display: block; }
.mini-input { width: 110px; padding: 6px 8px; font-size: 13px; }
.mini-input:focus { outline: 2px solid var(--accent-soft); border-color: var(--accent); }
.run-row { display: flex; gap: 12px; align-items: center; margin-top: 16px; flex-wrap: wrap; }
.run-btn {
  padding: 9px 22px; font-size: 14.5px; font-weight: 650; border: none;
  border-radius: 8px; background: var(--accent); color: #fff; cursor: pointer;
}
.run-btn:hover { background: var(--accent-hover); }
.run-btn:disabled { opacity: .5; cursor: default; }
select.topn { width: auto; padding: 7px 10px; font-size: 13.5px; }
.quota { font-size: 12.5px; color: var(--text-3); }
.result-sum {
  font-size: 13.5px; color: var(--text-2); margin: 0 0 10px;
  display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
}
.result-sum b.pass { color: var(--accent); }
.sum-btn {
  font-size: 12.5px; padding: 4px 12px; border-radius: 99px;
  border: 1px solid var(--line-strong); background: var(--surface); cursor: pointer;
}
.sum-btn:hover { border-color: var(--accent); color: var(--accent); }
.grid { width: 100%; border-collapse: collapse; font-size: 13.5px; }
.grid th, .grid td {
  padding: 7px 10px; border-bottom: 1px solid var(--line); text-align: right; white-space: nowrap;
}
.grid th:first-child, .grid td:first-child,
.grid th:nth-child(2), .grid td:nth-child(2) { text-align: left; }
.grid th { color: var(--text-3); font-weight: 600; border-bottom: 1px solid var(--line-strong); }
.grid td.name { color: var(--text-2); }
.grid td.code { cursor: pointer; }
.grid td.code:hover { color: var(--accent); }
.empty { color: var(--text-3); font-size: 13.5px; padding: 18px 0; text-align: center; }
.degrade {
  border: 1px solid #fcd34d; background: #fffbeb; border-radius: 10px;
  padding: 12px 14px; font-size: 13px; color: #92400e; line-height: 1.7;
}
.toast { font-size: 12.5px; color: var(--text-2); margin-top: 8px; min-height: 16px; }
.toast.bad, .bad { color: #dc2626; }
.foot-note { color: #64748b; font-size: 12.5px; margin-top: 16px; line-height: 1.7; }
</style>
