<script setup lang="ts">
import { computed } from 'vue'
import CustomOpenAIRoleSettings from './CustomOpenAIRoleSettings.vue'
import OllamaRoleSettings from './OllamaRoleSettings.vue'
import LlmSamplingSettings from './LlmSamplingSettings.vue'
import SamplingHelp from './SamplingHelp.vue'
import { normalizeSampling, type SamplingSettings } from '@/services/llmSampling'
import type { LLMRole } from '@/services/llmRoleEndpoints'

const props = defineProps<{
  form: Record<string, unknown>
  role: LLMRole
  customLoading: boolean
  customModels?: string[]
  ollamaLoading: boolean
  ollamaModels?: string[]
}>()
const emit = defineEmits<{
  change: [value: Record<string, unknown>]
  refreshCustom: []
  refreshOllama: []
}>()
const provider = computed(() => String(props.form[`${props.role}_model_provider`] || 'openai'))
const sampling = computed(() =>
  normalizeSampling(props.form.sampling as SamplingSettings | undefined)
)
const thinking = computed(() => ['small', 'complex', 'generator'].includes(props.role))
function change(field: string, value: unknown) {
  emit('change', { [field]: value })
}
function text(field: string): string {
  return String(props.form[field] || '')
}
function number(field: string): number | null {
  return typeof props.form[field] === 'number' ? (props.form[field] as number) : null
}
function numeric(field: string, event: Event) {
  const value = (event.target as HTMLInputElement).value
  change(field, value === '' ? null : Number(value))
}
</script>

<template>
  <details :data-generation-role="role" class="rounded-xl border border-purple-700/40 p-4">
    <summary class="cursor-pointer text-xs font-bold text-purple-300">Generation settings</summary>
    <div class="mt-4 space-y-4">
      <div class="grid gap-4 sm:grid-cols-2">
        <div v-if="role !== 'play_agent'" class="space-y-1.5">
          <div class="flex items-center justify-between">
            <label :for="`generation-${role}-tokens`" class="text-xs text-slate-300"
              >Max generation tokens</label
            >
            <SamplingHelp
              :id="`generation-${role}-tokens-help`"
              label="output token limit"
              text="Maximum generated tokens for this role, not the size of the input context. A small limit can cut off prose or JSON; a large limit allows longer generation and can increase latency and cost. Thinking has a separate configured budget where supported."
            />
          </div>
          <input
            :id="`generation-${role}-tokens`"
            type="number"
            min="512"
            :max="role === 'generator' ? 131072 : 65536"
            :value="number(`${role}_max_tokens`)"
            class="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white"
            @input="numeric(`${role}_max_tokens`, $event)"
          />
        </div>
        <label v-if="provider === 'openrouter'" class="block text-xs text-slate-300"
          >OpenRouter provider routing
          <input
            :value="text(`${role}_openrouter_provider`)"
            type="text"
            placeholder="Optional provider order"
            class="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white"
            @input="
              change(`${role}_openrouter_provider`, ($event.target as HTMLInputElement).value)
            "
          />
        </label>
      </div>
      <div
        v-if="thinking"
        class="flex flex-wrap items-center gap-3 rounded-lg border border-slate-700 p-3"
      >
        <label class="flex flex-1 items-center gap-2 text-xs text-slate-300"
          ><input
            type="checkbox"
            :checked="!!form[`${role}_enable_thinking`]"
            class="accent-purple-400"
            @change="change(`${role}_enable_thinking`, ($event.target as HTMLInputElement).checked)"
          />Reasoning / thinking</label
        >
        <SamplingHelp
          :id="`generation-${role}-thinking-help`"
          label="reasoning mode"
          text="Requests internal reasoning from models and providers that support it. It can help planning and consistency, but consumes tokens and delays visible output. It is separate from the fictional character thoughts displayed in the story."
        />
        <label v-if="form[`${role}_enable_thinking`]" class="text-xs text-slate-300"
          >Thinking budget
          <input
            :value="number(`${role}_max_thinking_tokens`)"
            type="number"
            min="256"
            max="32768"
            class="ml-2 w-24 rounded-lg bg-slate-950 px-2 py-1 text-white"
            @input="numeric(`${role}_max_thinking_tokens`, $event)"
        /></label>
      </div>
      <LlmSamplingSettings
        embedded
        :model-value="sampling"
        :role="role"
        :provider="provider"
        @update:model-value="change('sampling', $event)"
      />
      <CustomOpenAIRoleSettings
        v-if="provider === 'custom_openai'"
        embedded
        :role="role"
        :url="text(`${role}_custom_openai_url`)"
        :global-url="text('custom_openai_url')"
        :loading="customLoading"
        :models="customModels"
        @update:url="change(`${role}_custom_openai_url`, $event)"
        @refresh="emit('refreshCustom')"
      />
      <OllamaRoleSettings
        v-if="provider === 'ollama'"
        embedded
        :role="role"
        :url="text(`${role}_ollama_url`)"
        :timeout="number(`${role}_ollama_timeout`)"
        :num-ctx="number(`${role}_ollama_num_ctx`)"
        :global-url="text('ollama_url')"
        :loading="ollamaLoading"
        :models="ollamaModels"
        @update:url="change(`${role}_ollama_url`, $event)"
        @update:timeout="change(`${role}_ollama_timeout`, $event)"
        @update:num-ctx="change(`${role}_ollama_num_ctx`, $event)"
        @refresh="emit('refreshOllama')"
      />
    </div>
  </details>
</template>
