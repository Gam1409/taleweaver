<script setup lang="ts">
import { computed } from 'vue'
import type { ImagePromptRules, PromptTemplate } from '@/types/comfyui'

const props = defineProps<{ modelValue: ImagePromptRules | null; templates: PromptTemplate[] }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: ImagePromptRules | null): void }>()
const selected = computed(() => props.templates.find(t => t.id === props.modelValue?.template_id))
function selectTemplate(event: Event): void {
  const item = props.templates.find(t => t.id === (event.target as HTMLSelectElement).value)
  emit('update:modelValue', item ? { ...item.rules } : null)
}
function update<K extends keyof ImagePromptRules>(key: K, value: ImagePromptRules[K]): void {
  if (props.modelValue) emit('update:modelValue', { ...props.modelValue, [key]: value })
}
</script>

<template>
  <div class="space-y-4">
    <label class="block text-sm">Prompt template
      <select :value="modelValue?.template_id ?? ''" class="control" @change="selectTemplate">
        <option value="">Keep existing prompt behavior</option>
        <option v-for="item in templates" :key="item.id" :value="item.id">{{ item.name }}</option>
        <option v-if="modelValue?.template_id === 'custom'" value="custom">Custom rules</option>
      </select>
    </label>
    <p v-if="selected" class="text-xs text-slate-400">{{ selected.notes }} <a v-if="selected.source" :href="selected.source" target="_blank" rel="noopener noreferrer" class="text-cyan-300 underline">Model guidance</a></p>
    <p v-if="!modelValue" class="text-xs text-slate-400">Preserves the original TaleWeaver prompt construction. Select a template to adapt descriptions to your model.</p>
    <template v-if="modelValue">
      <label class="flex gap-2 items-start text-sm">
        <input type="checkbox" :checked="modelValue.adapt_with_llm" @change="update('adapt_with_llm', ($event.target as HTMLInputElement).checked)" />
        <span>Adapt descriptions with the Small / Utility LLM</span>
      </label>
      <p class="text-xs text-slate-400">Used for world generation and suggested prompts. Manually entered prompts keep your wording; required prefix and suffix are still added.</p>
      <details class="rounded-xl border border-slate-700 p-4">
        <summary class="cursor-pointer text-sm">Additional prompt rules</summary>
        <div class="mt-4 space-y-4">
          <label class="block text-sm">Output format<select :value="modelValue.format" class="control" @change="update('format', ($event.target as HTMLSelectElement).value as ImagePromptRules['format'])"><option value="description">Connected description</option><option value="tags">Comma-separated tags</option><option value="hybrid">Description and tags</option></select></label>
          <div class="grid sm:grid-cols-2 gap-4">
            <label class="block text-sm">Prompt language<input :value="modelValue.language" maxlength="80" class="control" @input="update('language', ($event.target as HTMLInputElement).value)" /></label>
            <label class="block text-sm">Target body word count<input type="number" min="10" max="300" :value="modelValue.max_words" class="control" @input="update('max_words', Number(($event.target as HTMLInputElement).value))" /></label>
          </div>
          <p class="text-xs text-slate-400">This guides the LLM; valid responses are not cut to this length. It is not the text encoder's token limit. Check your model and workflow.</p>
          <label class="block text-sm">Required prefix / trigger words<textarea :value="modelValue.prefix" maxlength="2000" rows="2" class="control" @input="update('prefix', ($event.target as HTMLTextAreaElement).value)" /></label>
          <label class="block text-sm">Required suffix<textarea :value="modelValue.suffix" maxlength="2000" rows="2" class="control" @input="update('suffix', ($event.target as HTMLTextAreaElement).value)" /></label>
          <label class="block text-sm">Additional negative prompt<textarea :value="modelValue.negative_prompt" maxlength="4000" rows="2" class="control" @input="update('negative_prompt', ($event.target as HTMLTextAreaElement).value)" /></label>
          <p class="text-xs text-slate-400">Appended to existing workflow conditioning only when a negative input is mapped. LoRA strength, CFG and denoise remain in the workflow.</p>
          <label class="block text-sm">Instructions for the prompt adapter<textarea :value="modelValue.instructions" maxlength="4000" rows="4" class="control" @input="update('instructions', ($event.target as HTMLTextAreaElement).value)" /></label>
        </div>
      </details>
    </template>
  </div>
</template>

<style scoped>
.control { @apply block mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 p-3 text-sm text-slate-100 focus:outline-cyan-400; }
</style>
