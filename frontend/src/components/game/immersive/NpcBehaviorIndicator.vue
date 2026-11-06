<script setup lang="ts">
import { useNpcBehaviorStatus } from '@/composables/useNpcBehaviorStatus'
const props = defineProps<{ sessionId?: string }>()
const state = useNpcBehaviorStatus(() => props.sessionId)
</script>

<template>
  <p
    v-if="state?.mode === 'live'"
    role="status"
    class="mt-1 text-[10px] leading-tight"
    :class="state.quality === 'simplified' ? 'text-amber-300' : 'text-slate-400'"
    :title="
      state.quality === 'simplified'
        ? 'The story continues with the last confirmed character identity. New psychological updates were not confirmed for this turn.'
        : 'Optional NPC character and memory guidance is enabled.'
    "
  >
    NPC Personality{{ state.quality === 'simplified' ? ': simplified RP' : '' }} · v{{
      state.module_version
    }}
    <span v-if="state.cooldown_remaining">
      · checking again after {{ state.cooldown_remaining }} turns</span
    >
  </p>
</template>
