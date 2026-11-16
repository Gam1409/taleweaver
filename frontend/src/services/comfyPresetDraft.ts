import { rememberWorkflows } from './comfyLibrary'
import type { PresetAssignment } from './imagePurposes'
import type { ComfyOptions, ComfyPreset } from '@/types/comfyui'

export interface PresetWorkspace {
  presets: Record<string, ComfyPreset>
  selectedId: string
  url: string
  timeout: number
  workflows: NonNullable<ComfyOptions['comfyui_workflows']>
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
export function addStarterPreset(workspace: PresetWorkspace, preset: ComfyPreset): void {
  const current = workspace.presets[workspace.selectedId]
  const blank =
    current?.name === 'New preset' &&
    !current.generate &&
    !current.reference &&
    !workspace.baseline.comfyui_presets?.[workspace.selectedId]
  const id = blank ? workspace.selectedId : newPreset(workspace)
  workspace.presets[id] = clonePresetData(preset)
}

export function presetWorkspace(
  options: ComfyOptions,
  profile: PresetAssignment,
  fallbackProfile?: 'simple' | 'advanced'
): PresetWorkspace {
  const presets = clonePresetData(options.comfyui_presets ?? {})
  const assigned =
    options.comfyui_assignments?.[profile] ??
    (fallbackProfile ? options.comfyui_assignments?.[fallbackProfile] : undefined) ??
    ''
  const workspace: PresetWorkspace = {
    presets,
    selectedId: presets[assigned] ? assigned : (Object.keys(presets)[0] ?? ''),
    url: options.comfyui_url,
    timeout: options.comfyui_timeout,
    workflows: rememberWorkflows(options.comfyui_workflows ?? {}, presets, false),
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
  if (preset.generate?.bindings.image)
    return 'Move the image-input workflow to the Reference variant.'
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
  const workflows = { ...current.comfyui_workflows, ...workspace.workflows }
  for (const id of Object.keys(workspace.baseline.comfyui_workflows ?? {})) {
    if (!workspace.workflows[id]) delete workflows[id]
  }
  const edited = Object.fromEntries(
    changedPresets(workspace).map(id => [id, clonePresetData(workspace.presets[id]!)])
  )
  const presets = { ...current.comfyui_presets, ...edited }
  const assignments = { ...current.comfyui_assignments }
  const removed = Object.keys(workspace.baseline.comfyui_presets ?? {}).filter(
    id => !workspace.presets[id]
  )
  for (const id of removed) {
    if (
      current.comfyui_presets?.[id] &&
      JSON.stringify(current.comfyui_presets[id]) !==
        JSON.stringify(workspace.baseline.comfyui_presets?.[id])
    )
      throw new Error(
        'A preset marked for removal changed elsewhere. Reopen the preset library before deleting it.'
      )
    delete presets[id]
  }
  for (const task of Object.keys(assignments) as PresetAssignment[]) {
    if (removed.includes(assignments[task] ?? '')) delete assignments[task]
  }
  return {
    ...current,
    comfyui_url:
      workspace.url !== workspace.baseline.comfyui_url ? workspace.url : current.comfyui_url,
    comfyui_timeout:
      workspace.timeout !== workspace.baseline.comfyui_timeout
        ? workspace.timeout
        : current.comfyui_timeout,
    comfyui_workflows: rememberWorkflows(workflows, edited),
    comfyui_presets: presets,
    comfyui_test_preset: removed.includes(current.comfyui_test_preset ?? '')
      ? null
      : current.comfyui_test_preset,
    comfyui_assignments: { ...assignments, [profile]: workspace.selectedId }
  }
}

export function removePreset(workspace: PresetWorkspace): void {
  if (Object.keys(workspace.presets).length <= 1) return
  delete workspace.presets[workspace.selectedId]
  workspace.selectedId = Object.keys(workspace.presets)[0]!
}
