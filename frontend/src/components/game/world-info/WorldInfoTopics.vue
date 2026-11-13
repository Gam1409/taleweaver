<script setup lang="ts">
import type { WorldInfoController } from '@/composables/useWorldInfo'
import { infoCount } from '@/services/worldInfoDisplay'
const props = defineProps<{ controller: WorldInfoController }>()
const data = props.controller.data
</script>
<template>
  <section class="world-info-topic-content" aria-label="Groups and tags">
    <form class="mb-4 space-y-2" @submit.prevent="controller.catalog.loadFacets()"><label>Find a group or tag<input v-model="data.facetQuery" type="search" placeholder="Find a topic…" /></label><button type="submit" class="world-info-button">Find topics</button></form>
    <h3 class="mb-2 font-semibold">Groups</h3>
    <button type="button" class="world-info-topic" :aria-pressed="data.groupFilter === null" :disabled="!!data.busy" @click="controller.catalog.selectGroup(null)"><span>All groups</span></button>
    <button v-for="group in data.facets?.groups.items" :key="group.name" type="button" class="world-info-topic" :aria-pressed="data.groupFilter === group.name" :disabled="!!data.busy" @click="controller.catalog.selectGroup(group.name)"><span class="break-words">{{ group.name || 'Ungrouped' }}</span><small>{{ infoCount(group.count) }}</small></button>
    <p v-if="data.facets" class="mt-2 text-xs text-slate-500">{{ data.facets.groups.items.length }} of {{ infoCount(data.facets.groups.total) }} groups. Find a topic to narrow the names.</p>
    <label class="mt-5">Tag filter<select v-model="data.tagFilter" aria-label="Tag filter" :disabled="!!data.busy" @change="controller.catalog.search()"><option value="">All tags</option><option v-if="data.tagFilter && !data.facets?.tags.items.some(tag => tag.name === data.tagFilter)" :value="data.tagFilter">#{{ data.tagFilter }}</option><option v-for="tag in data.facets?.tags.items" :key="tag.name" :value="tag.name">#{{ tag.name }} ({{ infoCount(tag.count) }})</option></select></label>
    <p v-if="data.facets" class="mt-2 text-xs text-slate-500">{{ data.facets.tags.items.length }} of {{ infoCount(data.facets.tags.total) }} tags. Topic search also finds tags outside this list.</p>
  </section>
</template>
