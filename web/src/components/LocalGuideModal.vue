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
python run.py`;

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
  <Modal v-model:open="open" title="两步变实时：拿 AppID + 本地运行" width="600px">
    <p class="hint-line">
      当前是<strong>只读在线演示</strong>：真实数据的历史快照（截止 {{ asOf }}），
      示例仅含贵州茅台(600519)。自己的持仓、实时行情、记账计税、观察池同步
      都在本地完整版里。
    </p>

    <div class="step">
      <div class="step-no">1</div>
      <div class="step-body">
        <p style="margin:0">
          <strong>获取 AppID（免费）</strong>——
          <a href="https://open.winmale.com" target="_blank" rel="noopener">open.winmale.com</a>
          微信扫码登录 →「开放平台」→「我的应用」，复制 client_id 与 api-key
          （注册即送免费额度）。
        </p>
      </div>
    </div>

    <div class="step">
      <div class="step-no">2</div>
      <div class="step-body">
        <p style="margin:0 0 8px"><strong>本地运行完整版</strong>（三行命令，Windows / macOS / Linux 通用；macOS/Linux 无 <code>python</code> 命令时用 <code>python3</code>）：</p>
        <div class="cmd-box">
          <pre>{{ CMD }}</pre>
          <button class="ghost" style="flex:none" @click="copyCmd">
            {{ copied ? '已复制 ✓' : '复制' }}
          </button>
        </div>
        <p class="muted" style="margin:10px 0 0;font-size:12.5px">
          启动后浏览器打开 <code>http://127.0.0.1:8787/</code>，点右上角
          「数据源 Key」粘贴保存——<strong>验证通过立即实时全市场，全程无需环境变量</strong>。
          真实取数需安装
          <a href="https://github.com/open-winmale/wmshare" target="_blank" rel="noopener">wmshare</a>
          （<code>git clone https://github.com/open-winmale/wmshare && pip install -e ./wmshare</code>）。
        </p>
      </div>
    </div>

    <div class="toolbar" style="margin-top:14px">
      <router-link to="/setup" style="font-size:13px">详细配置步骤 →</router-link>
    </div>
  </Modal>
</template>

<style scoped>
.hint-line { font-size: 13px; color: var(--text-2); margin: 0 0 12px; line-height: 1.7; }
.step { display: flex; gap: 12px; margin: 14px 0; }
.step-no {
  flex: none; width: 24px; height: 24px; border-radius: 50%;
  background: var(--accent); color: #fff; font-weight: 640;
  display: flex; align-items: center; justify-content: center; font-size: 12.5px;
}
.step-body { flex: 1; font-size: 13px; color: var(--text-2); line-height: 1.7; }
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
