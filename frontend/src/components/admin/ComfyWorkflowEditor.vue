<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { apiFetch } from '@/services/http'
import { importWorkflowGraphWithServer, type NodeSchemas } from '@/services/comfyEditorImport'
import { comfyRequest } from '@/services/comfyPresetService'
import { autoLayout, existingPositions, suggestBindings, withPositions } from '@/services/comfyWorkflowGraph'
import ComfyWorkflowCanvas from './ComfyWorkflowCanvas.vue'
import ComfyWorkflowJson from './ComfyWorkflowJson.vue'
import ComfyWorkflowStarter from './ComfyWorkflowStarter.vue'
import ComfyWorkflowParameters from './ComfyWorkflowParameters.vue'
import type { BindingName, ComfyWorkflow } from '@/types/comfyui'

const props = defineProps<{ modelValue: ComfyWorkflow | null; url: string; reference?: boolean; suggestedFamily?: string; sourceWorkflow?: ComfyWorkflow | null }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: ComfyWorkflow | null): void; (e: 'busy', value: boolean): void }>()
const error = ref('')
const report = ref<string[]>([])
const checking = ref(false)
const checkingNodes = ref(false)
const nodeReport = ref<string[]>([])
let nodeCheckVersion = 0
const importing = ref(false)
const loadingModels = ref(false)
const canvasBusy = ref(false)
watch([checking, checkingNodes, importing, loadingModels, canvasBusy], values => emit('busy', values.some(Boolean)))
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
let importVersion = 0
let disposed = false
watch(() => [props.url, props.modelValue], () => {
  importVersion++
  nodeCheckVersion++
  checkingNodes.value = false
  nodeReport.value = []
  importing.value = false
}, { flush: 'sync' })
onBeforeUnmount(() => { disposed = true; importVersion++; nodeCheckVersion++ })

async function loadWorkflow(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const version = ++importVersion
  const active = () => !disposed && version === importVersion
  error.value = ''
  importing.value = true
  try {
    if (file.size > 262144) throw new Error('Maximum workflow size is 256 KiB.')
    const url = props.url
    const fetchSchemas = url.trim()
      ? (classes: string[]) => comfyRequest<NodeSchemas>('node-schemas', { url, classes })
      : undefined
    const result = await importWorkflowGraphWithServer(await file.text(), fetchSchemas)
    if (!active()) return
    const suggestion = suggestBindings(result.graph)
    const graph = existingPositions(result.graph)
      ? result.graph
      : withPositions(result.graph, autoLayout(result.graph))
    const bindings: ComfyWorkflow['bindings'] = {}
    for (const role of Object.keys(suggestion.bindings) as BindingName[]) {
      const target = suggestion.bindings[role]
      if (target) bindings[role] = target
    }
    update({ name: file.name, graph, bindings, output_node: suggestion.output_node })
    report.value = [`Imported ${Object.keys(graph).length} nodes; drag them into a comfortable arrangement.`]
      .concat(result.notes)
      .concat(suggestion.notes)
  } catch (err) {
    if (active()) error.value = err instanceof Error ? err.message : 'Could not load workflow.'
  } finally {
    if (active()) { importing.value = false; input.value = '' }
  }
}
async function checkNodes(): Promise<void> {
  if (!props.modelValue || !props.url.trim() || checkingNodes.value) return
  const version = ++nodeCheckVersion
  const active = () => !disposed && version === nodeCheckVersion
  checkingNodes.value = true
  nodeReport.value = []
  try {
    const classes = [...new Set(Object.values(props.modelValue.graph).map(node => node.class_type))]
    const data = await comfyRequest<{ node_types: number; missing_node_types: string[] }>(
      'check-nodes', { url: props.url, classes }
    )
    if (!active()) return
    nodeReport.value = data.missing_node_types.length
      ? data.missing_node_types.map(name => `Missing node type: ${name}`)
      : [`All ${data.node_types} node types are installed on this server.`]
  } catch (err) {
    if (active()) nodeReport.value = [err instanceof Error ? err.message : 'Could not check server nodes.']
  } finally {
    if (active()) checkingNodes.value = false
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
    <div class="flex flex-wrap items-center justify-between gap-3">
      <p class="text-sm font-semibold text-slate-200">{{ reference ? 'Image workflow (optional)' : 'Base workflow (required)' }}</p>
      <button type="button" :disabled="!modelValue || !url.trim() || checkingNodes || importing" class="rounded-lg bg-cyan-700 px-3 py-2 text-xs text-white disabled:opacity-50" @click="checkNodes">
        {{ checkingNodes ? 'Checking nodes…' : 'Check nodes' }}
      </button>
    </div>
    <ul v-if="nodeReport.length" aria-live="polite" class="list-disc space-y-1 pl-4 text-xs text-slate-300">
      <li v-for="line in nodeReport" :key="line">{{ line }}</li>
    </ul>
    <p class="text-xs text-slate-400">{{ reference ? 'Your graph decides whether the image is a reference or an img2img source.' : 'Used when creating a new image without a reference.' }}</p>
    <ComfyWorkflowStarter :reference="reference" :empty="!modelValue" :suggested-family="suggestedFamily" :source-workflow="sourceWorkflow" @choose="chooseStarter" />
    <label class="block text-xs text-slate-300">Import workflow JSON (ComfyUI editor or API export)
      <input type="file" accept=".json,application/json" class="block mt-2 w-full text-xs" @change="loadWorkflow" />
      <span class="mt-1 block text-slate-400">Editor exports keep your node arrangement; bypassed nodes are skipped like ComfyUI's API export.</span>
    </label>
    <template v-if="modelValue">
      <p class="text-xs text-cyan-300 break-all">{{ modelValue.name }} · {{ Object.keys(modelValue.graph).length }} nodes</p>
      <ComfyWorkflowCanvas :model-value="modelValue" :url="url" :reference="reference" @update:model-value="update" @busy="canvasBusy = $event" />
      <details class="space-y-3">
        <summary class="cursor-pointer text-xs text-slate-300">List view: models, parameters and bindings</summary>
        <p class="text-xs text-slate-500">Only mapped inputs are replaced. Other model, sampler and denoise values stay as defined in your workflow.</p>
        <ComfyWorkflowParameters ref="parameters" :model-value="modelValue" :url="url" @busy="loadingModels = $event" @update:model-value="update" />
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
          <select :value="modelValue.dimension_multiple || 8" class="mt-1 w-full rounded-lg bg-slate-900 border border-slate-700 p-2" @change="update({ ...modelValue, dimension_multiple: Number(($event.target as HTMLSelectElement).value) as 8 | 16 | 32 | 64 })">
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
