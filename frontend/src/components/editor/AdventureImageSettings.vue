<script setup lang="ts">
import { useAdventureImageSettings } from '@/composables/useAdventureImageSettings'

const props = defineProps<{
  adventureId: string
  targetType: string
  advanced: boolean
  reference: boolean
  disabled?: boolean
}>()
const emit = defineEmits<{ (e: 'busy', value: boolean): void }>()
const { data, source, busy, error, saved, reload, save } = useAdventureImageSettings(
  () => ({ adventureId: props.adventureId, targetType: props.targetType, advanced: props.advanced, reference: props.reference }),
  value => emit('busy', value),
)
</script>

<template>
  <section aria-label="Adventure image settings" class="space-y-3 rounded-2xl border border-cyan-500/20 bg-cyan-500/5 p-4">
    <h4 class="text-xs font-black uppercase tracking-widest text-cyan-300">Image settings for this adventure</h4>
    <p class="text-xs text-slate-400">Saved adventure choices can override global task presets. The test preset is separate.</p>
    <p v-if="busy" role="status" class="text-xs text-slate-300">Loading image settings...</p>
    <div v-if="data" class="flex flex-wrap items-end gap-3">
      <label class="min-w-0 flex-1 text-xs text-slate-300">Preset source
        <select v-model="source" :disabled="busy || disabled" class="mt-2 w-full rounded-lg border border-white/10 bg-slate-950 p-2 text-sm text-white disabled:opacity-50">
          <option value="current">Use current global settings</option>
          <option value="saved">Use saved adventure selection</option>
        </select>
      </label>
      <button type="button" :disabled="busy || disabled || source === data.source" class="rounded-xl bg-cyan-700 px-3 py-2 text-xs font-bold text-white disabled:opacity-40" @click="save">Apply image settings</button>
    </div>
    <div v-if="data?.effective" class="space-y-1 break-words text-xs text-slate-300">
      <p v-if="data.effective.error" role="alert" class="text-amber-300">{{ data.effective.error }}</p>
      <template v-else>
        <p>Active provider: <strong>{{ data.effective.provider }}</strong></p>
        <p v-if="data.effective.preset_name">Preset: <strong>{{ data.effective.preset_name }}</strong></p>
        <p v-if="data.effective.workflow_name">Workflow: {{ data.effective.workflow_name }} · {{ data.effective.variant }}</p>
        <p v-for="file in data.effective.models || []" :key="file.node + file.input">{{ file.loader }}: {{ file.file }}</p>
      </template>
    </div>
    <p v-if="saved" role="status" class="text-xs text-emerald-300">Saved. Future images use this source.</p>
    <p v-if="error" role="alert" class="text-xs text-rose-300">{{ error }} <button type="button" :disabled="busy || disabled" class="underline disabled:opacity-50" @click="reload">Retry image settings</button></p>
    <details class="text-xs text-slate-500"><summary class="cursor-pointer">Scope and saved choices</summary>
      <p class="mt-2">This applies to all image tasks in this adventure. Existing images and saved preset choices are kept. Existing sessions have their own image settings.</p>
    </details>
  </section>
</template>
