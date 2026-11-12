<script setup lang="ts">
import type { NpcJournalEntry } from '@/composables/useNpcJournal'
defineProps<{ entries?: NpcJournalEntry[] }>()
</script>

<template>
  <details
    v-if="entries?.length"
    class="rounded-xl border border-slate-700 p-3 text-sm"
    data-general-overview
  >
    <summary class="cursor-pointer font-semibold focus-visible:outline-amber-300">
      General overview
    </summary>
    <ul class="mt-3 space-y-3 leading-relaxed text-slate-300">
      <li v-for="entry in entries" :key="entry.id" class="whitespace-pre-wrap break-words">
        <span v-if="entry.source === 'claimed'" class="mr-1 text-xs text-amber-200">Claim:</span
        >{{ entry.text }}
      </li>
    </ul>
  </details>
</template>
