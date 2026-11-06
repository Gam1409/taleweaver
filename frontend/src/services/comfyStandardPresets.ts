import type { ComfyOptions } from '@/types/comfyui'
import type { ImagePurpose } from './imagePurposes'
import type { PresetWorkspace } from './comfyPresetDraft'
import { clonePresetData } from './comfyPresetDraft'
import { rememberWorkflows } from './comfyLibrary'

export type StandardPresetBundle = Pick<ComfyOptions, 'comfyui_presets' | 'comfyui_workflows'>

export function addStandardPresets(workspace: PresetWorkspace, bundle: StandardPresetBundle, purpose?: ImagePurpose): number {
  const additions = Object.fromEntries(Object.entries(bundle.comfyui_presets ?? {})
    .filter(([id]) => !workspace.presets[id]))
  const count = Object.keys(additions).length
  if (Object.keys(workspace.presets).length + count > 32)
    throw new Error(`Adding ${count} standard presets would exceed the library limit of 32. Remove unused presets first.`)
  const presets = clonePresetData(additions)
  const workflows = rememberWorkflows(workspace.workflows, presets)
  workspace.presets = { ...workspace.presets, ...presets }
  workspace.workflows = workflows
  const preferred = `standard-anima-${purpose ?? 'npc'}`
  if (count && preferred in additions) workspace.selectedId = preferred
  return count
}
