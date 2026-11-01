<script setup lang="ts">
import { computed, onScopeDispose, ref, watch } from 'vue'
import { History } from 'lucide-vue-next'
import { useGameSocket } from '@/composables/useGameSocket'
import { useNotifications } from '@/composables/useNotifications'
import { apiFetch } from '@/services/http'
import type { ChatMessage } from '@/types'

const props = defineProps<{ gameId?: string, disabled?: boolean }>()
const socket = useGameSocket()
const { addNotification } = useNotifications()
const dialog = ref<HTMLDialogElement>()
const busy = ref(false)
const revisions = ref<{ id: string | null, content: string, origin: string }[]>([])
const current = ref<string | null>(null)
const selected = ref('')
let disposed = false
let generation = 0
onScopeDispose(() => { disposed = true; generation++ })
watch(() => props.gameId, () => { generation++; dialog.value?.close(); revisions.value = [] })
const latest = computed(() => [...socket.messages.value].reverse().find(m => ['user', 'assistant'].includes(m.role)))
const unavailable = computed(() => props.disabled || busy.value || latest.value?.role !== 'assistant' ||
  !latest.value.id || socket.inputLocked.value || socket.sheet.value?.agent_active ||
  !['connected', 'completed'].includes(socket.status.value))
const preview = computed(() => revisions.value.find(r => r.id === selected.value)?.content ?? '')
async function request(restore = false) {
  if (unavailable.value || !props.gameId || !latest.value?.id) return
  const id = props.gameId
  const messageId = latest.value.id
  const token = ++generation
  busy.value = true
  try {
    const response = await apiFetch(`/adventures/${encodeURIComponent(id)}/chat/${encodeURIComponent(messageId)}/versions${restore ? '/restore' : ''}`, restore ? {
      method: 'POST', includeJson: true,
      body: JSON.stringify({ version_id: selected.value, expected_revision_id: current.value }),
    } : {})
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Could not load narration versions.')
    if (disposed || token !== generation || props.gameId !== id || latest.value?.id !== messageId) return
    if (restore) {
      socket.messages.value = socket.messages.value.map(m => m.id === messageId ? data as ChatMessage : m)
      dialog.value?.close()
    } else {
      revisions.value = data.versions
      current.value = data.current_revision_id
      selected.value = current.value ?? ''
      dialog.value?.showModal()
    }
  } catch (error) {
    if (!disposed && token === generation) addNotification(error instanceof Error ? error.message : 'Could not load narration versions.', 'error')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <button type="button" :disabled="unavailable" title="Narration versions" aria-label="Narration versions"
    class="h-9 min-w-9 shrink-0 rounded-lg p-2 text-slate-300 hover:bg-slate-700/70 disabled:opacity-40" @click="request()">
    <History :size="18" />
  </button>
  <dialog ref="dialog" aria-label="Narration versions" class="w-[min(40rem,90vw)] max-h-[85dvh] rounded-xl border border-slate-600 bg-slate-900 p-5 text-slate-100 backdrop:bg-black/70">
    <h2 class="text-lg font-bold">Narration versions</h2>
    <p class="my-3 text-sm text-slate-300">Restoring replaces the latest narration only. It does not replay actions or restore world state. Derived poses will need confirmation.</p>
    <label class="block text-sm">Version
      <select v-model="selected" class="my-2 w-full rounded border border-slate-600 bg-slate-800 p-2">
        <option v-for="(revision, index) in revisions" :key="revision.id ?? 'original'" :value="revision.id ?? ''">{{ index + 1 }} — {{ revision.origin }}{{ revision.id === current ? ' (current)' : '' }}</option>
      </select>
    </label>
    <p class="max-h-[40dvh] overflow-auto whitespace-pre-wrap rounded bg-slate-950 p-3 text-sm">{{ preview }}</p>
    <div class="mt-4 flex justify-end gap-3">
      <button type="button" class="rounded border border-slate-600 px-4 py-2" @click="dialog?.close()">Close</button>
      <button type="button" :disabled="unavailable || !selected || selected === current" class="rounded bg-amber-600 px-4 py-2 disabled:opacity-40" @click="request(true)">Restore text</button>
    </div>
  </dialog>
</template>
