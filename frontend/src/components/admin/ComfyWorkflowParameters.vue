<script setup lang="ts">
import { computed, getCurrentInstance, ref, watch } from 'vue'
import { comfyRequest } from '@/services/comfyPresetService'
import ComfyModelField from './ComfyModelField.vue'
import type { ComfyWorkflow } from '@/types/comfyui'

const props = defineProps<{ modelValue: ComfyWorkflow; url: string }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: ComfyWorkflow): void; (event: 'busy', value: boolean): void }>()
type ModelOption = { node_id: string; input_name: string; choices: string[] }
const options = ref<ModelOption[]>([])
const loading = ref(false)
watch(loading, value => emit('busy', value))
const message = ref('')
const inputPrefix = `workflow-${getCurrentInstance()!.uid}`
const enumLabels: Record<string, string> = { sampler_name: 'Sampler', scheduler: 'Scheduler' }
const loaders = computed(() => JSON.stringify(Object.entries(props.modelValue.graph).map(([id, node]) => [id, node.class_type, Object.keys(node.inputs)])))
watch([() => props.url, loaders], () => { options.value = []; message.value = '' })
const labels: Record<string, string> = { ckpt_name: 'Checkpoint', unet_name: 'Diffusion model', clip_name: 'Text encoder', clip_name1: 'Text encoder 1', clip_name2: 'Text encoder 2', clip_name3: 'Text encoder 3', vae_name: 'VAE', lora_name: 'LoRA' }
const folders: Record<string, string> = { ckpt_name: 'models/checkpoints', unet_name: 'models/diffusion_models', clip_name: 'models/text_encoders', clip_name1: 'models/text_encoders', clip_name2: 'models/text_encoders', clip_name3: 'models/text_encoders', vae_name: 'models/vae', lora_name: 'models/loras' }
const controls: Record<string, { label: string; min: number; max: number; step: number }> = {
  steps: { label: 'Steps', min: 1, max: 10000, step: 1 }, cfg: { label: 'CFG', min: 0, max: 100, step: 0.1 },
  guidance: { label: 'Guidance', min: 0, max: 100, step: 0.1 }, denoise: { label: 'Denoise', min: 0, max: 1, step: 0.05 },
  strength_model: { label: 'LoRA model strength', min: -100, max: 100, step: 0.05 }, strength_clip: { label: 'LoRA encoder strength', min: -100, max: 100, step: 0.05 },
}
const entries = computed(() => Object.entries(props.modelValue.graph).flatMap(([id, node]) => Object.entries(node.inputs).map(([field, value]) => ({ id, field, value, kind: node.class_type }))))
const models = computed(() => entries.value.filter(item => labels[item.field] && typeof item.value === 'string'))
const checkpointVaeSources = computed(() => [...new Set(entries.value.flatMap(item => {
  if (item.field !== 'vae' || !Array.isArray(item.value) || item.value[1] !== 2) return []
  const source = props.modelValue.graph[String(item.value[0])]
  if (!source || !['CheckpointLoaderSimple', 'CheckpointLoader'].includes(source.class_type)) return []
  return [String(source.inputs.ckpt_name || item.value[0])]
}))])
const checkedModels = computed(() => models.value.filter(item => modelFiles(item.id, item.field) !== undefined))
const missingModels = computed(() => checkedModels.value.filter(item => !choices(item.id, item.field).includes(String(item.value))))
const parameters = computed(() => entries.value.filter(item => controls[item.field] && typeof item.value === 'number' && /KSampler|CLIPTextEncodeFlux|FluxGuidance|LoraLoader/.test(item.kind)))
const enums = computed(() => entries.value.filter(item => enumLabels[item.field] && typeof item.value === 'string' && item.kind.startsWith('KSampler')))
function numberChanged(id: string, field: string, event: Event): void {
  const input = event.target as HTMLInputElement
  if (!input.value || !input.checkValidity()) {
    input.reportValidity(); input.value = String(props.modelValue.graph[id]!.inputs[field]); return
  }
  update(id, field, Number(input.value))
}
defineExpose({ refresh })
function choices(id: string, field: string): string[] { return options.value.find(item => item.node_id === id && item.input_name === field)?.choices ?? [] }
function modelFiles(id: string, field: string): string[] | undefined { return options.value.find(item => item.node_id === id && item.input_name === field)?.choices }
function update(id: string, field: string, value: string | number): void {
  const graph = JSON.parse(JSON.stringify(props.modelValue.graph)) as ComfyWorkflow['graph']
  graph[id]!.inputs[field] = value
  emit('update:modelValue', { ...props.modelValue, graph })
}
async function refresh(): Promise<void> {
  loading.value = true; message.value = ''
  const snapshot = JSON.stringify(props.modelValue.graph)
  const url = props.url
  try {
    const result = await comfyRequest<ModelOption[]>('model-options', { url, workflow: props.modelValue })
    if (url !== props.url || snapshot !== JSON.stringify(props.modelValue.graph)) return
    options.value = result
    const graph = JSON.parse(snapshot) as ComfyWorkflow['graph']
    let resolved = 0
    for (const item of models.value) {
      const current = String(item.value)
      const available = choices(item.id, item.field)
      const matches = available.filter(name => name.replace(/\\/g, '/').split('/').pop() === current.replace(/\\/g, '/').split('/').pop())
      if (!available.includes(current) && matches.length === 1) {
        graph[item.id]!.inputs[item.field] = matches[0]!
        resolved++
      }
    }
    emit('update:modelValue', { ...props.modelValue, graph })
    message.value = resolved ? `Model lists refreshed. Resolved ${resolved} matching filename(s) to their server folders.` : 'Model lists refreshed.'
  } catch (err) { if (url === props.url && snapshot === JSON.stringify(props.modelValue.graph)) message.value = String(err) }
  finally { loading.value = false }
}
</script>

<template>
  <div class="space-y-3">
    <p v-if="checkpointVaeSources.length" role="status" class="text-xs text-slate-400">
      VAE from checkpoint: {{ checkpointVaeSources.join(', ') }}. These workflow connections use the checkpoint's VAE output; no separate VAE file is needed for them. Run a test image to confirm the checkpoint contains a working VAE.
    </p>
    <ComfyModelField v-for="item in models" :key="`${item.id}-${item.field}`" :label="labels[item.field]! + (models.filter(model => model.field === item.field).length > 1 ? ` · ${item.id}` : '')" :model-value="String(item.value)" :files="modelFiles(item.id, item.field)" :folder="folders[item.field]" @update:model-value="update(item.id, item.field, $event)" />
    <button v-if="models.length" type="button" :disabled="loading" class="text-xs text-cyan-300 underline disabled:opacity-40" @click="refresh">{{ loading ? 'Loading models…' : 'Refresh model list from server' }}</button>
    <p v-if="message" role="status" class="text-xs text-slate-400">{{ message }}</p>
    <p v-if="checkedModels.length" role="status" :class="['text-xs', missingModels.length ? 'text-amber-300' : 'text-slate-400']">
      {{ checkedModels.length - missingModels.length }} of {{ checkedModels.length }} selected model files are available.
      {{ missingModels.length ? 'Choose the missing files or check the model folders in ComfyUI.' : 'Run the compatibility check before generating.' }}
    </p>
    <details v-if="parameters.length || enums.length" class="rounded-lg border border-slate-700 p-3">
      <summary class="cursor-pointer text-xs text-slate-300">Generation parameters</summary>
      <p class="mt-3 text-xs text-slate-400">Defaults belong to this workflow. CFG and guidance are different controls; changing the prompt template does not change them. A lower img2img denoise preserves more of the source.</p>
      <div class="mt-3 grid grid-cols-2 gap-3">
        <label v-for="item in parameters" :key="`${item.id}-${item.field}`" class="text-xs text-slate-300">{{ controls[item.field]!.label }}<span v-if="parameters.filter(parameter => parameter.field === item.field).length > 1"> · {{ item.id }}</span>
          <input :value="item.value" type="number" :min="controls[item.field]!.min" :max="controls[item.field]!.max" :step="controls[item.field]!.step" class="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2" @change="numberChanged(item.id, item.field, $event)" />
        </label>
        <label v-for="item in enums" :key="`${item.id}-${item.field}`" class="text-xs text-slate-300">{{ enumLabels[item.field] }}
          <input :value="item.value" :list="`${inputPrefix}-${item.id}-${item.field}`" class="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2" @change="update(item.id, item.field, ($event.target as HTMLInputElement).value)" />
          <datalist :id="`${inputPrefix}-${item.id}-${item.field}`"><option v-for="name in choices(item.id, item.field)" :key="name" :value="name" /></datalist>
        </label>
      </div>
    </details>
  </div>
</template>
