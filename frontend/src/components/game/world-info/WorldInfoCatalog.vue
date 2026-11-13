<script setup lang="ts">
import { computed, ref } from 'vue'
import { List, Table2 } from 'lucide-vue-next'
import type { WorldInfoController } from '@/composables/useWorldInfo'
import WorldInfoTopics from './WorldInfoTopics.vue'
import WorldInfoBulk from './WorldInfoBulk.vue'
import { infoCount, worldInfoKinds, worldInfoSourceOptions } from '@/services/worldInfoDisplay'
const props = defineProps<{ controller: WorldInfoController }>()
const emit = defineEmits<{ navigate: [action: () => unknown]; openEntry: [id: string]; publish: []; bulkApply: [] }>()
const data = props.controller.data
const layout = ref<'cards' | 'table' | null>(null)
const table = computed(() => (layout.value ?? (data.total > 50 ? 'table' : 'cards')) === 'table')
const allRevisions = computed(() => worldInfoSourceOptions(data.state?.sources ?? [], data.source, data.tab === 'active'))
function select(id: string, checked: boolean) { data.selected = checked ? [...data.selected, id] : data.selected.filter(value => value !== id) }
function page(offset: number) { emit('navigate', () => props.controller.catalog.loadEntries(offset)) }
function openRow(event: MouseEvent, id: string) {
  if ((event.target as Element).closest('input, button, a, select, textarea')) return
  emit('openEntry', id)
}
</script>
<template>
  <section class="world-info-catalog" aria-label="Knowledge entries">
    <div class="world-info-catalog-tools">
      <form class="space-y-3" @submit.prevent="controller.catalog.search()"><fieldset :disabled="!!data.busy" class="space-y-3">
        <div class="flex items-end gap-2"><label class="min-w-0 flex-1">Search entries<input v-model="data.query" type="search" maxlength="200" placeholder="Words, facts, names or tags…" /></label><button type="submit" class="world-info-button">Search / refresh</button></div>
        <div class="flex items-center justify-between gap-2"><span class="text-xs text-slate-400">{{ infoCount(data.total) }} matching entries</span><div class="flex gap-1"><button type="button" class="world-info-button" aria-label="Entry cards" :aria-pressed="!table" @click="layout = 'cards'"><List class="h-4 w-4" /></button><button type="button" class="world-info-button" aria-label="Entry table" :aria-pressed="table" @click="layout = 'table'"><Table2 class="h-4 w-4" /></button></div></div>
        <details class="world-info-filter-options"><summary>Filters · {{ data.tab === 'active' ? 'Accepted entries' : data.catalogView === 'all' ? 'All saved entries' : 'Drafts for review' }}</summary>
          <div class="mt-3 space-y-3"><p class="text-xs text-slate-500">All search words must match anywhere in the saved text, across every page.</p>
            <label v-if="data.tab === 'review'">Browse entries<select v-model="data.catalogView" aria-label="Browse entries" @change="controller.catalog.search()"><option value="review">Drafts for review</option><option value="all">All saved entries</option></select></label>
            <div class="grid grid-cols-2 gap-3"><label>Kind<select v-model="data.kindFilter" aria-label="Entry kind filter" @change="controller.catalog.search()"><option value="">All kinds</option><option v-for="(label, value) in worldInfoKinds" :key="value" :value="value">{{ label }}</option></select></label><label>Sort<select v-model="data.sort" aria-label="Sort entries" @change="controller.catalog.search()"><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="title_asc">Title A–Z</option><option value="title_desc">Title Z–A</option><option value="source">Source</option></select></label></div>
            <label>Source version<select v-model="data.revisionFilter" aria-label="Source version filter" @change="controller.catalog.search()"><option value="">{{ data.tab === 'review' ? data.catalogView === 'all' ? 'All source versions' : 'All latest drafts' : 'All accepted sources' }}</option><option v-if="data.revisionFilter && !allRevisions.some(value => value.id === data.revisionFilter)" :value="data.revisionFilter">Selected saved version</option><option v-for="revision in allRevisions" :key="revision.id" :value="revision.id">{{ revision.title }}</option></select></label>
          </div>
        </details>
      </fieldset></form>
      <details class="world-info-mobile-topics world-info-card mt-3"><summary>Groups & tags{{ data.groupFilter !== null ? ` · ${data.groupFilter || 'Ungrouped'}` : '' }}{{ data.tagFilter ? ` · #${data.tagFilter}` : '' }}</summary><WorldInfoTopics class="mt-3" :controller="controller" /></details>
      <p v-if="data.catalogLoading" role="status" class="mt-2 text-xs text-slate-400">Loading page…</p>
      <div v-if="data.tab === 'review' && data.selected.length" class="my-3"><button type="button" class="world-info-button is-primary" :disabled="!!data.busy || controller.dirty.value" @click="emit('publish')">Publish selected ({{ data.selected.length }})</button><p class="mt-1 text-xs text-slate-500">This page only. Choose one source version.</p></div>
      <WorldInfoBulk class="mt-3" :controller="controller" @apply="emit('bulkApply')" />
    </div>
    <div class="world-info-catalog-results">
      <p v-if="!data.entries.length && !data.catalogLoading" class="world-info-empty">No entries match this selection. Change the words, group, tag or source filter.</p>
      <table v-if="table && data.entries.length" class="world-info-entry-table"><thead><tr><th v-if="data.tab === 'review'"><span class="sr-only">Select</span></th><th>Entry</th><th>Facts</th></tr></thead><tbody><tr v-for="entry in data.entries" :key="entry.id" @click="openRow($event, entry.id)" :class="{ 'is-selected': data.draft?.id === entry.id }"><td v-if="data.tab === 'review'"><input type="checkbox" :aria-label="`Select ${entry.title}`" :checked="data.selected.includes(entry.id)" :disabled="!!data.busy || data.catalogLoading" @change="select(entry.id, ($event.target as HTMLInputElement).checked)" /></td><td><button class="world-info-entry-title" type="button" :title="entry.title" :data-world-info-entry="entry.id" @click="emit('openEntry', entry.id)">{{ entry.title }}</button><p v-if="entry.summary" class="world-info-entry-excerpt">{{ entry.summary }}</p><small class="world-info-entry-meta">{{ entry.group_name || 'Ungrouped' }} · {{ worldInfoKinds[entry.kind] }} · {{ entry.is_active ? 'Accepted entry' : entry.status === 'archived' ? 'Archived entry' : 'Draft entry' }} · v{{ entry.source_revision_number }}</small></td><td>{{ infoCount(entry.facts_count) }}</td></tr></tbody></table>
      <ul v-else class="world-info-entry-cards"><li v-for="entry in data.entries" :key="entry.id" class="flex items-start gap-2"><input v-if="data.tab === 'review'" class="mt-4 h-4 w-4 shrink-0" type="checkbox" :aria-label="`Select ${entry.title}`" :checked="data.selected.includes(entry.id)" :disabled="!!data.busy || data.catalogLoading" @change="select(entry.id, ($event.target as HTMLInputElement).checked)" /><button type="button" class="world-info-row" :class="{ 'is-selected': data.draft?.id === entry.id }" :data-world-info-entry="entry.id" @click="emit('openEntry', entry.id)"><span class="min-w-0"><strong class="block break-words">{{ entry.title }}</strong><span v-if="entry.summary" class="world-info-entry-excerpt">{{ entry.summary }}</span><small class="block break-words">{{ worldInfoKinds[entry.kind] }} · {{ entry.source_filename }} · v{{ entry.source_revision_number }}</small><small class="block">{{ entry.group_name || 'Ungrouped' }} · {{ entry.is_active ? 'Accepted entry' : entry.status === 'archived' ? 'Archived entry' : 'Draft entry' }}</small><small>{{ infoCount(entry.facts_count) }} facts · {{ infoCount(entry.byte_count) }} bytes · {{ infoCount(entry.character_count) }} characters</small><span class="mt-1 block break-words text-xs text-slate-400">{{ entry.tags.map(tag => `#${tag}`).join(' ') }}</span></span></button></li></ul>
    </div>
    <footer class="world-info-catalog-pages"><span>{{ data.total ? `${infoCount(data.offset + 1)}–${infoCount(Math.min(data.offset + 50, data.total))}` : '0' }} of {{ infoCount(data.total) }}</span><div class="flex gap-2"><button type="button" class="world-info-button" :disabled="!data.offset || data.catalogLoading || !!data.busy || controller.catalog.hasPendingFilters()" @click="page(Math.max(0, data.offset - 50))">Previous</button><button type="button" class="world-info-button" :disabled="data.next === null || data.catalogLoading || !!data.busy || controller.catalog.hasPendingFilters()" @click="page(data.next ?? 0)">Next</button></div></footer>
  </section>
</template>
