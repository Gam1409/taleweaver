import { computed, onScopeDispose, ref, watch } from 'vue'
import { comfyRequest } from '@/services/comfyPresetService'
import { clonePresetData } from '@/services/comfyPresetDraft'
import { MODEL_FIELD_LABELS } from '@/services/comfyWorkflowGraph'
import type { ComfyPreset } from '@/types/comfyui'

export interface StarterRecipe {
  family: string
  purpose: string
  layout: 'checkpoint' | 'diffusion'
  encoder_source: 'embedded' | 'external'
  vae_source: 'embedded' | 'external'
  checkpoint_name: string | null
}
interface ModelOption { node_id: string; input_name: string; choices: string[] }
interface CheckReport { compatible: boolean; errors: string[]; message: string }
const PLACEHOLDER = '__choose_checkpoint__.safetensors'

export function useComfyStarterModels(
  props: { url: string; recipe: StarterRecipe | null; requiresFilename?: boolean },
  prepared: (preset: ComfyPreset | null) => void,
) {
  const preset = ref<ComfyPreset | null>(null)
  const options = ref<ModelOption[]>([])
  const report = ref<CheckReport | null>(null)
  const error = ref('')
  const busy = ref(false)
  let version = 0
  function reset() {
    version++
    preset.value = null
    options.value = []
    report.value = null
    error.value = ''
    busy.value = false
    prepared(null)
  }
  watch(() => JSON.stringify([props.url, props.recipe, props.requiresFilename]), reset, { flush: 'sync' })
  onScopeDispose(() => { version++; busy.value = false })
  const fields = computed(() => Object.entries(preset.value?.generate?.graph ?? {}).flatMap(([id, node]) =>
    Object.entries(node.inputs).filter(([name, value]) => MODEL_FIELD_LABELS[name] && typeof value === 'string')
      .map(([name, value]) => ({ id, name, value: String(value),
        label: MODEL_FIELD_LABELS[name]!,
        files: options.value.find(item => item.node_id === id && item.input_name === name)?.choices }))))

  function publish(candidate: ComfyPreset) {
    const unresolved = Object.values(candidate.generate?.graph ?? {}).some(node =>
      Object.values(node.inputs).includes(PLACEHOLDER))
    prepared(unresolved ? null : clonePresetData(candidate))
  }

  async function check() {
    if (busy.value || !props.url.trim() || !props.recipe) return
    const current = ++version
    const url = props.url
    busy.value = true
    report.value = null
    error.value = ''
    try {
      const recipe = { ...props.recipe }
      if (props.requiresFilename && !recipe.checkpoint_name) recipe.checkpoint_name = PLACEHOLDER
      const candidate = preset.value ?? (await comfyRequest<{ preset: ComfyPreset }>('starter-presets', recipe)).preset
      if (current !== version || !candidate.generate) return
      const [files, result] = await Promise.all([
        comfyRequest<ModelOption[]>('model-options', { url, workflow: candidate.generate }),
        comfyRequest<CheckReport>('check', { url, workflow: candidate.generate }),
      ])
      if (current !== version) return
      preset.value = clonePresetData(candidate)
      options.value = files
      report.value = result
      publish(candidate)
    } catch (cause) {
      if (current === version) error.value = cause instanceof Error ? cause.message : 'Could not check ComfyUI models. Please retry.'
    } finally {
      if (current === version) busy.value = false
    }
  }

  function select(nodeId: string, name: string, value: string) {
    if (busy.value || !preset.value?.generate) return
    const candidate = clonePresetData(preset.value)
    const source = candidate.generate!.graph[nodeId]
    if (!source || typeof source.inputs[name] !== 'string') return
    const old = source.inputs[name]
    const reference = candidate.reference?.graph[nodeId]
    if (reference?.class_type === source.class_type && reference.inputs[name] === old) reference.inputs[name] = value
    source.inputs[name] = value
    preset.value = candidate
    report.value = null
    error.value = ''
    publish(candidate)
  }

  return { preset, fields, report, error, busy, check, select }
}
