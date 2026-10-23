<script setup lang="ts">
import { ref, watch } from 'vue'
import { parseApiGraph, replaceGraph } from '@/services/comfyWorkflowService'
import type { ComfyWorkflow } from '@/types/comfyui'

const props = defineProps<{ modelValue: ComfyWorkflow }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: ComfyWorkflow): void }>()
const text = ref('')
const error = ref('')
watch(() => props.modelValue.graph, graph => { text.value = JSON.stringify(graph, null, 2); error.value = '' }, { immediate: true })
function apply(): void {
  try { emit('update:modelValue', replaceGraph(props.modelValue, parseApiGraph(text.value))); error.value = '' }
  catch (err) { error.value = err instanceof Error ? err.message : 'Invalid workflow JSON.' }
}
function download(): void {
  const url = URL.createObjectURL(new Blob([JSON.stringify(props.modelValue.graph, null, 2)], { type: 'application/json' }))
  const link = document.createElement('a')
  link.href = url; link.download = 'comfyui-api-workflow.json'; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
</script>

<template>
  <details class="rounded-lg border border-slate-700 p-3">
    <summary class="cursor-pointer text-xs text-slate-300">Advanced: edit or export workflow JSON</summary>
    <p class="mt-3 text-xs text-slate-400">For visual node editing, export this API graph and use ComfyUI. After changing nodes here, check the input mappings and server compatibility. Export includes the graph; TaleWeaver mappings and prompt rules stay in the preset.</p>
    <label class="mt-3 block text-xs text-slate-300">API workflow JSON<textarea v-model="text" rows="12" spellcheck="false" class="mt-1 block w-full rounded border border-slate-700 bg-slate-900 p-2 font-mono text-xs" /></label>
    <div class="mt-3 flex flex-wrap gap-3 text-xs">
      <button type="button" class="rounded bg-cyan-700 p-2 text-white" @click="apply">Apply JSON to draft</button>
      <button type="button" class="rounded border border-slate-600 p-2" @click="download">Export current API JSON</button>
    </div>
    <p v-if="error" role="alert" class="mt-2 text-xs text-rose-300">{{ error }}</p>
  </details>
</template>
