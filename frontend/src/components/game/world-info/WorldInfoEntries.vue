<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { ArrowLeft, FolderOpen } from 'lucide-vue-next'
import type { WorldInfoController } from '@/composables/useWorldInfo'
import WorldInfoCatalog from './WorldInfoCatalog.vue'
import WorldInfoTopics from './WorldInfoTopics.vue'
const props = defineProps<{ controller: WorldInfoController }>()
const emit = defineEmits<{ navigate: [action: () => unknown]; openEntry: [id: string]; publish: []; bulkApply: [] }>()
const data = props.controller.data
const topicsOpen = ref(false)
const workspace = ref<HTMLElement>()
async function showTopics() {
  topicsOpen.value = true
  await nextTick()
  workspace.value?.querySelector<HTMLInputElement>('.world-info-topics input')?.focus()
}
async function hideTopics() {
  topicsOpen.value = false
  await nextTick()
  workspace.value?.querySelector<HTMLButtonElement>('[data-world-info-topics-toggle]')?.focus({ preventScroll: true })
}
function dismissTopics() {
  if (!topicsOpen.value) return false
  void hideTopics()
  return true
}
defineExpose({ dismissTopics })
watch(() => data.tab, () => { topicsOpen.value = false })
</script>
<template>
  <div ref="workspace" class="world-info-workspace world-info-entry-workspace" :class="{ 'topics-open': topicsOpen }">
    <aside id="world-info-topics" class="world-info-topics" aria-label="Knowledge groups">
      <button type="button" class="world-info-button world-info-topics-back" @click="hideTopics"><ArrowLeft class="h-4 w-4" aria-hidden="true" />Back to entries</button>
      <h3 class="world-info-topics-heading"><FolderOpen class="h-4 w-4" aria-hidden="true" />Groups & tags</h3>
      <WorldInfoTopics :controller="controller" />
    </aside>
    <WorldInfoCatalog :controller="controller" :topics-open="topicsOpen" @show-topics="showTopics" @navigate="emit('navigate', $event)" @open-entry="emit('openEntry', $event)" @publish="emit('publish')" @bulk-apply="emit('bulkApply')" />
  </div>
</template>
