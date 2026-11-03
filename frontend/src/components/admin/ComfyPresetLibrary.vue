<script setup lang="ts">
import { computed } from 'vue'
import { imagePurposes, type ImagePurpose } from '@/services/imagePurposes'
import type { PresetWorkspace } from '@/services/comfyPresetDraft'
const props = defineProps<{ workspace: PresetWorkspace }>()
const selected = computed(() => props.workspace.presets[props.workspace.selectedId]!)
function togglePurpose(purpose: ImagePurpose, checked: boolean): void {
  const values = new Set(selected.value.purpose_tags ?? [])
  if (checked) values.add(purpose)
  else values.delete(purpose)
  selected.value.purpose_tags = [...values]
}
function setTags(event: Event): void {
  selected.value.style_tags = [...new Set((event.target as HTMLInputElement).value.split(',').map(tag => tag.trim().slice(0,40)).filter(Boolean))].slice(0,16)
}
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
      <details class="text-xs text-slate-400">
        <summary class="cursor-pointer">Library tags (optional)</summary>
        <p class="mt-2">Tags organize presets. Set actual style instructions in the Prompt tab.</p>
        <div class="mt-2 grid grid-cols-2 gap-2">
          <label v-for="purpose in imagePurposes" :key="purpose.id" class="flex gap-2">
            <input type="checkbox" :checked="selected.purpose_tags?.includes(purpose.id)" @change="togglePurpose(purpose.id, ($event.target as HTMLInputElement).checked)" />{{ purpose.label }}
          </label>
        </div>
        <label class="mt-3 block">Style tags, separated by commas
          <input :value="selected.style_tags?.join(', ') ?? ''" placeholder="gothic, watercolor, pastel" class="mt-1 w-full rounded border border-slate-600 bg-slate-900 p-2" @change="setTags" />
        </label>
      </details>
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
