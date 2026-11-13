<script setup lang="ts">
import { computed } from 'vue'
import type { WorldInfoController } from '@/composables/useWorldInfo'
import WorldInfoEntryEditor from './WorldInfoEntryEditor.vue'
import WorldInfoCatalog from './WorldInfoCatalog.vue'
import WorldInfoTopics from './WorldInfoTopics.vue'
const props = defineProps<{ controller: WorldInfoController }>()
const emit = defineEmits<{ navigate: [action: () => unknown]; publish: []; remove: []; unpublish: []; bulkApply: [] }>()
const data = props.controller.data
const topics = computed(() => (data.state?.totals?.entries ?? data.total) > 50)
</script>
<template>
  <div class="world-info-workspace world-info-entry-workspace" :class="{ 'show-detail': data.mobileDetail, 'has-topics': topics }">
    <aside v-if="topics" class="world-info-topics"><WorldInfoTopics :controller="controller" /></aside>
    <WorldInfoCatalog :controller="controller" @navigate="emit('navigate', $event)" @publish="emit('publish')" @bulk-apply="emit('bulkApply')" />
    <section class="world-info-detail" aria-label="Entry review and editing">
      <button type="button" class="world-info-button world-info-back mb-4" @click="data.mobileDetail = false">← Back to entries</button>
      <WorldInfoEntryEditor :controller="controller" />
      <div v-if="data.draft" class="mt-4 flex flex-wrap gap-2"><button type="button" class="world-info-button" @click="emit('navigate', () => controller.openEntry(data.draft!.id))">Reload latest entry</button><button v-if="data.draft.is_active" type="button" class="world-info-button" :disabled="!!data.busy" @click="emit('unpublish')">Remove from recall</button><button type="button" class="world-info-button is-danger" :disabled="!!data.busy" @click="emit('remove')">Delete entry</button></div>
    </section>
  </div>
</template>
