<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ArrowLeft, Pencil, X } from 'lucide-vue-next'
import type { WorldInfoController } from '@/composables/useWorldInfo'
import { useWorldInfoViewport } from '@/composables/useWorldInfoViewport'
import WorldInfoEntryEditor from './WorldInfoEntryEditor.vue'
import WorldInfoEntryView from './WorldInfoEntryView.vue'
const props = defineProps<{ controller: WorldInfoController }>()
const emit = defineEmits<{ back: [] }>()
const data = props.controller.data
const viewport = useWorldInfoViewport(1080)
const dialog = ref<HTMLDialogElement>()
const content = ref<HTMLElement>()
const more = ref<HTMLDetailsElement>()
const editing = ref(false)
const confirmation = ref<{ title: string; text: string; action: () => unknown } | null>(null)
let confirmationOpener: HTMLElement | null = null
let alive = true
function confirm(title: string, text: string, action: () => unknown) {
  confirmationOpener = document.activeElement instanceof HTMLElement ? document.activeElement : null
  confirmation.value = { title, text, action }
  void nextTick(() => dialog.value?.querySelector<HTMLButtonElement>('[data-confirm-action]')?.focus())
}
function cancelConfirmation() {
  confirmation.value = null
  void nextTick(() => {
    if (confirmationOpener?.isConnected && confirmationOpener.getClientRects().length) confirmationOpener.focus()
    else dialog.value?.querySelector<HTMLElement>('[data-entry-more]')?.focus()
  })
}
function guard(action: () => unknown) {
  if (data.busy) return
  if (!props.controller.dirty.value) { void action(); return }
  confirm('Discard unsaved entry changes?', 'Your saved entry and original source are kept.', () => { props.controller.discardEntry(); void action() })
}
function back() { guard(() => emit('back')) }
async function edit() {
  editing.value = true
  await nextTick()
  if (content.value) content.value.scrollTop = 0
  dialog.value?.querySelector<HTMLInputElement>('#world-info-entry-form input')?.focus({ preventScroll: true })
}
async function saved() {
  if (props.controller.dirty.value) return
  editing.value = false
  await nextTick()
  if (content.value) content.value.scrollTop = 0
  dialog.value?.querySelector<HTMLButtonElement>('[data-edit-entry]')?.focus({ preventScroll: true })
}
function cancelEdit() { guard(() => { props.controller.discardEntry(); void saved() }) }
function reload() { if (more.value) more.value.open = false; guard(async () => { const id = data.draft?.id; if (id) { editing.value = false; await props.controller.openEntry(id) } }) }
function remove(action: 'delete' | 'unpublish') {
  if (more.value) more.value.open = false
  confirm(action === 'delete' ? 'Delete this entry?' : 'Remove this entry from recall?', action === 'delete' ? 'This entry and links to it will be removed. Original source text and chat history are kept.' : 'This entry stops contributing to recall. Its source and saved text are kept.', async () => {
    const ok = await (action === 'delete' ? props.controller.removeEntry() : props.controller.unpublish())
    if (alive && ok) emit('back')
  })
}
function confirmAction() { const action = confirmation.value?.action; confirmation.value = null; void action?.() }
function dismissImmediately() { confirmation.value = null; dialog.value?.close() }
defineExpose({ dismissImmediately })
onMounted(async () => { await nextTick(); if (alive) dialog.value?.showModal() })
onBeforeUnmount(() => { alive = false; dismissImmediately() })
</script>
<template>
  <Teleport to="body">
    <dialog ref="dialog" class="world-info-window world-info-entry-dialog" :class="{ 'is-short': viewport.short.value, 'is-tiny': viewport.tiny.value, 'is-narrow': viewport.narrow.value }" :style="viewport.style.value" aria-labelledby="world-info-entry-dialog-title" @cancel.prevent="confirmation ? cancelConfirmation() : back()">
      <header :inert="!!confirmation" class="world-info-heading"><div class="min-w-0"><span class="world-info-eyebrow">WORLD INFO · {{ editing ? 'EDIT ENTRY' : 'VIEW ENTRY' }}</span><h2 id="world-info-entry-dialog-title" :title="data.draft?.title">{{ data.draft?.title || 'World Info entry' }}</h2><p v-if="data.draft">{{ data.draft.source_filename }} · source version {{ data.draft.source_revision_number }}</p></div><button type="button" class="world-info-button" aria-label="Close entry" :disabled="!!data.busy" @click="back"><X class="h-4 w-4" aria-hidden="true" /></button></header>
      <div class="world-info-entry-notices"><p v-if="data.entryLoading" role="status">Loading entry…</p><p v-if="data.busy" role="status">{{ data.busy }}</p><p v-if="data.message" role="status" class="text-emerald-200">{{ data.message }}</p><p v-if="data.error" role="alert" class="text-rose-200">{{ data.error }}</p></div>
      <main ref="content" :inert="!!confirmation" class="world-info-entry-dialog-body">
        <WorldInfoEntryEditor v-if="editing && data.draft" :controller="controller" form-id="world-info-entry-form" :actions="false" @saved="saved" />
        <WorldInfoEntryView v-else-if="data.draft" :controller="controller" />
        <p v-else-if="!data.entryLoading" class="world-info-empty">The entry could not be opened. Return to the catalog to select it again.</p>
      </main>
      <section v-if="confirmation" class="world-info-confirm" aria-label="Confirm entry action"><h3 class="font-semibold">{{ confirmation.title }}</h3><p class="mt-1 text-sm">{{ confirmation.text }}</p><div class="mt-3 flex flex-wrap gap-2"><button type="button" class="world-info-button" @click="cancelConfirmation">Keep current state</button><button data-confirm-action type="button" class="world-info-button is-primary" :disabled="!!data.busy" @click="confirmAction">Confirm</button></div></section>
      <footer :inert="!!confirmation" class="world-info-footer world-info-entry-footer"><button type="button" class="world-info-button" :disabled="!!data.busy" @click="back"><ArrowLeft class="h-4 w-4" aria-hidden="true" />Back to catalog</button><div class="flex flex-wrap items-center gap-2"><span v-if="editing && controller.dirty.value">Unsaved changes</span><details v-if="!editing && data.draft" ref="more" class="world-info-entry-actions"><summary data-entry-more class="world-info-button">More actions</summary><div class="world-info-entry-actions-panel"><button type="button" class="world-info-button" :disabled="!!data.busy" @click="reload">Reload latest entry</button><button v-if="data.draft.is_active" type="button" class="world-info-button" :disabled="!!data.busy" @click="remove('unpublish')">Remove from recall</button><button type="button" class="world-info-button is-danger" :disabled="!!data.busy" @click="remove('delete')">Delete entry</button></div></details><template v-if="editing"><button type="button" class="world-info-button" :disabled="!!data.busy" @click="cancelEdit">Cancel editing</button><button type="submit" form="world-info-entry-form" class="world-info-button is-primary" :disabled="!!data.busy || !controller.dirty.value || (data.draft?.audience === 'restricted' && !data.draft.known_by.length)">Save entry</button></template><button v-else-if="data.draft" data-edit-entry type="button" class="world-info-button is-primary" :disabled="!!data.busy" @click="edit"><Pencil class="h-4 w-4" aria-hidden="true" />Edit entry</button></div></footer>
    </dialog>
  </Teleport>
</template>
