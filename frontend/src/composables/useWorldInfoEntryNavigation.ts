import { nextTick, onScopeDispose, ref, watch, type Ref } from 'vue'
import type { WorldInfoController } from './useWorldInfo'

interface EntryDialog { dismissImmediately: () => void }
/** Swap two native dialogs while retaining the catalog DOM, scroll positions and opener. */
export function useWorldInfoEntryNavigation(dialog: Ref<HTMLDialogElement | undefined>, controller: WorldInfoController, sessionId: Readonly<Ref<string>>) {
  const entryOpen = ref(false)
  const entryDialog = ref<EntryDialog>()
  function setEntryDialog(value: unknown) { entryDialog.value = value ? value as EntryDialog : undefined }
  let entryId = ''
  let alive = true
  let positions: { element: HTMLElement; top: number; left: number }[] = []
  function remember() {
    positions = Array.from(dialog.value?.querySelectorAll<HTMLElement>('.world-info-catalog-results, .world-info-catalog-tools, .world-info-topics') ?? []).map(element => ({ element, top: element.scrollTop, left: element.scrollLeft }))
  }
  function restore() { for (const position of positions) { position.element.scrollTop = position.top; position.element.scrollLeft = position.left } }
  async function openEntry(id: string) {
    if (entryOpen.value || controller.data.busy) return
    entryId = id
    remember()
    dialog.value?.close()
    entryOpen.value = true
    await controller.openEntry(id)
  }
  async function backToCatalog() {
    if (!alive) return
    const sid = sessionId.value
    entryDialog.value?.dismissImmediately()
    entryOpen.value = false
    controller.closeEntry()
    await nextTick()
    if (!alive || sid !== sessionId.value || !dialog.value?.isConnected) return
    if (!dialog.value.open) dialog.value.showModal()
    await nextTick()
    restore()
    const rows = Array.from(dialog.value.querySelectorAll<HTMLButtonElement>('[data-world-info-entry]'))
    const opener = rows.find(row => row.dataset.worldInfoEntry === entryId)
    const target = opener ?? rows[0] ?? dialog.value.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')
    target?.focus({ preventScroll: true })
    if (opener) restore()
    else target?.scrollIntoView({ block: 'nearest' })
  }
  watch(sessionId, async () => {
    entryDialog.value?.dismissImmediately()
    entryOpen.value = false
    entryId = ''
    positions = []
    await nextTick()
    if (alive && dialog.value?.isConnected && !dialog.value.open) dialog.value.showModal()
  }, { flush: 'sync' })
  onScopeDispose(() => { alive = false; entryDialog.value?.dismissImmediately() })
  return { entryOpen, setEntryDialog, openEntry, backToCatalog }
}
