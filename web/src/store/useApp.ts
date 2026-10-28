import { computed, ref } from 'vue';
import { defineStore } from 'pinia';
import { api, PAGES_MODE } from '@/api/client';
import { guideOpen } from '@/api/static';
import type { AppInfo, KeyStatus } from '@/api/types';

export const useApp = defineStore('app', () => {
  const info = ref<AppInfo | null>(null);
  const key = ref<KeyStatus | null>(null);
  const keyDialogOpen = ref(false);

  async function init(): Promise<void> {
    try {
      info.value = await api.appinfo();
    } catch { /* 后端未就绪时静默，badge 留空 */ }
    if (!PAGES_MODE) void refreshKey();
  }

  async function refreshKey(): Promise<void> {
    try {
      key.value = await api.keyStatus();
    } catch { /* 忽略 */ }
  }

  const demo = computed(() => info.value?.demo ?? false);

  /** Pages 只读演示构建（静态数据源，操作引导本地运行） */
  const pagesDemo = computed(() => PAGES_MODE || info.value?.pages_demo === true);

  /** 顶栏数据源徽章：演示模式明示是真实数据快照（非实时），换 Key 即实时 */
  const badge = computed(() => {
    if (info.value?.demo) {
      const asOf = info.value.demo_as_of ? `（${info.value.demo_as_of}）` : '';
      const head = pagesDemo.value ? '只读演示 · 真实数据快照' : '演示模式 · 真实数据快照';
      return { text: `${head}${asOf} · 非实时`, cls: 'ok' };
    }
    if (key.value?.custom) return { text: '已用自己的 Key', cls: 'ok' };
    return null;
  });

  function openKeyDialog(): void {
    // Pages 只读演示没有后端可换 Key：引导本地运行完整工具
    if (pagesDemo.value) { guideOpen.value = true; return; }
    keyDialogOpen.value = true;
  }

  /** 演示模式下，这批持仓代码是否含快照外的标的（用于「换 Key」引导条） */
  function hasDemoOutside(codes: (string | null | undefined)[]): boolean {
    if (!demo.value) return false;
    const known = new Set((info.value?.demo_symbols ?? []).map((s) => s.code));
    if (!known.size) return false;
    return codes.some((c) => c && !known.has(c));
  }

  return {
    info, key, demo, badge, pagesDemo, keyDialogOpen, guideOpen,
    init, refreshKey, openKeyDialog, hasDemoOutside,
  };
});
