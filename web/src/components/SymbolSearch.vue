<script setup lang="ts">
/* 股票搜索联想：收息佬与波段共用（wmshare 离线代码目录，后端 /api/symbols）。
   交互同旧版：200ms 防抖、↑↓ 选择、Enter 取 active 项；无联想时
   A 股 6 位代码回车直加（emit raw）。 */
import { onBeforeUnmount, onMounted, ref } from 'vue';
import { api } from '@/api/client';
import type { SymbolItem } from '@/api/types';

const props = withDefaults(defineProps<{
  market?: string;
  endpoint?: 'symbols' | 'bigly';
  placeholder?: string;
  /** 初始显示文本（如波段页默认 600519） */
  initialText?: string;
  /** 选中后输入框保留代码（波段页行为）；否则清空（收息佬行为） */
  keepPicked?: boolean;
}>(), {
  market: 'cn',
  endpoint: 'symbols',
  placeholder: '试试输入：茅台、长江电力、00700、gzmt',
  initialText: '',
  keepPicked: false,
});

const emit = defineEmits<{
  pick: [item: SymbolItem];
  raw: [code: string];
}>();

const input = ref<HTMLInputElement | null>(null);
const q = ref(props.initialText || '');
const results = ref<SymbolItem[]>([]);
const asOf = ref<string | null>(null);
const activeIdx = ref(0);
const dropdownOpen = ref(false);
const box = ref<HTMLDivElement | null>(null);

let timer: ReturnType<typeof setTimeout> | null = null;

async function query(text: string): Promise<void> {
  try {
    const fn = props.endpoint === 'bigly' ? api.biglySymbols : api.symbols;
    const d = await fn(text, props.market);
    results.value = d.results || [];
    asOf.value = d.as_of || null;
    activeIdx.value = 0;
    dropdownOpen.value = true;
  } catch { /* 搜索失败静默 */ }
}

function onInput(): void {
  const text = q.value.trim();
  if (timer) clearTimeout(timer);
  if (!text) { dropdownOpen.value = false; return; }
  timer = setTimeout(() => void query(text), 200);
}

function pick(item: SymbolItem): void {
  emit('pick', item);
  q.value = props.keepPicked ? item.code : '';
  dropdownOpen.value = false;
  input.value?.focus();
}

function onKeydown(e: KeyboardEvent): void {
  if (!dropdownOpen.value || !results.value.length) {
    if (e.key === 'Enter' && /^\d{6}$/.test(q.value.trim())) {
      e.preventDefault();
      emit('raw', q.value.trim());
      q.value = '';
    }
    return;
  }
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    activeIdx.value = (activeIdx.value + 1) % results.value.length;
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    activeIdx.value = (activeIdx.value - 1 + results.value.length) % results.value.length;
  } else if (e.key === 'Enter') {
    e.preventDefault();
    pick(results.value[activeIdx.value] || results.value[0]);
  } else if (e.key === 'Escape') {
    dropdownOpen.value = false;
  }
}

function onDocClick(e: MouseEvent): void {
  if (box.value && !box.value.contains(e.target as Node)) dropdownOpen.value = false;
}

onMounted(() => document.addEventListener('click', onDocClick));
onBeforeUnmount(() => document.removeEventListener('click', onDocClick));
</script>

<template>
  <div ref="box" class="search-box">
    <input ref="input" v-model="q" autocomplete="off" spellcheck="false"
           :placeholder="placeholder" @input="onInput" @keydown="onKeydown">
    <div v-if="dropdownOpen" class="sym-dropdown">
      <template v-if="results.length">
        <div v-for="(it, i) in results" :key="it.code" class="sym-item"
             :class="{ active: i === activeIdx }" @mousedown.prevent="pick(it)">
          <span class="sym-code">{{ it.code }}</span>
          <span class="sym-name">{{ it.name }}</span>
        </div>
      </template>
      <div v-else class="sym-empty">无匹配；A 股可直接回车输入 6 位代码</div>
      <div v-if="asOf && results.length" class="sym-fresh">代码目录快照 {{ asOf }}</div>
    </div>
  </div>
</template>
