<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
const props = defineProps<{
  npcId: string
  text: string
  name: string
  anchor: HTMLElement | null
}>()
const emit = defineEmits<{ dismiss: [] }>()
const bubble = ref<HTMLElement | null>(null)
const side = ref('right')
const position = ref<Record<string, string>>({ visibility: 'hidden' })
const clamp = (value: number, minimum: number, maximum: number) =>
  Math.max(minimum, Math.min(value, Math.max(minimum, maximum)))
function place(element?: Element) {
  const cloud = element instanceof HTMLElement ? element : bubble.value
  if (!props.anchor || !cloud) return
  const rect = props.anchor.getBoundingClientRect()
  // Layout dimensions remain stable while the entrance animation scales the cloud.
  const width = cloud.offsetWidth
  const height = cloud.offsetHeight
  const margin = 16
  const gap = 24
  const head = rect.top + Math.min(64, rect.height / 3)
  let left = rect.right + gap
  let top = head - height / 2
  side.value = 'right'
  if (left + width > window.innerWidth - margin) {
    left = rect.left - width - gap
    side.value = 'left'
  }
  if (left < margin) {
    side.value = rect.top >= height + gap + margin ? 'above' : 'below'
    left = rect.left + rect.width / 2 - width / 2
    top = side.value === 'above' ? rect.top - height - gap : rect.bottom + gap
  }
  left = clamp(left, margin, window.innerWidth - width - margin)
  top = clamp(top, margin, window.innerHeight - height - margin)
  const tailX = clamp(rect.left + rect.width / 2 - left, 28, width - 28)
  const tailY = clamp(head - top, 26, height - 26)
  const origins: Record<string, string> = {
    right: `0 ${tailY}px`,
    left: `100% ${tailY}px`,
    above: `${tailX}px 100%`,
    below: `${tailX}px 0`
  }
  position.value = {
    left: `${left}px`,
    top: `${top}px`,
    '--tail-x': `${tailX}px`,
    '--tail-y': `${tailY}px`,
    '--thought-origin': origins[side.value],
    visibility: 'visible'
  }
}
watch(
  () => [props.text, props.anchor],
  async () => {
    await nextTick()
    place()
  },
  { immediate: true, flush: 'post' }
)
function dismiss() {
  emit('dismiss')
}
function keydown(event: KeyboardEvent) {
  if (event.key === 'Escape') dismiss()
}
onMounted(() => {
  window.addEventListener('resize', dismiss)
  window.addEventListener('scroll', dismiss, true)
  window.addEventListener('keydown', keydown)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', dismiss)
  window.removeEventListener('scroll', dismiss, true)
  window.removeEventListener('keydown', keydown)
})
</script>

<template>
  <Teleport to="body">
    <Transition name="npc-thought" mode="out-in" appear @enter="place">
      <div
        v-if="text && anchor"
        :key="npcId"
        id="npc-current-thought"
        ref="bubble"
        role="tooltip"
        :style="position"
        :data-side="side"
        class="npc-thought-bubble"
      >
        <span class="npc-thought-name">{{ name }}</span>
        <p class="npc-thought-text">{{ text }}</p>
        <span aria-hidden="true" class="npc-thought-dot npc-thought-dot-near"></span>
        <span aria-hidden="true" class="npc-thought-dot npc-thought-dot-far"></span>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.npc-thought-bubble {
  --thought-x: 0px;
  --thought-y: 10px;
  position: fixed;
  z-index: 100;
  width: min(19rem, calc(100vw - 32px));
  padding: 15px 18px 17px;
  pointer-events: none;
  border: 1px solid rgb(216 180 254 / 38%);
  border-radius: 26px 30px 28px 22px;
  background: linear-gradient(145deg, rgb(35 25 49 / 98%), rgb(12 16 29 / 98%));
  box-shadow:
    0 12px 32px rgb(0 0 0 / 40%),
    inset 0 1px 0 rgb(255 255 255 / 7%);
  font-family:
    system-ui,
    -apple-system,
    BlinkMacSystemFont,
    'Segoe UI',
    sans-serif;
  transform-origin: var(--thought-origin, 0 50%);
}
.npc-thought-name {
  display: block;
  margin-bottom: 5px;
  color: #d8b4e7;
  font-size: 10px;
  font-weight: 650;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}
.npc-thought-text {
  margin: 0;
  color: #f3edf8;
  font-size: 15px;
  font-style: normal;
  line-height: 1.6;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
.npc-thought-dot {
  position: absolute;
  border: 1px solid rgb(216 180 254 / 38%);
  border-radius: 50%;
  background: #171521;
}
.npc-thought-dot-near {
  width: 12px;
  height: 12px;
}
.npc-thought-dot-far {
  width: 6px;
  height: 6px;
}
[data-side='right'] {
  --thought-x: -10px;
}
[data-side='left'] {
  --thought-x: 10px;
}
[data-side='below'] {
  --thought-y: -10px;
}
[data-side='right'] .npc-thought-dot-near {
  left: -14px;
  top: calc(var(--tail-y) - 6px);
}
[data-side='right'] .npc-thought-dot-far {
  left: -24px;
  top: calc(var(--tail-y) + 6px);
}
[data-side='left'] .npc-thought-dot-near {
  right: -14px;
  top: calc(var(--tail-y) - 6px);
}
[data-side='left'] .npc-thought-dot-far {
  right: -24px;
  top: calc(var(--tail-y) + 6px);
}
[data-side='above'] .npc-thought-dot-near {
  bottom: -14px;
  left: calc(var(--tail-x) - 6px);
}
[data-side='above'] .npc-thought-dot-far {
  bottom: -24px;
  left: calc(var(--tail-x) + 6px);
}
[data-side='below'] .npc-thought-dot-near {
  top: -14px;
  left: calc(var(--tail-x) - 6px);
}
[data-side='below'] .npc-thought-dot-far {
  top: -24px;
  left: calc(var(--tail-x) + 6px);
}
.npc-thought-enter-active {
  animation: npc-thought-arrive 300ms cubic-bezier(0.16, 1, 0.3, 1) both;
}
.npc-thought-enter-active .npc-thought-dot-near {
  animation: npc-thought-dot 180ms 35ms both;
}
.npc-thought-enter-active .npc-thought-dot-far {
  animation: npc-thought-dot 150ms both;
}
.npc-thought-leave-active {
  transition:
    opacity 140ms ease,
    transform 140ms ease;
}
.npc-thought-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.98);
}
@keyframes npc-thought-arrive {
  from {
    opacity: 0;
    transform: translate(var(--thought-x), var(--thought-y)) scale(0.92);
  }
  70% {
    opacity: 1;
    transform: translateY(-2px) scale(1.01);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
@keyframes npc-thought-dot {
  from {
    opacity: 0;
    transform: scale(0.3);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}
@media (prefers-reduced-motion: reduce) {
  .npc-thought-enter-active,
  .npc-thought-leave-active,
  .npc-thought-enter-active .npc-thought-dot {
    animation: none;
    transition: none;
  }
}
</style>
