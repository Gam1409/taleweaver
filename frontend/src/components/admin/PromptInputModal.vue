<script setup lang="ts">
import { ref } from 'vue'
import type { CatalogTile } from '@/types'

const props = defineProps<{
  isOpen: boolean
  data: { type: 'styles' | 'tones', item: CatalogTile, index: number } | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'generate', payload: { type: 'styles' | 'tones', item: CatalogTile, index: number, prompt: string }): void
}>()

const customPrompt = ref('')

const INSPIRATION_CHIPS = [
  'Dark Fantasy',
  'Oil Painting',
  'Cinematic Rim Lighting',
  'Moody Watercolor',
  'Gothic Cathedral',
  'Graphic Novel Ink',
  'Eerie Volumetric Fog',
  'Detailed Concept Art'
]

const addChip = (chip: string) => {
  if (!customPrompt.value.trim()) {
    customPrompt.value = chip
  } else if (!customPrompt.value.includes(chip)) {
    customPrompt.value = `${customPrompt.value.trim()}, ${chip}`
  }
}

const handleGenerate = () => {
  if (props.data && customPrompt.value.trim()) {
    emit('generate', { 
      type: props.data.type, 
      item: props.data.item, 
      index: props.data.index, 
      prompt: customPrompt.value.trim()
    })
    customPrompt.value = ''
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="isOpen" class="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <div class="absolute inset-0 bg-black/85 backdrop-blur-sm" @click="emit('close')"></div>
      <div class="relative w-full max-w-lg bg-slate-900 border border-slate-800 rounded-3xl shadow-2xl p-6 sm:p-8 animate-fade-in">
        <!-- Header -->
        <div class="flex items-center justify-between pb-4 mb-4 border-b border-slate-800">
          <div class="flex items-center gap-3">
            <div class="w-10 h-10 rounded-xl bg-blue-500/10 text-blue-400 border border-blue-500/20 flex items-center justify-center text-lg">
              <i class="ra ra-quill-ink"></i>
            </div>
            <div>
              <h2 class="text-lg font-bold text-white">Custom Tile Artwork</h2>
              <p class="text-xs text-slate-400">Generate tailored cover art for <strong>{{ data?.item.name }}</strong>.</p>
            </div>
          </div>
          <button @click="emit('close')" class="p-1.5 text-slate-500 hover:text-white rounded-lg transition-colors">
            <i class="ra ra-cancel text-sm"></i>
          </button>
        </div>

        <!-- Prompt Textarea -->
        <div class="space-y-2 mb-4">
          <div class="flex items-center justify-between">
            <label class="block text-xs font-bold text-slate-400 uppercase tracking-wider">
              Visual Prompt
            </label>
            <span class="text-[10px] font-mono text-slate-500">{{ customPrompt.length }} characters</span>
          </div>
          <textarea 
            v-model="customPrompt" 
            rows="4" 
            placeholder="e.g. A solitary hooded wanderer gazing over a misty crag at sunrise, moody oil painting with dramatic rim lighting..."
            class="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-white text-xs placeholder-slate-600 focus:ring-2 focus:ring-blue-500/50 outline-none resize-none leading-relaxed font-sans"
            @keydown.enter.prevent="customPrompt.trim() && handleGenerate()"
          ></textarea>
        </div>

        <!-- Inspiration Chips -->
        <div class="mb-6 space-y-1.5">
          <span class="text-[10px] font-bold uppercase tracking-wider text-slate-500">Quick Style Modifiers:</span>
          <div class="flex flex-wrap gap-1.5">
            <button
              v-for="chip in INSPIRATION_CHIPS"
              :key="chip"
              type="button"
              @click="addChip(chip)"
              class="px-2.5 py-1 bg-slate-950 hover:bg-slate-800 border border-slate-800 hover:border-slate-700 text-slate-400 hover:text-blue-300 rounded-lg text-[11px] transition-all font-mono"
            >
              + {{ chip }}
            </button>
          </div>
        </div>

        <!-- Actions -->
        <div class="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
          <button 
            type="button"
            @click="emit('close')" 
            class="px-5 py-2.5 rounded-xl border border-slate-800 text-slate-400 hover:text-white hover:bg-slate-800 text-xs font-bold transition-all"
          >
            Cancel
          </button>
          <button 
            type="button"
            @click="handleGenerate" 
            :disabled="!customPrompt.trim()"
            class="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-bold transition-all shadow-lg shadow-blue-900/20 disabled:opacity-50 flex items-center gap-2 cursor-pointer"
          >
            <i class="ra ra-cycle"></i>
            <span>Generate Artwork</span>
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.animate-fade-in {
  animation: fadeIn 0.3s ease-out;
}
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
