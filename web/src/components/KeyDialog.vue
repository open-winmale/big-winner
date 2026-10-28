<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { api, ApiError } from '@/api/client';
import { useApp } from '@/store/useApp';
import Modal from '@/components/ui/Modal.vue';

const app = useApp();
const emit = defineEmits<{ close: [] }>();

const open = computed({
  get: () => app.keyDialogOpen,
  set: (v: boolean) => { app.keyDialogOpen = v; },
});

const status = ref<{ custom: boolean; demo: boolean } | null>(null);
const clientId = ref('');
const secret = ref('');
const showSecret = ref(false);
const saving = ref(false);
const result = ref<{ ok: boolean; text: string } | null>(null);

watch(open, async (v) => {
  if (!v) return;
  result.value = null;
  status.value = null;
  try { status.value = await api.keyStatus(); } catch { /* 忽略 */ }
});

async function save(): Promise<void> {
  const cid = clientId.value.trim();
  const sec = secret.value.trim();
  if (!cid || !sec) {
    result.value = { ok: false, text: 'client_id 与 api-key 都必填' };
    return;
  }
  saving.value = true;
  result.value = null;
  const wasDemo = !!app.info?.demo;
  try {
    const r = await api.keySave({ client_id: cid, client_secret: sec });
    await app.refreshKey();
    try { app.info = await api.appinfo(); } catch { /* 忽略 */ }
    result.value = { ok: true, text: r.message };
    if (wasDemo && app.info && !app.info.demo) {
      // 演示模式已热切换为实时数据：整页刷新，让所有模块按实时重建
      setTimeout(() => window.location.reload(), 900);
      return;
    }
  } catch (e) {
    result.value = {
      ok: false,
      text: e instanceof ApiError ? e.message : String(e),
    };
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <Modal v-model:open="open" title="wmshare 数据 Key" width="560px"
         @close="emit('close')">
    <p class="hint-line">
      <template v-if="status?.demo">当前是演示模式：页面是真实数据的静态快照（截至 {{ app.info?.demo_as_of || '快照日' }}），非实时。换 Key 验证通过后<strong>立即切换为实时数据，无需重启</strong>。</template>
      <template v-else-if="status?.custom">✓ 正在使用你自己的 Key（额度独立）。可随时换 Key：验证通过立即热切换，无需重启。</template>
      <template v-else>当前没有检测到自己的 Key。填入并验证通过后立即生效（额度独立）。</template>
    </p>
    <p class="muted" style="margin:0 0 10px;font-size:12.5px">
      到 <a href="https://open.winmale.com" target="_blank" rel="noopener">open.winmale.com</a>
      微信扫码登录 →「我的」→「开放平台」→「我的应用」→ 复制 client_id 与 api-key。
      保存后<strong>立即验证并热切换</strong>，无需重启（Key 只存本机
      ~/.wmshare/credentials.env，权限 600，不会回显）。
    </p>
    <div style="display:flex;flex-direction:column;gap:8px">
      <input v-model="clientId" placeholder="client_id" autocomplete="off" spellcheck="false">
      <div style="display:flex;gap:8px">
        <input v-model="secret" :type="showSecret ? 'text' : 'password'"
               placeholder="api-key（client_secret）" autocomplete="off">
        <button class="ghost" style="flex:none" @click="showSecret = !showSecret">
          {{ showSecret ? '隐藏' : '显示' }}
        </button>
      </div>
      <div class="toolbar">
        <button class="primary" :disabled="saving" @click="save">
          {{ saving ? '验证中…'
            : (result?.ok ? (status?.demo ? '已保存 ✓' : '已生效 ✓')
              : (status?.custom ? '验证并换 Key' : '验证并保存')) }}
        </button>
        <span class="muted" style="font-size:12px">非商业用途免费</span>
      </div>
    </div>
    <div v-if="result" style="margin-top:10px">
      <span v-if="result.ok" class="badge ok">{{ result.text }}</span>
      <div v-else class="error">{{ result.text }}</div>
    </div>
  </Modal>
</template>

<style scoped>
.hint-line { font-size: 12px; color: var(--text-3); margin: 0 0 10px; }
</style>
