<script setup lang="ts">
import { computed } from 'vue';
import { mktLabel } from '@/format';

const props = defineProps<{ market?: string | null }>();
const label = computed(() => mktLabel(props.market));
</script>

<template>
  <span class="chip-mkt" :class="`mkt-${market || 'cn'}`">{{ label }}</span>
</template>
