<script setup lang="ts">
import { computed } from 'vue'
import { FilePenLine, Sparkles } from 'lucide-vue-next'
import type { WorldInfoController } from '@/composables/useWorldInfo'
import type { WorldInfoSourceDraft } from '@/types/worldInfo'
import { infoCount } from '@/services/worldInfoDisplay'

const props = defineProps<{ controller: WorldInfoController; modelValue: WorldInfoSourceDraft }>()
const emit = defineEmits<{ 'update:modelValue': [value: WorldInfoSourceDraft] }>()
const data = props.controller.data
const characters = computed(() => Array.from(props.modelValue.text).length)
const bytes = computed(() => new Blob([props.modelValue.text]).size)
const oversized = computed(() => !!data.state && (bytes.value > data.state.limits.max_source_bytes || characters.value > data.state.limits.max_source_characters))
const full = computed(() => !!data.state && data.state.sources.length >= data.state.limits.max_sources)
function update(patch: Partial<WorldInfoSourceDraft>) { emit('update:modelValue', { ...props.modelValue, ...patch }) }
async function analyse() {
  if (!props.modelValue.text.trim() || oversized.value || full.value || data.busy) return
  const submitted = { ...props.modelValue }
  const file = new File([submitted.text], 'written-entry.md', { type: 'text/markdown' })
  if (!await props.controller.upload(file, submitted.title)) return
  if (props.modelValue.title !== submitted.title || props.modelValue.text !== submitted.text) return
  const session = data.state?.session_id
  emit('update:modelValue', { title: '', text: '' })
  await props.controller.changeTab('files')
  if (data.state?.session_id === session) data.mobileDetail = true
}
</script>
<template>
  <form class="world-info-text-entry" aria-label="Create entries from text" @submit.prevent="analyse">
    <header class="world-info-text-heading"><FilePenLine class="h-5 w-5" aria-hidden="true" /><div><h3>Create from text</h3><p>Write or paste reference material. Your configured model will propose facts, groups and tags for review.</p></div></header>
    <fieldset :disabled="!data.state || !!data.busy" class="space-y-4">
      <label>Source title<input :value="modelValue.title" maxlength="200" placeholder="A name for these notes" @input="update({ title: ($event.target as HTMLInputElement).value })" /></label>
      <label>Source text<textarea :value="modelValue.text" required rows="12" placeholder="Describe a place, character, event or other knowledge for this session…" @input="update({ text: ($event.target as HTMLTextAreaElement).value })" /></label>
      <div class="world-info-text-counts"><span>{{ infoCount(characters) }} characters · {{ infoCount(bytes) }} UTF-8 bytes</span><span v-if="data.state">Up to {{ infoCount(data.state.limits.max_source_characters) }} characters / {{ infoCount(data.state.limits.max_source_bytes) }} bytes</span></div>
      <p v-if="oversized" role="alert" class="text-sm text-amber-200">Shorten the source text to the displayed limits before starting analysis.</p>
      <p v-if="full" role="alert" class="text-sm text-amber-200">The session source limit has been reached. Remove an unused source before adding new text.</p>
      <div class="world-info-text-submit"><button type="submit" class="world-info-button is-primary" :disabled="!modelValue.text.trim() || oversized || full"><Sparkles class="h-4 w-4" aria-hidden="true" />Analyse text</button><p>Text is saved as a new session source. Review and publish the resulting drafts before they become available to recall.</p></div>
      <p class="text-xs text-slate-400">Progress appears in Files & processing. Large sources wait for workload confirmation. The original text, quotations and normal session limits are preserved.</p>
    </fieldset>
  </form>
</template>
