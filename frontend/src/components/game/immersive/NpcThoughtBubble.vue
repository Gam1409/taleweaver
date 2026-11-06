<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
const props = defineProps<{ text: string; name: string; anchor: HTMLElement | null }>()
const emit = defineEmits<{ dismiss: [] }>()
const bubble = ref<HTMLElement | null>(null)
const position = ref({ left: '0px', top: '0px', visibility: 'hidden' as 'visible' | 'hidden' })
async function place() {
  position.value.visibility = 'hidden'
  await nextTick()
  if (!props.anchor || !bubble.value) return
  const rect = props.anchor.getBoundingClientRect()
  const box = bubble.value.getBoundingClientRect()
  const right = rect.right + 12
  const left = right + box.width <= window.innerWidth - 12 ? right : rect.left - box.width - 12
  position.value = {
    left: `${Math.max(12, Math.min(left, window.innerWidth - box.width - 12))}px`,
    top: `${Math.max(12, Math.min(rect.top + rect.height / 3, window.innerHeight - box.height - 12))}px`,
    visibility: 'visible',
  }
}
watch(() => [props.text, props.anchor], place, { immediate: true, flush: 'post' })
function dismiss() { emit('dismiss') }
function keydown(event: KeyboardEvent) { if (event.key === 'Escape') dismiss() }
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
    <Transition name="npc-thought">
      <div v-if="text && anchor" id="npc-current-thought" ref="bubble" role="tooltip" :style="position" class="npc-thought-bubble fixed z-[100] w-64 max-w-[calc(100vw-24px)] pointer-events-none rounded-2xl border border-fuchsia-300/30 bg-slate-950/95 px-4 py-3 shadow-2xl backdrop-blur-md">
        <span class="block mb-1 text-[10px] font-bold uppercase tracking-widest text-fuchsia-200/75">{{ name }}</span>
        <p class="text-sm italic leading-relaxed text-slate-100 break-words">{{ text }}</p>
        <span aria-hidden="true" class="absolute -bottom-2 left-5 w-3 h-3 rounded-full bg-slate-950 border border-fuchsia-300/30"></span>
        <span aria-hidden="true" class="absolute -bottom-4 left-3 w-1.5 h-1.5 rounded-full bg-slate-950 border border-fuchsia-300/30"></span>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.npc-thought-enter-active, .npc-thought-leave-active { transition: opacity 180ms ease, transform 180ms ease; }
.npc-thought-enter-from, .npc-thought-leave-to { opacity: 0; transform: translateY(6px) scale(.97); }
@media (prefers-reduced-motion: reduce) {
  .npc-thought-enter-active, .npc-thought-leave-active { transition: none; }
}
</style>
