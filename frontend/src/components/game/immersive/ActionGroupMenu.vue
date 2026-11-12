<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  useId,
  watch,
  type Component
} from 'vue'
import { ChevronDown } from 'lucide-vue-next'

const props = defineProps<{
  label: string
  icon: Component
  modelValue: boolean
  glow?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [open: boolean] }>()
const id = useId()
const trigger = ref<HTMLButtonElement>()
const panel = ref<HTMLElement>()
let observer: ResizeObserver | undefined
const placement = ref({ left: '12px', top: '12px', maxHeight: '360px' })
const items = () =>
  Array.from(
    panel.value?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)') || []
  )
const position = computed(() => ({ ...placement.value, width: 'min(19rem, calc(100vw - 24px))' }))

function place() {
  const anchor = trigger.value?.getBoundingClientRect()
  if (!anchor || !panel.value) return
  const viewport = window.visualViewport
  const leftEdge = viewport?.offsetLeft || 0
  const topEdge = viewport?.offsetTop || 0
  const width = viewport?.width || window.innerWidth
  const height = viewport?.height || window.innerHeight
  const panelWidth = Math.min(304, width - 24)
  const above = anchor.top - topEdge - 20
  const below = topEdge + height - anchor.bottom - 20
  const upwards = above >= Math.min(panel.value.scrollHeight, 320) || above >= below
  const available = Math.max(96, Math.min(420, upwards ? above : below))
  const panelHeight = Math.min(panel.value.scrollHeight, available)
  placement.value = {
    left: `${Math.max(leftEdge + 12, Math.min(anchor.left, leftEdge + width - panelWidth - 12))}px`,
    top: `${upwards ? Math.max(topEdge + 12, anchor.top - panelHeight - 8) : anchor.bottom + 8}px`,
    maxHeight: `${available}px`
  }
}

async function open(last = false) {
  emit('update:modelValue', true)
  await nextTick()
  place()
  const choices = items()
  choices[last ? choices.length - 1 : 0]?.focus()
}

function close(restoreFocus = false) {
  emit('update:modelValue', false)
  if (restoreFocus) trigger.value?.focus()
}

function toggle() {
  if (props.modelValue) close(true)
  else void open()
}

function onTriggerKey(event: KeyboardEvent) {
  if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return
  event.preventDefault()
  void open(event.key === 'ArrowUp')
}

function onPanelKey(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    close(true)
    return
  }
  if (event.key === 'Tab') {
    close(true)
    return
  }
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const choices = items()
  const current = choices.indexOf(document.activeElement as HTMLButtonElement)
  const delta = event.key === 'ArrowDown' ? 1 : -1
  const next =
    event.key === 'Home'
      ? 0
      : event.key === 'End'
        ? choices.length - 1
        : (current + delta + choices.length) % choices.length
  choices[next]?.focus()
}

function onPanelClick(event: MouseEvent) {
  const button = (event.target as Element).closest('button')
  if (button && !button.hasAttribute('data-menu-keep-open')) close()
}

function onOutside(event: PointerEvent) {
  if (!props.modelValue) return
  const target = event.target as Node
  if (!trigger.value?.contains(target) && !panel.value?.contains(target)) close()
}

function onResize() {
  if (props.modelValue) place()
}

watch(
  () => props.modelValue,
  async value => {
    if (!value) return
    await nextTick()
    place()
  }
)
onMounted(() => {
  observer = new ResizeObserver(onResize)
  if (panel.value) observer.observe(panel.value)
  document.addEventListener('pointerdown', onOutside)
  window.addEventListener('resize', onResize)
  window.visualViewport?.addEventListener('resize', onResize)
})
onBeforeUnmount(() => {
  observer?.disconnect()
  document.removeEventListener('pointerdown', onOutside)
  window.removeEventListener('resize', onResize)
  window.visualViewport?.removeEventListener('resize', onResize)
})
</script>

<template>
  <button
    :id="`${id}-trigger`"
    ref="trigger"
    type="button"
    class="action-group-trigger group"
    :class="{ 'is-open': modelValue, 'has-update': glow }"
    :aria-expanded="modelValue"
    :aria-controls="`${id}-panel`"
    aria-haspopup="menu"
    @click="toggle"
    @keydown="onTriggerKey"
  >
    <component :is="icon" class="group-icon" aria-hidden="true" />
    <span>{{ label }}</span>
    <span v-if="glow" class="update-dot" aria-label="New activity" />
    <ChevronDown class="group-chevron hidden sm:block" aria-hidden="true" />
  </button>
  <Teleport to="body">
    <Transition name="action-group">
      <section
        v-show="modelValue"
        :id="`${id}-panel`"
        ref="panel"
        :style="position"
        role="menu"
        :inert="!modelValue"
        :aria-hidden="!modelValue"
        :aria-labelledby="`${id}-trigger`"
        class="action-group-panel"
        @keydown="onPanelKey"
        @click="onPanelClick"
      >
        <div class="action-group-heading" aria-hidden="true">{{ label }}</div>
        <slot />
      </section>
    </Transition>
  </Teleport>
</template>

<style scoped>
.action-group-trigger {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 38px;
  padding: 6px 10px;
  border: 1px solid transparent;
  border-radius: 9px;
  color: #a5afbf;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  transition:
    background 0.18s,
    border-color 0.18s,
    color 0.18s;
}
.action-group-trigger:hover,
.action-group-trigger.is-open {
  background: rgb(251 191 36 / 0.08);
  border-color: rgb(251 191 36 / 0.25);
  color: #fde68a;
}
.action-group-trigger:focus-visible {
  outline: 2px solid #fbbf24;
  outline-offset: 2px;
}
.group-icon {
  width: 16px;
  height: 16px;
  stroke-width: 1.6;
  color: #94a3b8;
  transition: color 0.18s;
}
.action-group-trigger:hover .group-icon,
.is-open .group-icon {
  color: #fcd34d;
}
.group-chevron {
  width: 11px;
  height: 11px;
  transition: transform 0.2s;
  color: #64748b;
}
.is-open .group-chevron {
  transform: rotate(180deg);
  color: #d6b46f;
}
.update-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #fbbf24;
}
.action-group-panel {
  position: fixed;
  z-index: 70;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 7px;
  border: 1px solid rgb(148 163 184 / 0.25);
  border-radius: 14px;
  background: rgb(15 23 42 / 0.97);
  backdrop-filter: blur(18px);
  box-shadow: 0 16px 48px rgb(0 0 0 / 0.55);
  color: #e2e8f0;
  transform-origin: bottom left;
  scrollbar-width: thin;
}
.action-group-heading {
  padding: 7px 10px 11px;
  margin-bottom: 4px;
  border-bottom: 1px solid rgb(100 116 139 / 0.25);
  color: #d6b46f;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}
.action-group-panel :deep(.action-menu-item) {
  display: flex;
  align-items: center;
  gap: 11px;
  width: 100%;
  min-height: 48px;
  padding: 9px 10px;
  border: 1px solid transparent;
  border-radius: 9px;
  text-align: left;
  color: #e2e8f0;
  font-size: 12px;
  transition:
    background 0.15s,
    border-color 0.15s;
}
.action-group-panel :deep(.action-menu-item:hover:not(:disabled)) {
  background: rgb(148 163 184 / 0.08);
  border-color: rgb(148 163 184 / 0.12);
}
.action-group-panel :deep(.action-menu-item:focus-visible) {
  outline: 2px solid rgb(251 191 36 / 0.7);
  outline-offset: -2px;
  background: rgb(251 191 36 / 0.06);
}
.action-group-panel :deep(.action-menu-item svg) {
  flex-shrink: 0;
  width: 17px;
  height: 17px;
  stroke-width: 1.6;
}
.action-group-panel :deep(.action-menu-copy) {
  flex: 1;
  min-width: 0;
}
.action-group-panel :deep(.action-menu-title) {
  display: block;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.5;
}
.action-group-panel :deep(.action-menu-description) {
  display: block;
  margin-top: 2px;
  color: #94a3b8;
  font-size: 10px;
  line-height: 1.5;
}
.action-group-enter-active,
.action-group-leave-active {
  transition:
    opacity 0.2s,
    transform 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}
.action-group-enter-from,
.action-group-leave-to {
  opacity: 0;
  transform: translateY(8px) scale(0.98);
}
@media (max-width: 639px) {
  .action-group-trigger {
    min-height: 44px;
    padding: 5px 5px;
    gap: 4px;
    font-size: 10px;
  }
  .group-icon {
    width: 14px;
    height: 14px;
  }
  .update-dot {
    width: 4px;
    height: 4px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .action-group-enter-active,
  .action-group-leave-active,
  .group-chevron,
  .action-group-trigger {
    transition-duration: 0.001ms;
  }
}
</style>
