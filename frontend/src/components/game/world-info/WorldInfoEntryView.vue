<script setup lang="ts">
import { computed } from 'vue'
import type { WorldInfoController } from '@/composables/useWorldInfo'
import { infoCount, worldInfoAudiences, worldInfoKinds } from '@/services/worldInfoDisplay'
const props = defineProps<{ controller: WorldInfoController }>()
const data = props.controller.data
const recipients = computed(() => data.draft?.known_by.map(id => ({
  name: data.state?.characters.find(character => character.id === id)?.name ?? 'Unavailable character',
  dormant: data.draft?.unresolved_known_by?.includes(id) || !data.state?.characters.some(character => character.id === id),
})) ?? [])
const relationKinds = { related: 'Related', supports: 'Supports', contradicts: 'Contradicts', part_of: 'Part of' }
</script>
<template>
  <article v-if="data.draft" class="world-info-entry-reader" aria-label="Entry content">
    <div class="world-info-entry-reading"><div class="world-info-read-badges"><span>{{ worldInfoKinds[data.draft.kind] }}</span><span>{{ worldInfoAudiences[data.draft.audience] }}</span><span>{{ data.draft.is_active ? 'Accepted' : data.draft.status === 'archived' ? 'Archived' : 'Draft' }}</span></div>
      <p v-if="data.draft.summary" class="world-info-entry-lead">{{ data.draft.summary }}</p>
      <section class="space-y-4" aria-label="Entry facts"><h3 class="text-lg font-semibold">Facts in this entry</h3>
        <article v-for="(fact, index) in data.draft.facts" :key="fact.id" class="world-info-read-fact">
          <span class="world-info-read-eyebrow">FACT {{ index + 1 }}</span>
          <p class="mt-2 whitespace-pre-wrap break-words">{{ fact.text }}</p>
          <p v-if="fact.edited || fact.text !== fact.original_text" class="mt-2 text-xs text-amber-200">Author correction · original evidence is kept</p>
          <details class="mt-4"><summary>Original proposal & source evidence</summary><p class="mt-3 whitespace-pre-wrap break-words text-sm text-slate-400">{{ fact.original_text }}</p><blockquote v-for="(evidence, i) in fact.evidence" :key="i" class="mt-3 border-l-2 border-amber-500/30 pl-3"><p class="whitespace-pre-wrap break-words text-sm">{{ evidence.quote }}</p><small class="break-all">{{ evidence.pointer === null ? 'Markdown' : `JSON ${evidence.pointer || '/'}` }} · characters {{ evidence.start }}–{{ evidence.end }}</small></blockquote></details>
        </article>
      </section>
      <section v-if="data.draft.relations.length" class="mt-6 space-y-3" aria-label="Related entries"><h3 class="text-lg font-semibold">Related entries</h3><article v-for="(relation, index) in data.draft.relations" :key="index" class="world-info-card"><strong>{{ relationKinds[relation.kind] }} · {{ data.candidates.find(entry => entry.id === relation.target_id)?.title || 'Linked entry' }}</strong><p v-if="relation.note" class="mt-2 whitespace-pre-wrap break-words text-sm text-slate-400">{{ relation.note }}</p></article></section>
    </div>
    <aside class="world-info-entry-metadata" aria-label="Entry information">
      <dl class="world-info-read-details"><div><dt>Primary group</dt><dd>{{ data.draft.group_name || 'Ungrouped' }}</dd></div><div><dt>Kind</dt><dd>{{ worldInfoKinds[data.draft.kind] }}</dd></div><div><dt>Available to</dt><dd>{{ worldInfoAudiences[data.draft.audience] }}</dd></div><div v-if="recipients.length"><dt>Selected characters</dt><dd v-for="(recipient, index) in recipients" :key="index">{{ recipient.name }}{{ recipient.dormant ? ' · Dormant reference' : '' }}</dd></div><div><dt>Status</dt><dd>{{ data.draft.is_active ? 'Accepted' : data.draft.status === 'archived' ? 'Archived' : 'Draft' }}{{ data.draft.edited ? ' · Edited by author' : '' }}</dd></div><div><dt>Source</dt><dd>{{ data.draft.source_filename }}</dd></div><div><dt>Source version</dt><dd>{{ data.draft.source_revision_number }}</dd></div><div><dt>Saved entry version</dt><dd>{{ data.draft.version }}</dd></div><div><dt>Saved size</dt><dd>{{ infoCount(data.draft.facts_count) }} facts · {{ infoCount(data.draft.byte_count) }} UTF-8 bytes · {{ infoCount(data.draft.character_count) }} characters</dd></div></dl>
      <section v-if="data.draft.tags.length" class="mt-5"><h3 class="world-info-read-eyebrow">TAGS</h3><div class="mt-2 flex flex-wrap gap-2"><span v-for="tag in data.draft.tags" :key="tag" class="world-info-read-tag">#{{ tag }}</span></div></section>
      <p class="mt-5 text-xs leading-relaxed text-slate-500">Reference information does not automatically become a character’s learned memory or a witnessed event. Current game state takes precedence.</p>
      <p class="mt-3 text-xs leading-relaxed text-slate-500">Rumors preserve uncertainty. News may be outdated or unverified. Recollections remain source-attributed references.</p>
    </aside>
  </article>
</template>
