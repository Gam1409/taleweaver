<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, toRef, watch } from 'vue'
import { BookOpenText, X } from 'lucide-vue-next'
import { useWorldInfo } from '@/composables/useWorldInfo'
import { useWorldInfoEntryNavigation } from '@/composables/useWorldInfoEntryNavigation'
import WorldInfoEntryDialog from './world-info/WorldInfoEntryDialog.vue'
import { useWorldInfoViewport } from '@/composables/useWorldInfoViewport'
import { indexMessage, infoCount, worldInfoTagLabel } from '@/services/worldInfoDisplay'
import type { WorldInfoSource, WorldInfoTab } from '@/types/worldInfo'
import WorldInfoFiles from './world-info/WorldInfoFiles.vue'
import WorldInfoEntries from './world-info/WorldInfoEntries.vue'
import './world-info/world-info.css'
const props = defineProps<{ sessionId: string }>()
const emit = defineEmits<{ close: [] }>()
const controller = useWorldInfo(toRef(props, 'sessionId'))
const data = controller.data
const viewport = useWorldInfoViewport()
const dialog = ref<HTMLDialogElement>()
const { entryOpen, setEntryDialog, openEntry, backToCatalog } = useWorldInfoEntryNavigation(dialog, controller, toRef(props, 'sessionId'))
const confirmation = ref<{ title: string; text: string; action: () => unknown } | null>(null)
const tabs: { id: WorldInfoTab; label: string }[] = [{ id: 'files', label: 'Files & processing' }, { id: 'review', label: 'Review' }, { id: 'active', label: 'Active entries' }]
let previous: HTMLElement | null = null
let confirmationOpener: HTMLElement | null = null
function confirm(title: string, text: string, action: () => unknown) {
  confirmationOpener = document.activeElement instanceof HTMLElement ? document.activeElement : null
  confirmation.value = { title, text, action }
  void nextTick(() => dialog.value?.querySelector<HTMLButtonElement>('[data-confirm-action]')?.focus())
}
function cancelConfirmation() {
  confirmation.value = null
  void nextTick(() => { if (confirmationOpener?.isConnected) confirmationOpener.focus() })
}
function navigate(action: () => unknown) {
  if (!controller.dirty.value) { void action(); return }
  confirm('Discard unsaved entry changes?', 'Your saved entry and original source are kept.', action)
}
function close() { navigate(() => emit('close')) }
function removeSource(source: WorldInfoSource) {
  confirm('Delete this source?', 'This removes the source, its versions, draft and accepted entries, and their links from this session. Chat history is kept.', () => controller.removeSource(source))
}
function publish() {
  const source = controller.selectedSource.value
  const revision = controller.selectedEntries.value[0]?.source_revision_number
  if (!source) return
  const selection = JSON.parse(JSON.stringify({ source, entries: controller.selectedEntries.value }))
  if (source?.published_revision && source.published_revision !== revision) {
    confirm('Replace the accepted source version?', 'Publishing this version replaces the source’s previously accepted entries. Unselected entries remain drafts. Other sources are kept.', () => controller.publish(selection))
    return
  }
  void controller.publish(selection)
}
function bulkConfirm() {
  const selection = controller.catalog.bulkSelection()
  if (!selection) return
  const publishing = selection.intent.action === 'publish'
  const action = publishing ? 'Publish matching entries.' : selection.intent.action === 'set_group' ? `Set primary group to ${selection.intent.group_name || 'Ungrouped'}.` : `${selection.intent.action === 'add_tags' ? 'Add' : 'Remove'} tags ${selection.intent.tags?.map(worldInfoTagLabel).join(' ')}.`
  confirm(`Apply to ${infoCount(selection.preview.count)} matching entries?`, `${action} ${infoCount(selection.preview.facts_count)} facts in this session match the current filters. ${publishing ? 'Publishing this source version may replace its previously accepted entries.' : 'Every matching entry is included, across all pages.'} Changes are applied together after the saved selection is checked again.`, () => controller.catalog.applyBulk(selection))
}
function confirmAction() { const action = confirmation.value?.action; confirmation.value = null; void action?.() }
function tabKey(event: KeyboardEvent) {
  if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const index = tabs.findIndex(tab => tab.id === data.tab)
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (index + (event.key === 'ArrowRight' ? 1 : -1) + 3) % 3
  const tab = tabs[next]!
  navigate(async () => { await controller.changeTab(tab.id); dialog.value?.querySelector<HTMLButtonElement>(`#world-info-tab-${tab.id}`)?.focus() })
}
watch(() => props.sessionId, () => { confirmation.value = null })
onMounted(async () => {
  const active = document.activeElement instanceof HTMLElement ? document.activeElement : null
  const owner = active?.closest('[role="menu"]')?.getAttribute('aria-labelledby')
  previous = owner ? document.getElementById(owner) : active
  if (!previous?.isConnected || previous === document.body) previous = document.querySelector<HTMLElement>('.header-session-menu [aria-haspopup="menu"]')
  await nextTick()
  dialog.value?.showModal()
})
onBeforeUnmount(() => {
  dialog.value?.close()
  const opener = previous
  requestAnimationFrame(() => { if (opener?.isConnected && !document.querySelector('dialog[open]')) opener.focus() })
})
</script>
<template>
  <Teleport to="body">
    <dialog ref="dialog" class="world-info-window" :class="{ 'is-short': viewport.short.value, 'is-tiny': viewport.tiny.value, 'is-narrow': viewport.narrow.value }" :style="viewport.style.value" aria-labelledby="world-info-title" @cancel.prevent="confirmation ? cancelConfirmation() : close()">
      <header class="world-info-heading"><div><span class="world-info-eyebrow"><BookOpenText aria-hidden="true" class="h-4 w-4" />CURRENT SESSION</span><h2 id="world-info-title">World Info</h2><p>Knowledge for this session</p></div><button type="button" class="world-info-button" aria-label="Close World Info" @click="close"><X aria-hidden="true" class="h-4 w-4" /></button></header>
      <nav :inert="!!confirmation" class="world-info-tabs" role="tablist" aria-label="World Info sections" @keydown="tabKey"><button v-for="tab in tabs" :id="`world-info-tab-${tab.id}`" :key="tab.id" type="button" role="tab" :aria-selected="data.tab === tab.id" :tabindex="data.tab === tab.id ? 0 : -1" :aria-controls="`world-info-panel-${tab.id}`" @click="navigate(() => controller.changeTab(tab.id))">{{ tab.label }}</button></nav>
      <div :inert="!!confirmation" class="world-info-notices">
        <div v-if="data.state?.totals" class="world-info-totals" aria-label="Session knowledge counts"><span><strong>{{ infoCount(data.state.totals.entries) }}</strong> entries</span><span><strong>{{ infoCount(data.state.totals.facts) }}</strong> facts</span><span>{{ infoCount(data.state.totals.active_entries) }} accepted</span><span>{{ infoCount(data.state.totals.draft_entries) }} drafts</span><span>{{ infoCount(data.state.totals.sources) }} sources</span></div>
        <p v-if="data.loading" role="status">Loading session knowledge…</p>
        <p v-if="data.busy" role="status">{{ data.busy }}</p>
        <p v-if="data.message" role="status" class="text-emerald-200">{{ data.message }}</p>
        <p v-if="data.error" role="alert" class="text-rose-200">{{ data.error }}</p>
        <p v-if="data.offline" role="status" class="text-amber-200">Status checks are paused. Processing may still be running. <button class="underline" @click="controller.load()">Reconnect</button></p>
        <details v-if="data.state" class="world-info-index-details" :open="data.tab === 'files'"><summary>Memory & indexing</summary><div class="world-info-index"><p>{{ indexMessage(data.state.index) }}</p><div class="flex flex-wrap gap-2"><button type="button" class="world-info-button" :disabled="data.loading || !!data.busy" @click="controller.load()">Refresh status</button><button type="button" class="world-info-button" :disabled="!!data.busy || !data.state.index.enabled" @click="controller.rebuild()">Rebuild this session’s index</button></div></div></details>
        <button v-if="!data.state && !data.loading" class="world-info-button" @click="controller.load()">Retry loading</button>
      </div>
      <main :id="`world-info-panel-${data.tab}`" :inert="!!confirmation" class="world-info-body" role="tabpanel" :aria-labelledby="`world-info-tab-${data.tab}`">
        <WorldInfoFiles v-if="data.tab === 'files'" :key="props.sessionId" :controller="controller" @remove="removeSource" />
        <WorldInfoEntries v-else :key="props.sessionId" :controller="controller" @navigate="navigate" @open-entry="openEntry" @publish="publish" @bulk-apply="bulkConfirm" />
      </main>
      <section v-if="confirmation" class="world-info-confirm" aria-label="Confirm World Info action"><h3 class="font-semibold">{{ confirmation.title }}</h3><p class="mt-1 text-sm">{{ confirmation.text }}</p><div class="mt-3 flex flex-wrap gap-2"><button type="button" class="world-info-button" @click="cancelConfirmation">Keep current state</button><button data-confirm-action type="button" class="world-info-button is-primary" :disabled="!!data.busy" @click="confirmAction">Confirm</button></div></section>
      <footer class="world-info-footer"><span>{{ controller.dirty.value ? 'Unsaved entry changes' : 'Sources and entries belong only to this session.' }}</span><button type="button" class="world-info-button" @click="close">Close</button></footer>
    </dialog>
    <WorldInfoEntryDialog v-if="entryOpen" :key="props.sessionId" :ref="setEntryDialog" :controller="controller" @back="backToCatalog" />
  </Teleport>
</template>
