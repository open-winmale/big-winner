<script setup lang="ts">
import { onMounted } from 'vue';
import { useApp } from '@/store/useApp';
import TopBar from '@/components/TopBar.vue';
import DemoBanner from '@/components/DemoBanner.vue';
import KeyDialog from '@/components/KeyDialog.vue';
import LocalGuideModal from '@/components/LocalGuideModal.vue';

const app = useApp();
onMounted(() => { void app.init(); });
</script>

<template>
  <TopBar />
  <DemoBanner />
  <router-view />
  <KeyDialog />
  <LocalGuideModal />
</template>
