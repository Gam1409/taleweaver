<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ plan?: Record<string, unknown> | null; positive?: unknown }>()
const profile = computed(() => props.plan?.capabilities as Record<string, unknown> | undefined)
const provenance = computed(() => props.plan?.provenance as Record<string, unknown> | undefined)
const facts = computed(() => {
  const values = provenance.value?.facts
  if (!Array.isArray(values)) return []
  const text = Array.from(typeof props.positive === 'string' ? props.positive : '')
  return values.filter((value): value is Record<string, unknown> => Boolean(value) && typeof value === 'object').map(value => {
    const start = value.positive_start
    const end = value.positive_end
    const mapped = Number.isInteger(start) && Number.isInteger(end) && (start as number) >= 0 && (end as number) <= text.length && (end as number) > (start as number)
    return { predicate: String(value.predicate || 'Fact'), disposition: String(value.disposition || ''), excerpt: mapped ? text.slice(start as number, end as number).join('') : '', emitted: Number.isInteger(value.start) }
  })
})
const represented = computed(() => facts.value.filter(fact => fact.emitted).length)
const reused = computed(() => props.plan?.cache_hit || props.plan?.normalization_cache_hit)
</script>

<template>
  <details v-if="plan" class="mb-4 rounded-lg border border-slate-700 p-3">
    <summary class="cursor-pointer text-sm font-semibold">Saved visual plan</summary>
    <dl class="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
      <dt class="text-slate-400">Format</dt><dd>{{ profile?.format || 'Not recorded' }}</dd>
      <dt class="text-slate-400">Continuity check</dt><dd>{{ plan.semantic_audit || 'Not recorded' }}</dd>
      <dt class="text-slate-400">English plan</dt><dd>{{ reused ? 'Reused' : 'Prepared for this image' }}</dd>
      <dt v-if="facts.length" class="text-slate-400">Facts with output</dt><dd v-if="facts.length">{{ represented }} / {{ facts.length }}</dd>
    </dl>
    <p class="mt-3 text-xs text-slate-400">These links show which prompt fragments came from saved facts. They do not prove that the image depicts them correctly.</p>
    <p v-if="plan.limited_output_coverage" class="mt-2 text-xs text-amber-300">Some facts have limited expression in this format. Global tags may not distinguish who wears or does what.</p>
    <ul v-if="facts.length" aria-label="Saved facts and prompt fragments" class="mt-3 max-h-64 space-y-2 overflow-y-auto text-xs">
      <li v-for="(fact, index) in facts" :key="index" class="rounded bg-slate-950 p-2">
        <span class="font-semibold">{{ fact.predicate }}</span>
        <p v-if="fact.excerpt" class="mt-1 whitespace-pre-wrap break-words">{{ fact.excerpt }}</p>
        <p v-else class="mt-1 text-slate-400">{{ fact.disposition ? `Declared limitation: ${fact.disposition}` : 'Final text mapping unavailable.' }}</p>
      </li>
    </ul>
  </details>
</template>
