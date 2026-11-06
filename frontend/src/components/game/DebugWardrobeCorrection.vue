<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { WardrobeRejection } from './DebugWardrobeRejections.vue'

const props = defineProps<{
  entry: WardrobeRejection
  source: string
  token: string
  busy: boolean
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
const valid = computed(() =>
  !props.busy && ['worn', 'carried'].includes(status.value) && evidence.value.length >= 4 && evidence.value.length <= 800 &&
  props.source.includes(evidence.value) &&
  uncovered.value.every(region => props.entry.coverage.includes(region)) &&
  (!uncovered.value.length
    ? !placement.value
    : placement.value.length >= 4 && placement.value.length <= 800 && props.source.includes(placement.value))
)
function submit() {
  if (!valid.value) return
  const payload = JSON.stringify({
    status: status.value,
    evidence: evidence.value,
    uncovered_regions: uncovered.value,
    placement_evidence: placement.value,
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
      <fieldset :disabled="busy" class="space-y-3">
        <label class="block text-sm">
          Clothing state
          <select v-model="status" aria-label="Clothing state" required class="mt-1 block w-full rounded bg-slate-800 p-2">
            <option value="" disabled>Choose the state confirmed by the story</option>
            <option value="worn">Worn — includes clothing pulled aside or lowered</option>
            <option value="carried">Fully removed — still owned by this NPC</option>
          </select>
        </label>
        <label class="block text-sm">
          Exact item quote
          <textarea v-model="evidence" rows="3" maxlength="800" required class="mt-1 block w-full rounded bg-slate-800 p-2" />
        </label>
        <div v-if="status === 'worn'" class="space-y-2 text-sm">
          <p>Exposed regions (optional)</p>
          <p class="text-xs text-slate-400">Select only regions the displaced garment no longer covers.</p>
          <div class="flex flex-wrap gap-3">
            <label v-for="region in entry.coverage" :key="region" class="flex items-center gap-1">
              <input v-model="uncovered" type="checkbox" :value="region" /> {{ region }}
            </label>
          </div>
          <label class="block">
            Exact placement quote from the same message
            <textarea v-model="placement" rows="3" maxlength="800" class="mt-1 block w-full rounded bg-slate-800 p-2" />
          </label>
        </div>
      </fieldset>
      <p v-if="!valid && !busy" class="text-xs text-amber-200">
        Choose a state and copy a continuous exact item quote. Exposed regions also need an exact
        placement quote from the same message. Omit placement when no regions are exposed.
      </p>
      <button type="submit" :disabled="!valid" class="rounded-full bg-cyan-900 px-3 py-2 disabled:opacity-40">
        Validate correction
      </button>
    </form>
  </details>
</template>
