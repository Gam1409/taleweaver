<script setup lang="ts">
import type { ComfyOptions } from '@/types/comfyui'

const props = defineProps<{ modelValue: ComfyOptions }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: ComfyOptions): void }>()
function setUrl(event: Event): void {
  emit('update:modelValue', { ...props.modelValue, comfyui_url: (event.target as HTMLInputElement).value })
}
function setTimeoutValue(event: Event): void {
  emit('update:modelValue', { ...props.modelValue, comfyui_timeout: Number((event.target as HTMLInputElement).value) })
}
</script>

<template>
  <section class="rounded-2xl border border-cyan-800 bg-slate-900 p-5 space-y-5">
    <h3 class="text-sm font-semibold text-white">ComfyUI (Local)</h3>
    <label class="block text-xs text-slate-300">ComfyUI API URL
      <input :value="modelValue.comfyui_url" placeholder="http://127.0.0.1:8188" class="block mt-2 w-full rounded-lg bg-slate-950 border border-slate-700 p-3 font-mono" @input="setUrl" />
    </label>
    <p class="text-xs text-slate-400">This address must be reachable from the TaleWeaver backend. Localhost refers to the backend machine. Models and custom nodes must already be installed in ComfyUI.</p>
    <p class="text-xs text-slate-400">Final images are reduced without cropping to fit TaleWeaver's limits: covers 2048×1024, scenes 1600×900, portraits 1024×1280, items 1024×1024. Large files may be reduced further to fit the upload size limits. Smaller images are not enlarged.</p>
    <details>
      <summary class="text-xs text-slate-300 cursor-pointer">Advanced connection settings</summary>
      <label class="block mt-3 text-xs text-slate-300">Queue and execution timeout (seconds)
        <input type="number" min="30" max="3600" :value="modelValue.comfyui_timeout" class="ml-2 rounded bg-slate-950 p-2 w-28" @input="setTimeoutValue" />
      </label>
    </details>
    <p class="text-xs text-slate-400">Use Test Generation in each profile to verify execution. Save Visual Preferences to retain your preset assignments.</p>
  </section>
</template>
