<script setup lang="ts">
import { computed, ref } from 'vue'
import { apiFetch } from '@/services/http'
import type { BindingName, ComfyWorkflow } from '@/types/comfyui'

const props = defineProps<{ modelValue: ComfyWorkflow | null; url: string; reference?: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: ComfyWorkflow | null): void }>()
const error = ref('')
const report = ref<string[]>([])
const checking = ref(false)
const fields = computed<BindingName[]>(() => props.reference
  ? ['prompt', 'negative_prompt', 'seed', 'width', 'height', 'image']
  : ['prompt', 'negative_prompt', 'seed', 'width', 'height'])
const inputs = computed(() => Object.entries(props.modelValue?.graph ?? {}).flatMap(([id, node]) =>
  Object.entries(node.inputs).filter(([, value]) => typeof value === 'string' || typeof value === 'number')
    .map(([name]) => ({ value: JSON.stringify([id, name]), label: `${id}: ${node._meta?.title || node.class_type} → ${name}` }))))

function update(value: ComfyWorkflow): void {
  report.value = []
  error.value = ''
  emit('update:modelValue', value)
}
function setBinding(field: BindingName, event: Event): void {
  if (!props.modelValue) return
  const value = (event.target as HTMLSelectElement).value
  const bindings = { ...props.modelValue.bindings }
  delete bindings[field]
  if (value) {
    const [nodeId, inputName] = JSON.parse(value) as [string, string]
    bindings[field] = { node_id: nodeId, input_name: inputName }
  }
  update({ ...props.modelValue, bindings })
}
function bindingValue(field: BindingName): string {
  const binding = props.modelValue?.bindings[field]
  return binding ? JSON.stringify([binding.node_id, binding.input_name]) : ''
}
function setOutput(event: Event): void {
  if (props.modelValue) update({ ...props.modelValue, output_node: (event.target as HTMLSelectElement).value })
}
async function loadWorkflow(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  error.value = ''
  try {
    if (file.size > 262144) throw new Error('Maximum workflow size is 256 KiB.')
    const graph = JSON.parse(await file.text()) as ComfyWorkflow['graph']
    const nodes = Object.entries(graph)
    if (!nodes.length || nodes.length > 256 || nodes.some(([, n]) => !n || typeof n.class_type !== 'string' || !n.inputs || Array.isArray(n.inputs))) {
      throw new Error('Export an API workflow from ComfyUI. The editor JSON is not supported.')
    }
    const outputs = nodes.filter(([, n]) => n.class_type === 'SaveImage')
    update({ name: file.name, graph, bindings: {}, output_node: outputs.length === 1 ? outputs[0]![0] : '' })
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Could not load workflow.'
  } finally {
    input.value = ''
  }
}
async function checkWorkflow(): Promise<void> {
  checking.value = true
  error.value = ''
  report.value = []
  try {
    const response = await apiFetch('/settings/comfyui/check', {
      method: 'POST', includeJson: true, timeoutMs: 45000,
      body: JSON.stringify({ url: props.url, workflow: props.modelValue }),
    })
    const data = await response.json()
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Check the API workflow and required bindings.')
    report.value = data.compatible
      ? [`All ${data.node_types} node types found. Known model choices match.`, data.message]
      : data.errors
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Compatibility check failed.'
  } finally {
    checking.value = false
  }
}
</script>

<template>
  <div class="rounded-xl border border-slate-700 bg-slate-950 p-4 space-y-3">
    <p class="text-sm font-semibold text-slate-200">{{ reference ? 'Image workflow (optional)' : 'Base workflow (required)' }}</p>
    <p class="text-xs text-slate-400">{{ reference ? 'Your graph decides whether the image is a reference or an img2img source.' : 'Used when creating a new image without a reference.' }}</p>
    <label class="block text-xs text-slate-300">Import API workflow JSON
      <input type="file" accept=".json,application/json" class="block mt-2 w-full text-xs" @change="loadWorkflow" />
    </label>
    <template v-if="modelValue">
      <p class="text-xs text-cyan-300 break-all">{{ modelValue.name }} · {{ Object.keys(modelValue.graph).length }} nodes</p>
      <details open class="space-y-3">
        <summary class="cursor-pointer text-xs text-slate-300">Workflow inputs and output</summary>
        <p class="text-xs text-slate-500">Only mapped inputs are replaced. Other model, sampler and denoise values stay as defined in your workflow.</p>
        <label v-for="field in fields" :key="field" class="block text-xs text-slate-300">
          {{ field }} {{ field === 'prompt' || field === 'image' ? '(required)' : '(optional)' }}
          <select :value="bindingValue(field)" class="mt-1 w-full rounded-lg bg-slate-900 border border-slate-700 p-2" @change="setBinding(field, $event)">
            <option value="">Choose input</option>
            <option v-for="input in inputs" :key="input.value" :value="input.value">{{ input.label }}</option>
          </select>
        </label>
        <label class="block text-xs text-slate-300">Image output node (required)
          <select :value="modelValue.output_node" class="mt-1 w-full rounded-lg bg-slate-900 border border-slate-700 p-2" @change="setOutput">
            <option value="">Choose output</option>
            <option v-for="(node, id) in modelValue.graph" :key="id" :value="id">{{ id }}: {{ node._meta?.title || node.class_type }}</option>
          </select>
        </label>
      </details>
      <div class="flex gap-3 text-xs">
        <button type="button" :disabled="checking" class="rounded-lg bg-cyan-700 p-2 text-white disabled:opacity-50" @click="checkWorkflow">{{ checking ? 'Checking…' : 'Check server compatibility' }}</button>
        <button type="button" class="text-slate-400" @click="emit('update:modelValue', null)">Remove workflow</button>
      </div>
    </template>
    <p v-if="error" role="alert" class="text-xs text-rose-300">{{ error }}</p>
    <ul v-if="report.length" aria-live="polite" class="text-xs text-slate-300 list-disc pl-4 space-y-1"><li v-for="line in report" :key="line">{{ line }}</li></ul>
  </div>
</template>
