<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { HeartPulse, Plus, Save } from 'lucide-vue-next'

type Kind = 'injury' | 'contamination' | 'fluid' | 'pain' | 'other'
type Operation = 'record' | 'change' | 'treat' | 'reduce' | 'clean' | 'heal' | 'remove'
interface Source { kind: string; message_id?: string; quote: string }
interface Condition {
  id: string; target_id: string; kind: Kind; part: string; detail: string
  status: string; visibility: 'public' | 'private'; origin: Source; latest: Source
}
interface Ledger {
  revision: number; conditions: Record<string, Condition>
  subjects: { id: string; name: string }[]; error?: string
  archived_resolved: number; archived_events: number
  last_check: { status?: string; reason?: string; rejected?: string[] }
}
const props = defineProps<{ data?: Ledger; busy: boolean }>()
const emit = defineEmits<{ command: [command: string] }>()
const selected = ref('')
const filter = ref('')
const showResolved = ref(false)
const target = ref('__player__')
const kind = ref<Kind>('injury')
const part = ref('')
const detail = ref('')
const visibility = ref<'public' | 'private'>('private')
const operation = ref<Operation>('record')
const current = computed(() => props.data?.conditions?.[selected.value])
const available = computed(() => props.data && !props.data.error && Number.isInteger(props.data.revision))
const kinds: Kind[] = ['injury', 'contamination', 'fluid', 'pain', 'other']
const labels: Record<Operation, string> = {
  record: 'Record condition', change: 'Correct description', treat: 'Treat — keep condition',
  reduce: 'Reduce — keep remainder', clean: 'Fully clean', heal: 'Fully heal', remove: 'Fully remove',
}
const operations = computed<Operation[]>(() => {
  if (!current.value) return ['record']
  if (['injury', 'pain'].includes(current.value.kind)) return ['change', 'treat', 'reduce', 'heal']
  return ['change', 'reduce', ...(current.value.kind === 'other' ? [] : ['clean'] as Operation[]), 'remove']
})
function subjectName(id: string) { return props.data?.subjects?.find(s => s.id === id)?.name || id }
const rows = computed(() => Object.values(props.data?.conditions || {}).filter(row =>
  (showResolved.value || row.status !== 'resolved') &&
  [subjectName(row.target_id), row.part, row.detail].join(' ').toLowerCase().includes(filter.value.toLowerCase()),
))
const canSave = computed(() => available.value && !props.busy &&
  current.value?.status !== 'resolved' && detail.value.trim().length > 0 &&
  (current.value || (part.value.trim() && props.data?.subjects?.some(s => s.id === target.value))),
)
function populate() {
  const row = current.value
  target.value = row?.target_id || '__player__'
  kind.value = row?.kind || 'injury'
  part.value = row?.part || ''
  detail.value = row?.detail || ''
  visibility.value = row?.visibility || 'private'
  operation.value = row ? 'change' : 'record'
}
watch([selected, () => props.data?.revision], populate)
function save() {
  if (!canSave.value || !props.data) return
  const fields = current.value
    ? { condition_id: current.value.id }
    : { target_id: target.value, kind: kind.value, part: part.value.trim() }
  emit('command', '/debug condition ' + JSON.stringify({
    operation: operation.value, ...fields, detail: detail.value.trim(),
    visibility: visibility.value, expected_revision: props.data.revision,
  }))
}
</script>

<template>
  <section class="flex-1 min-h-0 overflow-y-auto p-4 sm:p-6 space-y-4 text-slate-200">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h3 class="flex items-center gap-2 font-bold text-white"><HeartPulse class="w-5 h-5 text-cyan-400" /> Persistent physical state</h3>
        <p class="text-xs text-slate-400 mt-1">Injuries, dirt and fluid traces persist until explicitly changed. Treatment keeps the condition.</p>
      </div>
      <button type="button" class="state-button" :disabled="!available || busy" @click="selected = ''; populate()"><Plus class="w-4 h-4" /> Record condition</button>
    </div>
    <p v-if="!data" role="status">State data is unavailable. Refresh the debug inspector.</p>
    <p v-else-if="data.error" role="alert" class="text-amber-300">{{ data.error }}</p>
    <template v-else>
      <div v-if="data.last_check?.status === 'failed' || data.last_check?.rejected?.length" role="status" class="rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200">
        <p class="font-bold">Last check needs review. Existing conditions were kept.</p>
        <p v-if="data.last_check.reason">{{ data.last_check.reason }}</p>
        <ul v-if="data.last_check.rejected?.length" class="list-disc pl-5 mt-2"><li v-for="(reason, i) in data.last_check.rejected" :key="i">{{ reason }}</li></ul>
      </div>
      <div class="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(16rem,2fr)]">
        <div class="min-w-0 space-y-3">
          <div class="flex flex-wrap items-center gap-3">
            <input v-model="filter" aria-label="Search physical conditions" placeholder="Search subject, body part or condition…" class="state-field flex-1 min-w-48" />
            <label class="text-xs flex gap-2 items-center"><input v-model="showResolved" type="checkbox" /> Show resolved</label>
          </div>
          <p v-if="!rows.length" class="text-sm text-slate-400 py-4">No recorded conditions match this view. Older narration is not automatically reconstructed.</p>
          <article v-for="row in rows" :key="row.id" class="rounded-xl border bg-slate-950/70 p-3 space-y-2" :class="selected === row.id ? 'border-cyan-500' : 'border-slate-700'">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0"><h4 class="font-bold break-words">{{ subjectName(row.target_id) }} · {{ row.part }}</h4><p class="text-xs text-cyan-300">{{ row.kind }} · {{ row.status }} · {{ row.visibility }}</p></div>
              <button type="button" class="state-button" :disabled="busy" @click="selected = row.id">{{ row.status === 'resolved' ? 'View' : 'Edit' }}</button>
            </div>
            <p class="text-sm whitespace-pre-wrap break-words">{{ row.detail }}</p>
            <details class="text-xs text-slate-400">
              <summary class="cursor-pointer">Source · {{ row.latest.kind }}</summary>
              <blockquote class="border-l border-slate-600 pl-2 my-2 whitespace-pre-wrap break-words">{{ row.latest.quote }}</blockquote>
              <p v-if="row.latest.message_id" class="break-all">Message: {{ row.latest.message_id }}</p>
              <p v-if="row.latest.kind === 'unavailable'">The original message is unavailable in this copy; the saved fact was retained.</p>
              <p v-if="row.origin.message_id && row.origin.message_id !== row.latest.message_id" class="break-all mt-1">First recorded: {{ row.origin.message_id }}</p>
            </details>
          </article>
        </div>
        <form class="rounded-xl border border-slate-700 bg-slate-900/80 p-4 space-y-3 self-start" @submit.prevent="save">
          <h4 class="font-bold">{{ current ? 'Manual correction' : 'Record a missing condition' }}</h4>
          <p class="text-xs text-slate-400">Changes affect this session only and are marked as manual. No model call or time advance.</p>
          <label class="state-label">Subject<select v-model="target" aria-label="Subject" class="state-field" :disabled="!!current || busy"><option v-for="subject in data.subjects" :key="subject.id" :value="subject.id">{{ subject.name }} [{{ subject.id }}]</option></select></label>
          <label class="state-label">Kind<select v-model="kind" aria-label="Kind" class="state-field" :disabled="!!current || busy"><option v-for="value in kinds" :key="value" :value="value">{{ value }}</option></select></label>
          <label class="state-label">Body part or item area<input v-model="part" class="state-field" maxlength="80" required :disabled="!!current || busy" /></label>
          <label class="state-label">Operation<select v-model="operation" aria-label="Operation" class="state-field" :disabled="busy || current?.status === 'resolved'"><option v-for="value in operations" :key="value" :value="value">{{ labels[value] }}</option></select></label>
          <label class="state-label">Current detail<textarea v-model="detail" class="state-field min-h-24" maxlength="320" required :disabled="busy || current?.status === 'resolved'" /></label>
          <label class="state-label">Visibility<select v-model="visibility" aria-label="Visibility" class="state-field" :disabled="busy || current?.status === 'resolved'"><option value="private">Private — owner only</option><option value="public">Public — subject to clothing and perspective</option></select></label>
          <p v-if="current?.status === 'resolved'" class="text-xs text-slate-400">Resolved records are read-only. Record a new occurrence if needed.</p>
          <button type="submit" class="state-button w-full justify-center" :disabled="!canSave"><Save class="w-4 h-4" /> Save condition</button>
        </form>
      </div>
      <p class="text-xs text-slate-500">Revision {{ data.revision }}. Recent view retains 64 resolved conditions and 128 changes. Earlier resolved records: {{ data.archived_resolved }}; earlier changes: {{ data.archived_events }}. Active conditions are never evicted. Original narration remains in chat history.</p>
    </template>
  </section>
</template>

<style scoped>
.state-button { @apply flex items-center gap-1.5 rounded-xl border border-cyan-500/30 bg-cyan-500/10 px-3 py-2 text-xs font-bold text-cyan-200 transition-colors hover:bg-cyan-500/20 disabled:opacity-40 disabled:cursor-not-allowed; }
.state-label { @apply flex flex-col gap-1 text-xs text-slate-300; }
.state-field { @apply w-full rounded-xl border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-400 disabled:opacity-60; }
</style>
