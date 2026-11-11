<script setup lang="ts">
import DebugWardrobeCorrection from './DebugWardrobeCorrection.vue'
import DebugBodyPlacementCorrection from './DebugBodyPlacementCorrection.vue'
import { ref, watch } from 'vue'
export interface WardrobeRejection {
  index: number
  label: string
  source_message_id: string
  basis: string
  disposition: string
  evidence: string
  placement_evidence: string
  restore_coverage?: boolean
  coverage: string[]
  uncovered_regions: string[]
  reasons: string[]
  attachment_slot?: 'vaginal' | 'anal'
}
const props = defineProps<{
  entries: WardrobeRejection[]
  sources?: Record<string, string> | null
  token?: string
  busy?: boolean
  sourceRoles?: Record<string, string>
}>()
const emit = defineEmits<{ command: [value: string] }>()
const selectedQuote = ref({ index: -1, text: '' })
watch(
  () => props.token,
  () => {
    selectedQuote.value = { index: -1, text: '' }
  }
)
function captureSelection(index: number, event: Event) {
  const element = event.currentTarget as HTMLElement
  const selection = window.getSelection()
  const range = selection?.rangeCount === 1 ? selection.getRangeAt(0) : null
  selectedQuote.value = {
    index,
    text: range && element.contains(range.commonAncestorContainer) ? range.toString() : ''
  }
}
</script>
<template>
  <section class="space-y-3">
    <h4 class="font-bold text-rose-200">Rejected entries — {{ entries.length }}</h4>
    <article
      v-for="entry in entries"
      :key="entry.index"
      class="space-y-2 rounded border border-rose-900 p-3"
    >
      <strong>{{ entry.label }}</strong>
      <p v-for="(reason, index) in entry.reasons" :key="index" class="text-rose-300">
        {{ reason }}
      </p>
      <p class="text-xs text-slate-400">
        Basis: {{ entry.basis }} · Disposition: {{ entry.disposition }}
      </p>
      <p class="break-all text-xs text-slate-400">Cited message: {{ entry.source_message_id }}</p>
      <p v-if="sourceRoles?.[entry.source_message_id] === 'user'" class="text-xs text-amber-200">
        Player message — requires your explicit confirmation in Debug.
      </p>
      <p v-if="entry.attachment_slot" class="text-xs">
        Body placement: {{ entry.attachment_slot }}
      </p>
      <p class="font-bold">Proposed item quote</p>
      <blockquote class="whitespace-pre-wrap break-words border-l-2 border-rose-800 pl-2">
        {{ entry.evidence }}
      </blockquote>
      <div v-if="entry.uncovered_regions.length || entry.placement_evidence" class="space-y-1">
        <p class="text-xs">
          Garment coverage: {{ entry.coverage.join(', ') || 'unspecified' }} · Exposed:
          {{ entry.uncovered_regions.join(', ') || 'none' }}
        </p>
        <p class="font-bold">Proposed placement quote</p>
        <blockquote class="whitespace-pre-wrap break-words border-l-2 border-rose-800 pl-2">
          {{ entry.placement_evidence || '(missing)' }}
        </blockquote>
      </div>
      <details v-if="sources?.[entry.source_message_id]" class="rounded bg-slate-900 p-2">
        <summary class="cursor-pointer text-cyan-200">
          Original
          {{ sourceRoles?.[entry.source_message_id] === 'user' ? 'player' : 'assistant' }} message —
          compare the exact wording
        </summary>
        <pre
          @mouseup="captureSelection(entry.index, $event)"
          @keyup="captureSelection(entry.index, $event)"
          class="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words font-sans text-xs select-text"
          >{{ sources[entry.source_message_id] }}</pre>
      </details>
      <p v-else class="text-amber-200">The cited message was not found in the reviewed history.</p>
      <DebugWardrobeCorrection
        v-if="
          token &&
          sources?.[entry.source_message_id] &&
          entry.coverage.length &&
          !entry.attachment_slot
        "
        :key="`${token}:${entry.index}`"
        :entry="entry"
        :source="sources[entry.source_message_id]!"
        :token="token"
        :busy="!!busy"
        :selected-quote="selectedQuote.index === entry.index ? selectedQuote.text : ''"
        @command="emit('command', $event)"
      />
      <DebugBodyPlacementCorrection
        v-if="token && sources?.[entry.source_message_id] && entry.attachment_slot"
        :key="`${token}:${entry.index}:placement`"
        :entry="entry"
        :source="sources[entry.source_message_id]!"
        :token="token"
        :busy="!!busy"
        :selected-quote="selectedQuote.index === entry.index ? selectedQuote.text : ''"
        @command="emit('command', $event)"
      />
    </article>
  </section>
</template>
