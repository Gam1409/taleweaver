<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
defineProps<{ title: string; maximizable?: boolean }>()
const maximized = ref(false)
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
      class="workspace-dialog comfy-dialog m-auto h-[90dvh] max-h-[100dvh] w-[min(1280px,96vw)] max-w-none overflow-hidden rounded-2xl border border-slate-700 bg-slate-900 p-0 text-slate-100 max-sm:h-[100dvh] max-sm:w-full max-sm:rounded-none"
      :class="{ 'comfy-dialog-maximized': maximized }"
      @cancel.prevent="emit('close')"
    >
      <div class="flex h-full flex-col">
        <header
          class="flex shrink-0 items-center justify-between gap-4 border-b border-slate-700 px-6 py-4"
        >
          <h2 class="text-lg font-semibold">{{ title }}</h2>
          <div class="flex items-center gap-2">
            <button
              v-if="maximizable"
              type="button"
              class="rounded px-3 py-2 text-sm hover:bg-slate-700"
              :aria-label="maximized ? 'Restore window' : 'Maximize window'"
              :aria-pressed="maximized"
              @click="maximized = !maximized"
            >
              {{ maximized ? 'Restore' : 'Maximize' }}
            </button>
            <button
              type="button"
              aria-label="Close window"
              class="rounded px-3 py-2 hover:bg-slate-700"
              @click="emit('close')"
            >
              ✕
            </button>
          </div>
        </header>
        <main class="min-h-0 flex-1 p-5" :class="maximized ? 'overflow-hidden' : 'overflow-y-auto'">
          <slot :maximized="maximized" />
        </main>
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
.comfy-dialog-maximized {
  width: 100vw;
  height: 100dvh;
  max-height: 100dvh;
  margin: 0;
  border-radius: 0;
}
.comfy-dialog::backdrop {
  background: rgb(2 6 23 / 78%);
  backdrop-filter: blur(4px);
}
</style>
