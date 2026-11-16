import { nextTick, onBeforeUnmount, onMounted, type Ref } from 'vue'

/** Keep keyboard navigation inside a modal and restore its opener on close. */
export function useDialogFocus(element: Ref<HTMLElement | null>, close: () => void): void {
  let opener: HTMLElement | null = null
  const focusable = (): HTMLElement[] => Array.from(element.value?.querySelectorAll<HTMLElement>(
    'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex="0"]',
  ) ?? []).filter(node => node.getClientRects().length > 0)
  const keydown = (event: KeyboardEvent): void => {
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      close()
      return
    }
    if (event.key !== 'Tab') return
    const items = focusable()
    const first = items[0] ?? element.value
    const last = items[items.length - 1] ?? element.value
    const outside = !element.value?.contains(document.activeElement)
    if (outside || (event.shiftKey ? document.activeElement === first : document.activeElement === last)) {
      event.preventDefault()
      ;(event.shiftKey ? last : first)?.focus()
    }
  }
  onMounted(async () => {
    opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    await nextTick()
    ;(focusable()[0] ?? element.value)?.focus()
    document.addEventListener('keydown', keydown, true)
  })
  onBeforeUnmount(() => {
    document.removeEventListener('keydown', keydown, true)
    opener?.focus()
  })
}
