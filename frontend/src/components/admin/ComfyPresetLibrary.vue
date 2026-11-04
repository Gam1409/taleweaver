<script setup lang="ts">
import { computed } from 'vue'
import ComfyPresetBrowser from './ComfyPresetBrowser.vue'
import ComfyPresetStarter from './ComfyPresetStarter.vue'
import { addStarterPreset } from '@/services/comfyPresetDraft'
import { imagePurposes, type ImagePurpose } from '@/services/imagePurposes'
import type { PresetWorkspace } from '@/services/comfyPresetDraft'
const props = defineProps<{ workspace: PresetWorkspace; purpose?: ImagePurpose }>()
const selected = computed(() => props.workspace.presets[props.workspace.selectedId]!)
function togglePurpose(purpose: ImagePurpose, checked: boolean): void {
  const values = new Set(selected.value.purpose_tags ?? [])
  if (checked) values.add(purpose)
  else values.delete(purpose)
  selected.value.purpose_tags = [...values]
}
function setTags(event: Event): void {
  selected.value.style_tags = [
    ...new Set(
      (event.target as HTMLInputElement).value
        .split(',')
        .map(tag => tag.trim().slice(0, 40))
        .filter(Boolean)
    )
  ].slice(0, 16)
}
const emit = defineEmits<{
  (event: 'select', id: string): void
  (event: 'rename', value: string): void
  (event: 'remove-draft'): void
  (event: 'configure'): void
}>()
</script>
<template>
  <ComfyPresetStarter
    :purpose="purpose"
    :disabled="Object.keys(workspace.presets).length >= 32"
    @create="addStarterPreset(workspace, $event)"
  />
  <div class="grid items-start gap-5 lg:grid-cols-[minmax(0,1.7fr)_minmax(16rem,1fr)]">
    <ComfyPresetBrowser
      :presets="workspace.presets"
      :selected="workspace.selectedId"
      @select="emit('select', $event)"
    />
    <div class="space-y-4 rounded-xl border border-slate-700 bg-slate-950/40 p-5">
      <label class="block text-sm font-medium"
        >Preset name<input
          :value="workspace.presets[workspace.selectedId]?.name"
          @input="emit('rename', ($event.target as HTMLInputElement).value)"
          maxlength="120"
          class="mt-2 block w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2.5 text-white"
      /></label>
      <details open class="text-xs text-slate-400">
        <summary class="cursor-pointer">Task and style labels</summary>
        <p class="mt-2">Tags organize presets. Set actual style instructions in the Prompt tab.</p>
        <div class="mt-2 grid grid-cols-2 gap-2">
          <label v-for="purpose in imagePurposes" :key="purpose.id" class="flex gap-2">
            <input
              type="checkbox"
              :checked="selected.purpose_tags?.includes(purpose.id)"
              @change="togglePurpose(purpose.id, ($event.target as HTMLInputElement).checked)"
            />{{ purpose.label }}
          </label>
        </div>
        <label class="mt-3 block"
          >Style tags, separated by commas
          <input
            :value="selected.style_tags?.join(', ') ?? ''"
            placeholder="gothic, watercolor, pastel"
            class="mt-1 w-full rounded border border-slate-600 bg-slate-900 p-2"
            @change="setTags"
          />
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
