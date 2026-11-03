import type { PresetAssignment } from './imagePurposes'
import type { ComfyOptions, ComfyPreset } from '@/types/comfyui'

export interface PresetWorkspace {
  presets: Record<string, ComfyPreset>
  selectedId: string
  url: string
  timeout: number
  baseline: ComfyOptions
}
export const clonePresetData = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T
const newId = () =>
  globalThis.crypto?.randomUUID?.() ?? `preset-${Date.now()}-${Math.random().toString(36).slice(2)}`

export function newPreset(workspace: PresetWorkspace, copy = false): string {
  if (Object.keys(workspace.presets).length >= 32)
    throw new Error('The preset library can contain at most 32 presets.')
  const current = workspace.presets[workspace.selectedId]
  const preset: ComfyPreset =
    copy && current
      ? clonePresetData(current)
      : {
          name: 'New preset',
          generate: null,
          reference: null,
          prompt_rules: null,
          auto_prompt_template: true
        }
  if (copy && current) preset.name = `${current.name.slice(0, 115)} copy`
  const id = newId()
  workspace.presets[id] = preset
  workspace.selectedId = id
  return id
}
export function presetWorkspace(
  options: ComfyOptions,
  profile: PresetAssignment,
  fallbackProfile?: 'simple' | 'advanced'
): PresetWorkspace {
  const presets = clonePresetData(options.comfyui_presets ?? {})
  const assigned = options.comfyui_assignments?.[profile]
    ?? (fallbackProfile ? options.comfyui_assignments?.[fallbackProfile] : undefined) ?? ''
  const workspace: PresetWorkspace = {
    presets,
    selectedId: presets[assigned] ? assigned : (Object.keys(presets)[0] ?? ''),
    url: options.comfyui_url,
    timeout: options.comfyui_timeout,
    baseline: clonePresetData(options)
  }
  if (!workspace.selectedId) newPreset(workspace)
  return workspace
}
export function changedPresets(workspace: PresetWorkspace): string[] {
  return Object.keys(workspace.presets).filter(
    id =>
      JSON.stringify(workspace.presets[id]) !==
      JSON.stringify(workspace.baseline.comfyui_presets?.[id])
  )
}
export function presetProblem(preset: ComfyPreset): string {
  if (!preset.name.trim()) return 'Enter a preset name.'
  if (!preset.generate?.bindings.prompt || !preset.generate.output_node)
    return 'Configure the base workflow and its required inputs.'
  if (
    preset.reference &&
    (!preset.reference.bindings.prompt ||
      !preset.reference.bindings.image ||
      !preset.reference.output_node)
  )
    return 'Complete the reference workflow inputs.'
  if (preset.auto_prompt_template && !preset.prompt_rules)
    return 'Choose a prompt template or complete model detection.'
  return ''
}
export function applyPresetWorkspace(
  current: ComfyOptions,
  workspace: PresetWorkspace,
  profile: PresetAssignment
): ComfyOptions {
  const edited = Object.fromEntries(
    changedPresets(workspace).map(id => [id, clonePresetData(workspace.presets[id]!)])
  )
  return {
    ...current,
    comfyui_url:
      workspace.url !== workspace.baseline.comfyui_url ? workspace.url : current.comfyui_url,
    comfyui_timeout:
      workspace.timeout !== workspace.baseline.comfyui_timeout
        ? workspace.timeout
        : current.comfyui_timeout,
    comfyui_presets: { ...current.comfyui_presets, ...edited },
    comfyui_assignments: { ...current.comfyui_assignments, [profile]: workspace.selectedId }
  }
}

export function removeUnsavedPreset(workspace: PresetWorkspace): void {
  if (
    workspace.baseline.comfyui_presets?.[workspace.selectedId] ||
    Object.keys(workspace.presets).length <= 1
  )
    return
  delete workspace.presets[workspace.selectedId]
  workspace.selectedId = Object.keys(workspace.presets)[0]!
}
