<script setup lang="ts">
import { computed, ref } from 'vue';
import { guideOpen } from '@/api/static';
import { useApp } from '@/store/useApp';
import Modal from '@/components/ui/Modal.vue';

const app = useApp();
const open = computed({
  get: () => guideOpen.value,
  set: (v: boolean) => { guideOpen.value = v; },
});

const asOf = computed(() => app.info?.demo_as_of ?? '快照日');

const CMD = `git clone https://github.com/open-winmale/big-winner.git
cd big-winner
PYTHONPATH=src python -m bigwinner.shouxi`;

const copied = ref(false);

async function copyCmd(): Promise<void> {
  try {
    await navigator.clipboard.writeText(CMD);
    copied.value = true;
    setTimeout(() => { copied.value = false; }, 1600);
  } catch { /* 剪贴板不可用时忽略 */ }
}
</script>

<template>
  <Modal v-model:open="open" title="完整体验请本地运行" width="600px">
    <p class="hint-line">
      当前是<strong>只读在线演示</strong>：真实数据的历史快照（截止 {{ asOf }}），
      示例仅含贵州茅台(600519)。自己的持仓、实时行情、记账计税、观察池同步
      都在本地完整版里。
    </p>
    <p class="muted" style="margin:0 0 8px;font-size:12.5px">
      三行命令启动（零依赖，开箱即演示模式，无需任何凭证）：
    </p>
    <div class="cmd-box">
      <pre>{{ CMD }}</pre>
      <button class="ghost" style="flex:none" @click="copyCmd">
        {{ copied ? '已复制 ✓' : '复制' }}
      </button>
    </div>
    <p class="muted" style="margin:10px 0 0;font-size:12.5px">
      启动后浏览器打开 <code>http://127.0.0.1:8787/</code>。
      要看<strong>实时全市场</strong>：安装
      <a href="https://github.com/open-winmale/wmshare" target="_blank" rel="noopener">wmshare</a>
      （<code>pip install -e ./wmshare</code>），页面右上角「数据源 Key」填入自己的
      AppID（<a href="https://open.winmale.com" target="_blank" rel="noopener">open.winmale.com</a>
      免费申请）——验证通过立即热切换，无需重启。
    </p>
    <div class="toolbar" style="margin-top:14px">
      <router-link to="/setup" style="font-size:13px">详细配置步骤 →</router-link>
    </div>
  </Modal>
</template>

<style scoped>
.hint-line { font-size: 13px; color: var(--text-2); margin: 0 0 12px; line-height: 1.7; }
.cmd-box {
  display: flex; gap: 8px; align-items: flex-start;
  background: var(--surface-2); border: 1px solid var(--line);
  border-radius: 10px; padding: 12px 14px;
}
.cmd-box pre {
  flex: 1; margin: 0; font-size: 12.5px; line-height: 1.7; overflow-x: auto;
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}
</style>
