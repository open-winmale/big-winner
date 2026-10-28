<script setup lang="ts">
import { useApp } from '@/store/useApp';

const app = useApp();
</script>

<template>
  <header class="topbar">
    <div class="topbar-inner">
      <router-link to="/" class="brand" style="color:inherit;text-decoration:none">
        收息佬<span class="dot">·</span>工具集
      </router-link>
      <span class="spacer"></span>
      <span v-if="app.badge" class="meta">
        <span class="badge" :class="app.badge.cls">{{ app.badge.text }}</span>
      </span>
      <button class="ghost" style="padding:4px 10px;font-size:12.5px"
              @click="app.openKeyDialog()">数据源 Key</button>
    </div>
  </header>
</template>
