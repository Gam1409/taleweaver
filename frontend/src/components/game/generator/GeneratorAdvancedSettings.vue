<script setup lang="ts">
import AdventureRuleModeSelector from '@/components/create-adventure/AdventureRuleModeSelector.vue'
import { ref } from 'vue'
import { Layers, ChevronDown, ChevronUp } from 'lucide-vue-next'

import type { RuleMode } from '@/types'

const props = defineProps<{
  minScenes: number | null
  maxScenes: number | null
  minQuests: number | null
  maxQuests: number | null
  questGenerationEnabled: boolean
  minContainers: number | null
  maxContainers: number | null
  containerGenerationEnabled: boolean
  minTextLogs: number | null
  maxTextLogs: number | null
  textLogGenerationEnabled: boolean
  minAwards: number | null
  maxAwards: number | null
  awardGenerationEnabled: boolean
  ruleEnforcementMode: RuleMode
}>()

const emit = defineEmits<{
  (e: 'update:minScenes', val: number | null): void
  (e: 'update:maxScenes', val: number | null): void
  (e: 'update:minQuests', val: number | null): void
  (e: 'update:maxQuests', val: number | null): void
  (e: 'update:questGenerationEnabled', val: boolean): void
  (e: 'update:minContainers', val: number | null): void
  (e: 'update:maxContainers', val: number | null): void
  (e: 'update:containerGenerationEnabled', val: boolean): void
  (e: 'update:minTextLogs', val: number | null): void
  (e: 'update:maxTextLogs', val: number | null): void
  (e: 'update:textLogGenerationEnabled', val: boolean): void
  (e: 'update:minAwards', val: number | null): void
  (e: 'update:maxAwards', val: number | null): void
  (e: 'update:awardGenerationEnabled', val: boolean): void
  (e: 'update:ruleEnforcementMode', val: RuleMode): void
}>()

const isExpanded = ref(false)

function onNumberInput(e: Event, emitEvent: any, minLimit?: number, maxLimit?: number) {
  const target = e.target as HTMLInputElement
  const raw = target.value.trim()
  if (raw === '') {
    emitEvent(null)
  } else {
    let val = Number(raw)
    if (minLimit !== undefined) val = Math.max(minLimit, val)
    if (maxLimit !== undefined) val = Math.min(maxLimit, val)
    if (isNaN(val)) emitEvent(null)
    else emitEvent(val)
  }
}
</script>

<template>
  <div class="space-y-3">
    <!-- Accordion Trigger -->
    <button
      type="button"
      @click="isExpanded = !isExpanded"
      class="w-full py-2.5 px-3 rounded-xl bg-slate-950/30 hover:bg-slate-950/60 border border-white/5 text-xs font-bold text-slate-400 hover:text-cyan-400 flex items-center justify-between transition-all select-none"
    >
      <div class="flex items-center gap-2">
        <Layers class="w-3.5 h-3.5 text-cyan-400" />
        <span>{{ isExpanded ? 'Hide Advanced World Settings' : 'Show Advanced World Settings' }}</span>
      </div>
      <component :is="isExpanded ? ChevronUp : ChevronDown" class="w-4 h-4 text-slate-500" />
    </button>

    <!-- Expanded Body -->
    <div v-if="isExpanded" class="p-4 sm:p-5 bg-slate-950/50 border border-white/5 rounded-2xl space-y-5 animate-fade-in">
      <AdventureRuleModeSelector :model-value="ruleEnforcementMode" @update:model-value="emit('update:ruleEnforcementMode', $event)" />

      <!-- Bounds Configuration -->
      <div class="space-y-3 pt-1">
        <span class="block text-[10px] font-black uppercase tracking-widest text-slate-400">
          World Generation Bounds
        </span>

        <!-- Scene Count Grid -->
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
          <div>
            <label class="block text-[10px] font-bold text-slate-400 mb-1">Min Scenes</label>
            <input
              :value="props.minScenes"
              @input="onNumberInput($event, (v: any) => emit('update:minScenes', v), 1, 15)"
              type="number"
              min="1"
              max="15"
              placeholder="Auto"
              class="w-full px-3 py-2 bg-slate-900 border border-slate-700/80 rounded-lg text-white text-xs font-bold outline-none focus:border-cyan-500"
            />
          </div>
          <div>
            <label class="block text-[10px] font-bold text-slate-400 mb-1">Max Scenes</label>
            <input
              :value="props.maxScenes"
              @input="onNumberInput($event, (v: any) => emit('update:maxScenes', v), 1, 20)"
              type="number"
              min="1"
              max="20"
              placeholder="Auto"
              class="w-full px-3 py-2 bg-slate-900 border border-slate-700/80 rounded-lg text-white text-xs font-bold outline-none focus:border-cyan-500"
            />
          </div>
          <div v-if="ruleEnforcementMode !== 'vn'">
            <label class="block text-[10px] font-bold text-slate-400 mb-1">Min Sidequests</label>
            <input
              :value="props.minQuests"
              @input="onNumberInput($event, (v: any) => emit('update:minQuests', v), 0, 10)"
              type="number"
              min="0"
              max="10"
              placeholder="Auto"
              class="w-full px-3 py-2 bg-slate-900 border border-slate-700/80 rounded-lg text-white text-xs font-bold outline-none focus:border-cyan-500"
            />
          </div>
          <div v-if="ruleEnforcementMode !== 'vn'">
            <label class="block text-[10px] font-bold text-slate-400 mb-1">Max Sidequests</label>
            <input
              :value="props.maxQuests"
              @input="onNumberInput($event, (v: any) => emit('update:maxQuests', v), 0, 10)"
              type="number"
              min="0"
              max="10"
              placeholder="Auto"
              class="w-full px-3 py-2 bg-slate-900 border border-slate-700/80 rounded-lg text-white text-xs font-bold outline-none focus:border-cyan-500"
            />
          </div>
        </div>
      </div>

      <!-- Feature Toggles -->
      <div class="space-y-2 pt-2 border-t border-white/5">
        <span class="block text-[10px] font-black uppercase tracking-widest text-slate-400">
          Content Modules
        </span>
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
          <label v-if="ruleEnforcementMode !== 'vn'" class="flex items-center gap-2 p-2 rounded-lg bg-slate-900/60 border border-white/5 text-xs font-semibold text-slate-300 cursor-pointer hover:border-white/10 select-none">
            <input
              type="checkbox"
              :checked="props.questGenerationEnabled"
              @change="emit('update:questGenerationEnabled', ($event.target as HTMLInputElement).checked)"
              class="rounded bg-slate-800 border-slate-700 text-cyan-500 focus:ring-0"
            />
            <span>Sidequests</span>
          </label>

          <label class="flex items-center gap-2 p-2 rounded-lg bg-slate-900/60 border border-white/5 text-xs font-semibold text-slate-300 cursor-pointer hover:border-white/10 select-none">
            <input
              type="checkbox"
              :checked="props.containerGenerationEnabled"
              @change="emit('update:containerGenerationEnabled', ($event.target as HTMLInputElement).checked)"
              class="rounded bg-slate-800 border-slate-700 text-cyan-500 focus:ring-0"
            />
            <span>Containers</span>
          </label>

          <label class="flex items-center gap-2 p-2 rounded-lg bg-slate-900/60 border border-white/5 text-xs font-semibold text-slate-300 cursor-pointer hover:border-white/10 select-none">
            <input
              type="checkbox"
              :checked="props.textLogGenerationEnabled"
              @change="emit('update:textLogGenerationEnabled', ($event.target as HTMLInputElement).checked)"
              class="rounded bg-slate-800 border-slate-700 text-cyan-500 focus:ring-0"
            />
            <span>Lore & Logs</span>
          </label>

          <label v-if="ruleEnforcementMode !== 'vn'" class="flex items-center gap-2 p-2 rounded-lg bg-slate-900/60 border border-white/5 text-xs font-semibold text-slate-300 cursor-pointer hover:border-white/10 select-none">
            <input
              type="checkbox"
              :checked="props.awardGenerationEnabled"
              @change="emit('update:awardGenerationEnabled', ($event.target as HTMLInputElement).checked)"
              class="rounded bg-slate-800 border-slate-700 text-cyan-500 focus:ring-0"
            />
            <span>Awards</span>
          </label>
        </div>
      </div>
    </div>
  </div>
</template>
