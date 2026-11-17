<script setup lang="ts">
import { computed } from 'vue'
import type { ChpmSettings } from '@/composables/useChpmSettings'

const props = defineProps<{
  modelValue?: ChpmSettings | null
  characters: { id: string; name: string }[]
  hostMode?: 'vn' | 'rpg' | 'story' | 'chat'
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
  notebook_enabled: false,
  action_tools: false,
  tool_protocol: 'auto',
  workflow: 'staged',
  semantic_memory: false,
  failure_policy: 'continue'
}
const draft = computed(() => props.modelValue ?? defaults)
const isCombatControl = computed(() => props.hostMode === 'rpg')
const minimum = computed(() =>
  draft.value.mode === 'off'
    ? 0
    : isCombatControl.value
      ? 3 * Math.min(draft.value.actor_ids.length, draft.value.max_active_npcs) * (draft.value.agent_steps ?? 0)
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
const visibleLimits = computed(() => isCombatControl.value ? limits.filter(field => field.key !== 'memory_limit') : limits)
function update<K extends keyof ChpmSettings>(key: K, value: ChpmSettings[K], extra: Partial<ChpmSettings> = {}) {
  emit('update:modelValue', { ...draft.value, actor_ids: [...draft.value.actor_ids], [key]: value, ...extra })
}
function setNotebookEnabled(enabled: boolean) {
  update('notebook_enabled', enabled, enabled ? { agent_steps: Math.max(1, draft.value.agent_steps ?? 0) } : {})
}
function setWorkflow(workflow: 'staged' | 'integrated') {
  update('workflow', workflow, workflow === 'integrated' ? { max_input_chars: Math.max(48000, draft.value.max_input_chars) } : draft.value.action_tools ? { action_tools: false } : {})
}
function setActionToolsEnabled(enabled: boolean) {
  update('action_tools', enabled, enabled ? {
    workflow: 'integrated',
    agent_steps: Math.max(1, draft.value.agent_steps ?? 0),
    max_input_chars: Math.max(48000, draft.value.max_input_chars)
  } : {})
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
      <h3 class="text-lg font-bold text-cyan-200">{{ isCombatControl ? 'NPC combat actions' : 'NPC Personality' }}</h3>
      <p v-if="isCombatControl" class="mt-2 text-sm text-slate-400">Selected NPCs choose authored abilities on their own combat turn. The engine validates costs, targets and results. The player's choices stay theirs.</p>
      <p v-else class="mt-2 text-sm text-slate-400">
        Character decisions, witnessed memory and gradual changes grounded in each NPC's own values.
        Optional; extra analysis adds requests and waiting.
      </p>
    </div>
    <label class="block text-sm text-slate-200"
      >{{ isCombatControl ? 'Default combat action control for new RPG sessions' : 'Default mode for new VN sessions' }}
      <select
        :value="draft.mode"
        class="mt-2 w-full rounded-lg bg-slate-800 p-2"
        @change="update('mode', ($event.target as HTMLSelectElement).value as ChpmSettings['mode'])"
      >
        <option value="off">Standard — no extra requests</option>
        <option v-if="!isCombatControl || draft.mode === 'shadow'" value="shadow" :disabled="isCombatControl">Observe — inspect decisions without changing replies</option>
        <option value="live">{{ isCombatControl ? 'Enabled — choose combat abilities' : 'Enabled — guide and review NPC dialogue' }}</option>
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
        <label v-if="!isCombatControl && draft.mode === 'live'" class="text-sm text-slate-200"
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
      <p v-if="isCombatControl" class="text-xs text-slate-400">Combat control uses existing authored abilities. Dialogue personality, private notebooks and psychological memory are available only in VN sessions. Their saved preferences are retained.</p>
      <p v-else class="text-xs text-slate-400">
        Deeply process active interlocutors; other selected characters retain their state. Enabled
        dialogue waits for review before display. Living World private decisions must be disabled.
      </p>
      <details class="rounded-xl border border-slate-700 p-4">
        <summary class="cursor-pointer text-sm text-slate-200">
          Request limits & agent lookups
        </summary>
        <label v-if="!isCombatControl && draft.mode === 'live'" class="mb-3 mt-4 block text-xs text-slate-300">
          <input type="checkbox" :checked="draft.semantic_memory ?? false" class="mr-2 accent-cyan-400" @change="update('semantic_memory', ($event.target as HTMLInputElement).checked)" />
          Semantic NPC memory (experimental)
          <span class="mt-2 block text-slate-400">Uses the administrator's embeddings with observer-scoped history and lexical fallback. No additional generative model request; disabled by default.</span>
        </label>
        <label v-if="!isCombatControl && draft.mode === 'live'" class="mb-3 block text-xs text-slate-300">
          <input name="npc-private-notebooks" type="checkbox" :checked="draft.notebook_enabled ?? false" class="mr-2 accent-cyan-400" @change="setNotebookEnabled(($event.target as HTMLInputElement).checked)" />
          Private NPC notebooks
          <span class="mt-2 block text-slate-400">One freely organized JSON notebook per NPC, up to 16,000,000 UTF-8 bytes each. Notes are subjective and may be mistaken. The latest notes stay after Undo or Chronicles restore; no notebook history is kept. Disabled by default. Enabling selects at least one agent tool round and uses the existing request budget.</span>
        </label>
        <div class="mt-4 grid gap-4 sm:grid-cols-2">
          <label v-for="field in visibleLimits" :key="field.key" class="text-xs text-slate-300"
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
            >Agent tool rounds per active NPC<select
              name="npc-agent-tool-rounds"
              :value="draft.agent_steps ?? 0"
              class="mt-2 w-full rounded-lg bg-slate-800 p-2"
              @change="update('agent_steps', Number(($event.target as HTMLSelectElement).value))"
            >
              <option :value="0" :disabled="draft.notebook_enabled || draft.action_tools">Off</option>
              <option :value="1">Up to one round</option>
              <option :value="2">Up to two rounds</option>
              <option :value="3">Up to three rounds — can correct and check</option>
            </select></label
          >
        </div>
        <label v-if="draft.mode === 'live'" class="mt-4 block text-xs text-slate-300">NPC decision workflow
          <select name="npc-decision-workflow" :value="draft.workflow ?? 'staged'" class="mt-2 w-full rounded-lg bg-slate-800 p-2" @change="setWorkflow(($event.target as HTMLSelectElement).value as 'staged' | 'integrated')">
            <option value="staged" :disabled="isCombatControl">Staged — memory tools, then decision (default)</option>
            <option value="integrated">Integrated — tools or decision (experimental)</option>
          </select>
          <span v-if="isCombatControl" class="mt-2 block text-slate-400">Combat action control requires Integrated and at least one tool round. Selecting Integrated sets the input budget to at least 48,000 characters and keeps larger limits.</span>
          <span v-else class="mt-2 block text-slate-400">With enabled tool rounds, Integrated can submit the validated decision without a separate readiness call. Selecting it sets the input budget to at least 48,000 characters and keeps larger limits. Existing sessions keep their saved workflow.</span>
        </label>
        <label v-if="draft.mode === 'live'" class="mt-4 block text-xs text-slate-300">
          <input name="npc-world-actions" type="checkbox" :checked="draft.action_tools ?? false" class="mr-2 accent-cyan-400" @change="setActionToolsEnabled(($event.target as HTMLInputElement).checked)" />
          {{ isCombatControl ? 'Combat action control (experimental)' : 'NPC world actions (experimental)' }}
          <span v-if="isCombatControl" class="mt-2 block text-slate-400">NPCs choose existing authored abilities; the combat engine applies valid results. Enabling selects Integrated and at least one tool round.</span>
          <span v-else class="mt-2 block text-slate-400">NPCs choose their own actions; the engine validates changes to the world. The player's choices stay theirs. Enabling selects Integrated and at least one tool round.</span>
        </label>
        <p v-if="isCombatControl && (!draft.action_tools || draft.workflow !== 'integrated' || !draft.agent_steps)" role="alert" class="mt-3 text-xs text-amber-200">Enable combat action control before saving, or select Standard.</p>
        <label v-if="draft.mode === 'live' && (draft.notebook_enabled || draft.workflow === 'integrated')" class="mt-4 block text-xs text-slate-300">{{ draft.action_tools ? 'Agent tool compatibility' : 'Memory tool compatibility' }}
          <select name="npc-memory-tool-protocol" :value="draft.tool_protocol ?? 'auto'" class="mt-2 w-full rounded-lg bg-slate-800 p-2" @change="update('tool_protocol', ($event.target as HTMLSelectElement).value as 'auto' | 'native' | 'json')">
            <option value="auto">Automatic</option>
            <option value="native">Native function calls</option>
            <option value="json">JSON compatibility</option>
          </select>
          <span v-if="isCombatControl" class="mt-2 block text-slate-400">Choose JSON compatibility for a server without native tools. Both modes keep the same ability catalog and request limits.</span>
          <span v-else class="mt-2 block text-slate-400">Choose JSON compatibility for a server without native tools. Both modes keep the same private notebook and request limits; uncertain requests are never automatically repeated.</span>
        </label>
        <p v-if="isCombatControl && draft.mode === 'live'" class="mt-3 text-xs text-slate-400">Each tool round allows one request per NPC combat turn to choose an available ability or keep standard combat AI. Invalid choices can be corrected within remaining rounds; the model can finish early.</p>
        <p v-else-if="draft.mode === 'live'" class="mt-3 text-xs text-slate-400">
          Each round adds one model request per active NPC and up to two local tool operations.
          Tools read this NPC's witnessed history and host observations; enabled notebooks also allow
          edits to its own private notes. Other NPCs' notes remain private.
          <span v-if="draft.action_tools">World actions use these rounds too and remain subject to engine checks.</span>
          <span v-else>Memory tools cannot change world state.</span>
          Disabling optional tools keeps the selected rounds; set rounds to Off to stop these extra requests.
        </p>
        <p
          class="mt-4 text-xs"
          :class="draft.max_calls_per_turn < minimum ? 'text-amber-200' : 'text-slate-400'"
        >
          Minimum request budget: {{ minimum }}<span v-if="isCombatControl">, reserving up to three combat turns per selected active NPC per player command, multiplied by tool rounds. Unused turns and rounds are not spent.</span><span v-else>, including repair reserve.</span> Ordinary narration is
          additional. Several active NPCs can take minutes on local models.
        </p>
      </details>
    </template>
    <p class="text-xs text-amber-200">
      Save the adventure to apply defaults to new sessions only. Existing sessions keep their own
      {{ isCombatControl ? 'combat settings.' : 'settings and psychological history.' }}
    </p>
  </section>
</template>
