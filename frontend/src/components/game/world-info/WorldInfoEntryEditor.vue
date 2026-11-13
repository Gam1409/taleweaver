<script setup lang="ts">
import { computed } from 'vue'
import WorldInfoRelations from './WorldInfoRelations.vue'
import { infoCount, worldInfoAudiences, worldInfoKinds } from '@/services/worldInfoDisplay'
import type { WorldInfoController } from '@/composables/useWorldInfo'
const props = defineProps<{ controller: WorldInfoController }>()
const data = props.controller.data
const unavailableRecipients = computed(() => data.draft?.known_by.filter(id =>
  data.draft?.unresolved_known_by?.includes(id) || !data.state?.characters.some(npc => npc.id === id)
) ?? [])
const tags = computed({
  get: () => data.draft?.tags.map(tag => `#${tag}`).join(' ') || '',
  set: (value: string) => { if (data.draft) data.draft.tags = [...new Set(value.split(/[\s,#]+/u).filter(Boolean))] },
})
function knownBy(id: string, checked: boolean) {
  if (!data.draft) return
  data.draft.known_by = checked ? [...data.draft.known_by, id] : data.draft.known_by.filter(value => value !== id)
  if (!checked) data.draft.resolve_known_by = (data.draft.resolve_known_by ?? []).filter(value => value !== id)
}
function assign(id: string) {
  if (!data.draft) return
  data.draft.resolve_known_by = [...new Set([...(data.draft.resolve_known_by ?? []), id])]
}
function removeUnavailable(id: string) {
  if (!data.draft) return
  data.draft.known_by = data.draft.known_by.filter(value => value !== id)
  data.draft.resolve_known_by = (data.draft.resolve_known_by ?? []).filter(value => value !== id)
}
</script>
<template>
  <form v-if="data.draft && data.state" class="space-y-4" @submit.prevent="controller.saveEntry()">
    <div class="world-info-card text-xs text-slate-400"><p class="break-words">{{ data.draft.source_filename }} · source version {{ data.draft.source_revision_number }}</p><p>{{ infoCount(data.draft.facts_count) }} facts · {{ infoCount(data.draft.byte_count) }} UTF-8 bytes · {{ infoCount(data.draft.character_count) }} characters in saved entry</p><p>{{ data.draft.is_active ? 'Accepted entry' : data.draft.status === 'archived' ? 'Archived entry' : 'Draft entry' }}{{ data.draft.edited ? ' · Edited by author' : '' }}</p></div>
    <fieldset :disabled="!!data.busy" class="space-y-4">
      <label>Entry title<input v-model="data.draft.title" required :maxlength="data.state.limits.max_entry_title_characters ?? 160" /></label>
      <label>Summary<textarea v-model="data.draft.summary" rows="3" :maxlength="data.state.limits.max_entry_summary_characters ?? 500" /></label>
      <label>Primary group<input v-model="data.draft.group_name" :maxlength="data.state.limits.max_group_characters ?? 80" placeholder="Ungrouped" /><small>One primary topic per entry. Tags can connect several topics.</small></label>
      <div class="grid gap-4 sm:grid-cols-2">
        <label>Kind<select aria-label="Kind" v-model="data.draft.kind"><option v-for="(label, value) in worldInfoKinds" :key="value" :value="value">{{ label }}</option></select></label>
        <label>Available to<select aria-label="Available to" v-model="data.draft.audience"><option v-for="(label, value) in worldInfoAudiences" :key="value" :value="value">{{ label }}</option></select></label>
      </div>
      <p class="text-xs text-slate-400">Reference information does not automatically become a character’s learned memory or a witnessed event. Current game state takes precedence.</p>
      <p class="text-xs text-slate-400">Rumors preserve uncertainty. News may be outdated or unverified. Recollections remain source-attributed references.</p>
      <fieldset v-if="data.draft.audience === 'restricted'" class="world-info-card space-y-2">
        <legend>Characters who may use this reference</legend>
        <label v-for="npc in data.state.characters" :key="npc.id" class="world-info-check"><input type="checkbox" :checked="data.draft.known_by.includes(npc.id)" :disabled="!data.draft.known_by.includes(npc.id) && data.draft.known_by.length >= data.state.limits.max_known_by" @change="knownBy(npc.id, ($event.target as HTMLInputElement).checked)" />{{ npc.name }}</label>
        <div v-for="(id, index) in unavailableRecipients" :key="id" class="rounded-lg border border-amber-500/25 p-3 text-xs text-amber-200">
          <p>Unavailable character {{ index + 1 }} · this reference remains dormant for that saved recipient.</p>
          <p class="mt-1">Remove this recipient and select a current character to reassign access explicitly.</p>
          <div class="mt-2 flex flex-wrap gap-2"><button v-if="data.state.characters.some(npc => npc.id === id)" type="button" class="world-info-button" :disabled="data.draft.resolve_known_by?.includes(id)" @click="assign(id)">Assign to {{ data.state.characters.find(npc => npc.id === id)?.name }}</button><button type="button" class="world-info-button" @click="removeUnavailable(id)">Remove unavailable recipient {{ index + 1 }}</button></div>
          <p v-if="data.draft.resolve_known_by?.includes(id)" class="mt-1">Explicit assignment will be applied when you save.</p>
        </div>
        <p v-if="!data.state.characters.length" class="text-xs text-amber-200">No characters are available in this session. Choose another audience.</p>
      </fieldset>
      <label>Tags / hashtags<input v-model.lazy="tags" :maxlength="data.state.limits.max_tags * (data.state.limits.max_tag_characters + 2)" placeholder="#history #coast" /><small>Up to {{ data.state.limits.max_tags }} tags, {{ data.state.limits.max_tag_characters }} characters each. Separate with spaces or commas.</small></label>
      <section aria-label="Entry facts" class="space-y-3">
        <h3 class="font-semibold">Facts proposed from this source</h3>
        <article v-for="(fact, index) in data.draft.facts" :key="fact.id" class="world-info-card space-y-3">
          <label>Fact {{ index + 1 }}<textarea v-model="fact.text" required rows="3" :maxlength="data.state.limits.max_fact_characters ?? 500" /></label>
          <span v-if="fact.text !== fact.original_text" class="text-xs text-amber-200">Author correction · original evidence is kept</span>
          <details><summary>Original proposal & source evidence</summary><p class="mt-2 whitespace-pre-wrap break-words text-sm">{{ fact.original_text }}</p><blockquote v-for="(evidence, i) in fact.evidence" :key="i" class="mt-3 border-l-2 border-amber-500/30 pl-3"><p class="whitespace-pre-wrap break-words text-sm">{{ evidence.quote }}</p><small class="break-all">{{ evidence.pointer === null ? 'Markdown' : `JSON ${evidence.pointer || '/'}` }} · characters {{ evidence.start }}–{{ evidence.end }}</small></blockquote></details>
          <button v-if="data.draft.facts.length > 1" type="button" class="world-info-button" @click="data.draft.facts = data.draft.facts.filter(value => value.id !== fact.id)">Remove fact {{ index + 1 }}</button>
        </article>
      </section>
      <WorldInfoRelations v-model="data.draft.relations" :candidates="data.candidates" :entry-id="data.draft.id" :limit="data.state.limits.max_relations" :note-limit="data.state.limits.max_relation_note_characters ?? 160" :more="data.candidateNext !== null" :previous="data.candidateOffset > 0" :disabled="!!data.busy" @search="controller.loadCandidates" />
      <div class="flex flex-wrap gap-2"><button class="world-info-button is-primary" type="submit" :disabled="!controller.dirty.value || (data.draft.audience === 'restricted' && !data.draft.known_by.length)">Save entry</button><button type="button" class="world-info-button" :disabled="!controller.dirty.value" @click="data.draft = JSON.parse(data.baseline)">Discard changes</button></div>
    </fieldset>
  </form>
  <p v-else class="world-info-empty">Choose an entry to review its facts, source evidence and visibility.</p>
</template>
