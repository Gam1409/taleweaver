<script setup lang="ts">
import { computed } from 'vue'
import type { NpcInsights } from '@/composables/useNpcJournal'

const props = defineProps<{ insights?: NpcInsights | null }>()
const labels = { trust: 'Trust', affinity: 'Affinity', respect: 'Respect', tension: 'Tension' } as const
const estimates = computed(() => {
  const scores = props.insights?.relationship
  if (!scores) return []
  return (Object.keys(labels) as Array<keyof typeof labels>)
    .filter(key => typeof scores[key] === 'number' && Number.isFinite(scores[key]))
    .map(key => ({ key, label: labels[key], value: scores[key] }))
})
const emotion = computed(() => props.insights?.emotion?.replace(/_/g, ' ') || '')
</script>

<template>
  <section class="rounded-xl border border-sky-400/20 bg-sky-400/5 p-3" aria-label="Last evaluated narrative state">
    <h3 class="font-semibold text-sm">Last evaluated state</h3>
    <p class="mt-1 text-xs text-slate-400">Estimates from the last reviewed interaction; they may lag behind the story.</p>
    <template v-if="insights?.available">
      <p v-if="emotion" class="mt-3 text-sm"><span class="text-slate-400">Last observed emotion:</span> <span class="capitalize">{{ emotion }}</span></p>
      <dl v-if="estimates.length" class="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2">
        <div v-for="estimate in estimates" :key="estimate.key" class="rounded-lg bg-slate-950/50 px-3 py-2">
          <dt class="text-xs text-slate-400">{{ estimate.label }}</dt>
          <dd class="mt-1 font-semibold tabular-nums">{{ estimate.value > 0 ? '+' : '' }}{{ estimate.value }}</dd>
        </div>
      </dl>
      <p v-if="estimates.length" class="mt-2 text-xs text-slate-400">Trust, affinity and respect: −100 to 100. Tension: 0 to 100.</p>
      <p v-else class="mt-2 text-xs text-slate-400">No confirmed relationship estimate yet.</p>
      <details v-if="insights.evidence" class="mt-3 text-xs text-slate-400">
        <summary class="cursor-pointer">Source interaction</summary>
        <blockquote class="mt-2 whitespace-pre-wrap border-l-2 border-sky-400/30 pl-3">{{ insights.evidence }}</blockquote>
      </details>
    </template>
    <p v-else class="mt-3 text-sm text-slate-400">No evaluated VN state is available for this character yet.</p>
  </section>
</template>
