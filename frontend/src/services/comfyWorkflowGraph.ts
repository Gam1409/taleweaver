import type { BindingName, ComfyNode, ComfyWorkflow } from '@/types/comfyui'

/** Pure graph helpers for the workflow canvas: layout, sizing, role mapping.
 *
 * No runtime dependencies so the module stays testable under node:test. */

export interface GraphPosition {
  x: number
  y: number
}
export type PositionMap = Record<string, GraphPosition>
export interface GraphEdge {
  from: string
  fromSlot: number
  to: string
  toInput: string
}
export interface BindingTarget {
  node_id: string
  input_name: string
}
export interface BindingSuggestion {
  bindings: Partial<Record<BindingName, BindingTarget>>
  output_node: string
  notes: string[]
}
export interface NodeGeometry {
  width: number
  height: number
}

export const HEADER_H = 34
export const ROW_H = 22
export const NODE_VPADDING = 10
export const COLUMN_GAP = 120
export const ROW_GAP = 48

export const ROLE_LABELS: Record<BindingName, string> = {
  prompt: 'Prompt',
  negative_prompt: 'Negative',
  seed: 'Seed',
  width: 'Width',
  height: 'Height',
  image: 'Image'
}

export const MODEL_FIELD_LABELS: Record<string, string> = {
  ckpt_name: 'Checkpoint',
  unet_name: 'Diffusion model',
  clip_name: 'Text encoder',
  clip_name1: 'Text encoder 1',
  clip_name2: 'Text encoder 2',
  clip_name3: 'Text encoder 3',
  clip_name4: 'Text encoder 4',
  model_name: 'Upscale model',
  vae_name: 'VAE',
  lora_name: 'LoRA'
}

export const MODEL_FIELD_FOLDERS: Record<string, string> = {
  ckpt_name: 'models/checkpoints',
  unet_name: 'models/diffusion_models',
  clip_name: 'models/text_encoders',
  clip_name1: 'models/text_encoders',
  clip_name2: 'models/text_encoders',
  clip_name3: 'models/text_encoders',
  clip_name4: 'models/text_encoders',
  model_name: 'models/upscale_models',
  vae_name: 'models/vae',
  lora_name: 'models/loras'
}

export const NUMERIC_CONTROLS: Record<string, { label: string; min: number; max: number; step: number }> = {
  steps: { label: 'Steps', min: 1, max: 10000, step: 1 },
  cfg: { label: 'CFG', min: 0, max: 100, step: 0.1 },
  guidance: { label: 'Guidance', min: 0, max: 100, step: 0.1 },
  denoise: { label: 'Denoise', min: 0, max: 1, step: 0.05 },
  strength_model: { label: 'LoRA model strength', min: -100, max: 100, step: 0.05 },
  strength_clip: { label: 'LoRA encoder strength', min: -100, max: 100, step: 0.05 }
}

export const ENUM_LABELS: Record<string, string> = { sampler_name: 'Sampler', scheduler: 'Scheduler' }

/** ComfyUI-style socket palette, keyed by the wire type. */
export const SOCKET_TYPE_COLORS: Record<string, string> = {
  MODEL: '#b39bdb',
  CLIP: '#ffd54f',
  VAE: '#7ee787',
  CONDITIONING: '#ff8a3c',
  LATENT: '#ff9e9e',
  IMAGE: '#64b5f6',
  MASK: '#81c784',
  CONTROL_NET: '#6ee7b7'
}

const SOCKET_TYPES_BY_INPUT: Record<string, string> = {
  model: 'MODEL',
  unet: 'MODEL',
  clip: 'CLIP',
  clip_vision: 'CLIP',
  vae: 'VAE',
  positive: 'CONDITIONING',
  negative: 'CONDITIONING',
  conditioning: 'CONDITIONING',
  latent_image: 'LATENT',
  samples: 'LATENT',
  latents: 'LATENT',
  noise: 'LATENT',
  image: 'IMAGE',
  images: 'IMAGE',
  mask: 'MASK',
  masks: 'MASK',
  control_net: 'CONTROL_NET',
  controlnet: 'CONTROL_NET'
}

/** Wire colour for an input name; core sockets match ComfyUI, others stay neutral. */
export function socketColor(inputName: string): string {
  return SOCKET_TYPE_COLORS[SOCKET_TYPES_BY_INPUT[inputName] ?? ''] ?? '#94a3b8'
}

export function isLiteral(value: unknown): boolean {
  return typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
}

export function wantsString(role: BindingName): boolean {
  return role === 'prompt' || role === 'negative_prompt' || role === 'image'
}

/** Inputs the backend accepts for a role: string literals for text roles,
 * integer literals for numeric roles. Connected sockets never qualify. */
export function eligibleInputs(
  graph: ComfyWorkflow['graph'],
  role: BindingName
): BindingTarget[] {
  const result: BindingTarget[] = []
  const text = wantsString(role)
  for (const [id, node] of Object.entries(graph)) {
    for (const [name, value] of Object.entries(node.inputs)) {
      const ok = text
        ? typeof value === 'string'
        : typeof value === 'number' && Number.isInteger(value)
      if (ok) result.push({ node_id: id, input_name: name })
    }
  }
  return result
}

export function outputCandidates(graph: ComfyWorkflow['graph']): string[] {
  return Object.keys(graph).filter(id => graph[id].class_type.includes('SaveImage'))
}

export function edges(graph: ComfyWorkflow['graph']): GraphEdge[] {
  const result: GraphEdge[] = []
  for (const [id, node] of Object.entries(graph)) {
    for (const [name, value] of Object.entries(node.inputs)) {
      if (Array.isArray(value) && typeof value[0] === 'string' && graph[value[0]]) {
        result.push({ from: value[0], fromSlot: Number(value[1]) || 0, to: id, toInput: name })
      }
    }
  }
  return result
}

export function outputCounts(graph: ComfyWorkflow['graph']): Record<string, number> {
  const counts: Record<string, number> = {}
  for (const id of Object.keys(graph)) counts[id] = 1
  for (const edge of edges(graph)) counts[edge.from] = Math.max(counts[edge.from] || 1, edge.fromSlot + 1)
  return counts
}

function displayText(node: ComfyNode): string {
  const title = node._meta?.title || node.class_type
  return String(title).slice(0, 40)
}

/** Deterministic node box so the canvas and the layout agree. */
export function nodeSize(node: ComfyNode, outputs: number): NodeGeometry {
  const inputs = Object.keys(node.inputs)
  let chars = displayText(node).length
  for (const [name, value] of Object.entries(node.inputs)) {
    const preview = isLiteral(value) ? `${name}: ${String(value)}` : name
    chars = Math.max(chars, Math.min(preview.length, 46))
  }
  const width = Math.min(340, Math.max(180, Math.round(chars * 7.4) + 34))
  const rows = Math.max(inputs.length, outputs)
  const height = HEADER_H + Math.max(1, rows) * ROW_H + NODE_VPADDING
  return { width, height }
}

export function inputPinY(index: number): number {
  return HEADER_H + ROW_H / 2 + index * ROW_H
}

/** Stable topological order; nodes inside cycles keep insertion order at the end. */
export function topoOrder(graph: ComfyWorkflow['graph']): string[] {
  const ids = Object.keys(graph)
  const indegree: Record<string, number> = {}
  const outgoing: Record<string, string[]> = {}
  for (const id of ids) {
    indegree[id] ??= 0
    outgoing[id] ??= []
  }
  for (const edge of edges(graph)) {
    indegree[edge.to] = (indegree[edge.to] || 0) + 1
    outgoing[edge.from].push(edge.to)
  }
  const queue = ids.filter(id => !indegree[id])
  const result: string[] = []
  while (queue.length) {
    const id = queue.shift()!
    result.push(id)
    for (const next of outgoing[id]) {
      indegree[next] -= 1
      if (!indegree[next]) queue.push(next)
    }
  }
  for (const id of ids) if (!result.includes(id)) result.push(id)
  return result
}

function longestPathLayers(graph: ComfyWorkflow['graph']): Record<string, number> {
  const order = topoOrder(graph)
  const layers: Record<string, number> = {}
  for (const id of order) layers[id] = 0
  for (const id of order) {
    for (const edge of edges(graph)) {
      if (edge.to !== id) continue
      const source = layers[edge.from]
      if (source === undefined) continue
      layers[id] = Math.max(layers[id], source + 1)
    }
  }
  return layers
}

/** Left-to-right layered layout with barycenter ordering inside each column. */
export function autoLayout(graph: ComfyWorkflow['graph']): PositionMap {
  const ids = Object.keys(graph)
  if (!ids.length) return {}
  const layers = longestPathLayers(graph)
  const sizes: Record<string, NodeGeometry> = {}
  const counts = outputCounts(graph)
  for (const id of ids) sizes[id] = nodeSize(graph[id], counts[id])
  const maxLayer = Math.max(...ids.map(id => layers[id]))
  const columns: string[][] = Array.from({ length: maxLayer + 1 }, () => [])
  for (const id of ids) columns[layers[id]].push(id)

  const edgeList = edges(graph)
  const indexIn: Record<string, number> = {}
  for (const column of columns) {
    column.forEach((id, index) => {
      indexIn[id] = index
    })
  }
  for (let pass = 0; pass < 2; pass++) {
    for (let c = 1; c < columns.length; c++) {
      columns[c] = [...columns[c]].sort((a, b) => {
        const rank = (id: string) => {
          const parents = edgeList.filter(edge => edge.to === id).map(edge => indexIn[edge.from])
          if (!parents.length) return indexIn[id]
          return parents.reduce((sum, value) => sum + value, 0) / parents.length
        }
        return rank(a) - rank(b) || 0
      })
      columns[c].forEach((id, index) => {
        indexIn[id] = index
      })
    }
  }

  const positions: PositionMap = {}
  const columnHeights = columns.map(column =>
    column.reduce((sum, id) => sum + sizes[id].height + ROW_GAP, 0)
  )
  const tallest = Math.max(...columnHeights, 0)
  let x = 0
  for (let c = 0; c < columns.length; c++) {
    const column = columns[c]
    const contentHeight = columnHeights[c]
    let y = (tallest - contentHeight) / 2
    for (const id of column) {
      positions[id] = { x, y }
      y += sizes[id].height + ROW_GAP
    }
    const widest = Math.max(...column.map(id => sizes[id].width), 0)
    x += widest + COLUMN_GAP
  }
  return positions
}

export function withPositions(
  graph: ComfyWorkflow['graph'],
  positions: PositionMap
): ComfyWorkflow['graph'] {
  const clone = JSON.parse(JSON.stringify(graph)) as ComfyWorkflow['graph']
  for (const [id, position] of Object.entries(positions)) {
    const node = clone[id]
    if (node) node._meta = { ...(node._meta || {}), pos: [Math.round(position.x), Math.round(position.y)] }
  }
  return clone
}

export function existingPositions(graph: ComfyWorkflow['graph']): PositionMap | null {
  const positions: PositionMap = {}
  for (const [id, node] of Object.entries(graph)) {
    const pos = node._meta?.pos
    if (
      !Array.isArray(pos) ||
      pos.length !== 2 ||
      typeof pos[0] !== 'number' ||
      typeof pos[1] !== 'number' ||
      !Number.isFinite(pos[0]) ||
      !Number.isFinite(pos[1])
    ) {
      return null
    }
    positions[id] = { x: pos[0], y: pos[1] }
  }
  return positions
}

export function setBinding(
  workflow: ComfyWorkflow,
  role: BindingName,
  target: BindingTarget
): ComfyWorkflow {
  const value = workflow.graph[target.node_id]?.inputs[target.input_name]
  if (value === undefined) throw new Error(`Input ${target.node_id}.${target.input_name} is missing.`)
  const ok = wantsString(role) ? typeof value === 'string' : typeof value === 'number' && Number.isInteger(value)
  if (!ok) throw new Error(`The ${role} role needs a ${wantsString(role) ? 'text' : 'whole-number'} input.`)
  for (const [other, binding] of Object.entries(workflow.bindings)) {
    if (other !== role && binding.node_id === target.node_id && binding.input_name === target.input_name) {
      throw new Error(`That input already serves the ${ROLE_LABELS[other as BindingName]} role.`)
    }
  }
  const bindings = { ...workflow.bindings, [role]: { ...target } }
  return { ...workflow, bindings }
}

export function clearBinding(workflow: ComfyWorkflow, role: BindingName): ComfyWorkflow {
  if (!workflow.bindings[role]) return workflow
  const bindings = { ...workflow.bindings }
  delete bindings[role]
  return { ...workflow, bindings }
}

export function setOutput(workflow: ComfyWorkflow, nodeId: string): ComfyWorkflow {
  return { ...workflow, output_node: nodeId }
}

function firstSampler(graph: ComfyWorkflow['graph']): string[] {
  return topoOrder(graph).filter(id => {
    const kind = graph[id].class_type
    return kind.includes('KSampler') || kind.startsWith('SamplerCustom')
  })
}

function textBindingOf(graph: ComfyWorkflow['graph'], nodeId: string): BindingTarget | null {
  const node = graph[nodeId]
  if (!node) return null
  if (typeof node.inputs.text === 'string') return { node_id: nodeId, input_name: 'text' }
  const literal = Object.entries(node.inputs).find(([, value]) => typeof value === 'string')
  return literal ? { node_id: nodeId, input_name: literal[0] } : null
}

function conditionedBinding(
  graph: ComfyWorkflow['graph'],
  samplerId: string,
  socket: 'positive' | 'negative'
): BindingTarget | null {
  const value = graph[samplerId]?.inputs[socket]
  if (Array.isArray(value) && typeof value[0] === 'string') return textBindingOf(graph, value[0])
  return null
}

/** Best-effort role mapping for a freshly imported workflow, following the
 * same typing rules the backend enforces. `notes` explain every decision so
 * the preset dialog can show exactly what was detected. */
export function suggestBindings(graph: ComfyWorkflow['graph']): BindingSuggestion {
  const bindings: Partial<Record<BindingName, BindingTarget>> = {}
  const notes: string[] = []
  const describe = (target: BindingTarget | null) =>
    target ? `${target.node_id} · ${graph[target.node_id].class_type}.${target.input_name}` : 'not found'
  const samplers = firstSampler(graph)

  let prompt: BindingTarget | null = null
  let negative: BindingTarget | null = null
  for (const sampler of samplers) {
    prompt ??= conditionedBinding(graph, sampler, 'positive')
    negative ??= conditionedBinding(graph, sampler, 'negative')
  }
  if (!prompt || !negative) {
    const encoders = topoOrder(graph).filter(id => graph[id].class_type.includes('CLIPTextEncode'))
    for (const id of encoders) {
      const target = textBindingOf(graph, id)
      if (!target) continue
      const title = (graph[id]._meta?.title || '').toLowerCase()
      if (title.includes('negative')) negative ??= target
      else prompt ??= target
    }
    if (!negative && prompt) {
      for (const id of encoders) {
        const target = textBindingOf(graph, id)
        if (target && id !== prompt.node_id) {
          negative = target
          break
        }
      }
    }
  }
  if (prompt) bindings.prompt = prompt
  if (negative) bindings.negative_prompt = negative
  notes.push(`prompt → ${describe(prompt ?? null)}`)
  notes.push(`negative → ${describe(negative ?? null)}`)

  for (const role of ['seed', 'width', 'height'] as const) {
    let target: BindingTarget | null = null
    if (role === 'seed') {
      for (const sampler of samplers) {
        const inputs = graph[sampler].inputs
        for (const name of ['seed', 'noise_seed']) {
          if (typeof inputs[name] === 'number' && Number.isInteger(inputs[name])) {
            target = { node_id: sampler, input_name: name }
            break
          }
        }
        if (target) break
      }
    } else {
      for (const id of topoOrder(graph)) {
        const node = graph[id]
        if (!node.class_type.includes('EmptyLatent')) continue
        if (typeof node.inputs[role] === 'number' && Number.isInteger(node.inputs[role])) {
          target = { node_id: id, input_name: role }
          break
        }
      }
    }
    if (target) bindings[role] = target
    notes.push(`${ROLE_LABELS[role].toLowerCase()} → ${describe(target)}`)
  }

  const loaders = topoOrder(graph).filter(id => graph[id].class_type === 'LoadImage')
  const image = loaders.length ? textBindingOf(graph, loaders[0]) : null
  if (image && typeof graph[image.node_id].inputs.image === 'string') {
    bindings.image = { node_id: image.node_id, input_name: 'image' }
  }
  notes.push(`image → ${describe(bindings.image ?? null)}`)

  const saves = outputCandidates(graph)
  let output = ''
  if (saves.length === 1) {
    output = saves[0]
  } else if (saves.length > 1) {
    const order = topoOrder(graph)
    output = saves.reduce((best, id) => (order.indexOf(id) > order.indexOf(best) ? id : best), saves[0])
  }
  notes.push(`output → ${output ? `${output} · ${graph[output].class_type}` : 'not found'}`)

  return { bindings, output_node: output, notes }
}
