<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { LayoutGrid, Maximize2, Wand2, X, ZoomIn, ZoomOut } from 'lucide-vue-next'
import { useComfyModelOptions } from '@/composables/useComfyModelOptions'
import ComfyModelField from './ComfyModelField.vue'
import {
  ENUM_LABELS,
  HEADER_H,
  MODEL_FIELD_FOLDERS,
  MODEL_FIELD_LABELS,
  ROLE_LABELS,
  autoLayout,
  clearBinding,
  edges as graphEdges,
  eligibleInputs,
  existingPositions,
  inputPinY,
  isLiteral,
  nodeSize,
  outputCounts,
  setBinding,
  socketColor,
  suggestBindings,
  withPositions,
  type BindingTarget,
  type PositionMap
} from '@/services/comfyWorkflowGraph'
import type { BindingName, ComfyWorkflow } from '@/types/comfyui'

const props = defineProps<{ modelValue: ComfyWorkflow; url: string; reference?: boolean; expanded?: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: ComfyWorkflow): void; (e: 'busy', value: boolean): void }>()

interface InputRow {
  name: string
  literal: boolean
  connectedFrom: string | null
  preview: string
  eligible: boolean
}
interface NodeView {
  id: string
  title: string
  classType: string
  family: string
  x: number
  y: number
  width: number
  height: number
  collapsed: boolean
  inputs: InputRow[]
  roles: BindingName[]
  isOutput: boolean
  outputHint: boolean
}

const container = ref<HTMLDivElement>()
const positions = ref<PositionMap>({})
const view = ref({ x: 40, y: 40, k: 1 })
const selected = ref('')
const assignRole = ref<BindingName | 'output' | null>(null)
const note = ref('')
const fittedOnce = ref(false)
const { choicesFor } = useComfyModelOptions(props, value => emit('busy', value))

const graph = computed(() => props.modelValue.graph)
const roles = computed<BindingName[]>(() =>
  props.reference
    ? ['prompt', 'negative_prompt', 'seed', 'width', 'height', 'image']
    : ['prompt', 'negative_prompt', 'seed', 'width', 'height']
)

const isCollapsed = (id: string): boolean => graph.value[id]?._meta?.collapsed === true

const geometries = computed(() => {
  const counts = outputCounts(graph.value)
  const result: Record<string, { width: number; height: number }> = {}
  for (const [id, node] of Object.entries(graph.value)) {
    const size = nodeSize(node, counts[id])
    result[id] = isCollapsed(id) ? { width: size.width, height: HEADER_H } : size
  }
  return result
})

const edgeViews = computed(() => {
  const views: { d: string; color: string }[] = []
  for (const edge of graphEdges(graph.value)) {
    const target = graph.value[edge.to]
    const from = positions.value[edge.from]
    const to = positions.value[edge.to]
    const size = geometries.value[edge.from]
    if (!from || !to || !size || !target) continue
    const inputIndex = Object.keys(target.inputs).indexOf(edge.toInput)
    const x1 = from.x + size.width
    const y1 = from.y + (isCollapsed(edge.from) ? HEADER_H / 2 : inputPinY(edge.fromSlot))
    const x2 = to.x
    const y2 = to.y + (isCollapsed(edge.to) ? HEADER_H / 2 : inputPinY(Math.max(0, inputIndex)))
    const bend = Math.max(40, Math.abs(x2 - x1) / 2)
    views.push({
      d: `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`,
      color: socketColor(edge.toInput)
    })
  }
  return views
})

const nodeViews = computed<NodeView[]>(() => {
  const roleByInput: Record<string, BindingName> = {}
  for (const role of Object.keys(props.modelValue.bindings) as BindingName[]) {
    const binding = props.modelValue.bindings[role]
    if (binding) roleByInput[`${binding.node_id}.${binding.input_name}`] = role
  }
  const eligible =
    assignRole.value && assignRole.value !== 'output'
      ? new Set(eligibleInputs(graph.value, assignRole.value).map(t => `${t.node_id}.${t.input_name}`))
      : null
  return Object.entries(graph.value).map(([id, node]) => {
    const position = positions.value[id] || { x: 0, y: 0 }
    const size = geometries.value[id]
    const inputs: InputRow[] = Object.entries(node.inputs).map(([name, value]) => {
      const connected = Array.isArray(value) && typeof value[0] === 'string'
      return {
        name,
        literal: isLiteral(value),
        connectedFrom: connected ? String(value[0]) : null,
        preview: isLiteral(value) ? String(value).slice(0, 34) : '',
        eligible: eligible ? eligible.has(`${id}.${name}`) : false
      }
    })
    return {
      id,
      title: node._meta?.title || node.class_type,
      classType: node.class_type,
      family: familyOf(node.class_type),
      x: position.x,
      y: position.y,
      width: size.width,
      height: size.height,
      collapsed: isCollapsed(id),
      inputs,
      roles: (Object.keys(props.modelValue.bindings) as BindingName[]).filter(
        role => props.modelValue.bindings[role]?.node_id === id
      ),
      isOutput: props.modelValue.output_node === id,
      outputHint: assignRole.value === 'output' && node.class_type.includes('SaveImage')
    }
  })
})

const selectedNode = computed(() => nodeViews.value.find(node => node.id === selected.value))
const selectedValues = computed<Record<string, unknown>>(
  () => (selected.value && graph.value[selected.value]?.inputs) || {}
)

function familyOf(classType: string): string {
  if (classType.includes('SaveImage') || classType === 'LoadImage') return 'image'
  if (classType.includes('KSampler') || classType.startsWith('SamplerCustom')) return 'sampler'
  if (classType.includes('TextEncode')) return 'encoder'
  if (classType.includes('Load')) return 'loader'
  if (classType.includes('EmptyLatent')) return 'latent'
  return 'plain'
}

const familyClasses: Record<string, string> = {
  image: 'bg-[#3e8c7b]',
  sampler: 'bg-[#b3543f]',
  encoder: 'bg-[#a68b2f]',
  loader: 'bg-[#7c6bb0]',
  latent: 'bg-[#a85846]',
  plain: 'bg-slate-700'
}
const roleChipClasses: Record<string, string> = {
  prompt: 'bg-emerald-500 text-slate-950',
  negative_prompt: 'bg-rose-500 text-slate-950',
  seed: 'bg-violet-500 text-slate-950',
  width: 'bg-amber-400 text-slate-950',
  height: 'bg-amber-600 text-slate-950',
  image: 'bg-sky-400 text-slate-950'
}
const roleBadgeClasses: Record<string, string> = {
  prompt: 'border-emerald-400/70 text-emerald-300',
  negative_prompt: 'border-rose-400/70 text-rose-300',
  seed: 'border-violet-400/70 text-violet-300',
  width: 'border-amber-400/70 text-amber-200',
  height: 'border-amber-500/70 text-amber-200',
  image: 'border-sky-400/70 text-sky-300'
}

function shortTarget(role: BindingName): string {
  const binding = props.modelValue.bindings[role]
  return binding ? `${binding.node_id}.${binding.input_name}` : ''
}

function startAssign(role: BindingName | 'output'): void {
  assignRole.value = assignRole.value === role ? null : role
  note.value =
    assignRole.value === 'output'
      ? 'Click the SaveImage node that receives the final image.'
      : assignRole.value
        ? `Click the ${ROLE_LABELS[assignRole.value]} input on a node.`
        : ''
}

function assignTo(target: BindingTarget): void {
  if (!assignRole.value || assignRole.value === 'output') return
  try {
    let next = setBinding(props.modelValue, assignRole.value, target)
    next = { ...next, graph: withPositions(next.graph, positions.value) }
    emit('update:modelValue', next)
    note.value = `${ROLE_LABELS[assignRole.value]} → ${target.node_id}.${target.input_name}`
    assignRole.value = null
  } catch (err) {
    note.value = err instanceof Error ? err.message : 'Could not set the role.'
  }
}

function clearRole(role: BindingName | 'output'): void {
  if (role === 'output') emit('update:modelValue', { ...props.modelValue, output_node: '' })
  else emit('update:modelValue', clearBinding(props.modelValue, role))
  note.value = ''
}

function autoDetect(): void {
  const suggestion = suggestBindings(graph.value)
  let next = props.modelValue
  let applied = 0
  for (const role of roles.value) {
    const target = suggestion.bindings[role]
    if (target && !next.bindings[role]) {
      next = setBinding(next, role, target)
      applied++
    }
  }
  if (suggestion.output_node && !next.output_node) {
    next = { ...next, output_node: suggestion.output_node }
    applied++
  }
  emit('update:modelValue', { ...next, graph: withPositions(next.graph, positions.value) })
  const missing = suggestion.notes.filter(line => line.includes('not found')).length
  note.value = `Auto-detected ${applied} role(s).` + (missing ? ` ${missing} not found — assign manually.` : ' All roles resolved.')
}

function inputClick(nodeId: string, row: InputRow): void {
  if (assignRole.value && assignRole.value !== 'output' && row.eligible) {
    assignTo({ node_id: nodeId, input_name: row.name })
    return
  }
  selected.value = nodeId
}

function nodeClick(nodeId: string): void {
  if (assignRole.value === 'output') {
    if (graph.value[nodeId]?.class_type.includes('SaveImage')) {
      const next = withPositions(props.modelValue.graph, positions.value)
      emit('update:modelValue', { ...props.modelValue, graph: next, output_node: nodeId })
      note.value = `Output → ${nodeId}`
      assignRole.value = null
    } else {
      note.value = 'The output must be a SaveImage node.'
    }
    return
  }
  selected.value = nodeId
}

/* Pan, zoom and node dragging -------------------------------------------------- */

let panState: { startX: number; startY: number; viewX: number; viewY: number } | null = null
let dragState: {
  id: string
  originX: number
  originY: number
  pointerX: number
  pointerY: number
  moved: boolean
} | null = null

function onCanvasPointerDown(event: PointerEvent): void {
  const target = event.target as HTMLElement
  if (target.closest('[data-node]') || target.closest('aside')) return
  ensureFitted()
  panState = { startX: event.clientX, startY: event.clientY, viewX: view.value.x, viewY: view.value.y }
}

function startNodeDrag(event: PointerEvent, id: string): void {
  if (event.button !== 0) return
  const position = positions.value[id]
  if (!position) return
  dragState = {
    id,
    originX: position.x,
    originY: position.y,
    pointerX: event.clientX,
    pointerY: event.clientY,
    moved: false
  }
}

function onWindowPointerMove(event: PointerEvent): void {
  if (dragState) {
    const position = positions.value[dragState.id]
    if (position) {
      // Delta-based: container offsets and panning are already inside the
      // captured origin, so 1 px of mouse moves the node by exactly 1/k px.
      position.x = dragState.originX + (event.clientX - dragState.pointerX) / view.value.k
      position.y = dragState.originY + (event.clientY - dragState.pointerY) / view.value.k
      dragState.moved = true
    }
    return
  }
  if (!panState) return
  view.value.x = panState.viewX + (event.clientX - panState.startX)
  view.value.y = panState.viewY + (event.clientY - panState.startY)
}

function onWindowPointerUp(): void {
  if (dragState?.moved) {
    const next = withPositions(props.modelValue.graph, positions.value)
    emit('update:modelValue', { ...props.modelValue, graph: next })
  }
  dragState = null
  panState = null
}

function onWheel(event: WheelEvent): void {
  event.preventDefault()
  const rect = container.value?.getBoundingClientRect()
  if (!rect) return
  const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12
  const k = Math.min(2, Math.max(0.25, view.value.k * factor))
  const cursorX = event.clientX - rect.left
  const cursorY = event.clientY - rect.top
  view.value.x = cursorX - ((cursorX - view.value.x) * k) / view.value.k
  view.value.y = cursorY - ((cursorY - view.value.y) * k) / view.value.k
  view.value.k = k
}

function zoomBy(factor: number): void {
  const rect = container.value?.getBoundingClientRect()
  if (!rect) return
  const k = Math.min(2, Math.max(0.25, view.value.k * factor))
  const centerX = rect.width / 2
  const centerY = rect.height / 2
  view.value.x = centerX - ((centerX - view.value.x) * k) / view.value.k
  view.value.y = centerY - ((centerY - view.value.y) * k) / view.value.k
  view.value.k = k
}

function fitView(): void {
  const rect = container.value?.getBoundingClientRect()
  const nodes = nodeViews.value
  if (!rect || !nodes.length || rect.width < 10) return
  const minX = Math.min(...nodes.map(node => node.x))
  const minY = Math.min(...nodes.map(node => node.y))
  const maxX = Math.max(...nodes.map(node => node.x + node.width))
  const maxY = Math.max(...nodes.map(node => node.y + node.height))
  const k = Math.min(
    1.5,
    Math.max(
      0.25,
      Math.min((rect.width - 48) / (maxX - minX || 1), (rect.height - 48) / (maxY - minY || 1))
    )
  )
  view.value.k = k
  view.value.x = (rect.width - (maxX - minX) * k) / 2 - minX * k
  view.value.y = (rect.height - (maxY - minY) * k) / 2 - minY * k
  fittedOnce.value = true
}

function ensureFitted(): void {
  const rect = container.value?.getBoundingClientRect()
  if (!fittedOnce.value && rect && rect.width > 10) fitView()
}

function reLayout(): void {
  positions.value = autoLayout(graph.value)
  emit('update:modelValue', { ...props.modelValue, graph: withPositions(graph.value, positions.value) })
  nextTick(fitView)
}

function onKey(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    assignRole.value = null
    selected.value = ''
    note.value = ''
  }
}

/* Inspector editing ------------------------------------------------------------ */

function updateNodeInput(nodeId: string, field: string, value: unknown): void {
  const clone = JSON.parse(JSON.stringify(props.modelValue.graph)) as ComfyWorkflow['graph']
  clone[nodeId].inputs[field] = value
  emit('update:modelValue', { ...props.modelValue, graph: clone })
}

function updateTitle(nodeId: string, title: string): void {
  const clone = JSON.parse(JSON.stringify(props.modelValue.graph)) as ComfyWorkflow['graph']
  clone[nodeId]._meta = { ...(clone[nodeId]._meta || {}), title: title.slice(0, 80) }
  emit('update:modelValue', { ...props.modelValue, graph: clone })
}

function toggleCollapsed(nodeId: string): void {
  const clone = JSON.parse(JSON.stringify(props.modelValue.graph)) as ComfyWorkflow['graph']
  const node = clone[nodeId]
  if (!node) return
  node._meta = { ...(node._meta || {}), collapsed: !node._meta?.collapsed }
  emit('update:modelValue', { ...props.modelValue, graph: clone })
}

/* Lifecycle ---------------------------------------------------------------------- */

watch(
  () => props.modelValue,
  value => {
    // Fires on every preset switch and saved edit, so node classes, positions
    // and model lists can never lag behind the workflow on display.
    const existing = existingPositions(value.graph)
    positions.value = existing || autoLayout(value.graph)
    if (selected.value && !value.graph[selected.value]) selected.value = ''
    if (!existing) {
      fittedOnce.value = false
      nextTick(ensureFitted)
    }
  }
)

let resizeObserver: ResizeObserver | undefined
watch(() => props.expanded, () => nextTick(fitView))

onMounted(() => {
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => ensureFitted())
    if (container.value) resizeObserver.observe(container.value)
  }
  positions.value = existingPositions(graph.value) || autoLayout(graph.value)
  nextTick(ensureFitted)
  window.addEventListener('pointermove', onWindowPointerMove)
  window.addEventListener('pointerup', onWindowPointerUp)
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  window.removeEventListener('pointermove', onWindowPointerMove)
  window.removeEventListener('pointerup', onWindowPointerUp)
})
</script>

<template>
  <div :class="expanded ? 'flex min-h-0 flex-1 flex-col gap-2' : 'space-y-2'">
    <div class="flex flex-wrap items-center gap-1.5 text-xs">
      <button
        v-for="role in roles"
        :key="role"
        type="button"
        :aria-pressed="assignRole === role"
        class="flex items-center gap-1 rounded-full border px-2 py-0.5"
        :class="
          assignRole === role
            ? 'border-cyan-400 bg-cyan-900/60 text-white'
            : modelValue.bindings[role]
              ? 'border-emerald-500/60 text-emerald-300'
              : 'border-slate-600 text-slate-300'
        "
        @click="startAssign(role)"
      >
        <span class="rounded px-1" :class="roleChipClasses[role]">{{ ROLE_LABELS[role] }}</span>
        <span v-if="modelValue.bindings[role]" class="max-w-[110px] truncate">{{
          shortTarget(role)
        }}</span>
        <span
          v-if="modelValue.bindings[role]"
          role="button"
          tabindex="0"
          :aria-label="`Clear ${ROLE_LABELS[role]}`"
          class="px-0.5 text-rose-300 hover:text-rose-200"
          @click.stop="clearRole(role)"
          @keydown.enter.stop.prevent="clearRole(role)"
          >×</span
        >
      </button>
      <button
        type="button"
        :aria-pressed="assignRole === 'output'"
        class="flex items-center gap-1 rounded-full border px-2 py-0.5"
        :class="
          assignRole === 'output'
            ? 'border-cyan-400 bg-cyan-900/60 text-white'
            : modelValue.output_node
              ? 'border-emerald-500/60 text-emerald-300'
              : 'border-slate-600 text-slate-300'
        "
        @click="startAssign('output')"
      >
        <span class="rounded bg-teal-500 px-1 text-slate-950">Output</span>
        <span v-if="modelValue.output_node" class="max-w-[110px] truncate">{{
          modelValue.output_node
        }}</span>
        <span
          v-if="modelValue.output_node"
          role="button"
          tabindex="0"
          aria-label="Clear output"
          class="px-0.5 text-rose-300 hover:text-rose-200"
          @click.stop="clearRole('output')"
          @keydown.enter.stop.prevent="clearRole('output')"
          >×</span
        >
      </button>
      <span class="mx-1 h-4 w-px bg-slate-700" aria-hidden="true"></span>
      <button
        type="button"
        class="flex items-center gap-1 rounded-full border border-slate-600 px-2 py-0.5 text-slate-300 hover:border-cyan-400"
        @click="autoDetect"
      >
        <Wand2 class="h-3 w-3" aria-hidden="true" /> Auto-detect
      </button>
      <button
        type="button"
        class="rounded-full border border-slate-600 px-2 py-0.5 text-slate-300 hover:border-cyan-400"
        aria-label="Zoom out"
        @click="zoomBy(1 / 1.2)"
      >
        <ZoomOut class="h-3 w-3" aria-hidden="true" />
      </button>
      <button
        type="button"
        class="rounded-full border border-slate-600 px-2 py-0.5 text-slate-300 hover:border-cyan-400"
        aria-label="Zoom in"
        @click="zoomBy(1.2)"
      >
        <ZoomIn class="h-3 w-3" aria-hidden="true" />
      </button>
      <button
        type="button"
        class="flex items-center gap-1 rounded-full border border-slate-600 px-2 py-0.5 text-slate-300 hover:border-cyan-400"
        @click="reLayout"
      >
        <LayoutGrid class="h-3 w-3" aria-hidden="true" /> Tidy
      </button>
      <button
        type="button"
        class="flex items-center gap-1 rounded-full border border-slate-600 px-2 py-0.5 text-slate-300 hover:border-cyan-400"
        @click="fitView"
      >
        <Maximize2 class="h-3 w-3" aria-hidden="true" /> Fit
      </button>
    </div>

    <div
      ref="container"
      class="relative select-none overflow-hidden rounded-xl border border-slate-700 bg-slate-950"
      :class="[
        assignRole ? 'cursor-crosshair' : 'cursor-grab',
        expanded ? 'min-h-0 flex-1' : 'h-[480px]'
      ]"
      :style="{
        backgroundImage: 'radial-gradient(circle, rgba(148,163,184,0.14) 1px, transparent 1px)',
        backgroundSize: '22px 22px'
      }"
      tabindex="0"
      :aria-label="'Workflow graph editor' + (reference ? ' for reference images' : '')"
      @wheel="onWheel"
      @pointerdown="onCanvasPointerDown"
      @keydown.escape="onKey"
    >
      <div
        class="absolute inset-0"
        :style="{
          transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})`,
          transformOrigin: '0 0'
        }"
      >
        <svg
          class="pointer-events-none absolute left-0 top-0 h-full w-full overflow-visible"
          aria-hidden="true"
        >
          <path
            v-for="(edge, index) in edgeViews"
            :key="index"
            :d="edge.d"
            :stroke="edge.color"
            class="fill-none"
            stroke-width="2"
            stroke-opacity="0.85"
          />
        </svg>
        <div
          v-for="node in nodeViews"
          :key="node.id"
          data-node
          class="absolute rounded-lg border bg-slate-900 shadow-md"
          :class="[
            selected === node.id
              ? 'border-cyan-400 ring-1 ring-cyan-400/40'
              : assignRole === 'output' && node.outputHint
                ? 'border-teal-400'
                : 'border-slate-700',
            assignRole === 'output' && !node.outputHint ? 'opacity-40' : ''
          ]"
          :style="{
            left: node.x + 'px',
            top: node.y + 'px',
            width: node.width + 'px',
            minHeight: node.height + 'px'
          }"
          @click="nodeClick(node.id)"
        >
          <div
            v-if="node.roles.length || node.isOutput"
            class="absolute -top-2.5 left-1.5 z-20 flex max-w-[calc(100%-12px)] flex-wrap gap-1"
          >
            <span
              v-for="role in node.roles"
              :key="role"
              class="rounded-full border bg-slate-950/95 px-1.5 text-[9px] font-bold uppercase leading-4 shadow"
              :class="roleBadgeClasses[role]"
              >{{ ROLE_LABELS[role] }}</span
            >
            <span
              v-if="node.isOutput"
              class="rounded-full border border-teal-400/70 bg-slate-950/95 px-1.5 text-[9px] font-bold uppercase leading-4 text-teal-300 shadow"
              >Output</span
            >
          </div>
          <div
            data-node-header
            class="flex cursor-grab items-center justify-between gap-2 rounded-t-lg px-2 py-1"
            :class="[familyClasses[node.family], node.collapsed ? 'rounded-b-lg' : '']"
            @pointerdown="startNodeDrag($event, node.id)"
          >
            <span class="truncate text-xs font-semibold text-white">{{ node.title }}</span>
            <span class="flex shrink-0 items-center gap-1">
              <button
                type="button"
                :aria-label="node.collapsed ? 'Expand node' : 'Collapse node'"
                :aria-expanded="!node.collapsed"
                class="rounded px-0.5 text-[10px] leading-none text-slate-100/80 hover:bg-black/30"
                @pointerdown.stop
                @click.stop="toggleCollapsed(node.id)"
              >
                {{ node.collapsed ? '▸' : '▾' }}
              </button>
              <span class="text-[10px] text-slate-200">{{ node.id }}</span>
            </span>
          </div>
          <ul v-if="!node.collapsed" class="px-1 pb-1">
            <li
              v-for="row in node.inputs"
              :key="row.name"
              class="flex items-center gap-1 truncate py-0.5 text-[10px]"
              :class="[
                row.eligible
                  ? 'cursor-pointer rounded bg-cyan-900/70 ring-1 ring-cyan-400'
                  : 'cursor-default',
                row.connectedFrom ? 'text-slate-400' : 'text-slate-300'
              ]"
              @click.stop="inputClick(node.id, row)"
            >
              <span
                class="h-2 w-2 shrink-0 rounded-full border"
                :style="{
                  backgroundColor: row.connectedFrom ? socketColor(row.name) : 'transparent',
                  borderColor: socketColor(row.name)
                }"
              ></span>
              <span class="shrink-0">{{ row.name }}</span>
              <span v-if="row.preview" class="truncate text-slate-500">{{ row.preview }}</span>
              <span v-else-if="row.connectedFrom" class="truncate text-slate-500"
                >← {{ row.connectedFrom }}</span
              >
            </li>
          </ul>
        </div>
      </div>

      <aside
        v-if="selectedNode"
        class="absolute inset-y-0 right-0 w-72 max-w-full overflow-y-auto overscroll-contain border-l border-slate-700 bg-slate-900/95 p-3 text-xs"
        @wheel.stop
        @pointerdown.stop
      >
        <div class="mb-2 flex items-start justify-between gap-2">
          <label class="block min-w-0 flex-1 text-slate-300">
            Title
            <input
              :value="selectedNode.title"
              maxlength="80"
              class="mt-1 w-full rounded border border-slate-700 bg-slate-800 p-1.5 text-slate-200"
              @change="updateTitle(selectedNode.id, ($event.target as HTMLInputElement).value)"
            />
          </label>
          <button
            type="button"
            class="mt-4 text-rose-300"
            aria-label="Close node settings"
            @click="selected = ''"
          >
            <X class="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
        <p class="mb-2 text-slate-500">{{ selectedNode.id }} · {{ selectedNode.classType }}</p>
        <div class="space-y-2">
          <template v-for="row in selectedNode.inputs" :key="row.name">
            <div v-if="row.connectedFrom !== null" class="text-slate-500">
              {{ row.name }} ← connected from {{ row.connectedFrom }}
            </div>
            <div v-else-if="MODEL_FIELD_LABELS[row.name] !== undefined" class="text-slate-300">
              <ComfyModelField
                :label="MODEL_FIELD_LABELS[row.name]"
                :model-value="String(selectedValues[row.name])"
                :files="choicesFor(selectedNode.id, row.name)"
                :folder="MODEL_FIELD_FOLDERS[row.name]"
                @update:model-value="updateNodeInput(selectedNode.id, row.name, $event)"
              />
            </div>
            <label
              v-else-if="
                ENUM_LABELS[row.name] !== undefined && typeof selectedValues[row.name] === 'string'
              "
              class="block text-slate-300"
            >
              {{ ENUM_LABELS[row.name] }}
              <select
                :value="String(selectedValues[row.name])"
                class="mt-1 w-full rounded border border-slate-700 bg-slate-800 p-1.5"
                @change="
                  updateNodeInput(
                    selectedNode.id,
                    row.name,
                    ($event.target as HTMLSelectElement).value
                  )
                "
              >
                <option
                  v-if="
                    !choicesFor(selectedNode.id, row.name)?.includes(
                      String(selectedValues[row.name])
                    )
                  "
                  :value="String(selectedValues[row.name])"
                  disabled
                >
                  Unavailable: {{ selectedValues[row.name] }}
                </option>
                <option
                  v-if="!choicesFor(selectedNode.id, row.name)?.length"
                  :value="String(selectedValues[row.name])"
                >
                  {{ selectedValues[row.name] }}
                </option>
                <option
                  v-for="choice in choicesFor(selectedNode.id, row.name)"
                  :key="choice"
                  :value="choice"
                >
                  {{ choice }}
                </option>
              </select>
            </label>
            <label
              v-else-if="typeof selectedValues[row.name] === 'number'"
              class="block text-slate-300"
            >
              {{ row.name }}
              <input
                :value="selectedValues[row.name]"
                type="number"
                class="mt-1 w-full rounded border border-slate-700 bg-slate-800 p-1.5"
                @change="
                  updateNodeInput(
                    selectedNode.id,
                    row.name,
                    Number(($event.target as HTMLInputElement).value)
                  )
                "
              />
            </label>
            <label
              v-else-if="typeof selectedValues[row.name] === 'boolean'"
              class="flex items-center gap-2 text-slate-300"
            >
              <input
                type="checkbox"
                :checked="Boolean(selectedValues[row.name])"
                @change="
                  updateNodeInput(
                    selectedNode.id,
                    row.name,
                    ($event.target as HTMLInputElement).checked
                  )
                "
              />
              {{ row.name }}
            </label>
            <label v-else class="block text-slate-300">
              {{ row.name }}
              <input
                :value="String(selectedValues[row.name])"
                class="mt-1 w-full rounded border border-slate-700 bg-slate-800 p-1.5"
                @change="
                  updateNodeInput(
                    selectedNode.id,
                    row.name,
                    ($event.target as HTMLInputElement).value
                  )
                "
              />
            </label>
          </template>
        </div>
      </aside>
    </div>
    <p class="text-xs text-slate-400" role="status">
      {{
        note ||
        'Drag nodes · wheel to zoom · click a node to edit its inputs · role chips mark what TaleWeaver replaces at generation time.'
      }}
    </p>
  </div>
</template>
