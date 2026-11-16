<script setup lang="ts">
import { ref } from 'vue'
import type { WorldInfoEntrySummary, WorldInfoRelation } from '@/types/worldInfo'
const props = defineProps<{ modelValue: WorldInfoRelation[]; candidates: WorldInfoEntrySummary[]; entryId: string; limit: number; noteLimit: number; more: boolean; previous: boolean; disabled: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: WorldInfoRelation[]]; search: [query: string, direction?: 'next' | 'previous'] }>()
const query = ref('')
const target = ref('')
function add() {
  if (!target.value || props.modelValue.length >= props.limit) return
  emit('update:modelValue', [...props.modelValue, { target_id: target.value, kind: 'related', note: '' }])
  target.value = ''
}
function update(index: number, patch: Partial<WorldInfoRelation>) {
  emit('update:modelValue', props.modelValue.map((value, i) => i === index ? { ...value, ...patch } : value))
}
</script>
<template>
  <section class="world-info-card" aria-label="Relationships between entries">
    <h3 class="font-semibold">Relationships between entries ({{ modelValue.length }} / {{ limit }})</h3>
    <fieldset :disabled="disabled" class="mt-3 space-y-3">
      <div v-for="(relation, index) in modelValue" :key="index" class="space-y-2 border-b border-slate-700 pb-3">
        <p class="break-words text-sm">{{ candidates.find(entry => entry.id === relation.target_id)?.title || relation.target_id }}</p>
        <label>Relationship<select :value="relation.kind" @change="update(index, { kind: ($event.target as HTMLSelectElement).value as WorldInfoRelation['kind'] })"><option value="related">Related</option><option value="supports">Supports</option><option value="contradicts">Contradicts</option><option value="part_of">Part of</option></select></label>
        <label>Relationship note<input :value="relation.note" :maxlength="noteLimit" @input="update(index, { note: ($event.target as HTMLInputElement).value })" /></label>
        <button type="button" class="world-info-button" @click="emit('update:modelValue', modelValue.filter((_, i) => i !== index))">Remove relationship {{ index + 1 }}</button>
      </div>
      <label>Find a session entry<input v-model="query" type="search" @change="emit('search', query)" @keydown.enter.prevent="emit('search', query)" /></label>
      <label>Related entry<select aria-label="Related entry" v-model="target"><option value="">Choose an entry</option><option v-for="entry in candidates.filter(value => value.id !== entryId)" :key="entry.id" :value="entry.id">{{ entry.title }} · {{ entry.source_filename }}</option></select></label>
      <div class="flex flex-wrap gap-2"><button v-if="previous" type="button" class="world-info-button" @click="emit('search', query, 'previous')">Previous matching entries</button><button v-if="more" type="button" class="world-info-button" @click="emit('search', query, 'next')">Next matching entries</button><button type="button" class="world-info-button" :disabled="!target || modelValue.length >= limit" @click="add">Add relationship</button></div>
    </fieldset>
  </section>
</template>
