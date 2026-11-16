<script setup lang="ts">
import { computed } from 'vue'
import { CheckCheck } from 'lucide-vue-next'
import type { WorldInfoController } from '@/composables/useWorldInfo'
import { infoCount } from '@/services/worldInfoDisplay'

const props = defineProps<{ controller: WorldInfoController }>()
const emit = defineEmits<{ publish: []; publishMatching: [] }>()
const data = props.controller.data
const selected = computed(() => props.controller.selectedEntries.value)
const all = computed(() => !!data.entries.length && data.entries.every(entry => data.selected.includes(entry.id)))
const some = computed(() => data.entries.some(entry => data.selected.includes(entry.id)))
const oneVersion = computed(() => new Set(selected.value.map(entry => entry.source_revision_id)).size <= 1)
const unavailable = computed(() => !!data.busy || data.catalogLoading || props.controller.catalog.hasPendingFilters())
function selectPage(checked: boolean) { data.selected = checked ? data.entries.map(entry => entry.id) : [] }
</script>
<template>
  <section class="world-info-selection-controls" aria-label="Select and publish entries">
    <div class="world-info-selection-row">
      <label class="world-info-check"><input type="checkbox" aria-label="Select this page" :checked="all" :indeterminate="some && !all" :disabled="unavailable || !data.entries.length" @change="selectPage(($event.target as HTMLInputElement).checked)" />Select this page</label>
      <span class="world-info-selected-count">{{ infoCount(data.selected.length) }} selected</span>
      <button type="button" class="world-info-button" :disabled="unavailable || !data.selected.length" @click="data.selected = []">Clear selection</button>
      <button type="button" class="world-info-button is-primary" :disabled="unavailable || !selected.length || !oneVersion || controller.dirty.value" @click="emit('publish')"><CheckCheck class="h-4 w-4" aria-hidden="true" />Publish selected ({{ data.selected.length }})</button>
      <button type="button" class="world-info-button" :disabled="unavailable || !data.total || !data.revisionFilter || controller.dirty.value" @click="emit('publishMatching')">Publish all matching</button>
    </div>
    <p v-if="!oneVersion" class="world-info-selection-hint">Select entries from one source version to publish them together.</p>
    <p v-else class="world-info-selection-hint">Select this page affects only the {{ infoCount(data.entries.length) }} entries shown. To publish across every page, choose a source version above and preview all matching entries.</p>
  </section>
</template>
