<script setup lang="ts">
defineProps<{
  enabled: boolean
  sessionId?: string
}>()
</script>

<template>
  <p
    v-if="enabled && sessionId"
    class="mt-0.5 text-[9px] leading-tight font-mono text-slate-500 break-all select-text"
    aria-label="Session UUID"
  >{{ sessionId }}</p>
</template>
