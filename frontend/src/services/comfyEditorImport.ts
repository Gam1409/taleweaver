import { parseApiGraph } from '@/services/comfyWorkflowService'
import type { ComfyNode, ComfyWorkflow } from '@/types/comfyui'

/** Parsing and conversion for ComfyUI editor-workflow JSON.
 *
 * Presets and the backend speak the API format (node map with `class_type`),
 * while the ComfyUI editor saves `nodes` + `links` arrays. This module turns an
 * editor export into an API graph: bypassed/muted nodes are skipped and their
 * links resolved through them, editor-only nodes (Reroute, PrimitiveNode,
 * Note) are resolved or dropped, exactly like ComfyUI's own "Export (API)".
 * The visual arrangement is kept in `_meta` (title, pos, collapsed) so the
 * canvas can show the workflow the way it looked in ComfyUI.
 *
 * Legacy positional `widgets_values` are named from the live `/object_info` of
 * the user's ComfyUI server (passed in as `schemas`), so any custom node pack
 * imports correctly. POSITIONAL_WIDGETS below is only an offline fallback for
 * core nodes when the server is unreachable.
 *
 * No runtime dependencies so the module stays testable under node:test. */

export interface EditorSocket {
  name: string
  type?: string
  link?: number | null
  links?: number[] | null
  label?: string
  slot_index?: number
  /** Widgets converted to inputs keep their value here when unlinked. */
  widget?: { name?: string; value?: unknown } | null
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

/** One input of a node class as reported by the live ComfyUI `/object_info`:
 * the editor renders combo/STRING/INT/FLOAT/BOOLEAN as widgets and everything
 * else (MODEL, CLIP, VAE, custom socket types) as connectable sockets. */
export interface SchemaInput {
  name: string
  kind: 'combo' | 'string' | 'int' | 'float' | 'boolean' | 'socket'
}
/** Live node definitions by class, served by the backend `/node-schemas`. */
export type NodeSchemas = Record<string, SchemaInput[]>
export type SchemaFetcher = (classes: string[]) => Promise<NodeSchemas>

const MAX_WORKFLOW_BYTES = 262144
const BYPASSED = 4
const MUTED = 2
const MAX_RESOLUTION_DEPTH = 32

/** Widget names ComfyUI renders as UI controls only; they never reach the API. */
const UI_ONLY_WIDGETS = new Set(['control_after_generate', '__image_upload__'])

/** Node types defined by the editor itself; they never execute on the server.
 * Reroutes pass their links through, PrimitiveNode feeds a literal value,
 * Notes carry no data — ComfyUI's API export never contains them. */
const EDITOR_ONLY_TYPES = new Set(['Reroute', 'Note', 'MarkdownNote', 'PrimitiveNode'])

/** Offline fallback of positional widget orders for core nodes, used only when
 * the user's ComfyUI server could not be asked for `/object_info` (or the class
 * is missing there). Custom nodes need the live registry — they can't be
 * hardcoded. */
const POSITIONAL_WIDGETS: Record<string, string[]> = {
  CheckpointLoaderSimple: ['ckpt_name'],
  CheckpointLoader: ['config_name', 'ckpt_name', 'vae_name'],
  UNETLoader: ['unet_name', 'weight_dtype'],
  VAELoader: ['vae_name'],
  LoraLoader: ['lora_name', 'strength_model', 'strength_clip'],
  LoraLoaderModelOnly: ['lora_name', 'strength_model'],
  CLIPVisionLoader: ['clip_name'],
  ControlNetLoader: ['control_net_name'],
  UpscaleModelLoader: ['model_name'],
  CLIPLoader: ['clip_name', 'type'],
  DualCLIPLoader: ['clip_name1', 'clip_name2', 'type'],
  QuadrupleCLIPLoader: ['clip_name1', 'clip_name2', 'clip_name3', 'clip_name4'],
  CLIPTextEncode: ['text'],
  CLIPSetLastLayer: ['stop_at_clip_layer'],
  EmptyLatentImage: ['width', 'height', 'batch_size'],
  EmptySD3LatentImage: ['width', 'height', 'batch_size'],
  EmptyMochiLatentVideo: ['width', 'height', 'length', 'batch_size'],
  LatentUpscale: ['upscale_method', 'width', 'height', 'crop'],
  ImageScale: ['upscale_method', 'width', 'height', 'crop'],
  ImageScaleBy: ['upscale_method', 'scale_by'],
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
  VAEDecode: [],
  VAEEncode: [],
  SaveImage: ['filename_prefix'],
  PreviewImage: ['filename_prefix'],
  LoadImage: ['image', '__image_upload__'],
  LoadImageMask: ['image', 'channel', '__image_upload__']
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
  return parseEditorWorkflowValue(parsed)
}

export function parseEditorWorkflowValue(parsed: unknown): EditorWorkflow {
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

/** Widget order for legacy positional `widgets_values`, derived from the live
 * `/object_info` of the user's ComfyUI server — works for any installed custom
 * node pack. Returns null when no server schema is available for the class.
 * Widgets converted to inputs hold their value on the input itself, and INT
 * widgets named like a seed get a UI-only control_after_generate after them,
 * exactly as the editor renders them. */
function widgetLayoutFromSchema(
  schemas: NodeSchemas | null | undefined,
  node: EditorNode
): string[] | null {
  const schema = schemas?.[node.type]
  if (!Array.isArray(schema)) return null
  const converted = new Set(
    (node.inputs ?? [])
      .filter(input => input.widget && typeof input.widget.name === 'string')
      .map(input => input.widget?.name as string)
  )
  const layout: string[] = []
  for (const entry of schema) {
    if (entry.kind === 'socket') continue
    if (converted.has(entry.name)) continue
    layout.push(entry.name)
    if (entry.kind === 'int' && /seed/i.test(entry.name)) layout.push('control_after_generate')
  }
  // Core image loaders serialize the upload button alongside input widgets.
  // It is not an API input and is absent from /object_info.
  if (
    (node.type === 'LoadImage' || node.type === 'LoadImageMask') &&
    layout.includes('image') && node.widgets_values?.length === layout.length + 1
  ) layout.push('__image_upload__')
  return layout
}

function widgetValues(
  node: EditorNode,
  notes: string[],
  schemas: NodeSchemas | null | undefined
): Record<string, unknown> {
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
  const layout = widgetLayoutFromSchema(schemas, node)
  if (layout) {
    if (layout.length !== widgets.length) {
      notes.push(
        `Node ${node.id} (${node.type}): the export stores ${widgets.length} widget values but your ComfyUI server defines ${layout.length}; its widgets were skipped instead of guessing. Re-export the workflow or fix the values in the JSON editor.`
      )
      return {}
    }
    const values: Record<string, unknown> = {}
    layout.forEach((name, index) => {
      if (!UI_ONLY_WIDGETS.has(name)) values[name] = widgets[index]
    })
    return values
  }
  const positional = POSITIONAL_WIDGETS[node.type]
  if (!positional) {
    notes.push(
      schemas
        ? `Node ${node.id} (${node.type}) is unknown to your ComfyUI server or exports no widget schema; check that its node pack is installed, or fill the values in the JSON editor.`
        : `Node ${node.id} (${node.type}) comes from an old export without named widget values; re-export from an up-to-date ComfyUI or fill its values in the JSON editor.`
    )
    return {}
  }
  const values: Record<string, unknown> = {}
  positional.forEach((name, index) => {
    if (index < widgets.length && !UI_ONLY_WIDGETS.has(name)) values[name] = widgets[index]
  })
  return values
}

function primitiveValue(node: EditorNode): unknown {
  const named = node.widgets_values_named
  if (named && typeof named === 'object' && !Array.isArray(named)) {
    for (const [name, value] of Object.entries(named)) {
      if (!UI_ONLY_WIDGETS.has(name)) return value
    }
    return undefined
  }
  const values = node.widgets_values
  return Array.isArray(values) && values.length > 0 ? values[0] : undefined
}

type ResolvedSource = { id: string; slot: number } | { value: unknown }

/** Follows a link to the first active node; bypassed nodes pass their input
 * through (like ComfyUI), muted nodes break the chain. Editor-only Reroutes
 * pass through as well and PrimitiveNode feeds its literal widget value.
 * Returns null when the connection disappears. */
function resolveSource(
  nodesById: Map<number, EditorNode>,
  linksById: Map<number, EditorLink>,
  nodeId: number,
  slot: number,
  depth = 0
): ResolvedSource | null {
  const node = nodesById.get(nodeId)
  if (!node || depth > MAX_RESOLUTION_DEPTH) return null
  if (node.type === 'PrimitiveNode') {
    const value = primitiveValue(node)
    return value === undefined ? null : { value }
  }
  if (node.type === 'Reroute') {
    const input = (node.inputs ?? [])[0]
    if (!input || typeof input.link !== 'number') return null
    const link = linksById.get(input.link)
    if (!link) return null
    return resolveSource(nodesById, linksById, link[1], link[2], depth + 1)
  }
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

export function editorToApiGraph(
  editor: EditorWorkflow,
  schemas?: NodeSchemas | null
): EditorImportResult {
  const notes: string[] = []
  const skipped: string[] = []
  const editorOnly: string[] = []
  const nodesById = new Map(editor.nodes.map(node => [node.id, node]))
  const linksById = new Map<number, EditorLink>((editor.links ?? []).map(link => [link[0], link]))

  const graph: ComfyWorkflow['graph'] = {}
  for (const node of editor.nodes) {
    if (EDITOR_ONLY_TYPES.has(node.type)) {
      editorOnly.push(`${node.type}#${node.id}`)
      continue
    }
    if (node.mode === BYPASSED || node.mode === MUTED) {
      skipped.push(String(node.id))
      continue
    }
    const inputs: Record<string, unknown> = {}
    for (const input of node.inputs ?? []) {
      if (typeof input.link === 'number') {
        const link = linksById.get(input.link)
        if (!link) continue
        const source = resolveSource(nodesById, linksById, link[1], link[2])
        if (!source) continue
        inputs[input.name] = 'value' in source ? source.value : [source.id, source.slot]
      } else if (
        input.widget &&
        typeof input.widget.name === 'string' &&
        input.widget.value !== undefined
      ) {
        inputs[input.widget.name] = input.widget.value
      }
    }
    for (const [name, value] of Object.entries(widgetValues(node, notes, schemas))) {
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
  if (editorOnly.length) {
    notes.push(
      `${editorOnly.length} editor-only node(s) skipped, exactly like ComfyUI's API export: ${editorOnly.join(', ')}.`
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
  if (looksLikeEditorWorkflow(parsed)) return editorToApiGraph(parseEditorWorkflowValue(parsed))
  return { graph: parseApiGraph(text), notes: [], skipped: [] }
}

/** Accepts either export format and always returns an API graph. For editor
 * exports it first asks the user's ComfyUI server for the real widget order of
 * every node class — core or custom — so legacy positional `widgets_values`
 * are named correctly. Without a reachable server the built-in core table is
 * the only fallback. */
export async function importWorkflowGraphWithServer(
  text: string,
  fetchSchemas?: SchemaFetcher
): Promise<EditorImportResult> {
  if (new TextEncoder().encode(text).length > MAX_WORKFLOW_BYTES) {
    throw new Error('Maximum workflow size is 256 KiB.')
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    throw new Error('The file is not valid JSON.')
  }
  if (!looksLikeEditorWorkflow(parsed)) return importWorkflowGraph(text)
  const editor = parseEditorWorkflowValue(parsed)
  const notes: string[] = []
  const classes = [...new Set(editor.nodes.map(node => node.type))]
  let schemas: NodeSchemas | null = null
  if (fetchSchemas && classes.length > 0) {
    try {
      schemas = await fetchSchemas(classes)
    } catch {
      notes.push(
        'ComfyUI node definitions were not fetched (server unreachable or URL unset); core nodes use built-in layouts and legacy custom-node widgets may stay unnamed.'
      )
    }
  }
  const result = editorToApiGraph(editor, schemas)
  result.notes.unshift(...notes)
  return result
}
