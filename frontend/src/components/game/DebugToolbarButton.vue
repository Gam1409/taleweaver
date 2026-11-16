<script setup lang="ts">
defineProps<{ disabled?: boolean }>()
defineEmits<{ click: [] }>()
</script>
<template>
  <button
    type="button"
    :disabled="disabled"
    class="inline-flex h-9 shrink-0 items-center justify-center rounded-xl bg-transparent px-3.5 font-sans text-xs font-bold uppercase tracking-wider gap-2 text-slate-400 transition-colors hover:bg-slate-800 hover:text-slate-200 disabled:cursor-not-allowed disabled:opacity-40"
    @click="$emit('click')"
  >
    <slot />
  </button>
</template>
