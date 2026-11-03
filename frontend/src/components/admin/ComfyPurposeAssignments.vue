<script setup lang="ts">
import { computed, ref } from 'vue'
import ComfyPresetModal from './ComfyPresetModal.vue'
import { imagePurposes, type ImagePurpose } from '@/services/imagePurposes'
import type { ComfyOptions } from '@/types/comfyui'

const props = defineProps<{
  modelValue: ComfyOptions
  settings: Record<string, unknown>
  testResults: Record<string, { status: string; message: string; image_url?: string }>
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: ComfyOptions): void
  (e: 'test', value: { options: ComfyOptions; profile: 'simple' | 'advanced' }): void
}>()
const editing = ref<ImagePurpose>('npc')
const open = ref(false)
const assigned = computed(
  () => imagePurposes.filter(p => props.modelValue.comfyui_assignments?.[p.id]).length
)
function profileFor(id: ImagePurpose): 'simple' | 'advanced' {
  const purpose = imagePurposes.find(p => p.id === id)!
  return (props.settings[purpose.quality] ?? purpose.fallback) === 'simple' ? 'simple' : 'advanced'
}
const profile = computed(() => profileFor(editing.value))
function assign(id: ImagePurpose, event: Event): void {
  const assignments = { ...props.modelValue.comfyui_assignments }
  const value = (event.target as HTMLSelectElement).value
  if (value) assignments[id] = value
  else delete assignments[id]
  emit('update:modelValue', { ...props.modelValue, comfyui_assignments: assignments })
}
function edit(id: ImagePurpose): void {
  editing.value = id
  open.value = true
}
function apply(value: ComfyOptions): void {
  emit('update:modelValue', value)
  open.value = false
}
</script>

<template>
  <details class="rounded-2xl border border-slate-700 bg-slate-900 p-5">
    <summary class="cursor-pointer text-sm font-semibold text-white">
      Workflows by task
      <span class="ml-2 font-normal text-slate-400">{{ assigned }} of 8 assigned</span>
    </summary>
    <p class="mt-3 text-xs text-slate-400">
      Choose a ComfyUI preset for each task. A preset can serve several tasks. Unassigned tasks keep
      their current provider and quality profile. Save Visuals Settings to publish changes.
    </p>
    <div class="mt-4 divide-y divide-slate-700/60">
      <div
        v-for="purpose in imagePurposes"
        :key="purpose.id"
        class="grid gap-2 py-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-center"
      >
        <div>
          <label :for="`purpose-${purpose.id}`" class="text-sm text-slate-200">{{
            purpose.label
          }}</label>
          <p class="text-xs text-slate-500">{{ purpose.hint }}</p>
        </div>
        <select
          :id="`purpose-${purpose.id}`"
          :value="modelValue.comfyui_assignments?.[purpose.id] ?? ''"
          class="min-w-0 rounded-lg border border-slate-700 bg-slate-950 p-2 text-sm"
          @change="assign(purpose.id, $event)"
        >
          <option value="">Use {{ profileFor(purpose.id) }} profile</option>
          <option v-for="(preset, id) in modelValue.comfyui_presets" :key="id" :value="id">
            {{ preset.name }}
          </option>
        </select>
        <button
          type="button"
          class="rounded-lg border border-slate-600 px-3 py-2 text-xs text-cyan-300"
          @click="edit(purpose.id)"
        >
          Configure
        </button>
      </div>
    </div>
    <ComfyPresetModal
      :key="editing"
      :open="open"
      :purpose="editing"
      :profile="profile"
      :model-value="modelValue"
      :test-result="testResults[profile === 'simple' ? 'simple_v' : 'advanced_v']"
      @close="open = false"
      @apply="apply"
      @test="options => emit('test', { options, profile })"
    />
  </details>
</template>
