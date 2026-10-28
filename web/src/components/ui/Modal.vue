<script setup lang="ts">
defineProps<{ open: boolean; title?: string; hint?: string; width?: string }>();
/* close 给 :open/@close 用法；update:open 让 v-model:open 生效（二者都发，
   否则 v-model 用法的关闭链会断在父组件没监听 close 的地方） */
const emit = defineEmits<{ close: []; 'update:open': [boolean] }>();
function close(): void {
  emit('close');
  emit('update:open', false);
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="diag-overlay" @click.self="close()">
      <div class="diag-modal card" role="dialog" aria-modal="true"
           :style="width ? `width:min(${width}, 100%)` : ''">
        <div class="card-head">
          <h2>{{ title }}</h2>
          <span v-if="hint" class="hint">{{ hint }}</span>
          <span class="spacer"></span>
          <button class="ghost" style="padding:4px 10px" @click="close()">关闭</button>
        </div>
        <slot />
      </div>
    </div>
  </Teleport>
</template>

