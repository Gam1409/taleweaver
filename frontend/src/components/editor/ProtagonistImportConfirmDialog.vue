<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { FileInput } from 'lucide-vue-next'

const emit = defineEmits<{ confirm: []; cancel: [] }>()
const dialog = ref<HTMLDialogElement>()

function closeOnBackdrop(event: MouseEvent) {
  if (event.target !== dialog.value) return
  const box = dialog.value.getBoundingClientRect()
  if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) emit('cancel')
}

onMounted(() => dialog.value?.showModal())
onBeforeUnmount(() => dialog.value?.close())
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" class="authoring-dialog m-auto w-[calc(100%_-_2rem)] max-w-lg overflow-y-auto p-0" aria-labelledby="protagonist-import-title" aria-describedby="protagonist-import-description" @cancel.prevent="emit('cancel')" @click="closeOnBackdrop">
      <header class="flex items-center gap-3 border-b border-slate-700/60 p-5 sm:p-6">
        <FileInput class="h-5 w-5 shrink-0 text-amber-200/80" aria-hidden="true" />
        <h2 id="protagonist-import-title" class="text-xl font-semibold text-slate-100">Import protagonist?</h2>
      </header>
      <p id="protagonist-import-description" class="p-5 leading-relaxed text-slate-300 sm:p-6">Importing replaces the current protagonist profile, stats, and portrait. Inventory and equipment are kept.</p>
      <footer class="flex flex-wrap justify-end gap-3 border-t border-slate-700/60 p-4 sm:px-6">
        <button type="button" autofocus class="workspace-button" @click="emit('cancel')">Cancel</button>
        <button type="button" class="workspace-button workspace-primary" @click="emit('confirm')">Choose bundle</button>
      </footer>
    </dialog>
  </Teleport>
</template>
