<script setup lang="ts">
import { useChpmSettings } from '@/composables/useChpmSettings'

const props = defineProps<{ sessionId: string }>()
const { status, draft, busy, error, minimumCalls, budgetWarning, historyWarnings, selectStandard, load, save } = useChpmSettings(() => props.sessionId)
defineExpose({ save })
</script>

<template>
  <details class="rounded-2xl border border-cyan-500/20 bg-slate-950/40 p-4">
    <summary class="cursor-pointer text-sm font-semibold text-cyan-200">NPC Personality <span v-if="status?.module_version">v{{ status.module_version }}</span> <span v-if="historyWarnings.length || budgetWarning" class="text-amber-300">· Needs attention</span></summary>
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
        <label v-if="draft.mode === 'live'" class="block text-xs text-slate-300">If NPC analysis fails
          <select v-model="draft.failure_policy" class="mt-1 w-full rounded-lg border border-slate-600 bg-slate-800 p-2">
            <option value="continue">Keep playing — temporarily use standard RP (recommended)</option>
            <option value="strict">Strict — stop the turn for inspection</option>
          </select>
          <span class="mt-2 block text-slate-400">Keep playing preserves the last confirmed personality and records unreviewed turns. A rejected reply gets at most one new narrator response; an unavailable reviewer can leave an explicitly unreviewed reply. Repeated analysis failures pause NPC Personality for three completed turns. Session and save errors still stop safely.</span>
        </label>
        <p class="text-xs text-slate-400">This optional module chooses dialogue intentions, not world actions or a complete psychological simulation. Enabled mode waits for the full response and a model review, with the selected recovery policy if analysis fails. The reviewer can also make mistakes.</p>
        <div v-if="historyWarnings.length" role="alert" class="space-y-2 rounded-lg border border-amber-500/40 bg-amber-950/20 p-3 text-xs text-amber-200">
          <p v-for="item in historyWarnings" :key="item.id">{{ item.name }}: {{ item.status === 'pause_required' ? 'NPC Personality needs a pause before the next turn' : 'Psychological history is approaching capacity' }} — {{ item.used.events }}/{{ item.limits.events }} events, {{ item.used.beliefs }}/{{ item.limits.beliefs }} beliefs. <span v-if="item.active_events !== undefined">{{ item.active_events }} active / {{ item.archived_events }} archived events.</span> <span v-if="item.used.experiences !== undefined">{{ item.used.experiences }}/{{ item.limits.experiences }} affect/need dimensions.</span></p>
          <p>Older events move to an exact archive; total storage is finite. When a complete turn cannot fit, Keep playing uses standard RP and Strict pauses before model requests. Nothing is discarded. You can also select Standard and save, or deselect affected NPCs. Original identity and psychological history stay saved; re-enabling does not clear the limit.</p>
          <button type="button" class="rounded border border-amber-300/50 px-3 py-2 font-semibold" @click="selectStandard">Select Standard (save to apply)</button>
        </div>
        <fieldset class="space-y-2">
          <legend class="mb-2 text-xs text-slate-300">Character roster (up to 20; absent NPCs retain their saved psychology)</legend>
          <p v-if="!status.characters.length" class="text-xs text-slate-400">Meet a character before selecting them here.</p>
          <label v-for="actor in status.characters" :key="actor.id" class="flex items-center gap-2 text-sm text-slate-200">
            <input v-model="draft.actor_ids" type="checkbox" :value="actor.id" :disabled="draft.actor_ids.length >= 20 && !draft.actor_ids.includes(actor.id)" class="accent-cyan-400" />
            {{ actor.name }}
          </label>
        </fieldset>
        <label class="block text-xs text-slate-300">Active NPCs per turn
          <input v-model.number="draft.max_active_npcs" type="number" min="1" max="20" class="mt-1 w-full rounded-lg border border-slate-600 bg-slate-800 p-2" />
        </label>
        <p class="text-xs text-slate-400">Default: 3. In larger casts, process direct participants without filling spare places. With no direct participants, keep the current conversation; choose another group when its participants leave. Inactive characters keep their state and do not receive new dialogue or psychological updates. If direct participants exceed this limit, Keep playing uses standard RP and Strict stops for inspection. Set 20 to process every present selected NPC, and raise the request budget accordingly. Attribution is model-based and can be mistaken.</p>
        <p v-if="draft.actor_ids.length > 3" role="status" class="text-xs text-amber-200">Large casts need larger shared perception/review responses. Check input and output limits before live use. Twenty active NPCs require 25 NPC Personality requests with agent lookups off including the repair reserve, plus the narrator; this can take many minutes. Unused reserve is not spent.</p>
        <p v-if="draft.mode === 'live' && draft.actor_ids.length >= 2" role="status" class="rounded-lg border border-amber-500/30 p-3 text-xs text-amber-200">Selected NPCs are processed sequentially. With several NPCs and a slow local model, a turn can take several minutes. Text appears only after the full narration is reviewed; it does not stream while being generated. A repair adds more waiting. Actual time depends on the model and context.</p>
        <label class="block text-xs text-slate-300">Use existing model configuration
          <select v-model="draft.model_role" class="mt-1 w-full rounded-lg border border-slate-600 bg-slate-800 p-2">
            <option value="complex">Complex model</option><option value="small">Small model</option>
          </select>
        </label>
        <p class="text-xs text-slate-400">No separate server is required. Enabled mode replaces dialogue planning for selected NPCs; Living World private decisions must be disabled.</p>
        <label v-if="draft.mode === 'live'" class="block text-xs text-slate-300">
          <input v-model="draft.semantic_memory" type="checkbox" class="mr-2 accent-cyan-400" />
          Semantic NPC memory (experimental)
          <span class="mt-2 block text-slate-400">Requires administrator Memory &amp; recall settings. Combines semantic and exact-word search within each NPC's witnessed sources. Uses one bounded embeddings batch for active NPCs; no extra generative model request. Falls back to lexical memory when unavailable. Disabled by default.</span>
        </label>
        <label v-if="draft.mode === 'live'" class="block text-xs text-slate-300">Agent lookups per active NPC
          <select v-model.number="draft.agent_steps" class="mt-1 w-full rounded-lg border border-slate-600 bg-slate-800 p-2">
            <option :value="0">Off — existing decision flow</option>
            <option :value="1">Up to 1 lookup round</option>
            <option :value="2">Up to 2 rounds — can refine a search or read a result</option>
          </select>
          <span class="mt-2 block text-slate-400">Optional, read-only lookups scoped to this session and NPC. Searches known history, checks own possessions, and reads visible clothing layers of present NPCs. Each round adds one model request with up to two local tool reads; the model can stop early. Hidden inventories are unavailable. Lexical memory search may miss paraphrases. Increase the request budget below when enabling. With the 25-call cap, use at most 10 active NPCs for one round, or 6 for two rounds.</span>
        </label>
        <p v-if="budgetWarning" role="alert" class="text-xs text-amber-200">Increase Requests per turn to at least {{ minimumCalls }} before saving. Enabled mode reserves agent rounds, one shared proposal retry plus two requests for narration repair and repeat review.</p>
        <details class="rounded-lg border border-slate-700 p-3">
          <summary class="cursor-pointer text-xs text-slate-300">Request limits</summary>
          <div class="mt-3 grid grid-cols-2 gap-3 text-xs text-slate-300">
            <label>Requests per turn<input v-model.number="draft.max_calls_per_turn" type="number" :min="Math.max(1, minimumCalls)" max="25" class="mt-1 w-full rounded bg-slate-800 p-2" /></label>
            <label>Decision/review output tokens<input v-model.number="draft.max_output_tokens" type="number" min="512" max="8192" step="128" class="mt-1 w-full rounded bg-slate-800 p-2" /></label>
            <label class="col-span-2">Input size per request (characters, including instructions)<input v-model.number="draft.max_input_chars" type="number" min="8000" max="192000" step="1000" class="mt-1 w-full rounded bg-slate-800 p-2" /></label>
            <label class="col-span-2">Remembered observations per NPC<input v-model.number="draft.memory_limit" type="number" min="0" max="24" class="mt-1 w-full rounded bg-slate-800 p-2" /></label>
          </div>
          <p class="mt-2 text-xs text-slate-400">One shared perception request, then one proposal per present selected NPC; enabled mode adds a review and reserves one shared proposal retry plus two calls for narration repair and another review. Minimum for this selection: {{ minimumCalls }}. Reserved calls are used only if needed. A repair uses the Complex model with up to 4,096 output tokens. The ordinary narrator request is separate from this NPC Personality budget. These are logical requests; provider retries may add cost.</p>
          <p class="mt-2 text-xs text-slate-400">The dialogue window retains source-checked quotations. Set it to 0 to disable that window. Enabled NPC Personality separately retains exact psychological history: up to 256 active events and 8,192 total archived and active events per NPC. Its appraisal keeps current observed fragments, a bounded recent window and up to three short older fragments retrieved by matching perceived words. This is lexical recall, not guaranteed semantic recall. Edited or removed sources invalidate their dependent history.</p>
          <p class="mt-2 text-xs text-slate-400">Declared goals and promises have a separate source-checked ledger: up to 8 active entries per NPC, 256 records per session. Enabled mode records selected changes only after speech review. Observe mode does not change this ledger. No additional model request is needed.</p>
          <p class="mt-2 text-xs text-slate-400">Enabled mode can record qualitative affect and need appraisals with current evidence. These are tentative states, not diagnoses or personality edits. After 30 game minutes without reassessment, current intensity is marked unknown; time does not automatically heal feelings or restore trust.</p>
        </details>
      </template>
      <p class="text-xs text-amber-200/80">Changing mode or character selection restarts the pilot's private decision memory. Recorded goals, promises and story events remain. Standard mode pauses ledger updates; sources are checked again when enabled. Save between turns.</p>
      <p class="text-xs text-slate-400">The first successfully reviewed enabled turn pins the NPC's original character, traits and goal. Later card edits do not replace this psychological identity. Dated experiences can support tentative conversational habits, relationship expectations and gradual trait tendencies; counterevidence remains visible. These qualifications do not rewrite the card or erase its values. Consolidation is deferred if its optional context cannot fit. This is not a validated clinical simulation or numerical personality model.</p>
    </fieldset>
    <p v-if="status?.agenda_counts" class="mt-3 text-xs text-slate-400">Recorded agenda: {{ status.agenda_counts.active }} active · {{ status.agenda_counts.closed }} closed (last saved state; completion reports are not verified world outcomes).</p>
    <div v-if="status && status.usage.status !== 'idle'" class="mt-4 text-xs text-slate-400" aria-live="polite">
      Last completed turn: {{ status.usage.simplified ? 'Simplified RP' : status.usage.status }} · {{ status.usage.calls }} requests · {{ status.usage.repairs }} repairs.<br />
      <p v-if="status.usage.fallback_requests">Additional ordinary narrator requests: {{ status.usage.fallback_requests }} (at most one).</p>
      <p v-if="status.continuation?.unreviewed_turns">{{ status.continuation.unreviewed_turns }} recent turns continued without confirmed psychological updates. Current host facts will be refreshed; unreviewed dialogue is not silently added to psychological memory.</p>
      {{ status.usage.input_chars }} input / {{ status.usage.output_chars }} output characters (not token counts).
      <p v-if="status.usage.memory_evictions">{{ status.usage.memory_evictions }} older quotations left the memory window this turn.</p>
      <p v-if="status.usage.proposal_repairs">Proposal retries: {{ status.usage.proposal_repairs }}</p>
      <p v-for="(feedback, index) in status.usage.proposal_feedback ?? []" :key="index">{{ feedback }}</p>
      <p v-if="status.usage.detail">{{ status.usage.detail }}</p>
    </div>
    <section v-if="status?.last_proposal_failure && status.last_proposal_failure.source !== 'current_turn'" aria-label="Previous NPC proposal failure" class="mt-3 space-y-2 rounded-lg border border-amber-500/30 bg-amber-950/20 p-3 text-xs text-amber-100">
      <h4 class="font-semibold">Most recent rejected NPC proposal</h4>
      <p>Validation feedback from an earlier failed turn. The current turn may be paused and show zero analysis requests.</p>
      <p v-for="(feedback, index) in status.last_proposal_failure.proposal_feedback" :key="index" class="whitespace-pre-wrap break-words">{{ feedback }}</p>
      <p v-if="status.last_proposal_failure.source === 'previous_turn_snapshot'" class="text-amber-200/70">Read from the previous turn snapshot; game state is unchanged.</p>
    </section>
    <details v-if="status && (status.trace.length || status.agenda?.length)" class="mt-3 text-xs text-slate-400">
      <summary class="cursor-pointer">Administrator decision trace</summary>
      <pre class="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words">{{ JSON.stringify(status.trace, null, 2) }}</pre>
      <pre class="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words">{{ JSON.stringify(status.memory, null, 2) }}</pre>
      <pre class="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words">{{ JSON.stringify(status.agenda, null, 2) }}</pre>
    </details>
  </details>
</template>
