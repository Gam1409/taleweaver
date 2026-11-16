import { computed, onScopeDispose, ref } from 'vue'
import { normalizeHoverEntity } from '@/services/hoverEntityService'
import { gameHoverPlacement, type HoverViewport } from '@/utils/gameHoverPlacement'

/** Own the existing global hover snapshot and its readable popup lifetime. */
export function useGameHoverTooltip() {
  const hoveredEntity = ref<any>(null)
  const mousePos = ref({ x: 0, y: 0 })
  const tooltipImageFailed = ref(false)
  const tooltipElement = ref<HTMLElement | null>(null)
  const tooltipTarget = ref<HTMLElement | string>('body')
  const viewport = ref<HoverViewport>({ left: 0, top: 0, width: 1024, height: 768, layoutHeight: 768 })
  let anchor: HTMLElement | null = null
  let previousFocus: HTMLElement | null = null
  let timer: ReturnType<typeof setTimeout> | undefined
  const tooltipStyle = computed(() => hoveredEntity.value ? gameHoverPlacement(mousePos.value, viewport.value, anchor?.getBoundingClientRect()) : {})
  function retainHover() { clearTimeout(timer) }
  function closeHover(restoreFocus = false) {
    retainHover()
    const focused = typeof document !== 'undefined' && tooltipElement.value?.contains(document.activeElement)
    hoveredEntity.value = null
    if (restoreFocus && focused && previousFocus?.isConnected) previousFocus.focus()
    anchor = null
  }
  function leaveHover() {
    retainHover()
    if (!hoveredEntity.value || tooltipElement.value?.contains(document.activeElement)) return
    timer = setTimeout(() => closeHover(), 250)
  }
  function handleHover(entity: any, event: MouseEvent) {
    retainHover()
    anchor = typeof HTMLElement !== 'undefined' && event.currentTarget instanceof HTMLElement ? event.currentTarget : null
    if (typeof document !== 'undefined' && !tooltipElement.value?.contains(document.activeElement)) previousFocus = document.activeElement as HTMLElement | null
    tooltipTarget.value = anchor?.closest('dialog') || 'body'
    tooltipImageFailed.value = false
    hoveredEntity.value = normalizeHoverEntity(entity)
    mousePos.value = { x: event.clientX, y: event.clientY }
  }
  function setTooltipElement(element: HTMLElement | null) { tooltipElement.value = element }
  function resize() {
    const visual = window.visualViewport
    viewport.value = { left: visual?.offsetLeft || 0, top: visual?.offsetTop || 0, width: visual?.width || window.innerWidth, height: visual?.height || window.innerHeight, layoutHeight: window.innerHeight }
  }
  function outside(event: PointerEvent) {
    const target = event.target as Node | null
    if (target && !anchor?.contains(target) && !tooltipElement.value?.contains(target)) closeHover()
  }
  function scroll(event: Event) {
    if (!tooltipElement.value?.contains(event.target as Node)) closeHover()
  }
  function key(event: KeyboardEvent) {
    if (event.key !== 'Escape' || !hoveredEntity.value) return
    const inside = tooltipElement.value?.contains(event.target as Node) || false
    if (inside) { event.preventDefault(); event.stopPropagation() }
    closeHover(inside)
  }
  if (typeof window !== 'undefined' && typeof document !== 'undefined') {
    resize()
    window.addEventListener('resize', resize)
    window.visualViewport?.addEventListener('resize', resize)
    window.visualViewport?.addEventListener('scroll', resize)
    document.addEventListener('pointerdown', outside)
    document.addEventListener('scroll', scroll, true)
    document.addEventListener('keydown', key, true)
    onScopeDispose(() => {
      retainHover()
      window.removeEventListener('resize', resize)
      window.visualViewport?.removeEventListener('resize', resize)
      window.visualViewport?.removeEventListener('scroll', resize)
      document.removeEventListener('pointerdown', outside)
      document.removeEventListener('scroll', scroll, true)
      document.removeEventListener('keydown', key, true)
    })
  }
  return { hoveredEntity, mousePos, tooltipImageFailed, tooltipStyle, tooltipTarget, handleHover, retainHover, leaveHover, closeHover, setTooltipElement }
}
