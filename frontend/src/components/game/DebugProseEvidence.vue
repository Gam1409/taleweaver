<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { apiFetch } from '@/services/http'

const props = defineProps<{ sessionId: string }>()
interface Finding {
  kind: string; value: string; actor_id: string | null; item_id: string | null
  recipient_id: string | null; resolved: boolean; latest: boolean
  passage_id: string; prefix: string; quote: string; suffix: string
}
interface Review {
  has_snapshot: boolean
  sources: { message_id: string; revision_id: string | null; role: string; discarded: number; completed_passes: number; requested_passes: number; events: Finding[]; error?: string }[]
}
const review = ref<Review | null>(null)
const busy = ref(false)
const error = ref('')
let request: AbortController | null = null
function reset() {
  request?.abort()
  request = null
  review.value = null
  error.value = ''
  busy.value = false
}
watch(() => props.sessionId, reset)
onBeforeUnmount(reset)
async function inspect() {
  if (busy.value) return
  reset()
  const current = new AbortController()
  request = current
  busy.value = true
  try {
    const response = await apiFetch(`/adventures/${encodeURIComponent(props.sessionId)}/prose-evidence`, {
      method: 'POST', signal: current.signal, timeoutMs: null,
    })
    const result = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Evidence review failed.')
    if (!Array.isArray(result.sources)) throw new Error('The evidence review returned an incomplete response.')
    if (current === request) review.value = result
  } catch (cause) {
    if (current === request) error.value = cause instanceof Error ? cause.message : 'Evidence review failed.'
  } finally {
    if (current === request) {
      request = null
      busy.value = false
    }
  }
}
</script>
<template>
  <section class="space-y-3 rounded-xl border border-slate-700 bg-slate-900/70 p-4">
    <h3 class="font-bold text-white">Turn evidence</h3>
    <p class="text-xs text-slate-400">Review the latest published turn. The configured model reads the player and narrator separately. Findings are read-only.</p>
    <button type="button" class="rounded-lg border border-cyan-500/40 px-3 py-2 text-sm text-cyan-200 disabled:opacity-50" :disabled="busy" @click="inspect">
      {{ busy ? 'Reviewing…' : 'Review latest turn' }}
    </button>
    <p v-if="error" role="alert" class="text-sm text-rose-300">{{ error }}</p>
    <div v-if="review" aria-live="polite" class="space-y-4">
      <p v-if="!review.has_snapshot" class="text-xs text-amber-200">The original scene snapshot is unavailable. Item references are unresolved.</p>
      <section v-for="source in review.sources" :key="source.message_id" class="space-y-2">
        <h4 class="font-semibold">{{ source.role === 'user' ? 'Player' : 'Narrator' }}</h4>
        <p v-if="source.requested_passes > 1" class="text-xs text-slate-400">
          {{ source.completed_passes }} of {{ source.requested_passes }} passes completed.
          <span v-if="source.completed_passes < source.requested_passes" class="text-amber-200">Partial review.</span>
        </p>
        <p v-if="source.error" role="alert" class="text-sm text-amber-200">{{ source.error }}</p>
        <p v-else-if="!source.events.length" class="text-sm text-slate-400">No supported findings returned.</p>
        <p v-if="source.discarded" class="text-xs text-amber-200">{{ source.discarded }} unsupported or conflicting findings omitted.</p>
        <article v-for="(event, i) in source.events" :key="i" class="rounded-lg bg-slate-950/70 p-3 text-sm">
          <p>{{ event.kind }} · {{ event.value }} · {{ event.actor_id || 'Unknown actor' }} <span v-if="event.item_id">· {{ event.item_id }}</span><span v-if="event.recipient_id"> → {{ event.recipient_id }}</span></p>
          <p class="text-xs text-amber-200">{{ !event.resolved ? 'Unresolved reference' : event.latest ? 'Last mention in this source' : '' }}</p>
          <blockquote class="mt-1 whitespace-pre-wrap break-words text-slate-400">{{ event.prefix }}<mark class="rounded bg-amber-300/20 text-amber-100">{{ event.quote }}</mark>{{ event.suffix }}</blockquote>
        </article>
      </section>
    </div>
  </section>
</template>
