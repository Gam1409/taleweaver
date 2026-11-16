<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { apiFetch } from '@/services/http'
import { ClipboardCheck } from 'lucide-vue-next'
const props = defineProps<{ sessionId: string }>()
interface Checks {
  mode: string
  items: {
    status: string
    reason: string
    error_type: string
    failure?: {
      code: string
      reason: string
      validation_fields?: string[]
      validation_details?: { field: string; code: string; reason: string }[]
    } | null
    message_id: string
    accepted: { name: string; destination: string; disposition: string }[]
    rejected: string[]
    rejected_details?: { label: string; reason: string; basis: string; evidence: string }[]
  }
  arrival: {
    destination: string
    player_entered: boolean
    companions: { npc_id: string; name: string; status: string }[]
  } | null
}
const dialog = ref<HTMLDialogElement>()
const result = ref<Checks | null>(null)
const error = ref('')
const loading = ref(false)
let request = 0
async function refresh(): Promise<void> {
  const version = ++request
  loading.value = true
  error.value = ''
  try {
    const response = await apiFetch(
      `/adventures/${encodeURIComponent(props.sessionId)}/state-checks`
    )
    if (!response.ok) throw new Error('Could not load the latest checks.')
    const value = (await response.json()) as Checks
    if (version === request) result.value = value
  } catch (cause) {
    if (version === request)
      error.value = cause instanceof Error ? cause.message : 'Could not load checks.'
  } finally {
    if (version === request) loading.value = false
  }
}
function open(): void {
  dialog.value?.showModal()
  void refresh()
}
watch(
  () => props.sessionId,
  () => {
    request++
    dialog.value?.close()
    result.value = null
    loading.value = false
  }
)
onBeforeUnmount(() => {
  request++
  dialog.value?.close()
})
</script>
<template>
  <button type="button" class="inline-flex w-fit items-center gap-2 rounded-xl border border-cyan-500/30 bg-slate-950 px-3 py-2 text-xs font-bold text-cyan-300 hover:bg-cyan-500/10 focus-visible:ring-2 focus-visible:ring-cyan-400" @click="open">
    <ClipboardCheck class="h-4 w-4" aria-hidden="true" />
    Item and travel checks
  </button>
  <Teleport to="body">
    <dialog
      ref="dialog"
      aria-label="Item and travel checks"
      class="m-auto max-h-[85dvh] w-[min(640px,94vw)] overflow-y-auto rounded-xl border border-slate-600 bg-slate-900 p-5 text-slate-100"
    >
      <header class="mb-4 flex items-center justify-between gap-3">
        <h2 class="font-bold">Item and travel checks</h2>
        <button type="button" aria-label="Close checks" @click="dialog?.close()">✕</button>
      </header>
      <p class="mb-3 text-xs text-slate-400">
        Saved results remain available here. Refresh after the current turn finishes.
      </p>
      <button
        type="button"
        :disabled="loading"
        class="mb-4 rounded bg-cyan-800 px-3 py-2 text-sm disabled:opacity-50"
        @click="refresh"
      >
        {{ loading ? 'Loading…' : 'Refresh checks' }}
      </button>
      <p v-if="error" role="alert" class="text-rose-300">{{ error }}</p>
      <div v-if="result" class="space-y-5 text-sm" aria-live="polite">
        <section class="space-y-2">
          <h3 class="font-bold">Items — {{ result.items.status }}</h3>
          <p v-if="result.mode !== 'vn'" class="text-amber-300">
            Post-narration item checks currently run in VN mode. This session uses
            {{ result.mode }}.
          </p>
          <p v-if="result.items.reason">{{ result.items.reason }}</p>
          <p v-if="result.items.error_type">Failure: {{ result.items.error_type }}</p>
          <div v-if="result.items.failure" class="space-y-2 rounded border border-amber-500/30 p-3 text-amber-300">
            <p>{{ result.items.failure.reason }}</p>
            <ul v-if="result.items.failure.validation_details?.length" class="space-y-2">
              <li v-for="(detail, index) in result.items.failure.validation_details" :key="index">
                <code class="break-all">{{ detail.field }}</code>: {{ detail.reason }}
              </li>
            </ul>
            <p v-else-if="result.items.failure.validation_fields?.length" class="break-all">
              Validation fields: {{ result.items.failure.validation_fields.join(', ') }}
            </p>
          </div>
          <p
            v-if="
              result.items.status === 'complete' &&
              !result.items.accepted.length &&
              !result.items.rejected.length
            "
          >
            No additional item changes were detected in the completed response.
          </p>
          <ul class="space-y-1">
            <li v-for="(item, index) in result.items.accepted" :key="index">
              {{ item.name }} →
              {{ item.destination === '__player__' ? 'Player' : item.destination }} ({{
                item.disposition
              }})
            </li>
            <li
              v-for="(reason, index) in result.items.rejected"
              :key="`rejected-${index}`"
              class="text-amber-300"
            >
              Not applied: {{ reason }}
            </li>
          </ul>
          <details v-if="result.items.rejected_details?.length" class="rounded border border-amber-500/30 p-3">
            <summary class="cursor-pointer font-semibold text-amber-300">Rejected proposal details</summary>
            <p class="mt-2 text-xs text-slate-400">
              These quotes were proposed by the model and were not accepted as evidence.
              Compare them with the original narration before correcting a clothing record.
            </p>
            <ul class="mt-3 space-y-4">
              <li v-for="(proposal, index) in result.items.rejected_details" :key="index" class="space-y-1 break-words">
                <p class="font-semibold">{{ proposal.label }}</p>
                <p class="text-amber-300">{{ proposal.reason }}</p>
                <p class="text-xs text-slate-400">Action basis: {{ proposal.basis }}</p>
                <blockquote class="whitespace-pre-wrap border-l-2 border-slate-600 pl-3">{{ proposal.evidence }}</blockquote>
              </li>
            </ul>
          </details>
          <p v-if="result.items.message_id" class="break-all font-mono text-xs text-slate-400">
            Source turn: {{ result.items.message_id }}
          </p>
        </section>
        <section class="space-y-2">
          <h3 class="font-bold">Latest local arrival</h3>
          <template v-if="result.arrival">
            <p class="break-all">Destination: {{ result.arrival.destination }}</p>
            <p>Player entered: {{ result.arrival.player_entered ? 'Yes' : 'No' }}</p>
            <p v-if="!result.arrival.companions.length">
              No accompanying NPCs were confirmed for this arrival.
            </p>
            <ul>
              <li v-for="npc in result.arrival.companions" :key="npc.npc_id">
                {{ npc.name }} — {{ npc.status }}
              </li>
            </ul>
          </template>
          <p v-else>No local arrival check has been recorded yet.</p>
        </section>
      </div>
    </dialog>
  </Teleport>
</template>
