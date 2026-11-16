<script setup lang="ts">
import { computed } from 'vue'
import NarrationVersions from './NarrationVersions.vue'
import { RotateCcw } from 'lucide-vue-next'
import { useGameSocket } from '@/composables/useGameSocket'
import { useNarrationRegeneration } from '@/composables/useNarrationRegeneration'

const props = defineProps<{ gameId?: string, disabled?: boolean, showLabel?: boolean, compact?: boolean, menu?: boolean }>()
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
    :role="menu ? 'menuitem' : undefined"
    :disabled="unavailable"
    :aria-busy="busy"
    aria-label="Regenerate last response"
    title="Regenerate last response (keeps the turn outcome)"
    class="flex shrink-0 items-center justify-center gap-2 text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed"
    :class="menu ? 'action-menu-item' : compact ? 'px-3 py-1.5 rounded-xl border border-slate-700/80 bg-slate-900/90 hover:border-amber-400 font-bold' : 'min-w-9 h-9 px-2 rounded-lg hover:bg-slate-700/70'"
    @click="regenerate"
  >
    <RotateCcw :size="compact || menu ? 15 : 18" :class="{ 'animate-spin': busy, 'text-amber-300': menu }" />
    <span v-if="menu" class="action-menu-copy"><span class="action-menu-title">Rewrite text</span><span class="action-menu-description">Rephrase the response, keeping its outcome</span></span>
    <span v-else-if="showLabel" class="text-xs" :class="{ 'uppercase tracking-wider': compact }">{{ compact ? 'Rewrite' : 'Rewrite response' }}</span>
  </button>
  <NarrationVersions :game-id="gameId" :disabled="disabled || busy" :menu="menu" />
</template>
