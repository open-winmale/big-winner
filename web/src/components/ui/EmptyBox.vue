<script setup lang="ts">
/* 通用空态 / 加载骨架 */
defineProps<{ skeleton?: number }>();
</script>

<template>
  <div class="empty">
    <slot />
    <template v-if="skeleton">
      <div v-for="i in skeleton" :key="i" class="skeleton" style="margin:9px 0"></div>
    </template>
  </div>
</template>
