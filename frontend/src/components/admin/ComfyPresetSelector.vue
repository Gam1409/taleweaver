<script setup lang="ts">
import { computed, ref } from 'vue'
import { SlidersHorizontal } from 'lucide-vue-next'
import ComfyPresetModal from './ComfyPresetModal.vue'
import type { ComfyOptions } from '@/types/comfyui'

const props = defineProps<{
  modelValue: ComfyOptions
  profile: 'simple' | 'advanced'
  testResult?: { status: string; message: string; image_url?: string }
}>()
const emit = defineEmits<{
  (event: 'update:modelValue', value: ComfyOptions): void
  (event: 'test', value: ComfyOptions): void
}>()
const selected = computed(
  () =>
    props.modelValue.comfyui_presets?.[props.modelValue.comfyui_assignments?.[props.profile] ?? '']
)
const open = ref(false)
function apply(options: ComfyOptions): void {
  emit('update:modelValue', options)
  open.value = false
}
</script>

<template>
  <div class="space-y-2">
    <span class="block text-xs font-bold uppercase tracking-wider text-slate-400"
      >Generation preset</span
    >
    <button
      type="button"
      class="flex w-full items-center justify-between gap-3 rounded-xl border border-slate-700 bg-slate-950 px-3 py-3 text-left text-white transition-colors hover:border-cyan-500/60 hover:bg-slate-900 focus-visible:outline focus-visible:outline-cyan-400"
      @click="open = true"
    >
      <span class="min-w-0"
        ><span class="block truncate text-sm font-semibold">{{
          selected?.name || 'Set up a preset'
        }}</span
        ><span class="mt-1 block text-xs text-slate-400"
          >{{ selected?.prompt_rules?.format || 'Choose a preset' }} · Workflows, prompts and
          connection</span
        ></span
      ><SlidersHorizontal :size="18" class="shrink-0 text-cyan-300" aria-hidden="true" />
    </button>
    <ComfyPresetModal
      :open="open"
      :model-value="modelValue"
      :profile="profile"
      :test-result="testResult"
      @close="open = false"
      @apply="apply"
      @test="emit('test', $event)"
    />
  </div>
</template>
