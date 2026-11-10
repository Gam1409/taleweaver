<script setup lang="ts">
import { computed } from 'vue'
import SamplingHelp from './SamplingHelp.vue'
import { roleParallel, updateParallel, type ParallelSettings } from '@/services/llmParallel'
import type { LLMRole } from '@/services/llmRoleEndpoints'

const props = defineProps<{ modelValue: ParallelSettings; role: LLMRole }>()
const emit = defineEmits<{ 'update:modelValue': [value: ParallelSettings] }>()
const policy = computed(() => roleParallel(props.modelValue, props.role))
function enabled(event: Event) {
  emit(
    'update:modelValue',
    updateParallel(props.modelValue, props.role, {
      enabled: (event.target as HTMLInputElement).checked
    })
  )
}
function limit(event: Event) {
  emit(
    'update:modelValue',
    updateParallel(props.modelValue, props.role, {
      max_concurrent: Number((event.target as HTMLSelectElement).value)
    })
  )
}
</script>

<template>
  <div :data-parallel-role="role" class="space-y-2 rounded-xl border border-teal-700/40 p-3">
    <div class="flex flex-wrap items-center gap-3">
      <label
        :for="`parallel-${role}`"
        class="flex flex-1 items-center gap-2 text-xs text-slate-200"
      >
        <input
          :id="`parallel-${role}`"
          type="checkbox"
          :checked="policy.enabled"
          class="accent-teal-400"
          @change="enabled"
        />
        Allow parallel requests
      </label>
      <SamplingHelp
        :id="`parallel-${role}-help`"
        label="parallel requests"
        text="Allows independent analyses to overlap without changing prompts, output budgets or validation. Dependent stages still wait: narration follows NPC intentions, and world changes are applied sequentially. Roles on the same server share capacity; an exclusive role waits for the pool to empty. NPC Personality also uses the session's Concurrent NPC analyses limit. A server with one inference slot may become slower. Start with two and compare timings. This does not guarantee better decisions."
      />
      <label v-if="policy.enabled" :for="`parallel-${role}-limit`" class="text-xs text-slate-300">
        Maximum simultaneous requests
        <select
          :id="`parallel-${role}-limit`"
          :value="policy.max_concurrent"
          class="ml-2 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-white"
          @change="limit"
        >
          <option v-for="count in [2, 3, 4]" :key="count" :value="count">{{ count }}</option>
        </select>
      </label>
    </div>
    <p class="text-xs text-slate-400">
      Independent analyses only. NPC Personality also respects the session's concurrency limit. Save
      LLM settings to apply.
    </p>
    <p v-if="!Object.keys(modelValue.roles).length" class="text-xs text-slate-500">
      No connection policy saved yet; existing scheduling is preserved until you save.
      Saving with these boxes unchecked limits each server to one LLM request at a time.
    </p>
  </div>
</template>
