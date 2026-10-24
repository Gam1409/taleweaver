<script setup lang="ts">
import { computed, ref } from 'vue'
import ComfyPresetDrawer from './ComfyPresetDrawer.vue'
import type { ComfyOptions, ComfyPreset } from '@/types/comfyui'

const props = defineProps<{ modelValue: ComfyOptions; profile: 'simple' | 'advanced' }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: ComfyOptions): void }>()
const selectedId = computed(() => props.modelValue.comfyui_assignments?.[props.profile] ?? '')
const selected = computed(() => props.modelValue.comfyui_presets?.[selectedId.value])
const open = ref(false)
const editingId = ref('')
const draft = ref<ComfyPreset>({ name: 'New preset', generate: null, reference: null, prompt_rules: null, auto_prompt_template: true })
function select(event: Event): void {
  const key = (event.target as HTMLSelectElement).value
  emit('update:modelValue', { ...props.modelValue, comfyui_assignments: { ...props.modelValue.comfyui_assignments, [props.profile]: key } })
}
function edit(create: boolean): void {
  editingId.value = create ? crypto.randomUUID() : selectedId.value
  draft.value = create ? { name: 'New preset', generate: null, reference: null, prompt_rules: null, auto_prompt_template: true } : JSON.parse(JSON.stringify(selected.value))
  open.value = true
}
function apply(preset: ComfyPreset, copy: boolean): void {
  const key = copy ? crypto.randomUUID() : editingId.value
  const value = JSON.parse(JSON.stringify(preset)) as ComfyPreset
  if (copy) value.name += ' copy'
  emit('update:modelValue', {
    ...props.modelValue,
    comfyui_presets: { ...props.modelValue.comfyui_presets, [key]: value },
    comfyui_assignments: { ...props.modelValue.comfyui_assignments, [props.profile]: key },
  })
  open.value = false
}
</script>

<template>
  <div class="space-y-2">
    <label :for="`comfy-preset-${profile}`" class="block text-xs font-bold text-slate-400 uppercase tracking-wider">Generation preset</label>
    <div class="flex flex-wrap gap-2">
      <select :id="`comfy-preset-${profile}`" :value="selectedId" class="min-w-0 flex-1 rounded-xl border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-white" @change="select">
        <option value="" disabled>Choose a preset</option>
        <option v-for="(preset, id) in modelValue.comfyui_presets" :key="id" :value="id">{{ preset.name }}</option>
      </select>
      <button type="button" :disabled="!selected" class="rounded-lg bg-slate-800 px-3 text-xs text-white disabled:opacity-40" @click="edit(false)">Configure</button>
      <button type="button" class="rounded-lg border border-slate-700 px-3 py-2 text-xs text-cyan-300" @click="edit(true)">New preset</button>
    </div>
    <p v-if="selected" class="text-xs text-slate-400">{{ selected.prompt_rules?.format ?? 'Existing prompt behavior' }} · {{ selected.generate ? 'Workflow configured' : 'Workflow required' }}</p>
    <ComfyPresetDrawer :open="open" :preset="draft" :url="modelValue.comfyui_url" @close="open = false" @apply="apply" />
  </div>
</template>
