<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref } from 'vue'

defineProps<{ id: string; label: string; text: string }>()
const open = ref(false)
const button = ref<HTMLButtonElement | null>(null)
const panel = ref<HTMLElement | null>(null)
const position = ref({ top: '0px', left: '0px' })

function place() {
  if (!open.value || !button.value || !panel.value) return
  const anchor = button.value.getBoundingClientRect()
  const box = panel.value.getBoundingClientRect()
  const left = Math.max(8, Math.min(anchor.right - box.width, window.innerWidth - box.width - 8))
  const below = anchor.bottom + 8
  const top =
    below + box.height < window.innerHeight - 96 ? below : Math.max(8, anchor.top - box.height - 8)
  position.value = { left: `${left}px`, top: `${top}px` }
}

function outside(event: PointerEvent) {
  if (
    event.target instanceof Node &&
    !button.value?.contains(event.target) &&
    !panel.value?.contains(event.target)
  )
    close()
}

function close() {
  open.value = false
  window.removeEventListener('scroll', place, true)
  window.removeEventListener('resize', place)
  document.removeEventListener('pointerdown', outside)
}

async function toggle() {
  if (open.value) return close()
  open.value = true
  await nextTick()
  if (!open.value) return
  place()
  window.addEventListener('scroll', place, true)
  window.addEventListener('resize', place)
  document.addEventListener('pointerdown', outside)
}
onBeforeUnmount(close)
</script>

<template>
  <span class="inline-flex" @keydown.esc.stop="close">
    <button
      type="button"
      ref="button"
      :aria-label="`About ${label}`"
      :aria-expanded="open"
      :aria-controls="id"
      :aria-describedby="open ? id : undefined"
      class="inline-flex h-5 w-5 items-center justify-center rounded-full border border-slate-600 text-xs font-bold text-slate-300 hover:border-purple-400 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-purple-400"
      @click="toggle"
    >
      ?
    </button>
    <Teleport to="body">
      <span
        v-if="open"
        :id="id"
        role="note"
        ref="panel"
        :style="position"
        class="fixed z-[100] w-64 max-w-[75vw] rounded-xl border border-purple-500/40 bg-slate-950 p-3 text-xs font-normal normal-case leading-relaxed text-slate-200 shadow-xl"
      >
        {{ text }}
      </span>
    </Teleport>
  </span>
</template>
