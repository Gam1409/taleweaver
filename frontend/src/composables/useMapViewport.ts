import { onBeforeUnmount, onMounted, type Ref } from 'vue'

type Point = { x: number; y: number }

/** Pan and pinch the centered map while keeping the touched content anchored. */
export function useMapViewport(
  viewport: Ref<HTMLElement | null>,
  content: Ref<HTMLElement | null>,
  zoom: Ref<number>,
  offset: Ref<Point>,
) {
  const pointers = new Map<number, Point>()
  let lastPosition: Point | null = null
  let pinch: { distance: number; zoom: number; offset: Point; center: Point; origin: Point } | null = null
  const position = (event: PointerEvent): Point => ({ x: event.clientX, y: event.clientY })

  function rebase() {
    const [one, two] = [...pointers.values()]
    lastPosition = pointers.size === 1 ? one : null
    pinch = null
    if (pointers.size !== 2 || !content.value) return
    const rect = content.value.getBoundingClientRect()
    pinch = {
      distance: Math.hypot(two.x - one.x, two.y - one.y), zoom: zoom.value,
      offset: { ...offset.value }, center: { x: (one.x + two.x) / 2, y: (one.y + two.y) / 2 },
      origin: { x: rect.left + rect.width / 2 - offset.value.x, y: rect.top + rect.height / 2 - offset.value.y },
    }
  }

  function releasePointer(id: number) {
    if (viewport.value?.hasPointerCapture?.(id)) viewport.value.releasePointerCapture(id)
  }

  function resetPointers() {
    const ids = [...pointers.keys()]
    pointers.clear()
    rebase()
    ids.forEach(releasePointer)
  }

  function handlePointerDown(event: PointerEvent) {
    if (!viewport.value || event.button !== 0) return
    pointers.set(event.pointerId, position(event))
    try { viewport.value.setPointerCapture?.(event.pointerId) }
    catch { /* Global browser cancellation still ends an uncaptured gesture. */ }
    rebase()
  }

  function handlePointerMove(event: PointerEvent) {
    if (!pointers.has(event.pointerId)) return
    const point = position(event)
    pointers.set(event.pointerId, point)
    if (pointers.size === 1 && lastPosition) {
      offset.value = { x: offset.value.x + point.x - lastPosition.x, y: offset.value.y + point.y - lastPosition.y }
      lastPosition = point
      return
    }
    if (pointers.size !== 2 || !pinch || pinch.distance <= 0) return
    const [one, two] = [...pointers.values()]
    const distance = Math.hypot(two.x - one.x, two.y - one.y)
    const nextZoom = Math.max(0.2, Math.min(3, pinch.zoom * distance / pinch.distance))
    const center = { x: (one.x + two.x) / 2, y: (one.y + two.y) / 2 }
    const ratio = nextZoom / pinch.zoom
    offset.value = {
      x: center.x - pinch.origin.x - (pinch.center.x - pinch.origin.x - pinch.offset.x) * ratio,
      y: center.y - pinch.origin.y - (pinch.center.y - pinch.origin.y - pinch.offset.y) * ratio,
    }
    zoom.value = nextZoom
  }

  function handlePointerUp(event: PointerEvent) {
    if (!pointers.delete(event.pointerId)) return
    rebase()
    releasePointer(event.pointerId)
  }

  function handleWheel(event: WheelEvent) {
    event.preventDefault()
    resetPointers()
    zoom.value = Math.max(0.2, Math.min(3, zoom.value * (event.deltaY > 0 ? 0.9 : 1.1)))
  }

  onMounted(() => {
    window.addEventListener('blur', resetPointers)
    window.addEventListener('pointerup', handlePointerUp)
    window.addEventListener('pointercancel', handlePointerUp)
  })
  onBeforeUnmount(() => {
    resetPointers()
    window.removeEventListener('blur', resetPointers)
    window.removeEventListener('pointerup', handlePointerUp)
    window.removeEventListener('pointercancel', handlePointerUp)
  })

  return { handlePointerDown, handlePointerMove, handlePointerUp, handleWheel, resetPointers }
}
