<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
const props = defineProps<{ label: string; text: string }>()
const button = ref<HTMLButtonElement | null>(null)
const popup = ref<HTMLElement | null>(null)
const open = ref(false)
const pinned = ref(false)
const position = ref({ left: '0px', top: '0px' })
const id = computed(() => 'living-help-' + props.label.toLowerCase().replace(/[^a-z0-9]+/g, '-'))
function show(): void {
  const rect = button.value?.getBoundingClientRect()
  if (!rect) return
  position.value = { left: `${Math.max(12, Math.min(rect.right - 320, window.innerWidth - 332))}px`, top: `${Math.max(12, Math.min(rect.bottom + 8, window.innerHeight - 220))}px` }
  open.value = true
}
function leave(): void { if (!pinned.value) open.value = false }
function toggle(): void { pinned.value = !pinned.value; if (pinned.value) show(); else open.value = false }
function close(): void { open.value = false; pinned.value = false }
function outside(event: MouseEvent): void {
  if (!button.value?.contains(event.target as Node) && !popup.value?.contains(event.target as Node)) close()
}
onMounted(() => document.addEventListener('click', outside))
onBeforeUnmount(() => document.removeEventListener('click', outside))
</script>

<template>
  <button ref="button" type="button" class="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-white/20 bg-black/30 text-xs font-black text-white/60 transition hover:border-cyan-400/60 hover:text-cyan-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-400" :aria-label="`Help: ${label}`" :aria-expanded="open" :aria-describedby="open ? id : undefined" @mouseenter="show" @mouseleave="leave" @focus="show" @blur="leave" @click="toggle" @keydown.esc.stop="close">?</button>
  <Teleport to="body">
    <div v-if="open" :id="id" ref="popup" role="tooltip" :style="position" class="fixed z-[200] max-h-48 w-80 max-w-[calc(100vw-24px)] overflow-auto rounded-xl border border-cyan-400/30 bg-slate-950 p-4 text-xs leading-relaxed text-slate-200 shadow-2xl">
      <p class="mb-2 font-black uppercase tracking-wider text-cyan-300">{{ label }}</p>{{ text }}
    </div>
  </Teleport>
</template>
