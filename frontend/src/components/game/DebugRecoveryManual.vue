<script setup lang="ts">
import { computed, ref } from 'vue'
import ClothingItemFields from '@/components/editor/ClothingItemFields.vue'
import type { ClothingDraft } from '@/services/clothingAuthoring'
import { EQUIPMENT_SLOTS } from '@/utils/equipmentSlots'
import { quoteError } from '@/utils/wardrobeQuotes'
import DebugRecoverySource from './DebugRecoverySource.vue'

const props = defineProps<{
  token: string
  sources: Record<string, string>
  sourceRoles?: Record<string, string>
  busy: boolean
}>()
const emit = defineEmits<{ command: [value: string] }>()
const sourceId = ref('')
const selectedQuote = ref('')
const evidence = ref('')
const name = ref('')
const description = ref('')
const kind = ref<'ordinary' | 'clothing'>('ordinary')
const status = ref('worn')
const attachment = ref('')
const clothing = ref<ClothingDraft>({})
const slots = ref<string[]>([])
const source = computed(() => props.sources[sourceId.value] || '')
const quoteIssue = computed(() => {
  if (!source.value) return 'Choose a message from the loaded history sources.'
  const issue = quoteError(source.value, evidence.value)
  if (issue || kind.value !== 'ordinary') return issue
  const quote = evidence.value.trim()
  return source.value.indexOf(quote) === source.value.lastIndexOf(quote)
    ? ''
    : 'Select a longer passage that occurs only once in this message.'
})
const canCopy = computed(() => !props.busy && !quoteError(source.value, selectedQuote.value))
const size = (value: string) => [...value.trim()].length
const valid = computed(() => {
  if (
    props.busy ||
    !source.value ||
    quoteIssue.value ||
    !size(name.value) ||
    size(name.value) > 120 ||
    size(description.value) < 4 ||
    size(description.value) > 1000
  )
    return false
  if (kind.value === 'ordinary') return ['vaginal', 'anal'].includes(attachment.value)
  const layer = clothing.value.layer
  return (
    ['worn', 'carried'].includes(status.value) &&
    Number.isInteger(layer) &&
    layer! >= 0 &&
    layer! <= 4 &&
    !!clothing.value.coverage?.length &&
    slots.value.length > 0 &&
    slots.value.length <= 4
  )
})
function submit() {
  if (!valid.value) return
  const item = {
    kind: kind.value,
    name: name.value.trim(),
    description: description.value.trim(),
    ...(kind.value === 'clothing' ? { clothing: clothing.value, wearable_slots: slots.value } : {})
  }
  const payload = {
    source_message_id: sourceId.value,
    evidence: evidence.value.trim(),
    new_item: item,
    disposition: kind.value === 'ordinary' ? 'worn' : status.value,
    ...(kind.value === 'ordinary' ? { attachment_slot: attachment.value } : {})
  }
  emit('command', `/debug wardrobe_add ${props.token} ${JSON.stringify(payload)}`)
}
</script>

<template>
  <form
    class="min-w-0 space-y-3 rounded border border-cyan-800 bg-slate-950 p-3"
    @submit.prevent="submit"
  >
    <h4 class="font-bold text-cyan-200">Manual recovery from source</h4>
    <p class="text-xs text-slate-400">
      You confirm the meaning and current state after checking later removals or transfers. Use only
      known details; a short intrinsic description is enough. This adds a proposal, not an inventory
      item. No model request.
    </p>
    <DebugRecoverySource
      v-model="sourceId"
      :sources="sources"
      :source-roles="sourceRoles"
      :disabled="busy"
      expanded
      @quote="selectedQuote = $event"
    />
    <fieldset :disabled="busy" class="space-y-3">
      <label class="block text-sm"
        >Item type
        <select v-model="kind" class="mt-1 w-full rounded bg-slate-800 p-2">
          <option value="ordinary">Placed ordinary object</option>
          <option value="clothing">Garment</option>
        </select>
      </label>
      <label class="block text-sm"
        >Item name
        <input
          v-model="name"
          maxlength="240"
          required
          class="mt-1 w-full rounded bg-slate-800 p-2"
        />
      </label>
      <label class="block text-sm"
        >Intrinsic description (known facts only)
        <textarea
          v-model="description"
          rows="2"
          maxlength="2000"
          required
          class="mt-1 w-full rounded bg-slate-800 p-2"
        />
      </label>
      <template v-if="kind === 'clothing'">
        <label class="block text-sm"
          >Current garment state
          <select v-model="status" class="mt-1 w-full rounded bg-slate-800 p-2">
            <option value="worn">Worn</option>
            <option value="carried">Removed — register as an owned inventory item</option>
          </select>
        </label>
        <p v-if="status === 'carried'" class="text-xs text-slate-400">
          For a garment lying in the room, use Place in room after restoring this record.
        </p>
        <fieldset>
          <legend class="text-sm">Equipment slots</legend>
          <div class="mt-1 flex flex-wrap gap-3">
            <label v-for="slot in EQUIPMENT_SLOTS" :key="slot.key" class="text-sm"
              ><input v-model="slots" type="checkbox" :value="slot.key" /> {{ slot.label }}</label
            >
          </div>
        </fieldset>
        <ClothingItemFields
          v-model="clothing"
          :name="name"
          :description="description"
          :slots="slots"
          :disabled="busy"
        />
        <label class="flex gap-2 text-sm"
          ><input v-model="clothing.underwear" type="checkbox" /> Underwear</label
        >
      </template>
      <label v-else class="block text-sm"
        >Confirmed body placement
        <select v-model="attachment" class="mt-1 w-full rounded bg-slate-800 p-2">
          <option value="" disabled>Select the placement established in the source</option>
          <option value="vaginal">Vaginal placement</option>
          <option value="anal">Anal placement</option>
        </select>
      </label>
      <label class="block text-sm"
        >Exact source quote
        <textarea
          v-model="evidence"
          rows="3"
          maxlength="1600"
          required
          :aria-invalid="!!quoteIssue"
          class="mt-1 w-full rounded bg-slate-800 p-2"
        />
      </label>
      <button
        type="button"
        :disabled="!canCopy"
        class="text-xs text-cyan-200 underline disabled:opacity-40"
        @click="evidence = selectedQuote.trim()"
      >
        Use selected source passage
      </button>
      <p v-if="quoteIssue" role="status" class="text-xs text-amber-200">{{ quoteIssue }}</p>
    </fieldset>
    <button
      type="submit"
      :disabled="!valid"
      class="rounded bg-cyan-900 px-3 py-2 disabled:opacity-40"
    >
      Add proposal to preview
    </button>
  </form>
</template>
