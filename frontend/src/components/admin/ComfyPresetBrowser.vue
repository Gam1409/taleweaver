<script setup lang="ts">
import { computed, reactive } from 'vue'
import { imagePurposes } from '@/services/imagePurposes'
import { filterPresets } from '@/services/comfyLibrary'
import type { ComfyPreset } from '@/types/comfyui'
const props = defineProps<{ presets: Record<string, ComfyPreset>; selected?: string }>()
const emit = defineEmits<{ (event: 'select', id: string): void }>()
const filters = reactive({ query: '', task: '', reference: '' })
const entries = computed(() => filterPresets(props.presets, filters))
</script>
<template>
  <div class="space-y-4">
    <div class="grid gap-3 sm:grid-cols-3">
      <label class="text-xs text-slate-400"
        >Search<input
          v-model="filters.query"
          type="search"
          placeholder="Name, style or model family"
          class="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 p-2.5 text-sm text-white"
      /></label>
      <label class="text-xs text-slate-400"
        >Task<select
          v-model="filters.task"
          class="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 p-2.5 text-sm text-white"
        >
          <option value="">All tasks</option>
          <option v-for="task in imagePurposes" :key="task.id" :value="task.id">
            {{ task.label }}
          </option>
        </select></label
      >
      <label class="text-xs text-slate-400"
        >Reference support<select
          v-model="filters.reference"
          class="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 p-2.5 text-sm text-white"
        >
          <option value="">Any</option>
          <option value="yes">With reference</option>
          <option value="no">Without reference</option>
        </select></label
      >
    </div>
    <p v-if="!entries.length" role="status" class="py-6 text-sm text-slate-400">
      No matching presets. Change the filters or create a preset.
    </p>
    <div class="grid gap-3 sm:grid-cols-2">
      <button
        v-for="[id, preset] in entries"
        :key="id"
        type="button"
        :aria-pressed="selected === id"
        class="min-w-0 rounded-xl border p-4 text-left"
        :class="
          selected === id
            ? 'border-cyan-400 bg-cyan-400/10'
            : 'border-slate-700 bg-slate-950/40 hover:border-slate-500'
        "
        @click="emit('select', id)"
      >
        <span class="block break-words font-semibold text-white">{{ preset.name }}</span>
        <span class="mt-2 block text-xs text-slate-400"
          >{{ preset.prompt_rules?.template_id || 'Custom prompt' }} ·
          {{
            preset.reference?.bindings.image ? 'With / without reference' : 'Without reference'
          }}</span
        >
        <span class="mt-3 flex flex-wrap gap-1"
          ><span
            v-for="task in preset.purpose_tags"
            :key="task"
            class="rounded bg-cyan-950 px-2 py-1 text-xs text-cyan-200"
            >{{ imagePurposes.find(p => p.id === task)?.label ?? task }}</span
          ><span
            v-for="tag in preset.style_tags"
            :key="tag"
            class="rounded bg-slate-800 px-2 py-1 text-xs text-slate-300"
            >{{ tag }}</span
          ></span
        >
        <span v-if="!preset.purpose_tags?.length" class="mt-2 block text-xs text-slate-500"
          >No task labels</span
        >
      </button>
    </div>
  </div>
</template>
