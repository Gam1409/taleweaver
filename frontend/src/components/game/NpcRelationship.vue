<script setup lang="ts">
import { computed } from 'vue'
import type { NpcAttitude, NpcRelationship } from '@/composables/useNpcJournal'

const props = defineProps<{ relationship?: NpcRelationship }>()
const styles: Record<NpcAttitude, { label: string; color: string }> = {
  unknown: { label: 'Unknown', color: 'border-slate-600 text-slate-300 bg-slate-800' },
  love: { label: 'Love', color: 'border-pink-400/40 text-pink-200 bg-pink-500/10' },
  trust: { label: 'Trust', color: 'border-emerald-400/40 text-emerald-200 bg-emerald-500/10' },
  friendly: { label: 'Friendly', color: 'border-sky-400/40 text-sky-200 bg-sky-500/10' },
  neutral: { label: 'Neutral', color: 'border-slate-400/40 text-slate-200 bg-slate-500/10' },
  suspicion: { label: 'Suspicion', color: 'border-amber-400/40 text-amber-200 bg-amber-500/10' },
  hostility: { label: 'Hostility', color: 'border-red-400/40 text-red-200 bg-red-500/10' },
  fear: { label: 'Fear', color: 'border-violet-400/40 text-violet-200 bg-violet-500/10' },
  mixed: { label: 'Mixed', color: 'border-orange-400/40 text-orange-200 bg-orange-500/10' },
}
const badge = computed(() => styles[props.relationship?.status || 'unknown'] || styles.unknown)
</script>

<template>
  <section class="rounded-xl border border-slate-700 p-3 space-y-2" aria-label="Attitude toward your character">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <span class="text-sm font-semibold">Attitude toward your character</span>
      <span class="rounded-full border px-2.5 py-0.5 text-xs font-semibold" :class="badge.color">{{ badge.label }}</span>
    </div>
    <p class="text-xs text-slate-400">Last known attitude, based on what your character has learned.</p>
    <p v-if="relationship?.source === 'claimed'" class="text-xs text-amber-200">Claim — not verified</p>
    <p v-else-if="relationship?.source === 'observed'" class="text-xs text-slate-300">Based on observed behavior</p>
    <details v-if="relationship?.text || relationship?.evidence" class="text-sm">
      <summary class="cursor-pointer text-slate-300">Why this assessment?</summary>
      <p v-if="relationship.text" class="mt-2 whitespace-pre-wrap">{{ relationship.text }}</p>
      <blockquote v-if="relationship.evidence" class="mt-2 border-l-2 border-slate-600 pl-2 text-xs text-slate-400 whitespace-pre-wrap">{{ relationship.evidence }}</blockquote>
    </details>
    <p v-else class="text-xs text-slate-400">There is not enough information yet. Unknown does not mean neutral.</p>
  </section>
</template>
