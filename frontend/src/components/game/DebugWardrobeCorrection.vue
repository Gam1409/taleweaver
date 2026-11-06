<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { WardrobeRejection } from './DebugWardrobeRejections.vue'
import { quoteError, quoteSuggestion } from '@/utils/wardrobeQuotes'

const props = defineProps<{
  entry: WardrobeRejection
  source: string
  token: string
  busy: boolean
  selectedQuote?: string
}>()
const emit = defineEmits<{ command: [value: string] }>()
const status = ref('')
const evidence = ref(props.entry.evidence)
const placement = ref(props.entry.placement_evidence)
const uncovered = ref([...props.entry.uncovered_regions])
watch(status, value => {
  if (value === 'carried') {
    uncovered.value = []
    placement.value = ''
  }
})
const statusError = computed(() => ['worn', 'carried'].includes(status.value) ? '' : 'Choose the clothing state confirmed by the story.')
const itemError = computed(() => quoteError(props.source, evidence.value))
const placementError = computed(() => uncovered.value.length
  ? quoteError(props.source, placement.value)
  : placement.value ? 'Clear the placement quote or select the regions this garment no longer covers.' : '')
const regionChoices = computed(() => [...new Set([...props.entry.coverage, ...uncovered.value])])
const regionError = computed(() => {
  const invalid = uncovered.value.filter(region => !props.entry.coverage.includes(region))
  if (invalid.length) return `Outside garment coverage: ${invalid.join(', ')}. Uncheck these regions or reset the selection.`
  if (new Set(uncovered.value).size !== uncovered.value.length) return 'Duplicate exposed regions. Reset the selection and select each region once.'
  return ''
})
const valid = computed(() => !props.busy && !statusError.value && !itemError.value && !placementError.value && !regionError.value)
const itemSuggestion = computed(() => quoteSuggestion(props.source, evidence.value))
const placementSuggestion = computed(() => quoteSuggestion(props.source, placement.value))
const canUseSelection = computed(() => !props.busy && !quoteError(props.source, props.selectedQuote ?? ''))
const buttonHint = computed(() => props.busy ? 'Wait for the current request to finish.'
  : statusError.value || itemError.value || regionError.value || placementError.value || 'Validate this corrected proposal.')
function useSelection(target: 'item' | 'placement') {
  if (!canUseSelection.value) return
  if (target === 'item') evidence.value = props.selectedQuote!.trim()
  else placement.value = props.selectedQuote!.trim()
}
function submit() {
  if (!valid.value) return
  const payload = JSON.stringify({
    status: status.value,
    evidence: evidence.value.trim(),
    uncovered_regions: uncovered.value,
    placement_evidence: placement.value.trim(),
  })
  emit('command', `/debug wardrobe_correct ${props.token} ${props.entry.index} ${payload}`)
}
</script>

<template>
  <details class="rounded border border-cyan-900 bg-slate-950 p-2">
    <summary class="cursor-pointer text-cyan-200">Correct this proposal</summary>
    <form class="mt-3 space-y-3" @submit.prevent="submit">
      <p class="text-xs text-slate-400">
        Copy exact text from the original assistant message above. Correcting only updates the
        preview; review and select the garment before applying. Ownership and clothing settings
        are checked again.
      </p>
      <p class="text-xs text-cyan-200">
        Select a short passage in Original assistant message above, then use the buttons below to
        copy it without retyping. The same exact quote may be used in both fields.
      </p>
      <div class="flex flex-wrap gap-2">
        <button type="button" :disabled="!canUseSelection" class="rounded-full border border-cyan-800 px-3 py-1 text-xs disabled:opacity-40" @click="useSelection('item')">Use selection as item quote</button>
        <button v-if="status === 'worn' && uncovered.length" type="button" :disabled="!canUseSelection" class="rounded-full border border-cyan-800 px-3 py-1 text-xs disabled:opacity-40" @click="useSelection('placement')">Use selection as placement quote</button>
      </div>
      <fieldset :disabled="busy" class="space-y-3">
        <label class="block text-sm">
          Clothing state
          <select v-model="status" aria-label="Clothing state" required class="mt-1 block w-full rounded bg-slate-800 p-2">
            <option value="" disabled>Choose the state confirmed by the story</option>
            <option value="worn">Worn — includes clothing pulled aside or lowered</option>
            <option value="carried">Fully removed — still owned by this NPC</option>
          </select>
        </label>
        <p v-if="statusError" role="status" class="text-xs text-amber-200">{{ statusError }}</p>
        <label class="block text-sm">
          Exact item quote
          <textarea v-model="evidence" :aria-invalid="!!itemError" rows="3" maxlength="1600" required class="mt-1 block w-full rounded bg-slate-800 p-2" />
        </label>
        <p v-if="itemError" role="status" class="text-xs text-amber-200">{{ itemError }}</p>
        <div v-if="itemSuggestion" class="space-y-1 text-xs">
          <blockquote class="whitespace-pre-wrap border-l-2 border-cyan-800 pl-2">{{ itemSuggestion }}</blockquote>
          <button type="button" class="text-cyan-200 underline" @click="evidence = itemSuggestion">Use exact source wording for item quote</button>
        </div>
        <div v-if="status === 'worn'" class="space-y-2 text-sm">
          <p>Exposed regions (optional)</p>
          <p class="text-xs text-slate-400">Select only regions the displaced garment no longer covers.</p>
          <div class="flex flex-wrap gap-3">
            <label v-for="region in regionChoices" :key="region" class="flex items-center gap-1">
              <input v-model="uncovered" type="checkbox" :value="region" /> {{ region }}{{ entry.coverage.includes(region) ? '' : ' (outside coverage)' }}
            </label>
          </div>
          <p v-if="regionError" role="status" class="text-xs text-amber-200">{{ regionError }}</p>
          <button v-if="uncovered.length" type="button" class="text-xs text-cyan-200 underline" @click="uncovered = []; placement = ''">Reset exposed regions</button>
          <label class="block">
            Exact placement quote from the same message
            <textarea v-model="placement" :aria-invalid="!!placementError" rows="3" maxlength="1600" class="mt-1 block w-full rounded bg-slate-800 p-2" />
          </label>
          <p v-if="placementError" role="status" class="text-xs text-amber-200">{{ placementError }}</p>
          <button v-if="uncovered.length && !itemError" type="button" class="text-xs text-cyan-200 underline" @click="placement = evidence">Use item quote for placement</button>
          <div v-if="placementSuggestion" class="space-y-1 text-xs">
            <blockquote class="whitespace-pre-wrap border-l-2 border-cyan-800 pl-2">{{ placementSuggestion }}</blockquote>
            <button type="button" class="text-cyan-200 underline" @click="placement = placementSuggestion">Use exact source wording for placement quote</button>
          </div>
        </div>
      </fieldset>
      <p v-if="busy" role="status" class="text-xs text-amber-200">Wait for the current request to finish.</p>
      <button type="submit" :disabled="!valid" :title="buttonHint" class="rounded-full bg-cyan-900 px-3 py-2 disabled:opacity-40">
        Validate correction
      </button>
    </form>
  </details>
</template>
