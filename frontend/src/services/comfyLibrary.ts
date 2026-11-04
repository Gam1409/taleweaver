import type { ComfyPreset, ComfyWorkflow, ComfyWorkflowVersion } from '@/types/comfyui'
export interface PresetFilter {
  query: string
  task: string
  reference: string
}
export function filterPresets(presets: Record<string, ComfyPreset>, filter: PresetFilter) {
  const query = filter.query.trim().toLocaleLowerCase()
  return Object.entries(presets).filter(([, preset]) => {
    const searchable = [
      preset.name,
      ...(preset.style_tags ?? []),
      ...(preset.purpose_tags ?? []),
      preset.prompt_rules?.template_id ?? ''
    ]
      .join(' ')
      .toLocaleLowerCase()
    return (
      (!query || searchable.includes(query)) &&
      (!filter.task || preset.purpose_tags?.some(task => task === filter.task)) &&
      (filter.reference !== 'yes' || Boolean(preset.reference?.bindings.image)) &&
      (filter.reference !== 'no' || !preset.reference)
    )
  })
}
export function workflowDependencies(workflow: ComfyWorkflow | null): string[] {
  const extensions = /\.(safetensors|ckpt|pt|pth|bin|gguf)$/i
  return [
    ...new Set(
      Object.values(workflow?.graph ?? {}).flatMap(node =>
        Object.entries(node.inputs)
          .filter(
            ([key, value]) =>
              typeof value === 'string' &&
              (extensions.test(value) ||
                /^(ckpt_name|unet_name|vae_name|clip_name\d*|lora_name|model_name)$/.test(key))
          )
          .map(([key, value]) => `${node.class_type} · ${key}: ${value}`)
      )
    )
  ]
}
export function rememberWorkflows(
  library: Record<string, ComfyWorkflowVersion>,
  presets: Record<string, ComfyPreset>,
  strict = true
): Record<string, ComfyWorkflowVersion> {
  const result = { ...library }
  const workflows = Object.values(presets).flatMap(preset => [preset.generate, preset.reference])
  for (const workflow of workflows) {
    if (
      !workflow ||
      Object.values(result).some(item => JSON.stringify(item.workflow) === JSON.stringify(workflow))
    )
      continue
    if (Object.keys(result).length >= 128 && !strict) continue
    if (Object.keys(result).length >= 128)
      throw new Error('The workflow library is full (128 versions). Remove unused versions first.')
    const siblings = Object.values(result).filter(item => item.workflow.name === workflow.name)
    const revision = Math.max(0, ...siblings.map(item => item.revision)) + 1
    result[
      globalThis.crypto?.randomUUID?.() ??
        `workflow-${Date.now()}-${Math.random().toString(36).slice(2)}`
    ] = { revision, workflow: JSON.parse(JSON.stringify(workflow)) }
  }
  return result
}
