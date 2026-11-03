import { parseApiGraph } from '@/services/comfyWorkflowService'
import type { ComfyNode, ComfyWorkflow } from '@/types/comfyui'

/** Parsing and conversion for ComfyUI editor-workflow JSON.
 *
 * Presets and the backend speak the API format (node map with `class_type`),
 * while the ComfyUI editor saves `nodes` + `links` arrays. This module turns an
 * editor export into an API graph: bypassed/muted nodes are skipped and their
 * links resolved through them, exactly like ComfyUI's own "Export (API)". The
 * visual arrangement is kept in `_meta` (title, pos, collapsed) so the canvas
 * can show the workflow the way it looked in ComfyUI.
 *
 * No runtime dependencies so the module stays testable under node:test. */

export interface EditorSocket {
  name: string
  type?: string
  link?: number | null
  links?: number[] | null
  label?: string
  slot_index?: number
}
export interface EditorNode {
  id: number
  type: string
  pos?: [number, number]
  size?: [number, number]
  mode?: number
  flags?: { collapsed?: boolean } | null
  title?: string
  inputs?: EditorSocket[]
  outputs?: EditorSocket[]
  widgets_values?: unknown[]
  widgets_values_named?: Record<string, unknown> | null
}
/** [linkId, fromNodeId, fromSlot, toNodeId, toSlot, socketType] */
export type EditorLink = [number, number, number, number, number, string]
export interface EditorWorkflow {
  nodes: EditorNode[]
  links?: EditorLink[]
}

export interface EditorImportResult {
  graph: ComfyWorkflow['graph']
  notes: string[]
  skipped: string[]
}

const MAX_WORKFLOW_BYTES = 262144
const BYPASSED = 4
const MUTED = 2
const MAX_RESOLUTION_DEPTH = 32

/** Widget names ComfyUI renders as UI controls only; they never reach the API. */
const UI_ONLY_WIDGETS = new Set(['control_after_generate'])

/** Positional widget order for core nodes, used when an export predates
 * `widgets_values_named`. Custom nodes from that era must be re-exported. */
const POSITIONAL_WIDGETS: Record<string, string[]> = {
  CheckpointLoaderSimple: ['ckpt_name'],
  CheckpointLoader: ['config_name', 'ckpt_name', 'vae_name'],
  UNETLoader: ['unet_name', 'weight_dtype'],
  VAELoader: ['vae_name'],
  LoraLoader: ['lora_name', 'strength_model', 'strength_clip'],
  LoraLoaderOnlyModel: ['lora_name', 'strength_model'],
  CLIPVisionLoader: ['clip_name'],
  ControlNetLoader: ['control_net_name'],
  UpscaleModelLoader: ['model_name'],
  KSampler: [
    'seed',
    'control_after_generate',
    'steps',
    'cfg',
    'sampler_name',
    'scheduler',
    'denoise'
  ],
  KSamplerAdvanced: [
    'add_noise',
    'noise_seed',
    'control_after_generate',
    'steps',
    'cfg',
    'sampler_name',
    'scheduler',
    'start_at_step',
    'end_at_step',
    'return_with_leftover_noise'
  ],
  CLIPTextEncode: ['text'],
  CLIPSetLastLayer: ['stop_at_clip_layer'],
  EmptyLatentImage: ['width', 'height', 'batch_size'],
  LatentUpscale: ['upscale_method', 'width', 'height', 'crop'],
  VAEDecode: [],
  VAEEncode: [],
  SaveImage: ['filename_prefix'],
  PreviewImage: ['filename_prefix'],
  LoadImage: ['image', 'upload'],
  LoadImageMask: ['image', 'channel', 'upload']
}

export function looksLikeEditorWorkflow(value: unknown): boolean {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const nodes = (value as { nodes?: unknown }).nodes
  return (
    Array.isArray(nodes) &&
    nodes.length > 0 &&
    nodes.every(
      node =>
        node &&
        typeof node === 'object' &&
        typeof (node as EditorNode).type === 'string' &&
        typeof (node as EditorNode).id === 'number'
    )
  )
}

export function parseEditorWorkflow(text: string): EditorWorkflow {
  if (new TextEncoder().encode(text).length > MAX_WORKFLOW_BYTES)
    throw new Error('Maximum workflow size is 256 KiB.')
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    throw new Error('The file is not valid JSON.')
  }
  if (!looksLikeEditorWorkflow(parsed)) {
    throw new Error('Export a workflow from the ComfyUI editor (Save) or use the API export.')
  }
  const workflow = parsed as EditorWorkflow
  if (workflow.nodes.length > 256) throw new Error('Workflows are limited to 256 nodes.')
  const ids = new Set(workflow.nodes.map(node => node.id))
  if (ids.size !== workflow.nodes.length)
    throw new Error('The workflow contains duplicate node ids.')
  return workflow
}

function widgetValues(node: EditorNode, notes: string[]): Record<string, unknown> {
  const named = node.widgets_values_named
  if (named && typeof named === 'object' && !Array.isArray(named)) {
    const values: Record<string, unknown> = {}
    for (const [name, value] of Object.entries(named)) {
      if (!UI_ONLY_WIDGETS.has(name)) values[name] = value
    }
    return values
  }
  const widgets = node.widgets_values
  if (!Array.isArray(widgets) || widgets.length === 0) return {}
  const positional = POSITIONAL_WIDGETS[node.type]
  if (!positional) {
    notes.push(
      `Node ${node.id} (${node.type}) comes from an old export without named widget values; re-export from an up-to-date ComfyUI or fill its values in the JSON editor.`
    )
    return {}
  }
  const values: Record<string, unknown> = {}
  positional.forEach((name, index) => {
    if (index < widgets.length && !UI_ONLY_WIDGETS.has(name)) values[name] = widgets[index]
  })
  return values
}

/** Follows a link to the first active node; bypassed nodes pass their input
 * through (like ComfyUI), muted nodes break the chain. Returns null when the
 * connection disappears. */
function resolveSource(
  nodesById: Map<number, EditorNode>,
  linksById: Map<number, EditorLink>,
  nodeId: number,
  slot: number,
  depth = 0
): { id: string; slot: number } | null {
  const node = nodesById.get(nodeId)
  if (!node) return null
  if (node.mode !== BYPASSED && node.mode !== MUTED) return { id: String(nodeId), slot }
  if (depth > MAX_RESOLUTION_DEPTH || node.mode === MUTED) return null
  const outputType = (node.outputs ?? [])[slot]?.type
  const connected = (node.inputs ?? []).filter(
    input => typeof input.link === 'number' && linksById.has(input.link)
  )
  const match =
    connected.find(input => !outputType || input.type === outputType) ??
    (outputType ? undefined : connected[0])
  const sourceLink = match ? linksById.get(match.link as number) : undefined
  return sourceLink
    ? resolveSource(nodesById, linksById, sourceLink[1], sourceLink[2], depth + 1)
    : null
}

export function editorToApiGraph(editor: EditorWorkflow): EditorImportResult {
  const notes: string[] = []
  const skipped: string[] = []
  const nodesById = new Map(editor.nodes.map(node => [node.id, node]))
  const linksById = new Map<number, EditorLink>((editor.links ?? []).map(link => [link[0], link]))

  const graph: ComfyWorkflow['graph'] = {}
  for (const node of editor.nodes) {
    if (node.mode === BYPASSED || node.mode === MUTED) {
      skipped.push(String(node.id))
      continue
    }
    const inputs: Record<string, unknown> = {}
    for (const input of node.inputs ?? []) {
      if (typeof input.link !== 'number') continue
      const link = linksById.get(input.link)
      if (!link) continue
      const source = resolveSource(nodesById, linksById, link[1], link[2])
      if (source) inputs[input.name] = [source.id, source.slot]
    }
    for (const [name, value] of Object.entries(widgetValues(node, notes))) {
      if (inputs[name] === undefined) inputs[name] = value
    }
    const meta: NonNullable<ComfyNode['_meta']> = { title: node.title || node.type }
    if (Array.isArray(node.pos) && node.pos.length === 2) {
      meta.pos = [Math.round(node.pos[0]), Math.round(node.pos[1])]
    }
    if (node.flags?.collapsed) meta.collapsed = true
    graph[String(node.id)] = { class_type: node.type, inputs, _meta: meta }
  }
  if (skipped.length) {
    notes.push(
      `${skipped.length} bypassed or muted node(s) skipped, exactly like ComfyUI's API export: ${skipped.join(', ')}.`
    )
  }
  return { graph, notes, skipped }
}

/** Accepts either export format and always returns an API graph. */
export function importWorkflowGraph(text: string): EditorImportResult {
  if (new TextEncoder().encode(text).length > MAX_WORKFLOW_BYTES) {
    throw new Error('Maximum workflow size is 256 KiB.')
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    throw new Error('The file is not valid JSON.')
  }
  if (looksLikeEditorWorkflow(parsed)) return editorToApiGraph(parseEditorWorkflow(text))
  return { graph: parseApiGraph(text), notes: [], skipped: [] }
}
