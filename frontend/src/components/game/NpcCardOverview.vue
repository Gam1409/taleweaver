<script setup lang="ts">
import type { NpcCard } from '@/composables/useNpcJournal'
import NpcRelationship from './NpcRelationship.vue'
import NpcNarrativeInsights from './NpcNarrativeInsights.vue'
defineProps<{ card: NpcCard; showIndicators: boolean }>()
</script>

<template>
  <div class="npc-card-overview space-y-5">
    <section aria-label="About this character" class="space-y-2">
      <p class="text-[10px] uppercase tracking-widest text-amber-200/70">Known character</p>
      <h3 class="text-xl font-semibold text-slate-100">About {{ card.name }}</h3>
      <p class="text-sm font-normal leading-relaxed text-slate-300">
        {{ card.description || 'You have not learned much about this character yet.' }}
      </p>
    </section>
    <NpcRelationship :relationship="card.relationship" />
    <NpcNarrativeInsights v-if="showIndicators && card.state_visible" :insights="card.insights" />
    <section
      v-if="
        card.current_state?.availability === 'present' && card.current_state.conditions.items.length
      "
      aria-label="Current observations"
      class="space-y-3"
    >
      <h3 class="text-xs font-semibold uppercase tracking-wider text-slate-400">
        Current observations
      </h3>
      <p
        v-for="condition in card.current_state.conditions.items"
        :key="condition.id"
        class="rounded-xl border border-slate-700/70 bg-slate-950/25 p-4 text-sm font-normal leading-relaxed text-slate-300"
      >
        {{ condition.detail }}
      </p>
    </section>
  </div>
</template>
