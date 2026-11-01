<script setup lang="ts">
import type { PresetWorkspace } from '@/services/comfyPresetDraft'
defineProps<{ workspace: PresetWorkspace }>()
const emit = defineEmits<{
  (event: 'select', id: string): void
  (event: 'rename', value: string): void
  (event: 'remove-draft'): void
  (event: 'configure'): void
}>()
</script>
<template>
  <div class="grid items-start gap-5 lg:grid-cols-[minmax(0,1.7fr)_minmax(16rem,1fr)]">
    <div class="grid gap-3 sm:grid-cols-2">
      <button
        v-for="(preset, key) in workspace.presets"
        :key="key"
        type="button"
        :aria-pressed="workspace.selectedId === key"
        class="min-w-0 rounded-xl border p-4 text-left transition-colors"
        :class="
          workspace.selectedId === key
            ? 'border-cyan-500/60 bg-cyan-400/10 ring-1 ring-cyan-500/20'
            : 'border-slate-700 bg-slate-950/40 hover:border-slate-500'
        "
        @click="emit('select', String(key))"
      >
        <span class="block truncate text-sm font-semibold text-white">{{
          preset.name || 'Unnamed preset'
        }}</span
        ><span class="mt-2 block text-xs text-slate-400"
          >{{ preset.prompt_rules?.format || 'No prompt template' }} ·
          {{ preset.generate ? 'Base workflow ready' : 'Workflow needed' }}</span
        ><span
          class="mt-3 inline-block rounded-md bg-slate-800 px-2 py-1 text-[11px] text-slate-300"
          >{{ preset.reference ? 'Reference supported' : 'Text to image' }}</span
        >
      </button>
    </div>
    <div class="space-y-4 rounded-xl border border-slate-700 bg-slate-950/40 p-5">
      <label class="block text-sm font-medium"
        >Preset name<input
          :value="workspace.presets[workspace.selectedId]?.name"
          @input="emit('rename', ($event.target as HTMLInputElement).value)"
          maxlength="120"
          class="mt-2 block w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2.5 text-white"
      /></label>
      <button
        v-if="
          !workspace.baseline.comfyui_presets?.[workspace.selectedId] &&
          Object.keys(workspace.presets).length > 1
        "
        type="button"
        class="text-xs text-rose-300 underline"
        @click="emit('remove-draft')"
      >
        Remove unsaved preset
      </button>
      <p class="text-xs leading-relaxed text-slate-400">
        Switching presets keeps your edits in this window. Duplicate a preset to customize it
        without changing other profiles or stories that use the original.
      </p>
      <button
        type="button"
        class="w-full rounded-lg bg-cyan-700 px-4 py-2.5 text-sm font-medium text-white hover:bg-cyan-600"
        @click="emit('configure')"
      >
        Configure workflow
      </button>
    </div>
  </div>
</template>
