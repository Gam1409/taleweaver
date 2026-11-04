<script setup lang="ts">
export interface WardrobeRecoveryPreview {
  token: string
  notes: string
  messages_scanned: number
  limited: boolean
  errors: string[]
  accepted: {
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
defineProps<{ npcId: string; preview?: WardrobeRecoveryPreview | null; busy: boolean }>()
const emit = defineEmits<{ command: [value: string] }>()
</script>
<template>
  <section class="space-y-2 rounded border border-cyan-900 p-2">
    <button
      type="button"
      :disabled="busy"
      class="rounded bg-cyan-900 px-3 py-2 disabled:opacity-40"
      @click="emit('command', `/debug wardrobe_preview ${npcId}`)"
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
      <p v-if="preview.notes" class="text-amber-200">{{ preview.notes }}</p>
      <p v-if="!preview.accepted.length && !preview.errors.length">No confirmed missing clothing was proposed.</p>
      <article
        v-for="(entry, index) in preview.accepted"
        :key="index"
        class="space-y-1 rounded bg-slate-800 p-2"
      >
        <strong
          >{{ entry.item.name }} — {{ entry.disposition === 'worn' ? 'Worn' : 'Inventory' }}</strong
        >
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
      <p v-for="(error, index) in preview.errors" :key="index" class="text-rose-300">{{ error }}</p>
      <button
        type="button"
        :disabled="busy || !preview.accepted.length || !!preview.errors.length"
        class="rounded bg-emerald-900 px-3 py-2 disabled:opacity-40"
        @click="emit('command', `/debug wardrobe_apply ${preview.token}`)"
      >
        Apply reviewed clothing
      </button>
    </div>
  </section>
</template>
