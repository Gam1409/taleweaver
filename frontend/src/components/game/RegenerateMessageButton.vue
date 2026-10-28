<script setup lang="ts">
import { computed } from 'vue'
import { RotateCcw } from 'lucide-vue-next'
import { useGameSocket } from '@/composables/useGameSocket'
import { useNarrationRegeneration } from '@/composables/useNarrationRegeneration'

const props = defineProps<{ gameId?: string, disabled?: boolean }>()
const socket = useGameSocket()
const { regenerate, busy, canRegenerate } = useNarrationRegeneration(
  () => props.gameId,
  socket,
)
const unavailable = computed(() => props.disabled || !canRegenerate.value)
</script>

<template>
  <button
    type="button"
    :disabled="unavailable"
    :aria-busy="busy"
    aria-label="Regenerate last response"
    title="Regenerate last response (keeps the turn outcome)"
    class="flex shrink-0 items-center justify-center w-9 h-9 ml-2 rounded-lg text-slate-300 hover:bg-slate-700/70 disabled:opacity-40 disabled:cursor-not-allowed"
    @click="regenerate"
  >
    <RotateCcw :size="18" :class="{ 'animate-spin': busy }" />
  </button>
</template>
