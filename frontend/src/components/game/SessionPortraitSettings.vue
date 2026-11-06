<script setup lang="ts">
import { useSessionPortraitSettings } from '@/composables/useSessionPortraitSettings'
import { Palette, MessageCircle } from 'lucide-vue-next'
const props = defineProps<{ sessionId: string }>()
const { draft, loaded, busy, error, load, save } = useSessionPortraitSettings(() => props.sessionId)
defineExpose({ save })
</script>

<template>
  <section class="space-y-4 rounded-2xl border border-white/10 bg-slate-950/40 p-4" aria-label="Portrait presentation">
    <label class="flex items-center gap-3 cursor-pointer">
      <Palette class="w-5 h-5 shrink-0 text-cyan-300" aria-hidden="true" />
      <span class="flex-1 text-sm font-bold text-slate-200">Палитра эмоций</span>
      <input v-model="draft.emotion_palette" type="checkbox" :disabled="!loaded || busy" class="accent-cyan-400 w-4 h-4" />
    </label>
    <p class="text-xs text-slate-400">A subtle portrait glow shows the dominant overall emotion assessed by the narrator. Its strength follows the emotion's intensity.</p>
    <label v-if="draft.emotion_palette" class="block text-xs text-slate-300">
      Glow brightness · {{ draft.brightness }}%
      <input v-model.number="draft.brightness" type="range" min="0" max="100" :disabled="!loaded || busy" class="block mt-2 w-full accent-cyan-400" />
    </label>
    <label class="flex items-center gap-3 cursor-pointer">
      <MessageCircle class="w-5 h-5 shrink-0 text-fuchsia-300" aria-hidden="true" />
      <span class="flex-1 text-sm font-bold text-slate-200">Мысли персонажей</span>
      <input v-model="draft.character_thoughts" type="checkbox" :disabled="!loaded || busy" class="accent-fuchsia-400 w-4 h-4" />
    </label>
    <p class="text-xs text-slate-400">Hover over or focus an NPC portrait to glimpse a short fictional thought. New replies supply the thought; older unassessed replies stay blank.</p>
    <p v-if="busy" role="status" class="text-xs text-slate-400">Loading portrait settings…</p>
    <div v-if="error" role="alert" class="text-xs text-rose-300">
      {{ error }}
      <button type="button" class="ml-2 underline rounded focus-visible:ring-2 focus-visible:ring-cyan-400" :disabled="busy" @click="load">Reload</button>
    </div>
  </section>
</template>
