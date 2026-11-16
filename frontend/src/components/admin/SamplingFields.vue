<script setup lang="ts">
import { computed } from 'vue'
import SamplingHelp from './SamplingHelp.vue'
import { SAMPLING_FIELDS, type SamplingProfile } from '@/services/llmSampling'

const props = defineProps<{ modelValue: SamplingProfile; provider: string; id: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: SamplingProfile] }>()
const local = computed(() => ['shared', 'ollama', 'custom_openai'].includes(props.provider))
const fields = computed(() =>
  SAMPLING_FIELDS.filter(
    field =>
      !field.local ||
      (local.value && (props.provider !== 'custom_openai' || props.modelValue.local_extensions))
  )
)
function update(key: keyof SamplingProfile, value: number | boolean | null) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}
</script>

<template>
  <div class="space-y-3">
    <p class="text-xs leading-relaxed text-slate-400">
      Blank means the provider's default. These controls change token selection, not NPC goals or
      permissions. Model support varies; some reasoning models restrict Temperature or Top P.
    </p>
    <label
      v-if="provider === 'shared' || provider === 'custom_openai'"
      class="flex items-start gap-2 text-xs text-slate-300"
    >
      <input
        type="checkbox"
        :checked="modelValue.local_extensions"
        class="mt-0.5 accent-purple-400"
        @change="update('local_extensions', ($event.target as HTMLInputElement).checked)"
      />
      Send local sampler extensions to compatible APIs (KoboldCpp / llama.cpp). Enable only when the
      server supports them. Ollama supports local sampler fields directly.
    </label>
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <div v-for="field in fields" :key="field.key" class="space-y-1.5">
        <div class="flex items-center justify-between gap-2">
          <label :for="`${id}-${field.key}`" class="text-xs text-slate-300">{{
            field.label
          }}</label>
          <SamplingHelp :id="`${id}-${field.key}-help`" :label="field.label" :text="field.help" />
        </div>
        <input
          :id="`${id}-${field.key}`"
          type="number"
          :min="field.min"
          :max="field.max"
          :step="field.step"
          :value="modelValue[field.key] ?? ''"
          placeholder="Provider default"
          class="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white invalid:border-rose-400"
          @input="
            update(
              field.key,
              ($event.target as HTMLInputElement).value === ''
                ? null
                : Number(($event.target as HTMLInputElement).value)
            )
          "
        />
      </div>
    </div>
    <p v-if="!local" class="text-xs text-slate-400">
      Top K, Min P and repetition penalty are local-server options and are not sent to this
      provider.
    </p>
  </div>
</template>
