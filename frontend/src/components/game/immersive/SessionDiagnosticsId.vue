<script setup lang="ts">
import SessionStateChecks from './SessionStateChecks.vue'
defineProps<{
  enabled: boolean
  sessionId?: string
}>()
</script>

<template>
  <p
    v-if="enabled && sessionId"
    class="mt-0.5 text-[9px] leading-tight font-mono text-slate-500 truncate select-text"
    :title="sessionId"
    aria-label="Session UUID"
  >
    {{ sessionId }}
  </p>
  <SessionStateChecks v-if="sessionId" :session-id="sessionId" />
</template>
