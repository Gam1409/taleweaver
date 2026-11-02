import { computed, ref, watch } from 'vue'
import type { ComfyOptions, ImagePromptRules, PromptTemplate } from '@/types/comfyui'
import { comfyRequest, loadPromptTemplates } from '@/services/comfyPresetService'
import {
  applyPresetWorkspace,
  changedPresets,
  newPreset,
  presetProblem,
  presetWorkspace,
  removeUnsavedPreset
} from '@/services/comfyPresetDraft'

type Detection = { template_id: string | null; models: string[]; message: string }
export function useComfyPresetWorkspace(props: {
  open: boolean
  modelValue: ComfyOptions
  profile: 'simple' | 'advanced'
}) {
  const workspace = ref(presetWorkspace(props.modelValue, props.profile))
  const draft = computed(() => workspace.value.presets[workspace.value.selectedId]!)
  const templates = ref<PromptTemplate[]>([])
  const error = ref('')
  const detection = ref<Detection | null>(null)
  const detecting = ref(false)
  const baseBusy = ref(false)
  const referenceBusy = ref(false)
  const previewing = ref(false)
  const example = ref(
    'A traveler in a red coat stands beside a stone bridge at dawn. A brass lantern hangs from their belt.'
  )
  const preview = ref<{ positive: string; negative: string } | null>(null)
  let generation = 0
  let previewVersion = 0
  const invalid = computed(() =>
    [...new Set([...changedPresets(workspace.value), workspace.value.selectedId])]
      .map(id => ({
        id,
        name: workspace.value.presets[id]!.name || 'Unnamed preset',
        reason: presetProblem(workspace.value.presets[id]!)
      }))
      .filter(item => item.reason)
  )
  const connectionProblem = computed(() =>
    !workspace.value.url.trim()
      ? 'Enter the ComfyUI server address in Visual Generation > ComfyUI connection.'
      : !Number.isInteger(workspace.value.timeout) ||
          workspace.value.timeout < 30 ||
          workspace.value.timeout > 3600
        ? 'Choose a timeout between 30 and 3600 seconds in Visual Generation > ComfyUI connection.'
        : ''
  )
  const ready = computed(
    () =>
      !invalid.value.length &&
      !detecting.value &&
      !baseBusy.value &&
      !referenceBusy.value &&
      Boolean(workspace.value.url.trim()) &&
      Number.isInteger(workspace.value.timeout) &&
      workspace.value.timeout >= 30 &&
      workspace.value.timeout <= 3600
  )

  watch(
    () => props.open,
    open => {
      generation++
      previewVersion++
      detecting.value = false
      previewing.value = false
      if (!open) return
      workspace.value = presetWorkspace(props.modelValue, props.profile)
      error.value = ''
      preview.value = null
      detection.value = null
    },
    { immediate: true }
  )
  watch(
    () =>
      JSON.stringify([
        props.open,
        workspace.value.selectedId,
        draft.value.generate?.graph,
        draft.value.reference?.graph
      ]),
    () => {
      if (props.open) void detect()
    },
    { immediate: true }
  )
  watch(
    () => JSON.stringify([workspace.value.selectedId, draft.value, example.value]),
    () => {
      preview.value = null
      previewVersion++
      previewing.value = false
    }
  )

  async function detect(): Promise<void> {
    const version = ++generation
    const selected = draft.value
    const sourceWorkspace = workspace.value
    const sourceId = workspace.value.selectedId
    const graphSignature = JSON.stringify([selected.generate?.graph, selected.reference?.graph])
    const relevant = () =>
      props.open &&
      workspace.value === sourceWorkspace &&
      sourceWorkspace.presets[sourceId] === selected &&
      JSON.stringify([selected.generate?.graph, selected.reference?.graph]) === graphSignature
    detection.value = null
    detecting.value = true
    if (selected.auto_prompt_template) selected.prompt_rules = null
    try {
      templates.value = await loadPromptTemplates()
      if (!relevant()) return
      if (!selected.generate) return
      const result = await comfyRequest<Detection>('detect-template', {
        graph: selected.generate.graph,
        reference_graph: selected.reference?.graph ?? null
      })
      if (!relevant()) return
      if (version === generation) detection.value = result
      if (selected.auto_prompt_template) {
        const item = templates.value.find(template => template.id === result.template_id)
        selected.prompt_rules = item ? { ...item.rules } : null
      }
    } catch (cause) {
      if (version === generation && props.open) error.value = String(cause)
    } finally {
      if (version === generation) detecting.value = false
    }
  }
  function setAutomatic(event: Event): void {
    draft.value.auto_prompt_template = (event.target as HTMLInputElement).checked
    if (draft.value.auto_prompt_template) void detect()
  }
  function setRules(value: ImagePromptRules | null): void {
    draft.value.auto_prompt_template = false
    draft.value.prompt_rules = value
  }
  async function previewPrompt(): Promise<void> {
    const version = ++previewVersion
    previewing.value = true
    error.value = ''
    preview.value = null
    const payload = JSON.stringify({ preset: draft.value, description: example.value })
    try {
      const result = await comfyRequest<{ positive: string; negative: string }>(
        'preview-prompt',
        JSON.parse(payload)
      )
      if (
        props.open &&
        version === previewVersion &&
        payload === JSON.stringify({ preset: draft.value, description: example.value })
      )
        preview.value = result
    } catch (cause) {
      if (props.open && version === previewVersion) error.value = String(cause)
    } finally {
      if (version === previewVersion) previewing.value = false
    }
  }
  function add(copy = false): void {
    newPreset(workspace.value, copy)
  }
  function removeDraft(): void {
    removeUnsavedPreset(workspace.value)
  }
  function result(): ComfyOptions {
    return applyPresetWorkspace(props.modelValue, workspace.value, props.profile)
  }
  return {
    workspace,
    draft,
    templates,
    error,
    detection,
    detecting,
    baseBusy,
    referenceBusy,
    previewing,
    example,
    preview,
    invalid,
    ready,
    add,
    result,
    setAutomatic,
    setRules,
    previewPrompt,
    removeDraft,
    connectionProblem
  }
}
