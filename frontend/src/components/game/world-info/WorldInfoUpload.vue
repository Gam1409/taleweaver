<script setup lang="ts">
import { ref } from 'vue'
import { Upload } from 'lucide-vue-next'
import type { WorldInfoController } from '@/composables/useWorldInfo'
import { infoCount } from '@/services/worldInfoDisplay'

const props = defineProps<{ controller: WorldInfoController }>()
const data = props.controller.data
const file = ref<File | null>(null)
const title = ref('')
const replacing = ref('')
const input = ref<HTMLInputElement>()
async function upload() {
  if (!file.value) return
  const replacement = data.state?.sources.find(source => source.id === replacing.value)
  if (replacing.value && !replacement) { data.error = 'This source is no longer available. Refresh status and choose an upload destination again.'; return }
  if (!await props.controller.upload(file.value, title.value, replacement)) return
  file.value = null
  if (input.value) input.value.value = ''
}
</script>
<template>
  <form class="world-info-upload" aria-label="Add source material" @submit.prevent="upload">
    <fieldset :disabled="!data.state || !!data.busy" class="world-info-upload-row">
      <label>Source file · Markdown or JSON<input ref="input" type="file" accept=".md,.json,text/markdown,application/json" required @change="file = ($event.target as HTMLInputElement).files?.[0] || null" /></label>
      <label>Upload destination<select aria-label="Upload destination" v-model="replacing"><option value="">New source</option><option v-for="source in data.state?.sources" :key="source.id" :value="source.id">New version of {{ source.title || source.filename }}</option></select></label>
      <label v-if="!replacing">Source title · optional<input v-model="title" maxlength="200" /></label>
      <button type="submit" class="world-info-button is-primary" :disabled="!file || (!replacing && !!data.state && data.state.sources.length >= data.state.limits.max_sources)"><Upload aria-hidden="true" class="h-4 w-4" />Upload & analyse</button>
    </fieldset>
    <p v-if="data.state" class="world-info-upload-hint">UTF-8 · up to {{ infoCount(data.state.limits.max_source_bytes) }} bytes and {{ infoCount(data.state.limits.max_source_characters) }} characters · {{ data.state.limits.max_sources }} sources per session · {{ data.state.limits.max_source_revisions }} versions per source. Review model proposals before publishing.</p>
    <p v-if="replacing" class="world-info-upload-hint text-amber-200">Accepted entries stay active until you explicitly publish the replacement version.</p>
  </form>
</template>
