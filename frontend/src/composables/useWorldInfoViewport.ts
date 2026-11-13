import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

/** Native dialogs must fit the visible area when the keyboard or pinch zoom changes it. */
export function useWorldInfoViewport() {
  const area = ref({ width: window.innerWidth, height: window.innerHeight, left: 0, top: 0 })
  function update() {
    const viewport = window.visualViewport
    area.value = { width: viewport?.width ?? window.innerWidth, height: viewport?.height ?? window.innerHeight, left: viewport?.offsetLeft ?? 0, top: viewport?.offsetTop ?? 0 }
  }
  onMounted(() => {
    update()
    window.addEventListener('resize', update)
    window.visualViewport?.addEventListener('resize', update)
    window.visualViewport?.addEventListener('scroll', update)
  })
  onBeforeUnmount(() => {
    window.removeEventListener('resize', update)
    window.visualViewport?.removeEventListener('resize', update)
    window.visualViewport?.removeEventListener('scroll', update)
  })
  return {
    short: computed(() => area.value.height < 500),
    tiny: computed(() => area.value.height < 300),
    narrow: computed(() => area.value.width < 768),
    style: computed(() => ({ width: `${Math.max(1, Math.min(1160, area.value.width - 16))}px`, height: `${Math.max(1, Math.min(900, area.value.height - 16))}px`, left: `${area.value.left + area.value.width / 2}px`, top: `${area.value.top + area.value.height / 2}px` })),
  }
}
