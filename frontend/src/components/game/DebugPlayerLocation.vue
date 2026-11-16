<script setup lang="ts">
import { MapPin } from 'lucide-vue-next'
const props = defineProps<{
  sceneId: string
  currentSceneId: string
  busy: boolean
}>()
const emit = defineEmits<{ command: [value: string] }>()
function move() {
  if (props.busy || !props.sceneId || props.sceneId === props.currentSceneId) return
  emit('command', `/debug move_player ${JSON.stringify(props.sceneId)}`)
}
</script>

<template>
  <div class="my-3 space-y-2">
    <button type="button" class="inline-flex items-center gap-2 rounded-xl border border-cyan-500/40 bg-cyan-500/10 px-3 py-2 text-xs font-bold text-cyan-300 hover:bg-cyan-500/20 disabled:opacity-40" :disabled="busy || !sceneId || sceneId === currentSceneId" @click="move">
      <MapPin class="h-4 w-4" aria-hidden="true" />
      {{ sceneId === currentSceneId ? 'Player is here' : 'Move player here' }}
    </button>
    <p class="text-[11px] leading-relaxed text-slate-400">Manual session correction. Bypasses travel checks; NPCs, inventory and story time stay unchanged.</p>
  </div>
</template>
