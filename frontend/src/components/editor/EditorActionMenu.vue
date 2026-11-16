<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, type CSSProperties } from 'vue'

const props = defineProps<{ anchor: HTMLElement | null; label: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()
const panel = ref<HTMLElement | null>(null)
const style = ref<CSSProperties>({ visibility: 'hidden' })
let frame = 0
let observer: ResizeObserver | null = null
let disposed = false

function position() {
  frame = 0
  if (!props.anchor?.isConnected || !panel.value) return emit('close')
  const anchor = props.anchor.getBoundingClientRect()
  const viewport = window.visualViewport
  const left = viewport?.offsetLeft || 0, top = viewport?.offsetTop || 0
  const width = viewport?.width || window.innerWidth, height = viewport?.height || window.innerHeight
  if (anchor.bottom < top || anchor.top > top + height || anchor.right < left || anchor.left > left + width) return emit('close')
  const inset = 8, gap = 4
  const menuWidth = Math.min(224, Math.max(1, width - 2 * inset))
  const menuHeight = Math.min(panel.value.scrollHeight + 2, Math.max(1, height - 2 * inset))
  const below = top + height - anchor.bottom - gap - inset
  const above = anchor.top - gap - top - inset
  const y = below >= menuHeight || below >= above ? anchor.bottom + gap : anchor.top - gap - menuHeight
  style.value = {
    visibility: 'visible', width: `${menuWidth}px`, maxHeight: `${Math.max(1, height - 2 * inset)}px`,
    left: `${Math.max(left + inset, Math.min(anchor.right - menuWidth, left + width - inset - menuWidth))}px`,
    top: `${Math.max(top + inset, Math.min(y, top + height - inset - menuHeight))}px`,
  }
}
function schedule() {
  if (!disposed && !frame) frame = requestAnimationFrame(position)
}
function outside(event: PointerEvent) {
  if (event.target instanceof Node && !panel.value?.contains(event.target) && !props.anchor?.contains(event.target)) emit('close')
}
function keydown(event: KeyboardEvent) {
  if (event.key !== 'Escape') return
  event.preventDefault()
  event.stopPropagation()
  props.anchor?.focus({ preventScroll: true })
  emit('close')
}
onMounted(async () => {
  await nextTick()
  if (disposed) return
  position()
  panel.value?.querySelector('button')?.focus({ preventScroll: true })
  window.addEventListener('resize', schedule)
  window.addEventListener('scroll', schedule, true)
  window.visualViewport?.addEventListener('resize', schedule)
  window.visualViewport?.addEventListener('scroll', schedule)
  document.addEventListener('pointerdown', outside)
  document.addEventListener('keydown', keydown)
  observer = new ResizeObserver(schedule)
  if (panel.value) observer.observe(panel.value)
})
onBeforeUnmount(() => {
  disposed = true
  cancelAnimationFrame(frame)
  observer?.disconnect()
  window.removeEventListener('resize', schedule)
  window.removeEventListener('scroll', schedule, true)
  window.visualViewport?.removeEventListener('resize', schedule)
  window.visualViewport?.removeEventListener('scroll', schedule)
  document.removeEventListener('pointerdown', outside)
  document.removeEventListener('keydown', keydown)
})
</script>

<template>
  <Teleport to="body">
    <div ref="panel" role="group" :aria-label="label" :style="style" @click="emit('close')"
      class="fixed z-[230] max-w-[calc(100vw-16px)] overflow-y-auto overscroll-contain rounded-lg border border-white/20 bg-slate-900 py-1.5 shadow-2xl ring-1 ring-white/5">
      <slot />
    </div>
  </Teleport>
</template>
