<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
defineProps<{ title: string }>()
const emit = defineEmits<{ (event: 'close'): void }>()
const dialog = ref<HTMLDialogElement>()
let previous: HTMLElement | null = null
onMounted(async () => {
  previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
  await nextTick()
  dialog.value?.showModal()
})
onBeforeUnmount(() => {
  dialog.value?.close()
  previous?.focus()
})
</script>
<template>
  <Teleport to="body">
    <dialog
      ref="dialog"
      :aria-label="title"
      class="comfy-dialog m-auto h-[90dvh] max-h-[100dvh] w-[min(1280px,96vw)] max-w-none overflow-hidden rounded-2xl border border-slate-700 bg-slate-900 p-0 text-slate-100 max-sm:h-[100dvh] max-sm:w-full max-sm:rounded-none"
      @cancel.prevent="emit('close')"
    >
      <div class="flex h-full flex-col">
        <header
          class="flex shrink-0 items-center justify-between gap-4 border-b border-slate-700 px-6 py-4"
        >
          <h2 class="text-lg font-semibold">{{ title }}</h2>
          <button
            type="button"
            aria-label="Close window"
            class="rounded px-3 py-2 hover:bg-slate-700"
            @click="emit('close')"
          >
            ✕
          </button>
        </header>
        <main class="min-h-0 flex-1 overflow-y-auto p-5"><slot /></main>
        <footer
          v-if="$slots.footer"
          class="flex shrink-0 flex-wrap items-center justify-end gap-3 border-t border-slate-700 p-4"
        >
          <slot name="footer" />
        </footer>
      </div>
    </dialog>
  </Teleport>
</template>
<style scoped>
.comfy-dialog::backdrop {
  background: rgb(2 6 23 / 78%);
  backdrop-filter: blur(4px);
}
</style>
