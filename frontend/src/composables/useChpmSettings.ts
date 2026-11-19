import { computed, onScopeDispose, ref, watch } from 'vue'
import { apiFetch } from '@/services/http'
import type { NpcToolProfile } from '@/utils/npcToolProfiles'

export interface ChpmSettings {
  control_scope?: 'dialogue' | 'combat_actions'
  workflow?: 'staged' | 'integrated'
  npc_concurrency?: number
  failure_policy?: 'continue' | 'strict'
  mode: 'off' | 'shadow' | 'live'
  actor_ids: string[]
  max_active_npcs: number
  model_role: 'small' | 'complex'
  max_output_tokens: number
  max_input_chars: number
  max_calls_per_turn: number
  memory_limit: number
  agent_steps?: number
  notebook_enabled?: boolean
  action_tools?: boolean
  npc_decision_mode?: 'legacy' | 'two_phase'
  tool_protocol?: 'auto' | 'native' | 'json'
  tool_profile?: NpcToolProfile
  semantic_memory?: boolean
}

export interface RequestTiming {
  actor_id: string
  phase: string
  duration_ms: number
  queue_ms: number | null
  ttft_ms: number | null
  prefill_ms: number | null
  server_generation_ms: number | null
  cached_prompt_tokens: number | null
}

export interface AnalysisFailure {
  reason: string
  proposal_feedback: string[]
  detail?: string | null
  reply_id: string | null
  source: 'current_turn' | 'recent_turn' | 'previous_turn_snapshot'
}

export interface ChpmStatus {
  host_mode?: 'vn' | 'rpg' | 'story' | 'chat'
  module_version?: string
  continuation?: { quality: string; cooldown_remaining: number; unreviewed_turns: number; total_simplified_turns: number }
  settings: ChpmSettings
  revision: number
  available: boolean
  characters: { id: string; name: string }[]
  usage: { workflow?: 'staged' | 'integrated' | null; calls: number; input_chars: number; output_chars: number; repairs: number; proposal_repairs?: number; format_repairs?: number; proposal_feedback?: string[]; actor_failures?: Record<string, string>; status: string; detail: string; memory_evictions: number; simplified?: boolean; fallback_requests?: number; preparation_ms?: number | null; timings?: RequestTiming[] }
  last_analysis_failure?: AnalysisFailure | null
  last_proposal_failure?: AnalysisFailure | null
  trace: unknown[]
  memory_counts: Record<string, number>
  memory: Record<string, unknown[]>
  agenda_counts: { active: number; closed: number }
  agenda: unknown[]
  history_capacity?: Record<string, {
    status: 'ready' | 'warning' | 'pause_required'
    used: { events: number; evidence: number; sources: number; beliefs: number; experiences?: number }
    limits: { events: number; evidence: number; sources: number; beliefs: number; experiences?: number }
    blocking_resources: string[]
    active_events: number
    archived_events: number
    archive_blocks: number
  }>
  required_call_budget?: number
}

export function useChpmSettings(sessionId: () => string) {
  const status = ref<ChpmStatus | null>(null)
  const draft = ref<ChpmSettings | null>(null)
  const busy = ref(false)
  const error = ref('')
  const dirty = computed(() => !!status.value && JSON.stringify(draft.value) !== JSON.stringify(status.value.settings))
  const isCombatControl = computed(() => status.value?.host_mode === 'rpg')
  const minimumCalls = computed(() => {
    if (!draft.value || draft.value.mode === 'off') return 0
    const actors = Math.min(draft.value.actor_ids.length, draft.value.max_active_npcs ?? 3)
    if (isCombatControl.value) return 3 * actors * (draft.value.agent_steps ?? 0)
    return actors * (1 + (draft.value.mode === 'live' ? (draft.value.agent_steps ?? 0) : 0)) + (draft.value.mode === 'live' ? 5 : 1)
  })
  const budgetWarning = computed(() => !!draft.value && draft.value.max_calls_per_turn < minimumCalls.value)
  const historyWarnings = computed(() => isCombatControl.value || draft.value?.mode !== 'live' ? [] : draft.value.actor_ids.flatMap(id => {
    const capacity = status.value?.history_capacity?.[id]
    if (!capacity || capacity.status === 'ready') return []
    return [{ id, name: status.value?.characters.find(actor => actor.id === id)?.name ?? id, ...capacity }]
  }))
  let controller: AbortController | null = null

  function setMode(mode: ChpmSettings['mode']) {
    if (!draft.value) return
    draft.value.mode = mode
    if (mode !== 'live') delete draft.value.npc_decision_mode
  }

  function selectStandard() {
    setMode('off')
  }

  function setNotebookEnabled(enabled: boolean) {
    if (!draft.value) return
    draft.value.notebook_enabled = enabled
    if (enabled) draft.value.agent_steps = Math.max(1, draft.value.agent_steps ?? 0)
  }

  function setToolProfile(profile: NpcToolProfile) {
    if (draft.value) draft.value.tool_profile = profile
  }

  function setWorkflow(workflow: 'staged' | 'integrated') {
    if (!draft.value) return
    draft.value.workflow = workflow
    if (workflow === 'integrated') draft.value.max_input_chars = Math.max(48000, draft.value.max_input_chars)
    else if (draft.value.action_tools) setActionToolsEnabled(false)
  }

  function setActionToolsEnabled(enabled: boolean) {
    if (!draft.value) return
    draft.value.action_tools = enabled
    if (!enabled) {
      delete draft.value.npc_decision_mode
      return
    }
    setWorkflow('integrated')
    draft.value.agent_steps = Math.max(1, draft.value.agent_steps ?? 0)
  }

  async function request(saving: boolean): Promise<boolean> {
    controller?.abort()
    const current = new AbortController()
    controller = current
    busy.value = true
    error.value = ''
    try {
      const response = await apiFetch(`/adventures/${encodeURIComponent(sessionId())}/chpm`, {
        method: saving ? 'PATCH' : 'GET', signal: current.signal, timeoutMs: 15000,
        ...(saving ? { includeJson: true, body: JSON.stringify({ settings: draft.value, expected_revision: status.value?.revision }) } : {}),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'Could not save NPC behavior settings.')
      if (controller !== current) return false
      const settings = { ...data.settings, tool_profile: data.settings.tool_profile ?? 'auto' }
      status.value = { ...data, settings } as ChpmStatus
      draft.value = { ...settings, actor_ids: [...settings.actor_ids] }
      return true
    } catch (cause) {
      if (controller === current) error.value = cause instanceof Error ? cause.message : 'Could not load NPC behavior settings.'
      return false
    } finally {
      if (controller === current) busy.value = false
    }
  }

  async function load(): Promise<boolean> {
    status.value = null
    draft.value = null
    return request(false)
  }

  async function save(): Promise<boolean> {
    if (busy.value) return false
    if (isCombatControl.value && draft.value && draft.value.mode !== 'off' && (draft.value.mode !== 'live' || !draft.value.action_tools || draft.value.workflow !== 'integrated' || !(draft.value.agent_steps && draft.value.agent_steps >= 1))) {
      error.value = 'Enable combat action control with Integrated workflow and at least one tool round before saving.'
      return false
    }
    if (budgetWarning.value) {
      error.value = isCombatControl.value
        ? `Use at least ${minimumCalls.value} requests per turn to cover the selected NPCs and their combat tool rounds.`
        : `Use at least ${minimumCalls.value} requests per turn to cover perception and, in enabled mode, one proposal retry, narration repair and repeat review.`
      return false
    }
    if (!status.value || !dirty.value) return true
    return request(true)
  }

  watch(sessionId, () => { void load() }, { immediate: true })
  onScopeDispose(() => { controller?.abort(); controller = null })
  return { status, draft, busy, error, dirty, minimumCalls, budgetWarning, historyWarnings, selectStandard, setMode, setNotebookEnabled, setToolProfile, setActionToolsEnabled, setWorkflow, load, save }
}
