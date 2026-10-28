<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { api } from '@/api/client';
import type { ToolInfo } from '@/api/types';

const tools = ref<ToolInfo[]>([]);
const demo = ref(false);

const SLUG_META: Record<string, { desc: string; to: string }> = {
  'dividend-xray': {
    to: '/shouxi',
    desc: '攒股收息驾驶舱：分红日历、每票持续性分析、税后记账与 CSV 导出；' +
      '打开即看未来除权/到账，A 股 / 港股持仓通用。',
  },
  bigly: {
    to: '/bigly',
    desc: '估值通道 · 买卖点参考 · 拨测回看：PE/PB 通道分位定档，' +
      '推荐区间/自定义区间与多轮进出回放；统计描述与历史回放，买卖点由你自己设定。',
  },
  screener: {
    to: '/screener',
    desc: '预置策略 · 一键全市场选股：格雷厄姆、高股息、破净、派息健康等策略' +
      '一句话讲清口径，清单数字即入选证据，可一键加入观察池跟踪。选股结果 ≠ 推荐。',
  },
};

onMounted(async () => {
  try {
    const d = await api.tools();
    tools.value = d.tools || [];
    demo.value = d.demo;
  } catch { /* 后端未就绪：给静态卡 */ }
});
</script>

<template>
  <main class="wrap">
    <div class="page-head">
      <h1>给攒股人的三个小工具：收息透视 · 估值波段 · 条件选股</h1>
      <p>一组围绕 A 股与港股持仓、分红的小工具。真实数据来自
        <a href="https://github.com/open-winmale/wmshare" target="_blank" rel="noopener">wmshare</a>，
        只做事实与统计聚合，不提供任何买卖建议。</p>
    </div>

    <div class="tool-grid">
      <router-link v-for="t in tools" :key="t.slug" class="tool-card"
                   :to="SLUG_META[t.slug]?.to || '/'">
        <h3>{{ t.title }}</h3>
        <p>{{ SLUG_META[t.slug]?.desc || t.tagline }}</p>
        <span class="badge ok">{{ demo ? '演示数据' : '真实数据' }}</span>
      </router-link>
    </div>

    <div v-if="!tools.length" class="tool-grid">
      <router-link class="tool-card" to="/shouxi">
        <h3>收息佬</h3>
        <p>攒股收息驾驶舱：分红日历、每票持续性分析、税后记账与 CSV 导出。</p>
      </router-link>
      <router-link class="tool-card" to="/bigly">
        <h3>波段</h3>
        <p>估值通道 · 买卖点参考 · 拨测回看。</p>
      </router-link>
      <router-link class="tool-card" to="/screener">
        <h3>选股</h3>
        <p>预置策略 · 一键全市场选股，清单数字即入选证据。</p>
      </router-link>
    </div>

    <div class="footer">
      <div>本工具集仅做数据统计聚合，不构成任何投资建议；数据来自 wmshare，最终以上市公司公告为准；历史分红不代表未来。</div>
      <div style="margin-top:6px">工具代码 MIT 开源；依赖的 wmshare 为 PolyForm Noncommercial 许可，仅限非商业使用。</div>
    </div>
  </main>
</template>
