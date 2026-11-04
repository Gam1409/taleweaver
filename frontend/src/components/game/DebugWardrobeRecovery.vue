<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import DebugWardrobeMentions, { type WardrobeMention } from './DebugWardrobeMentions.vue'
import DebugWardrobeRejections, { type WardrobeRejection } from './DebugWardrobeRejections.vue'
export interface WardrobeRecoveryPreview {
  token: string
  notes: string
  messages_scanned: number
  limited: boolean
  errors: string[]
  mention_checks?: WardrobeMention[] | null
  rejected_entries?: WardrobeRejection[] | null
  rejected_sources?: Record<string, string> | null
  skipped?: string[] | null
  model_role?: string | null
  accepted: {
    proposal_index?: number
    item: {
      name: string
      description: string
      clothing?: { layer: number; coverage: string[]; underwear: boolean }
    }
    disposition: string
    evidence: string
    source_message_id: string
    uncovered_regions?: string[]
    placement_evidence?: string
  }[]
}
const props = defineProps<{
  npcId: string
  preview?: WardrobeRecoveryPreview | null
  busy: boolean
}>()
const modelRole = ref('complex')
const selected = ref<number[]>([])
const selectable = computed(() =>
  (props.preview?.accepted || []).flatMap(entry =>
    typeof entry.proposal_index === 'number' ? [entry.proposal_index] : []
  )
)
watch(
  () => props.preview?.token,
  () => {
    selected.value = []
  }
)
const emit = defineEmits<{ command: [value: string] }>()
</script>
<template>
  <section class="space-y-2 rounded border border-cyan-900 p-2">
    <label class="block">
      Recovery model
      <select v-model="modelRole" :disabled="busy" class="ml-2 rounded bg-slate-800 p-2">
        <option value="complex">Main model (Complex)</option>
        <option value="small">Small model</option>
      </select>
    </label>
    <button
      type="button"
      :disabled="busy"
      class="rounded bg-cyan-900 px-3 py-2 disabled:opacity-40"
      @click="emit('command', `/debug wardrobe_preview ${JSON.stringify(npcId)} ${modelRole}`)"
    >
      Restore clothing from history…
    </button>
    <p class="text-slate-400">
      Preview missing clothing from up to 80 recent story messages. Nothing changes until you apply.
      Check later removals and transfers before accepting.
    </p>
    <div v-if="preview" class="space-y-2">
      <p>
        Messages reviewed: {{ preview.messages_scanned
        }}{{ preview.limited ? ' (older history excluded)' : '' }}.
      </p>
      <p v-if="preview.model_role" class="text-slate-400">
        Preview model role: {{ preview.model_role }}
      </p>
      <p v-if="preview.notes" class="text-amber-200">{{ preview.notes }}</p>
      <p v-if="!preview.accepted.length && !preview.errors.length">
        No confirmed missing clothing was proposed.
      </p>
      <div v-if="preview.accepted.length" class="flex flex-wrap items-center gap-3">
        <span>Choose garments to restore: {{ selected.length }} selected.</span>
        <button
          type="button"
          :disabled="busy"
          class="text-cyan-300 underline"
          @click="selected = [...selectable]"
        >
          Select all validated
        </button>
        <button
          type="button"
          :disabled="busy"
          class="text-slate-400 underline"
          @click="selected = []"
        >
          Clear selection
        </button>
      </div>
      <p
        v-if="preview.accepted.length && selectable.length !== preview.accepted.length"
        class="text-amber-200"
      >
        Generate a new preview to select garments from this older result.
      </p>
      <article
        v-for="(entry, index) in preview.accepted"
        :key="index"
        class="space-y-1 rounded bg-slate-800 p-2"
      >
        <label class="flex items-start gap-2 font-bold">
          <input
            v-model="selected"
            type="checkbox"
            :value="entry.proposal_index"
            :disabled="busy || typeof entry.proposal_index !== 'number'"
            class="mt-1"
          />
          {{ entry.item.name }} — {{ entry.disposition === 'worn' ? 'Worn' : 'Inventory' }}
        </label>
        <p>{{ entry.item.description }}</p>
        <p v-if="entry.item.clothing">
          Layer {{ entry.item.clothing.layer }} · {{ entry.item.clothing.coverage.join(', ')
          }}{{ entry.item.clothing.underwear ? ' · Underwear' : '' }}
        </p>
        <p v-if="entry.uncovered_regions?.length">
          Partially displaced — exposed: {{ entry.uncovered_regions.join(', ') }}
        </p>
        <p v-if="entry.placement_evidence" class="italic">{{ entry.placement_evidence }}</p>
        <blockquote class="border-l-2 border-slate-500 pl-2 italic">
          {{ entry.evidence }}
        </blockquote>
        <p class="break-all text-[10px] text-slate-400">Source: {{ entry.source_message_id }}</p>
      </article>
      <div v-if="preview.skipped?.length" class="space-y-1 text-amber-200">
        <p>
          Skipped by clothing settings or age requirements. These entries will not be applied; other
          validated entries can be applied.
        </p>
        <p v-for="(reason, index) in preview.skipped" :key="index">{{ reason }}</p>
      </div>
      <p v-if="preview.errors.length" class="text-rose-300">
        Rejected candidates cannot be selected. Other validated garments can be restored
        independently.
      </p>
      <DebugWardrobeRejections
        v-if="preview.rejected_entries?.length"
        :entries="preview.rejected_entries"
        :sources="preview.rejected_sources"
      />
      <p
        v-for="(error, index) in preview.rejected_entries?.length ? [] : preview.errors"
        :key="index"
        class="text-rose-300"
      >
        {{ error }}
      </p>
      <DebugWardrobeMentions
        v-if="preview.mention_checks?.length"
        :checks="preview.mention_checks"
      />
      <button
        type="button"
        :disabled="busy || !selected.length"
        class="rounded bg-emerald-900 px-3 py-2 disabled:opacity-40"
        @click="emit('command', `/debug wardrobe_apply ${preview.token} ${selected.join(',')}`)"
      >
        Restore selected clothing
      </button>
    </div>
  </section>
</template>
