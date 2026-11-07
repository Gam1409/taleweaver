<script setup lang="ts">
import { computed } from 'vue'
import type { ChpmSettings } from '@/composables/useChpmSettings'

const props = defineProps<{
  modelValue?: ChpmSettings | null
  characters: { id: string; name: string }[]
}>()
const emit = defineEmits<{ 'update:modelValue': [value: ChpmSettings] }>()
const defaults: ChpmSettings = {
  mode: 'off',
  actor_ids: [],
  max_active_npcs: 3,
  model_role: 'complex',
  max_output_tokens: 1200,
  max_input_chars: 24000,
  max_calls_per_turn: 8,
  memory_limit: 12,
  agent_steps: 0,
  semantic_memory: false,
  failure_policy: 'continue'
}
const draft = computed(() => props.modelValue ?? defaults)
const minimum = computed(() =>
  draft.value.mode === 'off'
    ? 0
    : Math.min(draft.value.actor_ids.length, draft.value.max_active_npcs) *
        (1 + (draft.value.mode === 'live' ? (draft.value.agent_steps ?? 0) : 0)) +
      (draft.value.mode === 'live' ? 5 : 1)
)
const limits = [
  { key: 'max_active_npcs', label: 'Active NPCs per turn', min: 1, max: 20 },
  { key: 'max_calls_per_turn', label: 'Requests per turn', min: 1, max: 25 },
  { key: 'max_output_tokens', label: 'Analysis output tokens', min: 512, max: 8192 },
  { key: 'max_input_chars', label: 'Input characters per request', min: 8000, max: 192000 },
  { key: 'memory_limit', label: 'Remembered quotations per NPC', min: 0, max: 24 }
] as const
function update<K extends keyof ChpmSettings>(key: K, value: ChpmSettings[K]) {
  emit('update:modelValue', { ...draft.value, actor_ids: [...draft.value.actor_ids], [key]: value })
}
function selectActor(id: string, selected: boolean) {
  update(
    'actor_ids',
    selected ? [...draft.value.actor_ids, id] : draft.value.actor_ids.filter(value => value !== id)
  )
}
</script>

<template>
  <section class="space-y-5 rounded-2xl border border-cyan-400/20 bg-slate-950/40 p-5">
    <div>
      <h3 class="text-lg font-bold text-cyan-200">NPC Personality</h3>
      <p class="mt-2 text-sm text-slate-400">
        Character decisions, witnessed memory and gradual changes grounded in each NPC's own values.
        Optional; extra analysis adds requests and waiting.
      </p>
    </div>
    <label class="block text-sm text-slate-200"
      >Default mode for new VN sessions
      <select
        :value="draft.mode"
        class="mt-2 w-full rounded-lg bg-slate-800 p-2"
        @change="update('mode', ($event.target as HTMLSelectElement).value as ChpmSettings['mode'])"
      >
        <option value="off">Standard — no extra requests</option>
        <option value="shadow">Observe — inspect decisions without changing replies</option>
        <option value="live">Enabled — guide and review NPC dialogue</option>
      </select>
    </label>
    <template v-if="draft.mode !== 'off'">
      <fieldset class="space-y-2">
        <legend class="mb-2 text-sm font-bold text-slate-200">Character roster</legend>
        <p v-if="!characters.length" class="text-sm text-amber-200">
          Add NPCs to this adventure before enabling Personality.
        </p>
        <label
          v-for="actor in characters"
          :key="actor.id"
          class="flex items-center gap-3 text-sm text-slate-300"
        >
          <input
            type="checkbox"
            :checked="draft.actor_ids.includes(actor.id)"
            :disabled="draft.actor_ids.length >= 20 && !draft.actor_ids.includes(actor.id)"
            @change="selectActor(actor.id, ($event.target as HTMLInputElement).checked)"
          />
          {{ actor.name }}
        </label>
        <p v-if="!draft.actor_ids.length" role="alert" class="text-xs text-amber-200">
          Choose at least one NPC before saving an enabled mode.
        </p>
      </fieldset>
      <div class="grid gap-4 sm:grid-cols-2">
        <label class="text-sm text-slate-200"
          >Analysis model
          <select
            :value="draft.model_role"
            class="mt-2 w-full rounded-lg bg-slate-800 p-2"
            @change="
              update(
                'model_role',
                ($event.target as HTMLSelectElement).value as ChpmSettings['model_role']
              )
            "
          >
            <option value="complex">Complex model</option>
            <option value="small">Small model</option>
          </select>
        </label>
        <label v-if="draft.mode === 'live'" class="text-sm text-slate-200"
          >On analysis failure
          <select
            :value="draft.failure_policy ?? 'continue'"
            class="mt-2 w-full rounded-lg bg-slate-800 p-2"
            @change="
              update(
                'failure_policy',
                ($event.target as HTMLSelectElement).value as ChpmSettings['failure_policy']
              )
            "
          >
            <option value="continue">Keep playing (recommended)</option>
            <option value="strict">Strict — stop for inspection</option>
          </select>
        </label>
      </div>
      <p class="text-xs text-slate-400">
        Deeply process active interlocutors; other selected characters retain their state. Enabled
        dialogue waits for review before display. Living World private decisions must be disabled.
      </p>
      <details class="rounded-xl border border-slate-700 p-4">
        <summary class="cursor-pointer text-sm text-slate-200">
          Request limits & agent lookups
        </summary>
        <label v-if="draft.mode === 'live'" class="mb-3 mt-4 block text-xs text-slate-300">
          <input type="checkbox" :checked="draft.semantic_memory ?? false" class="mr-2 accent-cyan-400" @change="update('semantic_memory', ($event.target as HTMLInputElement).checked)" />
          Semantic NPC memory (experimental)
          <span class="mt-2 block text-slate-400">Uses the administrator's embeddings with observer-scoped history and lexical fallback. No additional generative model request; disabled by default.</span>
        </label>
        <div class="mt-4 grid gap-4 sm:grid-cols-2">
          <label v-for="field in limits" :key="field.key" class="text-xs text-slate-300"
            >{{ field.label
            }}<input
              type="number"
              :value="draft[field.key]"
              :min="field.min"
              :max="field.max"
              class="mt-2 w-full rounded-lg bg-slate-800 p-2"
              @input="update(field.key, Number(($event.target as HTMLInputElement).value))"
          /></label>
          <label v-if="draft.mode === 'live'" class="text-xs text-slate-300"
            >Read-only agent rounds per active NPC<select
              :value="draft.agent_steps ?? 0"
              class="mt-2 w-full rounded-lg bg-slate-800 p-2"
              @change="update('agent_steps', Number(($event.target as HTMLSelectElement).value))"
            >
              <option :value="0">Off</option>
              <option :value="1">Up to one round</option>
              <option :value="2">Up to two rounds</option>
            </select></label
          >
        </div>
        <p
          class="mt-4 text-xs"
          :class="draft.max_calls_per_turn < minimum ? 'text-amber-200' : 'text-slate-400'"
        >
          Minimum request budget: {{ minimum }}, including repair reserve. Ordinary narration is
          additional. Several active NPCs can take minutes on local models.
        </p>
      </details>
    </template>
    <p class="text-xs text-amber-200">
      Save the adventure to apply defaults to new sessions only. Existing sessions keep their own
      settings and psychological history.
    </p>
  </section>
</template>
