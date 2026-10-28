<script setup lang="ts">
import { computed } from 'vue';
import { useApp } from '@/store/useApp';

const app = useApp();

/** 快照覆盖的示例标的文案：「贵州茅台(600519)」 */
const symbolsText = computed(() => {
  const syms = app.info?.demo_symbols ?? [];
  if (!syms.length) return '';
  return `示例仅含 ${syms.map((s) => `${s.name}(${s.code})`).join('、')}`;
});

const ctaText = computed(() =>
  app.pagesDemo ? '📦 本地运行完整版' : '🔑 换 Key 解锁实时');
</script>

<template>
  <div v-if="app.demo" class="demo-banner">
    <span class="tag">{{ app.pagesDemo ? '只读演示' : '演示数据' }}</span>
    <span class="txt">
      真实数据的历史快照<template v-if="app.info?.demo_as_of">，截止
        <strong>{{ app.info.demo_as_of }}</strong></template>，非实时<template v-if="symbolsText">；{{ symbolsText }}</template>。<template v-if="app.pagesDemo">本地运行完整版，页面内粘贴 Key 即变实时全市场（无需环境变量）。</template><template v-else>配置自己的
        Key 即变实时工具，无需重启。</template>
    </span>
    <button class="cta" @click="app.openKeyDialog()">{{ ctaText }}</button>
  </div>
</template>

<style scoped>
.demo-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  max-width: 1080px;
  margin: 12px auto 0;
  padding: 9px 14px;
  border: 1px solid #fde68a;          /* amber-200 */
  border-radius: 10px;
  background: var(--warn-soft);
  font-size: 13px;
}
.tag {
  flex: none;
  padding: 2px 9px;
  border-radius: 999px;
  background: var(--warn);
  color: #fff;
  font-size: 11.5px;
  font-weight: 600;
}
.txt { color: var(--text-2); }
.cta {
  margin-left: auto;
  flex: none;
  background: var(--accent);
  border: 1px solid var(--accent);
  color: #fff;
  font-weight: 560;
  padding: 5px 12px;
  font-size: 12.5px;
}
.cta:hover { background: var(--accent-hover); border-color: var(--accent-hover); }
</style>
