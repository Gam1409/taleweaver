<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { apiFetch } from '@/services/http'
import { parseApiGraph } from '@/services/comfyWorkflowService'
import ComfyWorkflowJson from './ComfyWorkflowJson.vue'
import ComfyWorkflowStarter from './ComfyWorkflowStarter.vue'
import ComfyWorkflowParameters from './ComfyWorkflowParameters.vue'
import type { BindingName, ComfyWorkflow } from '@/types/comfyui'

const props = defineProps<{ modelValue: ComfyWorkflow | null; url: string; reference?: boolean; suggestedFamily?: string; sourceWorkflow?: ComfyWorkflow | null }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: ComfyWorkflow | null): void; (e: 'busy', value: boolean): void }>()
const error = ref('')
const report = ref<string[]>([])
const checking = ref(false)
const loadingModels = ref(false)
watch([checking, loadingModels], ([checkingServer, loadingFiles]) => emit('busy', checkingServer || loadingFiles))
const parameters = ref<InstanceType<typeof ComfyWorkflowParameters>>()
async function chooseStarter(value: ComfyWorkflow): Promise<void> {
  update(value)
  await nextTick()
  await parameters.value?.refresh()
  await nextTick()
  await checkWorkflow()
}
watch(() => JSON.stringify([props.url, props.modelValue]), () => { report.value = [] })
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
    const graph = parseApiGraph(await file.text())
    const nodes = Object.entries(graph)
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
  const snapshot = JSON.stringify([props.url, props.modelValue])
  try {
    const response = await apiFetch('/settings/comfyui/check', {
      method: 'POST', includeJson: true, timeoutMs: 45000,
      body: JSON.stringify({ url: props.url, workflow: props.modelValue }),
    })
    const data = await response.json()
    if (snapshot !== JSON.stringify([props.url, props.modelValue])) return
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
    <ComfyWorkflowStarter :reference="reference" :empty="!modelValue" :suggested-family="suggestedFamily" :source-workflow="sourceWorkflow" @choose="chooseStarter" />
    <label class="block text-xs text-slate-300">Import API workflow JSON
      <input type="file" accept=".json,application/json" class="block mt-2 w-full text-xs" @change="loadWorkflow" />
    </label>
    <template v-if="modelValue">
      <p class="text-xs text-cyan-300 break-all">{{ modelValue.name }} · {{ Object.keys(modelValue.graph).length }} nodes</p>
      <ComfyWorkflowParameters ref="parameters" :model-value="modelValue" :url="url" @busy="loadingModels = $event" @update:model-value="update" />
      <details :open="!modelValue.bindings.prompt || !modelValue.output_node || (reference && !modelValue.bindings.image)" class="space-y-3">
        <summary class="cursor-pointer text-xs text-slate-300">Advanced: workflow inputs and output</summary>
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
        <label class="block text-xs text-slate-300">Dimension alignment
          <select :value="modelValue.dimension_multiple || 8" class="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 p-2" @change="update({ ...modelValue, dimension_multiple: Number(($event.target as HTMLSelectElement).value) as 8 | 16 | 32 | 64 })">
            <option v-for="size in [8, 16, 32, 64]" :key="size" :value="size">Multiples of {{ size }} pixels</option>
          </select>
          <span class="mt-1 block text-slate-400">Starter workflows set this automatically. Change only if your custom architecture requires it.</span>
        </label>
      </details>
      <ComfyWorkflowJson :model-value="modelValue" @update:model-value="update" />
      <div class="flex flex-wrap gap-3 text-xs">
        <button type="button" :disabled="checking" class="rounded-lg bg-cyan-700 p-2 text-white disabled:opacity-50" @click="checkWorkflow">{{ checking ? 'Checking…' : 'Check server compatibility' }}</button>
        <button type="button" class="text-slate-400" @click="emit('update:modelValue', null)">Remove workflow</button>
      </div>
    </template>
    <p v-if="error" role="alert" class="text-xs text-rose-300">{{ error }}</p>
    <ul v-if="report.length" aria-live="polite" class="text-xs text-slate-300 list-disc pl-4 space-y-1"><li v-for="line in report" :key="line">{{ line }}</li></ul>
  </div>
</template>
