<script setup lang="ts">
import { computed } from 'vue'
import type { WorldInfoController } from '@/composables/useWorldInfo'
import WorldInfoCatalog from './WorldInfoCatalog.vue'
import WorldInfoTopics from './WorldInfoTopics.vue'
const props = defineProps<{ controller: WorldInfoController }>()
const emit = defineEmits<{ navigate: [action: () => unknown]; openEntry: [id: string]; publish: []; bulkApply: [] }>()
const data = props.controller.data
const topics = computed(() => (data.state?.totals?.entries ?? data.total) > 50)
</script>
<template>
  <div class="world-info-workspace world-info-entry-workspace" :class="{ 'has-topics': topics }">
    <aside v-if="topics" class="world-info-topics"><WorldInfoTopics :controller="controller" /></aside>
    <WorldInfoCatalog :controller="controller" @navigate="emit('navigate', $event)" @open-entry="emit('openEntry', $event)" @publish="emit('publish')" @bulk-apply="emit('bulkApply')" />
  </div>
</template>
