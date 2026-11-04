<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, ref, watch } from 'vue'
import ComfyDialog from './ComfyDialog.vue'
import { workflowDependencies } from '@/services/comfyLibrary'
import { clonePresetData } from '@/services/comfyPresetDraft'
import { comfyRequest } from '@/services/comfyPresetService'
import type { ComfyWorkflow, ComfyWorkflowVersion } from '@/types/comfyui'
const Editor = defineAsyncComponent(() => import('./ComfyWorkflowEditor.vue'))
const props = defineProps<{
  modelValue: ComfyWorkflow | null
  library: Record<string, ComfyWorkflowVersion>
  url: string
  reference?: boolean
  sourceWorkflow?: ComfyWorkflow | null
  suggestedFamily?: string
}>()
const emit = defineEmits<{
  (event: 'update:modelValue', value: ComfyWorkflow | null): void
  (event: 'forget', id: string): void
}>()
const dependencies = computed(() => workflowDependencies(props.modelValue))
const entries = computed(() =>
  Object.entries(props.library).filter(
    ([, item]) => Boolean(item.workflow.bindings.image) === Boolean(props.reference)
  )
)
const selected = ref('')
const editing = ref(false)
const draft = ref<ComfyWorkflow | null>(null)
const busy = ref(false)
const checking = ref(false)
const importing = ref(false)
const report = ref<string[]>([])
let version = 0
let importedSignature = ''
watch(
  () => JSON.stringify([props.url, props.modelValue]),
  signature => {
    version++
    if (signature !== importedSignature) report.value = []
    importedSignature = ''
    checking.value = false
    importing.value = false
    selected.value = ''
  }
)
onBeforeUnmount(() => {
  version++
})
function choose(): void {
  const item = props.library[selected.value]
  if (item) emit('update:modelValue', clonePresetData(item.workflow))
}
function edit(): void {
  draft.value = clonePresetData(props.modelValue)
  busy.value = false
  editing.value = true
}
function save(): void {
  emit('update:modelValue', clonePresetData(draft.value))
  editing.value = false
}
const valid = computed(
  () =>
    draft.value?.bindings.prompt &&
    draft.value.output_node &&
    (props.reference ? draft.value.bindings.image : !draft.value.bindings.image)
)
async function importFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const current = ++version
  importing.value = true
  report.value = []
  try {
    if (file.size > 262144) throw new Error('Maximum workflow size is 256 KiB.')
    const { importWorkflowGraphWithServer } = await import('@/services/comfyEditorImport')
    const { suggestBindings } = await import('@/services/comfyWorkflowGraph')
    const result = await importWorkflowGraphWithServer(
      await file.text(),
      props.url.trim()
        ? classes => comfyRequest('node-schemas', { url: props.url, classes })
        : undefined
    )
    if (current !== version) return
    const suggested = suggestBindings(result.graph)
    const workflow: ComfyWorkflow = {
      name: file.name.slice(0, 120),
      graph: result.graph,
      bindings: suggested.bindings,
      output_node: suggested.output_node
    }
    importedSignature = JSON.stringify([props.url, workflow])
    report.value = [...result.notes, ...suggested.notes]
    emit('update:modelValue', workflow)
  } catch (error) {
    if (current === version) report.value = [String(error)]
  } finally {
    if (current === version) importing.value = false
    input.value = ''
  }
}
async function check(): Promise<void> {
  if (!props.modelValue || checking.value) return
  const current = ++version
  checking.value = true
  report.value = []
  try {
    const data = await comfyRequest<{ compatible: boolean; errors: string[]; message: string }>(
      'check',
      { url: props.url, workflow: props.modelValue }
    )
    if (current === version)
      report.value = data.compatible
        ? ['Required nodes and known model choices are available.', data.message]
        : data.errors
  } catch (error) {
    if (current === version) report.value = [String(error)]
  } finally {
    if (current === version) checking.value = false
  }
}
</script>
<template>
  <div class="space-y-5 rounded-xl border border-slate-700 bg-slate-950/40 p-5">
    <div>
      <h4 class="font-semibold">
        {{ reference ? 'With reference (optional)' : 'Without reference' }}
      </h4>
      <p class="mt-1 text-sm text-slate-400">{{ modelValue?.name || 'No workflow selected' }}</p>
    </div>
    <p class="text-xs text-slate-400">
      Choose a saved version or import JSON below. Open the graph only when you need to edit nodes
      or bindings. Changes create an independent version when the preset is applied. Other presets
      keep their graphs.
    </p>
    <label class="block text-sm"
      >Saved workflows<select
        v-model="selected"
        class="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 p-3"
        @change="choose"
      >
        <option value="">Choose a workflow version…</option>
        <option v-for="[id, item] in entries" :key="id" :value="id">
          {{ item.workflow.name }} · v{{ item.revision }}
        </option>
      </select></label
    >
    <label class="block text-sm"
      >Import workflow JSON (editor or API export)<input
        type="file"
        accept=".json,application/json"
        :disabled="importing"
        class="mt-2 block w-full text-xs"
        @change="importFile"
      /><span v-if="importing" role="status" class="mt-2 block text-xs text-slate-400"
        >Reading workflow…</span
      ></label
    >
    <div class="rounded-lg border border-slate-700 p-4">
      <h5 class="text-sm">Required model files</h5>
      <ul v-if="dependencies.length" class="mt-2 space-y-2 break-all text-xs text-slate-400">
        <li v-for="dependency in dependencies" :key="dependency">{{ dependency }}</li>
      </ul>
      <p v-else class="mt-2 text-xs text-slate-400">
        {{
          modelValue
            ? 'No standard model filenames identified. Custom loaders may have additional requirements.'
            : 'Select or import a workflow to identify its model files.'
        }}
      </p>
    </div>
    <div class="flex flex-wrap gap-3">
      <button
        type="button"
        class="rounded-lg border border-slate-600 px-4 py-2 text-sm disabled:opacity-40"
        :disabled="!modelValue || !url.trim() || checking"
        @click="check"
      >
        {{ checking ? 'Checking…' : 'Check models and nodes' }}</button
      ><button type="button" class="rounded-lg bg-cyan-700 px-4 py-2 text-sm" @click="edit">
        {{ modelValue ? 'Open workflow editor' : 'Create workflow' }}</button
      ><button
        v-if="reference && modelValue"
        type="button"
        class="text-sm text-rose-300"
        @click="emit('update:modelValue', null)"
      >
        Remove reference variant
      </button>
    </div>
    <ul v-if="report.length" role="status" class="space-y-1 text-sm text-slate-300">
      <li v-for="line in report" :key="line">{{ line }}</li>
    </ul>
    <details v-if="entries.length" class="text-xs text-slate-400">
      <summary class="cursor-pointer">Manage saved versions ({{ entries.length }})</summary>
      <p class="my-3">Removing a library version keeps the copies already used by presets.</p>
      <div
        v-for="[id, item] in entries"
        :key="id"
        class="flex items-center justify-between gap-3 border-t border-slate-800 py-2"
      >
        <span>{{ item.workflow.name }} · v{{ item.revision }}</span
        ><button type="button" class="text-rose-300" @click="emit('forget', id)">
          Remove from library
        </button>
      </div>
    </details>
    <p v-if="reference" class="text-xs text-slate-400">
      An image input does not guarantee identity preservation. The workflow determines whether it
      performs img2img, style transfer or identity conditioning.
    </p>
    <ComfyDialog
      v-if="editing"
      :maximizable="!!draft"
      :title="reference ? 'Reference workflow editor' : 'Base workflow editor'"
      @close="editing = false"
    >
      <template #default="{ maximized }">
        <label v-if="draft && !maximized" class="mb-4 block text-sm"
          >Workflow name<input
            v-model="draft.name"
            maxlength="120"
            class="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 p-2"
        /></label>
        <Editor
          v-model="draft"
          :expanded="maximized"
          :url="url"
          :reference="reference"
          :suggested-family="suggestedFamily"
          :source-workflow="sourceWorkflow"
          @busy="busy = $event"
        />
      </template>
      <template #footer
        ><button type="button" class="px-4 py-2 text-sm" @click="editing = false">
          Discard changes</button
        ><button
          type="button"
          :disabled="busy || !valid || !draft?.name.trim()"
          class="rounded-lg bg-cyan-700 px-4 py-2 text-sm disabled:opacity-40"
          @click="save"
        >
          Use in preset
        </button></template
      >
    </ComfyDialog>
  </div>
</template>
