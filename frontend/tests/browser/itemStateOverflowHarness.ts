import { createApp, h, ref } from 'vue'
import '../../src/assets/main.css'
import GameHoverTooltip from '../../src/components/game/GameHoverTooltip.vue'
import ContainerModal from '../../src/components/game/ContainerModal.vue'
import { useGameInteractionState } from '../../src/composables/useGameInteractionState'
import image from '../../src/assets/svg/app-logo.svg'

const current_state = Array.from({ length: 12 }, (_, index) => {
  const end = ` Ending state ${index + 1}.`
  const start = index === 0 ? '<ScRiPt>window.executed = true</ScRiPt> ' : `Property ${index + 1}: `
  return { dimension: `custom_property_${index}`, detail: (start + 'Observed condition. '.repeat(30)).slice(0, 320 - end.length) + end }
})
const item = { id: 'FLASK', name: 'Coastal flask', entity_type: 'ITEM', item_type: 'WEAPON', current_state,
  description: 'Original description: a metal flask. <SCRIPT>window.executed = true</SCRIPT>',
  image_url: new URL(image, window.location.origin).href, damage_dice: '1d4', weapon_cost_type: 'stamina', weapon_cost_value: 2,
}
Object.assign(window, { overflowFixture: { item } })
createApp({ setup() {
  const hover = useGameInteractionState({ isActionInputBlocked: ref(false), npcMetadata: ref({}), handlePlayerInput: async () => {} })
  const container = ref(false)
  const clicks = ref(0)
  const outsideClicks = ref(0)
  const native = ref<HTMLDialogElement | null>(null)
  Object.assign((window as any).overflowFixture, { openNative: () => native.value?.showModal() })
  const leave = hover.leaveHover
  return () => h('main', { class: 'min-h-screen bg-slate-950 p-8 text-white' }, [
    h('button', { class: 'rounded border p-3', onClick: () => { clicks.value += 1 }, onMouseenter: (event: MouseEvent) => hover.handleHover(item, event), onMouseleave: leave }, 'Inspect flask'),
    h('button', { class: 'ml-3 rounded border p-3', onClick: () => { container.value = true } }, 'Open container'),
    h('button', { class: 'fixed left-0 top-0 rounded border px-1 text-xs', onClick: () => { outsideClicks.value += 1; hover.closeHover() } }, 'Outside action'),
    h('output', { 'aria-label': 'Source activations', class: 'block' }, String(clicks.value)),
    h('output', { 'aria-label': 'Outside activations', class: 'block' }, String(outsideClicks.value)),
    h('dialog', { ref: native, 'aria-label': 'Independent dialog' }, [h('button', { onClick: () => native.value?.close() }, 'Close independent dialog')]),
    h(ContainerModal, { open: container.value, title: 'Coastal chest', items: [item], onClose: () => { container.value = false }, onTakeItem: () => { clicks.value += 1 }, onItemHover: hover.handleHover, onItemLeave: leave }),
    h(GameHoverTooltip, { hoveredEntity: hover.hoveredEntity.value, teleportTarget: hover.tooltipTarget.value, onRetain: hover.retainHover, onLeave: hover.leaveHover, onClose: () => hover.closeHover(true), onElement: hover.setTooltipElement, tooltipStyle: hover.tooltipStyle.value, tooltipImageFailed: hover.tooltipImageFailed.value,
      showsMechanics: true, isConsumableHover: false, ruleMode: 'rpg', onImageError: hover.onTooltipImageError }),
  ])
} }).mount('#app')
