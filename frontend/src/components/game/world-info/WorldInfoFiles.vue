<script setup lang="ts">
import { ref } from 'vue'
import { FileText, Upload } from 'lucide-vue-next'
import type { WorldInfoController } from '@/composables/useWorldInfo'
import type { WorldInfoSource } from '@/types/worldInfo'
import { infoCount } from '@/services/worldInfoDisplay'
const props = defineProps<{ controller: WorldInfoController }>()
const emit = defineEmits<{ remove: [source: WorldInfoSource] }>()
const data = props.controller.data
const file = ref<File | null>(null)
const title = ref('')
const replacing = ref('')
const input = ref<HTMLInputElement>()
async function upload() {
  if (!file.value) return
  const replacement = data.state?.sources.find(source => source.id === replacing.value)
  if (replacing.value && !replacement) { data.error = 'This source is no longer available. Refresh status and choose an upload destination again.'; return }
  await props.controller.upload(file.value, title.value, replacement)
  if (data.error) return
  file.value = null
  if (input.value) input.value.value = ''
}
</script>
<template>
  <div class="world-info-workspace" :class="{ 'show-detail': data.mobileDetail }">
    <section class="world-info-list" aria-label="Files and processing">
      <form class="world-info-card space-y-3" @submit.prevent="upload">
        <h3 class="flex items-center gap-2 font-semibold"><Upload aria-hidden="true" class="h-4 w-4" /> Add source material</h3>
        <p class="text-xs text-slate-400">Upload and analyse proposes source-backed entries using your configured model. Large sources pause for a workload review before analysis starts. Review and publish the entries you accept.</p>
        <fieldset :disabled="!data.state || !!data.busy" class="space-y-3">
          <label>Upload destination<select aria-label="Upload destination" v-model="replacing"><option value="">New source</option><option v-for="source in data.state?.sources" :key="source.id" :value="source.id">New version of {{ source.title || source.filename }}</option></select></label>
          <p v-if="replacing" class="text-xs text-amber-200">Accepted entries stay active until you explicitly publish the replacement version.</p>
          <label>Source file · Markdown or JSON<input ref="input" type="file" accept=".md,.json,text/markdown,application/json" required @change="file = ($event.target as HTMLInputElement).files?.[0] || null" /></label>
          <label v-if="!replacing">Source title · optional<input v-model="title" maxlength="200" /></label>
          <p v-if="data.state" class="text-xs text-slate-400">UTF-8 only · up to {{ infoCount(data.state.limits.max_source_bytes) }} bytes and {{ infoCount(data.state.limits.max_source_characters) }} characters per file · {{ data.state.limits.max_sources }} sources per session · {{ data.state.limits.max_source_revisions }} versions per source.</p>
          <button type="submit" class="world-info-button is-primary" :disabled="!file || (!replacing && !!data.state && data.state.sources.length >= data.state.limits.max_sources)">Upload & analyse</button>
        </fieldset>
      </form>
      <p v-if="!data.state?.sources.length" class="world-info-empty">No source files in this session. Add Markdown or JSON to propose knowledge for review.</p>
      <ul class="space-y-2"><li v-for="source in data.state?.sources" :key="source.id"><button type="button" class="world-info-row" :class="{ 'is-selected': data.source?.source.id === source.id }" @click="controller.openSource(source.id)"><FileText aria-hidden="true" class="h-4 w-4 shrink-0" /><span class="min-w-0 flex-1"><strong class="block break-words">{{ source.title || source.filename }}</strong><small class="block break-words">{{ source.filename }} · version {{ source.job.number }} · {{ source.job.status }}</small><small>{{ source.active_entries }} accepted · {{ source.draft_entries }} drafts</small></span></button></li></ul>
    </section>
    <section class="world-info-detail" aria-label="Source details">
      <button type="button" class="world-info-button world-info-back mb-4" @click="data.mobileDetail = false">← Back to files</button>
      <div v-if="data.source && data.job" class="space-y-4">
        <h3 class="break-words text-lg font-semibold">{{ data.source.source.title || data.source.source.filename }}</h3>
        <label>Source version<select aria-label="Source version" :value="data.job.id" @change="controller.chooseRevision(data.source.revisions.find(job => job.id === ($event.target as HTMLSelectElement).value)!)"><option v-for="job in data.source.revisions" :key="job.id" :value="job.id">Version {{ job.number }} · {{ job.status }}{{ data.source.source.published_revision === job.number ? ' · Accepted version' : '' }}</option></select></label>
        <div class="world-info-card space-y-2" role="status" aria-live="polite">
          <p class="font-semibold">{{ data.job.status }} · version {{ data.job.number }}</p>
          <p>{{ infoCount(data.job.cursor) }} / {{ infoCount(data.job.total_batches) }} processing batches saved</p>
          <p>{{ infoCount(data.job.processed_characters) }} characters processed</p>
          <p>Original: {{ infoCount(data.job.input_bytes) }} UTF-8 bytes · {{ infoCount(data.job.input_characters) }} characters</p>
          <p>{{ infoCount(data.job.facts_count) }} facts · {{ infoCount(data.job.entries_count) }} entries</p>
          <p>Entries: {{ infoCount(data.job.entries_bytes) }} UTF-8 bytes · {{ infoCount(data.job.entries_characters) }} characters</p>
          <p v-if="data.job.last_error_code" class="text-amber-200">{{ data.job.last_error_code === 'storage_limit' ? 'Session knowledge storage limit reached. Remove unused entries or sources, then resume.' : 'Processing could not finish. Saved work is kept; resume when available.' }}</p>
          <p class="text-xs text-slate-400">You may close this window and keep playing. Closing stops status checks; it does not cancel processing.</p>
        </div>
        <section v-if="(data.job.total_batches ?? 0) > 16 && (data.job.can_start || data.job.can_resume)" class="world-info-card border-amber-500/30 text-sm text-amber-100" aria-label="Large source workload"><h4 class="font-semibold">Review the workload before starting</h4><p class="mt-2">{{ infoCount(data.job.total_batches) }} batches in this source · {{ infoCount((data.job.total_batches ?? 0) - data.job.cursor) }} remaining. Up to {{ infoCount(2 * ((data.job.total_batches ?? 0) - data.job.cursor)) }} remaining model calls for analysis and corrections; provider retries can add requests.</p><p class="mt-2">A detailed book may take hours. The source stays saved if you close this window without starting.</p></section>
        <div class="flex flex-wrap gap-2">
          <button v-if="data.job.can_start || data.job.can_resume" type="button" class="world-info-button is-primary" :disabled="!!data.busy" @click="controller.control(data.job, 'process')">{{ data.job.can_resume ? 'Resume processing' : (data.job.total_batches ?? 0) > 16 ? 'Start analysis' : 'Analyse source' }}</button>
          <button v-if="data.job.can_cancel" type="button" class="world-info-button" :disabled="!!data.busy" @click="controller.control(data.job, 'cancel')">Cancel processing</button>
          <button type="button" class="world-info-button" @click="controller.reviewRevision(data.job)">Review this version</button>
          <button type="button" class="world-info-button" @click="controller.previewSource()">View original source</button>
          <button type="button" class="world-info-button" @click="controller.openSource(data.source.source.id)">Refresh source</button>
          <button type="button" class="world-info-button is-danger" :disabled="!!data.busy" @click="emit('remove', data.source.source)">Delete source</button>
        </div>
        <section v-if="data.content" class="world-info-card" aria-label="Original source preview"><h4 class="mb-2 font-semibold">Original source · read only</h4><p class="mb-2 text-xs text-slate-400">Plain text. Links, images and embedded instructions are not executed.</p><pre tabindex="0" class="max-h-80 overflow-y-auto whitespace-pre-wrap break-words text-sm">{{ data.content.content }}</pre><p class="mt-3 text-xs text-slate-400">Characters {{ infoCount((data.content.offset ?? 0) + 1) }}–{{ infoCount((data.content.offset ?? 0) + Array.from(data.content.content).length) }} of {{ infoCount(data.content.total_characters ?? data.content.input_characters) }}</p><div class="mt-2 flex flex-wrap gap-2"><button type="button" class="world-info-button" :disabled="!(data.content.offset ?? 0)" @click="controller.previewSource(Math.max(0, (data.content.offset ?? 0) - 8000))">Previous source page</button><button type="button" class="world-info-button" :disabled="data.content.next_offset == null" @click="controller.previewSource(data.content.next_offset ?? 0)">Next source page</button></div></section>
      </div>
      <p v-else class="world-info-empty">Choose a source to inspect versions, processing progress and review results.</p>
    </section>
  </div>
</template>
