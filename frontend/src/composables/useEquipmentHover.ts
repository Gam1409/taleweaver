import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

/** Keep the hover list inside the native dialog's top layer and inside the viewport. */
export function useEquipmentHover() {
  const active = ref('')
  const popup = ref<HTMLElement | null>(null)
  const target = ref<HTMLElement | null>(null)
  const style = ref({ left: '0px', top: '0px' })
  let anchor: HTMLElement | null = null
  let pinned = false
  let timer: ReturnType<typeof setTimeout> | undefined

  function retain() {
    clearTimeout(timer)
  }
  function close() {
    retain()
    active.value = ''
    anchor = null
    pinned = false
  }
  function position() {
    if (!anchor?.isConnected || !popup.value) return
    const rect = anchor.getBoundingClientRect()
    const bounds = popup.value.getBoundingClientRect()
    if (!visibleAnchor(rect)) {
      close()
      return
    }
    const rightFits = rect.right + bounds.width + 12 <= innerWidth
    const leftFits = rect.left - bounds.width - 12 >= 0
    const beside = rightFits || leftFits
    const left = rightFits
      ? rect.right + 12
      : leftFits
        ? rect.left - bounds.width - 12
        : rect.left + rect.width / 2 - bounds.width / 2
    const top = beside
      ? rect.top
      : rect.bottom + bounds.height + 10 <= innerHeight
        ? rect.bottom + 10
        : rect.top - bounds.height - 10
    style.value = {
      left: `${Math.max(10, Math.min(left, innerWidth - bounds.width - 10))}px`,
      top: `${Math.max(10, Math.min(top, innerHeight - bounds.height - 10))}px`
    }
  }
  function visibleAnchor(rect: DOMRect) {
    if (rect.bottom <= 0 || rect.top >= innerHeight) return false
    for (let parent = anchor?.parentElement; parent; parent = parent.parentElement) {
      if (!/(auto|scroll|hidden|clip)/.test(getComputedStyle(parent).overflowY)) continue
      const bounds = parent.getBoundingClientRect()
      if (rect.bottom <= bounds.top || rect.top >= bounds.bottom) return false
    }
    return true
  }
  async function open(key: string, event: Event, pin = false) {
    retain()
    anchor = event.currentTarget as HTMLElement
    target.value = anchor.closest('dialog') || document.body
    active.value = key
    pinned = pin
    await nextTick()
    position()
  }
  function leave() {
    if (!pinned) timer = setTimeout(close, 120)
  }
  function scroll() {
    if (pinned) position()
    else close()
  }
  function escape(event: KeyboardEvent) {
    if (event.key !== 'Escape' || !active.value) return
    event.preventDefault()
    event.stopPropagation()
    close()
  }
  function outside(event: PointerEvent) {
    if (!anchor?.contains(event.target as Node) && !popup.value?.contains(event.target as Node))
      close()
  }
  onMounted(() => {
    window.addEventListener('resize', close)
    document.addEventListener('scroll', scroll, true)
    document.addEventListener('keydown', escape, true)
    document.addEventListener('pointerdown', outside)
  })
  onBeforeUnmount(() => {
    retain()
    window.removeEventListener('resize', close)
    document.removeEventListener('scroll', scroll, true)
    document.removeEventListener('keydown', escape, true)
    document.removeEventListener('pointerdown', outside)
  })
  return { active, popup, target, style, open, close, retain, leave, position }
}
