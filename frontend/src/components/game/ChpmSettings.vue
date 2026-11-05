<script setup lang="ts">
import { useChpmSettings } from '@/composables/useChpmSettings'

const props = defineProps<{ sessionId: string }>()
const { status, draft, busy, error, load, save } = useChpmSettings(() => props.sessionId)
defineExpose({ save })
</script>

<template>
  <details class="rounded-2xl border border-cyan-500/20 bg-slate-950/40 p-4">
    <summary class="cursor-pointer text-sm font-semibold text-cyan-200">NPC behavior · CHPM pilot</summary>
    <p class="mt-3 text-xs text-slate-400">Optional dialogue decisions for selected NPCs. Standard behavior remains the default.</p>
    <p v-if="error" role="alert" class="mt-3 text-sm text-red-300">{{ error }}</p>
    <button v-if="!status" type="button" :disabled="busy" class="mt-3 text-cyan-300" @click="load">{{ busy ? 'Loading…' : 'Retry loading' }}</button>
    <fieldset v-if="draft && status" :disabled="busy || !status.available" class="mt-4 space-y-4 disabled:opacity-60">
      <label class="block text-xs text-slate-300">Mode
        <select v-model="draft.mode" class="mt-1 w-full rounded-lg border border-slate-600 bg-slate-800 p-2">
          <option value="off">Standard — no extra requests</option>
          <option value="shadow">Observe — calculate decisions without changing replies</option>
          <option value="live">Enabled — validate dialogue before showing it</option>
        </select>
      </label>
      <template v-if="draft.mode !== 'off'">
        <p class="text-xs text-slate-400">This pilot chooses dialogue intentions, not world actions or a complete psychological simulation. Enabled mode waits for the full response and a model review. The reviewer can also make mistakes.</p>
        <fieldset class="space-y-2">
          <legend class="mb-2 text-xs text-slate-300">Characters (up to 3; only present NPCs are processed)</legend>
          <p v-if="!status.characters.length" class="text-xs text-slate-400">Meet a character before selecting them here.</p>
          <label v-for="actor in status.characters" :key="actor.id" class="flex items-center gap-2 text-sm text-slate-200">
            <input v-model="draft.actor_ids" type="checkbox" :value="actor.id" :disabled="draft.actor_ids.length >= 3 && !draft.actor_ids.includes(actor.id)" class="accent-cyan-400" />
            {{ actor.name }}
          </label>
        </fieldset>
        <label class="block text-xs text-slate-300">Use existing model configuration
          <select v-model="draft.model_role" class="mt-1 w-full rounded-lg border border-slate-600 bg-slate-800 p-2">
            <option value="complex">Complex model</option><option value="small">Small model</option>
          </select>
        </label>
        <p class="text-xs text-slate-400">No separate server is required. Enabled mode replaces dialogue planning for selected NPCs; Living World private decisions must be disabled.</p>
        <details class="rounded-lg border border-slate-700 p-3">
          <summary class="cursor-pointer text-xs text-slate-300">Request limits</summary>
          <div class="mt-3 grid grid-cols-2 gap-3 text-xs text-slate-300">
            <label>Requests per turn<input v-model.number="draft.max_calls_per_turn" type="number" min="1" max="8" class="mt-1 w-full rounded bg-slate-800 p-2" /></label>
            <label>Decision/review output tokens<input v-model.number="draft.max_output_tokens" type="number" min="512" max="2048" step="128" class="mt-1 w-full rounded bg-slate-800 p-2" /></label>
            <label class="col-span-2">Input size per request (characters, including instructions)<input v-model.number="draft.max_input_chars" type="number" min="8000" max="48000" step="1000" class="mt-1 w-full rounded bg-slate-800 p-2" /></label>
          </div>
          <p class="mt-2 text-xs text-slate-400">One proposal per present selected NPC; enabled mode adds a review. At most one repair and another review. A repair uses the Complex model with up to 4,096 output tokens. These are logical requests; provider retries may add cost.</p>
        </details>
      </template>
      <p class="text-xs text-amber-200/80">Changing mode or character selection restarts the pilot's private decision memory. Existing story events remain. Save between turns.</p>
    </fieldset>
    <div v-if="status && status.usage.status !== 'idle'" class="mt-4 text-xs text-slate-400" aria-live="polite">
      Last completed turn: {{ status.usage.status }} · {{ status.usage.calls }} requests · {{ status.usage.repairs }} repairs.<br />
      {{ status.usage.input_chars }} input / {{ status.usage.output_chars }} output characters (not token counts).
      <p v-if="status.usage.detail">{{ status.usage.detail }}</p>
    </div>
    <details v-if="status?.trace.length" class="mt-3 text-xs text-slate-400">
      <summary class="cursor-pointer">Administrator decision trace</summary>
      <pre class="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words">{{ JSON.stringify(status.trace, null, 2) }}</pre>
    </details>
  </details>
</template>
