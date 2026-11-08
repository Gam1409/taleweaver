<script setup lang="ts">
import { npcBehaviorExplanation, useNpcBehaviorStatus } from '@/composables/useNpcBehaviorStatus'
const props = defineProps<{ sessionId?: string }>()
const state = useNpcBehaviorStatus(() => props.sessionId)
</script>

<template>
  <p
    v-if="state?.mode === 'live'"
    role="status"
    class="mt-1 text-[10px] leading-tight"
    :class="state.quality === 'simplified' ? 'text-amber-300' : 'text-slate-400'"
    :title="npcBehaviorExplanation(state)"
    :aria-label="npcBehaviorExplanation(state)"
    tabindex="0"
  >
    NPC Personality{{ state.quality === 'simplified' ? ': simplified RP' : '' }} · v{{
      state.module_version
    }}
    <span v-if="state.cooldown_remaining">
      · checking again after {{ state.cooldown_remaining }} {{ state.cooldown_remaining === 1 ? 'turn' : 'turns' }}</span
    >
  </p>
</template>
