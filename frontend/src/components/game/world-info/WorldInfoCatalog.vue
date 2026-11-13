<script setup lang="ts">
import { computed, ref } from 'vue'
import { FolderOpen, LayoutGrid, Search, Table2 } from 'lucide-vue-next'
import type { WorldInfoController } from '@/composables/useWorldInfo'
import WorldInfoBulk from './WorldInfoBulk.vue'
import WorldInfoSelection from './WorldInfoSelection.vue'
import { infoCount, worldInfoTagLabel, worldInfoKinds, worldInfoSourceOptions } from '@/services/worldInfoDisplay'
const props = defineProps<{ controller: WorldInfoController; topicsOpen?: boolean }>()
const emit = defineEmits<{ navigate: [action: () => unknown]; openEntry: [id: string]; publish: []; bulkApply: []; showTopics: [] }>()
const data = props.controller.data
const layout = ref<'cards' | 'table' | null>(null)
const bulk = ref<InstanceType<typeof WorldInfoBulk>>()
const table = computed(() => (layout.value ?? (data.total > 50 ? 'table' : 'cards')) === 'table')
const allRevisions = computed(() => worldInfoSourceOptions(data.state?.sources ?? [], data.source, data.tab === 'active'))
function select(id: string, checked: boolean) { data.selected = checked ? [...data.selected, id] : data.selected.filter(value => value !== id) }
function page(offset: number) { emit('navigate', () => props.controller.catalog.loadEntries(offset)) }
function openRow(event: MouseEvent, id: string) {
  if (data.busy) return
  if ((event.target as Element).closest('input, button, a, select, textarea')) return
  emit('openEntry', id)
}
</script>
<template>
  <section class="world-info-catalog" aria-label="Knowledge entries">
    <div class="world-info-catalog-tools">
      <form @submit.prevent="controller.catalog.search()"><fieldset :disabled="!!data.busy">
        <div class="world-info-search-row"><label class="min-w-0 flex-1">Search entries<input v-model="data.query" type="search" maxlength="200" placeholder="Words, facts, names or tags…" /></label><button type="submit" class="world-info-button"><Search class="h-4 w-4" aria-hidden="true" />Search / refresh</button></div>
        <div class="world-info-filter-options">
            <label v-if="data.tab === 'review'">Browse entries<select v-model="data.catalogView" aria-label="Browse entries" @change="controller.catalog.search()"><option value="review">Drafts for review</option><option value="all">All saved entries</option></select></label>
            <label>Kind<select v-model="data.kindFilter" aria-label="Entry kind filter" @change="controller.catalog.search()"><option value="">All kinds</option><option v-for="(label, value) in worldInfoKinds" :key="value" :value="value">{{ label }}</option></select></label><label>Sort<select v-model="data.sort" aria-label="Sort entries" @change="controller.catalog.search()"><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="title_asc">Title A–Z</option><option value="title_desc">Title Z–A</option><option value="source">Source</option></select></label>
            <label>Source version<select v-model="data.revisionFilter" aria-label="Source version filter" @change="controller.catalog.search()"><option value="">{{ data.tab === 'review' ? data.catalogView === 'all' ? 'All source versions' : 'All latest drafts' : 'All accepted sources' }}</option><option v-if="data.revisionFilter && !allRevisions.some(value => value.id === data.revisionFilter)" :value="data.revisionFilter">Selected saved version</option><option v-for="revision in allRevisions" :key="revision.id" :value="revision.id">{{ revision.title }}</option></select></label>
        </div>
      </fieldset></form>
      <div class="world-info-results-toolbar">
        <button data-world-info-topics-toggle type="button" class="world-info-button world-info-topics-toggle" aria-controls="world-info-topics" :aria-expanded="!!topicsOpen" @click="emit('showTopics')"><FolderOpen class="h-4 w-4" aria-hidden="true" />Groups & tags</button>
        <span class="world-info-result-count">{{ infoCount(data.total) }} matching entries<span v-if="data.groupFilter !== null"> · {{ data.groupFilter || 'Ungrouped' }}</span><span v-if="data.tagFilter"> · {{ worldInfoTagLabel(data.tagFilter) }}</span></span>
        <div class="world-info-layout-switch" role="group" aria-label="Entry layout"><button type="button" class="world-info-button" aria-label="Entry cards" :aria-pressed="!table" @click="layout = 'cards'"><LayoutGrid class="h-4 w-4" aria-hidden="true" /></button><button type="button" class="world-info-button" aria-label="Entry table" :aria-pressed="table" @click="layout = 'table'"><Table2 class="h-4 w-4" aria-hidden="true" /></button></div>
      </div>
      <p v-if="data.catalogLoading" role="status" class="text-xs text-slate-400">Loading page…</p>
      <WorldInfoBulk ref="bulk" :controller="controller" @apply="emit('bulkApply')" />
    </div>
    <WorldInfoSelection v-if="data.tab === 'review'" :controller="controller" @publish="emit('publish')" @publish-matching="bulk?.previewPublication()" />
    <div class="world-info-catalog-results">
      <p v-if="!data.entries.length && !data.catalogLoading" class="world-info-empty">No entries match this selection. Change the words, group, tag or source filter.</p>
      <table v-if="table && data.entries.length" class="world-info-entry-table"><thead><tr><th v-if="data.tab === 'review'"><span class="sr-only">Select</span></th><th>Entry</th><th>Facts</th></tr></thead><tbody><tr v-for="entry in data.entries" :key="entry.id" @click="openRow($event, entry.id)" :class="{ 'is-selected': data.draft?.id === entry.id }"><td v-if="data.tab === 'review'"><input type="checkbox" :aria-label="`Select ${entry.title}`" :checked="data.selected.includes(entry.id)" :disabled="!!data.busy || data.catalogLoading" @change="select(entry.id, ($event.target as HTMLInputElement).checked)" /></td><td><button class="world-info-entry-title" type="button" :title="entry.title" :data-world-info-entry="entry.id" :disabled="!!data.busy" @click="emit('openEntry', entry.id)">{{ entry.title }}</button><p v-if="entry.summary" class="world-info-entry-excerpt">{{ entry.summary }}</p><small class="world-info-entry-meta">{{ entry.group_name || 'Ungrouped' }} · {{ worldInfoKinds[entry.kind] }} · {{ entry.is_active ? 'Accepted entry' : entry.status === 'archived' ? 'Archived entry' : 'Draft entry' }} · v{{ entry.source_revision_number }}</small></td><td>{{ infoCount(entry.facts_count) }}</td></tr></tbody></table>
      <ul v-else class="world-info-entry-cards"><li v-for="entry in data.entries" :key="entry.id" class="world-info-entry-card"><input v-if="data.tab === 'review'" class="world-info-entry-select" type="checkbox" :aria-label="`Select ${entry.title}`" :checked="data.selected.includes(entry.id)" :disabled="!!data.busy || data.catalogLoading" @change="select(entry.id, ($event.target as HTMLInputElement).checked)" /><button type="button" class="world-info-row" :class="{ 'is-selected': data.draft?.id === entry.id || data.selected.includes(entry.id) }" :data-world-info-entry="entry.id" :disabled="!!data.busy" @click="emit('openEntry', entry.id)"><span class="min-w-0"><strong class="block break-words">{{ entry.title }}</strong><span v-if="entry.summary" class="world-info-entry-excerpt">{{ entry.summary }}</span><small class="block break-words">{{ worldInfoKinds[entry.kind] }} · {{ entry.source_filename }} · v{{ entry.source_revision_number }}</small><small class="block">{{ entry.group_name || 'Ungrouped' }} · {{ entry.is_active ? 'Accepted entry' : entry.status === 'archived' ? 'Archived entry' : 'Draft entry' }}</small><small>{{ infoCount(entry.facts_count) }} facts · {{ infoCount(entry.byte_count) }} bytes · {{ infoCount(entry.character_count) }} characters</small><span class="mt-1 block break-words text-xs text-slate-400">{{ entry.tags.map(worldInfoTagLabel).join(' ') }}</span></span></button></li></ul>
    </div>
    <footer class="world-info-catalog-pages"><span>{{ data.total ? `${infoCount(data.offset + 1)}–${infoCount(Math.min(data.offset + 50, data.total))}` : '0' }} of {{ infoCount(data.total) }}</span><div class="flex gap-2"><button type="button" class="world-info-button" :disabled="!data.offset || data.catalogLoading || !!data.busy || controller.catalog.hasPendingFilters()" @click="page(Math.max(0, data.offset - 50))">Previous</button><button type="button" class="world-info-button" :disabled="data.next === null || data.catalogLoading || !!data.busy || controller.catalog.hasPendingFilters()" @click="page(data.next ?? 0)">Next</button></div></footer>
  </section>
</template>
