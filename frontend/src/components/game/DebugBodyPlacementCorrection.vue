<script setup lang="ts">
import { computed, ref } from 'vue'
import type { WardrobeRejection } from './DebugWardrobeRejections.vue'
import { quoteError } from '@/utils/wardrobeQuotes'
import { BODY_ITEM_SLOTS } from '@/utils/equipmentSlots'

const props = defineProps<{
  entry: WardrobeRejection
  source: string
  token: string
  busy: boolean
  selectedQuote?: string
  sourceMessageId?: string
}>()
const emit = defineEmits<{ command: [value: string] }>()
const evidence = ref(props.entry.evidence)
const slot = ref(props.entry.attachment_slot ?? '')
const error = computed(() => {
  const invalid = quoteError(props.source, evidence.value)
  if (invalid) return invalid
  const quote = evidence.value.trim()
  return props.source.indexOf(quote) === props.source.lastIndexOf(quote)
    ? ''
    : 'Select a longer passage that occurs only once in this message.'
})
const valid = computed(
  () => !props.busy && !error.value && BODY_ITEM_SLOTS.some(region => region.region === slot.value)
)
const canUseSelection = computed(
  () => !props.busy && !quoteError(props.source, props.selectedQuote ?? '')
)
function submit() {
  if (!valid.value) return
  const payload = JSON.stringify({
    status: 'worn',
    evidence: evidence.value.trim(),
    ...(props.sourceMessageId ? { source_message_id: props.sourceMessageId } : {}),
    attachment_slot: slot.value
  })
  emit('command', `/debug wardrobe_correct ${props.token} ${props.entry.index} ${payload}`)
}
</script>

<template>
  <details class="rounded border border-cyan-900 bg-slate-950 p-2">
    <summary class="cursor-pointer text-cyan-200">Correct this proposal</summary>
    <form class="mt-3 space-y-3" @submit.prevent="submit">
      <p class="text-xs text-slate-400">
        Copy an exact passage identifying the item, character and its current placement. Correction
        updates the preview; review and select the item before applying.
      </p>
      <button
        type="button"
        :disabled="!canUseSelection"
        class="text-cyan-200 underline disabled:opacity-40"
        @click="evidence = selectedQuote!.trim()"
      >
        Use selected source passage
      </button>
      <label class="block text-sm">
        Confirmed placement
        <select v-model="slot" :disabled="busy" class="mt-1 w-full rounded bg-slate-800 p-2">
          <option v-for="region in BODY_ITEM_SLOTS" :key="region.region" :value="region.region">{{ region.label }}</option>
        </select>
      </label>
      <label class="block text-sm">
        Exact item and placement quote
        <textarea
          v-model="evidence"
          :disabled="busy"
          :aria-invalid="!!error"
          rows="3"
          maxlength="800"
          required
          class="mt-1 w-full rounded bg-slate-800 p-2"
        />
      </label>
      <p v-if="error" role="status" class="text-xs text-amber-200">{{ error }}</p>
      <button
        type="submit"
        :disabled="!valid"
        class="rounded-full bg-cyan-900 px-3 py-2 disabled:opacity-40"
      >
        Validate correction
      </button>
    </form>
  </details>
</template>
