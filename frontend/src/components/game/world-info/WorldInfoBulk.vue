<script setup lang="ts">
import { ref } from 'vue'
import type { WorldInfoController } from '@/composables/useWorldInfo'
import type { WorldInfoBulkRequest } from '@/types/worldInfo'
import { infoCount } from '@/services/worldInfoDisplay'
const props = defineProps<{ controller: WorldInfoController }>()
const emit = defineEmits<{ apply: [] }>()
const action = ref<WorldInfoBulkRequest['action']>('set_group'), group = ref(''), tags = ref('')
function preview() {
  const values = [...new Set(tags.value.split(/[\s,#]+/u).filter(Boolean))]
  void props.controller.catalog.previewBulk(action.value, group.value, values)
}
function clearPreview() { props.controller.catalog.clearBulk() }
</script>
<template>
  <details class="world-info-card world-info-bulk">
    <summary>Organize all matching entries</summary>
    <p class="mt-3 text-xs text-slate-400">Applies to the full filtered result, across every page. Preview the count and sample before confirming.</p>
    <form class="mt-3 space-y-3" @submit.prevent="preview" @input="clearPreview" @change="clearPreview"><fieldset :disabled="!!controller.data.busy || controller.dirty.value" class="space-y-3">
      <label>Action<select v-model="action" aria-label="Bulk action"><option value="set_group">Set primary group</option><option value="add_tags">Add tags</option><option value="remove_tags">Remove tags</option><option value="publish">Publish matching entries</option></select></label>
      <label v-if="action === 'set_group'">Group name<input v-model="group" :maxlength="controller.data.state?.limits.max_group_characters ?? 80" placeholder="Empty clears the primary group" /></label>
      <label v-if="action === 'add_tags' || action === 'remove_tags'">Tags for matching entries<input v-model="tags" required placeholder="#history #coast" :maxlength="(controller.data.state?.limits.max_tags ?? 12) * ((controller.data.state?.limits.max_tag_characters ?? 48) + 2)" /></label>
      <p v-if="action === 'publish'" class="text-xs text-amber-200">Choose one source version. Accepting another version replaces that source’s previously accepted entries.</p>
      <button type="submit" class="world-info-button" :disabled="!controller.data.total">Preview matching entries</button>
    </fieldset></form>
    <section v-if="controller.data.bulkPreview" class="mt-4 space-y-3 border-t border-slate-700 pt-3" aria-label="Bulk action preview"><p class="font-semibold">{{ infoCount(controller.data.bulkPreview.count) }} matching entries · {{ infoCount(controller.data.bulkPreview.facts_count) }} facts</p><p class="break-words text-sm">{{ controller.data.bulkIntent?.action === 'set_group' ? `Set primary group: ${controller.data.bulkIntent.group_name || 'Ungrouped'}` : controller.data.bulkIntent?.action === 'publish' ? 'Publish the matching source-version entries' : `${controller.data.bulkIntent?.action === 'add_tags' ? 'Add' : 'Remove'} tags: ${controller.data.bulkIntent?.tags?.map(tag => `#${tag}`).join(' ')}` }}</p><p class="text-xs text-slate-400">{{ infoCount(controller.data.bulkPreview.active_count) }} are currently accepted. Sample of up to five:</p><ul class="space-y-1 text-sm"><li v-for="entry in controller.data.bulkPreview.sample" :key="entry.id" class="break-words">{{ entry.title }}</li></ul><button type="button" class="world-info-button is-primary" :disabled="!controller.data.bulkPreview.count || !!controller.data.busy || controller.dirty.value" @click="emit('apply')">Confirm matching changes</button></section>
  </details>
</template>
